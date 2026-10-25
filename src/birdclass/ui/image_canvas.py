from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

HIGHLIGHT_COLOR = QColor("#ffb020")
MUTED_COLOR = QColor("#9aa59a")


@dataclass(frozen=True)
class CanvasBox:
    box: tuple[float, float, float, float]
    label: str = ""
    highlighted: bool = False


class ZoomableImageCanvas(QGraphicsView):
    """A reusable image view with fit/zoom/pan and normalized box overlays."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#111713"))
        self.setMinimumSize(320, 240)
        self._image: QImage | None = None
        self._pixmap_item = None
        self._boxes: list[CanvasBox] = []
        self._box_items: list = []
        self._show_boxes = False
        self._auto_fit = True

    @property
    def image(self) -> QImage | None:
        return self._image

    @property
    def show_boxes(self) -> bool:
        return self._show_boxes

    def load_image(self, path: str | Path, boxes: list[CanvasBox] | None = None) -> bool:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            self.clear()
            return False
        self.set_image(image, boxes=boxes)
        return True

    def set_image(self, image: QImage, boxes: list[CanvasBox] | None = None) -> None:
        self._image = image
        self._boxes = list(boxes or [])
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(QPixmap.fromImage(image))
        self._pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.setSceneRect(QRectF(0, 0, image.width(), image.height()))
        self._rebuild_boxes()
        self._auto_fit = True
        self.fit_to_window()

    def set_boxes(self, boxes: list[CanvasBox]) -> None:
        self._boxes = list(boxes)
        self._rebuild_boxes()

    def set_show_boxes(self, visible: bool) -> None:
        self._show_boxes = bool(visible)
        for item in self._box_items:
            item.setVisible(self._show_boxes)

    def has_boxes(self) -> bool:
        return bool(self._boxes)

    def _rebuild_boxes(self) -> None:
        self._box_items = []
        if self._image is None:
            return
        width, height = self._image.width(), self._image.height()
        for index, spec in enumerate(self._boxes):
            left, top, right, bottom = spec.box
            rect = QRectF(
                max(0.0, min(1.0, left)) * width,
                max(0.0, min(1.0, top)) * height,
                max(0.0, min(1.0, right) - max(0.0, min(1.0, left))) * width,
                max(0.0, min(1.0, bottom) - max(0.0, min(1.0, top))) * height,
            )
            color = HIGHLIGHT_COLOR if spec.highlighted else MUTED_COLOR
            pen = QPen(color, 4)
            pen.setCosmetic(False)
            item = self._scene.addRect(rect, pen)
            item.setVisible(self._show_boxes)
            self._box_items.append(item)
            label = spec.label or str(index + 1)
            text = self._scene.addSimpleText(str(label), QFont("Helvetica", 12))
            text.setBrush(color)
            text.setPos(rect.left() + 4, max(0.0, rect.top() - 24))
            text.setVisible(self._show_boxes)
            self._box_items.append(text)

    def fit_to_window(self) -> None:
        if self._pixmap_item is None:
            return
        self._auto_fit = True
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def actual_size(self) -> None:
        if self._pixmap_item is None:
            return
        self._auto_fit = False
        self.resetTransform()

    def zoom_in(self) -> None:
        self._zoom(1.25)

    def zoom_out(self) -> None:
        self._zoom(0.8)

    def _zoom(self, factor: float) -> None:
        if self._pixmap_item is None:
            return
        self._auto_fit = False
        self.scale(factor, factor)

    def wheelEvent(self, event) -> None:
        if self._pixmap_item is None:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        self._zoom(1.15 if delta > 0 else 1 / 1.15)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if self._pixmap_item is None:
            super().mouseDoubleClickEvent(event)
            return
        if self._auto_fit:
            self.actual_size()
        else:
            self.fit_to_window()
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._auto_fit and self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def render_image(self, *, include_boxes: bool = False) -> QImage | None:
        if self._image is None:
            return None
        image = self._image.copy()
        if not include_boxes or not self._boxes:
            return image
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = image.width(), image.height()
        line_width = max(2, max(width, height) // 500)
        for index, spec in enumerate(self._boxes):
            left, top, right, bottom = spec.box
            rect = QRectF(
                max(0.0, min(1.0, left)) * width,
                max(0.0, min(1.0, top)) * height,
                max(0.0, min(1.0, right) - max(0.0, min(1.0, left))) * width,
                max(0.0, min(1.0, bottom) - max(0.0, min(1.0, top))) * height,
            )
            color = HIGHLIGHT_COLOR if spec.highlighted else MUTED_COLOR
            painter.setPen(QPen(color, line_width))
            painter.drawRect(rect)
            label = spec.label or str(index + 1)
            painter.setFont(QFont("Helvetica", max(10, height // 60)))
            painter.drawText(
                QRectF(rect.left() + 4, max(0, rect.top() - height // 25),
                       max(60, width // 8), height // 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                str(label),
            )
        painter.end()
        return image

    def clear(self) -> None:
        self._image = None
        self._boxes = []
        self._box_items = []
        self._pixmap_item = None
        self._scene.clear()
