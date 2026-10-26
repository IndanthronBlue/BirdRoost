from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .archive_db import ArchiveDatabase
from .library import ArchiveLibrary
from .taxonomy import Taxonomy, Taxon, load_taxonomy

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
SPECIAL_DIRS = ("待复核", "已纠正", "无鸟", "非鸟动物", "风景", "已删除")


@dataclass
class ArchiveEntry:
    relative_path: str
    absolute_path: Path
    folder: str
    species_cn: str
    species_latin: str = ""
    group_id: str = ""
    batch_id: str = ""
    target_indices: tuple[int, ...] = ()
    taxonomy: Taxon | None = None
    special: str = ""
    observation_location: str = ""
    observation_time: str = ""
    status: str = ""
    error_code: str = ""
    error_message: str = ""
    group: dict = field(default_factory=dict)

    @property
    def tree_path(self) -> tuple[str, ...]:
        if self.taxonomy is not None:
            return self.taxonomy.tree_path()
        if self.special:
            return (self.special,)
        return ("未收录", self.species_cn or self.folder)

    @property
    def display_name(self) -> str:
        if self.taxonomy is not None:
            return self.taxonomy.display_name
        return self.species_cn or self.folder

    @property
    def latin_name(self) -> str:
        if self.taxonomy is not None:
            return self.taxonomy.scientific_name
        return self.species_latin

    @property
    def has_boxes(self) -> bool:
        return any(target.get("box") for target in self.group.get("targets", []))


class ArchiveIndex:
    def __init__(
        self,
        output_root: Path,
        taxonomy: Taxonomy | None = None,
    ) -> None:
        self.output_root = output_root
        self.taxonomy = taxonomy if taxonomy is not None else load_taxonomy()
        self.library = ArchiveLibrary(output_root)
        self.database = ArchiveDatabase(output_root)
        self.entries: list[ArchiveEntry] = []
        self.groups: dict[str, dict] = {}
        self.batches: list[dict] = []
        self._copy_to_group: dict[str, tuple[dict, dict]] = {}

    def refresh(self) -> list[ArchiveEntry]:
        groups = self.library.load_groups()
        self.batches = self.library.load_batches()
        self.groups = {str(group.get("group_id", "")): group for group in groups}
        self._copy_to_group = {}
        for group in groups:
            for copy in group.get("copies", []):
                relative = str(copy.get("relative_path", "")).replace("\\", "/")
                if relative:
                    self._copy_to_group[relative] = (group, copy)

        entries: list[ArchiveEntry] = []
        if not self.output_root.exists():
            self.entries = []
            return self.entries
        for folder in sorted(self.output_root.iterdir(), key=lambda path: path.name.casefold()):
            if not folder.is_dir() or folder.name == ".birdroost" or folder.name.startswith("."):
                continue
            special = folder.name if folder.name in SPECIAL_DIRS else ""
            for path in sorted(folder.rglob("*")):
                if not path.is_file() or path.suffix.casefold() not in IMAGE_SUFFIXES:
                    continue
                relative = path.relative_to(self.output_root).as_posix()
                group, copy = self._copy_to_group.get(relative, ({}, {}))
                species_cn = str(copy.get("species_cn", "") or folder.name)
                species_latin = str(copy.get("species_latin", "") or "")
                target_indices = tuple(int(value) for value in copy.get("target_indices", []))
                if not species_latin and group:
                    for target in group.get("targets", []):
                        selection = target.get("selection") or {}
                        if selection.get("species_latin"):
                            species_latin = str(selection["species_latin"])
                            break
                taxon = None
                if not special:
                    taxon = self.taxonomy.resolve(
                        scientific_name=species_latin or None,
                        name_zh=species_cn or None,
                    )
                observation = group.get("observation") or {}
                entries.append(ArchiveEntry(
                    relative_path=relative,
                    absolute_path=path,
                    folder=folder.name,
                    species_cn=species_cn,
                    species_latin=species_latin,
                    group_id=str(group.get("group_id", "")),
                    batch_id=str(group.get("batch_id", "")),
                    target_indices=target_indices,
                    taxonomy=taxon,
                    special=special,
                    observation_location=str(observation.get("location", "")),
                    observation_time=str(observation.get("time", "")),
                    status=str(group.get("status", "")),
                    error_code=str(group.get("error_code", "")),
                    error_message=str(group.get("error_message", "")),
                    group=group,
                ))
        self.entries = entries
        try:
            self.database.sync(entries, self.groups, self.batches)
        except Exception:
            # The browser must remain usable if the cache cannot be written.
            pass
        return self.entries

    def filter_entries(
        self,
        *,
        tree_path: tuple[str, ...] | None = None,
        batch_id: str | None = None,
        search: str = "",
        location: str = "",
    ) -> list[ArchiveEntry]:
        needle = search.strip().casefold()
        result = []
        for entry in self.entries:
            if tree_path is not None and entry.tree_path[:len(tree_path)] != tree_path:
                continue
            if batch_id is not None and entry.batch_id != batch_id:
                continue
            if location and entry.observation_location != location:
                continue
            if needle:
                haystack = " ".join((
                    entry.species_cn, entry.species_latin, entry.latin_name,
                    entry.relative_path, entry.display_name,
                )).casefold()
                if needle not in haystack:
                    continue
            result.append(entry)
        return result

    def locations(self, batch_id: str | None = None) -> list[str]:
        cached = self.database.locations(batch_id)
        if cached:
            return cached
        values = {
            entry.observation_location
            for entry in self.entries
            if entry.observation_location and (batch_id is None or entry.batch_id == batch_id)
        }
        return sorted(values)

    def batch_issues(self, batch_id: str) -> list[dict]:
        issues = self.database.issues(batch_id)
        if issues:
            return issues
        result = []
        for group in self.groups.values():
            if group.get("batch_id") != batch_id:
                continue
            if group.get("status") not in {"failed", "review_pending"}:
                continue
            observation = group.get("observation") or {}
            result.append({
                "group_id": group.get("group_id", ""),
                "status": group.get("status", ""),
                "source_relative_path": group.get("source_relative_path", ""),
                "observation_location": observation.get("location", ""),
                "error_message": group.get("error_message", ""),
                "copies": "；".join(
                    copy.get("relative_path", "") for copy in group.get("copies", [])
                ),
            })
        return result

    def close(self) -> None:
        self.database.close()

    def count_by_tree_path(self, entries: Iterable[ArchiveEntry] | None = None) -> dict[tuple[str, ...], int]:
        counts: dict[tuple[str, ...], int] = {}
        for entry in entries if entries is not None else self.entries:
            path = entry.tree_path
            for index in range(1, len(path) + 1):
                key = path[:index]
                counts[key] = counts.get(key, 0) + 1
        return counts
