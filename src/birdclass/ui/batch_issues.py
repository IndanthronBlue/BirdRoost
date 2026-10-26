from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

STATUS_LABELS = {
    "failed": "失败",
    "review_pending": "待复核",
}


class BatchIssuesDialog(QDialog):
    def __init__(self, batch_id: str, issues: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"批次失败/待复核 · {batch_id[:8]}…")
        self.resize(900, 460)
        layout = QVBoxLayout(self)
        failed = sum(1 for issue in issues if issue.get("status") == "failed")
        pending = sum(1 for issue in issues if issue.get("status") == "review_pending")
        layout.addWidget(QLabel(f"失败 {failed} · 待复核 {pending}"))
        table = QTableWidget(len(issues), 5, self)
        table.setHorizontalHeaderLabels(["状态", "源文件", "观测地", "错误/说明", "副本"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for row, issue in enumerate(issues):
            status = STATUS_LABELS.get(str(issue.get("status", "")), str(issue.get("status", "")))
            values = [
                status,
                str(issue.get("source_relative_path", "")),
                str(issue.get("observation_location", "")),
                str(issue.get("error_message", "")),
                str(issue.get("copies", "")),
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        table.resizeColumnsToContents()
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
