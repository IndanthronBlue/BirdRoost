from __future__ import annotations

import csv
import hashlib
import os
import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image

from birdclass.errors import (
    ApiTransportError,
    ConfigError,
    RecognitionFailedError,
    SpeciesNotFoundError,
)
from birdclass.history import CsvHistory
from birdclass.models import (
    AppConfig,
    FileIdentity,
    HistoryEvent,
    ImageItem,
    Quota,
    RecognitionCandidate,
    ReviewAction,
    ReviewResult,
)
from birdclass.service import ClassificationService


def make_image(path: Path, size: tuple[int, int] = (20, 20)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "green").save(path)


def make_config(tmp_path: Path, **overrides) -> AppConfig:
    values = dict(
        api_key="secret",
        animal_class="B",
        area_code="WORLD",
        low_confidence_threshold=Decimal("80"),
        ambiguity_delta_threshold=Decimal("10"),
        source_dir=tmp_path / "source",
        output_dir=tmp_path / "output",
    )
    values.update(overrides)
    return AppConfig(**values)


def payload(first: str = "95", second: str | None = None, name: str = "麻雀"):
    candidates = [[first, f"{name}|Sparrow|Passer", "1", "B"]]
    if second is not None:
        candidates.append([second, "家燕|Swallow|Hirundo", "2", "B"])
    return [{"list": candidates}]


class FakeAPI:
    def __init__(self, quota: Quota, result_payload=None, quota_sequence=None):
        self.quota = quota
        self.result_payload = result_payload if result_payload is not None else payload()
        self.quota_sequence = list(quota_sequence or [])
        self.quota_calls = 0
        self.submit_calls = 0
        self.poll_wait_seconds = []

    def query_quota(self):
        self.quota_calls += 1
        if self.quota_sequence:
            return self.quota_sequence.pop(0)
        return self.quota

    def submit_image(self, image_path, animal_class, area_code):
        self.submit_calls += 1
        return f"result-{self.submit_calls}"

    def poll_result(self, result_id, total_wait_seconds=60):
        self.poll_wait_seconds.append(total_wait_seconds)
        return self.result_payload


def make_service(api: FakeAPI) -> ClassificationService:
    return ClassificationService(api_factory=lambda _key: api)


def auto_review(context):
    return ReviewResult(ReviewAction.CONFIRM, context.candidates[0])


def no_progress(_event, _data):
    pass


def run_service(service, config, review=auto_review):
    return service.run(config, review, no_progress, threading.Event())


def test_quota_limits_new_uploads(tmp_path):
    source = tmp_path / "source"
    for index in range(10):
        make_image(source / f"{index:02}.jpg")
    api = FakeAPI(Quota(7, 10, 3))

    summary = run_service(make_service(api), make_config(tmp_path))

    assert api.submit_calls == 3
    assert summary.completed == 3
    assert summary.stop_reason == "quota"


def test_second_run_skips_completed_with_updated_identity_and_metadata(tmp_path):
    import piexif

    source = tmp_path / "source"
    make_image(source / "done.jpg")
    make_image(source / "new.jpg")
    api = FakeAPI(Quota(0, 10, 10))
    config = make_config(tmp_path)
    first = run_service(make_service(api), config)

    second = run_service(make_service(api), config)

    assert first.completed == 2
    assert second.skipped == 2
    assert second.completed == 0
    assert api.submit_calls == 2
    events = CsvHistory(source / "birdclass_records.csv").load()
    completed = [event for event in events.values() if event.status == "completed"]
    assert len(completed) == 2
    for event in completed:
        original = source / event.identity.relative_path
        stat = original.stat()
        assert event.identity.file_size == stat.st_size
        assert event.identity.file_mtime_ns == stat.st_mtime_ns
        copied = tmp_path / "output" / event.destination_path
        assert piexif.load(str(original))["0th"][piexif.ImageIFD.ImageDescription].decode() == "麻雀"
        assert piexif.load(str(copied))["0th"][piexif.ImageIFD.ImageDescription].decode() == "麻雀"


def test_manual_second_candidate_is_archived_and_recorded(tmp_path):
    source = tmp_path / "source"
    make_image(source / "bird.jpg")
    api = FakeAPI(Quota(0, 10, 10), payload("0.70", "0.65"))

    def choose_second(context):
        return ReviewResult(ReviewAction.CONFIRM, context.candidates[1])

    summary = run_service(make_service(api), make_config(tmp_path), choose_second)

    assert summary.completed == 1
    assert summary.reviewed == 1
    assert (tmp_path / "output" / "家燕" / "全球_家燕_001.jpg").is_file()
    with (source / "birdclass_records.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["status"] for row in rows] == [
        "review_pending", "review_pending", "recognized", "recognized", "completed"
    ]
    assert rows[-1]["selection_mode"] == "manual"
    assert rows[-1]["species_cn"] == "家燕"
    assert '"selection_mode": "manual"' in rows[-1]["detection_payload"]


