from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QThread, QTimer, Qt
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

from ..cloud_backup import build_upload_plan
from .cloud_workers import ExportWorker, UploadWorker
from .cos_config_store import config_summary, load_cos_config, resolve_credentials


class CloudBackupDialog(QDialog):
    def __init__(
        self,
        archive_root: Path,
        output_root: Path,
        settings: QSettings,
        *,
        auto_generate: bool = False,
        auto_upload: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.archive_root = archive_root
        self.output_root = output_root
        self.settings = settings
        self._auto_generate = auto_generate
        self._auto_upload = auto_upload
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

        form_group = QGroupBox("导出与云端配置")
        form = QFormLayout(form_group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.export_dir = QLineEdit()
        self.export_dir.setPlaceholderText("导出目录，例如：鸟-cloud-export")
        export_row = QHBoxLayout()
        export_row.addWidget(self.export_dir, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse_export)
        export_row.addWidget(browse)
        form.addRow("导出目录", export_row)
        self.config_label = QLabel()
        self.config_label.setWordWrap(True)
        form.addRow("COS 配置", self.config_label)
        config_row = QHBoxLayout()
        self.config_button = QPushButton("打开配置…")
        self.config_button.clicked.connect(self._open_config)
        config_row.addWidget(self.config_button)
        config_row.addStretch(1)
        form.addRow("", config_row)
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
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self.generate_export)
        if self._auto_generate:
            self._auto_timer.start(50)

    def _restore(self) -> None:
        self.export_dir.setText(str(self.settings.value("cloud_export_dir", "")))
        self.config_label.setText(config_summary(self._cos_config()))

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

    def _cos_config(self):
        return load_cos_config(self.settings)

    def _save(self) -> None:
        self.settings.setValue("cloud_export_dir", self.export_dir.text().strip())
        self.settings.sync()

    def _open_config(self) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "open_config"):
            parent.open_config()
            self.config_label.setText(config_summary(self._cos_config()))

    def _set_busy(self, busy: bool, *, cancellable: bool = False) -> None:
        self.export_button.setEnabled(not busy)
        self.upload_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy and cancellable)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)

    def _worker_blocked(self) -> bool:
        if self._worker is None:
            return False
        if not self._worker.isRunning():
            self._worker = None
            self._set_busy(False)
            return False
        self._append("后台任务仍在运行，请稍候…")
        return True

    def generate_export(self) -> None:
        if self._worker_blocked():
            return
        export = self.export_dir.text().strip()
        if not export:
            QMessageBox.warning(self, "羽栖 BirdRoost", "请填写导出目录")
            return
        self._save()
        worker = ExportWorker(self.archive_root, Path(export).expanduser(), self)
        self._worker = worker
        self._set_busy(True)
        worker.done.connect(self._export_done)
        worker.failed.connect(self._export_failed)
        worker.finished.connect(lambda worker=worker: self._worker_finished(worker))
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
        if self._auto_upload:
            self._auto_upload = False
            secret_id, secret_key = resolve_credentials(self._cos_config())
            if secret_id and secret_key and not report.errors:
                QTimer.singleShot(0, self.start_upload)
            else:
                self._append("导出已生成；尚未配置 COS，请点“打开配置…”填写桶名和 Secret")
        self._worker = None
        self._set_busy(False)

    def _export_failed(self, message: str) -> None:
        self._append(f"导出失败：{message}")
        QMessageBox.warning(self, "羽栖 BirdRoost", f"导出失败：{message}")
        self._worker = None
        self._set_busy(False)

    def start_upload(self) -> None:
        if self._worker_blocked():
            return
        export = Path(self.export_dir.text().strip()).expanduser()
        config = self._cos_config()
        bucket = config.bucket.strip()
        region = config.region.strip()
        prefix = config.prefix.strip()
        secret_id, secret_key = resolve_credentials(config)
        if not bucket or not region:
            QMessageBox.warning(self, "羽栖 BirdRoost", "请先在“配置…”中填写桶名和地域")
            return
        if not secret_id or not secret_key:
            QMessageBox.warning(self, "羽栖 BirdRoost", "请先在“配置…”中填写 SecretId / SecretKey，或设置环境变量")
            return
        plan = build_upload_plan(
            export, bucket=bucket, region=region, prefix=prefix,
            endpoint=config.endpoint.strip(),
        )
        if plan.errors:
            QMessageBox.warning(self, "羽栖 BirdRoost", "\n".join(plan.errors[:10]))
            return
        self._save()
        self._append(
            f"准备上传 {len(plan.items)} 个对象到 {bucket} / users/{plan.prefix}/"
        )
        worker = UploadWorker(plan, secret_id, secret_key, self)
        self._worker = worker
        self._set_busy(True, cancellable=True)
        worker.progressed.connect(self._progress)
        worker.done.connect(self._upload_done)
        worker.failed.connect(self._upload_failed)
        worker.finished.connect(lambda worker=worker: self._worker_finished(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _progress(self, done: int, total: int, key: str) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total}")

    def _upload_done(self, report) -> None:
        if report.cancelled:
            self._append(
                f"上传已取消：已上传 {report.uploaded}，跳过 {report.skipped}，失败 {report.failed}"
            )
            self._append("已上传对象会保留；下次点“开始上传”会自动跳过并继续")
        else:
            self._append(
                f"上传完成：上传 {report.uploaded}，跳过 {report.skipped}，失败 {report.failed}"
            )
        for error in report.errors[:20]:
            self._append(f"  {error}")
        if report.failed:
            QMessageBox.warning(self, "羽栖 BirdRoost", "部分对象上传失败，详见日志")
        self._worker = None
        self._set_busy(False)

    def _upload_failed(self, message: str) -> None:
        self._append(f"上传失败：{message}")
        QMessageBox.warning(self, "羽栖 BirdRoost", f"上传失败：{message}")
        self._worker = None
        self._set_busy(False)

    def _worker_finished(self, worker) -> None:
        if self._worker is worker:
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
