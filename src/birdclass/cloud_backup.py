from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from qcloud_cos import CosConfig, CosS3Client

from .cloud_export import SCHEMA_VERSION
from .cloud_state import mark_uploaded

PREFIX_PATTERN = re.compile(r"[^\w.-]+")
ProgressCallback = Callable[[int, int, str], None]
PreparedCallback = Callable[[int, int, bool], None]
AUTH_ERROR_CODES = {
    "SignatureDoesNotMatch",
    "InvalidAccessKeyId",
    "InvalidSecretId",
    "RequestTimeTooSkewed",
}


@dataclass
class UploadItem:
    key: str
    local_path: Path
    size: int
    sha256: str
    kind: str


@dataclass
class UploadPlan:
    bucket: str
    region: str
    prefix: str
    endpoint: str = ""
    library_id: str = ""
    device_id: str = ""
    revision: int = 0
    base_revision: int = 0
    archive_root: Path | None = None
    items: list[UploadItem] = field(default_factory=list)
    manifest_path: Path | None = None
    manifest_key: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.items)


@dataclass
class UploadReport:
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_uploaded: int = 0
    cancelled: bool = False
    snapshot_path: str = ""
    used_remote_index: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "uploaded": self.uploaded,
            "skipped": self.skipped,
            "failed": self.failed,
            "bytes_uploaded": self.bytes_uploaded,
            "cancelled": self.cancelled,
            "snapshot_path": self.snapshot_path,
            "used_remote_index": self.used_remote_index,
            "errors": list(self.errors),
        }


def normalize_prefix(value: str) -> str:
    cleaned = PREFIX_PATTERN.sub("_", value.strip().strip("/"))[:80].strip("._-")
    return cleaned or "default"


def build_upload_plan(
    export_root: Path,
    *,
    bucket: str,
    region: str,
    prefix: str,
    endpoint: str = "",
) -> UploadPlan:
    export_root = export_root.expanduser().resolve()
    manifest_path = export_root / "manifest.json"
    plan = UploadPlan(
        bucket=bucket.strip(),
        region=region.strip(),
        prefix=normalize_prefix(prefix),
        endpoint=endpoint.strip(),
        manifest_path=manifest_path,
        manifest_key=f"users/{normalize_prefix(prefix)}/manifest.json",
    )
    if not manifest_path.is_file():
        plan.errors.append(f"manifest 不存在：{manifest_path}")
        return plan
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        plan.errors.append(f"manifest 无法读取：{exc}")
        return plan
    if not isinstance(manifest, dict):
        plan.errors.append("manifest 格式错误")
        return plan
    if int(manifest.get("schema_version", 0)) != SCHEMA_VERSION:
        plan.errors.append(f"manifest schema 版本不匹配：{manifest.get('schema_version')}")
        return plan

    source_root = Path(str(manifest.get("source_root", ""))).expanduser().resolve()
    plan.archive_root = source_root
    plan.library_id = str(manifest.get("library_id", ""))
    plan.device_id = str(manifest.get("device_id", ""))
    plan.revision = int(manifest.get("revision", 0) or 0)
    plan.base_revision = int(manifest.get("base_revision", 0) or 0)
    copies = manifest.get("copies", [])
    source_by_photo: dict[str, Path] = {}
    for copy in copies:
        photo_id = str(copy.get("photo_id", ""))
        relative = str(copy.get("local_relative_path", ""))
        if not photo_id or not relative:
            continue
        candidate = (source_root / relative).resolve()
        try:
            candidate.relative_to(source_root)
        except ValueError:
            continue
        if candidate.is_file() and photo_id not in source_by_photo:
            source_by_photo[photo_id] = candidate

    for photo in manifest.get("photos", []):
        photo_id = str(photo.get("photo_id", ""))
        source = source_by_photo.get(photo_id)
        if source is None:
            plan.errors.append(f"找不到原图：{photo_id}")
            continue
        plan.items.append(UploadItem(
            key=f"users/{plan.prefix}/{photo['original_object_key']}",
            local_path=source,
            size=int(photo.get("bytes", source.stat().st_size)),
            sha256=str(photo.get("sha256", photo_id)),
            kind="original",
        ))
        for variant in photo.get("variants", []):
            local = export_root / str(variant.get("object_key", ""))
            if local.is_file():
                plan.items.append(UploadItem(
                    key=f"users/{plan.prefix}/{variant['object_key']}",
                    local_path=local,
                    size=int(variant.get("bytes", local.stat().st_size)),
                    sha256=str(photo.get("sha256", photo_id)),
                    kind=str(variant.get("kind", "thumbnail")),
                ))
    from .archiver import sha256_file

    plan.items.append(UploadItem(
        key=plan.manifest_key,
        local_path=manifest_path,
        size=manifest_path.stat().st_size,
        sha256=sha256_file(manifest_path),
        kind="manifest",
    ))
    return plan


