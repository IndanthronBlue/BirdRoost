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
