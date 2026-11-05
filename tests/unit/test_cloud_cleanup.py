from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from birdclass.cloud_cleanup import cleanup_tombstones
from birdclass.cloud_export import export_archive
from birdclass.cloud_state import add_tombstone
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id


def make_library(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (40, 30), "green").save(source)
    output = tmp_path / "library"
    library = ArchiveLibrary(output)
    library.ensure()
    relative = "三趾滨鹬/a.jpg"
    image = output / relative
    image.parent.mkdir(parents=True)
    image.write_bytes(source.read_bytes())
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": new_batch_id(),
        "status": "completed",
        "observation": {},
        "targets": [],
        "copies": [{
            "relative_path": relative,
            "species_cn": "三趾滨鹬",
            "species_latin": "Calidris alba",
            "target_indices": [0],
        }],
    }
    library.write_group(group)
    return output, tmp_path / "export"


class FakeClient:
    def __init__(self):
        self.deleted = []

    def head_object(self, Bucket, Key):
        if "missing" in Key:
            raise RuntimeError("NoSuchKey")
        return {"Content-Length": 100}

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)


def test_cleanup_is_dry_run_by_default_and_skips_referenced(tmp_path: Path, monkeypatch):
    output, export = make_library(tmp_path)
    export_archive(output, export)
    add_tombstone(
        output, group_id="dead-group", species_cn="死图", target_indices=(0,),
        local_relative_path="死图/x.jpg", photo_id="dead-photo",
        original_object_key="originals/dead-photo.jpg",
        thumbnail_keys=["thumbs/dead-photo_256.webp"],
    )
    add_tombstone(
        output, group_id="live-group", species_cn="活图", target_indices=(0,),
        local_relative_path="活图/x.jpg", photo_id="live-photo",
        original_object_key="originals/live-photo.jpg",
    )
    # Make the live tombstone reference an existing current photo id.
    import json
    manifest = json.loads((export / "manifest.json").read_text())
    current_id = manifest["photos"][0]["photo_id"]
    # Rewrite the tombstone to the current photo id.
    from birdclass.cloud_state import load_state, save_state
    state = load_state(output)
    state.tombstones[-1]["photo_id"] = current_id
    save_state(state_path := output, state)

    fake = FakeClient()
    monkeypatch.setattr("birdclass.cloud_cleanup.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_cleanup.CosS3Client", lambda config: fake)

    report = cleanup_tombstones(
        output, export,
        bucket="bucket-1250000000", region="ap-shanghai", endpoint="",
        secret_id="id", secret_key="key", prefix="zjq",
        retention_days=0, dry_run=True, now=datetime.now(timezone.utc) + timedelta(days=1),
    )

    assert report.dry_run
    assert report.candidates >= 2
    assert report.deleted == 0
    assert fake.deleted == []

    actual = cleanup_tombstones(
        output, export,
        bucket="bucket-1250000000", region="ap-shanghai", endpoint="",
        secret_id="id", secret_key="key", prefix="zjq",
        retention_days=0, dry_run=False, now=datetime.now(timezone.utc) + timedelta(days=1),
    )

    assert actual.deleted >= 2
    assert "users/zjq/originals/dead-photo.jpg" in fake.deleted
    assert not any("live-photo" in key for key in fake.deleted)
