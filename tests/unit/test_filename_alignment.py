from pathlib import Path

from PIL import Image

from birdclass.filename_alignment import align_group_copies
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id


def test_alignment_renames_copy_and_updates_group(tmp_path: Path):
    output = tmp_path / "output"
    old_path = output / "三趾滨鹬" / "伊比利亚_260501_三趾滨鹬_001.jpg"
    old_path.parent.mkdir(parents=True)
    Image.new("RGB", (20, 20), "green").save(old_path)
    library = ArchiveLibrary(output)
    library.ensure()
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": new_batch_id(),
        "status": "completed",
        "observation": {
            "country": "西班牙",
            "region": "",
            "location": "多尼亚那",
            "time": "2026-05",
            "legacy_location": "伊比利亚",
            "legacy_time": "260501",
        },
        "targets": [],
        "copies": [{
            "relative_path": "三趾滨鹬/伊比利亚_260501_三趾滨鹬_001.jpg",
            "species_cn": "三趾滨鹬",
            "species_latin": "Calidris alba",
            "target_indices": [],
        }],
    }

    changes = align_group_copies(library, group)

    assert changes == [(
        "三趾滨鹬/伊比利亚_260501_三趾滨鹬_001.jpg",
        "三趾滨鹬/多尼亚那_2026-05_三趾滨鹬_001.jpg",
    )]
    assert (output / "三趾滨鹬" / "多尼亚那_2026-05_三趾滨鹬_001.jpg").is_file()
    assert not old_path.exists()
    assert group["copies"][0]["relative_path"] == "三趾滨鹬/多尼亚那_2026-05_三趾滨鹬_001.jpg"
