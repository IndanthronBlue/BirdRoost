from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from qcloud_cos import CosConfig, CosS3Client

from .cloud_export import SCHEMA_VERSION

PREFIX_PATTERN = re.compile(r"[^\w.-]+")
ProgressCallback = Callable[[int, int, str], None]


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
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "uploaded": self.uploaded,
            "skipped": self.skipped,
            "failed": self.failed,
            "bytes_uploaded": self.bytes_uploaded,
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
    plan.items.append(UploadItem(
        key=plan.manifest_key,
        local_path=manifest_path,
        size=manifest_path.stat().st_size,
        sha256="",
        kind="manifest",
    ))
    return plan


def _head_size(client: CosS3Client, bucket: str, key: str) -> int | None:
    try:
        response = client.head_object(Bucket=bucket, Key=key)
    except Exception:
        return None
    try:
        return int(response.get("Content-Length", -1))
    except (TypeError, ValueError):
        return -1


def _is_not_found(exc: Exception) -> bool:
    code = getattr(exc, "get_status_code", lambda: None)()
    error_code = str(getattr(exc, "get_error_code", lambda: "")())
    return code == 404 or error_code in {"NoSuchKey", "NoSuchBucket"}


def upload_plan(
    plan: UploadPlan,
    *,
    secret_id: str,
    secret_key: str,
    token: str = "",
    progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
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
    total = len(plan.items)
    done = 0
    uploaded_bytes = 0
    for item in plan.items:
        if cancelled is not None and cancelled():
            report.errors.append("用户取消上传")
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
        existing = _head_size(client, plan.bucket, item.key)
        if existing is not None and existing == item.size:
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
    return report
