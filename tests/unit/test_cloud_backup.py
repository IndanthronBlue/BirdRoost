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


class FakeConnectionClient:
    def __init__(self, *, write=True):
        self.write = write
        self.deleted = []

    def head_bucket(self, Bucket):
        return {}

    def head_object(self, Bucket, Key):
        raise RuntimeError("NoSuchKey")

    def put_object(self, Bucket, Key, Body):
        if not self.write:
            raise RuntimeError("AccessDenied")
        return {}

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)
        return {}


def test_connection_checks_write_and_cleans_probe(tmp_path: Path, monkeypatch):
    fake = FakeConnectionClient()
    monkeypatch.setattr("birdclass.cloud_backup.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_backup.CosS3Client", lambda config: fake)

    from birdclass.cloud_backup import test_connection
    report = test_connection(
        bucket="bucket-1250000000", region="ap-shanghai",
        secret_id="id", secret_key="key", prefix="zjq",
    )

    assert report.ok is True
    assert report.write_ok is True
    assert fake.deleted


def test_connection_reports_read_only_key(tmp_path: Path, monkeypatch):
    fake = FakeConnectionClient(write=False)
    monkeypatch.setattr("birdclass.cloud_backup.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_backup.CosS3Client", lambda config: fake)

    from birdclass.cloud_backup import test_connection
    report = test_connection(
        bucket="bucket-1250000000", region="ap-shanghai",
        secret_id="id", secret_key="key", prefix="zjq",
    )

    assert report.ok is False
    assert "写入" in report.error


def test_cancel_then_resume_skips_completed_objects(tmp_path: Path, monkeypatch):
    export_root = make_export(tmp_path)
    plan = build_upload_plan(export_root, bucket="bucket-1250000000", region="ap-shanghai", prefix="zjq")
    fake = FakeClient()
    monkeypatch.setattr("birdclass.cloud_backup.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_backup.CosS3Client", lambda config: fake)
    cancel = {"value": False}

    def progress(done, total, key):
        if done == 1:
            cancel["value"] = True

    first = upload_plan(
        plan, secret_id="id", secret_key="key",
        progress=progress, cancelled=lambda: cancel["value"],
    )

    assert first.cancelled is True
    assert first.uploaded == 1
    assert first.uploaded < len(plan.items)
    assert "下次" in first.errors[0]

    second = upload_plan(plan, secret_id="id", secret_key="key")

    assert second.cancelled is False
    assert second.failed == 0
    assert second.skipped >= 1
    assert second.uploaded + second.skipped == len(plan.items)


def test_upload_blocks_when_remote_revision_is_ahead(tmp_path: Path, monkeypatch):
    export_root = make_export(tmp_path)
    plan = build_upload_plan(export_root, bucket="bucket-1250000000", region="ap-shanghai", prefix="zjq")
    plan.base_revision = 1
    remote = tmp_path / "remote.json"
    remote.write_text(json.dumps({"schema_version": 2, "revision": 5, "device_id": "other"}), encoding="utf-8")

    class ConflictClient(FakeClient):
        def download_file(self, Bucket, Key, DestFilePath, **kwargs):
            Path(DestFilePath).write_bytes(remote.read_bytes())

    fake = ConflictClient()
    monkeypatch.setattr("birdclass.cloud_backup.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_backup.CosS3Client", lambda config: fake)

    report = upload_plan(plan, secret_id="id", secret_key="key")

    assert report.failed == 1
    assert "revision" in report.errors[0]
    assert fake.uploaded == []
    assert report.snapshot_path
    assert Path(report.snapshot_path).is_file()


def test_force_upload_bypasses_remote_revision_conflict(tmp_path: Path, monkeypatch):
    export_root = make_export(tmp_path)
    plan = build_upload_plan(export_root, bucket="bucket-1250000000", region="ap-shanghai", prefix="zjq")
    plan.base_revision = 1
    remote = tmp_path / "remote.json"
    remote.write_text(json.dumps({"schema_version": 2, "revision": 5}), encoding="utf-8")

    class ConflictClient(FakeClient):
        def download_file(self, Bucket, Key, DestFilePath, **kwargs):
            Path(DestFilePath).write_bytes(remote.read_bytes())

    fake = ConflictClient()
    monkeypatch.setattr("birdclass.cloud_backup.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_backup.CosS3Client", lambda config: fake)

    report = upload_plan(plan, secret_id="id", secret_key="key", force=True)

    assert report.failed == 0
    assert fake.uploaded


def test_upload_uses_remote_object_index_to_skip_head(tmp_path: Path, monkeypatch):
    export_root = make_export(tmp_path)
    plan = build_upload_plan(export_root, bucket="bucket-1250000000", region="ap-shanghai", prefix="zjq")
    indexed = [
        {"Key": item.key, "Size": item.size}
        for item in plan.items if item.kind != "manifest"
    ]

    class IndexClient(FakeClient):
        def list_objects(self, **kwargs):
            return {"Contents": indexed, "IsTruncated": "false"}

    fake = IndexClient()
    monkeypatch.setattr("birdclass.cloud_backup.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_backup.CosS3Client", lambda config: fake)

    report = upload_plan(plan, secret_id="id", secret_key="key")

    assert report.used_remote_index
    assert report.skipped == len(indexed)
    assert fake.uploaded == [plan.manifest_key]


def test_upload_reports_missing_count_before_uploading(tmp_path: Path, monkeypatch):
    export_root = make_export(tmp_path)
    plan = build_upload_plan(export_root, bucket="bucket-1250000000", region="ap-shanghai", prefix="zjq")
    indexed = [
        {"Key": item.key, "Size": item.size}
        for item in plan.items if item.kind != "manifest"
    ]

    class IndexClient(FakeClient):
        def list_objects(self, **kwargs):
            return {"Contents": indexed, "IsTruncated": "false"}

    fake = IndexClient()
    monkeypatch.setattr("birdclass.cloud_backup.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_backup.CosS3Client", lambda config: fake)
    prepared = []

    report = upload_plan(
        plan, secret_id="id", secret_key="key",
        prepared=lambda total, missing, indexed: prepared.append((total, missing, indexed)),
    )

    assert prepared == [(len(plan.items), 1, True)]
    assert report.uploaded == 1
    assert report.skipped == len(indexed)


class AuthError(Exception):
    def get_status_code(self):
        return 403

    def get_error_code(self):
        return "SignatureDoesNotMatch"


def test_upload_stops_before_upload_on_signature_error(tmp_path: Path, monkeypatch):
    export_root = make_export(tmp_path)
    plan = build_upload_plan(export_root, bucket="bucket-1250000000", region="ap-shanghai", prefix="zjq")

    class AuthClient(FakeClient):
        def list_objects(self, **kwargs):
            raise AuthError("bad signature")

        def head_object(self, Bucket, Key):
            raise AuthError("bad signature")

    fake = AuthClient()
    monkeypatch.setattr("birdclass.cloud_backup.CosConfig", lambda **kwargs: object())
    monkeypatch.setattr("birdclass.cloud_backup.CosS3Client", lambda config: fake)

    report = upload_plan(plan, secret_id="id", secret_key="key")

    assert report.failed == 1
    assert "凭证校验失败" in report.errors[0]
    assert fake.uploaded == []
