from pathlib import Path

from PIL import Image

from birdclass.archive_index import ArchiveEntry
from birdclass.ui.image_canvas import CanvasBox
from birdclass.ui.lightbox import LightboxDialog


def test_lightbox_box_toggle(qtbot, tmp_path: Path):
    image_path = tmp_path / "a.jpg"
    Image.new("RGB", (40, 30), "green").save(image_path)
    entry = ArchiveEntry("三趾滨鹬/a.jpg", image_path, "三趾滨鹬", "三趾滨鹬", "Calidris alba")
    dialog = LightboxDialog(
        [entry], 0,
        boxes_provider=lambda value: [CanvasBox((0.1, 0.1, 0.5, 0.5), "1", True)],
    )
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.canvas.show_boxes is True
    dialog.box_toggle.click()
    assert dialog.canvas.show_boxes is False
    dialog.next()
    assert dialog.canvas.show_boxes is False
    dialog.box_toggle.click()
    assert dialog.canvas.show_boxes is True
