from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .coordinates import image_orientation, upload_box_to_display
from .history import CsvHistory
from .library import (
    ArchiveLibrary,
    ImageGeometry,
    new_batch_id,
    new_group_id,
    now_iso,
)
from .taxonomy import TAXONOMY_VERSION


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0
    batch_id: str = ""
    groups: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _json_value(value: str) -> dict:
    if not value:
        return {}
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}


def _existing_destinations(event, output_root: Path) -> list[str]:
    destinations: list[str] = []
    if event.archive_payload:
        try:
            for value in _json_value(event.archive_payload).get("selections", []):
                destination = str(value.get("destination_path", "")).replace("\\", "/")
                if destination:
                    destinations.append(destination)
        except (ValueError, TypeError):
            pass
    if not destinations and event.destination_path:
        destinations = [
            value.replace("\\", "/")
            for value in event.destination_path.split("；")
            if value
        ]
    return [
        destination for destination in dict.fromkeys(destinations)
        if (output_root / destination).is_file()
    ]


def _copy_records(event, destinations: list[str], output_root: Path) -> list[dict]:
    records: list[dict] = []
    by_path: dict[str, dict] = {}
    if event.archive_payload:
        try:
            for value in _json_value(event.archive_payload).get("selections", []):
                destination = str(value.get("destination_path", "")).replace("\\", "/")
                if destination not in destinations:
                    continue
                candidate = value.get("candidate") or {}
                record = {
                    "relative_path": destination,
                    "species_cn": candidate.get("name_cn") or event.species_cn,
                    "species_latin": candidate.get("name_latin") or event.species_latin,
                    "target_indices": list(value.get("source_targets", [])),
                }
                records.append(record)
                by_path[destination] = record
        except (ValueError, TypeError):
            pass
    for destination in destinations:
        if destination not in by_path:
            records.append({
                "relative_path": destination,
                "species_cn": event.species_cn.split("、")[0] if event.species_cn else "",
                "species_latin": event.species_latin.split("、")[0] if event.species_latin else "",
                "target_indices": [],
            })
    return records


def _target_records(event, geometry: ImageGeometry) -> list[dict]:
    if not event.detection_payload:
        return []
    try:
        payload = _json_value(event.detection_payload)
    except (ValueError, TypeError):
        return []
    records: list[dict] = []
    for target in payload.get("targets", []):
        raw_box = target.get("box")
        box = None
        if raw_box is not None:
            box = upload_box_to_display(
                tuple(float(value) for value in raw_box),
                orientation=geometry.exif_orientation,
                upload_oriented=geometry.upload_oriented,
            )
        records.append({
            "target_index": int(target.get("target_index", len(records))),
            "box": list(box) if box is not None else None,
            "box_upload": list(raw_box) if raw_box is not None else None,
            "candidates": target.get("candidates", []),
            "selection": target.get("selection"),
        })
    return records


def import_csv_to_library(csv_path: Path, output_root: Path) -> ImportResult:
    csv_path = Path(csv_path)
    output_root = Path(output_root)
    library = ArchiveLibrary(output_root)
    library.ensure(taxonomy_version=TAXONOMY_VERSION)
    events = CsvHistory(csv_path).load()
    batch_id = new_batch_id()
    result = ImportResult(batch_id=batch_id)
    existing_copies = {
        str(copy.get("relative_path", "")).replace("\\", "/")
        for group in library.load_groups()
        for copy in group.get("copies", [])
    }
    for event in events.values():
        if event.status not in {"completed", "review_pending", "failed"}:
            result.skipped += 1
            continue
        destinations = _existing_destinations(event, output_root)
        if not destinations or any(destination in existing_copies for destination in destinations):
            result.skipped += 1
            continue
        first = output_root / destinations[0]
        try:
            orientation = image_orientation(first)
            geometry = ImageGeometry.from_path(
                first,
                upload_size=None,
                upload_was_compressed=event.upload_was_compressed,
                upload_oriented=event.upload_was_compressed or orientation == 1,
            )
            copies = _copy_records(event, destinations, output_root)
            group = {
                "schema_version": 1,
                "group_id": new_group_id(),
                "batch_id": batch_id,
                "created_at": now_iso(),
                "status": event.status,
                "source_relative_path": event.identity.relative_path,
                "observation": {
                    "location": event.observation_location,
                    "time": event.observation_time,
                },
                "image": geometry.to_dict(),
                "targets": _target_records(event, geometry),
                "copies": copies,
                "result_id": event.result_id,
                "imported_from_csv": csv_path.name,
            }
            library.write_group(group)
            existing_copies.update(copy["relative_path"] for copy in copies)
            result.groups.append(group["group_id"])
            result.imported += 1
        except (OSError, ValueError, TypeError, KeyError) as exc:
            result.errors.append(f"{event.identity.relative_path}: {exc}")
            result.skipped += 1
    library.write_batch({
        "schema_version": 1,
        "batch_id": batch_id,
        "started_at": now_iso(),
        "finished_at": now_iso(),
        "source_dir": str(csv_path.parent),
        "output_root": str(output_root),
        "groups": result.groups,
        "summary": {
            "total": result.imported + result.skipped,
            "completed": result.imported,
            "failed": 0,
            "deferred": 0,
        },
        "imported_from_csv": str(csv_path),
    })
    return result
