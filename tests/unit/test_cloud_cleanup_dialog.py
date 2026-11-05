from pathlib import Path

from PySide6.QtCore import QSettings

from birdclass.ui.cloud_cleanup_dialog import CloudCleanupDialog


def test_cleanup_dialog_requires_scan_before_delete(qtbot, tmp_path: Path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = CloudCleanupDialog(tmp_path, tmp_path / "export", settings)
    qtbot.addWidget(dialog)

    assert dialog.retention.value() == 30
    assert not dialog.delete_button.isEnabled()
