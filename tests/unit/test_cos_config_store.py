from PySide6.QtCore import QSettings

from birdclass.ui.cos_config_store import (
    CosConfig,
    config_summary,
    load_cos_config,
    resolve_credentials,
    save_cos_config,
)


def test_cos_config_round_trip_and_secret_storage(tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    saved = []
    deleted = []
    monkeypatch.setattr(
        "birdclass.ui.cos_config_store.save_cos_credentials",
        lambda secret_id, secret_key: saved.append((secret_id, secret_key)) or True,
    )
    monkeypatch.setattr(
        "birdclass.ui.cos_config_store.delete_cos_credentials",
        lambda: deleted.append(True) or True,
    )
    monkeypatch.setattr(
        "birdclass.ui.cos_config_store.load_cos_credentials",
        lambda: ("secret-id", "secret-key"),
    )

    ok, _ = save_cos_config(settings, CosConfig(
        bucket="bucket-1250000000", region="ap-shanghai", prefix="zjq",
        secret_id="secret-id", secret_key="secret-key", save_config=True,
    ))
    assert ok
    assert saved[-1] == ("secret-id", "secret-key")

    loaded = load_cos_config(settings)
    assert loaded.bucket == "bucket-1250000000"
    assert loaded.secret_id == "secret-id"
    assert loaded.secret_key == "secret-key"
    assert loaded.save_config is True
    assert "users/zjq/" in config_summary(loaded)

    ok, _ = save_cos_config(settings, CosConfig(save_config=False))
    assert ok
    assert deleted
    assert settings.value("cloud_bucket") is None


def test_resolve_credentials_prefers_config_and_supports_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TENCENTCLOUD_SECRET_ID", "env-id")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_KEY", "env-key")

    assert resolve_credentials(CosConfig()) == ("env-id", "env-key")
    assert resolve_credentials(CosConfig(secret_id="field-id", secret_key="field-key")) == (
        "field-id", "field-key"
    )


def test_resolve_export_root_handles_empty_setting(tmp_path):
    from birdclass.ui.cos_config_store import resolve_export_root

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    library = tmp_path / "鸟"

    assert resolve_export_root(settings, library) == tmp_path / "鸟-cloud-export"

    settings.setValue("cloud_export_dir", str(tmp_path / "custom"))
    assert resolve_export_root(settings, library) == tmp_path / "custom"
