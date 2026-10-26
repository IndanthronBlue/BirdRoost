from pathlib import Path

from PIL import Image
from PySide6.QtWidgets import QApplication

from birdclass.library import ArchiveLibrary, new_batch_id, new_group_id
from birdclass.ui.archive_browser import ArchiveBrowserWindow


def make_image(path: Path, size=(80, 60)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "green").save(path)


def add_group(library: ArchiveLibrary, relative_path: str, *, batch_id: str,
              species_cn: str, species_latin: str, box=(0.1, 0.1, 0.5, 0.5),
              location: str = "", observed_at: str = "") -> dict:
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": batch_id,
        "status": "completed",
        "observation": {"location": location, "time": observed_at},
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
    existing_node = browser._tree_items[
        next(path for path in browser._tree_items if path[-1] == "Turdus merula")
    ]

    make_image(output / "三趾滨鹬" / "b.jpg")
    add_group(library, "三趾滨鹬/b.jpg", batch_id=batch,
              species_cn="三趾滨鹬", species_latin="Calidris alba")
    browser.refresh()

    assert any(path[-1] == "Calidris alba" for path in browser._tree_items)
    assert browser._tree_items[
        next(path for path in browser._tree_items if path[-1] == "Calidris alba")
    ].text(1) == "1"
    assert browser._tree_items[
        next(path for path in browser._tree_items if path[-1] == "Turdus merula")
    ] is existing_node

    (output / "三趾滨鹬" / "b.jpg").unlink()
    browser.refresh()
    assert not any(path[-1] == "Calidris alba" for path in browser._tree_items)


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


def test_recent_batch_selector_switches_filter(qtbot, tmp_path: Path):
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
    for batch_id in (batch_a, batch_b):
        library.write_batch({
            "schema_version": 1,
            "batch_id": batch_id,
            "finished_at": f"2026-01-0{1 if batch_id == batch_a else 2}T00:00:00+00:00",
            "groups": [],
            "summary": {"total": 1},
        })
    browser = ArchiveBrowserWindow(output)
    qtbot.addWidget(browser)

    index = browser.batch_combo.findData(batch_b)
    assert index > 0
    browser.batch_combo.setCurrentIndex(index)

    assert browser.batch_id == batch_b
    assert [entry.batch_id for entry in browser._visible_entries()] == [batch_b]


