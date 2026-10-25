from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from .api import DongNiaoClient
from .archiver import FileArchiver
from .errors import (
    ApiProtocolError,
    HistoryError,
    ImagePreparationError,
    ImageValidationError,
    RecognitionFailedError,
    SpeciesNotFoundError,
)
from .history import CsvHistory
from .metadata import write_species_metadata
from .models import (
    AppConfig,
    ArchiveSelection,
    BatchSummary,
    CandidateDecision,
    DetectionTarget,
    HistoryEvent,
    ImageItem,
    Recognition,
    RecognitionCandidate,
    ReviewAction,
    ReviewContext,
    ReviewResult,
    TargetSelection,
)
from .resource_loader import area_name_for_code
from .scanner import HISTORY_FILENAME, scan_images
from .species import aggregate_selections, decide_candidate, parse_candidates, parse_detections
from .upload_preparer import PreparedUpload, UploadPreparer

ProgressCallback = Callable[[str, dict], None]
ReviewCallback = Callable[[ReviewContext], ReviewResult]


class ClassificationService:
    def __init__(self, api_factory=DongNiaoClient) -> None:
        self._api_factory = api_factory

    def run(
        self,
        config: AppConfig,
        review_callback: ReviewCallback,
        progress_callback: ProgressCallback,
        stop_event: threading.Event,
    ) -> BatchSummary:
        if not config.api_key.strip():
            raise ValueError("API Key 不能为空")
        history = CsvHistory(config.source_dir.expanduser().resolve() / HISTORY_FILENAME)
        history.load()
        items = scan_images(config.source_dir, config.output_dir)
        source = config.source_dir.expanduser().resolve()
        output = config.output_dir.expanduser().resolve()
        history.path = source / HISTORY_FILENAME
        archiver = FileArchiver(output)
        summary = BatchSummary(total=len(items))
        pending_new: list[ImageItem] = []
        api = self._api_factory(config.api_key)

        for item in items:
            event = history.latest_for(item)
            if event is None or event.status == "failed":
                pending_new.append(item)
                continue
            if event.status == "completed":
                summary.skipped += 1
                self._progress(progress_callback, "skipped", item)
                continue
            if stop_event.is_set():
                summary.stop_reason = "user"
                return summary
            if event.status == "recognized":
                if event.schema_version >= 2 and event.archive_payload:
                    self._archive_many_and_complete(
                        item, event, history, archiver, summary, progress_callback
                    )
                else:
                    recognition = self._recognition_from_event(event)
                    self._archive_and_complete(
                        item, recognition, event, history, archiver, summary, progress_callback
                    )
                continue
            if event.status == "review_pending":
                if event.schema_version >= 2:
                    selections, reviewed, deferred_targets, stop_action = self._review_multi(
                        item, event, review_callback, history
                    )
                    if stop_action == ReviewAction.STOP:
                        summary.deferred += 1
                        summary.stop_reason = "user"
                        return summary
                    self._finish_multi_review(
                        item, event, selections, reviewed, deferred_targets,
                        history, archiver, summary, progress_callback,
                    )
                    continue
                candidates = tuple(
                    RecognitionCandidate.from_dict(raw) for raw in json.loads(event.candidate_payload)
                )
                decision = decide_candidate(candidates, Decimal("0"), Decimal("0"))
                review = ReviewContext(
                    image_path=item.absolute_path,
                    relative_path=item.relative_path,
                    result_id=event.result_id,
                    candidates=candidates,
                    reason=event.review_reason,
                    low_threshold=Decimal(event.low_confidence_threshold or config.low_confidence_threshold),
                    delta_threshold=Decimal(event.ambiguity_delta_threshold or config.ambiguity_delta_threshold),
                    confidence_gap=decision.confidence_gap,
                )
                result = review_callback(review)
                if result.action == ReviewAction.STOP:
                    summary.deferred += 1
                    summary.stop_reason = "user"
                    return summary
                if result.action == ReviewAction.DEFER:
                    pending_destination = archiver.archive_pending(item)
                    summary.deferred += 1
                    summary.stop_reason = summary.stop_reason or "deferred"
                    self._progress(
                        progress_callback, "deferred", item,
                        destination=pending_destination, deferred_targets=[0],
                    )
                    continue
                candidate = self._selected_candidate(result, candidates)
                recognition = Recognition(
                    result_id=event.result_id,
                    candidate=candidate,
                    selection_mode="manual",
                    review_reason=event.review_reason,
                    reviewed_at=self._now(),
                )
                recognized_event = self._event(item, "recognized", config, recognition, event)
                history.append(recognized_event)
                summary.reviewed += 1
                self._archive_and_complete(
                    item, recognition, recognized_event, history, archiver, summary, progress_callback
                )
                continue
            raise HistoryError(f"未知 CSV 状态：{event.status}")

        if not pending_new:
            return summary
        quota = api.query_quota()
        self._progress(progress_callback, "quota", None, quota=quota)
        remaining = quota.remaining

        for item in pending_new:
            if stop_event.is_set():
                summary.stop_reason = "user"
                break
            if not quota.unlimited and remaining <= 0:
                summary.stop_reason = "quota"
                break
            prepared: PreparedUpload | None = None
            upload_was_compressed = False
            upload_bytes = 0
            try:
                with UploadPreparer.prepare(item) as prepared_upload:
                    prepared = prepared_upload
                    upload_was_compressed = prepared.was_compressed
                    upload_bytes = prepared.upload_bytes
                    self._progress(progress_callback, "uploading", item)
                    result_id = api.submit_image(
                        prepared.upload_path, config.animal_class, config.area_code
                    )
                    if not quota.unlimited:
                        remaining -= 1
                    raw_candidates = api.poll_result(result_id, config.result_wait_seconds)
                targets = [
                    target for target in parse_detections(raw_candidates, prepared.upload_size)
                    if target.candidates
                ]
                if not targets:
                    raise RecognitionFailedError("识别结果没有有效物种候选")
                selections: list[TargetSelection] = []
                needs_review = False
                for target in targets:
                    decision = decide_candidate(
                        target.candidates,
                        config.low_confidence_threshold,
                        config.ambiguity_delta_threshold,
                    )
                    if decision.needs_review:
                        needs_review = True
                    else:
                        assert decision.selected is not None
                        selections.append(TargetSelection(
                            target.target_index, decision.selected, "automatic"
                        ))
                base_event = self._event(
                    item, "review_pending" if needs_review else "recognized", config, None, None,
                    result_id=result_id,
                    schema_version=3,
                    detection_payload=self._detection_payload(targets, selections),
                    upload_was_compressed=upload_was_compressed,
                    upload_bytes=upload_bytes,
                )
                if needs_review:
                    history.append(base_event)
                    selections, reviewed, deferred_targets, stop_action = self._review_multi(
                        item, base_event, review_callback, history
                    )
                    if stop_action == ReviewAction.STOP:
                        summary.deferred += 1
                        summary.stop_reason = "user"
                        break
                    self._finish_multi_review(
                        item, base_event, selections, reviewed, deferred_targets,
                        history, archiver, summary, progress_callback,
                    )
                    continue
                recognized_event = self._recognized_multi(item, base_event, selections, archiver)
                history.append(recognized_event)
                self._archive_many_and_complete(
                    item, recognized_event, history, archiver, summary, progress_callback
                )
            except (ImageValidationError, ImagePreparationError, RecognitionFailedError) as exc:
                summary.failed += 1
                pending_destination = None
                if isinstance(exc, SpeciesNotFoundError):
                    pending_destination = archiver.archive_pending(item)
                    summary.deferred += 1
                history.append(self._event(
                    item, "failed", config, None, None,
                    error_code=exc.__class__.__name__,
                    error_message=str(exc),
                    upload_was_compressed=upload_was_compressed,
                    upload_bytes=upload_bytes,
                ))
                self._progress(
                    progress_callback, "failed", item,
                    error=str(exc), destination=pending_destination,
                )
        return summary

    @staticmethod
    def _detection_payload(
        targets: list[DetectionTarget], selections: list[TargetSelection]
    ) -> str:
        selected = {selection.target_index: selection for selection in selections}
        return json.dumps({"targets": [
            {
                **target.to_dict(),
                "selection": selected[target.target_index].to_dict()
                if target.target_index in selected else None,
            }
            for target in targets
        ]}, ensure_ascii=False)

    @staticmethod
    def _parse_detection_payload(payload: str) -> tuple[list[DetectionTarget], list[TargetSelection]]:
        raw = json.loads(payload)
        targets = []
        selections = []
        for item in raw["targets"]:
            targets.append(DetectionTarget.from_dict(item))
            if item.get("selection"):
                selections.append(TargetSelection.from_dict(item["selection"]))
        return targets, selections

    def _review_multi(
        self,
        item: ImageItem,
        event: HistoryEvent,
        review_callback: ReviewCallback,
        history: CsvHistory,
    ) -> tuple[list[TargetSelection], int, list[int], ReviewAction | None]:
        targets, selections = self._parse_detection_payload(event.detection_payload)
        selected_indices = {selection.target_index for selection in selections}
        config = self._config_from_event(event)
        reviewed = 0
        deferred_targets = []
        for target in targets:
            if target.target_index in selected_indices:
                continue
            decision = decide_candidate(
                target.candidates, config.low_confidence_threshold, config.ambiguity_delta_threshold
            )
            context = ReviewContext(
                image_path=item.absolute_path,
                relative_path=item.relative_path,
                result_id=event.result_id,
                candidates=target.candidates,
                reason=decision.reason,
                low_threshold=config.low_confidence_threshold,
                delta_threshold=config.ambiguity_delta_threshold,
                confidence_gap=decision.confidence_gap,
                target_index=target.target_index,
                target_count=len(targets),
                box=target.box,
            )
            result = review_callback(context)
            if result.action == ReviewAction.STOP:
                return selections, reviewed, deferred_targets, result.action
            if result.action == ReviewAction.DEFER:
                deferred_targets.append(target.target_index)
                continue
            candidate = self._selected_candidate(result, target.candidates)
            selections.append(TargetSelection(
                target_index=target.target_index,
                candidate=candidate,
                selection_mode="manual",
                review_reason=decision.reason,
                reviewed_at=self._now(),
            ))
            selected_indices.add(target.target_index)
            reviewed += 1
            pending = self._event(
                item, "review_pending", config, None, event,
                schema_version=event.schema_version,
                detection_payload=self._detection_payload(targets, selections),
            )
            history.append(pending)
        return selections, reviewed, deferred_targets, None

    def _finish_multi_review(
        self,
        item: ImageItem,
        event: HistoryEvent,
        selections: list[TargetSelection],
        reviewed: int,
        deferred_targets: list[int],
        history: CsvHistory,
        archiver: FileArchiver,
        summary: BatchSummary,
        progress_callback: ProgressCallback,
    ) -> None:
        summary.reviewed += reviewed
        if deferred_targets:
            summary.deferred += 1
            summary.stop_reason = summary.stop_reason or "deferred"
            if selections:
                self._archive_partial_and_keep_pending(
                    item, event, selections, deferred_targets,
                    history, archiver, progress_callback,
                )
            pending_destination = archiver.archive_pending(item)
            self._progress(
                progress_callback, "deferred", item,
                destination=pending_destination, deferred_targets=deferred_targets,
            )
            return
        recognized_event = self._recognized_multi(item, event, selections, archiver)
        history.append(recognized_event)
        self._archive_many_and_complete(
            item, recognized_event, history, archiver, summary, progress_callback
        )

    def _recognized_multi(
        self,
        item: ImageItem,
        previous: HistoryEvent,
        selections: list[TargetSelection],
        archiver: FileArchiver,
    ) -> HistoryEvent:
        aggregated = aggregate_selections(selections)
        if not aggregated:
            raise RecognitionFailedError("没有可归档的鸟种选择")
        saved_destinations = {}
        if previous.archive_payload:
            for value in json.loads(previous.archive_payload)["selections"]:
                saved = ArchiveSelection.from_dict(value)
                key = (saved.candidate.species_id, saved.candidate.animal_class)
                saved_destinations[key] = saved.destination_path
        archive = [
            ArchiveSelection(
                candidate=selection.candidate,
                source_targets=selection.source_targets,
                destination_path=saved_destinations.get(
                    (selection.candidate.species_id, selection.candidate.animal_class), ""
                ),
            )
            for selection in aggregated
        ]
        config = self._config_from_event(previous)
        planned = archiver.plan_many(
            archive,
            area_name_for_code(previous.area_code),
            item.absolute_path.suffix,
            observation_location=previous.observation_location,
            observation_time=previous.observation_time,
        )
        targets, _ = self._parse_detection_payload(previous.detection_payload)
        final_detection_payload = self._detection_payload(targets, selections)
        candidates = [selection.candidate for selection in planned]
        recognition = Recognition(
            result_id=previous.result_id,
            candidate=candidates[0],
            selection_mode="manual" if any(s.selection_mode == "manual" for s in selections) else "automatic",
            review_reason="+".join(sorted({s.review_reason for s in selections if s.review_reason != "none"})) or "none",
            reviewed_at=max((s.reviewed_at for s in selections), default=""),
        )
        return self._event(
            item, "recognized", config, recognition, previous,
            schema_version=previous.schema_version,
            detection_payload=final_detection_payload,
            archive_payload=json.dumps(
                {"selections": [selection.to_dict() for selection in planned]}, ensure_ascii=False
            ),
            species_id="、".join(candidate.species_id for candidate in candidates),
            species_cn="、".join(candidate.name_cn for candidate in candidates),
            species_en="、".join(candidate.name_en for candidate in candidates),
            species_latin="、".join(candidate.name_latin for candidate in candidates),
            confidence_percent="、".join(str(candidate.confidence_percent) for candidate in candidates),
            animal_class="、".join(dict.fromkeys(candidate.animal_class for candidate in candidates)),
            destination_path="；".join(selection.destination_path for selection in planned),
        )

    def _archive_partial_and_keep_pending(
        self,
        item: ImageItem,
        event: HistoryEvent,
        selections: list[TargetSelection],
        deferred_targets: list[int],
        history: CsvHistory,
        archiver: FileArchiver,
        progress_callback: ProgressCallback,
    ) -> None:
        recognized_event = self._recognized_multi(item, event, selections, archiver)
        config = self._config_from_event(recognized_event)
        archive_selections = [
            ArchiveSelection.from_dict(value)
            for value in json.loads(recognized_event.archive_payload)["selections"]
        ]
        write_species_metadata(item.absolute_path, "、".join(
            selection.candidate.name_cn for selection in archive_selections
        ))
        stat = item.absolute_path.stat()
        updated_item = ImageItem(item.absolute_path, item.relative_path, stat.st_size, stat.st_mtime_ns)
        destinations = archiver.archive_many(
            updated_item, archive_selections, area_name_for_code(recognized_event.area_code)
        )
        pending = self._event(
            updated_item, "review_pending", config, None, recognized_event,
            schema_version=recognized_event.schema_version,
            detection_payload=recognized_event.detection_payload,
            archive_payload=recognized_event.archive_payload,
        )
        history.append(pending)
        self._progress(
            progress_callback, "partially_completed", updated_item,
            destination=destinations[0], destinations=destinations,
            deferred_targets=deferred_targets,
        )

    def _archive_many_and_complete(
        self,
        item: ImageItem,
        recognized_event: HistoryEvent,
        history: CsvHistory,
        archiver: FileArchiver,
        summary: BatchSummary,
        progress_callback: ProgressCallback,
    ) -> None:
        config = self._config_from_event(recognized_event)
        raw = json.loads(recognized_event.archive_payload)
        selections = [ArchiveSelection.from_dict(value) for value in raw["selections"]]
        write_species_metadata(item.absolute_path, "、".join(
            selection.candidate.name_cn for selection in selections
        ))
        stat = item.absolute_path.stat()
        updated_item = ImageItem(item.absolute_path, item.relative_path, stat.st_size, stat.st_mtime_ns)
        updated_recognized = self._event(
            updated_item, "recognized", config, None, recognized_event,
            schema_version=recognized_event.schema_version,
            detection_payload=recognized_event.detection_payload,
            archive_payload=recognized_event.archive_payload,
        )
        history.append(updated_recognized)
        destinations = archiver.archive_many(
            updated_item, selections, area_name_for_code(recognized_event.area_code)
        )
        completed = self._event(
            updated_item, "completed", config, None, updated_recognized,
            schema_version=recognized_event.schema_version,
            detection_payload=recognized_event.detection_payload,
            archive_payload=recognized_event.archive_payload,
        )
        history.append(completed)
        summary.completed += 1
        self._progress(
            progress_callback, "completed", updated_item,
            destination=destinations[0], destinations=destinations,
        )

    def _archive_and_complete(
        self,
        item: ImageItem,
        recognition: Recognition,
        recognized_event: HistoryEvent,
        history: CsvHistory,
        archiver: FileArchiver,
        summary: BatchSummary,
        progress_callback: ProgressCallback,
    ) -> None:
        config = self._config_from_event(recognized_event)
        destination = archiver.archive(
            item,
            recognition,
            area_name=area_name_for_code(recognized_event.area_code),
            destination_path=recognized_event.destination_path or None,
            observation_location=recognized_event.observation_location,
            observation_time=recognized_event.observation_time,
        )
        stat = item.absolute_path.stat()
        updated_item = ImageItem(item.absolute_path, item.relative_path, stat.st_size, stat.st_mtime_ns)
        relative_destination = destination.relative_to(archiver.output_root).as_posix()
        updated_recognition = self._event(
            updated_item, "recognized", config, recognition, recognized_event,
            destination_path=relative_destination,
        )
        history.append(updated_recognition)
        completed_event = self._event(
            updated_item, "completed", config, recognition,
            updated_recognition, destination_path=relative_destination,
        )
        history.append(completed_event)
        summary.completed += 1
        self._progress(progress_callback, "completed", updated_item, destination=destination)

    @staticmethod
    def _selected_candidate(
        result: ReviewResult, candidates: tuple[RecognitionCandidate, ...]
    ) -> RecognitionCandidate:
        if result.action != ReviewAction.CONFIRM or result.candidate is None:
            raise RecognitionFailedError("人工复核未选择有效候选")
        selected = next(
            (candidate for candidate in candidates
             if (candidate.species_id, candidate.animal_class)
             == (result.candidate.species_id, result.candidate.animal_class)),
            None,
        )
        if selected is None:
            raise RecognitionFailedError("人工选择的候选不属于当前识别结果")
        return selected

    @staticmethod
    def _recognition_from_event(event: HistoryEvent) -> Recognition:
        candidate = RecognitionCandidate(
            species_id=event.species_id,
            animal_class=event.animal_class,
            name_cn=event.species_cn,
            name_en=event.species_en,
            name_latin=event.species_latin,
            confidence_raw="",
            confidence_percent=Decimal(event.confidence_percent),
        )
        return Recognition(
            result_id=event.result_id,
            candidate=candidate,
            selection_mode=event.selection_mode,
            review_reason=event.review_reason,
            reviewed_at=event.reviewed_at,
        )

    def _event(
        self,
        item: ImageItem,
        status: str,
        config: AppConfig,
        recognition: Recognition | None,
        previous: HistoryEvent | None,
        **overrides,
    ) -> HistoryEvent:
        now = self._now()
        candidate = recognition.candidate if recognition else None
        values = dict(
            identity=item.identity,
            status=status,
            updated_at=now,
            event_id=str(uuid.uuid4()),
            schema_version=previous.schema_version if previous else 1,
            classified_at=now if status == "completed" else (previous.classified_at if previous else ""),
            class_code=config.animal_class,
            area_code=config.area_code,
            observation_location=config.observation_location,
            observation_time=config.observation_time,
            result_id=recognition.result_id if recognition else (previous.result_id if previous else ""),
            species_id=candidate.species_id if candidate else (previous.species_id if previous else ""),
            species_cn=candidate.name_cn if candidate else (previous.species_cn if previous else ""),
            species_en=candidate.name_en if candidate else (previous.species_en if previous else ""),
            species_latin=candidate.name_latin if candidate else (previous.species_latin if previous else ""),
            confidence_percent=str(candidate.confidence_percent) if candidate else (previous.confidence_percent if previous else ""),
            animal_class=candidate.animal_class if candidate else (previous.animal_class if previous else ""),
            destination_path=previous.destination_path if previous else "",
            selection_mode=recognition.selection_mode if recognition else (previous.selection_mode if previous else ""),
            review_reason=recognition.review_reason if recognition else (previous.review_reason if previous else ""),
            low_confidence_threshold=str(config.low_confidence_threshold),
            ambiguity_delta_threshold=str(config.ambiguity_delta_threshold),
            reviewed_at=recognition.reviewed_at if recognition else (previous.reviewed_at if previous else ""),
            candidate_payload=previous.candidate_payload if previous else "",
            detection_payload=previous.detection_payload if previous else "",
            archive_payload=previous.archive_payload if previous else "",
            upload_was_compressed=previous.upload_was_compressed if previous else False,
            upload_bytes=previous.upload_bytes if previous else 0,
        )
        values.update(overrides)
        return HistoryEvent(**values)

    @staticmethod
    def _config_from_event(event: HistoryEvent) -> AppConfig:
        return AppConfig(
            api_key="not-persisted",
            animal_class=event.class_code,
            area_code=event.area_code,
            low_confidence_threshold=Decimal(event.low_confidence_threshold or "0"),
            ambiguity_delta_threshold=Decimal(event.ambiguity_delta_threshold or "0"),
            source_dir=Path("."),
            output_dir=Path("."),
            observation_location=event.observation_location,
            observation_time=event.observation_time,
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _progress(callback, event: str, item: ImageItem | None, **data) -> None:
        payload = dict(data)
        if item is not None:
            payload["relative_path"] = item.relative_path
        callback(event, payload)
