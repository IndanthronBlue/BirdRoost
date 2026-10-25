from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.theme import install_system_theme


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("BirdRoost")
    app.setOrganizationName("BirdClass")
    install_system_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
