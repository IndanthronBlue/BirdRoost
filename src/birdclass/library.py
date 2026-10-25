from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from .coordinates import display_size as oriented_display_size
from .coordinates import image_orientation
from .errors import LibraryError

LIBRARY_DIRNAME = ".birdroost"
LIBRARY_SCHEMA_VERSION = 1
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_group_id() -> str:
    return str(uuid.uuid4())


def new_batch_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class ImageGeometry:
    source_size: tuple[int, int]
    display_size: tuple[int, int]
    exif_orientation: int
    upload_size: tuple[int, int] | None
    upload_was_compressed: bool
    upload_oriented: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_size": list(self.source_size),
            "display_size": list(self.display_size),
            "exif_orientation": self.exif_orientation,
            "upload_size": list(self.upload_size) if self.upload_size else None,
            "upload_was_compressed": self.upload_was_compressed,
            "upload_oriented": self.upload_oriented,
            "coordinate_space": "display_oriented_normalized",
        }

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        upload_size: tuple[int, int] | None = None,
        upload_was_compressed: bool = False,
        upload_oriented: bool = False,
    ) -> "ImageGeometry":
        with Image.open(path) as image:
            source_size = image.size
        orientation = image_orientation(path)
        return cls(
            source_size=source_size,
            display_size=oriented_display_size(source_size, orientation),
            exif_orientation=orientation,
            upload_size=upload_size,
            upload_was_compressed=upload_was_compressed,
            upload_oriented=upload_oriented,
        )


def _validate_id(value: str, label: str) -> str:
    if not _ID_PATTERN.fullmatch(str(value)):
        raise LibraryError(f"{label} 不是有效的库标识：{value!r}")
    return str(value)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".birdroost-",
            suffix=".json",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise LibraryError(f"写入归档库失败：{exc}") from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError, TypeError) as exc:
        raise LibraryError(f"读取归档库失败：{path.name}：{exc}") from exc
    if not isinstance(value, dict):
        raise LibraryError(f"归档库文件不是对象：{path.name}")
    return value


class ArchiveLibrary:
    """Sidecar data stored under <output>/.birdroost."""

    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root
        self.root = output_root / LIBRARY_DIRNAME
        self.groups_dir = self.root / "groups"
        self.batches_dir = self.root / "batches"
        self.library_path = self.root / "library.json"
        self.corrections_path = self.root / "corrections.jsonl"
        self.index_path = self.root / "index.sqlite"

    def ensure(self, taxonomy_version: str = "") -> None:
        try:
            self.groups_dir.mkdir(parents=True, exist_ok=True)
            self.batches_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LibraryError(f"无法创建归档库目录：{exc}") from exc
        if not self.library_path.exists():
            _write_json(self.library_path, {
                "schema_version": LIBRARY_SCHEMA_VERSION,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "taxonomy": {
                    "source": "IOC World Bird List",
                    "version": taxonomy_version,
                },
            })
        else:
            try:
                data = _read_json(self.library_path)
                if taxonomy_version and data.get("taxonomy", {}).get("version") != taxonomy_version:
                    data.setdefault("taxonomy", {})["version"] = taxonomy_version
                    data["updated_at"] = now_iso()
                    _write_json(self.library_path, data)
            except LibraryError:
                # A corrupt library manifest should not prevent archiving.
                _write_json(self.library_path, {
                    "schema_version": LIBRARY_SCHEMA_VERSION,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "taxonomy": {
                        "source": "IOC World Bird List",
                        "version": taxonomy_version,
                    },
                })

    def _group_path(self, group_id: str) -> Path:
        return self.groups_dir / f"{_validate_id(group_id, 'group_id')}.json"

    def _batch_path(self, batch_id: str) -> Path:
        return self.batches_dir / f"{_validate_id(batch_id, 'batch_id')}.json"

    def write_group(self, group: dict[str, Any]) -> Path:
        group_id = _validate_id(str(group.get("group_id", "")), "group_id")
        if not group.get("created_at"):
            group = {**group, "created_at": now_iso()}
        path = self._group_path(group_id)
        _write_json(path, group)
        return path

    def read_group(self, group_id: str) -> dict[str, Any]:
        return _read_json(self._group_path(group_id))

    def write_batch(self, batch: dict[str, Any]) -> Path:
        batch_id = _validate_id(str(batch.get("batch_id", "")), "batch_id")
        if not batch.get("started_at"):
            batch = {**batch, "started_at": now_iso()}
        path = self._batch_path(batch_id)
        _write_json(path, batch)
        return path

    def read_batch(self, batch_id: str) -> dict[str, Any]:
        return _read_json(self._batch_path(batch_id))

    def append_correction(self, record: dict[str, Any]) -> Path:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.corrections_path.open("a", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise LibraryError(f"写入纠错记录失败：{exc}") from exc
        return self.corrections_path

    def load_groups(self, *, strict: bool = False) -> list[dict[str, Any]]:
        if not self.groups_dir.exists():
            return []
        groups: list[dict[str, Any]] = []
        for path in sorted(self.groups_dir.glob("*.json")):
            try:
                groups.append(_read_json(path))
            except LibraryError:
                if strict:
                    raise
        return groups

    def load_batches(self, *, strict: bool = False) -> list[dict[str, Any]]:
        if not self.batches_dir.exists():
            return []
        batches: list[dict[str, Any]] = []
        for path in sorted(self.batches_dir.glob("*.json")):
            try:
                batches.append(_read_json(path))
            except LibraryError:
                if strict:
                    raise
        return batches

    def load_corrections(self) -> list[dict[str, Any]]:
        if not self.corrections_path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            with self.corrections_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        value = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(value, dict):
                        records.append(value)
        except OSError as exc:
            raise LibraryError(f"读取纠错记录失败：{exc}") from exc
        return records

    def find_group_for_copy(self, relative_path: str) -> dict[str, Any] | None:
        target = relative_path.replace("\\", "/")
        for group in self.load_groups():
            for copy in group.get("copies", []):
                if str(copy.get("relative_path", "")).replace("\\", "/") == target:
                    return group
        return None
