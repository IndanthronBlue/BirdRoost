from pathlib import Path

from PIL import Image

from birdclass.archive_cleanup import cleanup_missing_copies
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
