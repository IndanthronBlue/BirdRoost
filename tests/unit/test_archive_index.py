from pathlib import Path

from PIL import Image

from birdclass.archive_index import ArchiveIndex
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id
from birdclass.taxonomy import load_taxonomy


def make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 20), "green").save(path)


def make_group(library: ArchiveLibrary, relative_path: str, *, batch_id: str, species_cn: str,
               species_latin: str, box: list[float] | None = None) -> dict:
    group_id = new_group_id()
    group = {
        "schema_version": 1,
        "group_id": group_id,
        "batch_id": batch_id,
        "status": "completed",
        "targets": [{
            "target_index": 0,
            "box": box,
            "selection": {
                "species_cn": species_cn,
                "species_latin": species_latin,
            },
        }],
        "copies": [{
            "relative_path": relative_path,
            "species_cn": species_cn,
            "species_latin": species_latin,
            "target_indices": [0],
        }],
    }
    library.write_group(group)
    return group


def test_index_scans_species_special_and_ignores_library(tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    make_image(output / "待复核" / "b.jpg")
    make_image(output / "已纠正" / "2026" / "c.jpg")
    make_image(output / "未收录鸟" / "d.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    batch_id = new_batch_id()
    group = make_group(
        library, "三趾滨鹬/a.jpg", batch_id=batch_id,
        species_cn="三趾滨鹬", species_latin="Calidris alba", box=[0.1, 0.2, 0.8, 0.9],
    )

    index = ArchiveIndex(output)
    entries = index.refresh()

    by_path = {entry.relative_path: entry for entry in entries}
    assert ".birdroost/library.json" not in by_path
    assert by_path["三趾滨鹬/a.jpg"].taxonomy.scientific_name == "Calidris alba"
    assert by_path["三趾滨鹬/a.jpg"].group_id == group["group_id"]
    assert by_path["三趾滨鹬/a.jpg"].target_indices == (0,)
    assert by_path["三趾滨鹬/a.jpg"].has_boxes is True
    assert by_path["待复核/b.jpg"].special == "待复核"
    assert by_path["已纠正/2026/c.jpg"].special == "已纠正"
    assert by_path["未收录鸟/d.jpg"].tree_path == ("未收录", "未收录鸟")


def test_filter_by_tree_batch_and_search(tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    make_image(output / "欧乌鸫" / "b.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    batch_a = new_batch_id()
    batch_b = new_batch_id()
    make_group(library, "三趾滨鹬/a.jpg", batch_id=batch_a,
               species_cn="三趾滨鹬", species_latin="Calidris alba")
    make_group(library, "欧乌鸫/b.jpg", batch_id=batch_b,
               species_cn="欧乌鸫", species_latin="Turdus merula")
    index = ArchiveIndex(output)
    index.refresh()

    assert [entry.relative_path for entry in index.filter_entries(batch_id=batch_a)] == [
        "三趾滨鹬/a.jpg"
    ]
    assert [entry.relative_path for entry in index.filter_entries(search="Turdus")] == [
        "欧乌鸫/b.jpg"
    ]
    assert {entry.relative_path for entry in index.filter_entries(tree_path=("未收录",))} == set()


def test_refresh_adds_new_species_without_recreating_index(tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "欧乌鸫" / "a.jpg")
    index = ArchiveIndex(output)
    index.refresh()
    assert [entry.species_cn for entry in index.entries] == ["欧乌鸫"]

    make_image(output / "三趾滨鹬" / "b.jpg")
    index.refresh()

    assert {entry.species_cn for entry in index.entries} == {"欧乌鸫", "三趾滨鹬"}
    assert index.count_by_tree_path()[index.entries[0].tree_path] >= 1


def test_aliases_resolve_archived_folder(tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "北灰鶲" / "a.jpg")
    index = ArchiveIndex(output)
    index.refresh()

    assert index.entries[0].taxonomy.scientific_name == "Muscicapa dauurica"
    assert index.entries[0].tree_path[-1] == "Muscicapa dauurica"


def test_taxonomy_snapshot_is_injected(tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    taxonomy = load_taxonomy()
    index = ArchiveIndex(output, taxonomy=taxonomy)
    index.refresh()

    assert index.entries[0].taxonomy is taxonomy.resolve(scientific_name="Calidris alba")
