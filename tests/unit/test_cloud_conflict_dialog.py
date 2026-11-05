import json
from pathlib import Path

from birdclass.ui.cloud_conflict_dialog import CloudConflictDialog


def test_conflict_dialog_summarizes_remote_snapshot(qtbot, tmp_path: Path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    local.write_text(json.dumps({
        "revision": 2,
        "photos": [{"photo_id": "a"}],
        "groups": [{"group_id": "local-group"}],
        "copies": [{"copy_id": "local-copy"}],
        "tombstones": [],
    }), encoding="utf-8")
    remote.write_text(json.dumps({
        "revision": 5,
        "photos": [],
        "groups": [{"group_id": "remote-group"}],
        "copies": [{"copy_id": "remote-copy"}],
        "tombstones": [],
    }), encoding="utf-8")
    dialog = CloudConflictDialog(local, str(remote))
    qtbot.addWidget(dialog)

    text = dialog.summary.toPlainText()
    assert "本地 revision：2" in text
    assert "云端 revision：5" in text
    assert "仅云端 group：1" in text
    assert "remote-group" in text
