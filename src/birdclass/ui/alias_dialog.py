from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ..taxonomy import Taxon


class AliasDialog(QDialog):
    def __init__(self, taxon: Taxon, parent=None) -> None:
        super().__init__(parent)
        self.taxon = taxon
        self.alias = ""
        self.setWindowTitle("添加检索别名")
        self.resize(420, 180)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"为「{taxon.display_name} · {taxon.scientific_name}」添加别名。\n"
            "别名只用于搜索/联想，不改变 IOC 正式名。"
        ))
        self.alias_edit = QLineEdit()
        self.alias_edit.setPlaceholderText("例如：伊比利亚灰喜鹊")
        self.alias_edit.setClearButtonEnabled(True)
        layout.addWidget(self.alias_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.alias_edit.textChanged.connect(
            lambda text: buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(text.strip()))
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def accept(self) -> None:
        self.alias = " ".join(self.alias_edit.text().split())
        if not self.alias:
            return
        super().accept()
