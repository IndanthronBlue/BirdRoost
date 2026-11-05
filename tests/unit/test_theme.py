import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

from birdclass.ui.theme import application_stylesheet, install_system_theme


def make_palette(window: str, text: str, base: str, alternate: str) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(window))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
    palette.setColor(QPalette.ColorRole.Text, QColor(text))
    palette.setColor(QPalette.ColorRole.Base, QColor(base))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(alternate))
    palette.setColor(QPalette.ColorRole.Mid, QColor("#7f8c83"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#3574f0"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    return palette


@pytest.mark.parametrize(
    ("window", "text", "base", "alternate"),
    [
        ("#f4f6f3", "#202421", "#ffffff", "#edf1ed"),
        ("#202522", "#edf2ee", "#171b18", "#252b27"),
    ],
)
def test_stylesheet_leaves_color_pairs_to_native_palette(window, text, base, alternate):
    palette = make_palette(window, text, base, alternate)

    stylesheet = application_stylesheet(palette)

    assert "palette(mid)" in stylesheet
    assert "QGroupBox" in stylesheet
    assert window not in stylesheet
    assert text not in stylesheet
    assert base not in stylesheet


def test_controller_refreshes_structural_stylesheet(qapp):
    original_palette = QPalette(qapp.palette())
    original_stylesheet = qapp.styleSheet()
    try:
        light = make_palette("#f4f6f3", "#202421", "#ffffff", "#edf1ed")
        qapp.setPalette(light)
        controller = install_system_theme(qapp)
        assert "palette(mid)" in qapp.styleSheet()
        assert "#f4f6f3" not in qapp.styleSheet()

        dark = make_palette("#202522", "#edf2ee", "#171b18", "#252b27")
        qapp.setPalette(dark)
        qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)

        assert "palette(mid)" in qapp.styleSheet()
        assert "#202522" not in qapp.styleSheet()
        assert controller.parent() is qapp
    finally:
        qapp.setPalette(original_palette)
        qapp.setStyleSheet(original_stylesheet)
