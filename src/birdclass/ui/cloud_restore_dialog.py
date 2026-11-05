from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..cloud_restore import download_manifest, restore_from_cos
from .cos_config_store import config_summary, load_cos_config, resolve_credentials


class _RestoreWorker(QThread):
    progressed = Signal(int, int, str)
    done = Signal(object, str)
    failed = Signal(str)

    def __init__(self, local_root: Path, config, parent=None) -> None:
        super().__init__(parent)
        self.local_root = local_root
        self.config = config
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            secret_id, secret_key = resolve_credentials(self.config)
            with tempfile.TemporaryDirectory(prefix="birdroost-restore-") as directory:
                manifest_path = Path(directory) / "manifest.json"
                manifest = download_manifest(
                    bucket=self.config.bucket,
                    region=self.config.region,
                    endpoint=self.config.endpoint,
                    secret_id=secret_id,
                    secret_key=secret_key,
                    prefix=self.config.prefix,
                    destination=manifest_path,
                )
                report = restore_from_cos(
                    self.local_root,
                    manifest,
                    bucket=self.config.bucket,
                    region=self.config.region,
                    endpoint=self.config.endpoint,
                    secret_id=secret_id,
                    secret_key=secret_key,
                    prefix=self.config.prefix,
                    progress=lambda done, total, label: self.progressed.emit(done, total, label),
                    cancelled=self.cancel_event.is_set,
                )
            self.done.emit(report, str(self.local_root))
        except Exception as exc:
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")

    def cancel(self) -> None:
        self.cancel_event.set()


class CloudRestoreDialog(QDialog):
    restored = Signal(str)

    def __init__(self, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._worker: _RestoreWorker | None = None
        self.setWindowTitle("羽栖 BirdRoost · 云端恢复")
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        info = QLabel(
            "从 COS 下载 manifest 和全部原图，重建本地 `.birdroost` 图库。\n"
            "这适合新电脑首次使用；缩略图会由本地浏览时按需生成。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        box = QGroupBox("恢复目标")
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.local_root = QLineEdit()
        self.local_root.setPlaceholderText("本地新图库目录")
        row = QHBoxLayout()
        row.addWidget(self.local_root, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        form.addRow("恢复到目录", row)
        self.config_label = QLabel(config_summary(load_cos_config(settings)))
        self.config_label.setWordWrap(True)
        form.addRow("COS 配置", self.config_label)
        config_button = QPushButton("打开配置…")
        config_button.clicked.connect(self._open_config)
        form.addRow("", config_button)
        layout.addWidget(box)

        actions = QHBoxLayout()
        self.start_button = QPushButton("开始恢复")
        self.start_button.clicked.connect(self.start_restore)
        actions.addWidget(self.start_button)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)
        self._restore_root()

    def _restore_root(self) -> None:
        saved = str(self.settings.value("cloud_restore_dir", ""))
        if saved:
            self.local_root.setText(saved)
        else:
            self.local_root.setText(str(Path.home() / "Pictures" / "BirdRoost"))

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择本地图库目录", self.local_root.text())
        if selected:
            self.local_root.setText(selected)

    def _open_config(self) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "open_config"):
            parent.open_config()
        self.config_label.setText(config_summary(load_cos_config(self.settings)))

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)

    def start_restore(self) -> None:
        if self._worker is not None:
            return
        root = Path(self.local_root.text().strip()).expanduser()
        if not self.local_root.text().strip():
            QMessageBox.warning(self, "羽栖 BirdRoost", "请选择恢复目标目录")
            return
        config = load_cos_config(self.settings)
        secret_id, secret_key = resolve_credentials(config)
        if not config.bucket or not config.region or not secret_id or not secret_key:
            QMessageBox.warning(self, "羽栖 BirdRoost", "请先在“配置…”中完成 COS 配置")
            return
        if root.exists() and any(root.iterdir()):
            answer = QMessageBox.question(
                self, "恢复目录非空", "目标目录非空，继续会合并/覆盖同名文件，是否继续？"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.settings.setValue("cloud_restore_dir", str(root))
        self.settings.sync()
        self._append(f"开始从 {config.bucket} / users/{config.prefix}/ 恢复…")
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setVisible(True)
        worker = _RestoreWorker(root, config, self)
        self._worker = worker
        worker.progressed.connect(self._progress)
        worker.done.connect(self._done)
        worker.failed.connect(self._failed)
        worker.finished.connect(lambda worker=worker: self._finished(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _progress(self, done: int, total: int, label: str) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total}")

    def _done(self, report, root: str) -> None:
        if report.cancelled:
            self._append(f"恢复已取消：已恢复 {report.restored}，跳过 {report.skipped}")
        else:
            self._append(
                f"恢复完成：{report.groups} 个 group / {report.copies} 个副本 / "
                f"{report.restored} 张原图"
            )
        for error in report.errors[:20]:
            self._append(f"  {error}")
        if report.failed:
            QMessageBox.warning(self, "羽栖 BirdRoost", "部分图片恢复失败，详见日志")
        self.restored.emit(root)

    def _failed(self, message: str) -> None:
        self._append(f"恢复失败：{message}")
        QMessageBox.warning(self, "羽栖 BirdRoost", f"恢复失败：{message}")

    def _finished(self, worker) -> None:
        if self._worker is worker:
            self._worker = None
            self.start_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.progress.setVisible(False)

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self._append("正在取消恢复…")

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            self._worker.cancel()
            QMessageBox.information(self, "羽栖 BirdRoost", "请等待恢复任务结束")
            event.ignore()
            return
        event.accept()