def test_deferred_review_recovers_without_new_upload(tmp_path):
    source = tmp_path / "source"
    make_image(source / "bird.jpg")
    config = make_config(tmp_path)
    api = FakeAPI(Quota(0, 10, 10), payload("0.60"))

    first = run_service(
        make_service(api),
        config,
        review=lambda _context: ReviewResult(ReviewAction.DEFER),
    )
    second = run_service(make_service(api), config)

    assert first.deferred == 1
    assert second.completed == 1
    assert api.submit_calls == 1
    pending = tmp_path / "output" / "待复核" / "bird.jpg"
    assert pending.is_file()
    assert len(list(pending.parent.glob("*.jpg"))) == 1
    assert not list(pending.parent.glob("*_待确认框*"))


def test_defer_skips_only_current_image_and_continues_batch(tmp_path):
    source = tmp_path / "source"
    make_image(source / "first.jpg")
    make_image(source / "second.jpg")
    api = FakeAPI(Quota(0, 10, 10))
    api.poll_result = lambda result_id, total_wait_seconds=60: (
        payload("0.60") if result_id == "result-1" else payload("95")
    )

    summary = run_service(
        make_service(api),
        make_config(tmp_path),
        review=lambda _context: ReviewResult(ReviewAction.DEFER),
    )

    assert summary.deferred == 1
    assert summary.completed == 1
    assert summary.stop_reason == "deferred"
    assert api.submit_calls == 2
    events = CsvHistory(source / "birdclass_records.csv").load()
    statuses = {event.identity.relative_path: event.status for event in events.values()}
    assert statuses == {"first.jpg": "review_pending", "second.jpg": "completed"}


