from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class CloudConflictDialog(QDialog):
    """Inspect a remote conflict snapshot before explicitly overriding it."""

    def __init__(self, local_manifest: Path, snapshot: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("羽栖 BirdRoost · 云端冲突")
        self.resize(820, 560)
        self.snapshot = Path(snapshot) if snapshot else None
        layout = QVBoxLayout(self)
        note = QLabel(
            "云端和本地都产生了新 revision。\n"
            "当前不会自动合并；请检查差异后决定是否用本地 manifest 覆盖云端。\n"
            "覆盖前已保存云端快照，原图不会删除。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        layout.addWidget(self.summary, 1)
        buttons = QHBoxLayout()
        if self.snapshot is not None and self.snapshot.is_file():
            open_button = QPushButton("打开快照目录")
            open_button.clicked.connect(self._open_snapshot)
            buttons.addWidget(open_button)
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        override = QPushButton("保留本地并覆盖云端")
        override.clicked.connect(self.accept)
        buttons.addWidget(override)
        layout.addLayout(buttons)
        self._load(local_manifest)

    def _read(self, path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _load(self, local_manifest: Path) -> None:
        local = self._read(local_manifest)
        remote = self._read(self.snapshot) if self.snapshot and self.snapshot.is_file() else {}
        lines = [
            f"本地 revision：{local.get('revision', '?')}",
            f"云端 revision：{remote.get('revision', '?')}",
            f"本地 photos/groups/copies：{len(local.get('photos', []))}/"
            f"{len(local.get('groups', []))}/{len(local.get('copies', []))}",
            f"云端 photos/groups/copies：{len(remote.get('photos', []))}/"
            f"{len(remote.get('groups', []))}/{len(remote.get('copies', []))}",
        ]
        local_groups = {str(value.get("group_id", "")) for value in local.get("groups", [])}
        remote_groups = {str(value.get("group_id", "")) for value in remote.get("groups", [])}
        local_copies = {str(value.get("copy_id", "")) for value in local.get("copies", [])}
        remote_copies = {str(value.get("copy_id", "")) for value in remote.get("copies", [])}
        lines.extend([
            "",
            f"仅本地 group：{len(local_groups - remote_groups)}",
            f"仅云端 group：{len(remote_groups - local_groups)}",
            f"仅本地 copy：{len(local_copies - remote_copies)}",
            f"仅云端 copy：{len(remote_copies - local_copies)}",
            f"本地 tombstone：{len(local.get('tombstones', []))}",
            f"云端 tombstone：{len(remote.get('tombstones', []))}",
        ])
        if local_groups - remote_groups:
            lines.append("\n仅本地 group ID：")
            lines.extend(f"  {value}" for value in sorted(local_groups - remote_groups)[:30])
        if remote_groups - local_groups:
            lines.append("\n仅云端 group ID：")
            lines.extend(f"  {value}" for value in sorted(remote_groups - local_groups)[:30])
        if self.snapshot is not None:
            lines.extend(["", f"云端快照：{self.snapshot}"])
        self.summary.setPlainText("\n".join(lines))

    def _open_snapshot(self) -> None:
        if self.snapshot is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.snapshot.parent)))
