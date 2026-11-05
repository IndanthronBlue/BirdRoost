from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .cloud_workers import PullWorker
from .cos_config_store import config_summary, load_cos_config, resolve_credentials


class CloudPullDialog(QDialog):
    pulled = Signal(str)

    def __init__(self, archive_root: Path, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.archive_root = archive_root
        self.settings = settings
        self._worker: PullWorker | None = None
        self._force_next = False
        self.setWindowTitle("羽栖 BirdRoost · 从云端同步")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        info = QLabel(
            "本地干净时，从云端 fast-forward 拉取：\n"
            "下载缺失原图、更新 group、应用远端删除。\n"
            "本地有未推送修改时不会覆盖，只显示冲突。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        config = load_cos_config(settings)
        self.config_label = QLabel(config_summary(config))
        self.config_label.setWordWrap(True)
        layout.addWidget(self.config_label)

        row = QHBoxLayout()
        self.pull_button = QPushButton("从云端同步")
        self.pull_button.clicked.connect(self.start_pull)
        row.addWidget(self.pull_button)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        self.auto_pull = QCheckBox("启动时自动拉取（仅本地干净）")
        self.auto_pull.setToolTip("只做 fast-forward；本地有修改时不会覆盖")
        self.auto_pull.setChecked(settings.value("cloud_auto_pull", False) in (True, "true"))
        self.auto_pull.toggled.connect(self._save_auto)
        row.addWidget(self.auto_pull)
        row.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)

    def _save_auto(self, checked: bool) -> None:
        self.settings.setValue("cloud_auto_pull", checked)
        self.settings.sync()

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)

    def start_pull(self) -> None:
        self._start(force=False)

    def _start(self, *, force: bool) -> None:
        if self._worker is not None:
            return
        config = load_cos_config(self.settings)
        secret_id, secret_key = resolve_credentials(config)
        if not config.bucket or not config.region or not secret_id or not secret_key:
            QMessageBox.warning(self, "羽栖 BirdRoost", "请先在“配置…”中完成 COS 配置")
            return
        self.pull_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setVisible(True)
        self._append("正在从云端拉取…" if not force else "正在用云端覆盖本地…")
        worker = PullWorker(
            self.archive_root,
            {
                "bucket": config.bucket,
                "region": config.region,
                "endpoint": config.endpoint,
                "secret_id": secret_id,
                "secret_key": secret_key,
                "prefix": config.prefix,
            },
            force=force,
            parent=self,
        )
        self._worker = worker
        worker.progressed.connect(self._progress)
        worker.done.connect(self._done)
        worker.failed.connect(self._failed)
        worker.finished.connect(lambda worker=worker: self._finished(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _progress(self, done: int, total: int, key: str) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total}")

    def _done(self, report) -> None:
        if report.action == "up_to_date":
            self._append(f"已经是最新：revision {report.local_revision}")
            self.pulled.emit(str(self.archive_root))
        elif report.action == "conflict":
            self._append("本地有未推送修改，未拉取云端内容。")
            snapshot = f"\n\n云端快照：{report.snapshot_path}" if report.snapshot_path else ""
            answer = QMessageBox.question(
                self, "本地与云端都有修改",
                "本地有未推送修改，云端也有新 revision。\n"
                f"本地 revision {report.local_revision}，云端 revision {report.remote_revision}。"
                f"{snapshot}\n\n是否用云端覆盖本地？本地 group 会先做快照，原图不会上传。",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._force_next = True
                self._append("已确认用云端覆盖本地，准备重试…")
        elif report.action == "pulled":
            self._append(
                f"拉取完成：revision {report.local_revision} → {report.remote_revision}，"
                f"下载 {report.downloaded}，跳过 {report.skipped}，"
                f"移除本地 group {report.removed_groups}，应用 tombstone {report.tombstones_applied}"
            )
            self.pulled.emit(str(self.archive_root))
        else:
            self._append("拉取失败")
        for error in report.errors[:20]:
            self._append(f"  {error}")
        self._set_idle()

    def _failed(self, message: str) -> None:
        self._append(f"拉取失败：{message}")
        QMessageBox.warning(self, "羽栖 BirdRoost", f"拉取失败：{message}")
        self._set_idle()

    def _set_idle(self) -> None:
        self._worker = None
        self.pull_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.setVisible(False)

    def _finished(self, worker) -> None:
        if self._worker is worker:
            self._worker = None
        if self._force_next:
            self._force_next = False
            self._start(force=True)

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self._append("正在取消拉取…")

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            self._worker.cancel()
            QMessageBox.information(self, "羽栖 BirdRoost", "请等待拉取任务结束")
            event.ignore()
            return
        event.accept()
