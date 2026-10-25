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


def relative_luminance(color: QColor) -> float:
    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel / 255) for channel in (color.red(), color.green(), color.blue()))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: QColor, second: QColor) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize(
    ("window", "text", "base", "alternate"),
    [
        ("#f4f6f3", "#202421", "#ffffff", "#edf1ed"),
        ("#202522", "#edf2ee", "#171b18", "#252b27"),
    ],
)
def test_stylesheet_uses_readable_light_and_dark_palette_colors(window, text, base, alternate):
    palette = make_palette(window, text, base, alternate)

    stylesheet = application_stylesheet(palette)

    assert f"background: {window};" in stylesheet
    assert f"color: {text};" in stylesheet
    assert f"background: {base};" in stylesheet
    assert f"alternate-background-color: {alternate};" in stylesheet
    assert "background: white" not in stylesheet
    assert contrast_ratio(QColor(window), QColor(text)) >= 4.5
    assert contrast_ratio(QColor(base), QColor(text)) >= 4.5


def test_controller_refreshes_stylesheet_when_system_color_scheme_changes(qapp):
    original_palette = QPalette(qapp.palette())
    original_stylesheet = qapp.styleSheet()
    try:
        light = make_palette("#f4f6f3", "#202421", "#ffffff", "#edf1ed")
        qapp.setPalette(light)
        controller = install_system_theme(qapp)
        assert "background: #f4f6f3;" in qapp.styleSheet()

        dark = make_palette("#202522", "#edf2ee", "#171b18", "#252b27")
        qapp.setPalette(dark)
        qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)

        assert "background: #202522;" in qapp.styleSheet()
        assert "background: #171b18;" in qapp.styleSheet()
        assert controller.parent() is qapp
    finally:
        qapp.setPalette(original_palette)
        qapp.setStyleSheet(original_stylesheet)
