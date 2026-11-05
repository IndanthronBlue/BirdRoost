from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from qcloud_cos import CosConfig, CosS3Client

from .cloud_backup import normalize_prefix
from .cloud_export import export_archive


@dataclass
class CleanupReport:
    dry_run: bool = True
    retention_days: int = 30
    tombstones: int = 0
    candidates: int = 0
    existing: int = 0
    missing: int = 0
    deleted: int = 0
    bytes_deleted: int = 0
    skipped_referenced: int = 0
    skipped_young: int = 0
    skipped_no_key: int = 0
    errors: list[str] = field(default_factory=list)
    objects: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "retention_days": self.retention_days,
            "tombstones": self.tombstones,
            "candidates": self.candidates,
            "existing": self.existing,
            "missing": self.missing,
            "deleted": self.deleted,
            "bytes_deleted": self.bytes_deleted,
            "skipped_referenced": self.skipped_referenced,
            "skipped_young": self.skipped_young,
            "skipped_no_key": self.skipped_no_key,
            "errors": list(self.errors),
            "objects": list(self.objects),
        }


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def _safe_key(key: str) -> bool:
    key = str(key)
    return key.startswith("originals/") or key.startswith("thumbs/")


def cleanup_tombstones(
    archive_root: Path,
    export_root: Path,
    *,
    bucket: str,
    region: str,
    endpoint: str,
    secret_id: str,
    secret_key: str,
    prefix: str,
    retention_days: int = 30,
    dry_run: bool = True,
    now: datetime | None = None,
) -> CleanupReport:
    """Delete cloud objects for old tombstones that are no longer referenced.

    Safety rules:
    - never delete an object still referenced by a current manifest photo;
    - require the tombstone to carry object keys (new tombstones do);
    - default retention window;
    - only touch users/<prefix>/(originals|thumbs)/.
    """
    archive_root = archive_root.expanduser().resolve()
    export_root = export_root.expanduser().resolve()
    report = CleanupReport(dry_run=dry_run, retention_days=retention_days)
    exported = export_archive(archive_root, export_root)
    if exported.errors:
        report.errors.extend(exported.errors)
        return report
    manifest = json.loads(exported.manifest_path.read_text(encoding="utf-8"))
    current_photo_ids = {
        str(photo.get("photo_id", "")) for photo in manifest.get("photos", [])
    }
    current_keys: set[str] = set()
    for photo in manifest.get("photos", []):
        if photo.get("original_object_key"):
            current_keys.add(str(photo["original_object_key"]))
        for variant in photo.get("variants", []):
            if variant.get("object_key"):
                current_keys.add(str(variant["object_key"]))
    prefix = normalize_prefix(prefix)
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(0, int(retention_days)))
    candidates: dict[str, int] = {}
    for tombstone in manifest.get("tombstones", []):
        report.tombstones += 1
        photo_id = str(tombstone.get("photo_id", ""))
        if photo_id and photo_id in current_photo_ids:
            report.skipped_referenced += 1
            continue
        deleted_at = _parse_time(str(tombstone.get("deleted_at", "")))
        if deleted_at is None or deleted_at > cutoff:
            report.skipped_young += 1
            continue
        keys = [
            str(tombstone.get("original_object_key", "")),
            *[str(key) for key in tombstone.get("thumbnail_keys", [])],
        ]
        keys = [key for key in keys if key]
        if not keys:
            report.skipped_no_key += 1
            continue
        for key in keys:
            if not _safe_key(key):
                report.errors.append(f"拒绝删除非图库对象：{key}")
                continue
            if key in current_keys:
                report.skipped_referenced += 1
                continue
            candidates[key] = 0
    report.candidates = len(candidates)
    if not candidates:
        return report
    client = CosS3Client(CosConfig(
        Region=region,
        SecretId=secret_id,
        SecretKey=secret_key,
        Scheme="https",
        Endpoint=endpoint or None,
    ))
    object_key_prefix = f"users/{prefix}/"
    for key in sorted(candidates):
        full_key = object_key_prefix + key
        try:
            response = client.head_object(Bucket=bucket, Key=full_key)
            size = int(response.get("Content-Length", 0) or 0)
        except Exception:
            report.missing += 1
            continue
        report.existing += 1
        report.objects.append({"key": full_key, "bytes": size})
        candidates[key] = size
    if dry_run:
        return report
    for key, size in sorted(candidates.items()):
        if not _safe_key(key):
            continue
        full_key = object_key_prefix + key
        try:
            client.delete_object(Bucket=bucket, Key=full_key)
            report.deleted += 1
            report.bytes_deleted += size
        except Exception as exc:
            report.errors.append(f"删除失败：{full_key}：{exc}")
    return report
