from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QTabWidget

from birdclass.ui.config_dialog import ConfigDialog
from birdclass.ui.main_window import MainWindow


def test_config_dialog_has_api_and_cos_tabs(qtbot, tmp_path: Path):
    from tests.unit.test_main_window import isolated_settings

    isolated_settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_config()
    dialog = window._config_dialog
    qtbot.addWidget(dialog)

    tabs = dialog.findChild(QTabWidget)
    assert tabs.count() == 2
    assert tabs.tabText(0) == "懂鸟 API Key"
    assert tabs.tabText(1) == "云图库 COS"
    assert dialog.secret_key.echoMode() == dialog.secret_key.EchoMode.Password
    window.close()
