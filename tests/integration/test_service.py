from __future__ import annotations

import csv
import hashlib
import os
import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from PIL import Image

from birdclass.history import CsvHistory
from birdclass.models import (
    AppConfig,
    FileIdentity,
    HistoryEvent,
    ImageItem,
    Quota,
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
    def __init__(self, quota: Quota, result_payload=None):
        self.quota = quota
        self.result_payload = result_payload if result_payload is not None else payload()
        self.submit_calls = 0
        self.poll_wait_seconds = []

    def query_quota(self):
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
