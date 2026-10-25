from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..models import ReviewAction, ReviewContext, ReviewResult
from .image_canvas import CanvasBox, ZoomableImageCanvas


class ReviewDialog(QDialog):
    def __init__(self, context: ReviewContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.result = ReviewResult(ReviewAction.STOP)
        self.setWindowTitle("需要人工确认识别结果")
        self.resize(900, 600)

        layout = QVBoxLayout(self)
        reason = {
            "low_confidence": "最高候选置信度较低",
            "ambiguous": "前两名候选置信度接近",
            "low_confidence+ambiguous": "最高置信度较低，且前两名候选接近",
        }.get(context.reason, "请人工确认识别结果")
        gap = "无" if context.confidence_gap is None else f"{context.confidence_gap:.2f} 个百分点"
        description = QLabel(
            f"目标 {context.target_index + 1}/{context.target_count} · {context.relative_path}\n"
            f"{reason}；当前差值：{gap}。请选择正确鸟种、输入人工鸟名，或稍后处理。"
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        splitter = QSplitter()
        image_panel = QWidget()
        image_layout = QVBoxLayout(image_panel)
        zoom_row = QHBoxLayout()
        for text, slot in (
            ("−", lambda: self.image_canvas.zoom_out()),
            ("+", lambda: self.image_canvas.zoom_in()),
            ("适应", lambda: self.image_canvas.fit_to_window()),
            ("1:1", lambda: self.image_canvas.actual_size()),
        ):
            button = QPushButton(text)
            button.setFixedWidth(48)
            button.clicked.connect(slot)
            zoom_row.addWidget(button)
        zoom_row.addStretch(1)
        image_layout.addLayout(zoom_row)
        self.image_canvas = ZoomableImageCanvas()
        self.image_canvas.setMinimumSize(360, 300)
        image_layout.addWidget(self.image_canvas, 1)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_layout.addWidget(self.preview_label)
        splitter.addWidget(image_panel)

        candidate_panel = QWidget()
        candidate_layout = QVBoxLayout(candidate_panel)
        candidate_layout.addWidget(QLabel("识别候选（按置信度从高到低）"))
        self.candidate_list = QListWidget()
        self.candidate_list.setAlternatingRowColors(True)
        self.candidate_list.setWordWrap(True)
        line_height = self.candidate_list.fontMetrics().height()
        for candidate in context.candidates:
            names = " / ".join(filter(None, [candidate.name_en, candidate.name_latin]))
            text = f"{candidate.name_cn}    {candidate.confidence_percent:.2f}%"
            if names:
                text += f"\n{names}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, candidate.source_order)
            item.setSizeHint(QSize(0, line_height * (2 if names else 1) + 10))
            self.candidate_list.addItem(item)
        self.candidate_list.setCurrentRow(0)
        self.candidate_list.itemDoubleClicked.connect(lambda _item: self.confirm())
        candidate_layout.addWidget(self.candidate_list)
        candidate_layout.addWidget(QLabel("候选都不正确时，输入人工确认的鸟种中文名"))
        self.custom_name = QLineEdit()
        self.custom_name.setPlaceholderText("例如：白鹡鸰")
        self.custom_name.setClearButtonEnabled(True)
        self.custom_button = QPushButton("按人工鸟名归档")
        self.custom_button.setEnabled(False)
        self.custom_name.textChanged.connect(
            lambda text: self.custom_button.setEnabled(bool(text.strip()))
        )
        self.custom_name.returnPressed.connect(self.confirm_custom)
        self.custom_button.clicked.connect(self.confirm_custom)
        candidate_layout.addWidget(self.custom_name)
        candidate_layout.addWidget(self.custom_button)
        self.apply_remaining = QCheckBox("后面同样（应用到本图剩余目标）")
        self.apply_remaining.setToolTip(
            "勾选后，确认所选鸟种或按人工鸟名归档时，本次选择会应用到本图所有"
            "尚未确认的后续检测目标；每个目标仍单独记录选择。"
        )
        candidate_layout.addWidget(self.apply_remaining)
        splitter.addWidget(candidate_panel)
        splitter.setSizes([520, 360])
        layout.addWidget(splitter, 1)

        buttons = QDialogButtonBox()
        self.confirm_button = QPushButton("确认所选鸟种")
        self.confirm_button.setDefault(True)
        self.defer_button = QPushButton("稍后处理（仅当前目标）")
        self.stop_button = QPushButton("停止本批次")
        buttons.addButton(self.confirm_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self.defer_button, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.addButton(self.stop_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.confirm_button.clicked.connect(self.confirm)
        self.defer_button.clicked.connect(self.defer)
        self.stop_button.clicked.connect(self.reject)
        layout.addWidget(buttons)
        self._load_preview()

    def confirm(self) -> None:
        row = self.candidate_list.currentRow()
        if row < 0:
            return
        self.result = ReviewResult(
            ReviewAction.CONFIRM,
            self.context.candidates[row],
            apply_to_remaining=self.apply_remaining.isChecked(),
        )
        self.accept()

    def defer(self) -> None:
        self.result = ReviewResult(ReviewAction.DEFER)
        self.accept()

    def confirm_custom(self) -> None:
        name = self.custom_name.text().strip()
        if not name:
            return
        self.result = ReviewResult(
            ReviewAction.CUSTOM,
            custom_name_cn=name,
            apply_to_remaining=self.apply_remaining.isChecked(),
        )
        self.accept()

    def reject(self) -> None:
        self.result = ReviewResult(ReviewAction.STOP)
        super().reject()

    def _load_preview(self) -> None:
        boxes = []
        if self.context.box is not None:
            boxes.append(CanvasBox(self.context.box, label=str(self.context.target_index + 1), highlighted=True))
        loaded = self.image_canvas.load_image(self.context.image_path, boxes=boxes)
        self.image_canvas.set_show_boxes(True)
        self.preview_label.setText("" if loaded else "无法加载原图预览")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
