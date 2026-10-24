import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox

from birdclass.ui.area_search import configure_area_search, resolve_area_code

pytestmark = pytest.mark.usefixtures("qapp")


def make_areas() -> QComboBox:
    combo = QComboBox()
    combo.addItem("全球（不过滤） — World [WORLD]", "WORLD")
    combo.addItem("中国 — China [CN]", "CN")
    combo.addItem("中国香港 — Hong Kong [HK]", "HK")
    combo.addItem("中国澳门 — Macao [MO]", "MO")
    combo.addItem("阿富汗 — Afghanistan [AF]", "AF")
    configure_area_search(combo)
    return combo


def test_exact_chinese_primary_name_wins_over_contains_matches():
    combo = make_areas()
    combo.setEditText("中国")

    assert resolve_area_code(combo) == "CN"


def test_unique_english_fragment_resolves_to_code():
    combo = make_areas()

    combo.setEditText("China")

    assert resolve_area_code(combo) == "CN"


def test_completer_uses_case_insensitive_contains_matching():
    combo = make_areas()

    assert combo.isEditable()
    completer = combo.completer()
    assert completer.filterMode() == Qt.MatchFlag.MatchContains
    assert completer.caseSensitivity() == Qt.CaseSensitivity.CaseInsensitive
    completer.setCompletionPrefix("china")
    assert completer.completionCount() == 1
    assert "China" in completer.currentCompletion()


def test_ambiguous_input_is_rejected():
    combo = make_areas()
    combo.setEditText("a")

    with pytest.raises(ValueError, match="有效国家"):
        resolve_area_code(combo)
