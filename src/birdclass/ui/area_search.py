from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter


def configure_area_search(combo: QComboBox) -> None:
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    completer = QCompleter(combo.model(), combo)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    combo.setCompleter(completer)
    combo.lineEdit().setPlaceholderText("输入中文、英文或地区代码进行匹配")


def resolve_area_code(combo: QComboBox) -> str:
    text = combo.currentText().strip()
    if not text:
        raise ValueError("请从下拉列表中选择有效国家／地区")
    folded = text.casefold()
    entries = [
        (combo.itemText(index), str(combo.itemData(index)))
        for index in range(combo.count())
    ]
    for label, code in entries:
        if code.casefold() == folded or label.casefold() == folded:
            return code
    primary_matches = [
        code for label, code in entries
        if label.split(" — ", 1)[0].casefold() == folded
    ]
    if len(primary_matches) == 1:
        return primary_matches[0]
    matches = [code for label, code in entries if folded in label.casefold()]
    if len(matches) == 1:
        return matches[0]
    raise ValueError("请从下拉列表中选择有效国家／地区，或输入更完整的名称")
