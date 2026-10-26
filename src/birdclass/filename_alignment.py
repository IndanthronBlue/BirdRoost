from __future__ import annotations

import re
from pathlib import Path

from .archiver import sanitize_species_directory
from .library import ArchiveLibrary, LibraryError

SPECIAL_FOLDERS = {"待复核", "已纠正", "无鸟", "非鸟动物", "风景", "已删除"}


def _safe(value: str, fallback: str) -> str:
    return sanitize_species_directory(str(value or "").strip(), fallback)


def _old_prefix(observation: dict, species: str) -> str:
    old_location = str(observation.get("legacy_location", "") or "").strip()
    old_time = str(observation.get("legacy_time", "") or "").strip()
    if old_location and old_time:
        return f"{_safe(old_location, 'unknown')}_{_safe(old_time, 'unknown')}_{_safe(species, 'species')}_"
    if old_location:
        return f"{_safe(old_location, 'unknown')}_{_safe(species, 'species')}_"
    if old_time:
        return f"{_safe(old_time, 'unknown')}_{_safe(species, 'species')}_"
    return ""


def desired_prefix(observation: dict, species: str) -> str:
    location = str(observation.get("location", "") or "").strip()
    time = str(observation.get("time", "") or "").strip()
    parts = []
    if location:
        parts.append(_safe(location, "unknown"))
    if time:
        parts.append(_safe(time, "unknown"))
    if not parts:
        return ""
    parts.append(_safe(species, "species"))
    return "_".join(parts) + "_"


def _sequence(old_stem: str, old_prefix: str) -> str:
    if old_prefix and old_stem.startswith(old_prefix):
        remainder = old_stem[len(old_prefix):]
        match = re.fullmatch(r"(\d{1,4})", remainder)
        if match:
            return match.group(1)
    match = re.search(r"_(\d{1,4})$", old_stem)
    if match:
        return match.group(1)
    return "001"


def align_group_copies(
    library: ArchiveLibrary,
    group: dict,
    *,
    reserved: set[str] | None = None,
    dry_run: bool = False,
) -> list[tuple[str, str]]:
    """Rename non-special copies to `<location>_<time>_<species>_<seq>`.

    group JSON remains the source of truth; this function updates copy paths in
    the in-memory group and returns old/new relative paths. The caller writes it.
    """
    observation = group.get("observation") or {}
    copies = group.get("copies", [])
    output = library.output_root.resolve()
    reserved = set(reserved or ())
    changes: list[tuple[str, str]] = []
    for copy in copies:
        if copy.get("pending"):
            continue
        relative = str(copy.get("relative_path", "") or "").replace("\\", "/")
        old = (output / relative).resolve()
        if not old.is_file():
            continue
        try:
            relative_to_root = old.relative_to(output)
        except ValueError:
            continue
        if relative_to_root.parts and relative_to_root.parts[0] in SPECIAL_FOLDERS:
            continue
        species = str(copy.get("species_cn", "") or old.parent.name)
        prefix = desired_prefix(observation, species)
        if not prefix:
            continue
        if old.name.startswith(prefix):
            continue
        old_prefix = _old_prefix(observation, species)
        sequence = _sequence(old.stem, old_prefix)
        candidate = old.with_name(f"{prefix}{sequence}{old.suffix}")
        number = int(sequence) if sequence.isdigit() else 1
        while candidate.exists() or str(candidate.relative_to(output)) in reserved:
            number += 1
            candidate = old.with_name(f"{prefix}{number:03d}{old.suffix}")
        new_relative = candidate.relative_to(output).as_posix()
        if not dry_run:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            old.rename(candidate)
            copy["relative_path"] = new_relative
        reserved.add(new_relative)
        changes.append((relative, new_relative))
    return changes


def align_all_filenames(library: ArchiveLibrary, *, dry_run: bool = False) -> dict[str, int]:
    groups = library.load_groups()
    reserved: set[str] = set()
    renamed = 0
    changed_groups = 0
    errors = 0
    for group in groups:
        try:
            changes = align_group_copies(library, group, reserved=reserved, dry_run=dry_run)
        except (OSError, LibraryError):
            errors += 1
            continue
        if changes:
            changed_groups += 1
            renamed += len(changes)
            if not dry_run:
                library.write_group(group)
    return {
        "groups": changed_groups,
        "files": renamed,
        "errors": errors,
        "total_groups": len(groups),
    }
