from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from pathlib import Path

from .errors import HistoryError
from .models import FileIdentity, HistoryEvent, ImageItem

HEADERS_V1 = [
    "schema_version", "event_id", "relative_path", "file_size", "file_mtime_ns",
    "status", "classified_at", "class_code", "area_code", "result_id",
    "species_id", "species_cn", "species_en", "species_latin", "confidence_percent",
    "animal_class", "destination_path", "selection_mode", "review_reason",
    "low_confidence_threshold", "ambiguity_delta_threshold", "reviewed_at",
    "candidate_payload", "upload_was_compressed", "upload_bytes", "error_code",
    "error_message", "updated_at",
]
HEADERS_V2 = [*HEADERS_V1, "detection_payload", "archive_payload"]
HEADERS_V3 = [*HEADERS_V2, "observation_location", "observation_time"]
HEADERS = [*HEADERS_V3, "observation_country", "observation_region"]
CURRENT_SCHEMA_VERSION = 4


class CsvHistory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._events: dict[FileIdentity, HistoryEvent] | None = None

    def load(self) -> dict[FileIdentity, HistoryEvent]:
        events: dict[FileIdentity, HistoryEvent] = {}
        if not self.path.exists():
            self._events = events
            return events
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames not in (HEADERS_V1, HEADERS_V2, HEADERS_V3, HEADERS):
                    raise HistoryError("CSV 表头缺失或与当前版本不一致，请先备份并修复")
                for line_number, row in enumerate(reader, start=2):
                    try:
                        event = self._from_row(row)
                        if not 1 <= event.schema_version <= CURRENT_SCHEMA_VERSION:
                            raise HistoryError("CSV schema 版本高于或不兼容当前程序")
                        if event.status == "review_pending":
                            if event.schema_version == 1:
                                payload = json.loads(event.candidate_payload)
                                valid = isinstance(payload, list) and bool(payload)
                            else:
                                payload = json.loads(event.detection_payload)
                                valid = isinstance(payload, dict) and isinstance(payload.get("targets"), list)
                            if not valid:
                                raise ValueError("empty or invalid candidates")
                        events[event.identity] = event
                    except HistoryError:
                        raise
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                        raise HistoryError(f"CSV 第 {line_number} 行或候选快照损坏") from exc
        except HistoryError:
            raise
        except (OSError, UnicodeError, csv.Error) as exc:
            raise HistoryError(f"无法读取 CSV：{exc}") from exc
        self._events = events
        return events

    def append(self, event: HistoryEvent) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            needs_header = not self.path.exists() or self.path.stat().st_size == 0
            if not needs_header:
                self._migrate_legacy_header_if_needed()
            with self.path.open("a", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="raise")
                if needs_header:
                    writer.writeheader()
                writer.writerow(self._to_row(event))
                handle.flush()
                os.fsync(handle.fileno())
        except (OSError, UnicodeError, csv.Error) as exc:
            raise HistoryError(f"无法写入 CSV：{exc}") from exc
        if self._events is not None:
            self._events[event.identity] = event

    def _migrate_legacy_header_if_needed(self) -> None:
        temporary_name: str | None = None
        version = 0
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames == HEADERS_V1:
                    version = 1
                elif reader.fieldnames == HEADERS_V2:
                    version = 2
                elif reader.fieldnames == HEADERS_V3:
                    version = 3
                else:
                    return
                old_headers = reader.fieldnames
                rows = list(reader)
            backup = self.path.with_suffix(f".v{version}.bak")
            if not backup.exists():
                shutil.copy2(self.path, backup)
            with tempfile.NamedTemporaryFile(
                prefix=".birdclass-history-", dir=self.path.parent, delete=False
            ) as temporary:
                temporary_name = temporary.name
            added_headers = HEADERS[len(old_headers):]
            with open(temporary_name, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="raise")
                writer.writeheader()
                for row in rows:
                    writer.writerow({**row, **{key: "" for key in added_headers}})
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        except (OSError, UnicodeError, csv.Error) as exc:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
            raise HistoryError(f"无法迁移 CSV v{version} 表头：{exc}") from exc

    def latest_for(self, item: ImageItem) -> HistoryEvent | None:
        if self._events is None:
            self.load()
        assert self._events is not None
        return self._events.get(item.identity)

    def latest_for_relative_path(self, relative_path: str) -> HistoryEvent | None:
        if self._events is None:
            self.load()
        assert self._events is not None
        events = [
            event for event in self._events.values()
            if event.identity.relative_path == relative_path
        ]
        return max(events, key=lambda event: event.updated_at) if events else None

    @staticmethod
    def _to_row(event: HistoryEvent) -> dict[str, object]:
        return {
            "schema_version": event.schema_version,
            "event_id": event.event_id,
            "relative_path": event.identity.relative_path,
            "file_size": event.identity.file_size,
            "file_mtime_ns": event.identity.file_mtime_ns,
            "status": event.status,
            "classified_at": event.classified_at,
            "class_code": event.class_code,
            "area_code": event.area_code,
            "observation_location": event.observation_location,
            "observation_time": event.observation_time,
            "observation_country": event.observation_country,
            "observation_region": event.observation_region,
            "result_id": event.result_id,
            "species_id": event.species_id,
            "species_cn": event.species_cn,
            "species_en": event.species_en,
            "species_latin": event.species_latin,
            "confidence_percent": event.confidence_percent,
            "animal_class": event.animal_class,
            "destination_path": event.destination_path,
            "selection_mode": event.selection_mode,
            "review_reason": event.review_reason,
            "low_confidence_threshold": event.low_confidence_threshold,
            "ambiguity_delta_threshold": event.ambiguity_delta_threshold,
            "reviewed_at": event.reviewed_at,
            "candidate_payload": event.candidate_payload,
            "detection_payload": event.detection_payload,
            "archive_payload": event.archive_payload,
            "upload_was_compressed": "1" if event.upload_was_compressed else "0",
            "upload_bytes": event.upload_bytes,
            "error_code": event.error_code,
            "error_message": event.error_message,
            "updated_at": event.updated_at,
        }

    @staticmethod
    def _from_row(row: dict[str, str]) -> HistoryEvent:
        return HistoryEvent(
            identity=FileIdentity(row["relative_path"], int(row["file_size"]), int(row["file_mtime_ns"])),
            status=row["status"],
            updated_at=row["updated_at"],
            event_id=row["event_id"],
            schema_version=int(row["schema_version"]),
            classified_at=row["classified_at"],
            class_code=row["class_code"],
            area_code=row["area_code"],
            observation_location=row.get("observation_location", ""),
            observation_time=row.get("observation_time", ""),
            observation_country=row.get("observation_country", ""),
            observation_region=row.get("observation_region", ""),
            result_id=row["result_id"],
            species_id=row["species_id"],
            species_cn=row["species_cn"],
            species_en=row["species_en"],
            species_latin=row["species_latin"],
            confidence_percent=row["confidence_percent"],
            animal_class=row["animal_class"],
            destination_path=row["destination_path"],
            selection_mode=row["selection_mode"],
            review_reason=row["review_reason"],
            low_confidence_threshold=row["low_confidence_threshold"],
            ambiguity_delta_threshold=row["ambiguity_delta_threshold"],
            reviewed_at=row["reviewed_at"],
            candidate_payload=row["candidate_payload"],
            detection_payload=row.get("detection_payload", ""),
            archive_payload=row.get("archive_payload", ""),
            upload_was_compressed=row["upload_was_compressed"] == "1",
            upload_bytes=int(row["upload_bytes"]),
            error_code=row["error_code"],
            error_message=row["error_message"],
        )