def _head_matches(client: CosS3Client, bucket: str, key: str, size: int, sha256: str = "") -> bool:
    try:
        response = client.head_object(Bucket=bucket, Key=key)
    except Exception:
        return False
    try:
        if int(response.get("Content-Length", -1)) != size:
            return False
    except (TypeError, ValueError):
        return False
    if sha256:
        metadata = response.get("Metadata") or {}
        remote_sha = response.get("x-cos-meta-sha256") or metadata.get("x-cos-meta-sha256")
        if remote_sha and str(remote_sha) != sha256:
            return False
    return True


def _is_not_found(exc: Exception) -> bool:
    code = getattr(exc, "get_status_code", lambda: None)()
    error_code = str(getattr(exc, "get_error_code", lambda: "")())
    return code == 404 or error_code in {"NoSuchKey", "NoSuchBucket"}


def _access_auth_error(client: CosS3Client, bucket: str, key: str) -> str:
    """Return a readable error only for credential/signature failures.

    A missing manifest is normal on the first upload. Other errors (for
    example a subaccount without ListBucket) should not block the upload;
    the per-object HEAD/upload path can still succeed.
    """
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        error_code = str(getattr(exc, "get_error_code", lambda: "")())
        if error_code in AUTH_ERROR_CODES:
            return f"{error_code}：{exc}"
    return ""


def _remote_revision(client: CosS3Client, bucket: str, key: str) -> int | None:
    if not hasattr(client, "download_file"):
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="birdroost-manifest-") as directory:
            target = Path(directory) / "manifest.json"
            client.download_file(Bucket=bucket, Key=key, DestFilePath=str(target))
            if not target.is_file():
                return None
            data = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            return int(data.get("revision", 0) or 0)
    except Exception:
        return None


def _remote_object_index(client: CosS3Client, bucket: str, prefix: str) -> dict[str, int] | None:
    if not hasattr(client, "list_objects"):
        return None
    result: dict[str, int] = {}
    marker = ""
    try:
        while True:
            response = client.list_objects(
                Bucket=bucket, Prefix=prefix, Marker=marker, MaxKeys=1000,
            )
            contents = response.get("Contents", []) or []
            for item in contents:
                try:
                    result[str(item["Key"])] = int(item.get("Size", -1))
                except (KeyError, TypeError, ValueError):
                    continue
            if str(response.get("IsTruncated", "")).lower() != "true":
                break
            marker = str(response.get("NextMarker", "") or "")
            if not marker and contents:
                marker = str(contents[-1].get("Key", ""))
            if not marker:
                break
        return result
    except Exception:
        return None


def save_conflict_snapshot(
    client: CosS3Client,
    bucket: str,
    key: str,
    archive_root: Path | None,
    revision: int | None,
) -> str:
    if archive_root is None:
        return ""
    directory = archive_root / ".birdroost" / "cloud_conflicts"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = directory / f"manifest-r{revision if revision is not None else 'unknown'}-{stamp}.json"
    try:
        client.download_file(Bucket=bucket, Key=key, DestFilePath=str(path))
        return str(path)
    except Exception:
        return ""


