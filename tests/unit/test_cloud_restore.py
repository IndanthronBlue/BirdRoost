import json
from pathlib import Path

from PIL import Image

from birdclass.cloud_export import export_archive
from birdclass.cloud_restore import restore_from_cos
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id


def make_export(tmp_path: Path) -> Path:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (60, 40), "green").save(source)
    output = tmp_path / "old"
    library = ArchiveLibrary(output)
    library.ensure()
    for index, species in enumerate(("三趾滨鹬", "欧乌鸫")):
        relative = f"{species}/a.jpg"
        image = output / relative
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(source.read_bytes())
        library.write_group({
            "schema_version": 1,
            "group_id": new_group_id(),
            "batch_id": new_batch_id(),
            "status": "completed",
            "observation": {"country": "西班牙", "region": "", "location": "多尼亚那", "time": "2026-05"},
            "targets": [],
            "copies": [{
                "relative_path": relative,
                "species_cn": species,
                "species_latin": "Calidris alba" if index == 0 else "Turdus merula",
                "target_indices": [0],
            }],
        })
    export = tmp_path / "export"
    export_archive(output, export)
    return export


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


def test_restore_rebuilds_groups_and_reuses_shared_photo(tmp_path: Path, monkeypatch):
    export = make_export(tmp_path)
    manifest = json.loads((export / "manifest.json").read_text(encoding="utf-8"))
    photo = manifest["photos"][0]
    source = Path(manifest["source_root"]) / manifest["copies"][0]["local_relative_path"]
    client = FakeDownloadClient({
        f"users/zjq/{photo['original_object_key']}": source,
    })
    monkeypatch.setattr("birdclass.cloud_restore.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_restore.CosS3Client", lambda config: client)

    local = tmp_path / "new"
    report = restore_from_cos(
        local, manifest,
        bucket="bucket-1250000000", region="ap-shanghai", endpoint="",
        secret_id="id", secret_key="key", prefix="zjq",
    )

    assert report.failed == 0
    assert report.groups == 2
    assert report.copies == 2
    assert len(client.calls) == 1
    assert len(list((local / "三趾滨鹬").glob("*.jpg"))) == 1
    assert len(list((local / "欧乌鸫").glob("*.jpg"))) == 1
    library = ArchiveLibrary(local)
    groups = library.load_groups()
    assert len(groups) == 2
    assert all(group["cloud_restored"] for group in groups)