def test_zero_quota_still_restores_pending_review_and_recognized(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    make_image(source / "review.jpg")
    make_image(source / "copy.jpg")
    history = CsvHistory(source / "birdclass_records.csv")
    history.load()
    candidate_payload = payload("0.50")[0]["list"]
    candidate_dict = {
        "species_id": "1", "animal_class": "B", "name_cn": "麻雀",
        "name_en": "Sparrow", "name_latin": "Passer", "confidence_raw": "0.5",
        "confidence_percent": "50", "source_order": 0,
    }
    import json
    for name, status in (("review.jpg", "review_pending"), ("copy.jpg", "recognized")):
        path = source / name
        stat = path.stat()
        history.append(HistoryEvent(
            identity=FileIdentity(name, stat.st_size, stat.st_mtime_ns),
            status=status,
            updated_at=datetime.now(timezone.utc).isoformat(),
            event_id=name,
            result_id=f"saved-{name}",
            species_id="1" if status == "recognized" else "",
            species_cn="麻雀" if status == "recognized" else "",
            confidence_percent="95" if status == "recognized" else "",
            selection_mode="automatic" if status == "recognized" else "",
            candidate_payload=json.dumps([candidate_dict], ensure_ascii=False) if status == "review_pending" else "",
        ))
    api = FakeAPI(Quota(10, 10, 0), payload("0.50"))

    summary = run_service(make_service(api), make_config(tmp_path))

    assert summary.completed == 2
    assert api.submit_calls == 0
    assert (output / "麻雀" / "全球_麻雀_002.jpg").is_file()
    assert (output / "麻雀" / "全球_麻雀_001.jpg").is_file()


def test_large_image_archives_original_pixels_and_species_metadata(tmp_path):
    source = tmp_path / "source"
    original = source / "large.png"
    original.parent.mkdir(parents=True)
    Image.frombytes("RGB", (1000, 1000), os.urandom(1000 * 1000 * 3)).save(original)
    assert original.stat().st_size > 2_000_000
    with Image.open(original) as image:
        before_pixels = image.convert("RGB").tobytes()
    api = FakeAPI(Quota(0, 10, 10))

    summary = run_service(make_service(api), make_config(tmp_path))

    archived = tmp_path / "output" / "麻雀" / "全球_麻雀_001.png"
    assert summary.completed == 1
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == hashlib.sha256(original.read_bytes()).hexdigest()
    with Image.open(original) as original_image, Image.open(archived) as archived_image:
        assert original_image.convert("RGB").tobytes() == before_pixels
        assert archived_image.convert("RGB").tobytes() == before_pixels
        assert original_image.text["Description"] == "麻雀"
        assert archived_image.text["Description"] == "麻雀"


def multi_species_payload(second_name="麻雀", second_id="2", second_confidence="90"):
    return [
        {"box": [0, 0, 10, 20], "list": [["95", "斑鸠|Dove|Streptopelia", "1", "B"]]},
        {"box": [10, 0, 20, 20], "list": [[second_confidence, f"{second_name}|Sparrow|Passer", second_id, "B"]]},
    ]


def test_multiple_detections_archive_each_species_once_with_one_upload(tmp_path):
    source = tmp_path / "source"
    make_image(source / "birds.jpg")
    api = FakeAPI(Quota(0, 10, 10), multi_species_payload())
    config = make_config(
        tmp_path, observation_location="云南大理", observation_time="2026-10-24 1430"
    )

    first = run_service(make_service(api), config)
    second = run_service(make_service(api), config)

    assert first.completed == 1
    assert api.submit_calls == 1
    assert (tmp_path / "output" / "斑鸠" / "云南大理_2026-10-24 1430_斑鸠_001.jpg").is_file()
    assert (tmp_path / "output" / "麻雀" / "云南大理_2026-10-24 1430_麻雀_001.jpg").is_file()
    assert second.skipped == 1
    assert api.submit_calls == 1
    events = CsvHistory(source / "birdclass_records.csv").load()
    completed = next(event for event in events.values() if event.status == "completed")
    assert completed.observation_location == "云南大理"
    assert completed.observation_time == "2026-10-24 1430"
    with Image.open(source / "birds.jpg") as image:
        exif = __import__("piexif").load(str(source / "birds.jpg"))
        assert exif["0th"][__import__("piexif").ImageIFD.ImageDescription].decode("utf-8") == "斑鸠、麻雀"


def test_same_species_across_detections_is_archived_only_once(tmp_path):
    source = tmp_path / "source"
    make_image(source / "birds.jpg")
    api = FakeAPI(Quota(0, 10, 10), multi_species_payload("斑鸠", "1"))

    summary = run_service(make_service(api), make_config(tmp_path))

    assert summary.completed == 1
    assert len(list((tmp_path / "output" / "斑鸠").glob("*.jpg"))) == 1


def test_only_uncertain_detection_requires_review(tmp_path):
    source = tmp_path / "source"
    make_image(source / "birds.jpg")
    api = FakeAPI(Quota(0, 10, 10), multi_species_payload(second_confidence="60"))
    contexts = []

    def review(context):
        contexts.append(context)
        return ReviewResult(ReviewAction.CONFIRM, context.candidates[0])

    summary = run_service(make_service(api), make_config(tmp_path), review)

    assert summary.completed == 1
    assert summary.reviewed == 1
    assert len(contexts) == 1
    assert contexts[0].target_index == 1
    assert [candidate.name_cn for candidate in contexts[0].candidates] == ["麻雀"]
    assert (tmp_path / "output" / "斑鸠" / "全球_斑鸠_001.jpg").is_file()
    assert (tmp_path / "output" / "麻雀" / "全球_麻雀_001.jpg").is_file()


def test_defer_skips_only_current_target_and_resumes_remaining_target(tmp_path):
    source = tmp_path / "source"
    make_image(source / "birds.jpg")
    result_payload = multi_species_payload(second_confidence="60")
    result_payload.append({
        "box": [20, 0, 30, 20],
        "list": [["55", "家燕|Swallow|Hirundo", "3", "B"]],
    })
    api = FakeAPI(Quota(0, 10, 10), result_payload)
    config = make_config(
        tmp_path, observation_location="原始地点", observation_time="原始时间"
    )
    first_contexts = []

    def defer_only_sparrow(context):
        first_contexts.append(context.target_index)
        action = ReviewAction.DEFER if context.target_index == 1 else ReviewAction.CONFIRM
        return ReviewResult(action, context.candidates[0] if action == ReviewAction.CONFIRM else None)

    first = run_service(make_service(api), config, defer_only_sparrow)

    assert first.deferred == 1
    assert first.completed == 0
    assert first.reviewed == 1
    assert first_contexts == [1, 2]
    assert (tmp_path / "output" / "斑鸠" / "原始地点_原始时间_斑鸠_001.jpg").is_file()
    assert (tmp_path / "output" / "家燕" / "原始地点_原始时间_家燕_001.jpg").is_file()
    assert not (tmp_path / "output" / "麻雀").exists()
    pending_copy = tmp_path / "output" / "待复核" / "birds.jpg"
    assert pending_copy.is_file()
    history = CsvHistory(source / "birdclass_records.csv")
    history.load()
    source_image = source / "birds.jpg"
    stat = source_image.stat()
    pending = history.latest_for(ImageItem(source_image, "birds.jpg", stat.st_size, stat.st_mtime_ns))
    assert pending is not None
    assert pending.status == "review_pending"
    assert pending.archive_payload

    changed_config = make_config(
        tmp_path, observation_location="新地点", observation_time="新时间"
    )
    second_contexts = []

    def confirm_remaining(context):
        second_contexts.append(context.target_index)
        return ReviewResult(ReviewAction.CONFIRM, context.candidates[0])

    second = run_service(make_service(api), changed_config, confirm_remaining)

    assert second.completed == 1
    assert second_contexts == [1]
    assert api.submit_calls == 1
    for species in ("斑鸠", "麻雀", "家燕"):
        directory = tmp_path / "output" / species
        assert len(list(directory.glob("*.jpg"))) == 1
        assert (directory / f"原始地点_原始时间_{species}_001.jpg").is_file()
    assert not list((tmp_path / "output").rglob("新地点*"))
    assert (pending_copy.parent / "birds_待确认框.jpg").is_file()
    assert len(list(pending_copy.parent.glob("*.jpg"))) == 2


def test_multiple_deferred_targets_create_only_one_pending_copy(tmp_path):
    source = tmp_path / "source"
    make_image(source / "birds.jpg")
    result_payload = multi_species_payload(second_confidence="60")
    result_payload[0]["list"][0][0] = "55"
    api = FakeAPI(Quota(0, 10, 10), result_payload)
    contexts = []

    def defer_every_target(context):
        contexts.append(context.target_index)
        return ReviewResult(ReviewAction.DEFER)

    summary = run_service(make_service(api), make_config(tmp_path), defer_every_target)

    assert summary.deferred == 1
    assert summary.reviewed == 0
    assert contexts == [0, 1]
    pending_directory = tmp_path / "output" / "待复核"
    assert (pending_directory / "birds.jpg").is_file()
    assert (pending_directory / "birds_待确认框.jpg").is_file()
    assert len(list(pending_directory.glob("*.jpg"))) == 2
    assert not (tmp_path / "output" / "斑鸠").exists()
    assert not (tmp_path / "output" / "麻雀").exists()


def test_partial_multi_copy_failure_resumes_without_upload_or_duplicates(tmp_path, monkeypatch):
    import pytest

    from birdclass.archiver import FileArchiver
    from birdclass.errors import ArchiveError

    source = tmp_path / "source"
    make_image(source / "birds.jpg")
    api = FakeAPI(Quota(0, 10, 10), multi_species_payload())
    config = make_config(tmp_path)
    original_copy = FileArchiver._copy_atomic
    calls = 0

    def fail_second(self, item, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ArchiveError("模拟第二张复制失败")
        return original_copy(item, destination)

    monkeypatch.setattr(FileArchiver, "_copy_atomic", fail_second)
    with pytest.raises(ArchiveError, match="第二张"):
        run_service(make_service(api), config)

    with (source / "birdclass_records.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    failed = rows[-1]
    assert failed["status"] == "failed"
    assert failed["error_code"] == "ArchiveError"
    assert failed["archive_payload"]

    monkeypatch.setattr(FileArchiver, "_copy_atomic", staticmethod(original_copy))
    second = run_service(make_service(api), config)

    assert second.completed == 1
    assert api.submit_calls == 1
    assert len(list((tmp_path / "output" / "斑鸠").glob("*.jpg"))) == 1
    assert len(list((tmp_path / "output" / "麻雀").glob("*.jpg"))) == 1


def test_mixed_manual_and_automatic_species_are_all_visible_in_csv(tmp_path):
    source = tmp_path / "source"
    make_image(source / "DSC_0704.jpg")
    result_payload = [
        {"box": [0, 0, 10, 20], "list": [
            ["42.51", "红颈滨鹬|Red-necked Stint|Calidris ruficollis", "1593", "B"],
            ["39.81", "三趾滨鹬|Sanderling|Calidris alba", "1594", "B"],
        ]},
        {"box": [10, 0, 20, 20], "list": [
            ["90.39", "环颈鸻|Kentish Plover|Anarhynchus alexandrinus", "1523", "B"],
        ]},
    ]
    api = FakeAPI(Quota(0, 10, 10), result_payload)
    config = make_config(
        tmp_path, area_code="ES", observation_location="多尼亚那", observation_time="260501"
    )

    def choose_sanderling(context):
        return ReviewResult(ReviewAction.CONFIRM, context.candidates[1])

    summary = run_service(make_service(api), config, choose_sanderling)

    assert summary.completed == 1
    with (source / "birdclass_records.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    completed = rows[-1]
    assert completed["status"] == "completed"
    assert completed["species_id"] == "1594、1523"
    assert completed["species_cn"] == "三趾滨鹬、环颈鸻"
    assert completed["species_en"] == "Sanderling、Kentish Plover"
    assert completed["species_latin"] == "Calidris alba、Anarhynchus alexandrinus"
    assert completed["confidence_percent"] == "39.81、90.39"
    assert completed["destination_path"] == (
        "三趾滨鹬/多尼亚那_260501_三趾滨鹬_001.jpg；"
        "环颈鸻/多尼亚那_260501_环颈鸻_001.jpg"
    )


def test_configured_result_wait_is_passed_to_api(tmp_path):
    source = tmp_path / "source"
    make_image(source / "bird.jpg")
    api = FakeAPI(Quota(0, 10, 10))
    config = make_config(tmp_path, result_wait_seconds=17)

    summary = run_service(make_service(api), config)

    assert summary.completed == 1
    assert api.poll_wait_seconds == [17]


def test_species_not_found_records_failure_and_continues_batch(tmp_path):
    source = tmp_path / "source"
    make_image(source / "first.jpg")
    make_image(source / "second.jpg")
    api = FakeAPI(Quota(0, 10, 10))

    def fail_first(result_id, total_wait_seconds=60):
        if result_id == "result-1":
            raise SpeciesNotFoundError(
                "地区筛选未返回可用物种（1011）：Species not found in this area"
            )
        return payload()

    api.poll_result = fail_first
    progress = []

    summary = make_service(api).run(
        make_config(tmp_path),
        auto_review,
        lambda event, data: progress.append(
            (event, data.get("relative_path"), data)
        ),
        threading.Event(),
    )

    assert api.submit_calls == 2
    assert summary.failed == 1
    assert summary.completed == 1
    assert summary.deferred == 1
    assert summary.stop_reason == ""
    failed_progress = [entry for entry in progress if entry[0] == "failed"]
    assert [entry[:2] for entry in failed_progress] == [("failed", "first.jpg")]
    pending = tmp_path / "output" / "待复核" / "first.jpg"
    assert pending.is_file()
    assert not list(pending.parent.glob("*_待确认框*"))
    assert failed_progress[0][2]["destination"] == pending
    events = CsvHistory(source / "birdclass_records.csv").load()
    statuses = {event.identity.relative_path: event.status for event in events.values()}
    assert statuses == {"first.jpg": "failed", "second.jpg": "completed"}


def test_custom_species_name_is_archived_with_metadata_and_csv(tmp_path):
    import piexif

    source = tmp_path / "source"
    make_image(source / "bird.jpg")
    api = FakeAPI(Quota(0, 10, 10), payload("0.60"))

    summary = run_service(
        make_service(api),
        make_config(tmp_path),
        lambda _context: ReviewResult(ReviewAction.CUSTOM, custom_name_cn="白鹡鸰"),
    )

    archived = tmp_path / "output" / "白鹡鸰" / "全球_白鹡鸰_001.jpg"
    assert summary.completed == 1
    assert summary.reviewed == 1
    assert archived.is_file()
    source_exif = piexif.load(str(source / "bird.jpg"))
    archive_exif = piexif.load(str(archived))
    assert source_exif["0th"][piexif.ImageIFD.ImageDescription].decode("utf-8") == "白鹡鸰"
    assert archive_exif["0th"][piexif.ImageIFD.ImageDescription].decode("utf-8") == "白鹡鸰"
    with (source / "birdclass_records.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    completed = rows[-1]
    assert completed["status"] == "completed"
    assert completed["species_id"] == "manual:白鹡鸰"
    assert completed["species_cn"] == "白鹡鸰"
    assert completed["selection_mode"] == "manual"
    assert completed["confidence_percent"] == "0"
    assert completed["review_reason"] == "low_confidence"


def test_duplicate_custom_names_across_targets_are_archived_once(tmp_path):
    source = tmp_path / "source"
    make_image(source / "birds.jpg")
    result_payload = [
        {"box": [0, 0, 10, 20], "list": [["60", "麻雀|Sparrow|Passer", "1", "B"]]},
        {"box": [10, 0, 20, 20], "list": [["55", "家燕|Swallow|Hirundo", "2", "B"]]},
    ]
    api = FakeAPI(Quota(0, 10, 10), result_payload)

    summary = run_service(
        make_service(api),
        make_config(tmp_path),
        lambda _context: ReviewResult(ReviewAction.CUSTOM, custom_name_cn="白鹡鸰"),
    )

    assert summary.completed == 1
    assert summary.reviewed == 2
    assert len(list((tmp_path / "output" / "白鹡鸰").glob("*.jpg"))) == 1
    assert not (tmp_path / "output" / "麻雀").exists()
    assert not (tmp_path / "output" / "家燕").exists()
    with (source / "birdclass_records.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[-1]["species_id"] == "manual:白鹡鸰"
    assert '"source_targets": [0, 1]' in rows[-1]["archive_payload"]


def test_custom_species_then_defer_resumes_without_duplicate(tmp_path):
    source = tmp_path / "source"
    make_image(source / "birds.jpg")
    result_payload = [
        {"box": [0, 0, 10, 20], "list": [["60", "麻雀|Sparrow|Passer", "1", "B"]]},
        {"box": [10, 0, 20, 20], "list": [["55", "家燕|Swallow|Hirundo", "2", "B"]]},
    ]
    api = FakeAPI(Quota(0, 10, 10), result_payload)
    config = make_config(tmp_path)

    def custom_then_defer(context):
        if context.target_index == 0:
            return ReviewResult(ReviewAction.CUSTOM, custom_name_cn="白鹡鸰")
        return ReviewResult(ReviewAction.DEFER)

    first = run_service(make_service(api), config, custom_then_defer)

    assert first.reviewed == 1
    assert first.deferred == 1
    assert first.completed == 0
    assert (tmp_path / "output" / "白鹡鸰" / "全球_白鹡鸰_001.jpg").is_file()
    assert (tmp_path / "output" / "待复核" / "birds.jpg").is_file()

    resumed_targets = []

    def confirm_remaining(context):
        resumed_targets.append(context.target_index)
        return ReviewResult(ReviewAction.CONFIRM, context.candidates[0])

    second = run_service(make_service(api), config, confirm_remaining)

    assert second.completed == 1
    assert resumed_targets == [1]
    assert api.submit_calls == 1
    assert (tmp_path / "output" / "家燕" / "全球_家燕_001.jpg").is_file()
    assert len(list((tmp_path / "output" / "白鹡鸰").glob("*.jpg"))) == 1


def test_custom_candidate_inherits_target_class_and_rejects_blank():
    candidates = (
        RecognitionCandidate(
            species_id="1593",
            animal_class="B",
            name_cn="红颈滨鹬",
            name_en="Red-necked Stint",
            name_latin="Calidris ruficollis",
            confidence_raw="42.51",
            confidence_percent=Decimal("42.51"),
        ),
    )

    custom = ClassificationService._selected_candidate(
        ReviewResult(ReviewAction.CUSTOM, custom_name_cn="  白鹡鸰  "), candidates
    )

    assert custom.species_id == "manual:白鹡鸰"
    assert custom.name_cn == "白鹡鸰"
    assert custom.animal_class == "B"
    assert custom.name_en == ""
    assert custom.name_latin == ""
    assert custom.confidence_raw == "manual"
    assert custom.confidence_percent == Decimal("0")
    assert custom.source_order == -1

    with pytest.raises(RecognitionFailedError, match="人工鸟名"):
        ClassificationService._selected_candidate(
            ReviewResult(ReviewAction.CUSTOM, custom_name_cn="   "), candidates
        )
    with pytest.raises(RecognitionFailedError, match="人工鸟名"):
        ClassificationService._selected_candidate(
            ReviewResult(ReviewAction.CUSTOM, custom_name_cn="白鹡鸰"), ()
        )


def test_schema1_pending_review_accepts_custom_name_without_upload(tmp_path):
    import json

    source = tmp_path / "source"
    output = tmp_path / "output"
    make_image(source / "legacy.jpg")
    stat = (source / "legacy.jpg").stat()
    history = CsvHistory(source / "birdclass_records.csv")
    history.load()
    history.append(HistoryEvent(
        identity=FileIdentity("legacy.jpg", stat.st_size, stat.st_mtime_ns),
        status="review_pending",
        updated_at=datetime.now(timezone.utc).isoformat(),
        event_id="legacy",
        result_id="saved-legacy",
        review_reason="low_confidence",
        low_confidence_threshold="80",
        ambiguity_delta_threshold="10",
        candidate_payload=json.dumps([{
            "species_id": "1", "animal_class": "B", "name_cn": "麻雀",
            "name_en": "Sparrow", "name_latin": "Passer",
            "confidence_raw": "0.5", "confidence_percent": "50", "source_order": 0,
        }], ensure_ascii=False),
    ))
    api = FakeAPI(Quota(0, 10, 0))

    summary = run_service(
        make_service(api),
        make_config(tmp_path),
        lambda _context: ReviewResult(ReviewAction.CUSTOM, custom_name_cn="白鹡鸰"),
    )

    assert summary.completed == 1
    assert api.submit_calls == 0
    assert (output / "白鹡鸰" / "全球_白鹡鸰_001.jpg").is_file()


def test_batch_end_requeries_quota_and_reports_final_value(tmp_path):
    source = tmp_path / "source"
    make_image(source / "a.jpg")
    make_image(source / "b.jpg")
    api = FakeAPI(
        Quota(0, 10, 2),
        quota_sequence=[Quota(0, 10, 2), Quota(2, 10, 0)],
    )
    progress = []

    summary = make_service(api).run(
        make_config(tmp_path),
        auto_review,
        lambda event, data: progress.append((event, data)),
        threading.Event(),
    )

    assert summary.completed == 2
    assert api.quota_calls == 2
    final = [data for event, data in progress if event == "quota" and data.get("final")]
    assert final and final[-1]["quota"] == Quota(2, 10, 0)


def test_batch_end_quota_failure_does_not_fail_completed_batch(tmp_path):
    class FailingFinalQuotaAPI(FakeAPI):
        def query_quota(self):
            self.quota_calls += 1
            if self.quota_calls > 1:
                raise ApiTransportError("网络请求失败：Timeout")
            return self.quota

    source = tmp_path / "source"
    make_image(source / "bird.jpg")
    api = FailingFinalQuotaAPI(Quota(0, 10, 1))
    progress = []

    summary = make_service(api).run(
        make_config(tmp_path),
        auto_review,
        lambda event, data: progress.append((event, data)),
        threading.Event(),
    )

    assert summary.completed == 1
    assert [event for event, _ in progress].count("quota_failed") == 1


def test_completed_only_run_still_requeries_quota(tmp_path):
    source = tmp_path / "source"
    make_image(source / "bird.jpg")
    api = FakeAPI(Quota(0, 10, 10))
    config = make_config(tmp_path)

    first = run_service(make_service(api), config)
    second = run_service(make_service(api), config)

    assert first.completed == 1
    assert second.skipped == 1
    assert api.quota_calls == 3


def test_poll_transport_error_records_failed_with_result_id(tmp_path):
    source = tmp_path / "source"
    make_image(source / "bird.jpg")
    api = FakeAPI(Quota(0, 10, 10))

    def fail_poll(result_id, total_wait_seconds=60):
        raise ApiTransportError("网络请求失败：Timeout")

    api.poll_result = fail_poll

    with pytest.raises(ApiTransportError, match="resultid: result-1"):
        run_service(make_service(api), make_config(tmp_path))

    with (source / "birdclass_records.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    failed = rows[-1]
    assert failed["status"] == "failed"
    assert failed["error_code"] == "ApiTransportError"
    assert failed["result_id"] == "result-1"
    assert "resultid: result-1" in failed["error_message"]


def test_upload_transport_error_marks_result_unknown(tmp_path):
    source = tmp_path / "source"
    make_image(source / "bird.jpg")
    api = FakeAPI(Quota(0, 10, 10))

    def fail_submit(*_args, **_kwargs):
        raise ApiTransportError("网络请求失败：ConnectionError")

    api.submit_image = fail_submit

    with pytest.raises(ApiTransportError, match="上传结果未知"):
        run_service(make_service(api), make_config(tmp_path))

    with (source / "birdclass_records.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    failed = rows[-1]
    assert failed["status"] == "failed"
    assert failed["error_code"] == "ApiTransportError"
    assert "上传结果未知" in failed["error_message"]


def test_config_error_records_failed_and_stops_batch(tmp_path):
    source = tmp_path / "source"
    make_image(source / "a.jpg")
    make_image(source / "b.jpg")
    api = FakeAPI(Quota(0, 10, 10))

    def fail_poll(result_id, total_wait_seconds=60):
        raise ConfigError("地区配置错误（1009）：Invalid area")

    api.poll_result = fail_poll

    with pytest.raises(ConfigError, match="1009"):
        run_service(make_service(api), make_config(tmp_path))

    with (source / "birdclass_records.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["error_code"] == "ConfigError"
    assert rows[0]["result_id"] == "result-1"
    assert api.submit_calls == 1


def test_partial_review_copy_failure_resumes_review_without_upload(tmp_path, monkeypatch):
    from birdclass.archiver import FileArchiver
    from birdclass.errors import ArchiveError

    source = tmp_path / "source"
    make_image(source / "birds.jpg")
    result_payload = [
        {"box": [0, 0, 10, 20], "list": [["60", "麻雀|Sparrow|Passer", "1", "B"]]},
        {"box": [10, 0, 20, 20], "list": [["55", "家燕|Swallow|Hirundo", "2", "B"]]},
    ]
    api = FakeAPI(Quota(0, 10, 10), result_payload)
    config = make_config(tmp_path)
    original_copy = FileArchiver._copy_atomic
    calls = 0

    def fail_first(self, item, destination):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ArchiveError("模拟部分归档复制失败")
        return original_copy(item, destination)

    def defer_second(context):
        action = ReviewAction.DEFER if context.target_index == 1 else ReviewAction.CONFIRM
        candidate = context.candidates[0] if action == ReviewAction.CONFIRM else None
        return ReviewResult(action, candidate)

    monkeypatch.setattr(FileArchiver, "_copy_atomic", fail_first)
    with pytest.raises(ArchiveError, match="部分归档"):
        run_service(make_service(api), config, defer_second)

    with (source / "birdclass_records.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[-1]["status"] == "failed"
    assert rows[-1]["error_code"] == "ArchiveError"
    assert "selection" in rows[-1]["detection_payload"]

    monkeypatch.setattr(FileArchiver, "_copy_atomic", staticmethod(original_copy))
    resumed_targets = []

    def confirm_remaining(context):
        resumed_targets.append(context.target_index)
        return ReviewResult(ReviewAction.CONFIRM, context.candidates[0])

    second = run_service(make_service(api), config, confirm_remaining)

    assert second.completed == 1
    assert resumed_targets == [1]
    assert api.submit_calls == 1
    assert (tmp_path / "output" / "麻雀" / "全球_麻雀_001.jpg").is_file()
    assert (tmp_path / "output" / "家燕" / "全球_家燕_001.jpg").is_file()


def test_schema1_recognized_copy_failure_resumes_without_upload(tmp_path, monkeypatch):
    from birdclass.archiver import FileArchiver
    from birdclass.errors import ArchiveError

    source = tmp_path / "source"
    output = tmp_path / "output"
    make_image(source / "legacy.jpg")
    stat = (source / "legacy.jpg").stat()
    history = CsvHistory(source / "birdclass_records.csv")
    history.load()
    history.append(HistoryEvent(
        identity=FileIdentity("legacy.jpg", stat.st_size, stat.st_mtime_ns),
        status="recognized",
        updated_at=datetime.now(timezone.utc).isoformat(),
        event_id="legacy-copy",
        result_id="saved-legacy",
        species_id="1",
        species_cn="麻雀",
        species_en="Sparrow",
        species_latin="Passer",
        confidence_percent="95",
        animal_class="B",
        selection_mode="automatic",
    ))
    api = FakeAPI(Quota(0, 10, 10))
    original_copy = FileArchiver._copy_atomic

    def fail_copy(item, destination):
        raise ArchiveError("模拟旧版复制失败")

    monkeypatch.setattr(FileArchiver, "_copy_atomic", staticmethod(fail_copy))
    with pytest.raises(ArchiveError, match="旧版复制失败"):
        run_service(make_service(api), make_config(tmp_path))

    with (source / "birdclass_records.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[-1]["status"] == "failed"
    assert rows[-1]["error_code"] == "ArchiveError"

    monkeypatch.setattr(FileArchiver, "_copy_atomic", staticmethod(original_copy))
    second = run_service(make_service(api), make_config(tmp_path))

    assert second.completed == 1
    assert api.submit_calls == 0
    assert (output / "麻雀" / "全球_麻雀_001.jpg").is_file()


def test_csv_write_failure_stops_before_further_uploads(tmp_path, monkeypatch):
    from birdclass.errors import HistoryError

    source = tmp_path / "source"
    make_image(source / "a.jpg")
    make_image(source / "b.jpg")
    api = FakeAPI(Quota(0, 10, 10))
    original_append = CsvHistory.append
    calls = 0

    def fail_second_append(self, event):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise HistoryError("模拟 CSV 写入失败")
        return original_append(self, event)

    monkeypatch.setattr(CsvHistory, "append", fail_second_append)

    with pytest.raises(HistoryError, match="CSV 写入失败"):
        run_service(make_service(api), make_config(tmp_path))

    assert api.submit_calls == 1


def test_apply_to_remaining_marks_later_targets_without_second_dialog(tmp_path):
    import json

    source = tmp_path / "source"
    make_image(source / "flock.jpg")
    result_payload = [
        {"box": [0, 0, 10, 20], "list": [["60", "麻雀|Sparrow|Passer", "1", "B"]]},
        {"box": [10, 0, 20, 20], "list": [["55", "麻雀|Sparrow|Passer", "1", "B"]]},
    ]
    api = FakeAPI(Quota(0, 10, 10), result_payload)
    contexts = []

    def review(context):
        contexts.append(context.target_index)
        return ReviewResult(
            ReviewAction.CONFIRM,
            context.candidates[0],
            apply_to_remaining=True,
        )

    progress = []
    summary = make_service(api).run(
        make_config(tmp_path),
        review,
        lambda event, data: progress.append((event, data)),
        threading.Event(),
    )

    assert contexts == [0]
    assert summary.completed == 1
    assert summary.reviewed == 2
    assert api.submit_calls == 1
    assert len(list((tmp_path / "output" / "麻雀").glob("*.jpg"))) == 1
    applied = [data for event, data in progress if event == "review_applied"]
    assert applied and applied[0]["target_indices"] == [1]

    with (source / "birdclass_records.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    payload = json.loads(rows[-1]["detection_payload"])
    selected = [
        target["selection"]["target_index"]
        for target in payload["targets"]
        if target["selection"]
    ]
    assert selected == [0, 1]


def test_defer_creates_annotated_pending_copy_when_box_exists(tmp_path):
    source = tmp_path / "source"
    make_image(source / "birds.png")
    api = FakeAPI(
        Quota(0, 10, 10),
        [{"box": [4, 4, 16, 16], "list": [["60", "麻雀|Sparrow|Passer", "1", "B"]]}],
    )

    summary = run_service(
        make_service(api),
        make_config(tmp_path),
        lambda _context: ReviewResult(ReviewAction.DEFER),
    )

    original = tmp_path / "output" / "待复核" / "birds.png"
    annotated = tmp_path / "output" / "待复核" / "birds_待确认框.png"
    assert summary.deferred == 1
    assert original.is_file()
    assert annotated.is_file()
    with Image.open(annotated) as image:
        colors = image.convert("RGB").getcolors(maxcolors=1_000_000) or []
    assert any(color == (255, 176, 32) for _, color in colors)


def test_completed_image_writes_group_and_batch(tmp_path):
    from birdclass.library import ArchiveLibrary

    source = tmp_path / "source"
    make_image(source / "bird.png")
    api = FakeAPI(
        Quota(0, 10, 10),
        [{"box": [2, 2, 18, 18], "list": [["95", "麻雀|Sparrow|Passer", "1", "B"]]}],
    )

    summary = run_service(make_service(api), make_config(tmp_path))

    library = ArchiveLibrary(tmp_path / "output")
    groups = library.load_groups()
    batches = library.load_batches()
    assert summary.completed == 1
    assert len(groups) == 1
    group = groups[0]
    assert group["status"] == "completed"
    assert group["batch_id"] == batches[0]["batch_id"]
    assert batches[0]["groups"] == [group["group_id"]]
    assert group["image"]["source_size"] == [20, 20]
    assert group["targets"][0]["box"] == pytest.approx([0.1, 0.1, 0.9, 0.9])
    assert group["copies"][0]["relative_path"] == "麻雀/全球_麻雀_001.png"


def test_rotated_upload_records_display_oriented_box(tmp_path):
    import piexif

    from birdclass.library import ArchiveLibrary

    source = tmp_path / "source"
    make_image(source / "rotated.jpg", size=(100, 80))
    exif = piexif.dump({"0th": {piexif.ImageIFD.Orientation: 6}})
    piexif.insert(exif, str(source / "rotated.jpg"))
    api = FakeAPI(
        Quota(0, 10, 10),
        [{"box": [8, 20, 40, 60], "list": [["95", "麻雀|Sparrow|Passer", "1", "B"]]}],
    )

    run_service(make_service(api), make_config(tmp_path))

    group = ArchiveLibrary(tmp_path / "output").load_groups()[0]
    assert group["image"]["source_size"] == [100, 80]
    assert group["image"]["display_size"] == [80, 100]
    assert group["image"]["exif_orientation"] == 6
    assert group["image"]["upload_oriented"] is True
    assert group["targets"][0]["box"] == pytest.approx([0.1, 0.2, 0.5, 0.6])


def test_deferred_image_writes_pending_group_with_both_copies(tmp_path):
    from birdclass.library import ArchiveLibrary

    source = tmp_path / "source"
    make_image(source / "birds.png")
    api = FakeAPI(
        Quota(0, 10, 10),
        [{"box": [4, 4, 16, 16], "list": [["60", "麻雀|Sparrow|Passer", "1", "B"]]}],
    )

    run_service(
        make_service(api),
        make_config(tmp_path),
        lambda _context: ReviewResult(ReviewAction.DEFER),
    )

    group = ArchiveLibrary(tmp_path / "output").load_groups()[0]
    assert group["status"] == "review_pending"
    assert {copy["relative_path"] for copy in group["copies"]} == {
        "待复核/birds.png",
        "待复核/birds_待确认框.png",
    }
    assert all(copy["target_indices"] == [0] for copy in group["copies"])
