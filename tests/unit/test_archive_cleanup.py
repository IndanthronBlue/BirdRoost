from pathlib import Path

from PIL import Image

from birdclass.archive_cleanup import cleanup_missing_copies, cleanup_review_annotations
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id


def make_group(library: ArchiveLibrary, copies: list[dict], status: str = "review_pending") -> dict:
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": new_batch_id(),
        "status": status,
        "observation": {},
        "targets": [],
        "copies": copies,
    }
    library.write_group(group)
    return group


def test_cleanup_removes_missing_copy_but_keeps_valid_group(tmp_path: Path):
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    valid = output / "三趾滨鹬" / "a.jpg"
    valid.parent.mkdir(parents=True)
    Image.new("RGB", (20, 20), "green").save(valid)
    group = make_group(library, [
        {"relative_path": "三趾滨鹬/a.jpg"},
        {"relative_path": "待复核/missing.jpg"},
    ])

    report = cleanup_missing_copies(library)

    assert report.missing_copies == 1
    assert report.quarantined_groups == 0
    updated = library.read_group(group["group_id"])
    assert [c["relative_path"] for c in updated["copies"]] == ["三趾滨鹬/a.jpg"]


def test_cleanup_quarantines_group_when_all_copies_missing(tmp_path: Path):
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    group = make_group(library, [{"relative_path": "待复核/missing.jpg"}])

    report = cleanup_missing_copies(library)

    assert report.quarantined_groups == 1
    assert not (library.groups_dir / f"{group['group_id']}.json").exists()
    assert list((library.root / "quarantine" / "groups").rglob(f"{group['group_id']}.json"))


def test_cleanup_quarantines_empty_group(tmp_path: Path):
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    group = make_group(library, [], status="failed")

    report = cleanup_missing_copies(library)

    assert report.quarantined_groups == 1
    assert not (library.groups_dir / f"{group['group_id']}.json").exists()


def test_cleanup_dry_run_does_not_change_files(tmp_path: Path):
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    group = make_group(library, [{"relative_path": "待复核/missing.jpg"}])

    report = cleanup_missing_copies(library, dry_run=True)

    assert report.quarantined_groups == 1
    assert (library.groups_dir / f"{group['group_id']}.json").exists()


def test_cleanup_review_annotations_dry_run_has_no_side_effects(tmp_path: Path):
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    pending = output / "风景" / "20260101-120000" / "待复核"
    pending.mkdir(parents=True)
    Image.new("RGB", (20, 20), "green").save(pending / "bird.jpg")
    Image.new("RGB", (20, 20), "orange").save(pending / "bird_待确认框.jpg")
    group = make_group(library, [
        {"relative_path": "风景/20260101-120000/待复核/bird.jpg"},
        {"relative_path": "风景/20260101-120000/待复核/bird_待确认框.jpg"},
    ], status="scenery")

    report = cleanup_review_annotations(library, dry_run=True)

    assert report.annotation_copies == 1
    assert report.annotation_files == 1
    assert report.flattened_copies == 1
    assert report.changed_groups == 1
    assert (pending / "bird.jpg").is_file()
    assert (pending / "bird_待确认框.jpg").is_file()
    assert [c["relative_path"] for c in library.read_group(group["group_id"])["copies"]] == [
        "风景/20260101-120000/待复核/bird.jpg",
        "风景/20260101-120000/待复核/bird_待确认框.jpg",
    ]


def test_cleanup_review_annotations_removes_helpers_and_flattens(tmp_path: Path):
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    pending = output / "风景" / "20260101-120000" / "待复核"
    pending.mkdir(parents=True)
    Image.new("RGB", (20, 20), "green").save(pending / "bird.jpg")
    Image.new("RGB", (20, 20), "orange").save(pending / "bird_待确认框.jpg")
    group = make_group(library, [
        {"relative_path": "风景/20260101-120000/待复核/bird.jpg"},
        {"relative_path": "风景/20260101-120000/待复核/bird_待确认框.jpg"},
    ], status="scenery")
    backup = tmp_path / "backup"

    report = cleanup_review_annotations(library, dry_run=False, backup_root=backup)

    assert not report.errors
    assert not (pending / "bird_待确认框.jpg").exists()
    assert not pending.exists()
    moved = output / "风景" / "20260101-120000" / "bird.jpg"
    assert moved.is_file()
    updated = library.read_group(group["group_id"])
    assert [c["relative_path"] for c in updated["copies"]] == [
        "风景/20260101-120000/bird.jpg"
    ]
    assert (backup / "removed" / "风景" / "20260101-120000" / "待复核" / "bird_待确认框.jpg").is_file()
    assert (backup / "groups" / f"{group['group_id']}.json").is_file()
    corrections = (library.root / "corrections.jsonl").read_text(encoding="utf-8")
    assert "cleanup_review_annotations" in corrections


def test_cleanup_review_annotations_quarantines_annotation_only_group(tmp_path: Path):
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    pending = output / "待复核"
    pending.mkdir(parents=True)
    Image.new("RGB", (20, 20), "orange").save(pending / "bird_待确认框.jpg")
    group = make_group(library, [
        {"relative_path": "待复核/bird_待确认框.jpg"},
    ], status="failed")

    report = cleanup_review_annotations(library, dry_run=False, backup_root=tmp_path / "backup")

    assert report.quarantined_groups == 1
    assert not (pending / "bird_待确认框.jpg").exists()
    assert not (library.groups_dir / f"{group['group_id']}.json").exists()

    second = cleanup_review_annotations(library, dry_run=False, backup_root=tmp_path / "backup2")
    assert second.changed_groups == 0
    assert second.annotation_files == 0


def test_cleanup_review_annotations_flatten_collision_is_renamed(tmp_path: Path):
    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    pending = output / "风景" / "20260101-120000" / "待复核"
    pending.mkdir(parents=True)
    Image.new("RGB", (20, 20), "green").save(pending / "bird.jpg")
    existing = output / "风景" / "20260101-120000" / "bird.jpg"
    Image.new("RGB", (20, 20), "blue").save(existing)
    group = make_group(library, [
        {"relative_path": "风景/20260101-120000/待复核/bird.jpg"},
    ], status="scenery")

    report = cleanup_review_annotations(library, dry_run=False, backup_root=tmp_path / "backup")

    assert not report.errors
    assert existing.is_file()
    assert (output / "风景" / "20260101-120000" / "bird_002.jpg").is_file()
    updated = library.read_group(group["group_id"])
    assert [c["relative_path"] for c in updated["copies"]] == [
        "风景/20260101-120000/bird_002.jpg"
    ]
