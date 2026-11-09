import json
from pathlib import Path

from PIL import Image

from birdclass.cloud_export import copy_id, export_archive
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id


def add_group(library: ArchiveLibrary, relative: str, species: str, latin: str, digest_source: Path) -> dict:
    image = library.output_root / relative
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(digest_source.read_bytes())
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": new_batch_id(),
        "status": "completed",
        "observation": {
            "country": "西班牙", "region": "", "location": "多尼亚那", "time": "2026-05",
        },
        "targets": [],
        "copies": [{
            "relative_path": relative,
            "species_cn": species,
            "species_latin": latin,
            "target_indices": [0],
        }],
    }
    library.write_group(group)
    return group


def test_export_deduplicates_content_and_generates_one_thumbnail_set(tmp_path: Path):
    source = tmp_path / "source.jpg"
    Image.new("RGB", (100, 80), "green").save(source)
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    first = add_group(library, "三趾滨鹬/a.jpg", "三趾滨鹬", "Calidris alba", source)
    second = add_group(library, "欧乌鸫/b.jpg", "欧乌鸫", "Turdus merula", source)

    report = export_archive(output, tmp_path / "export", thumbnail_sizes=(64, 128))

    assert report.photos == 1
    assert report.copies == 2
    assert report.thumbnails == 2
    assert not report.errors
    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["photos"] == 1
    assert len(manifest["groups"]) == 2
    assert {copy["group_id"] for copy in manifest["copies"]} == {first["group_id"], second["group_id"]}
    assert manifest["photos"][0]["variants"][0]["kind"] == "thumb_64"
    assert (tmp_path / "export" / "thumbs" / f"{manifest['photos'][0]['sha256']}_64.webp").is_file()
    assert (tmp_path / "export" / "thumbs" / f"{manifest['photos'][0]['sha256']}_128.webp").is_file()


def test_export_without_thumbnails(tmp_path: Path):
    source = tmp_path / "source.jpg"
    Image.new("RGB", (20, 20), "blue").save(source)
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    add_group(library, "三趾滨鹬/a.jpg", "三趾滨鹬", "Calidris alba", source)

    report = export_archive(output, tmp_path / "export", create_thumbnails=False)

    assert report.thumbnails == 0
    assert not list((tmp_path / "export" / "thumbs").glob("*.webp"))


def test_copy_id_is_stable_and_distinguishes_targets():
    first = copy_id("group-1", "三趾滨鹬", [1, 0])
    second = copy_id("group-1", "三趾滨鹬", [0, 1])
    other = copy_id("group-1", "三趾滨鹬", [2])
    assert first == second
    assert first != other


def test_second_export_skips_existing_thumbnails(tmp_path: Path):
    source = tmp_path / "source.jpg"
    Image.new("RGB", (100, 80), "green").save(source)
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    add_group(library, "三趾滨鹬/a.jpg", "三趾滨鹬", "Calidris alba", source)
    export_root = tmp_path / "export"

    first = export_archive(output, export_root, thumbnail_sizes=(64,))
    second = export_archive(output, export_root, thumbnail_sizes=(64,))

    assert first.thumbnails == 1
    assert second.thumbnails == 0
    assert second.thumbnails_skipped == 1


def test_manifest_v2_has_revision_and_tombstones(tmp_path: Path):
    source = tmp_path / "source.jpg"
    Image.new("RGB", (20, 20), "green").save(source)
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    group = add_group(library, "三趾滨鹬/a.jpg", "三趾滨鹬", "Calidris alba", source)
    from birdclass.cloud_state import add_tombstone

    add_tombstone(
        output,
        group_id=group["group_id"],
        species_cn="三趾滨鹬",
        target_indices=(0,),
        local_relative_path="三趾滨鹬/a.jpg",
    )
    export = tmp_path / "export"
    first = export_archive(output, export)
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 2
    assert manifest["library_id"]
    assert manifest["device_id"]
    assert manifest["revision"] >= 1
    assert manifest["tombstones"]

    second = export_archive(output, export)
    new_manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert new_manifest["revision"] > manifest["revision"]


def test_export_skips_review_annotation_copies(tmp_path: Path):
    source = tmp_path / "source.jpg"
    Image.new("RGB", (40, 30), "green").save(source)
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    group = add_group(library, "待复核/bird.jpg", "", "", source)
    annotation = output / "待复核" / "bird_待确认框.jpg"
    Image.new("RGB", (40, 30), "orange").save(annotation)
    group["copies"].append({
        "relative_path": "待复核/bird_待确认框.jpg",
        "species_cn": "",
        "species_latin": "",
        "target_indices": [0],
        "pending": True,
    })
    library.write_group(group)

    report = export_archive(output, tmp_path / "export", thumbnail_sizes=(64,))

    assert report.copies == 1
    assert report.photos == 1
    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    assert [copy["local_relative_path"] for copy in manifest["copies"]] == ["待复核/bird.jpg"]
    assert not list((tmp_path / "export" / "originals").glob("*_待确认框*"))
