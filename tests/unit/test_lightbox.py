from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt

from birdclass.archive_index import ArchiveEntry
from birdclass.ui.image_canvas import CanvasBox
from birdclass.ui.lightbox import LightboxDialog


def test_lightbox_navigation_and_boxes(qtbot, tmp_path: Path):
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    Image.new("RGB", (40, 30), "green").save(first)
    Image.new("RGB", (40, 30), "blue").save(second)
    entries = [
        ArchiveEntry("三趾滨鹬/a.jpg", first, "三趾滨鹬", "三趾滨鹬", "Calidris alba"),
        ArchiveEntry("欧乌鸫/b.jpg", second, "欧乌鸫", "欧乌鸫", "Turdus merula"),
    ]
    dialog = LightboxDialog(
        entries, 0,
        boxes_provider=lambda entry: [CanvasBox((0.1, 0.1, 0.5, 0.5), "1", True)],
    )
    qtbot.addWidget(dialog)
    dialog.show()

    assert "三趾滨鹬" in dialog.caption.text()
    assert dialog.canvas.has_boxes() is True
    qtbot.keyClick(dialog, Qt.Key.Key_Right)
    assert "欧乌鸫" in dialog.caption.text()
    qtbot.keyClick(dialog, Qt.Key.Key_Left)
    assert "三趾滨鹬" in dialog.caption.text()
