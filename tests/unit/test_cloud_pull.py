import json
from pathlib import Path

from PIL import Image

from birdclass.cloud_export import export_archive
from birdclass.cloud_pull import pull_from_cos
from birdclass.cloud_state import load_state, save_state
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id


def add_group(library: ArchiveLibrary, species: str) -> dict:
    source = library.output_root.parent / f"{species}.jpg"
    Image.new("RGB", (40, 30), "green" if species == "三趾滨鹬" else "blue").save(source)
    relative = f"{species}/{species}.jpg"
    image = library.output_root / relative
    image.parent.mkdir(parents=True, exist_ok=True)
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
            "species_cn": species,
            "species_latin": "Calidris alba",
            "target_indices": [0],
        }],
    }
    library.write_group(group)
    return group


class FakeDownloadClient:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def download_file(self, Bucket, Key, DestFilePath, **kwargs):
        self.calls.append(Key)
        source = self.mapping.get(Key)
        if source is None:
            raise RuntimeError("NoSuchKey")
        Path(DestFilePath).parent.mkdir(parents=True, exist_ok=True)
        Path(DestFilePath).write_bytes(Path(source).read_bytes())


def make_remote(tmp_path: Path) -> tuple[Path, dict, dict]:
    remote = ArchiveLibrary(tmp_path / "remote")
    remote.ensure()
    a = add_group(remote, "三趾滨鹬")
    b = add_group(remote, "欧乌鸫")
    remote_export = tmp_path / "remote-export"
    export_archive(remote.output_root, remote_export)
    manifest = json.loads((remote_export / "manifest.json").read_text())
    mapping = {"users/zjq/manifest.json": remote_export / "manifest.json"}
    for copy in manifest["copies"]:
        photo = next(value for value in manifest["photos"] if value["photo_id"] == copy["photo_id"])
        mapping["users/zjq/" + photo["original_object_key"]] = remote.output_root / copy["local_relative_path"]
    return remote.output_root, manifest, mapping


def test_pull_fast_forwards_and_only_downloads_missing(tmp_path: Path, monkeypatch):
    remote_root, manifest, mapping = make_remote(tmp_path)
    local = ArchiveLibrary(tmp_path / "local")
    local.ensure()
    first_group = next(group for group in manifest["groups"] if any(
        copy.get("species_cn") == "三趾滨鹬" for copy in manifest["copies"]
        if copy.get("group_id") == group.get("group_id")
    ))
    first_copy = next(copy for copy in manifest["copies"] if copy.get("group_id") == first_group["group_id"])
    image = local.output_root / first_copy["local_relative_path"]
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes((remote_root / first_copy["local_relative_path"]).read_bytes())
    local.write_group({
        "schema_version": 1,
        "group_id": first_group["group_id"],
        "batch_id": first_group.get("batch_id", ""),
        "status": "completed",
        "observation": {},
        "targets": [],
        "copies": [{
            "relative_path": first_copy["local_relative_path"],
            "species_cn": first_copy["species_cn"],
            "species_latin": first_copy["species_latin"],
            "target_indices": first_copy["target_indices"],
        }],
    })
    state = load_state(local.output_root)
    state.base_revision = 0
    state.dirty = False
    save_state(local.output_root, state)
    fake = FakeDownloadClient(mapping)
    monkeypatch.setattr("birdclass.cloud_pull.download_manifest", lambda **kwargs: manifest)
    monkeypatch.setattr("birdclass.cloud_restore.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_restore.CosS3Client", lambda config: fake)

    report = pull_from_cos(
        local.output_root,
        bucket="bucket-1250000000", region="ap-shanghai", endpoint="",
        secret_id="id", secret_key="key", prefix="zjq",
    )

    assert report.action == "pulled"
    assert report.errors == []
    assert report.removed_groups == 0
    assert len(local.load_groups()) == 2
    assert (local.output_root / "欧乌鸫" / "欧乌鸫.jpg").is_file()
    assert len(fake.calls) == 1  # manifest + only the missing original
    assert load_state(local.output_root).base_revision == manifest["revision"]


def test_pull_refuses_dirty_local_without_changes(tmp_path: Path, monkeypatch):
    remote_root, manifest, _mapping = make_remote(tmp_path)
    local = ArchiveLibrary(tmp_path / "local")
    local.ensure()
    first_group = next(group for group in manifest["groups"] if any(
        copy.get("species_cn") == "三趾滨鹬" for copy in manifest["copies"]
        if copy.get("group_id") == group.get("group_id")
    ))
    first_copy = next(copy for copy in manifest["copies"] if copy.get("group_id") == first_group["group_id"])
    image = local.output_root / first_copy["local_relative_path"]
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes((remote_root / first_copy["local_relative_path"]).read_bytes())
    local.write_group({
        "schema_version": 1,
        "group_id": first_group["group_id"],
        "batch_id": first_group.get("batch_id", ""),
        "status": "completed",
        "observation": {},
        "targets": [],
        "copies": [{
            "relative_path": first_copy["local_relative_path"],
            "species_cn": first_copy["species_cn"],
            "species_latin": first_copy["species_latin"],
            "target_indices": first_copy["target_indices"],
        }],
    })
    state = load_state(local.output_root)
    state.base_revision = 0
    state.dirty = True
    save_state(local.output_root, state)
    monkeypatch.setattr("birdclass.cloud_pull.download_manifest", lambda **kwargs: manifest)

    report = pull_from_cos(
        local.output_root,
        bucket="bucket-1250000000", region="ap-shanghai", endpoint="",
        secret_id="id", secret_key="key", prefix="zjq",
    )

    assert report.action == "conflict"
    assert report.snapshot_path
    assert len(local.load_groups()) == 1
    assert load_state(local.output_root).dirty is True


def test_unuploaded_manifest_revision_counts_as_dirty(tmp_path: Path, monkeypatch):
    _remote_root, manifest, _mapping = make_remote(tmp_path)
    local = ArchiveLibrary(tmp_path / "local")
    local.ensure()
    add_group(local, "三趾滨鹬")
    state = load_state(local.output_root)
    state.base_revision = 0
    state.revision = 1
    state.dirty = False
    save_state(local.output_root, state)
    monkeypatch.setattr("birdclass.cloud_pull.download_manifest", lambda **kwargs: manifest)

    report = pull_from_cos(
        local.output_root,
        bucket="bucket-1250000000", region="ap-shanghai", endpoint="",
        secret_id="id", secret_key="key", prefix="zjq",
    )

    assert report.action == "conflict"
    assert report.dirty is True
