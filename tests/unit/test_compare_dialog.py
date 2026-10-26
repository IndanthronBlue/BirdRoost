from pathlib import Path

from PIL import Image

from birdclass.archive_index import ArchiveEntry
from birdclass.ui.compare_dialog import CompareDialog


def test_compare_dialog_has_two_independent_canvases(qtbot, tmp_path: Path):
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    Image.new("RGB", (40, 30), "green").save(first)
    Image.new("RGB", (40, 30), "blue").save(second)
    entries = [
        ArchiveEntry("三趾滨鹬/a.jpg", first, "三趾滨鹬", "三趾滨鹬", "Calidris alba"),
        ArchiveEntry("欧乌鸫/b.jpg", second, "欧乌鸫", "欧乌鸫", "Turdus merula"),
    ]
    dialog = CompareDialog(entries)
    qtbot.addWidget(dialog)
    dialog.show()

    assert len(dialog.canvases) == 2
    assert all(canvas.image is not None for canvas in dialog.canvases)
    assert all(not canvas.has_boxes() for canvas in dialog.canvases)
    assert all(not canvas.show_boxes for canvas in dialog.canvases)
    before = dialog.canvases[1].transform().m11()
    dialog.canvases[0].zoom_in()
    assert dialog.canvases[0].transform().m11() != 1.0
    assert dialog.canvases[1].transform().m11() == before
