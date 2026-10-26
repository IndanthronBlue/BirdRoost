import json
from pathlib import Path
from types import SimpleNamespace

from birdclass.library_import import _copy_records


def test_duplicate_archive_selections_merge_into_one_copy(tmp_path: Path):
    destination = tmp_path / "三趾滨鹬" / "a.jpg"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"image")
    event = SimpleNamespace(
        archive_payload=json.dumps({"selections": [
            {
                "destination_path": "三趾滨鹬/a.jpg",
                "candidate": {"name_cn": "三趾滨鹬", "name_latin": "Calidris alba"},
                "source_targets": [0],
            },
            {
                "destination_path": "三趾滨鹬/a.jpg",
                "candidate": {"name_cn": "三趾滨鹬", "name_latin": "Calidris alba"},
                "source_targets": [1],
            },
        ]}),
        destination_path="",
        species_cn="三趾滨鹬",
        species_latin="Calidris alba",
    )

    records = _copy_records(event, ["三趾滨鹬/a.jpg"], tmp_path)

    assert len(records) == 1
    assert records[0]["target_indices"] == [0, 1]
