from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..archive_index import ArchiveEntry
from .image_canvas import ZoomableImageCanvas


class CompareDialog(QDialog):
    """Two independently zoomable archived images."""

    def __init__(self, entries: list[ArchiveEntry], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("羽栖 BirdRoost · 图片比较")
        self.resize(1400, 850)
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        self.canvases: list[ZoomableImageCanvas] = []
        for entry in entries[:2]:
            panel = QWidget()
            panel_layout = QVBoxLayout(panel)
            row = QHBoxLayout()
            label = QLabel(f"{entry.display_name} · {entry.relative_path}")
            label.setWordWrap(True)
            row.addWidget(label, 1)
            canvas = ZoomableImageCanvas()
            canvas.setMinimumSize(320, 240)
            self.canvases.append(canvas)
            for text, slot_name in (("−", "zoom_out"), ("+", "zoom_in"), ("适应", "fit_to_window"), ("1:1", "actual_size")):
                button = QPushButton(text)
                button.setFixedWidth(48)
                button.clicked.connect(getattr(canvas, slot_name))
                row.addWidget(button)
            panel_layout.addLayout(row)
            canvas.load_image(entry.absolute_path, boxes=[])
            canvas.set_show_boxes(False)
            panel_layout.addWidget(canvas, 1)
            splitter.addWidget(panel)
        layout.addWidget(splitter, 1)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
