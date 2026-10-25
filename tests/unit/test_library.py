import json
from pathlib import Path

import pytest

from birdclass.errors import LibraryError
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id


def test_ensure_creates_manifest_and_directories(tmp_path: Path):
    library = ArchiveLibrary(tmp_path / "archive")

    library.ensure(taxonomy_version="IOC 15.2")

    assert library.groups_dir.is_dir()
    assert library.batches_dir.is_dir()
    manifest = json.loads(library.library_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["taxonomy"]["version"] == "IOC 15.2"


def test_group_round_trip_and_copy_lookup(tmp_path: Path):
    library = ArchiveLibrary(tmp_path / "archive")
    library.ensure()
    group_id = new_group_id()
    group = {
        "schema_version": 1,
        "group_id": group_id,
        "batch_id": new_batch_id(),
        "status": "completed",
        "targets": [{"target_index": 0, "box": [0.1, 0.2, 0.5, 0.8]}],
        "copies": [
            {"relative_path": "三趾滨鹬/a.jpg", "species_cn": "三趾滨鹬", "target_indices": [0]}
        ],
    }

    path = library.write_group(group)

    assert path.is_file()
    assert library.read_group(group_id)["copies"][0]["relative_path"] == "三趾滨鹬/a.jpg"
    assert library.find_group_for_copy("三趾滨鹬/a.jpg")["group_id"] == group_id
    assert library.find_group_for_copy("不存在/a.jpg") is None


def test_batch_round_trip(tmp_path: Path):
    library = ArchiveLibrary(tmp_path / "archive")
    library.ensure()
    batch_id = new_batch_id()

    library.write_batch({
        "schema_version": 1,
        "batch_id": batch_id,
        "groups": [],
        "summary": {"completed": 1},
    })

    assert library.read_batch(batch_id)["summary"]["completed"] == 1


def test_corrections_are_appended_and_loaded(tmp_path: Path):
    library = ArchiveLibrary(tmp_path / "archive")
    library.ensure()

    library.append_correction({"group_id": "g1", "old": "A", "new": "B"})
    library.append_correction({"group_id": "g1", "old": "B", "new": "C"})

    records = library.load_corrections()
    assert [record["new"] for record in records] == ["B", "C"]
    assert library.corrections_path.read_text(encoding="utf-8").count("\n") == 2


def test_invalid_identifier_cannot_escape_library(tmp_path: Path):
    library = ArchiveLibrary(tmp_path / "archive")
    library.ensure()

    with pytest.raises(LibraryError, match="group_id"):
        library.write_group({"group_id": "../outside", "copies": []})


def test_corrupt_group_is_skipped_unless_strict(tmp_path: Path):
    library = ArchiveLibrary(tmp_path / "archive")
    library.ensure()
    (library.groups_dir / "broken.json").write_text("{not json", encoding="utf-8")

    assert library.load_groups() == []
    with pytest.raises(LibraryError):
        library.load_groups(strict=True)


def test_corrupt_manifest_is_recreated(tmp_path: Path):
    library = ArchiveLibrary(tmp_path / "archive")
    library.root.mkdir(parents=True)
    library.library_path.write_text("{broken", encoding="utf-8")

    library.ensure(taxonomy_version="IOC 15.2")

    manifest = json.loads(library.library_path.read_text(encoding="utf-8"))
    assert manifest["taxonomy"]["version"] == "IOC 15.2"
