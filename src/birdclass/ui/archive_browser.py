from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..archive_index import ArchiveEntry, ArchiveIndex
from ..correction import CorrectionError, correct_archive_copy
from ..library import ArchiveLibrary
from ..library_import import import_csv_to_library
from .image_canvas import CanvasBox, ZoomableImageCanvas
from .species_picker import SpeciesPickerDialog


class ArchiveBrowserWindow(QMainWindow):
    """Read-only archive browser; correction is added by the correction module."""

    def __init__(
        self,
        output_root: Path,
        *,
        batch_id: str | None = None,
        parent: QWidget | None = None,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self.output_root = Path(output_root)
        self.batch_id = batch_id
        self._settings = settings or QSettings("BirdClass", "BirdClass")
        self.language = str(self._settings.value("archive_tree_language", "zh"))
        if self.language not in {"zh", "bilingual", "latin"}:
            self.language = "zh"
        self.index = ArchiveIndex(self.output_root)
        self.library = ArchiveLibrary(self.output_root)
        self._tree_items: dict[tuple[str, ...], QTreeWidgetItem] = {}
        self._selected_entry_path = ""
        self._initialized = False
        self._closed = False
        self._updating_batch_combo = False
        self._thumbnail_cache: dict[tuple[str, float], QIcon] = {}
        self._watcher = QFileSystemWatcher(self)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(400)
        self._refresh_timer.timeout.connect(self.refresh)
        self._watcher.directoryChanged.connect(self._on_watched_change)
        self._build_ui()
        self._setup_watcher()
        self.refresh()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        self.setWindowTitle(
            "羽栖 BirdRoost · 批次结果" if self.batch_id else "羽栖 BirdRoost · 浏览归档"
        )
        self.resize(1440, 860)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索中文名、拉丁名、英文名或路径")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self.search, 1)

        self.language_combo = QComboBox()
        self.language_combo.addItem("中文", "zh")
        self.language_combo.addItem("中英", "bilingual")
        self.language_combo.addItem("拉丁", "latin")
        self.language_combo.setToolTip("分类树显示语言；中文缺失时回退拉丁名")
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        language_index = self.language_combo.findData(self.language)
        self.language_combo.setCurrentIndex(max(0, language_index))
        toolbar.addWidget(self.language_combo)

        self.batch_combo = QComboBox()
        self.batch_combo.setMinimumWidth(250)
        self.batch_combo.currentIndexChanged.connect(self._on_batch_combo_changed)
        toolbar.addWidget(self.batch_combo)
        self.batch_label = QLabel()
        toolbar.addWidget(self.batch_label)
        self.clear_batch_button = QPushButton("显示全部")
        self.clear_batch_button.clicked.connect(self.clear_batch_filter)
        self.clear_batch_button.setVisible(bool(self.batch_id))
        toolbar.addWidget(self.clear_batch_button)

        self.box_toggle = QCheckBox("显示检测框")
        self.box_toggle.setChecked(bool(self.batch_id))
        self.box_toggle.toggled.connect(self._on_box_toggled)
        toolbar.addWidget(self.box_toggle)

        for text, slot in (
            ("−", lambda: self.canvas.zoom_out()),
            ("+", lambda: self.canvas.zoom_in()),
            ("适应", lambda: self.canvas.fit_to_window()),
            ("1:1", lambda: self.canvas.actual_size()),
        ):
            button = QPushButton(text)
            button.setFixedWidth(48)
            button.clicked.connect(slot)
            toolbar.addWidget(button)

        self.copy_button = QPushButton("复制图片")
        self.copy_button.clicked.connect(lambda: self.copy_image(False))
        toolbar.addWidget(self.copy_button)
        self.copy_annotated_button = QPushButton("复制带框图")
        self.copy_annotated_button.clicked.connect(lambda: self.copy_image(True))
        toolbar.addWidget(self.copy_annotated_button)
        self.copy_path_button = QPushButton("复制路径")
        self.copy_path_button.clicked.connect(self.copy_path)
        toolbar.addWidget(self.copy_path_button)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self.refresh_button)
        self.cleanup_button = QPushButton("清理已纠正")
        self.cleanup_button.clicked.connect(self.cleanup_replaced)
        self.cleanup_button.setVisible(False)
        toolbar.addWidget(self.cleanup_button)
        self.import_button = QPushButton("导入旧 CSV")
        self.import_button.setToolTip("从旧 birdclass_records.csv 导入批次和检测框数据")
        self.import_button.clicked.connect(self.import_old_csv)
        toolbar.addWidget(self.import_button)
        root.addLayout(toolbar)

        self.summary_label = QLabel("正在读取归档…")
        root.addWidget(self.summary_label)

        splitter = QSplitter()
        self.splitter = splitter
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        splitter.setStyleSheet(
            "QSplitter::handle { background: palette(mid); }"
            "QSplitter::handle:horizontal { width: 8px; }"
        )
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["分类", "数量"])
        self.tree.setColumnWidth(0, 300)
        self.tree.setMinimumWidth(220)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        splitter.addWidget(self.tree)

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(160, 120))
        self.grid.setGridSize(QSize(190, 165))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.grid.setMinimumWidth(300)
        self.grid.currentItemChanged.connect(self._on_grid_selection)
        splitter.addWidget(self.grid)

        detail = QWidget()
        detail.setMinimumWidth(420)
        detail_layout = QVBoxLayout(detail)
        self.canvas = ZoomableImageCanvas()
        detail_layout.addWidget(self.canvas, 1)
        self.species_label = QLabel("未选择图片")
        self.species_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.species_label.setWordWrap(True)
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_layout.addWidget(self.species_label)
        detail_layout.addWidget(self.info_label)
        self.target_label = QLabel("目标")
        self.target_label.setVisible(False)
        detail_layout.addWidget(self.target_label)
        self.target_list = QListWidget()
        self.target_list.setMaximumHeight(110)
        self.target_list.setVisible(False)
        detail_layout.addWidget(self.target_list)
        self.correct_button = QPushButton("修改分类…")
        self.correct_button.setVisible(False)
        self.correct_button.clicked.connect(self.correct_selected)
        detail_layout.addWidget(self.correct_button)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 2)
        self._restore_splitter_sizes()
        splitter.splitterMoved.connect(self._save_splitter_sizes)
        root.addWidget(splitter, 1)

        self.status_label = QLabel("就绪")
        root.addWidget(self.status_label)

    # ---------- refresh / tree ----------

    def refresh(self) -> None:
        if self._closed:
            return
        expanded = {
            path for path, item in self._tree_items.items() if item.isExpanded()
        }
        self.index.refresh()
        self._update_batch_combo()
        entries = self._visible_entries()
        self._rebuild_tree(entries)
        self._restore_tree_state(expanded)
        self._refresh_grid()
        self._update_summary()
        self.cleanup_button.setVisible((self.output_root / "已纠正").exists())
        self._setup_watcher()

    def _visible_entries(self) -> list[ArchiveEntry]:
        return self.index.filter_entries(batch_id=self.batch_id)

    def _rebuild_tree(self, entries: list[ArchiveEntry]) -> None:
        self.tree.clear()
        self._tree_items = {}
        counts = self.index.count_by_tree_path(entries)
        labels: dict[tuple[str, ...], str] = {}
        for entry in entries:
            self._collect_labels(entry, labels)

        def ensure(path: tuple[str, ...]) -> QTreeWidgetItem:
            if path in self._tree_items:
                return self._tree_items[path]
            parent = ensure(path[:-1]) if len(path) > 1 else None
            item = QTreeWidgetItem([labels.get(path, path[-1]), ""])
            item.setData(0, Qt.ItemDataRole.UserRole, list(path))
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            self._tree_items[path] = item
            return item

        for path in sorted(counts, key=lambda value: (len(value), value)):
            item = ensure(path)
            item.setText(1, str(counts[path]))
        for path, item in self._tree_items.items():
            if len(path) == 1:
                item.setExpanded(True)
        if not self._initialized:
            self._initialized = True
            self.tree.expandToDepth(1)
        self.tree.sortItems(0, Qt.SortOrder.AscendingOrder)

    def _collect_labels(self, entry: ArchiveEntry, labels: dict[tuple[str, ...], str]) -> None:
        path = entry.tree_path
        for index, _value in enumerate(path):
            key = path[:index + 1]
            labels.setdefault(key, self._node_label(entry, index, key))

    def _display_label(self, chinese: str, latin: str) -> str:
        if self.language == "latin":
            return latin or chinese
        if self.language == "bilingual":
            if chinese and latin and chinese != latin:
                return f"{chinese} {latin}"
            return chinese or latin
        return chinese or latin

    def _node_label(self, entry: ArchiveEntry, index: int, prefix: tuple[str, ...]) -> str:
        if entry.taxonomy is not None:
            if index < len(entry.taxonomy.hierarchy()):
                _, chinese, latin = entry.taxonomy.hierarchy()[index]
                return self._display_label(chinese, latin)
        if prefix[0] == "未收录" and len(prefix) > 1:
            return prefix[-1]
        return prefix[-1]

    def _restore_tree_state(self, expanded: set[tuple[str, ...]]) -> None:
        selected_path = self._selected_entry_path
        selected_item = None
        for path, item in self._tree_items.items():
            if path in expanded:
                item.setExpanded(True)
        if selected_path:
            for entry in self.index.entries:
                if entry.relative_path == selected_path:
                    item = self._tree_items.get(entry.tree_path)
                    if item is not None:
                        selected_item = item
                    break
        if selected_item is None and self._tree_items:
            selected_item = next(iter(self._tree_items.values()))
        if selected_item is not None:
            self.tree.setCurrentItem(selected_item)

    def _on_tree_selection(self) -> None:
        self._refresh_grid()

    def _selected_tree_path(self) -> tuple[str, ...] | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        return tuple(data) if data else None

    def _refresh_grid(self) -> None:
        tree_path = self._selected_tree_path()
        entries = self.index.filter_entries(
            tree_path=tree_path,
            batch_id=self.batch_id,
            search=self.search.text(),
        )
        self.grid.blockSignals(True)
        self.grid.clear()
        selected_item = None
        for entry in entries:
            item = QListWidgetItem(self._thumbnail(entry), self._grid_text(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry.relative_path)
            item.setToolTip(entry.relative_path)
            self.grid.addItem(item)
            if entry.relative_path == self._selected_entry_path:
                selected_item = item
        self.grid.blockSignals(False)
        if selected_item is None and self.grid.count():
            selected_item = self.grid.item(0)
        if selected_item is not None:
            self.grid.setCurrentItem(selected_item)
        else:
            self._clear_detail()
        self._update_summary()

    @staticmethod
    def _grid_text(entry: ArchiveEntry) -> str:
        return f"{entry.display_name}\n{Path(entry.relative_path).name}"

    def _thumbnail(self, entry: ArchiveEntry) -> QIcon:
        try:
            mtime = entry.absolute_path.stat().st_mtime
        except OSError:
            return QIcon()
        key = (entry.relative_path, mtime)
        cached = self._thumbnail_cache.get(key)
        if cached is not None:
            return cached
        reader = QImageReader(str(entry.absolute_path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            target = size.scaled(QSize(160, 120), Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(target)
        image = reader.read()
        icon = QIcon(QPixmap.fromImage(image)) if not image.isNull() else QIcon()
        self._thumbnail_cache[key] = icon
        return icon

    # ---------- detail ----------

    def _on_grid_selection(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            self._clear_detail()
            return
        relative_path = current.data(Qt.ItemDataRole.UserRole)
        entry = next(
            (value for value in self.index.entries if value.relative_path == relative_path),
            None,
        )
        if entry is None:
            return
        self._selected_entry_path = entry.relative_path
        self._show_entry(entry)

    def _entry_boxes(self, entry: ArchiveEntry) -> list[CanvasBox]:
        boxes: list[CanvasBox] = []
        highlight = set(entry.target_indices)
        for target in entry.group.get("targets", []):
            box = target.get("box")
            if not box:
                continue
            index = int(target.get("target_index", len(boxes)))
            highlighted = index in highlight if highlight else True
            boxes.append(CanvasBox(
                box=tuple(float(value) for value in box),
                label=str(index + 1),
                highlighted=highlighted,
            ))
        return boxes

    def _show_entry(self, entry: ArchiveEntry) -> None:
        loaded = self.canvas.load_image(entry.absolute_path, boxes=self._entry_boxes(entry))
        self.canvas.set_show_boxes(self.box_toggle.isChecked())
        self.box_toggle.setEnabled(self.canvas.has_boxes())
        self.species_label.setText(entry.display_name)
        details = [
            f"路径：{entry.relative_path}",
            f"分类：{entry.latin_name or '未匹配 taxonomy'}",
        ]
        if entry.batch_id:
            details.append(f"批次：{entry.batch_id}")
        if entry.group_id:
            details.append(f"group：{entry.group_id}")
        details.append(f"检测框：{len(self._entry_boxes(entry))}")
        if not loaded:
            details.append("图片无法读取")
        self.info_label.setText("\n".join(details))
        self._populate_targets(entry)
        self.correct_button.setVisible(bool(entry.group_id) and not entry.special)
        self.correct_button.setEnabled(bool(entry.group_id) and not entry.special)
        self.status_label.setText(f"{entry.relative_path} · {len(self._entry_boxes(entry))} 个框")

    def _populate_targets(self, entry: ArchiveEntry) -> None:
        self.target_list.blockSignals(True)
        self.target_list.clear()
        for target in entry.group.get("targets", []):
            selection = target.get("selection") or {}
            index = int(target.get("target_index", 0))
            name = selection.get("species_cn") or entry.species_cn
            confidence = selection.get("confidence_percent")
            text = f"目标 {index + 1} · {name}"
            if confidence:
                text += f" · {confidence}%"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.target_list.addItem(item)
            if index in entry.target_indices:
                self.target_list.setCurrentItem(item)
        if self.target_list.currentItem() is None and self.target_list.count():
            self.target_list.setCurrentRow(0)
        self.target_list.blockSignals(False)
        visible = self.target_list.count() > 0
        self.target_label.setVisible(visible)
        self.target_list.setVisible(visible)

    def _selected_target_index(self) -> int | None:
        item = self.target_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def _clear_detail(self) -> None:
        self._selected_entry_path = ""
        self.canvas.clear()
        self.species_label.setText("未选择图片")
        self.info_label.setText("")
        self.target_list.clear()
        self.target_list.setVisible(False)
        self.target_label.setVisible(False)
        self.correct_button.setVisible(False)
        self.box_toggle.setEnabled(False)
        self.status_label.setText("就绪")

    # ---------- actions ----------

    def _on_language_changed(self, _index: int) -> None:
        language = self.language_combo.currentData()
        if language not in {"zh", "bilingual", "latin"} or language == self.language:
            return
        self.language = language
        self._settings.setValue("archive_tree_language", language)
        self.refresh()

    def _restore_splitter_sizes(self) -> None:
        saved = self._settings.value("archive_splitter_sizes")
        sizes = None
        if isinstance(saved, (list, tuple)) and len(saved) == 3:
            sizes = [int(value) for value in saved]
        elif isinstance(saved, str) and saved:
            try:
                parts = [int(value) for value in saved.split(",")]
                if len(parts) == 3:
                    sizes = parts
            except ValueError:
                sizes = None
        if sizes and all(value >= 150 for value in sizes):
            self.splitter.setSizes(sizes)
        else:
            self.splitter.setSizes([280, 520, 760])

    def _save_splitter_sizes(self, *_args) -> None:
        self._settings.setValue("archive_splitter_sizes", self.splitter.sizes())

    def _on_search_changed(self, _text: str) -> None:
        self._refresh_grid()

    def _on_box_toggled(self, checked: bool) -> None:
        self.canvas.set_show_boxes(checked)
        if checked and not self.canvas.has_boxes():
            self.status_label.setText("该图片没有检测框数据")
            return
        self.status_label.setText("已显示检测框" if checked else "已隐藏检测框")

    def copy_image(self, annotated: bool) -> None:
        image = self.canvas.render_image(include_boxes=annotated)
        if image is None or image.isNull():
            self.status_label.setText("没有可复制的图片")
            return
        QApplication.clipboard().setImage(image)
        self.status_label.setText("已复制带框图" if annotated else "已复制图片")

    def copy_path(self) -> None:
        if self._selected_entry_path:
            QApplication.clipboard().setText(self._selected_entry_path)
            self.status_label.setText("已复制相对路径")

    def correct_selected(self) -> None:
        entry = next(
            (value for value in self.index.entries
             if value.relative_path == self._selected_entry_path),
            None,
        )
        if entry is None or entry.special or not entry.group_id:
            QMessageBox.warning(self, "羽栖 BirdRoost", "该图片没有可用的归档库记录，不能纠错。")
            return
        picker = SpeciesPickerDialog(
            self.index.taxonomy,
            initial=entry.species_cn,
            parent=self,
        )
        if not picker.exec() or picker.selected_taxon is None:
            return
        taxon = picker.selected_taxon
        target_indices = None
        if self.batch_id:
            target_index = self._selected_target_index()
            if target_index is None:
                QMessageBox.warning(self, "羽栖 BirdRoost", "请先在目标列表中选择一个目标。")
                return
            target_indices = {target_index}
        answer = QMessageBox.question(
            self,
            "确认修改分类",
            f"将这张副本改为「{taxon.display_name}」。\n"
            "旧副本会保留到「已纠正」目录，可稍后删除。\n"
            "源图和 CSV 不会被修改。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            outcome = correct_archive_copy(
                self.library, entry, taxon, target_indices=target_indices
            )
        except CorrectionError as exc:
            QMessageBox.warning(self, "羽栖 BirdRoost", str(exc))
            return
        self._selected_entry_path = outcome.new_relative_path
        self.status_label.setText(
            f"已改为 {taxon.display_name}；旧副本：{outcome.replaced_relative_path or '保留'}"
        )
        self.refresh()

    def import_old_csv(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self, "选择 birdclass_records.csv", str(self.output_root.parent), "CSV (*.csv)"
        )
        if not selected:
            return
        result = import_csv_to_library(Path(selected), self.output_root)
        message = f"已导入 {result.imported} 张，跳过 {result.skipped} 张。"
        if result.errors:
            message += f"\n有 {len(result.errors)} 条记录解析失败。"
        QMessageBox.information(self, "导入旧 CSV", message)
        self.refresh()

    def cleanup_replaced(self) -> None:
        folder = self.output_root / "已纠正"
        if not folder.exists():
            self.status_label.setText("没有已纠正副本")
            return
        files = [path for path in folder.rglob("*") if path.is_file()]
        if not files:
            self.status_label.setText("没有已纠正副本")
            return
        answer = QMessageBox.question(
            self,
            "清理已纠正副本",
            f"将永久删除 {len(files)} 个已纠正副本。\n"
            "这些文件不再被归档库引用，删除后不可恢复。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(folder)
        except OSError as exc:
            QMessageBox.warning(self, "羽栖 BirdRoost", f"清理失败：{exc}")
            return
        self.status_label.setText(f"已删除 {len(files)} 个已纠正副本")
        self.refresh()

    def clear_batch_filter(self) -> None:
        self.batch_id = None
        self.clear_batch_button.setVisible(False)
        self.setWindowTitle("羽栖 BirdRoost · 浏览归档")
        self.refresh()

    def _update_batch_combo(self) -> None:
        self._updating_batch_combo = True
        try:
            self.batch_combo.clear()
            self.batch_combo.addItem("全部归档", "")
            batches = sorted(
                self.library.load_batches(),
                key=lambda batch: str(batch.get("finished_at") or batch.get("started_at") or ""),
                reverse=True,
            )
            for batch in batches[:30]:
                batch_id = str(batch.get("batch_id") or "")
                stamp = str(batch.get("finished_at") or batch.get("started_at") or "")[:16]
                self.batch_combo.addItem(f"{stamp} · {batch_id[:8]}…", batch_id)
            index = self.batch_combo.findData(self.batch_id or "")
            self.batch_combo.setCurrentIndex(max(0, index))
        finally:
            self._updating_batch_combo = False

    def _on_batch_combo_changed(self, _index: int) -> None:
        if self._updating_batch_combo:
            return
        selected = self.batch_combo.currentData() or None
        if selected == self.batch_id:
            return
        self.batch_id = selected
        self.clear_batch_button.setVisible(bool(self.batch_id))
        self.setWindowTitle(
            "羽栖 BirdRoost · 批次结果" if self.batch_id else "羽栖 BirdRoost · 浏览归档"
        )
        self.refresh()

    def _update_summary(self) -> None:
        if self.batch_id:
            self.batch_label.setText(f"批次：{self.batch_id[:8]}…")
            batch = next(
                (value for value in self.library.load_batches() if value.get("batch_id") == self.batch_id),
                None,
            )
            if batch:
                summary = batch.get("summary", {})
                self.summary_label.setText(
                    f"本批共 {summary.get('total', 0)} · 完成 {summary.get('completed', 0)} · "
                    f"失败 {summary.get('failed', 0)} · 待复核 {summary.get('deferred', 0)} · "
                    f"当前树显示 {len(self._visible_entries())} 张"
                )
            else:
                self.summary_label.setText(f"当前批次 {len(self._visible_entries())} 张")
        else:
            self.batch_label.setText("全部归档")
            self.summary_label.setText(f"归档共 {len(self.index.entries)} 张图片")

    # ---------- dynamic updates ----------

    def _setup_watcher(self) -> None:
        if self._closed:
            return
        paths = [self.output_root, self.library.groups_dir, self.library.batches_dir]
        for path in paths:
            if path.exists() and str(path) not in self._watcher.directories():
                self._watcher.addPath(str(path))
        for path in self._watcher.directories():
            if Path(path) not in paths:
                self._watcher.removePath(path)

    def _on_watched_change(self, _path: str) -> None:
        if not self._closed:
            self._refresh_timer.start()

    def closeEvent(self, event) -> None:
        self._closed = True
        self._refresh_timer.stop()
        try:
            self._watcher.deleteLater()
        except RuntimeError:
            pass
        super().closeEvent(event)
