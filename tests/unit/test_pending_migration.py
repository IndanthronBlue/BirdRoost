from pathlib import Path

from PIL import Image

from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id
from birdclass.pending_migration import migrate_pending_copies


def test_existing_pending_group_is_renamed_with_location_and_time(tmp_path: Path):
    output = tmp_path / "output"
    pending = output / "待复核" / "bird.jpg"
    pending.parent.mkdir(parents=True)
    Image.new("RGB", (20, 20), "green").save(pending)
    library = ArchiveLibrary(output)
    library.ensure()
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": new_batch_id(),
        "status": "failed",
        "source_relative_path": "bird.jpg",
        "observation": {"location": "荷兰", "time": "2602"},
        "targets": [],
        "copies": [{
            "relative_path": "待复核/bird.jpg",
            "species_cn": "",
            "species_latin": "",
            "target_indices": [],
            "pending": True,
        }],
    }
    library.write_group(group)

    result = migrate_pending_copies(output, [])

    assert result.renamed == 1
    renamed = output / "待复核" / "荷兰_2602_bird.jpg"
    assert renamed.is_file()
    updated = library.read_group(group["group_id"])
    assert updated["copies"][0]["relative_path"] == "待复核/荷兰_2602_bird.jpg"


def test_merge_duplicate_source_groups_keeps_one_group(tmp_path: Path):
    from birdclass.archive_index import ArchiveIndex
    from birdclass.library import new_batch_id, new_group_id
    from birdclass.pending_migration import merge_duplicate_source_groups

    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    batch = new_batch_id()
    primary = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": batch,
        "status": "review_pending",
        "source_relative_path": "same.jpg",
        "targets": [{"target_index": 0, "selection": None}],
        "copies": [{"relative_path": "三趾滨鹬/same.jpg", "species_cn": "三趾滨鹬", "target_indices": []}],
    }
    duplicate = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": batch,
        "status": "review_pending",
        "source_relative_path": "same.jpg",
        "targets": [{"target_index": 1, "selection": None}],
        "copies": [{"relative_path": "待复核/same.jpg", "species_cn": "", "target_indices": [], "pending": True}],
    }
    library.write_group(primary)
    library.write_group(duplicate)

    removed = merge_duplicate_source_groups(output)

    assert removed == 1
    groups = [g for g in library.load_groups() if g["source_relative_path"] == "same.jpg"]
    assert len(groups) == 1
    assert len(groups[0]["targets"]) == 2
    assert len(groups[0]["copies"]) == 2