def upload_plan(
    plan: UploadPlan,
    *,
    secret_id: str,
    secret_key: str,
    token: str = "",
    progress: ProgressCallback | None = None,
    prepared: PreparedCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
    force: bool = False,
) -> UploadReport:
    report = UploadReport()
    if plan.errors:
        report.errors.extend(plan.errors)
        report.failed += len(plan.errors)
        return report
    if not plan.bucket or not plan.region:
        report.errors.append("bucket 和 region 不能为空")
        report.failed += 1
        return report
    if not secret_id or not secret_key:
        report.errors.append("缺少 SecretId / SecretKey")
        report.failed += 1
        return report

    config = CosConfig(
        Region=plan.region,
        SecretId=secret_id,
        SecretKey=secret_key,
        Token=token or None,
        Scheme="https",
        Endpoint=plan.endpoint or None,
    )
    client = CosS3Client(config)
    remote_revision = _remote_revision(client, plan.bucket, plan.manifest_key)
    if (
        not force
        and remote_revision is not None
        and remote_revision > plan.base_revision
    ):
        report.failed += 1
        report.snapshot_path = save_conflict_snapshot(
            client, plan.bucket, plan.manifest_key, plan.archive_root, remote_revision
        )
        snapshot = f"；云端快照：{report.snapshot_path}" if report.snapshot_path else ""
        report.errors.append(
            f"云端 manifest revision={remote_revision} 高于本地基线={plan.base_revision}；"
            f"请先拉取云端最新内容或确认冲突后再上传{snapshot}"
        )
        return report
    remote_index = _remote_object_index(client, plan.bucket, f"users/{plan.prefix}/")
    report.used_remote_index = remote_index is not None
    total = len(plan.items)
    if remote_index is None:
        auth_error = _access_auth_error(client, plan.bucket, plan.manifest_key)
        if auth_error:
            report.failed += 1
            report.errors.append(
                "COS 凭证校验失败，未上传任何对象。"
                "请在“配置…”中重新填写 SecretId / SecretKey。"
                f"（{auth_error}）"
            )
            return report
    if prepared is not None:
        missing = total if remote_index is None else sum(
            1 for item in plan.items if remote_index.get(item.key) != item.size
        )
        prepared(total, missing, remote_index is not None)
    done = 0
    uploaded_bytes = 0
    for item in plan.items:
        if cancelled is not None and cancelled():
            report.cancelled = True
            report.errors.append("用户取消上传；下次会跳过已上传对象继续")
            break
        if item.kind == "manifest" and report.failed:
            report.errors.append("存在失败项，未上传 manifest")
            done += 1
            continue
        if not item.local_path.is_file():
            report.failed += 1
            report.errors.append(f"文件不存在：{item.local_path}")
            done += 1
            continue
        if (
            item.kind != "manifest"
            and remote_index is not None
            and remote_index.get(item.key) == item.size
        ):
            report.skipped += 1
            done += 1
            if progress:
                progress(done, total, item.key)
            continue
        if _head_matches(client, plan.bucket, item.key, item.size, item.sha256):
            report.skipped += 1
            done += 1
            if progress:
                progress(done, total, item.key)
            continue
        last_error = None
        for attempt in range(3):
            try:
                client.upload_file(
                    Bucket=plan.bucket,
                    Key=item.key,
                    LocalFilePath=str(item.local_path),
                    PartSize=1,
                    MAXThread=3,
                    EnableMD5=False,
                    Metadata={"x-cos-meta-sha256": item.sha256} if item.sha256 else {},
                )
                report.uploaded += 1
                uploaded_bytes += item.size
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if _is_not_found(exc):
                    break
                time.sleep(0.5 * (attempt + 1))
        if last_error is not None:
            report.failed += 1
            report.errors.append(f"{item.key}: {last_error}")
        done += 1
        if progress:
            progress(done, total, item.key)
    report.bytes_uploaded = uploaded_bytes
    if (
        plan.archive_root is not None
        and plan.revision
        and report.failed == 0
        and not report.cancelled
    ):
        mark_uploaded(plan.archive_root, plan.revision)
    return report


@dataclass
class ConnectionReport:
    ok: bool = False
    bucket_reachable: bool = False
    manifest_exists: bool = False
    write_ok: bool = False
    messages: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "bucket_reachable": self.bucket_reachable,
            "manifest_exists": self.manifest_exists,
            "write_ok": self.write_ok,
            "messages": list(self.messages),
            "error": self.error,
        }


def test_connection(
    *,
    bucket: str,
    region: str,
    secret_id: str,
    secret_key: str,
    prefix: str = "",
    endpoint: str = "",
    write_test: bool = True,
) -> ConnectionReport:
    """Check credentials and optional write permission without leaving an object."""
    report = ConnectionReport()
    bucket = bucket.strip()
    region = region.strip()
    if not bucket or not region:
        report.error = "bucket 和 region 不能为空"
        return report
    if not secret_id or not secret_key:
        report.error = "缺少 SecretId / SecretKey"
        return report
    try:
        config = CosConfig(
            Region=region,
            SecretId=secret_id,
            SecretKey=secret_key,
            Scheme="https",
            Endpoint=endpoint.strip() or None,
        )
        client = CosS3Client(config)
    except Exception as exc:
        report.error = f"初始化 COS 客户端失败：{exc}"
        return report

    try:
        client.head_bucket(Bucket=bucket)
        report.bucket_reachable = True
        report.messages.append("桶可访问")
    except Exception as exc:
        report.messages.append(f"HeadBucket 检查未通过：{exc}")

    manifest_key = f"users/{normalize_prefix(prefix)}/manifest.json"
    try:
        client.head_object(Bucket=bucket, Key=manifest_key)
        report.manifest_exists = True
        report.messages.append("已找到云端 manifest")
    except Exception as exc:
        code = str(getattr(exc, "get_error_code", lambda: "")())
        if code in {"NoSuchKey", "404"}:
            report.messages.append("桶可访问；云端尚无 manifest（首次上传时会创建）")
        else:
            report.messages.append(f"manifest 读取检查未通过：{exc}")

    if write_test:
        probe = f"users/{normalize_prefix(prefix)}/.birdroost-connection-test"
        try:
            client.put_object(Bucket=bucket, Key=probe, Body=b"birdroost-connection-test")
            report.write_ok = True
            report.messages.append("写入测试成功")
        except Exception as exc:
            report.error = f"写入测试失败：{exc}"
            report.messages.append(report.error)
        finally:
            try:
                client.delete_object(Bucket=bucket, Key=probe)
            except Exception:
                pass

    report.ok = (report.bucket_reachable or report.manifest_exists) and (report.write_ok or not write_test)
    if not report.ok and not report.error:
        report.error = "连接检查未通过，请确认桶名、地域、Endpoint 和子账号权限"
    return report
