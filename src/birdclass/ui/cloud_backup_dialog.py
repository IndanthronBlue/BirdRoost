from __future__ import annotations

import getpass
import os
import threading
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
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

from ..cloud_backup import build_upload_plan, normalize_prefix, upload_plan
from ..cloud_export import export_archive


class _ExportWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, archive_root: Path, export_root: Path, parent=None) -> None:
        super().__init__(parent)
        self.archive_root = archive_root
        self.export_root = export_root

    def run(self) -> None:
        try:
            self.done.emit(export_archive(self.archive_root, self.export_root))
        except Exception as exc:
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")


class _UploadWorker(QThread):
    progressed = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, plan, secret_id: str, secret_key: str, parent=None) -> None:
        super().__init__(parent)
        self.plan = plan
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            report = upload_plan(
                self.plan,
                secret_id=self.secret_id,
                secret_key=self.secret_key,
                progress=lambda done, total, key: self.progressed.emit(done, total, key),
                cancelled=self.cancel_event.is_set,
            )
            self.done.emit(report)
        except Exception as exc:
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")

    def cancel(self) -> None:
        self.cancel_event.set()


class CloudBackupDialog(QDialog):
    def __init__(self, archive_root: Path, output_root: Path, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.archive_root = archive_root
        self.output_root = output_root
        self.settings = settings
        self._worker: QThread | None = None
        self.setWindowTitle("羽栖 BirdRoost · 云备份")
        self.resize(720, 620)
        layout = QVBoxLayout(self)
        info = QLabel(
            "先生成导出清单和缩略图，再上传到腾讯云 COS。\n"
            "COS 桶必须为私有桶；SecretKey 不会保存到设置或日志。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form_group = QGroupBox("腾讯云 COS")
        form = QFormLayout(form_group)
        self.export_dir = QLineEdit()
        self.export_dir.setPlaceholderText("导出目录，例如：鸟-cloud-export")
        export_row = QHBoxLayout()
        export_row.addWidget(self.export_dir, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse_export)
        export_row.addWidget(browse)
        form.addRow("导出目录", export_row)
        self.bucket = QLineEdit()
        self.bucket.setPlaceholderText("例如：birdroost-1250000000（含 APPID）")
        form.addRow("桶名（含 APPID）", self.bucket)
        self.region = QComboBox()
        self.region.setEditable(True)
        for region in ("ap-shanghai", "ap-guangzhou", "ap-beijing", "ap-hongkong", "ap-singapore"):
            self.region.addItem(region)
        form.addRow("地域", self.region)
        self.prefix = QLineEdit()
        self.prefix.setPlaceholderText("用户前缀，例如：zjq")
        form.addRow("用户前缀", self.prefix)
        self.endpoint = QLineEdit()
        self.endpoint.setPlaceholderText("可选：cos.ap-shanghai.myqcloud.com")
        form.addRow("Endpoint（可选）", self.endpoint)
        self.secret_id = QLineEdit()
        self.secret_id.setPlaceholderText("留空则读 TENCENTCLOUD_SECRET_ID")
        form.addRow("SecretId", self.secret_id)
        self.secret_key = QLineEdit()
        self.secret_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret_key.setPlaceholderText("留空则读 TENCENTCLOUD_SECRET_KEY")
        form.addRow("SecretKey", self.secret_key)
        layout.addWidget(form_group)

        buttons = QHBoxLayout()
        self.export_button = QPushButton("生成清单和缩略图")
        self.export_button.clicked.connect(self.generate_export)
        buttons.addWidget(self.export_button)
        self.upload_button = QPushButton("开始上传")
        self.upload_button.clicked.connect(self.start_upload)
        buttons.addWidget(self.upload_button)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("云备份日志（不输出 SecretKey）")
        layout.addWidget(self.log, 1)

        self._restore()
        self._refresh_export_default()

    def _restore(self) -> None:
        self.export_dir.setText(str(self.settings.value("cloud_export_dir", "")))
        self.bucket.setText(str(self.settings.value("cloud_bucket", "")))
        region = str(self.settings.value("cloud_region", "ap-shanghai"))
        self.region.setCurrentText(region)
        self.prefix.setText(str(self.settings.value("cloud_prefix", normalize_prefix(getpass.getuser()))))
        self.endpoint.setText(str(self.settings.value("cloud_endpoint", "")))

    def _refresh_export_default(self) -> None:
        if self.export_dir.text().strip():
            return
        if not str(self.output_root).strip():
            return
        root = Path(self.output_root).expanduser()
        self.export_dir.setText(str(root.parent / f"{root.name}-cloud-export"))

    def _browse_export(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择导出目录", self.export_dir.text())
        if selected:
            self.export_dir.setText(selected)

    def _save(self) -> None:
        self.settings.setValue("cloud_export_dir", self.export_dir.text().strip())
        self.settings.setValue("cloud_bucket", self.bucket.text().strip())
        self.settings.setValue("cloud_region", self.region.currentText().strip())
        self.settings.setValue("cloud_prefix", self.prefix.text().strip())
        self.settings.setValue("cloud_endpoint", self.endpoint.text().strip())
        self.settings.sync()

    def _set_busy(self, busy: bool, *, cancellable: bool = False) -> None:
        self.export_button.setEnabled(not busy)
        self.upload_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy and cancellable)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)

    def generate_export(self) -> None:
        if self._worker is not None:
            return
        export = self.export_dir.text().strip()
        if not export:
            QMessageBox.warning(self, "羽栖 BirdRoost", "请填写导出目录")
            return
        self._save()
        worker = _ExportWorker(self.archive_root, Path(export).expanduser(), self)
        self._worker = worker
        self._set_busy(True)
        worker.done.connect(self._export_done)
        worker.failed.connect(self._export_failed)
        worker.finished.connect(self._worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _export_done(self, report) -> None:
        self._append(
            f"导出完成：{report.photos} 张原图 / {report.copies} 个副本 / {report.thumbnails} 张缩略图"
        )
        if report.errors:
            self._append(f"导出有 {len(report.errors)} 个错误")
            for error in report.errors[:20]:
                self._append(f"  {error}")

    def _export_failed(self, message: str) -> None:
        self._append(f"导出失败：{message}")
        QMessageBox.warning(self, "羽栖 BirdRoost", f"导出失败：{message}")

    def start_upload(self) -> None:
        if self._worker is not None:
            return
        export = Path(self.export_dir.text().strip()).expanduser()
        bucket = self.bucket.text().strip()
        region = self.region.currentText().strip()
        prefix = self.prefix.text().strip()
        secret_id = self.secret_id.text().strip() or os.environ.get("TENCENTCLOUD_SECRET_ID", "") or os.environ.get("COS_SECRET_ID", "")
        secret_key = self.secret_key.text().strip() or os.environ.get("TENCENTCLOUD_SECRET_KEY", "") or os.environ.get("COS_SECRET_KEY", "")
        if not bucket or not region:
            QMessageBox.warning(self, "羽栖 BirdRoost", "请填写桶名和地域")
            return
        if not secret_id or not secret_key:
            QMessageBox.warning(self, "羽栖 BirdRoost", "请填写 SecretId / SecretKey，或设置环境变量")
            return
        plan = build_upload_plan(
            export, bucket=bucket, region=region, prefix=prefix,
            endpoint=self.endpoint.text().strip(),
        )
        if plan.errors:
            QMessageBox.warning(self, "羽栖 BirdRoost", "\n".join(plan.errors[:10]))
            return
        self._save()
        self._append(
            f"准备上传 {len(plan.items)} 个对象到 {bucket} / users/{plan.prefix}/"
        )
        worker = _UploadWorker(plan, secret_id, secret_key, self)
        self._worker = worker
        self._set_busy(True, cancellable=True)
        worker.progressed.connect(self._progress)
        worker.done.connect(self._upload_done)
        worker.failed.connect(self._upload_failed)
        worker.finished.connect(self._worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _progress(self, done: int, total: int, key: str) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total}")

    def _upload_done(self, report) -> None:
        self._append(
            f"上传完成：上传 {report.uploaded}，跳过 {report.skipped}，失败 {report.failed}"
        )
        for error in report.errors[:20]:
            self._append(f"  {error}")
        if report.failed:
            QMessageBox.warning(self, "羽栖 BirdRoost", "部分对象上传失败，详见日志")

    def _upload_failed(self, message: str) -> None:
        self._append(f"上传失败：{message}")
        QMessageBox.warning(self, "羽栖 BirdRoost", f"上传失败：{message}")

    def _worker_finished(self) -> None:
        self._worker = None
        self._set_busy(False)

    def cancel(self) -> None:
        if isinstance(self._worker, _UploadWorker):
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self._append("正在取消上传…")

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            if isinstance(self._worker, _UploadWorker):
                self._worker.cancel()
            QMessageBox.information(self, "羽栖 BirdRoost", "请等待当前任务结束")
            event.ignore()
            return
        self._save()
        event.accept()
