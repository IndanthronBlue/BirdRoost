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
    assert dialog.image_canvas.image is not None
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


def test_review_dialog_shows_current_target_box_on_canvas(qtbot, tmp_path):
    from PySide6.QtCore import QRectF
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

    assert dialog.image_canvas.has_boxes() is True
    assert dialog.image_canvas.show_boxes is True
    assert dialog.image_canvas._box_items[0].rect() == QRectF(10.0, 10.0, 40.0, 30.0)
    assert any("目标 1/2" in label.text() for label in dialog.findChildren(QLabel))


def test_review_dialog_canvas_supports_zoom_and_fit(qtbot, tmp_path):
    image = tmp_path / "bird.png"
    Image.new("RGB", (100, 50), "green").save(image)
    context = ReviewContext(
        image_path=image,
        relative_path="bird.png",
        result_id="zoom-review",
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

    dialog.image_canvas.zoom_in()
    assert dialog.image_canvas.transform().m11() > 0
    dialog.image_canvas.actual_size()
    assert dialog.image_canvas.transform().m11() == 1.0
    dialog.image_canvas.fit_to_window()
    assert dialog.image_canvas.has_boxes() is True


def test_review_dialog_box_survives_canvas_resize(qtbot, tmp_path):
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

    original = dialog.image_canvas._box_items[0].rect()
    dialog.findChild(QSplitter).setSizes([650, 200])
    qtbot.wait(20)

    assert dialog.image_canvas._box_items[0].rect() == original


def test_candidate_rows_show_english_and_latin_names_on_two_lines(qtbot, tmp_path):
    image = tmp_path / "bird.png"
    Image.new("RGB", (100, 80), "green").save(image)
    context = ReviewContext(
        image_path=image,
        relative_path="bird.png",
        result_id="two-line-candidate",
        candidates=(candidate("1", "麻雀", "80"),),
        reason="low_confidence",
        low_threshold=Decimal("80"),
        delta_threshold=Decimal("10"),
        confidence_gap=None,
    )
    dialog = ReviewDialog(context)
    qtbot.addWidget(dialog)

    item = dialog.candidate_list.item(0)
    line_height = dialog.candidate_list.fontMetrics().height()

    assert dialog.candidate_list.wordWrap()
    assert "English / Latin" in item.text()
    assert item.sizeHint().height() >= line_height * 2




def test_custom_species_entry_enables_button_and_returns_trimmed_name(qtbot, tmp_path):
    image = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 80), "green").save(image)
    context = ReviewContext(
        image_path=image,
        relative_path="bird.jpg",
        result_id="custom-1",
        candidates=(candidate("1", "麻雀", "60"),),
        reason="low_confidence",
        low_threshold=Decimal("80"),
        delta_threshold=Decimal("10"),
        confidence_gap=None,
    )
    dialog = ReviewDialog(context)
    qtbot.addWidget(dialog)

    assert not dialog.custom_button.isEnabled()
    dialog.custom_name.setText("   ")
    assert not dialog.custom_button.isEnabled()

    dialog.custom_name.setText("  白鹡鸰  ")
    assert dialog.custom_button.isEnabled()
    dialog.custom_button.click()

    assert dialog.result.action == ReviewAction.CUSTOM
    assert dialog.result.custom_name_cn == "白鹡鸰"
    assert dialog.result.candidate is None


def test_blank_custom_species_is_not_submitted(qtbot, tmp_path):
    image = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 80), "green").save(image)
    context = ReviewContext(
        image_path=image,
        relative_path="bird.jpg",
        result_id="custom-2",
        candidates=(candidate("1", "麻雀", "60"),),
        reason="low_confidence",
        low_threshold=Decimal("80"),
        delta_threshold=Decimal("10"),
        confidence_gap=None,
    )
    dialog = ReviewDialog(context)
    qtbot.addWidget(dialog)

    dialog.custom_name.setText("   ")
    dialog.confirm_custom()

    assert dialog.result.action == ReviewAction.STOP
    assert dialog.result.custom_name_cn == ""


def test_many_candidates_are_listed_and_scrollable(qtbot, tmp_path):
    image = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 80), "green").save(image)
    candidates = tuple(candidate(str(index), f"鸟{index}", "60") for index in range(20))
    context = ReviewContext(
        image_path=image,
        relative_path="bird.jpg",
        result_id="many-candidates",
        candidates=candidates,
        reason="low_confidence",
        low_threshold=Decimal("80"),
        delta_threshold=Decimal("10"),
        confidence_gap=None,
    )
    dialog = ReviewDialog(context)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.candidate_list.count() == 20
    assert dialog.candidate_list.verticalScrollBar().maximum() > 0


def test_preview_failure_keeps_candidates_and_actions(qtbot, tmp_path):
    context = ReviewContext(
        image_path=tmp_path / "missing.jpg",
        relative_path="missing.jpg",
        result_id="missing-preview",
        candidates=(candidate("1", "麻雀", "60"),),
        reason="low_confidence",
        low_threshold=Decimal("80"),
        delta_threshold=Decimal("10"),
        confidence_gap=None,
    )
    dialog = ReviewDialog(context)
    qtbot.addWidget(dialog)

    assert dialog.image_canvas.image is None
    assert dialog.preview_label.text() == "无法加载原图预览"
    assert dialog.candidate_list.count() == 1
    assert dialog.confirm_button.isEnabled()
    assert dialog.defer_button.isEnabled()
    assert dialog.stop_button.isEnabled()

    dialog.confirm()

    assert dialog.result.action == ReviewAction.CONFIRM
    assert dialog.result.candidate.species_id == "1"


def test_apply_to_remaining_checkbox_sets_review_result(qtbot, tmp_path):
    image = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 80), "green").save(image)
    context = ReviewContext(
        image_path=image,
        relative_path="bird.jpg",
        result_id="apply-remaining",
        candidates=(candidate("1", "麻雀", "60"),),
        reason="low_confidence",
        low_threshold=Decimal("80"),
        delta_threshold=Decimal("10"),
        confidence_gap=None,
        target_index=0,
        target_count=2,
    )
    first = ReviewDialog(context)
    qtbot.addWidget(first)

    assert not first.apply_remaining.isChecked()
    first.apply_remaining.setChecked(True)
    first.confirm()

    assert first.result.action == ReviewAction.CONFIRM
    assert first.result.apply_to_remaining is True

    second = ReviewDialog(context)
    qtbot.addWidget(second)
    second.custom_name.setText("白鹡鸰")
    second.apply_remaining.setChecked(True)
    second.confirm_custom()

    assert second.result.action == ReviewAction.CUSTOM
    assert second.result.apply_to_remaining is True
