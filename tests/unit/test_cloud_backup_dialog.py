from pathlib import Path

from PySide6.QtCore import QSettings

from birdclass.ui.cloud_backup_dialog import CloudBackupDialog


def test_cloud_dialog_has_optional_cos_fields(qtbot, tmp_path: Path):
    output = tmp_path / "鸟"
    output.mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = CloudBackupDialog(output, output, settings)
    qtbot.addWidget(dialog)

    assert dialog.export_dir.text() == str(tmp_path / "鸟-cloud-export")
    assert dialog.bucket.text() == ""
    assert dialog.region.currentText() == "ap-shanghai"
    assert dialog.prefix.text() != ""
    assert dialog.endpoint.text() == ""
    assert dialog.secret_id.echoMode() == dialog.secret_id.EchoMode.Normal
    assert dialog.secret_key.echoMode() == dialog.secret_key.EchoMode.Password


def test_cos_config_can_be_saved_and_restored(qtbot, tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    saved = []
    deleted = []
    monkeypatch.setattr(
        "birdclass.ui.cloud_backup_dialog.save_cos_credentials",
        lambda secret_id, secret_key: saved.append((secret_id, secret_key)) or True,
    )
    monkeypatch.setattr(
        "birdclass.ui.cloud_backup_dialog.delete_cos_credentials",
        lambda: deleted.append(True) or True,
    )
    monkeypatch.setattr(
        "birdclass.ui.cloud_backup_dialog.load_cos_credentials",
        lambda: ("", ""),
    )
    output = tmp_path / "鸟"
    output.mkdir()
    first = CloudBackupDialog(output, output, settings)
    qtbot.addWidget(first)
    first.bucket.setText("bucket-1250000000")
    first.region.setCurrentText("ap-shanghai")
    first.prefix.setText("zjq")
    first.secret_id.setText("secret-id")
    first.secret_key.setText("secret-key")
    first.save_config.setChecked(True)
    first._save()
    first.close()

    assert saved[-1] == ("secret-id", "secret-key")
    assert settings.value("cloud_save_config") in (True, "true")
    assert settings.value("cloud_bucket") == "bucket-1250000000"

    monkeypatch.setattr(
        "birdclass.ui.cloud_backup_dialog.load_cos_credentials",
        lambda: ("secret-id", "secret-key"),
    )
    second = CloudBackupDialog(output, output, settings)
    qtbot.addWidget(second)
    assert second.bucket.text() == "bucket-1250000000"
    assert second.secret_id.text() == "secret-id"
    assert second.secret_key.text() == "secret-key"
    assert second.save_config.isChecked()

    second.save_config.setChecked(False)
    second._save()
    assert deleted
    assert settings.value("cloud_bucket") is None


def test_cloud_dialog_reads_credentials_from_fields(qtbot, tmp_path: Path):
    output = tmp_path / "鸟"
    output.mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = CloudBackupDialog(output, output, settings)
    qtbot.addWidget(dialog)
    dialog.secret_id.setText("secret-id")
    dialog.secret_key.setText("secret-key")

    assert dialog._credentials() == ("secret-id", "secret-key")
