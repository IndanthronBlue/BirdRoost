from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QThread
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

from .cloud_workers import ConnectionWorker
from .cos_config_store import (
    CosConfig,
    load_cos_config,
    resolve_credentials,
    save_cos_config,
)

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
            "SecretId/SecretKey 可选保存到 macOS 钥匙串，不写入 QSettings 或日志。\n"
            '<a href="https://console.cloud.tencent.com/cam/capi">获取 SecretId / SecretKey</a>'
            ' · <a href="https://console.cloud.tencent.com/cam">访问管理 CAM</a>'
            ' · <a href="https://console.cloud.tencent.com/cos/bucket">COS 桶列表</a>'
        )
        note.setTextFormat(Qt.TextFormat.RichText)
        note.setOpenExternalLinks(True)
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
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

    def _config(self) -> CosConfig:
        return CosConfig(
            bucket=self.bucket.text().strip(),
            region=self.region.currentText().strip(),
            endpoint=self.endpoint.text().strip(),
            prefix=self.prefix.text().strip(),
            secret_id=self.secret_id.text().strip(),
            secret_key=self.secret_key.text().strip(),
            save_config=self.save_config.isChecked(),
        )

    def _restore_cos(self) -> None:
        config = load_cos_config(self.settings)
        self.bucket.setText(config.bucket)
        self.region.setCurrentText(config.region)
        self.endpoint.setText(config.endpoint)
        self.prefix.setText(config.prefix)
        self.save_config.blockSignals(True)
        self.save_config.setChecked(config.save_config)
        self.save_config.blockSignals(False)
        if config.secret_id and config.secret_key:
            self.secret_id.setText(config.secret_id)
            self.secret_key.setText(config.secret_key)
            self.status.setText("已从 macOS 钥匙串读取 COS 配置")
        elif config.save_config:
            self.status.setText("未在钥匙串中找到 COS 配置")

    def _save_cos(self) -> None:
        ok, message = save_cos_config(self.settings, self._config())
        self.status.setText(message if ok else message)

    def _on_save_toggled(self, checked: bool) -> None:
        self._save_cos()

    def _test_connection(self) -> None:
        if self._worker is not None:
            return
        secret_id, secret_key = resolve_credentials(self._config())
        if not self.bucket.text().strip() or not self.region.currentText().strip():
            QMessageBox.warning(self, "羽栖 BirdRoost", "请填写桶名和地域")
            return
        if not secret_id or not secret_key:
            QMessageBox.warning(self, "羽栖 BirdRoost", "请填写 SecretId / SecretKey，或设置环境变量")
            return
        self._save_cos()
        config = self._config()
        worker = ConnectionWorker({
            "bucket": config.bucket,
            "region": config.region,
            "secret_id": secret_id,
            "secret_key": secret_key,
            "prefix": config.prefix,
            "endpoint": config.endpoint,
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
