from birdclass.taxonomy import load_taxonomy
from birdclass.ui.species_picker import SpeciesPickerDialog


def test_alias_search_selects_alias_name_and_canonical_taxon(qtbot):
    dialog = SpeciesPickerDialog(load_taxonomy(), initial="伊比利亚灰喜鹊")
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.list.count() == 1
    dialog.accept()

    assert dialog.selected_taxon.scientific_name == "Cyanopica cooki"
    assert dialog.selected_name == "伊比利亚灰喜鹊"


def test_unknown_name_falls_back_to_manual_taxon(qtbot):
    dialog = SpeciesPickerDialog(load_taxonomy(), initial="不存在鸟")
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.list.count() == 1
    dialog.accept()

    assert dialog.selected_name == "不存在鸟"
    assert dialog.selected_taxon.name_zh == "不存在鸟"
    assert dialog.selected_taxon.scientific_name == ""
