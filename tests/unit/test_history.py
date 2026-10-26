import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from birdclass.errors import HistoryError
from birdclass.history import HEADERS_V1, HEADERS_V2, CsvHistory
from birdclass.models import FileIdentity, HistoryEvent, ImageItem


def make_event(status="review_pending", size=10, payload=None):
    if payload is None:
        payload = json.dumps([{
            "species_id": "1", "animal_class": "B", "name_cn": "麻雀",
            "confidence_percent": "71.2", "confidence_raw": "0.712",
        }], ensure_ascii=False)
    return HistoryEvent(
        identity=FileIdentity(" nested/鸟图.jpg ", size, 123),
        status=status,
        updated_at=datetime.now(timezone.utc).isoformat(),
        event_id=str(uuid.uuid4()),
        result_id="result-1",
        candidate_payload=payload,
        review_reason="low_confidence" if status == "review_pending" else "none",
        selection_mode="" if status == "review_pending" else "auto",
    )


def test_history_restores_review_pending_with_chinese_and_bom(tmp_path: Path):
    path = tmp_path / "birdclass_records.csv"
    event = make_event()

    CsvHistory(path).append(event)
    loaded = CsvHistory(path).load()

    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    restored = loaded[event.identity]
    assert restored.status == "review_pending"
    assert restored.candidate_payload == event.candidate_payload
    assert "麻雀" in restored.candidate_payload


def test_latest_event_wins_for_same_identity(tmp_path: Path):
    path = tmp_path / "birdclass_records.csv"
    history = CsvHistory(path)
    pending = make_event()
    completed = make_event(status="completed")
    completed = HistoryEvent(**{**completed.__dict__, "identity": pending.identity})

    history.append(pending)
    history.append(completed)

    assert history.load()[pending.identity].status == "completed"


def test_file_identity_changes_when_file_changes(tmp_path: Path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"one")
    item = ImageItem(path, "a.jpg", 3, 10)
    changed = ImageItem(path, "a.jpg", 4, 10)

    assert item.identity != changed.identity


def test_bad_header_is_rejected(tmp_path: Path):
    path = tmp_path / "birdclass_records.csv"
    path.write_text("wrong,header\n1,2\n", encoding="utf-8-sig")

    with pytest.raises(HistoryError, match="表头"):
        CsvHistory(path).load()


def test_invalid_review_candidate_payload_is_rejected(tmp_path: Path):
    path = tmp_path / "birdclass_records.csv"

    CsvHistory(path).append(make_event(payload="not json"))

    with pytest.raises(HistoryError, match="候选"):
        CsvHistory(path).load()


def test_v2_detection_and_archive_payload_round_trip(tmp_path: Path):
    path = tmp_path / "birdclass_records.csv"
    event = HistoryEvent(**{
        **make_event().__dict__,
        "schema_version": 2,
        "candidate_payload": "",
        "detection_payload": json.dumps({"targets": [{"target_index": 0, "box": [0, 0, 1, 1]}]}),
        "archive_payload": json.dumps({"selections": [{"species_cn": "麻雀"}]}, ensure_ascii=False),
    })

    CsvHistory(path).append(event)
    restored = CsvHistory(path).load()[event.identity]

    assert restored.schema_version == 2
    assert restored.detection_payload == event.detection_payload
    assert "麻雀" in restored.archive_payload


def test_appending_v2_migrates_v1_header_and_preserves_events(tmp_path: Path):
    path = tmp_path / "birdclass_records.csv"
    old = make_event(status="completed", payload=[])
    history = CsvHistory(path)
    history.append(old)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS_V1, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    new = HistoryEvent(**{
        **make_event(size=11).__dict__,
        "schema_version": 2,
        "candidate_payload": "",
        "detection_payload": '{"targets": []}',
    })

    history.append(new)
    loaded = CsvHistory(path).load()

    assert loaded[old.identity].status == "completed"
    assert loaded[new.identity].detection_payload == '{"targets": []}'
    assert "detection_payload" in path.read_text(encoding="utf-8-sig").splitlines()[0]
    assert (tmp_path / "birdclass_records.v1.bak").exists()


def test_v3_observation_fields_round_trip(tmp_path: Path):
    path = tmp_path / "birdclass_records.csv"
    event = HistoryEvent(**{
        **make_event(status="completed").__dict__,
        "schema_version": 3,
        "observation_location": "云南大理",
        "observation_time": "2026-10-24 1430",
    })

    CsvHistory(path).append(event)
    restored = CsvHistory(path).load()[event.identity]

    assert restored.schema_version == 3
    assert restored.observation_location == "云南大理"
    assert restored.observation_time == "2026-10-24 1430"


def test_appending_v3_migrates_v2_header_and_preserves_events(tmp_path: Path):
    path = tmp_path / "birdclass_records.csv"
    old = HistoryEvent(**{
        **make_event(status="completed").__dict__,
        "schema_version": 2,
        "detection_payload": '{"targets": []}',
    })
    history = CsvHistory(path)
    history.append(old)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS_V2, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    new = HistoryEvent(**{
        **make_event(size=11).__dict__,
        "schema_version": 3,
        "candidate_payload": "",
        "detection_payload": '{"targets": []}',
        "observation_location": "云南大理",
        "observation_time": "2026-10-24 1430",
    })

    history.append(new)
    loaded = CsvHistory(path).load()

    assert loaded[old.identity].status == "completed"
    assert loaded[old.identity].observation_location == ""
    assert loaded[new.identity].observation_time == "2026-10-24 1430"
    assert "observation_location" in path.read_text(encoding="utf-8-sig").splitlines()[0]
    assert (tmp_path / "birdclass_records.v2.bak").exists()


def test_future_schema_is_rejected(tmp_path: Path):
    path = tmp_path / "birdclass_records.csv"
    event = HistoryEvent(**{**make_event().__dict__, "schema_version": 5})
    CsvHistory(path).append(event)

    with pytest.raises(HistoryError, match="schema"):
        CsvHistory(path).load()
