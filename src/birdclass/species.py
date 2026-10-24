from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from .errors import ApiProtocolError, RecognitionFailedError
from .models import (
    ArchiveSelection,
    CandidateDecision,
    DetectionTarget,
    NormalizedBox,
    RecognitionCandidate,
    TargetSelection,
)


def _percent_from_api(raw: Any) -> tuple[str, Decimal]:
    """真实 v2 接口直接返回 0～100 的百分数。"""
    try:
        percent = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ApiProtocolError("候选置信度不是数值") from exc
    if not Decimal("0") <= percent <= Decimal("100"):
        raise ApiProtocolError("候选置信度不在 0～100 范围内")
    return str(raw), percent


def parse_candidates(payload: list[Any]) -> list[RecognitionCandidate]:
    candidates: list[RecognitionCandidate] = []
    order = 0
    try:
        for detection in payload:
            raw_list = detection.get("list", [])
            for raw in raw_list:
                raw_confidence, raw_name, species_id, animal_class = raw
                parts = str(raw_name).split("|", 2)
                name_cn = parts[0].strip()
                if not name_cn:
                    continue
                confidence_raw, confidence_percent = _percent_from_api(raw_confidence)
                candidates.append(RecognitionCandidate(
                    species_id=str(species_id),
                    animal_class=str(animal_class),
                    name_cn=name_cn,
                    name_en=parts[1].strip() if len(parts) > 1 else "",
                    name_latin=parts[2].strip() if len(parts) > 2 else "",
                    confidence_raw=confidence_raw,
                    confidence_percent=confidence_percent,
                    source_order=order,
                ))
                order += 1
    except (TypeError, ValueError, AttributeError) as exc:
        raise ApiProtocolError("识别候选结构不符合手册") from exc
    ordered = _deduplicate_and_sort(candidates)
    if not ordered:
        raise RecognitionFailedError("识别结果没有有效物种候选")
    return ordered


def parse_detections(payload: list[Any], upload_size: tuple[int, int]) -> list[DetectionTarget]:
    width, height = upload_size
    if width <= 0 or height <= 0:
        raise ApiProtocolError("上传图片尺寸无效，无法解析检测框")
    targets: list[DetectionTarget] = []
    order = 0
    try:
        for target_index, detection in enumerate(payload):
            candidates: list[RecognitionCandidate] = []
            for raw in detection.get("list", []):
                raw_confidence, raw_name, species_id, animal_class = raw
                parts = str(raw_name).split("|", 2)
                name_cn = parts[0].strip()
                if not name_cn:
                    continue
                confidence_raw, confidence_percent = _percent_from_api(raw_confidence)
                candidates.append(RecognitionCandidate(
                    species_id=str(species_id),
                    animal_class=str(animal_class),
                    name_cn=name_cn,
                    name_en=parts[1].strip() if len(parts) > 1 else "",
                    name_latin=parts[2].strip() if len(parts) > 2 else "",
                    confidence_raw=confidence_raw,
                    confidence_percent=confidence_percent,
                    source_order=order,
                ))
                order += 1
            targets.append(DetectionTarget(
                target_index=target_index,
                box=_normalize_box(detection.get("box"), width, height),
                candidates=tuple(_deduplicate_and_sort(candidates)),
            ))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ApiProtocolError("识别候选或检测框结构不符合手册") from exc
    return targets


def _normalize_box(raw: Any, width: int, height: int) -> NormalizedBox | None:
    if raw is None or raw == []:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise ApiProtocolError("检测框必须包含四个坐标")
    left, top, right, bottom = (float(value) for value in raw)
    left, right = sorted((max(0.0, min(left, width)), max(0.0, min(right, width))))
    top, bottom = sorted((max(0.0, min(top, height)), max(0.0, min(bottom, height))))
    if left == right or top == bottom:
        return None
    return left / width, top / height, right / width, bottom / height


def aggregate_selections(selections: Iterable[TargetSelection]) -> list[ArchiveSelection]:
    grouped: dict[tuple[str, str], list[TargetSelection]] = {}
    for selection in sorted(selections, key=lambda value: value.target_index):
        key = (selection.candidate.species_id, selection.candidate.animal_class)
        grouped.setdefault(key, []).append(selection)
    archived = []
    for group in grouped.values():
        representative = max(group, key=lambda value: value.candidate.confidence_percent)
        archived.append(ArchiveSelection(
            candidate=representative.candidate,
            source_targets=tuple(value.target_index for value in group),
        ))
    return archived


def _deduplicate_and_sort(candidates: Iterable[RecognitionCandidate]) -> list[RecognitionCandidate]:
    unique: dict[tuple[str, str], RecognitionCandidate] = {}
    for candidate in candidates:
        key = (candidate.species_id, candidate.animal_class)
        existing = unique.get(key)
        if existing is None or candidate.confidence_percent > existing.confidence_percent:
            unique[key] = candidate
    return sorted(unique.values(), key=lambda c: (-c.confidence_percent, c.source_order))


def decide_candidate(
    candidates: Iterable[RecognitionCandidate],
    low_threshold: Decimal,
    delta_threshold: Decimal,
) -> CandidateDecision:
    if not Decimal("0") <= low_threshold <= Decimal("100"):
        raise ValueError("低置信度阈值必须在 0～100 之间")
    if not Decimal("0") <= delta_threshold <= Decimal("100"):
        raise ValueError("近似并列阈值必须在 0～100 之间")
    ordered = _deduplicate_and_sort(candidates)
    if not ordered:
        raise RecognitionFailedError("识别结果没有有效物种候选")
    top = ordered[0]
    gap = top.confidence_percent - ordered[1].confidence_percent if len(ordered) > 1 else None
    low = top.confidence_percent < low_threshold
    ambiguous = gap is not None and gap <= delta_threshold
    reasons = []
    if low:
        reasons.append("low_confidence")
    if ambiguous:
        reasons.append("ambiguous")
    needs_review = bool(reasons)
    return CandidateDecision(
        candidates=tuple(ordered),
        needs_review=needs_review,
        reason="+".join(reasons) if reasons else "none",
        selected=None if needs_review else top,
        confidence_gap=gap,
    )
