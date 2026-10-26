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
        self.selected_name: str = ""
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
            aliases = self.taxonomy.aliases_for(taxon)
            haystack = " ".join((
                taxon.name_zh, taxon.name_zh_trad, taxon.name_en,
                taxon.scientific_name, taxon.family_label, *aliases,
            )).casefold()
            if needle and needle not in haystack:
                continue
            display = taxon.display_name
            if taxon.name_en and taxon.name_en != display:
                display += f" / {taxon.name_en}"
            label = f"{display}\n{taxon.scientific_name} · {taxon.family_label}"
            if needle and any(needle == alias.casefold() for alias in aliases) and needle != display.casefold():
                label = f"{self.search.text().strip()}（别名）\n{taxon.scientific_name} · {taxon.family_label}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, taxon)
            self.list.addItem(item)
            count += 1
            if count >= 200:
                break
        if needle:
            exact = any(
                needle in {taxon.name_zh.casefold(), taxon.name_en.casefold()} or
                needle in {alias.casefold() for alias in self.taxonomy.aliases_for(taxon)}
                for taxon in self.taxonomy.all_taxa()
            )
            if not exact:
                item = QListWidgetItem(
                    f"使用「{self.search.text().strip()}」作为人工鸟名\n"
                    "不在 IOC 名录中；仍可按该名称归档"
                )
                item.setData(Qt.ItemDataRole.UserRole, ("manual", self.search.text().strip()))
                self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def accept(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        value = item.data(Qt.ItemDataRole.UserRole)
        query = self.search.text().strip()
        if isinstance(value, Taxon):
            self.selected_taxon = value
            if query and query.casefold() in {
                alias.casefold() for alias in self.taxonomy.aliases_for(value)
            }:
                self.selected_name = query
            else:
                self.selected_name = value.display_name
        elif isinstance(value, tuple) and len(value) == 2 and value[0] == "manual":
            name = value[1]
            self.selected_name = name
            self.selected_taxon = Taxon(
                taxonomy_key="",
                scientific_name="",
                name_zh=name,
                name_zh_trad="",
                name_en="",
                genus="",
                genus_zh="",
                family="",
                order="",
                animal_class="鸟纲",
                phylum="",
                kingdom="",
            )
        super().accept()
