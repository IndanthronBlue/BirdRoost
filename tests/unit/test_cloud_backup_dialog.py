from pathlib import Path

from PySide6.QtCore import QSettings

from birdclass.ui.cloud_backup_dialog import CloudBackupDialog


def test_cloud_dialog_has_export_and_config_summary(qtbot, tmp_path: Path):
    output = tmp_path / "鸟"
    output.mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = CloudBackupDialog(output, output, settings)
    qtbot.addWidget(dialog)

    assert dialog.export_dir.text() == str(tmp_path / "鸟-cloud-export")
    assert "未配置 COS" in dialog.config_label.text()
    assert dialog.config_button.text() == "打开配置…"


def test_cloud_dialog_shows_configured_summary(qtbot, tmp_path: Path):
    output = tmp_path / "鸟"
    output.mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("cloud_bucket", "bucket-1250000000")
    settings.setValue("cloud_region", "ap-shanghai")
    settings.setValue("cloud_prefix", "zjq")
    dialog = CloudBackupDialog(output, output, settings)
    qtbot.addWidget(dialog)

    assert "bucket-1250000000" in dialog.config_label.text()
    assert "users/zjq/" in dialog.config_label.text()
