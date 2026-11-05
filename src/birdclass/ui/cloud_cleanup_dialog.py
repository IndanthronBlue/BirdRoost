from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .cloud_workers import CleanupWorker
from .cos_config_store import config_summary, load_cos_config, resolve_credentials


class CloudCleanupDialog(QDialog):
    def __init__(self, archive_root: Path, export_root: Path, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.archive_root = archive_root
        self.export_root = export_root
        self.settings = settings
        self._worker: CleanupWorker | None = None
        self._dry_report = None
        self.setWindowTitle("羽栖 BirdRoost · 清理云端 tombstone")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        info = QLabel(
            "只删除已写 tombstone、超过保留期、且不再被当前 manifest 引用的原图和缩略图。\n"
            "先扫描，确认后再删除；删除不可恢复。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        config = load_cos_config(settings)
        self.config_label = QLabel(config_summary(config))
        self.config_label.setWordWrap(True)
        layout.addWidget(self.config_label)

        row = QHBoxLayout()
        row.addWidget(QLabel("保留天数"))
        self.retention = QSpinBox()
        self.retention.setRange(0, 3650)
        self.retention.setValue(30)
        row.addWidget(self.retention)
        self.scan_button = QPushButton("扫描可清理对象")
        self.scan_button.clicked.connect(self.scan)
        row.addWidget(self.scan_button)
        self.delete_button = QPushButton("删除…")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.delete)
        row.addWidget(self.delete_button)
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

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)

    def _config(self):
        config = load_cos_config(self.settings)
        return config, *resolve_credentials(config)

    def _start(self, *, dry_run: bool) -> None:
        if self._worker is not None:
            return
        config, secret_id, secret_key = self._config()
        if not config.bucket or not config.region or not secret_id or not secret_key:
            QMessageBox.warning(self, "羽栖 BirdRoost", "请先在“配置…”中完成 COS 配置")
            return
        worker = CleanupWorker(
            self.archive_root,
            self.export_root,
            {
                "bucket": config.bucket,
                "region": config.region,
                "endpoint": config.endpoint,
                "secret_id": secret_id,
                "secret_key": secret_key,
                "prefix": config.prefix,
                "retention_days": self.retention.value(),
            },
            dry_run=dry_run,
            parent=self,
        )
        self._worker = worker
        self.scan_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.progress.setVisible(True)
        self._append("正在扫描云端 tombstone…" if dry_run else "正在删除云端对象…")
        worker.done.connect(self._done)
        worker.failed.connect(self._failed)
        worker.finished.connect(lambda worker=worker: self._finished(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def scan(self) -> None:
        self._start(dry_run=True)

    def delete(self) -> None:
        if self._dry_report is None or not self._dry_report.existing:
            return
        size = sum(int(item.get("bytes", 0)) for item in self._dry_report.objects)
        answer = QMessageBox.question(
            self, "确认删除云端对象",
            f"将永久删除 {self._dry_report.existing} 个对象，"
            f"约 {size / 1024 / 1024:.1f} MB。\n"
            "删除后不可恢复，是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start(dry_run=False)

    def _done(self, report) -> None:
        if report.dry_run:
            self._dry_report = report
            self._append(
                f"扫描完成：tombstone {report.tombstones}，候选对象 {report.candidates}，"
                f"存在 {report.existing}，缺失 {report.missing}，"
                f"跳过引用中 {report.skipped_referenced}，未到保留期 {report.skipped_young}，"
                f"缺少对象键 {report.skipped_no_key}"
            )
            for item in report.objects[:50]:
                self._append(f"  {item['key']}  {item['bytes'] / 1024 / 1024:.2f} MB")
            if report.existing:
                self.delete_button.setEnabled(True)
                self.delete_button.setText(f"删除 {report.existing} 个对象…")
        else:
            self._append(
                f"删除完成：{report.deleted} 个对象，约 {report.bytes_deleted / 1024 / 1024:.1f} MB"
            )
            self.delete_button.setEnabled(False)
        for error in report.errors[:20]:
            self._append(f"  {error}")

    def _failed(self, message: str) -> None:
        self._append(f"清理失败：{message}")
        QMessageBox.warning(self, "羽栖 BirdRoost", f"清理失败：{message}")

    def _finished(self, worker) -> None:
        if self._worker is worker:
            self._worker = None
            self.scan_button.setEnabled(True)
            self.progress.setVisible(False)

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            QMessageBox.information(self, "羽栖 BirdRoost", "请等待清理任务结束")
            event.ignore()
            return
        event.accept()
