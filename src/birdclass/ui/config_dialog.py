from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..cloud_backup import normalize_prefix, test_connection
from ..secret_store import (
    delete_cos_credentials,
    last_error,
    load_cos_credentials,
    save_cos_credentials,
)
from .geo_fields import COUNTRIES, configure_geo_combo


class _ConnectionWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, kwargs, parent=None) -> None:
        super().__init__(parent)
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            self.done.emit(test_connection(**self.kwargs))
        except Exception as exc:
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")


class ConfigDialog(QDialog):
    """Unified API key + COS configuration."""

    def __init__(self, api_group: QWidget, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("羽栖 BirdRoost · 配置")
        self.resize(720, 560)
        self.settings = settings
        self._worker: QThread | None = None

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(api_group, "懂鸟 API Key")
        tabs.addTab(self._build_cos_page(), "云图库 COS")
        layout.addWidget(tabs, 1)
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        layout.addWidget(close)

    def _build_cos_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "这些配置用于云备份和云端图库。\n"
            "SecretId/SecretKey 可选保存到 macOS 钥匙串，不写入 QSettings 或日志。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.export_dir = QLineEdit()
        self.export_dir.setPlaceholderText("导出目录（可留空，上传时再选择）")
        form.addRow("导出目录", self.export_dir)
        self.bucket = QLineEdit()
        self.bucket.setPlaceholderText("例如：birdroost-1250000000（含 APPID）")
        form.addRow("桶名（含 APPID）", self.bucket)
        self.region = QComboBox()
        self.region.setEditable(True)
        for region in ("ap-shanghai", "ap-guangzhou", "ap-beijing", "ap-hongkong", "ap-singapore"):
            self.region.addItem(region)
        form.addRow("地域", self.region)
        self.endpoint = QLineEdit()
        self.endpoint.setPlaceholderText("可选：cos.ap-shanghai.myqcloud.com")
        form.addRow("Endpoint（可选）", self.endpoint)
        self.prefix = QLineEdit()
        self.prefix.setPlaceholderText("用户前缀，例如：zjq")
        form.addRow("用户前缀", self.prefix)
        self.secret_id = QLineEdit()
        self.secret_id.setPlaceholderText("留空则读环境变量")
        form.addRow("SecretId", self.secret_id)
        self.secret_key = QLineEdit()
        self.secret_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret_key.setPlaceholderText("留空则读环境变量")
        form.addRow("SecretKey", self.secret_key)
        self.save_config = QCheckBox("保存 COS 配置（Secret 存 macOS 钥匙串）")
        form.addRow("", self.save_config)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        form.addRow("", self.status)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(self._test_connection)
        row.addWidget(self.test_button)
        self.write_test = QCheckBox("包含写入测试")
        self.write_test.setChecked(True)
        row.addWidget(self.write_test)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self._restore_cos()
        self.save_config.toggled.connect(self._on_save_toggled)
        return page

    def _restore_cos(self) -> None:
        self.export_dir.setText(str(self.settings.value("cloud_export_dir", "")))
        self.bucket.setText(str(self.settings.value("cloud_bucket", "")))
        self.region.setCurrentText(str(self.settings.value("cloud_region", "ap-shanghai")))
        self.endpoint.setText(str(self.settings.value("cloud_endpoint", "")))
        self.prefix.setText(str(self.settings.value("cloud_prefix", normalize_prefix(os.environ.get("USER", "default")))))
        saved = self.settings.value("cloud_save_config", False)
        saved = saved if isinstance(saved, bool) else str(saved).lower() == "true"
        self.save_config.blockSignals(True)
        self.save_config.setChecked(saved)
        self.save_config.blockSignals(False)
        if saved:
            secret_id, secret_key = load_cos_credentials()
            if secret_id and secret_key:
                self.secret_id.setText(secret_id)
                self.secret_key.setText(secret_key)
                self.status.setText("已从 macOS 钥匙串读取 COS 配置")
            else:
                self.status.setText("未在钥匙串中找到 COS 配置")

    def _save_cos(self) -> None:
        save = self.save_config.isChecked()
        self.settings.setValue("cloud_save_config", save)
        if not save:
            for key in ("cloud_export_dir", "cloud_bucket", "cloud_region", "cloud_prefix", "cloud_endpoint"):
                self.settings.remove(key)
            delete_cos_credentials()
            self.settings.sync()
            return
        self.settings.setValue("cloud_export_dir", self.export_dir.text().strip())
        self.settings.setValue("cloud_bucket", self.bucket.text().strip())
        self.settings.setValue("cloud_region", self.region.currentText().strip())
        self.settings.setValue("cloud_endpoint", self.endpoint.text().strip())
        self.settings.setValue("cloud_prefix", self.prefix.text().strip())
        if self.secret_id.text().strip() and self.secret_key.text().strip():
            if save_cos_credentials(self.secret_id.text().strip(), self.secret_key.text().strip()):
                self.status.setText("COS 配置已保存到 macOS 钥匙串")
            else:
                self.status.setText(f"COS 配置保存失败：{last_error()}")
        self.settings.sync()

    def _on_save_toggled(self, checked: bool) -> None:
        if not checked:
            delete_cos_credentials()
            self.status.setText("已取消保存 COS 配置")
        else:
            self._save_cos()

    def _test_connection(self) -> None:
        if self._worker is not None:
            return
        secret_id = self.secret_id.text().strip() or os.environ.get("TENCENTCLOUD_SECRET_ID", "") or os.environ.get("COS_SECRET_ID", "")
        secret_key = self.secret_key.text().strip() or os.environ.get("TENCENTCLOUD_SECRET_KEY", "") or os.environ.get("COS_SECRET_KEY", "")
        if not self.bucket.text().strip() or not self.region.currentText().strip():
            QMessageBox.warning(self, "羽栖 BirdRoost", "请填写桶名和地域")
            return
        if not secret_id or not secret_key:
            QMessageBox.warning(self, "羽栖 BirdRoost", "请填写 SecretId / SecretKey，或设置环境变量")
            return
        self._save_cos()
        worker = _ConnectionWorker({
            "bucket": self.bucket.text().strip(),
            "region": self.region.currentText().strip(),
            "secret_id": secret_id,
            "secret_key": secret_key,
            "prefix": self.prefix.text().strip(),
            "endpoint": self.endpoint.text().strip(),
            "write_test": self.write_test.isChecked(),
        }, self)
        self._worker = worker
        self.test_button.setEnabled(False)
        worker.done.connect(self._test_done)
        worker.failed.connect(self._test_failed)
        worker.finished.connect(self._test_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _test_done(self, report) -> None:
        self.status.setText("；".join(report.messages + ([report.error] if report.error else [])))
        if report.ok:
            self.status.setText("连接测试通过：" + self.status.text())
        else:
            QMessageBox.warning(self, "羽栖 BirdRoost", report.error or "连接测试失败")

    def _test_failed(self, message: str) -> None:
        self.status.setText(f"连接测试失败：{message}")
        QMessageBox.warning(self, "羽栖 BirdRoost", message)

    def _test_finished(self) -> None:
        self._worker = None
        self.test_button.setEnabled(True)

    def closeEvent(self, event) -> None:
        if self.save_config is not None:
            self._save_cos()
        event.accept()
