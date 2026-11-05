from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QStyleFactory

from .tls import configure_ca_bundle


def main() -> int:
    configure_ca_bundle()
    from .ui.main_window import MainWindow
    from .ui.theme import install_system_theme

    app = QApplication.instance() or QApplication(sys.argv)
    if sys.platform == "darwin" and "macOS" in QStyleFactory.keys():
        app.setStyle("macOS")
    app.setApplicationName("BirdRoost")
    app.setOrganizationName("BirdClass")
    install_system_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
