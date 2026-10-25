from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileIdentity:
    relative_path: str
    file_size: int
    file_mtime_ns: int


@dataclass(frozen=True)
class ImageItem:
    absolute_path: Path
    relative_path: str
    size: int
    mtime_ns: int

    @property
    def identity(self) -> FileIdentity:
        return FileIdentity(self.relative_path, self.size, self.mtime_ns)


@dataclass(frozen=True)
class AppConfig:
    api_key: str = field(repr=False)
    animal_class: str
    area_code: str
    low_confidence_threshold: Decimal
    ambiguity_delta_threshold: Decimal
    source_dir: Path
    output_dir: Path
    observation_location: str = ""
    observation_time: str = ""
    result_wait_seconds: int = 60


@dataclass(frozen=True)
class Quota:
    used: int
    total: int
    remaining: int

    @property
    def unlimited(self) -> bool:
        return self.total == -1


@dataclass(frozen=True)
class RecognitionCandidate:
    species_id: str
    animal_class: str
    name_cn: str
    name_en: str
    name_latin: str
    confidence_raw: str
    confidence_percent: Decimal
    source_order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "species_id": self.species_id,
            "animal_class": self.animal_class,
            "name_cn": self.name_cn,
            "name_en": self.name_en,
            "name_latin": self.name_latin,
            "confidence_raw": self.confidence_raw,
            "confidence_percent": str(self.confidence_percent),
            "source_order": self.source_order,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecognitionCandidate":
        return cls(
            species_id=str(data["species_id"]),
            animal_class=str(data["animal_class"]),
            name_cn=str(data.get("name_cn", "")),
            name_en=str(data.get("name_en", "")),
            name_latin=str(data.get("name_latin", "")),
            confidence_raw=str(data.get("confidence_raw", "")),
            confidence_percent=Decimal(str(data["confidence_percent"])),
            source_order=int(data.get("source_order", 0)),
        )


NormalizedBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class DetectionTarget:
    target_index: int
    box: NormalizedBox | None
    candidates: tuple[RecognitionCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_index": self.target_index,
            "box": list(self.box) if self.box is not None else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DetectionTarget":
        raw_box = data.get("box")
        return cls(
            target_index=int(data["target_index"]),
            box=tuple(float(value) for value in raw_box) if raw_box is not None else None,
            candidates=tuple(RecognitionCandidate.from_dict(raw) for raw in data["candidates"]),
        )


@dataclass(frozen=True)
class TargetSelection:
    target_index: int
    candidate: RecognitionCandidate
    selection_mode: str
    review_reason: str = "none"
    reviewed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_index": self.target_index,
            "candidate": self.candidate.to_dict(),
            "selection_mode": self.selection_mode,
            "review_reason": self.review_reason,
            "reviewed_at": self.reviewed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TargetSelection":
        return cls(
            target_index=int(data["target_index"]),
            candidate=RecognitionCandidate.from_dict(data["candidate"]),
            selection_mode=data["selection_mode"],
            review_reason=data.get("review_reason", "none"),
            reviewed_at=data.get("reviewed_at", ""),
        )


@dataclass(frozen=True)
class ArchiveSelection:
    candidate: RecognitionCandidate
    source_targets: tuple[int, ...]
    destination_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "source_targets": list(self.source_targets),
            "destination_path": self.destination_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArchiveSelection":
        return cls(
            candidate=RecognitionCandidate.from_dict(data["candidate"]),
            source_targets=tuple(int(value) for value in data["source_targets"]),
            destination_path=data.get("destination_path", ""),
        )


@dataclass(frozen=True)
class Recognition:
    result_id: str
    candidate: RecognitionCandidate
    selection_mode: str
    review_reason: str = "none"
    reviewed_at: str = ""


@dataclass(frozen=True)
class CandidateDecision:
    candidates: tuple[RecognitionCandidate, ...]
    needs_review: bool
    reason: str
    selected: RecognitionCandidate | None
    confidence_gap: Decimal | None


class ReviewAction(Enum):
    CONFIRM = "confirm"
    CUSTOM = "custom"
    DEFER = "defer"
    STOP = "stop"


@dataclass(frozen=True)
class ReviewResult:
    action: ReviewAction
    candidate: RecognitionCandidate | None = None
    custom_name_cn: str = ""
    apply_to_remaining: bool = False


@dataclass(frozen=True)
class ReviewContext:
    image_path: Path
    relative_path: str
    result_id: str
    candidates: tuple[RecognitionCandidate, ...]
    reason: str
    low_threshold: Decimal
    delta_threshold: Decimal
    confidence_gap: Decimal | None
    target_index: int = 0
    target_count: int = 1
    box: NormalizedBox | None = None

    @property
    def candidate_payload(self) -> str:
        return json.dumps([c.to_dict() for c in self.candidates], ensure_ascii=False)


@dataclass(frozen=True)
class HistoryEvent:
    identity: FileIdentity
    status: str
    updated_at: str
    event_id: str
    schema_version: int = 1
    classified_at: str = ""
    class_code: str = ""
    area_code: str = ""
    observation_location: str = ""
    observation_time: str = ""
    result_id: str = ""
    species_id: str = ""
    species_cn: str = ""
    species_en: str = ""
    species_latin: str = ""
    confidence_percent: str = ""
    animal_class: str = ""
    destination_path: str = ""
    selection_mode: str = ""
    review_reason: str = ""
    low_confidence_threshold: str = ""
    ambiguity_delta_threshold: str = ""
    reviewed_at: str = ""
    candidate_payload: str = ""
    detection_payload: str = ""
    archive_payload: str = ""
    upload_was_compressed: bool = False
    upload_bytes: int = 0
    error_code: str = ""
    error_message: str = ""


@dataclass
class BatchSummary:
    total: int = 0
    skipped: int = 0
    completed: int = 0
    failed: int = 0
    deferred: int = 0
    reviewed: int = 0
    stop_reason: str = ""
