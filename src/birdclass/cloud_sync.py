from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from qcloud_cos import CosConfig, CosS3Client

from .archiver import sha256_file
from .cloud_backup import SCHEMA_VERSION, _remote_revision, normalize_prefix
from .cloud_export import export_archive
from .cloud_state import mark_uploaded


@dataclass
class SyncReport:
    revision: int = 0
    uploaded: bool = False
    skipped: bool = False
    error: str = ""
    export_errors: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "revision": self.revision,
            "uploaded": self.uploaded,
            "skipped": self.skipped,
            "error": self.error,
            "export_errors": list(self.export_errors),
            "message": self.message,
        }


def sync_manifest(
    archive_root: Path,
    export_root: Path,
    *,
    bucket: str,
    region: str,
    endpoint: str,
    secret_id: str,
    secret_key: str,
    prefix: str,
    force: bool = False,
) -> SyncReport:
    """Export the current local state and upload only the manifest.

    Intended for corrections/deletions after the initial full upload. New
    images should still go through the normal cloud-backup upload; this path
    does not silently upload new originals.
    """
    archive_root = archive_root.expanduser().resolve()
    export_root = export_root.expanduser().resolve()
    report = SyncReport()
    exported = export_archive(archive_root, export_root)
    report.export_errors = list(exported.errors)
    manifest_path = exported.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if int(manifest.get("schema_version", 0)) != SCHEMA_VERSION:
        report.error = f"manifest schema 版本不匹配：{manifest.get('schema_version')}"
        return report
    report.revision = int(manifest.get("revision", 0) or 0)
    if exported.errors:
        report.error = f"本地导出有 {len(exported.errors)} 个错误，已停止同步"
        return report
    bucket = bucket.strip()
    region = region.strip()
    if not bucket or not region or not secret_id or not secret_key:
        report.error = "COS 配置不完整"
        return report
    client = CosS3Client(CosConfig(
        Region=region,
        SecretId=secret_id,
        SecretKey=secret_key,
        Scheme="https",
        Endpoint=endpoint or None,
    ))
    prefix = normalize_prefix(prefix)
    key = f"users/{prefix}/manifest.json"
    remote_revision = _remote_revision(client, bucket, key)
    base_revision = int(manifest.get("base_revision", 0) or 0)
    if not force and remote_revision is not None and remote_revision > base_revision:
        report.error = (
            f"云端 manifest revision={remote_revision} 高于本地基线={base_revision}；"
            "请先处理云端冲突"
        )
        return report
    try:
        client.upload_file(
            Bucket=bucket,
            Key=key,
            LocalFilePath=str(manifest_path),
            PartSize=1,
            MAXThread=3,
            EnableMD5=False,
            Metadata={"x-cos-meta-sha256": sha256_file(manifest_path)},
        )
    except Exception as exc:
        report.error = f"manifest 上传失败：{exc}"
        return report
    report.uploaded = True
    report.message = "云端 manifest 已更新"
    mark_uploaded(archive_root, report.revision)
    return report
