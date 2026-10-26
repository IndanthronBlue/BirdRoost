from pathlib import Path

import pytest
from PIL import Image

from birdclass.archive_index import ArchiveIndex
from birdclass.correction import CorrectionError, correct_archive_copy
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id
from birdclass.taxonomy import load_taxonomy


def make_copy(tmp_path: Path, *, target_count: int = 1) -> tuple[ArchiveLibrary, object, dict]:
    output = tmp_path / "output"
    image_path = output / "三趾滨鹬" / "a.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (40, 30), "green").save(image_path)
    library = ArchiveLibrary(output)
    library.ensure()
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": new_batch_id(),
        "status": "completed",
        "targets": [
            {
                "target_index": index,
                "box": [0.1, 0.1, 0.4, 0.4],
                "selection": {
                    "species_cn": "三趾滨鹬",
                    "species_latin": "Calidris alba",
                },
            }
            for index in range(target_count)
        ],
        "copies": [{
            "relative_path": "三趾滨鹬/a.png",
            "species_cn": "三趾滨鹬",
            "species_latin": "Calidris alba",
            "target_indices": list(range(target_count)),
        }],
    }
    library.write_group(group)
    entry = ArchiveIndex(output).refresh()[0]
    return library, entry, group


def test_correct_whole_copy_moves_old_to_replaced(tmp_path: Path):
    library, entry, group = make_copy(tmp_path)
    taxon = load_taxonomy().resolve(scientific_name="Calidris ruficollis")
    assert taxon is not None

    outcome = correct_archive_copy(library, entry, taxon)

    assert outcome.new_relative_path.startswith("红颈滨鹬/")
    assert (library.output_root / outcome.new_relative_path).is_file()
    assert not (library.output_root / "三趾滨鹬/a.png").exists()
    assert outcome.replaced_relative_path == ""
    assert not (library.output_root / "已纠正").exists()
    updated = library.read_group(group["group_id"])
    assert updated["copies"][0]["relative_path"] == outcome.new_relative_path
    assert updated["copies"][0]["species_cn"] == "红颈滨鹬"
    assert updated["targets"][0]["selection"]["species_latin"] == "Calidris ruficollis"
    records = library.load_corrections()
    assert records[-1]["new_relative_path"] == outcome.new_relative_path
    assert records[-1]["old_copy_action"] == "moved"


def test_correct_single_target_splits_shared_copy(tmp_path: Path):
    library, entry, group = make_copy(tmp_path, target_count=2)
    taxon = load_taxonomy().resolve(scientific_name="Calidris ruficollis")
    assert taxon is not None

    outcome = correct_archive_copy(library, entry, taxon, target_indices={0})

    assert outcome.split is True
    assert (library.output_root / "三趾滨鹬/a.png").is_file()
    assert (library.output_root / outcome.new_relative_path).is_file()
    updated = library.read_group(group["group_id"])
    old_copy = next(copy for copy in updated["copies"] if copy["relative_path"] == "三趾滨鹬/a.png")
    new_copy = next(
        copy for copy in updated["copies"] if copy["relative_path"] == outcome.new_relative_path
    )
    assert old_copy["target_indices"] == [1]
    assert new_copy["target_indices"] == [0]
    assert updated["targets"][0]["selection"]["species_cn"] == "红颈滨鹬"
    assert updated["targets"][1]["selection"]["species_cn"] == "三趾滨鹬"
    assert library.load_corrections()[-1]["old_copy_action"] == "kept"


def test_same_species_is_rejected(tmp_path: Path):
    library, entry, _group = make_copy(tmp_path)
    taxon = load_taxonomy().resolve(scientific_name="Calidris alba")
    assert taxon is not None

    with pytest.raises(CorrectionError, match="相同"):
        correct_archive_copy(library, entry, taxon)


def test_filename_collision_gets_unique_suffix(tmp_path: Path):
    library, entry, _group = make_copy(tmp_path)
    taxon = load_taxonomy().resolve(scientific_name="Calidris ruficollis")
    assert taxon is not None
    existing = tmp_path / "output" / "红颈滨鹬" / "三趾滨鹬_a.png"
    existing.parent.mkdir(parents=True)
    Image.new("RGB", (10, 10), "red").save(existing)

    outcome = correct_archive_copy(library, entry, taxon)

    assert outcome.new_relative_path != "红颈滨鹬/三趾滨鹬_a.png"
    assert (tmp_path / "output" / outcome.new_relative_path).is_file()


def test_missing_copy_is_rejected(tmp_path: Path):
    library, entry, _group = make_copy(tmp_path)
    taxon = load_taxonomy().resolve(scientific_name="Calidris ruficollis")
    assert taxon is not None
    (tmp_path / "output" / "三趾滨鹬/a.png").unlink()

    with pytest.raises(CorrectionError, match="不存在"):
        correct_archive_copy(library, entry, taxon)


def test_same_taxon_can_be_renamed_to_alias_without_backup(tmp_path: Path):
    output = tmp_path / "output"
    image_path = output / "蓝尾灰喜鹊" / "a.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (40, 30), "green").save(image_path)
    library = ArchiveLibrary(output)
    library.ensure()
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": new_batch_id(),
        "status": "completed",
        "observation": {"location": "塞维利亚", "time": "202512"},
        "targets": [{
            "target_index": 0,
            "box": [0.1, 0.1, 0.4, 0.4],
            "selection": {"species_cn": "蓝尾灰喜鹊", "species_latin": "Cyanopica cooki"},
        }],
        "copies": [{
            "relative_path": "蓝尾灰喜鹊/a.png",
            "species_cn": "蓝尾灰喜鹊",
            "species_latin": "Cyanopica cooki",
            "target_indices": [0],
        }],
    }
    library.write_group(group)
    entry = ArchiveIndex(output).refresh()[0]
    taxon = load_taxonomy().resolve(name_zh="伊比利亚灰喜鹊")
    assert taxon is not None

    outcome = correct_archive_copy(
        library, entry, taxon, new_name="伊比利亚灰喜鹊"
    )

    assert outcome.new_relative_path.startswith("伊比利亚灰喜鹊/")
    assert not (output / "蓝尾灰喜鹊/a.png").exists()
    assert not (output / "已纠正").exists()
    updated = library.read_group(group["group_id"])
    assert updated["copies"][0]["species_cn"] == "伊比利亚灰喜鹊"
    assert updated["copies"][0]["species_latin"] == "Cyanopica cooki"
