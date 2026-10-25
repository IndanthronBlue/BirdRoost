from pathlib import Path

import piexif
from PIL import Image
from PySide6.QtCore import QRectF

from birdclass.ui.image_canvas import CanvasBox, ZoomableImageCanvas


def test_canvas_loads_image_with_exif_orientation(qtbot, tmp_path: Path):
    path = tmp_path / "rotated.jpg"
    Image.new("RGB", (100, 80), "green").save(path)
    exif = piexif.dump({"0th": {piexif.ImageIFD.Orientation: 6}})
    piexif.insert(exif, str(path))
    canvas = ZoomableImageCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(400, 300)

    assert canvas.load_image(path) is True
    assert canvas.image is not None
    assert (canvas.image.width(), canvas.image.height()) == (80, 100)


def test_canvas_draws_and_toggles_normalized_boxes(qtbot):
    from PySide6.QtGui import QImage, QColor

    image = QImage(100, 80, QImage.Format.Format_RGB32)
    image.fill(QColor("green"))
    canvas = ZoomableImageCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(image, boxes=[
        CanvasBox((0.1, 0.1, 0.5, 0.5), "1", highlighted=True),
        CanvasBox((0.6, 0.2, 0.9, 0.8), "2"),
    ])

    assert len(canvas._box_items) == 4
    assert all(not item.isVisible() for item in canvas._box_items)

    canvas.set_show_boxes(True)
    assert all(item.isVisible() for item in canvas._box_items)
    rect = canvas._box_items[0].rect()
    assert rect == QRectF(10.0, 8.0, 40.0, 32.0)


def test_canvas_fit_actual_and_annotated_render(qtbot):
    from PySide6.QtGui import QColor, QImage

    image = QImage(100, 80, QImage.Format.Format_RGB32)
    image.fill(QColor("green"))
    canvas = ZoomableImageCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(image, boxes=[CanvasBox((0.1, 0.1, 0.5, 0.5), "1", True)])
    canvas.set_show_boxes(True)

    clean = canvas.render_image()
    annotated = canvas.render_image(include_boxes=True)
    assert clean is not None and annotated is not None
    assert clean.size() == annotated.size() == image.size()
    assert clean.pixelColor(10, 8).name() == "#008000"
    assert annotated.pixelColor(10, 8).name() == "#ffb020"

    canvas.actual_size()
    assert canvas.transform().m11() == 1.0
    canvas.fit_to_window()
    assert canvas.transform().m11() != 0
