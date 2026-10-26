from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from .archive_index import ArchiveEntry
from .archiver import sanitize_species_directory
from .library import ArchiveLibrary, ImageGeometry, new_group_id, now_iso
from .metadata import write_species_metadata
from .taxonomy import load_taxonomy

NO_BIRD_DIR = "无鸟"
NON_BIRD_DIR = "非鸟动物"
SCENERY_DIR = "风景"
SPECIAL_ACTIONS = {
    "no_bird": (NO_BIRD_DIR, "no_bird"),
    "non_bird_animal": (NON_BIRD_DIR, "non_bird_animal"),
    "scenery": (SCENERY_DIR, "scenery"),
}


class ManualReviewError(Exception):
    pass


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ManualReviewError(f"无法生成唯一文件名：{path.name}")


def _pending_copies(group: dict) -> list[dict]:
    return [
        copy for copy in group.get("copies", [])
        if copy.get("pending") or str(copy.get("relative_path", "")).startswith("待复核/")
    ]


def _source_copy(copies: list[dict]) -> dict:
    return next(
        (copy for copy in copies if "_待确认框" not in str(copy.get("relative_path", ""))),
        copies[0],
    )


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _ensure_group(library: ArchiveLibrary, entry: ArchiveEntry) -> dict:
    if entry.group_id:
        return library.read_group(entry.group_id)
    path = library.output_root / entry.relative_path
    try:
        geometry = ImageGeometry.from_path(path)
    except OSError as exc:
        raise ManualReviewError(f"无法读取待复核图片：{exc}") from exc
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": "",
        "created_at": now_iso(),
        "status": "failed",
        "source_relative_path": entry.relative_path,
        "observation": {
            "location": entry.observation_location,
            "time": entry.observation_time,
        },
        "image": geometry.to_dict(),
        "targets": [],
        "copies": [{
            "relative_path": entry.relative_path,
            "species_cn": "",
            "species_latin": "",
            "target_indices": [],
            "pending": True,
        }],
        "error_code": "",
        "error_message": "",
    }
    library.write_group(group)
    entry.group_id = group["group_id"]
    entry.group = group
    return group


def resolve_manual(
    library: ArchiveLibrary,
    entry: ArchiveEntry,
    *,
    action: str,
    name: str = "",
    observation_location: str = "",
    observation_time: str = "",
) -> str:
    """Resolve a pending/failed group as manual species or no-bird.

    Returns the new relative path (or an empty string for no-bird).
    """
    if action != "manual" and action not in SPECIAL_ACTIONS:
        raise ManualReviewError("未知的人工复核操作")
    group = _ensure_group(library, entry)
    copies = group.get("copies", [])
    pending = _pending_copies(group)
    if not pending:
        raise ManualReviewError("该 group 没有待复核副本")
    output = library.output_root.resolve()
    source_rel = _source_copy(pending)
    source = output / str(source_rel["relative_path"])
    if not source.is_file():
        raise ManualReviewError(f"待复核副本不存在：{source_rel['relative_path']}")

    stamp = _stamp()
    new_relative = ""
    if action == "manual":
        name = " ".join(name.split())
        if not name:
            raise ManualReviewError("人工鸟名不能为空")
        folder = sanitize_species_directory(name, "manual")
        filename = source.name
        location = " ".join(observation_location.split())
        observed_at = " ".join(observation_time.split())
        if location and observed_at:
            prefix = (
                f"{sanitize_species_directory(location, '未知地点')}_"
                f"{sanitize_species_directory(observed_at, '未知时间')}_"
            )
            if not filename.startswith(prefix):
                filename = f"{prefix}{filename}"
        new_path = _unique_path(output / folder / filename)
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(new_path))
            write_species_metadata(new_path, name)
        except Exception as exc:
            if not source.exists() and new_path.exists():
                try:
                    shutil.move(str(new_path), str(source))
                except OSError:
                    pass
            new_path.unlink(missing_ok=True)
            raise ManualReviewError(f"创建人工归档副本失败：{exc}") from exc
        new_relative = new_path.relative_to(output).as_posix()
        taxon = load_taxonomy().resolve(name_zh=name)
        target_indices = sorted({
            int(index)
            for copy in pending
            for index in copy.get("target_indices", [])
        })
        targets = group.setdefault("targets", [])
        if not targets:
            targets.append({
                "target_index": 0,
                "box": None,
                "box_upload": None,
                "candidates": [],
                "selection": None,
            })
            target_indices = [0]
        if not target_indices:
            target_indices = [int(target.get("target_index", 0)) for target in targets]
        for target in targets:
            if int(target.get("target_index", -1)) not in target_indices:
                continue
            target["selection"] = {
                "species_cn": name,
                "species_latin": taxon.scientific_name if taxon else "",
                "selection_mode": "manual",
                "review_reason": "manual_review",
            }
        group["copies"] = [
            copy for copy in copies if copy not in pending
        ] + [{
            "relative_path": new_relative,
            "species_cn": name,
            "species_latin": taxon.scientific_name if taxon else "",
            "target_indices": target_indices,
        }]
        group["observation"] = {
            "location": observation_location or group.get("observation", {}).get("location", ""),
            "time": observation_time or group.get("observation", {}).get("time", ""),
        }
        group["status"] = "completed"
        group["error_code"] = ""
        group["error_message"] = ""
        library.write_group(group)
        # The source pending copy was moved into the species folder. Any
        # remaining annotated preview is redundant; remove it instead of
        # creating another copy under 已纠正/.
        for copy in pending:
            old = output / str(copy.get("relative_path", ""))
            if old != source and old.is_file():
                old.unlink(missing_ok=True)
        library.append_correction({
            "corrected_at": now_iso(),
            "group_id": entry.group_id,
            "action": "manual_archive",
            "new_species_cn": name,
            "old_relative_paths": [copy.get("relative_path", "") for copy in pending],
            "new_relative_path": new_relative,
        })
        return new_relative

    # no_bird / non_bird_animal / scenery
    folder, status = SPECIAL_ACTIONS[action]
    special_root = output / folder / stamp
    new_copies = []
    for copy in pending:
        old = output / str(copy.get("relative_path", ""))
        if not old.is_file():
            continue
        destination = special_root / str(copy.get("relative_path", ""))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(destination))
        new_copies.append({
            "relative_path": destination.relative_to(output).as_posix(),
            "species_cn": "",
            "species_latin": "",
            "target_indices": copy.get("target_indices", []),
            status: True,
        })
    group["copies"] = [copy for copy in copies if copy not in pending] + new_copies
    group["observation"] = {
        "location": observation_location or group.get("observation", {}).get("location", ""),
        "time": observation_time or group.get("observation", {}).get("time", ""),
    }
    group["status"] = status
    group["error_code"] = ""
    group["error_message"] = ""
    library.write_group(group)
    library.append_correction({
        "corrected_at": now_iso(),
        "group_id": entry.group_id,
        "action": action,
        "old_relative_paths": [copy.get("relative_path", "") for copy in pending],
    })
    return ""


