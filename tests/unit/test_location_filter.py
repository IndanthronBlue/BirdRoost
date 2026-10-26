from birdclass.ui.location_filter import LocationFilterButton


def test_location_filter_is_country_drawer(qtbot):
    button = LocationFilterButton()
    qtbot.addWidget(button)
    button.set_nodes([
        (("", "", ""), "全部观测地", 41),
        (("中国", "", ""), "中国", 41),
        (("中国", "上海", ""), "  上海", 40),
        (("中国", "上海", "南汇"), "    南汇", 30),
        (("西班牙", "", ""), "西班牙", 274),
        (("西班牙", "", "多尼亚那"), "  多尼亚那", 149),
    ])

    top = [action.text() for action in button.menu().actions()]
    assert top[0] == "全部观测地"
    assert "中国  (41)" in top
    assert "西班牙  (274)" in top
    assert "南汇  (30)" not in top
    assert "多尼亚那  (149)" not in top


def test_location_filter_selects_key(qtbot):
    button = LocationFilterButton()
    qtbot.addWidget(button)
    button.set_nodes([
        (("", "", ""), "全部观测地", 1),
        (("中国", "", ""), "中国", 1),
        (("中国", "上海", ""), "上海", 1),
        (("中国", "上海", "南汇"), "南汇", 1),
    ])
    emitted = []
    button.changed.connect(lambda: emitted.append(button.currentData()))

    button.setCurrentData(("中国", "上海", "南汇"))

    assert button.currentData() == ("中国", "上海", "南汇")
    assert button.text() == "中国 / 上海 / 南汇"
    assert emitted == [("中国", "上海", "南汇")]
