from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication


def application_stylesheet(_palette: QPalette) -> str:
    """Use native palette colors and only add light structural styling.

    Do not paint window/input backgrounds here: macOS dark mode and Qt's
    native styles already provide correct foreground/background pairs. Mixing
    a fixed palette color with a native widget color is what caused white text
    on light fields in dark mode.
    """
    return """
        QGroupBox {
            font-weight: 600;
            border: 1px solid palette(mid);
            border-radius: 8px;
            margin-top: 12px;
            padding: 14px 10px 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 4px;
        }
        QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {
            min-height: 28px;
        }
        QPushButton {
            padding: 6px 14px;
        }
        QPlainTextEdit {
            border: 1px solid palette(mid);
            border-radius: 6px;
        }
    """


class SystemThemeController(QObject):
    """Keep structural Qt styling in sync with the system appearance."""

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self.apply()
        app.styleHints().colorSchemeChanged.connect(self.apply)

    def apply(self) -> None:
        self._app.setStyleSheet(application_stylesheet(self._app.palette()))


def install_system_theme(app: QApplication) -> SystemThemeController:
    return SystemThemeController(app)
