from PySide6.QtWidgets import QApplication

from birdclass.ui.observation_dialog import ObservationDialog


def test_china_shows_region_and_foreign_hides_it(qtbot):
    dialog = ObservationDialog(
        country="中国", region="上海", location="南汇", time="2024"
    )
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.country_text == "中国"
    assert dialog.region_text == "上海"
    assert dialog.location_text == "南汇"
    assert dialog.time_text == "2024"
    assert dialog.region.isVisible()

    dialog.country.setCurrentText("西班牙")
    dialog.region.setCurrentText("")
    dialog.location.setText("多尼亚那")
    assert dialog.region_text == ""
    assert dialog.region.isHidden()


def test_dialog_can_apply_existing_observation_preset(qtbot):
    dialog = ObservationDialog(
        country="中国", region="上海", location="南汇", time="2024",
        options=[
            ("中国", "上海", "南汇", "2024", 25),
            ("格鲁吉亚", "", "巴统", "2026-10", 171),
        ],
    )
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.preset.count() == 3
    dialog.preset.setCurrentIndex(2)
    assert dialog.country_text == "格鲁吉亚"
    assert dialog.region_text == ""
    assert dialog.location_text == "巴统"
    assert dialog.time_text == "2026-10"