def test_cleanup_replaced_requires_confirmation_and_deletes(qtbot, tmp_path: Path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    replaced = output / "已纠正" / "stamp" / "三趾滨鹬" / "old.jpg"
    replaced.parent.mkdir(parents=True)
    replaced.write_bytes(b"old")
    browser = ArchiveBrowserWindow(output)
    qtbot.addWidget(browser)

    monkeypatch.setattr(
        "birdclass.ui.archive_browser.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    browser.cleanup_replaced()
    assert replaced.exists()

    monkeypatch.setattr(
        "birdclass.ui.archive_browser.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    browser.cleanup_replaced()

    assert not (output / "已纠正").exists()


def test_tree_language_toggle_and_draggable_splitter(qtbot, tmp_path: Path):
    from PySide6.QtCore import QSettings

    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    add_group(library, "三趾滨鹬/a.jpg", batch_id=new_batch_id(),
              species_cn="三趾滨鹬", species_latin="Calidris alba")
    settings = QSettings(str(tmp_path / "archive.ini"), QSettings.Format.IniFormat)
    browser = ArchiveBrowserWindow(output, settings=settings)
    qtbot.addWidget(browser)
    browser.resize(1400, 850)
    browser.show()
    qtbot.waitExposed(browser)

    species_path = next(path for path in browser._tree_items if path[-1] == "Calidris alba")
    order_path = species_path[:4]
    genus_path = species_path[:6]
    assert browser._tree_items[order_path].text(0) == "鸻形目"
    assert browser._tree_items[genus_path].text(0) == "滨鹬属"
    assert browser._tree_items[species_path].text(0) == "三趾滨鹬"

    browser.language_combo.setCurrentIndex(browser.language_combo.findData("bilingual"))
    assert "鸻形目 CHARADRIIFORMES" == browser._tree_items[order_path].text(0)
    assert "滨鹬属 Calidris" == browser._tree_items[genus_path].text(0)
    assert "三趾滨鹬 Calidris alba" == browser._tree_items[species_path].text(0)

    browser.language_combo.setCurrentIndex(browser.language_combo.findData("latin"))
    assert browser._tree_items[order_path].text(0) == "CHARADRIIFORMES"
    assert browser._tree_items[genus_path].text(0) == "Calidris"
    assert browser._tree_items[species_path].text(0) == "Calidris alba"

    assert browser.splitter.count() == 3
    assert browser.splitter.handleWidth() >= 8
    assert browser.splitter.childrenCollapsible() is False
    assert browser.grid.gridSize().height() >= (
        browser.grid.iconSize().height()
        + 2 * browser.grid.fontMetrics().lineSpacing()
    )
    assert settings.value("archive_tree_language") == "latin"


def test_target_list_shows_all_group_species_and_switches_box_highlight(qtbot, tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "小滨鹬" / "small.jpg")
    make_image(output / "金眶鸻" / "gold.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    batch = new_batch_id()
    group = {
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": batch,
        "status": "completed",
        "targets": [
            {"target_index": 0, "box": [0.1, 0.1, 0.3, 0.3], "selection": {"species_cn": "金眶鸻"}},
            {"target_index": 1, "box": [0.4, 0.4, 0.6, 0.6], "selection": {"species_cn": "小滨鹬"}},
            {"target_index": 2, "box": [0.7, 0.1, 0.9, 0.3], "selection": {"species_cn": "金眶鸻"}},
        ],
        "copies": [
            {"relative_path": "小滨鹬/small.jpg", "species_cn": "小滨鹬", "target_indices": [1]},
            {"relative_path": "金眶鸻/gold.jpg", "species_cn": "金眶鸻", "target_indices": [0, 2]},
        ],
    }
    library.write_group(group)
    browser = ArchiveBrowserWindow(output)
    qtbot.addWidget(browser)
    entry = next(e for e in browser.index.entries if e.relative_path == "小滨鹬/small.jpg")
    browser.tree.setCurrentItem(browser._tree_items[entry.tree_path])
    for row in range(browser.grid.count()):
        item = browser.grid.item(row)
        if item.data(0x0100) == entry.relative_path:
            browser.grid.setCurrentItem(item)
            break

    assert [browser.target_list.item(i).text() for i in range(browser.target_list.count())] == [
        "目标 1 · 金眶鸻",
        "目标 2 · 小滨鹬",
        "目标 3 · 金眶鸻",
    ]
    assert [(box.label, box.highlighted) for box in browser.canvas._boxes] == [
        ("1", False), ("2", True), ("3", False)
    ]

    browser.target_list.setCurrentRow(0)

    assert [(box.label, box.highlighted) for box in browser.canvas._boxes] == [
        ("1", True), ("2", False), ("3", False)
    ]
    assert browser.correct_button.isEnabled() is False


def test_deferred_load_shows_waiting_banner(qtbot, tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    add_group(library, "三趾滨鹬/a.jpg", batch_id=new_batch_id(),
              species_cn="三趾滨鹬", species_latin="Calidris alba")
    browser = ArchiveBrowserWindow(output, defer_load=True)
    qtbot.addWidget(browser)
    browser.show()
    qtbot.waitExposed(browser)

    assert browser.loading_widget.isVisible() is True
    assert browser.loading_label.text() == "正在读取归档…"

    browser.load_library()

    assert browser.loading_widget.isVisible() is False
    assert any(path[-1] == "Calidris alba" for path in browser._tree_items)


def test_pinyin_initial_search_and_enter(qtbot, tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "黑腹滨鹬" / "a.jpg")
    make_image(output / "欧乌鸫" / "b.jpg")
    browser = ArchiveBrowserWindow(output)
    qtbot.addWidget(browser)

    assert any("hfby" in suggestion for suggestion in browser.search_model.stringList())

    browser.search.setText("hfby")
    assert browser.grid.count() == 1
    browser.search.returnPressed.emit()

    assert browser.grid.currentItem() is not None
    assert "搜索到 1 张图片" in browser.status_label.text()


def test_chinese_prefix_search_matches(qtbot, tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "黑腹滨鹬" / "a.jpg")
    make_image(output / "欧乌鸫" / "b.jpg")
    browser = ArchiveBrowserWindow(output)
    qtbot.addWidget(browser)

    browser.search.setText("黑腹")

    assert browser.grid.count() == 1
    assert browser.grid.item(0).data(0x0100) == "黑腹滨鹬/a.jpg"


def test_search_is_global_when_tree_has_a_different_branch_selected(qtbot, tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "黑腹滨鹬" / "a.jpg")
    make_image(output / "灰斑鸻" / "b.jpg")
    browser = ArchiveBrowserWindow(output)
    qtbot.addWidget(browser)
    black = next(e for e in browser.index.entries if e.species_cn == "黑腹滨鹬")
    browser.tree.setCurrentItem(browser._tree_items[black.tree_path])
    assert browser.grid.count() == 1

    browser.search.setText("灰斑鸻")
    browser.search.returnPressed.emit()

    assert browser.grid.count() == 1
    assert browser.grid.item(0).data(0x0100) == "灰斑鸻/b.jpg"
    assert "没有匹配" not in browser.status_label.text()


def test_completion_display_text_is_reduced_to_species_name(qtbot, tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "红翅凤头鹃" / "DSC_7699.jpg")
    browser = ArchiveBrowserWindow(output)
    qtbot.addWidget(browser)

    browser.search.setText("红翅凤头鹃 · Clamator coromandus · Chestnut-winged Cuckoo · hcftj")

    assert browser.search.text() == "红翅凤头鹃"
    assert browser.grid.count() == 1
    assert browser.grid.item(0).data(0x0100) == "红翅凤头鹃/DSC_7699.jpg"
    assert "没有匹配" not in browser.status_label.text()


def test_location_filter_and_sorting(qtbot, tmp_path: Path):
    output = tmp_path / "output"
    make_image(output / "三趾滨鹬" / "a.jpg")
    make_image(output / "欧乌鸫" / "b.jpg")
    library = ArchiveLibrary(output)
    library.ensure()
    batch = new_batch_id()
    add_group(library, "三趾滨鹬/a.jpg", batch_id=batch,
              species_cn="三趾滨鹬", species_latin="Calidris alba",
              location="云南大理", observed_at="2026-01-02")
    add_group(library, "欧乌鸫/b.jpg", batch_id=batch,
              species_cn="欧乌鸫", species_latin="Turdus merula",
              location="四川成都", observed_at="2026-01-01")
    browser = ArchiveBrowserWindow(output)
    qtbot.addWidget(browser)

    assert browser.location_combo.findData("云南大理") > 0
    browser.location_combo.setCurrentIndex(browser.location_combo.findData("云南大理"))
    assert browser.grid.count() == 1
    assert browser.grid.item(0).data(0x0100) == "三趾滨鹬/a.jpg"

    browser.location_combo.setCurrentIndex(0)
    browser.sort_combo.setCurrentIndex(browser.sort_combo.findData("species"))
    paths = [browser.grid.item(i).data(0x0100) for i in range(browser.grid.count())]
    assert paths == sorted(paths, key=lambda value: value.split("/", 1)[0].casefold())


def test_batch_issues_button_and_dialog(qtbot, tmp_path: Path):
    from PySide6.QtCore import Qt
    from birdclass.ui.batch_issues import BatchIssuesDialog

    output = tmp_path / "output"
    library = ArchiveLibrary(output)
    library.ensure()
    batch = new_batch_id()
    library.write_group({
        "schema_version": 1,
        "group_id": new_group_id(),
        "batch_id": batch,
        "status": "failed",
        "source_relative_path": "bad.jpg",
        "error_code": "ImageValidationError",
        "error_message": "broken",
        "targets": [],
        "copies": [],
    })
    browser = ArchiveBrowserWindow(output, batch_id=batch)
    qtbot.addWidget(browser)
    assert browser.issues_button.isVisible() or not browser.isVisible()
    assert "1" in browser.issues_button.text()
    issues = browser.index.batch_issues(batch)
    assert issues[0]["status"] == "failed"

    dialog = BatchIssuesDialog(batch, issues)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.windowTitle().startswith("批次失败/待复核")
    dialog.accept()
