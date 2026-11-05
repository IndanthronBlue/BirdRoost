import json
from pathlib import Path

from PIL import Image

from birdclass.cloud_export import export_archive
from birdclass.cloud_state import load_state
from birdclass.cloud_sync import sync_manifest
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id


def make_library(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (60, 40), "green").save(source)
    output = tmp_path / "library"
    library = ArchiveLibrary(output)
    library.ensure()
    image = output / "三趾滨鹬" / "a.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(source.read_bytes())
    library.write_group({
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": new_batch_id(),
        "status": "completed",
        "observation": {},
        "targets": [],
        "copies": [{
            "relative_path": "三趾滨鹬/a.jpg",
            "species_cn": "三趾滨鹬",
            "species_latin": "Calidris alba",
            "target_indices": [0],
        }],
    })
    return output, tmp_path / "export"


class FakeClient:
    def __init__(self, remote_revision=None):
        self.remote_revision = remote_revision
        self.uploaded = []

    def upload_file(self, **kwargs):
        self.uploaded.append((kwargs["Key"], Path(kwargs["LocalFilePath"]).read_bytes()))

    def download_file(self, Bucket, Key, DestFilePath, **kwargs):
        if self.remote_revision is None:
            raise RuntimeError("NoSuchKey")
        Path(DestFilePath).write_text(json.dumps({"schema_version": 2, "revision": self.remote_revision}))


def test_manifest_only_sync_updates_state(tmp_path: Path, monkeypatch):
    output, export = make_library(tmp_path)
    fake = FakeClient()
    monkeypatch.setattr("birdclass.cloud_sync.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_sync.CosS3Client", lambda config: fake)

    report = sync_manifest(
        output, export,
        bucket="bucket-1250000000", region="ap-shanghai", endpoint="",
        secret_id="id", secret_key="key", prefix="zjq",
    )

    assert report.uploaded
    assert report.error == ""
    assert fake.uploaded[0][0] == "users/zjq/manifest.json"
    manifest = json.loads(fake.uploaded[0][1])
    assert manifest["schema_version"] == 2
    state = load_state(output)
    assert state.base_revision == report.revision
    assert state.dirty is False


def test_manifest_sync_blocks_on_remote_conflict(tmp_path: Path, monkeypatch):
    output, export = make_library(tmp_path)
    fake = FakeClient(remote_revision=99)
    monkeypatch.setattr("birdclass.cloud_sync.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_sync.CosS3Client", lambda config: fake)

    report = sync_manifest(
        output, export,
        bucket="bucket-1250000000", region="ap-shanghai", endpoint="",
        secret_id="id", secret_key="key", prefix="zjq",
    )

    assert not report.uploaded
    assert "revision" in report.error
    assert fake.uploaded == []


def test_manifest_sync_can_force_override_remote(tmp_path: Path, monkeypatch):
    output, export = make_library(tmp_path)
    fake = FakeClient(remote_revision=99)
    monkeypatch.setattr("birdclass.cloud_sync.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_sync.CosS3Client", lambda config: fake)

    report = sync_manifest(
        output, export,
        bucket="bucket-1250000000", region="ap-shanghai", endpoint="",
        secret_id="id", secret_key="key", prefix="zjq", force=True,
    )

    assert report.uploaded
    assert fake.uploaded
