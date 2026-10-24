from decimal import Decimal

import pytest

from birdclass.errors import ApiProtocolError, RecognitionFailedError
from birdclass.models import RecognitionCandidate, TargetSelection
from birdclass.species import aggregate_selections, decide_candidate, parse_candidates, parse_detections


def candidate(species_id: str, confidence: str, order: int = 0):
    return RecognitionCandidate(
        species_id=species_id,
        animal_class="B",
        name_cn=f"物种{species_id}",
        name_en="",
        name_latin="",
        confidence_raw="",
        confidence_percent=Decimal(confidence),
        source_order=order,
    )


def test_parse_candidates_deduplicates_across_boxes_and_sorts():
    payload = [
        {"box": [], "list": [[80, "麻雀|Tree Sparrow|Passer montanus", 1, "B"]]},
        {"box": [], "list": [[90, "麻雀|Tree Sparrow|Passer montanus", 1, "B"], [85, "家燕||Barn swallow", 2, "B"]]},
    ]

    candidates = parse_candidates(payload)

    assert [c.species_id for c in candidates] == ["1", "2"]
    assert candidates[0].confidence_percent == Decimal("90")
    assert candidates[1].name_latin == "Barn swallow"


def test_exact_boundaries_and_deduplication():
    candidates = [candidate("1", "80", 0), candidate("1", "70", 1), candidate("2", "69", 2)]

    decision = decide_candidate(candidates, Decimal("80"), Decimal("10"))

    assert not decision.needs_review
    assert decision.selected.species_id == "1"


def test_low_confidence_requires_review():
    decision = decide_candidate([candidate("1", "79.99")], Decimal("80"), Decimal("10"))

    assert decision.needs_review
    assert decision.reason == "low_confidence"


def test_near_tie_at_exact_delta_requires_review():
    decision = decide_candidate(
        [candidate("1", "90"), candidate("2", "80")], Decimal("80"), Decimal("10")
    )

    assert decision.needs_review
    assert decision.reason == "ambiguous"
    assert decision.confidence_gap == Decimal("10")


def test_low_and_ambiguous_reasons_are_combined():
    decision = decide_candidate(
        [candidate("1", "60"), candidate("2", "55")], Decimal("80"), Decimal("10")
    )

    assert decision.reason == "low_confidence+ambiguous"


def test_empty_candidates_are_recognition_failure():
    with pytest.raises(RecognitionFailedError):
        parse_candidates([{"box": [], "list": []}])


def test_out_of_range_confidence_is_rejected():
    payload = [{"box": [], "list": [[101, "麻雀||", 1, "B"]]}]

    with pytest.raises(ApiProtocolError, match="置信度"):
        parse_candidates(payload)


def test_parse_detections_preserves_boxes_and_separates_candidates():
    payload = [
        {"box": [100, 80, 0, 0], "list": [["95", "斑鸠|Dove|Streptopelia", 1, "B"]]},
        {"box": [-10, 0, 50, 40], "list": [["90", "麻雀|Sparrow|Passer", 2, "B"]]},
        {"box": [], "list": []},
    ]

    targets = parse_detections(payload, (200, 100))

    assert targets[0].box == (0.0, 0.0, 0.5, 0.8)
    assert targets[1].box == (0.0, 0.0, 0.25, 0.4)
    assert [target.target_index for target in targets] == [0, 1, 2]
    assert [target.candidates[0].name_cn for target in targets[:2]] == ["斑鸠", "麻雀"]
    assert targets[2].candidates == ()


def test_decisions_are_independent_across_detection_targets():
    payload = [
        {"box": [0, 0, 10, 10], "list": [["95", "斑鸠||", 1, "B"]]},
        {"box": [10, 0, 20, 10], "list": [["94", "麻雀||", 2, "B"]]},
    ]
    targets = parse_detections(payload, (20, 10))

    decisions = [decide_candidate(t.candidates, Decimal("80"), Decimal("10")) for t in targets]

    assert all(not decision.needs_review for decision in decisions)


def test_aggregate_selections_deduplicates_species_across_targets():
    first = TargetSelection(0, candidate("1", "90"), "automatic")
    second = TargetSelection(1, candidate("1", "95", 1), "manual")
    third = TargetSelection(2, candidate("2", "88", 2), "automatic")

    archived = aggregate_selections([first, second, third])

    assert len(archived) == 2
    assert archived[0].candidate.confidence_percent == Decimal("95")
    assert archived[0].source_targets == (0, 1)
    assert archived[1].source_targets == (2,)
