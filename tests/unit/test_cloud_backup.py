import json
from pathlib import Path

from PIL import Image

from birdclass.cloud_backup import build_upload_plan, normalize_prefix, upload_plan
from birdclass.cloud_export import export_archive
from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id


def make_export(tmp_path: Path) -> Path:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (60, 40), "green").save(source)
    output = tmp_path / "output"
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
        "observation": {"country": "西班牙", "region": "", "location": "多尼亚那", "time": "2026-05"},
        "targets": [],
        "copies": [{
            "relative_path": "三趾滨鹬/a.jpg",
            "species_cn": "三趾滨鹬",
            "species_latin": "Calidris alba",
            "target_indices": [0],
        }],
    })
    export_root = tmp_path / "export"
    export_archive(output, export_root, thumbnail_sizes=(64,))
    return export_root


def test_prefix_accepts_user_names():
    assert normalize_prefix("zjq") == "zjq"
    assert normalize_prefix("张三") == "张三"
    assert normalize_prefix(" /bad  name/ ") == "bad_name"
    assert normalize_prefix("") == "default"


def test_build_plan_uses_user_prefix_and_manifest(tmp_path: Path):
    export_root = make_export(tmp_path)
    plan = build_upload_plan(export_root, bucket="bucket-1250000000", region="ap-shanghai", prefix="张三")

    assert not plan.errors
    assert plan.prefix == "张三"
    assert plan.manifest_key == "users/张三/manifest.json"
    assert all(item.key.startswith("users/张三/") for item in plan.items)
    assert any(item.kind == "original" for item in plan.items)
    assert any(item.kind == "thumb_64" for item in plan.items)
    assert plan.items[-1].kind == "manifest"


class FakeClient:
    def __init__(self):
        self.uploaded = []
        self.objects = {}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise RuntimeError("NoSuchKey")
        return {"Content-Length": str(self.objects[Key])}

    def upload_file(self, **kwargs):
        self.uploaded.append(kwargs["Key"])
        self.objects[kwargs["Key"]] = Path(kwargs["LocalFilePath"]).stat().st_size


def test_upload_plan_uploads_and_skips_existing(tmp_path: Path, monkeypatch):
    export_root = make_export(tmp_path)
    plan = build_upload_plan(export_root, bucket="bucket-1250000000", region="ap-shanghai", prefix="zjq")
    fake = FakeClient()
    monkeypatch.setattr("birdclass.cloud_backup.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_backup.CosS3Client", lambda config: fake)

    first = upload_plan(plan, secret_id="id", secret_key="key")
    assert first.failed == 0
    assert first.uploaded == len(plan.items)
    assert first.skipped == 0

    second = upload_plan(plan, secret_id="id", secret_key="key")
    assert second.failed == 0
    assert second.uploaded == 0
    assert second.skipped == len(plan.items)


def test_upload_requires_credentials(tmp_path: Path):
    export_root = make_export(tmp_path)
    plan = build_upload_plan(export_root, bucket="bucket-1250000000", region="ap-shanghai", prefix="zjq")

    report = upload_plan(plan, secret_id="", secret_key="")

    assert report.failed == 1
    assert "SecretId" in report.errors[0]
