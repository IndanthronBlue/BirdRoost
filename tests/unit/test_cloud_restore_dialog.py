from pathlib import Path

from PySide6.QtCore import QSettings

from birdclass.ui.cloud_restore_dialog import CloudRestoreDialog


def test_restore_dialog_has_target_and_config(qtbot, tmp_path: Path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = CloudRestoreDialog(settings)
    qtbot.addWidget(dialog)

    assert dialog.local_root.text()
    assert "未配置 COS" in dialog.config_label.text()
    assert dialog.start_button.text() == "开始恢复"