DELETED_DIR = "已删除"


def delete_archive_photo(library: ArchiveLibrary, entry: ArchiveEntry) -> str:
    """Soft-delete one archived copy into 已删除/ and remove it from its group."""
    output = library.output_root.resolve()
    old = (output / entry.relative_path).resolve()
    if not old.is_file():
        raise ManualReviewError(f"归档副本不存在：{entry.relative_path}")
    stamp = _stamp()
    destination = output / DELETED_DIR / stamp / entry.relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old), str(destination))
    if entry.group_id:
        group = library.read_group(entry.group_id)
        copies = [
            copy for copy in group.get("copies", [])
            if str(copy.get("relative_path", "")).replace("\\", "/") != entry.relative_path
        ]
        group["copies"] = copies
        if not copies:
            group["status"] = "deleted"
        library.write_group(group)
    library.append_correction({
        "corrected_at": now_iso(),
        "group_id": entry.group_id,
        "action": "delete_photo",
        "old_relative_paths": [entry.relative_path],
        "new_relative_path": destination.relative_to(output).as_posix(),
    })
    return destination.relative_to(output).as_posix()


def mark_already_classified(library: ArchiveLibrary, entry: ArchiveEntry) -> None:
    """Remove pending copies after user confirms the photo was already handled."""
    group = _ensure_group(library, entry)
    pending = _pending_copies(group)
    if not pending:
        raise ManualReviewError("该 group 没有待复核副本")
    output = library.output_root.resolve()
    stamp = _stamp()
    for copy in pending:
        old = output / str(copy.get("relative_path", ""))
        if not old.is_file():
            continue
        destination = output / DELETED_DIR / stamp / str(copy.get("relative_path", ""))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(destination))
    group["copies"] = [copy for copy in group.get("copies", []) if copy not in pending]
    group["status"] = "completed" if group["copies"] else "already_classified"
    group["error_code"] = ""
    group["error_message"] = ""
    library.write_group(group)
    library.append_correction({
        "corrected_at": now_iso(),
        "group_id": entry.group_id,
        "action": "already_classified",
        "old_relative_paths": [copy.get("relative_path", "") for copy in pending],
    })
