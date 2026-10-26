import json
from pathlib import Path

from PIL import Image

from birdclass.archive_index import ArchiveIndex
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id
from birdclass.manual_review import (
    apply_species_to_all_targets, delete_archive_photo, resolve_manual,
)


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


def test_apply_species_to_all_targets_removes_pending(tmp_path: Path):
    output = tmp_path / "output"
    species_copy = output / "弯嘴滨鹬" / "a.jpg"
    pending_copy = output / "待复核" / "a.jpg"
    species_copy.parent.mkdir(parents=True)
    pending_copy.parent.mkdir(parents=True)
    Image.new("RGB", (40, 30), "green").save(species_copy)
    Image.new("RGB", (40, 30), "green").save(pending_copy)
    library = ArchiveLibrary(output)
    library.ensure()
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": new_batch_id(),
        "status": "review_pending",
        "source_relative_path": "a.jpg",
        "targets": [
            {"target_index": 0, "selection": {"species_cn": "弯嘴滨鹬"}},
            {"target_index": 1, "selection": None},
            {"target_index": 2, "selection": None},
        ],
        "copies": [
            {"relative_path": "弯嘴滨鹬/a.jpg", "species_cn": "弯嘴滨鹬", "target_indices": [0]},
            {"relative_path": "待复核/a.jpg", "species_cn": "", "target_indices": [], "pending": True},
        ],
    }
    library.write_group(group)
    entry = next(e for e in ArchiveIndex(output).refresh() if e.relative_path == "弯嘴滨鹬/a.jpg")

    count = apply_species_to_all_targets(library, entry)

    assert count == 3
    updated = library.read_group(group["group_id"])
    assert updated["status"] == "completed"
    assert all(target["selection"]["species_cn"] == "弯嘴滨鹬" for target in updated["targets"])
    assert not pending_copy.exists()
    assert all(not copy.get("pending") for copy in updated["copies"])


def test_manual_archive_reuses_existing_species_copy_for_remaining_targets(tmp_path: Path):
    output = tmp_path / "output"
    black = output / "黑腹滨鹬" / "a.jpg"
    red = output / "红腹滨鹬" / "a.jpg"
    pending = output / "待复核" / "a.jpg"
    for path in (black, red, pending):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (40, 30), "green").save(path)
    library = ArchiveLibrary(output)
    library.ensure()
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": new_batch_id(),
        "status": "review_pending",
        "source_relative_path": "a.jpg",
        "targets": [
            {"target_index": 0, "selection": {"species_cn": "黑腹滨鹬", "species_latin": "Calidris alpina"}},
            {"target_index": 1, "selection": {"species_cn": "红腹滨鹬", "species_latin": "Calidris canutus"}},
            {"target_index": 2, "selection": None},
            {"target_index": 3, "selection": None},
        ],
        "copies": [
            {"relative_path": "黑腹滨鹬/a.jpg", "species_cn": "黑腹滨鹬", "species_latin": "Calidris alpina", "target_indices": [0]},
            {"relative_path": "红腹滨鹬/a.jpg", "species_cn": "红腹滨鹬", "species_latin": "Calidris canutus", "target_indices": [1]},
            {"relative_path": "待复核/a.jpg", "species_cn": "", "species_latin": "", "target_indices": [], "pending": True},
        ],
    }
    library.write_group(group)
    entry = next(e for e in ArchiveIndex(output).refresh() if e.relative_path == "黑腹滨鹬/a.jpg")

    new_relative = resolve_manual(library, entry, action="manual", name="黑腹滨鹬")

    assert new_relative == "黑腹滨鹬/a.jpg"
    assert not pending.exists()
    assert sorted(path.name for path in (output / "黑腹滨鹬").iterdir()) == ["a.jpg"]
    updated = library.read_group(group["group_id"])
    assert updated["status"] == "completed"
    black_copy = next(c for c in updated["copies"] if c["species_cn"] == "黑腹滨鹬")
    assert black_copy["target_indices"] == [0, 2, 3]
    assert [target["selection"]["species_cn"] for target in updated["targets"]] == [
        "黑腹滨鹬", "红腹滨鹬", "黑腹滨鹬", "黑腹滨鹬"
    ]


def test_non_bird_animal_accepts_note_and_folders_by_note(tmp_path: Path):
    library, entry, group = make_pending_group(tmp_path / "nonbird")

    resolve_manual(library, entry, action="non_bird_animal", label="蜥蜴")

    moved = list((library.output_root / "非鸟动物" / "蜥蜴").rglob("bird.jpg"))
    assert moved
    updated = library.read_group(group["group_id"])
    assert updated["label"] == "蜥蜴"
    assert updated["status"] == "non_bird_animal"
