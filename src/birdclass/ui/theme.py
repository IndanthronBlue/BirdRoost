from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication


def application_stylesheet(palette: QPalette) -> str:
    """Build application chrome colors from the active system palette."""
    def color(role: QPalette.ColorRole) -> str:
        return palette.color(role).name()

    window = color(QPalette.ColorRole.Window)
    window_text = color(QPalette.ColorRole.WindowText)
    text = color(QPalette.ColorRole.Text)
    base = color(QPalette.ColorRole.Base)
    alternate = color(QPalette.ColorRole.AlternateBase)
    mid = color(QPalette.ColorRole.Mid)
    highlight = color(QPalette.ColorRole.Highlight)
    highlighted = color(QPalette.ColorRole.HighlightedText)

    return f"""
        QMainWindow, QDialog {{ background: {window}; color: {window_text}; }}
        QGroupBox {{
            font-weight: 600;
            border: 1px solid {mid};
            border-radius: 8px;
            margin-top: 12px;
            padding: 14px 10px 10px;
            background: {window};
            color: {window_text};
        }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
        QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
            min-height: 28px;
            background: {base};
            color: {text};
            selection-background-color: {highlight};
            selection-color: {highlighted};
        }}
        QComboBox QAbstractItemView, QListWidget {{
            background: {base};
            color: {text};
            alternate-background-color: {alternate};
            selection-background-color: {highlight};
            selection-color: {highlighted};
        }}
        QPushButton {{ padding: 6px 14px; }}
        QPlainTextEdit {{
            background: {base};
            color: {text};
            border: 1px solid {mid};
            border-radius: 6px;
            selection-background-color: {highlight};
            selection-color: {highlighted};
        }}
    """


class SystemThemeController(QObject):
    """Keep custom Qt styles aligned with the current system appearance."""

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self.apply()
        app.styleHints().colorSchemeChanged.connect(self.apply)

    def apply(self) -> None:
        self._app.setStyleSheet(application_stylesheet(self._app.palette()))


def install_system_theme(app: QApplication) -> SystemThemeController:
    return SystemThemeController(app)
