from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from ..taxonomy import Taxon, Taxonomy


class SpeciesPickerDialog(QDialog):
    def __init__(
        self,
        taxonomy: Taxonomy,
        *,
        initial: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.taxonomy = taxonomy
        self.selected_taxon: Taxon | None = None
        self.setWindowTitle("选择正确的鸟种")
        self.resize(560, 460)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索中文名、英文名或拉丁名")
        self.search.setClearButtonEnabled(True)
        self.search.setText(initial)
        self.search.textChanged.connect(self._populate)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate()

    def _populate(self) -> None:
        needle = self.search.text().strip().casefold()
        self.list.clear()
        count = 0
        for taxon in self.taxonomy.all_taxa():
            haystack = " ".join((
                taxon.name_zh, taxon.name_zh_trad, taxon.name_en,
                taxon.scientific_name, taxon.family_label,
            )).casefold()
            if needle and needle not in haystack:
                continue
            display = taxon.display_name
            if taxon.name_en and taxon.name_en != display:
                display += f" / {taxon.name_en}"
            item = QListWidgetItem(f"{display}\n{taxon.scientific_name} · {taxon.family_label}")
            item.setData(Qt.ItemDataRole.UserRole, taxon)
            self.list.addItem(item)
            count += 1
            if count >= 200:
                break
        if self.list.count():
            self.list.setCurrentRow(0)

    def accept(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        self.selected_taxon = item.data(Qt.ItemDataRole.UserRole)
        super().accept()
