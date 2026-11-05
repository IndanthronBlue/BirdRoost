from __future__ import annotations

import json
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from qcloud_cos import CosConfig, CosS3Client

from .archiver import sha256_file
from .cloud_export import SCHEMA_VERSION
from .cloud_backup import normalize_prefix
from .cloud_state import load_state, save_state
from .library import ArchiveLibrary, now_iso

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class RestoreReport:
    groups: int = 0
    copies: int = 0
    photos: int = 0
    restored: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False

    def to_dict(self) -> dict:
        return {
            "groups": self.groups,
            "copies": self.copies,
            "photos": self.photos,
            "restored": self.restored,
            "skipped": self.skipped,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "errors": list(self.errors),
        }


def _safe_path(root: Path, relative: str, fallback: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return (root / fallback).resolve()
    return candidate


def download_manifest(
    *,
    bucket: str,
    region: str,
    endpoint: str,
    secret_id: str,
    secret_key: str,
    prefix: str,
    destination: Path,
) -> dict:
    client = CosS3Client(CosConfig(
        Region=region,
        SecretId=secret_id,
        SecretKey=secret_key,
        Scheme="https",
        Endpoint=endpoint or None,
    ))
    key = f"users/{normalize_prefix(prefix)}/manifest.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(Bucket=bucket, Key=key, DestFilePath=str(destination))
    data = json.loads(destination.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest 格式错误")
    if int(data.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError(f"manifest schema 版本不支持：{data.get('schema_version')}")
    return data


def restore_from_cos(
    local_root: Path,
    manifest: dict,
    *,
    bucket: str,
    region: str,
    endpoint: str,
    secret_id: str,
    secret_key: str,
    prefix: str,
    progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> RestoreReport:
    report = RestoreReport()
    local_root = local_root.expanduser().resolve()
    library = ArchiveLibrary(local_root)
    library.ensure()
    client = CosS3Client(CosConfig(
        Region=region,
        SecretId=secret_id,
        SecretKey=secret_key,
        Scheme="https",
        Endpoint=endpoint or None,
    ))
    prefix = normalize_prefix(prefix)
    tombstones = {
        str(value.get("id", "")) for value in manifest.get("tombstones", [])
        if value.get("entity") == "copy"
    }
    photos = {str(photo.get("photo_id", "")): photo for photo in manifest.get("photos", [])}
    copies = manifest.get("copies", [])
    groups = manifest.get("groups", [])
    total = len(photos)
    done = 0
    photos_done: set[str] = set()
    photo_paths: dict[str, Path] = {}

    def download_photo(photo_id: str, target: Path) -> bool:
        photo = photos.get(photo_id)
        if photo is None:
            report.errors.append(f"找不到 photo：{photo_id}")
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            try:
                if sha256_file(target) == str(photo.get("sha256", "")):
                    report.skipped += 1
                    return True
            except OSError:
                pass
        temp = target.with_name(target.name + ".part")
        try:
            temp.unlink(missing_ok=True)
            client.download_file(
                Bucket=bucket,
                Key=f"users/{prefix}/{photo['original_object_key']}",
                DestFilePath=str(temp),
            )
            if sha256_file(temp) != str(photo.get("sha256", "")):
                temp.unlink(missing_ok=True)
                report.errors.append(f"哈希校验失败：{photo_id}")
                return False
            temp.replace(target)
            report.restored += 1
            return True
        except Exception as exc:
            temp.unlink(missing_ok=True)
            report.errors.append(f"下载失败：{photo_id}：{exc}")
            return False

    for group in groups:
        if cancelled is not None and cancelled():
            report.cancelled = True
            break
        group_id = str(group.get("group_id", ""))
        group_copies = [
            copy for copy in copies
            if str(copy.get("group_id", "")) == group_id
            and str(copy.get("copy_id", "")) not in tombstones
        ]
        local_copies = []
        for copy in group_copies:
            if cancelled is not None and cancelled():
                report.cancelled = True
                break
            photo_id = str(copy.get("photo_id", ""))
            species = str(copy.get("species_cn", "") or "未收录")
            relative = str(copy.get("local_relative_path", ""))
            if not relative:
                relative = f"{species}/{photo_id[:12]}.jpg"
            target = _safe_path(local_root, relative, f"{species}/{photo_id[:12]}.jpg")
            if photo_id not in photos_done:
                if not download_photo(photo_id, target):
                    report.failed += 1
                    continue
                photos_done.add(photo_id)
                photo_paths[photo_id] = target
                done += 1
                if progress:
                    progress(done, total, photo_id)
            elif not target.is_file():
                # Another copy of the same photo: copy local bytes.
                first = photo_paths.get(photo_id)
                if first is not None and first != target:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(first, target)
                elif first is None:
                    report.failed += 1
                    continue
            local_copies.append({
                "relative_path": target.relative_to(local_root).as_posix(),
                "species_cn": species,
                "species_latin": str(copy.get("species_latin", "")),
                "target_indices": [int(v) for v in copy.get("target_indices", [])],
            })
        if not local_copies:
            continue
        library.write_group({
            "schema_version": 1,
            "group_id": group_id,
            "batch_id": str(group.get("batch_id", "")),
            "created_at": now_iso(),
            "status": str(group.get("status", "completed")),
            "source_relative_path": str(group.get("source_relative_path", "")),
            "observation": group.get("observation", {}),
            "targets": group.get("targets", []),
            "copies": local_copies,
            "cloud_restored": True,
        })
        report.groups += 1
        report.copies += len(local_copies)

    state = load_state(local_root)
    state.library_id = str(manifest.get("library_id", state.library_id))
    state.revision = int(manifest.get("revision", state.revision) or state.revision)
    state.base_revision = state.revision
    state.dirty = False
    state.tombstones = list(manifest.get("tombstones", []))
    save_state(local_root, state)
    report.photos = len(photos_done)
    return report
