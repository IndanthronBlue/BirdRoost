from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .archiver import sanitize_species_directory
from .history import CsvHistory
from .library import ArchiveLibrary, ImageGeometry, new_batch_id, new_group_id, now_iso

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
PENDING_PREFIX = ("待复核",)


@dataclass
class PendingMigrationResult:
    renamed: int = 0
    groups_created: int = 0
    skipped: int = 0
    batch_id: str = ""
    errors: list[str] = field(default_factory=list)


def _prefix(location: str, observed_at: str) -> str:
    if not location.strip() or not observed_at.strip():
        return ""
    return (
        f"{sanitize_species_directory(location, '未知地点')}_"
        f"{sanitize_species_directory(observed_at, '未知时间')}_"
    )


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成唯一文件名：{path}")


def _move_with_prefix(path: Path, prefix: str) -> Path:
    if not prefix or path.name.startswith(prefix):
        return path
    target = _unique(path.with_name(prefix + path.name))
    shutil.move(str(path), str(target))
    return target


def _pending_files(output_root: Path) -> list[Path]:
    root = output_root / "待复核"
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES
    )


def _base_name(name: str) -> str:
    return name.replace("_待确认框", "")


def _event_map(csv_paths: list[Path]) -> dict[str, object]:
    events: dict[str, object] = {}
    for csv_path in csv_paths:
        try:
            loaded = CsvHistory(csv_path).load()
        except Exception:
            continue
        for event in loaded.values():
            name = Path(event.identity.relative_path).name
            current = events.get(name)
            if current is None or event.updated_at > current.updated_at:
                events[name] = event
    return events


def _find_event(name: str, events: dict[str, object]):
    base = _base_name(name)
    if base in events:
        return events[base]
    for event_name, event in events.items():
        if base == event_name or base.endswith("_" + event_name):
            return event
    return None


def migrate_pending_copies(
    output_root: Path, csv_paths: list[Path]
) -> PendingMigrationResult:
    library = ArchiveLibrary(output_root)
    library.ensure()
    result = PendingMigrationResult(batch_id=new_batch_id())
    groups = library.load_groups()
    group_by_copy = {
        str(copy.get("relative_path", "")).replace("\\", "/"): group
        for group in groups
        for copy in group.get("copies", [])
    }
    events = _event_map(csv_paths)
    assigned: set[str] = set()

    # Existing groups: rename their pending copies using group observation.
    for group in groups:
        pending = [
            copy for copy in group.get("copies", [])
            if copy.get("pending") or str(copy.get("relative_path", "")).startswith("待复核/")
        ]
        if not pending:
            continue
        observation = group.get("observation") or {}
        location = str(observation.get("location", ""))
        observed_at = str(observation.get("time", ""))
        if not location or not observed_at:
            event = _find_event(
                str(group.get("source_relative_path") or ""), events
            )
            if event is not None:
                location = event.observation_location
                observed_at = event.observation_time
                group["observation"] = {"location": location, "time": observed_at}
        prefix = _prefix(location, observed_at)
        if not prefix:
            result.skipped += len(pending)
            continue
        for copy in pending:
            relative = str(copy.get("relative_path", ""))
            old = output_root / relative
            if not old.is_file():
                continue
            new = _move_with_prefix(old, prefix)
            new_relative = new.relative_to(output_root).as_posix()
            if new_relative != relative:
                copy["relative_path"] = new_relative
                result.renamed += 1
            assigned.add(new_relative)
        library.write_group(group)

    # Orphan pending files: create a group from the matching CSV event.
    for path in _pending_files(output_root):
        relative = path.relative_to(output_root).as_posix()
        if relative in assigned:
            continue
        existing = group_by_copy.get(relative)
        if existing is not None:
            assigned.add(relative)
            continue
        event = _find_event(path.name, events)
        if event is None:
            result.skipped += 1
            continue
        location = event.observation_location
        observed_at = event.observation_time
        prefix = _prefix(location, observed_at)
        if not prefix:
            result.skipped += 1
            continue
        matched = [
            candidate for candidate in _pending_files(output_root)
            if _base_name(candidate.name).endswith(
                "_" + Path(event.identity.relative_path).name
            )
            or _base_name(candidate.name) == Path(event.identity.relative_path).name
        ]
        if not matched:
            matched = [path]
        copies = []
        for candidate in matched:
            rel = candidate.relative_to(output_root).as_posix()
            if rel in assigned:
                continue
            moved = _move_with_prefix(candidate, prefix)
            new_relative = moved.relative_to(output_root).as_posix()
            copies.append({
                "relative_path": new_relative,
                "species_cn": "",
                "species_latin": "",
                "target_indices": [],
                "pending": True,
            })
            assigned.add(new_relative)
            result.renamed += 1
        if not copies:
            continue
        try:
            geometry = ImageGeometry.from_path(output_root / copies[0]["relative_path"])
        except OSError:
            result.skipped += 1
            continue
        group = {
            "schema_version": 1,
            "group_id": new_group_id(),
            "batch_id": result.batch_id,
            "created_at": now_iso(),
            "status": event.status if event.status in {"failed", "review_pending"} else "review_pending",
            "source_relative_path": event.identity.relative_path,
            "observation": {"location": location, "time": observed_at},
            "image": geometry.to_dict(),
            "targets": [],
            "copies": copies,
            "error_code": event.error_code,
            "error_message": event.error_message,
            "imported_from_csv": "pending migration",
        }
        library.write_group(group)
        result.groups_created += 1

    library.write_batch({
        "schema_version": 1,
        "batch_id": result.batch_id,
        "started_at": now_iso(),
        "finished_at": now_iso(),
        "output_root": str(output_root),
        "groups": [],
        "summary": {
            "total": result.renamed,
            "completed": 0,
            "failed": 0,
            "deferred": result.groups_created,
        },
        "imported_from_csv": "pending migration",
    })
    return result
