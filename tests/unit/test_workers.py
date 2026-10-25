from decimal import Decimal
from pathlib import Path

from birdclass.models import (
    AppConfig,
    RecognitionCandidate,
    ReviewAction,
    ReviewResult,
)
from birdclass.ui.workers import ClassificationWorker


def make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        api_key="secret",
        animal_class="B",
        area_code="WORLD",
        low_confidence_threshold=Decimal("80"),
        ambiguity_delta_threshold=Decimal("10"),
        source_dir=tmp_path / "source",
        output_dir=tmp_path / "output",
    )


def make_candidate() -> RecognitionCandidate:
    return RecognitionCandidate(
        species_id="1",
        animal_class="B",
        name_cn="麻雀",
        name_en="Sparrow",
        name_latin="Passer",
        confidence_raw="80",
        confidence_percent=Decimal("80"),
    )


def test_worker_resolves_only_matching_request_id(qtbot, tmp_path):
    worker = ClassificationWorker(make_config(tmp_path))
    worker._request_id = "request-1"
    worker._review_event.clear()

    ignored = ReviewResult(ReviewAction.DEFER)
    worker.resolve_review("other-request", ignored)
    assert not worker._review_event.is_set()

    confirmed = ReviewResult(ReviewAction.CONFIRM, make_candidate())
    worker.resolve_review("request-1", confirmed)

    assert worker._review_event.is_set()
    assert worker._review_result is confirmed


def test_worker_stop_releases_pending_review(qtbot, tmp_path):
    worker = ClassificationWorker(make_config(tmp_path))
    worker._request_id = "request-1"
    worker._review_event.clear()

    worker.request_stop()

    assert worker.stop_event.is_set()
    assert worker._review_event.is_set()
    assert worker._review_result is not None
    assert worker._review_result.action == ReviewAction.STOP
