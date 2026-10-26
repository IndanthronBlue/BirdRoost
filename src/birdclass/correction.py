from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .archive_index import ArchiveEntry
from .archiver import sanitize_species_directory
from .manual_review import cleanup_resolved_pending
from .errors import LibraryError
from .library import ArchiveLibrary, now_iso
from .metadata import write_species_metadata
from .taxonomy import Taxon



class CorrectionError(Exception):
    pass


@dataclass(frozen=True)
class CorrectionOutcome:
    old_relative_path: str
    new_relative_path: str
    replaced_relative_path: str
    split: bool
    group_id: str


def _new_species_folder(taxon: Taxon, new_name: str | None = None) -> str:
    if new_name and new_name.strip():
        return sanitize_species_directory(new_name.strip(), "manual")
    return taxon.name_zh or taxon.name_en or taxon.scientific_name


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(2, 10_000):
        candidate = path.with_name(f"{stem}_{index:03d}{suffix}")
        if not candidate.exists():
            return candidate
    raise CorrectionError(f"无法为新文件生成唯一名称：{path.name}")


def _new_filename(entry: ArchiveEntry, new_folder: str) -> str:
    stem = Path(entry.relative_path).stem
    suffix = Path(entry.relative_path).suffix
    old_names = [entry.species_cn, entry.folder]
    replaced = stem
    for old_name in sorted({name for name in old_names if name}, key=len, reverse=True):
        if old_name in replaced:
            replaced = replaced.replace(old_name, new_folder, 1)
            break
    else:
        replaced = f"{new_folder}_{stem}"
    return f"{replaced}{suffix}"


def correct_archive_copy(
    library: ArchiveLibrary,
    entry: ArchiveEntry,
    taxon: Taxon,
    *,
    target_indices: set[int] | None = None,
    new_name: str | None = None,
    reason: str = "manual correction",
) -> CorrectionOutcome:
    output_root = library.output_root.resolve()
    old_path = (output_root / entry.relative_path).resolve()
    if not old_path.is_file():
        raise CorrectionError(f"归档副本不存在：{entry.relative_path}")
    new_folder = _new_species_folder(taxon, new_name)
    new_path = _unique_path(output_root / new_folder / _new_filename(entry, new_folder))
    new_relative = new_path.relative_to(output_root).as_posix()
    current_name = entry.species_cn or entry.folder
    if (
        entry.taxonomy is not None
        and entry.taxonomy.scientific_name == taxon.scientific_name
        and new_folder == current_name
    ):
        raise CorrectionError("新分类与当前分类相同")

    copy_target_indices = set(entry.target_indices)
    selected = copy_target_indices if target_indices is None else set(target_indices)
    split = bool(selected) and selected < copy_target_indices

    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        if split:
            shutil.copy2(old_path, new_path)
        else:
            shutil.move(str(old_path), str(new_path))
        write_species_metadata(new_path, new_folder)
    except Exception as exc:
        if not split and not old_path.exists() and new_path.exists():
            # The move succeeded but metadata failed: attempt a rollback.
            try:
                shutil.move(str(new_path), str(old_path))
            except OSError:
                pass
        new_path.unlink(missing_ok=True)
        raise CorrectionError(f"创建纠正副本失败：{exc}") from exc

    replaced_relative = ""
    old_moved = not split
    try:
        group = None
        if entry.group_id:
            group = library.read_group(entry.group_id)
            copies = group.setdefault("copies", [])
            copy_record = next(
                (copy for copy in copies if copy.get("relative_path") == entry.relative_path),
                None,
            )
            if copy_record is None:
                copy_record = {
                    "relative_path": entry.relative_path,
                    "species_cn": entry.species_cn,
                    "species_latin": entry.species_latin,
                    "target_indices": sorted(copy_target_indices),
                }
                copies.append(copy_record)
            if split:
                remaining = sorted(copy_target_indices - selected)
                copy_record["target_indices"] = remaining
                copies.append({
                    "relative_path": new_relative,
                    "species_cn": new_folder,
                    "species_latin": taxon.scientific_name,
                    "target_indices": sorted(selected),
                })
            else:
                copy_record["relative_path"] = new_relative
                copy_record["species_cn"] = new_folder
                copy_record["species_latin"] = taxon.scientific_name
            for target in group.get("targets", []):
                if int(target.get("target_index", -1)) not in selected:
                    continue
                selection = dict(target.get("selection") or {})
                selection["species_cn"] = new_folder
                selection["species_latin"] = taxon.scientific_name
                selection["selection_mode"] = "manual"
                target["selection"] = selection
            library.write_group(group)
            cleanup_resolved_pending(library, group["group_id"])

        library.append_correction({
            "corrected_at": now_iso(),
            "group_id": entry.group_id,
            "old_species_cn": entry.species_cn,
            "new_species_cn": new_folder,
            "new_species_latin": taxon.scientific_name,
            "old_relative_path": entry.relative_path,
            "new_relative_path": new_relative,
            "mode": "split" if split else "move",
            "old_copy_action": "kept" if split else "moved",
            "replaced_relative_path": replaced_relative,
            "target_indices": sorted(selected),
            "reason": reason,
        })
    except Exception as exc:
        if old_moved:
            try:
                old_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(new_path), str(old_path))
            except OSError:
                pass
        else:
            new_path.unlink(missing_ok=True)
        if isinstance(exc, (CorrectionError, LibraryError)):
            raise
        raise CorrectionError(f"更新归档库失败：{exc}") from exc

    return CorrectionOutcome(
        old_relative_path=entry.relative_path,
        new_relative_path=new_relative,
        replaced_relative_path=replaced_relative,
        split=split,
        group_id=entry.group_id,
    )
