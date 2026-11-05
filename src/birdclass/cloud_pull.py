from __future__ import annotations

import json
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .cloud_export import copy_id
from .cloud_restore import download_manifest, restore_from_cos
from .cloud_state import load_state, save_state
from .library import ArchiveLibrary

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class PullReport:
    action: str = "up_to_date"  # up_to_date | pulled | conflict | error
    local_revision: int = 0
    remote_revision: int = 0
    downloaded: int = 0
    skipped: int = 0
    groups: int = 0
    copies: int = 0
    removed_groups: int = 0
    tombstones_applied: int = 0
    errors: list[str] = field(default_factory=list)
    snapshot_path: str = ""
    dirty: bool = False

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "local_revision": self.local_revision,
            "remote_revision": self.remote_revision,
            "downloaded": self.downloaded,
            "skipped": self.skipped,
            "groups": self.groups,
            "copies": self.copies,
            "removed_groups": self.removed_groups,
            "tombstones_applied": self.tombstones_applied,
            "errors": list(self.errors),
            "snapshot_path": self.snapshot_path,
            "dirty": self.dirty,
        }


def _snapshot(archive_root: Path, manifest: dict) -> str:
    directory = archive_root / ".birdroost" / "cloud_conflicts"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = directory / f"remote-pull-r{manifest.get('revision', 'unknown')}-{stamp}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def _backup_local_groups(archive_root: Path) -> str:
    source = archive_root / ".birdroost" / "groups"
    directory = archive_root / ".birdroost" / "cloud_conflicts"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = directory / f"local-before-pull-{stamp}"
    if source.is_dir():
        shutil.copytree(source, target)
    return str(target)


def _remove_local_group(library: ArchiveLibrary, group: dict, stamp: str) -> int:
    removed = 0
    deleted_root = library.output_root / "已删除" / f"cloud-pull-{stamp}"
    for copy in group.get("copies", []):
        relative = str(copy.get("relative_path", ""))
        if not relative:
            continue
        source = (library.output_root / relative).resolve()
        try:
            source.relative_to(library.output_root)
        except ValueError:
            continue
        if source.is_file():
            target = deleted_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            removed += 1
    group_path = library.groups_dir / f"{group.get('group_id')}.json"
    group_path.unlink(missing_ok=True)
    return removed


def _apply_local_tombstones(
    library: ArchiveLibrary, tombstone_ids: set[str], stamp: str,
) -> int:
    applied = 0
    for group in library.load_groups():
        group_id = str(group.get("group_id", ""))
        kept = []
        changed = False
        for copy in group.get("copies", []):
            identifier = copy_id(
                group_id,
                str(copy.get("species_cn", "")),
                copy.get("target_indices", []),
            )
            if identifier not in tombstone_ids:
                kept.append(copy)
                continue
            changed = True
            applied += 1
            relative = str(copy.get("relative_path", ""))
            if relative:
                source = (library.output_root / relative).resolve()
                try:
                    source.relative_to(library.output_root)
                except ValueError:
                    source = None
                if source is not None and source.is_file():
                    target = library.output_root / "已删除" / f"cloud-pull-{stamp}" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(target))
        if changed:
            group["copies"] = kept
            if not kept:
                group["status"] = "deleted"
            library.write_group(group)
    return applied


def pull_from_cos(
    archive_root: Path,
    *,
    bucket: str,
    region: str,
    endpoint: str,
    secret_id: str,
    secret_key: str,
    prefix: str,
    force: bool = False,
    progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> PullReport:
    """Fast-forward a clean local library from the remote manifest.

    Local uncommitted changes are never overwritten unless force=True. The
    remote manifest is authoritative after a successful fast-forward.
    """
    archive_root = archive_root.expanduser().resolve()
    library = ArchiveLibrary(archive_root)
    library.ensure()
    state = load_state(archive_root)
    report = PullReport(local_revision=state.revision, dirty=state.dirty)
    with tempfile.TemporaryDirectory(prefix="birdroost-pull-") as directory:
        manifest_path = Path(directory) / "manifest.json"
        manifest = download_manifest(
            bucket=bucket,
            region=region,
            endpoint=endpoint,
            secret_id=secret_id,
            secret_key=secret_key,
            prefix=prefix,
            destination=manifest_path,
        )
    report.remote_revision = int(manifest.get("revision", 0) or 0)
    if report.remote_revision <= state.base_revision:
        report.action = "up_to_date"
        return report
    if state.dirty and not force:
        report.snapshot_path = _snapshot(archive_root, manifest)
        report.action = "conflict"
        report.errors.append("本地有未推送修改，已停止拉取；云端快照已保存")
        return report
    if force:
        report.snapshot_path = _snapshot(archive_root, manifest)
        _backup_local_groups(archive_root)

    old_revision = state.revision
    old_base = state.base_revision
    old_dirty = state.dirty
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tombstone_ids = {
        str(value.get("id", "")) for value in manifest.get("tombstones", [])
        if value.get("entity") == "copy"
    }
    report.tombstones_applied = _apply_local_tombstones(library, tombstone_ids, stamp)

    restored = restore_from_cos(
        archive_root,
        manifest,
        bucket=bucket,
        region=region,
        endpoint=endpoint,
        secret_id=secret_id,
        secret_key=secret_key,
        prefix=prefix,
        progress=progress,
        cancelled=cancelled,
    )
    report.downloaded = restored.restored
    report.skipped = restored.skipped
    report.groups = restored.groups
    report.copies = restored.copies
    report.errors.extend(restored.errors)

    remote_group_ids = {
        str(group.get("group_id", "")) for group in manifest.get("groups", [])
    }
    for group in library.load_groups():
        group_id = str(group.get("group_id", ""))
        if group_id not in remote_group_ids:
            _remove_local_group(library, group, stamp)
            report.removed_groups += 1

    if restored.cancelled:
        report.errors.append("拉取已取消")
    if report.errors or restored.failed or restored.cancelled:
        state = load_state(archive_root)
        state.revision = old_revision
        state.base_revision = old_base
        state.dirty = old_dirty
        save_state(archive_root, state)
        report.action = "error"
        return report
    report.action = "pulled"
    return report
