from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..archive_index import ArchiveEntry
from .image_canvas import CanvasBox, ZoomableImageCanvas


class LightboxDialog(QDialog):
    """Full-screen image inspection with keyboard navigation."""

    def __init__(
        self,
        entries: list[ArchiveEntry],
        start_index: int,
        *,
        boxes_provider=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.entries = entries
        self.index = max(0, min(start_index, len(entries) - 1)) if entries else 0
        self._boxes_provider = boxes_provider
        self.setWindowTitle("羽栖 BirdRoost · 全屏预览")
        self.setWindowFlag(Qt.WindowType.Window, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = ZoomableImageCanvas()
        layout.addWidget(self.canvas, 1)
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet("padding: 8px;")
        layout.addWidget(self.caption)
        controls = QHBoxLayout()
        self.prev_button = QPushButton("上一张")
        self.prev_button.clicked.connect(self.previous)
        controls.addWidget(self.prev_button)
        self.next_button = QPushButton("下一张")
        self.next_button.clicked.connect(self.next)
        controls.addWidget(self.next_button)
        controls.addStretch(1)
        self.copy_button = QPushButton("复制图片")
        self.copy_button.clicked.connect(lambda: self.copy(False))
        controls.addWidget(self.copy_button)
        self.copy_boxes_button = QPushButton("复制带框图")
        self.copy_boxes_button.clicked.connect(lambda: self.copy(True))
        controls.addWidget(self.copy_boxes_button)
        self.fit_button = QPushButton("适应")
        self.fit_button.clicked.connect(self.canvas.fit_to_window)
        controls.addWidget(self.fit_button)
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.accept)
        controls.addWidget(self.close_button)
        layout.addLayout(controls)
        self._load()

    def _load(self) -> None:
        if not self.entries:
            self.caption.setText("没有图片")
            return
        entry = self.entries[self.index]
        boxes = self._boxes_provider(entry) if self._boxes_provider else []
        self.canvas.load_image(entry.absolute_path, boxes=boxes)
        self.canvas.set_show_boxes(bool(boxes))
        self.caption.setText(
            f"{entry.display_name} · {self.index + 1}/{len(self.entries)}\n{entry.relative_path}"
        )
        self.prev_button.setEnabled(self.index > 0)
        self.next_button.setEnabled(self.index < len(self.entries) - 1)

    def previous(self) -> None:
        if self.index > 0:
            self.index -= 1
            self._load()

    def next(self) -> None:
        if self.index < len(self.entries) - 1:
            self.index += 1
            self._load()

    def copy(self, include_boxes: bool) -> None:
        image = self.canvas.render_image(include_boxes=include_boxes)
        if image is not None and not image.isNull():
            QApplication.clipboard().setImage(image)
            self.caption.setText(
                ("已复制带框图" if include_boxes else "已复制图片")
                + f" · {self.entries[self.index].relative_path}"
            )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Left:
            self.previous()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Right:
            self.next()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
            return
        if event.key() == Qt.Key.Key_F:
            if self.isFullScreen():
                self.showMaximized()
            else:
                self.showFullScreen()
            event.accept()
            return
        super().keyPressEvent(event)
