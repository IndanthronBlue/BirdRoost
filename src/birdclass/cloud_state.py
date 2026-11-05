from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_FILENAME = "cloud_state.json"


@dataclass
class CloudState:
    library_id: str = ""
    device_id: str = ""
    revision: int = 0
    base_revision: int = 0
    dirty: bool = True
    tombstones: list[dict[str, Any]] = field(default_factory=list)
    last_uploaded_at: str = ""

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "library_id": self.library_id,
            "device_id": self.device_id,
            "revision": self.revision,
            "base_revision": self.base_revision,
            "dirty": self.dirty,
            "tombstones": self.tombstones,
            "last_uploaded_at": self.last_uploaded_at,
        }


def _path(archive_root: Path) -> Path:
    return archive_root / ".birdroost" / STATE_FILENAME


def load_state(archive_root: Path) -> CloudState:
    path = _path(archive_root)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}
    state = CloudState(
        library_id=str(data.get("library_id", "") or ""),
        device_id=str(data.get("device_id", "") or ""),
        revision=int(data.get("revision", 0) or 0),
        base_revision=int(data.get("base_revision", 0) or 0),
        dirty=bool(data.get("dirty", True)),
        tombstones=list(data.get("tombstones", []) or []),
        last_uploaded_at=str(data.get("last_uploaded_at", "") or ""),
    )
    if not state.library_id:
        state.library_id = str(uuid.uuid4())
    if not state.device_id:
        state.device_id = str(uuid.uuid4())
    return state


def save_state(archive_root: Path, state: CloudState) -> Path:
    path = _path(archive_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def prepare_export_state(archive_root: Path, *, increment: bool = True) -> CloudState:
    state = load_state(archive_root)
    if increment:
        state.revision += 1
    state.dirty = False
    save_state(archive_root, state)
    return state


def mark_dirty(archive_root: Path) -> None:
    state = load_state(archive_root)
    state.dirty = True
    save_state(archive_root, state)


def mark_uploaded(archive_root: Path, revision: int) -> None:
    state = load_state(archive_root)
    state.revision = max(state.revision, int(revision))
    state.base_revision = int(revision)
    state.last_uploaded_at = datetime.now(timezone.utc).isoformat()
    save_state(archive_root, state)


def add_tombstone(
    archive_root: Path,
    *,
    group_id: str,
    species_cn: str,
    target_indices: tuple[int, ...] | list[int],
    local_relative_path: str,
) -> None:
    from .cloud_export import copy_id

    state = load_state(archive_root)
    identifier = copy_id(group_id, species_cn, target_indices)
    entry = {
        "entity": "copy",
        "id": identifier,
        "group_id": group_id,
        "local_relative_path": local_relative_path,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    }
    state.tombstones = [
        value for value in state.tombstones
        if not (value.get("entity") == "copy" and value.get("id") == identifier)
    ]
    state.tombstones.append(entry)
    state.dirty = True
    save_state(archive_root, state)
