from pathlib import Path

from PIL import Image
from PySide6.QtWidgets import QApplication

from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id
from birdclass.ui.archive_browser import ArchiveBrowserWindow


def make_image(path: Path, size=(80, 60)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "green").save(path)


def add_group(library: ArchiveLibrary, relative_path: str, *, batch_id: str,
              species_cn: str, species_latin: str, box=(0.1, 0.1, 0.5, 0.5)) -> dict:
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": batch_id,
        "status": "completed",
        "targets": [{
            "target_index": 0,
            "box": list(box),
            "selection": {"species_cn": species_cn, "species_latin": species_latin},
        }],
        "copies": [{
            "relative_path": relative_path,
            "species_cn": species_cn,
            "species_latin": species_latin,
            "target_indices": [0],
        }],
    }
    library.write_group(group)
    return group


def test_browser_builds_tree_filters_grid_and_toggles_boxes(qtbot, tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    make_image(output / "欧乌鸫" / "b.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    batch = new_batch_id()
    add_group(library, "三趾滨鹬/a.jpg", batch_id=batch,
              species_cn="三趾滨鹬", species_latin="Calidris alba")
    browser = ArchiveBrowserWindow(output)
    qtbot.addWidget(browser)

    assert browser.tree.topLevelItemCount() >= 1
    species_path = next(
        path for path in browser._tree_items
        if path[-1] == "Calidris alba"
    )
    browser.tree.setCurrentItem(browser._tree_items[species_path])
    assert browser.grid.count() == 1
    assert browser.canvas.image is not None
    assert browser.box_toggle.isChecked() is False
    assert browser.canvas.has_boxes() is True
    assert all(not item.isVisible() for item in browser.canvas._box_items)

    browser.box_toggle.setChecked(True)

    assert browser.canvas.show_boxes is True
    assert any(item.isVisible() for item in browser.canvas._box_items)


def test_browser_copy_image_and_annotated_image(qtbot, tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    batch = new_batch_id()
    add_group(library, "三趾滨鹬/a.jpg", batch_id=batch,
              species_cn="三趾滨鹬", species_latin="Calidris alba")
    browser = ArchiveBrowserWindow(output)
    qtbot.addWidget(browser)

    browser.copy_image(False)
    clean = QApplication.clipboard().image()
    assert (clean.width(), clean.height()) == (80, 60)

    browser.copy_image(True)
    annotated = QApplication.clipboard().image()
    assert (annotated.width(), annotated.height()) == (80, 60)
    assert annotated != clean


def test_browser_refresh_adds_new_species(qtbot, tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "欧乌鸫" / "a.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    batch = new_batch_id()
    add_group(library, "欧乌鸫/a.jpg", batch_id=batch,
              species_cn="欧乌鸫", species_latin="Turdus merula")
    browser = ArchiveBrowserWindow(output)
    qtbot.addWidget(browser)
    assert any(path[-1] == "Turdus merula" for path in browser._tree_items)

    make_image(output / "三趾滨鹬" / "b.jpg")
    add_group(library, "三趾滨鹬/b.jpg", batch_id=batch,
              species_cn="三趾滨鹬", species_latin="Calidris alba")
    browser.refresh()

    assert any(path[-1] == "Calidris alba" for path in browser._tree_items)
    assert browser._tree_items[
        next(path for path in browser._tree_items if path[-1] == "Calidris alba")
    ].text(1) == "1"


def test_browser_batch_filter_and_show_all(qtbot, tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    make_image(output / "欧乌鸫" / "b.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    batch_a = new_batch_id()
    batch_b = new_batch_id()
    add_group(library, "三趾滨鹬/a.jpg", batch_id=batch_a,
              species_cn="三趾滨鹬", species_latin="Calidris alba")
    add_group(library, "欧乌鸫/b.jpg", batch_id=batch_b,
              species_cn="欧乌鸫", species_latin="Turdus merula")
    browser = ArchiveBrowserWindow(output, batch_id=batch_a)
    qtbot.addWidget(browser)

    assert browser._visible_entries()
    assert all(entry.batch_id == batch_a for entry in browser._visible_entries())
    assert not any(path[-1] == "Turdus merula" for path in browser._tree_items)

    browser.clear_batch_filter()

    assert len(browser.index.entries) == 2
    assert any(path[-1] == "Turdus merula" for path in browser._tree_items)


def test_batch_page_defaults_boxes_on_and_shows_summary(qtbot, tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    batch = new_batch_id()
    group = add_group(library, "三趾滨鹬/a.jpg", batch_id=batch,
                      species_cn="三趾滨鹬", species_latin="Calidris alba")
    library.write_batch({
        "schema_version": 1,
        "batch_id": batch,
        "groups": [group["group_id"]],
        "summary": {"total": 1, "completed": 1, "failed": 0, "deferred": 0},
    })
    browser = ArchiveBrowserWindow(output, batch_id=batch)
    qtbot.addWidget(browser)

    assert browser.box_toggle.isChecked() is True
    assert "本批共 1" in browser.summary_label.text()
    assert browser.canvas.show_boxes is True


def test_browser_correction_button_moves_copy(qtbot, tmp_path: Path, monkeypatch):
    from birdclass.taxonomy import load_taxonomy

    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    batch = new_batch_id()
    add_group(library, "三趾滨鹬/a.jpg", batch_id=batch,
              species_cn="三趾滨鹬", species_latin="Calidris alba")
    browser = ArchiveBrowserWindow(output)
    qtbot.addWidget(browser)
    browser.tree.setCurrentItem(next(
        item for path, item in browser._tree_items.items() if path[-1] == "Calidris alba"
    ))
    browser.grid.setCurrentRow(0)
    assert browser.correct_button.isHidden() is False

    taxon = load_taxonomy().resolve(scientific_name="Calidris ruficollis")

    class FakePicker:
        def __init__(self, *args, **kwargs):
            self.selected_taxon = taxon

        def exec(self):
            return True

    monkeypatch.setattr("birdclass.ui.archive_browser.SpeciesPickerDialog", FakePicker)
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        "birdclass.ui.archive_browser.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    browser.correct_selected()

    assert (output / "红颈滨鹬" / "红颈滨鹬_a.jpg").is_file()
    assert any(record["new_species_cn"] == "红颈滨鹬" for record in library.load_corrections())


def test_batch_target_level_correction_splits_shared_copy(qtbot, tmp_path: Path, monkeypatch):
    from birdclass.taxonomy import load_taxonomy

    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    batch = new_batch_id()
    group = add_group(library, "三趾滨鹬/a.jpg", batch_id=batch,
                      species_cn="三趾滨鹬", species_latin="Calidris alba")
    updated = library.read_group(group["group_id"])
    updated["targets"].append({
        "target_index": 1,
        "box": [0.5, 0.5, 0.9, 0.9],
        "selection": {"species_cn": "三趾滨鹬", "species_latin": "Calidris alba"},
    })
    updated["copies"][0]["target_indices"] = [0, 1]
    library.write_group(updated)
    browser = ArchiveBrowserWindow(output, batch_id=batch)
    qtbot.addWidget(browser)
    browser.tree.setCurrentItem(next(
        item for path, item in browser._tree_items.items() if path[-1] == "Calidris alba"
    ))
    browser.grid.setCurrentRow(0)
    browser.target_list.setCurrentRow(0)
    taxon = load_taxonomy().resolve(scientific_name="Calidris ruficollis")

    class FakePicker:
        def __init__(self, *args, **kwargs):
            self.selected_taxon = taxon

        def exec(self):
            return True

    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr("birdclass.ui.archive_browser.SpeciesPickerDialog", FakePicker)
    monkeypatch.setattr(
        "birdclass.ui.archive_browser.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    browser.correct_selected()

    updated = library.read_group(group["group_id"])
    old_copy = next(copy for copy in updated["copies"] if copy["relative_path"] == "三趾滨鹬/a.jpg")
    new_copy = next(copy for copy in updated["copies"] if copy["species_cn"] == "红颈滨鹬")
    assert old_copy["target_indices"] == [1]
    assert new_copy["target_indices"] == [0]
    assert updated["targets"][0]["selection"]["species_latin"] == "Calidris ruficollis"
    assert updated["targets"][1]["selection"]["species_latin"] == "Calidris alba"
