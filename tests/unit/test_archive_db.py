from pathlib import Path

from PIL import Image

from birdclass.archive_db import ArchiveDatabase
from birdclass.archive_index import ArchiveIndex
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id


def make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 20), "green").save(path)


def test_sqlite_index_sync_locations_and_issues(tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    make_image(output / "欧乌鸫" / "b.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    batch = new_batch_id()
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": batch,
        "status": "completed",
        "source_relative_path": "a.jpg",
        "observation": {"location": "云南大理", "time": "2026-01-01"},
        "targets": [],
        "copies": [{"relative_path": "三趾滨鹬/a.jpg", "species_cn": "三趾滨鹬", "target_indices": [0]}],
    }
    library.write_group(group)
    failed = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": batch,
        "status": "failed",
        "source_relative_path": "bad.jpg",
        "error_code": "ImageValidationError",
        "error_message": "broken",
        "targets": [],
        "copies": [],
    }
    pending = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": batch,
        "status": "review_pending",
        "source_relative_path": "pending.jpg",
        "targets": [],
        "copies": [{"relative_path": "待复核/pending.jpg", "species_cn": "", "target_indices": [0]}],
    }
    library.write_group(failed)
    library.write_group(pending)

    index = ArchiveIndex(output)
    index.refresh()

    assert index.database.count() == 2
    assert index.locations() == ["云南大理"]
    issues = index.batch_issues(batch)
    assert {issue["status"] for issue in issues} == {"failed", "review_pending"}
    assert any(issue["error_message"] == "broken" for issue in issues)


def test_sqlite_index_can_be_rebuilt(tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    index = ArchiveIndex(output)
    index.refresh()
    database_path = output / ".birdroost" / "index.sqlite"
    assert database_path.is_file()

    database_path.unlink()
    index.database.close()
    index.database = ArchiveDatabase(output)
    index.refresh()

    assert index.database.count() == 1


def test_database_is_not_created_without_library(tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    index = ArchiveIndex(output)

    index.refresh()

    assert not (output / ".birdroost").exists()
    assert index.database.count() == 0
