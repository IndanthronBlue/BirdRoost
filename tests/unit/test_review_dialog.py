from decimal import Decimal

from PIL import Image

from birdclass.models import RecognitionCandidate, ReviewAction, ReviewContext
from birdclass.ui.review_dialog import ReviewDialog


def candidate(species_id: str, name: str, percent: str) -> RecognitionCandidate:
    return RecognitionCandidate(
        species_id=species_id,
        animal_class="B",
        name_cn=name,
        name_en="English",
        name_latin="Latin",
        confidence_raw="0.8",
        confidence_percent=Decimal(percent),
    )


def test_review_dialog_shows_image_candidates_and_confirm(qtbot, tmp_path):
    image = tmp_path / "bird.png"
    Image.new("RGB", (100, 80), "green").save(image)
    context = ReviewContext(
        image_path=image,
        relative_path="bird.png",
        result_id="result-1",
        candidates=(candidate("1", "麻雀", "80"), candidate("2", "家燕", "75")),
        reason="ambiguous",
        low_threshold=Decimal("80"),
        delta_threshold=Decimal("10"),
        confidence_gap=Decimal("5"),
    )
    dialog = ReviewDialog(context)
    qtbot.addWidget(dialog)

    assert dialog.candidate_list.count() == 2
    assert "80.00%" in dialog.candidate_list.item(0).text()
    assert dialog.defer_button.text() == "稍后处理（仅当前目标）"
    assert not dialog.image_label.pixmap().isNull()
    dialog.candidate_list.setCurrentRow(1)
    dialog.confirm()

    assert dialog.result.action == ReviewAction.CONFIRM
    assert dialog.result.candidate.species_id == "2"


def test_closing_review_defers_and_stops(qtbot, tmp_path):
    image = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 80), "green").save(image)
    context = ReviewContext(
        image_path=image,
        relative_path="bird.jpg",
        result_id="result-2",
        candidates=(candidate("1", "麻雀", "60"),),
        reason="low_confidence",
        low_threshold=Decimal("80"),
        delta_threshold=Decimal("10"),
        confidence_gap=None,
    )
    dialog = ReviewDialog(context)
    qtbot.addWidget(dialog)

    dialog.reject()

    assert dialog.result.action == ReviewAction.STOP
    assert dialog.result.candidate is None


def test_review_dialog_highlights_normalized_target_with_letterboxing(qtbot, tmp_path):
    from PySide6.QtWidgets import QLabel

    image = tmp_path / "bird.png"
    Image.new("RGB", (100, 50), "green").save(image)
    context = ReviewContext(
        image_path=image,
        relative_path="bird.png",
        result_id="result-3",
        candidates=(candidate("1", "麻雀", "60"),),
        reason="low_confidence",
        low_threshold=Decimal("80"),
        delta_threshold=Decimal("10"),
        confidence_gap=None,
        target_index=0,
        target_count=2,
        box=(0.1, 0.2, 0.5, 0.8),
    )
    dialog = ReviewDialog(context)
    qtbot.addWidget(dialog)

    dialog.image_label.resize(400, 300)
    dialog._update_image()
    rect = dialog.image_label.highlight_rect

    assert rect is not None
    assert rect.left() == 40
    assert rect.top() == 90
    assert rect.right() == 200
    assert rect.bottom() == 210
    assert any("目标 1/2" in label.text() for label in dialog.findChildren(QLabel))


def test_review_dialog_high_dpi_uses_logical_paint_coordinates(qtbot, tmp_path):
    image = tmp_path / "bird.png"
    Image.new("RGB", (100, 50), "green").save(image)
    context = ReviewContext(
        image_path=image,
        relative_path="bird.png",
        result_id="retina",
        candidates=(candidate("1", "麻雀", "60"),),
        reason="low_confidence",
        low_threshold=Decimal("80"),
        delta_threshold=Decimal("10"),
        confidence_gap=None,
        box=(0.1, 0.2, 0.5, 0.8),
    )
    dialog = ReviewDialog(context)
    qtbot.addWidget(dialog)
    dialog._pixmap.setDevicePixelRatio(2)
    dialog.image_label.resize(400, 300)

    dialog._update_image()
    rect = dialog.image_label.highlight_rect

    assert rect is not None
    assert dialog.image_label.pixmap().deviceIndependentSize().width() == 200
    assert (rect.left(), rect.top(), rect.right(), rect.bottom()) == (120, 120, 200, 180)


def test_highlight_recalculates_when_image_label_resizes(qtbot, tmp_path):
    from PySide6.QtWidgets import QSplitter

    image = tmp_path / "bird.png"
    Image.new("RGB", (100, 50), "green").save(image)
    context = ReviewContext(
        image_path=image,
        relative_path="bird.png",
        result_id="layout-resize",
        candidates=(candidate("1", "麻雀", "60"),),
        reason="low_confidence",
        low_threshold=Decimal("80"),
        delta_threshold=Decimal("10"),
        confidence_gap=None,
        box=(0.1, 0.2, 0.5, 0.8),
    )
    dialog = ReviewDialog(context)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    dialog.findChild(QSplitter).setSizes([650, 200])
    qtbot.waitUntil(lambda: dialog.image_label.width() > 600)
    rect = dialog.image_label.highlight_rect
    scaled = dialog.image_label.pixmap().deviceIndependentSize()
    expected_left = (dialog.image_label.width() - scaled.width()) / 2 + 0.1 * scaled.width()
    expected_top = (dialog.image_label.height() - scaled.height()) / 2 + 0.2 * scaled.height()

    assert rect is not None
    assert round(rect.left(), 6) == round(expected_left, 6)
    assert round(rect.top(), 6) == round(expected_top, 6)
    assert round(rect.width(), 6) == round(0.4 * scaled.width(), 6)
    assert round(rect.height(), 6) == round(0.6 * scaled.height(), 6)
