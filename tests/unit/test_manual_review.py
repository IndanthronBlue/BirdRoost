import json
from pathlib import Path

from PIL import Image

from birdclass.archive_index import ArchiveIndex
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id
from birdclass.manual_review import delete_archive_photo, resolve_manual


def make_pending_group(tmp_path: Path, status: str = "failed") -> tuple[ArchiveLibrary, object, dict]:
    output = tmp_path / "output"
    pending = output / "待复核" / "bird.jpg"
    pending.parent.mkdir(parents=True)
    Image.new("RGB", (40, 30), "green").save(pending)
    library = ArchiveLibrary(output)
    library.ensure()
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": new_batch_id(),
        "status": status,
        "source_relative_path": "bird.jpg",
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
    entry = ArchiveIndex(output).refresh()[0]
    return library, entry, group


def test_manual_archive_moves_pending_and_completes_group(tmp_path: Path):
    library, entry, group = make_pending_group(tmp_path)

    new_relative = resolve_manual(library, entry, action="manual", name="三趾滨鹬")

    assert new_relative.startswith("三趾滨鹬/")
    assert (library.output_root / new_relative).is_file()
    assert not (library.output_root / "待复核/bird.jpg").exists()
    updated = library.read_group(group["group_id"])
    assert updated["status"] == "completed"
    assert updated["copies"][0]["relative_path"] == new_relative
    assert updated["copies"][0]["species_cn"] == "三趾滨鹬"
    assert library.load_corrections()[-1]["action"] == "manual_archive"


def test_no_bird_non_bird_and_scenery_destinations(tmp_path: Path):
    for action, folder, status in (
        ("no_bird", "无鸟", "no_bird"),
        ("non_bird_animal", "非鸟动物", "non_bird_animal"),
        ("scenery", "风景", "scenery"),
    ):
        library, entry, group = make_pending_group(tmp_path / action)

        resolve_manual(library, entry, action=action)

        moved = list((library.output_root / folder).rglob("bird.jpg"))
        assert moved
        updated = library.read_group(group["group_id"])
        assert updated["status"] == status
        assert updated["copies"][0]["relative_path"].startswith(f"{folder}/")


def test_delete_photo_moves_to_deleted_and_updates_group(tmp_path: Path):
    library, entry, group = make_pending_group(tmp_path)

    new_relative = delete_archive_photo(library, entry)

    assert new_relative.startswith("已删除/")
    assert (library.output_root / new_relative).is_file()
    assert not (library.output_root / "待复核/bird.jpg").exists()
    updated = library.read_group(group["group_id"])
    assert updated["status"] == "deleted"
    assert updated["copies"] == []
