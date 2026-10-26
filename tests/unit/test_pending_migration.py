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
