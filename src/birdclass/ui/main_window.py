from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)

from ..models import AppConfig, BatchSummary, Quota, ReviewResult
from ..resource_loader import load_areas
from .area_search import configure_area_search, resolve_area_code
from .review_dialog import ReviewDialog
from .workers import ClassificationWorker, QuotaWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("羽栖 BirdRoost · 鸟图整理")
        self.resize(860, 760)
        self._settings = QSettings("BirdClass", "BirdClass")
        self._worker: ClassificationWorker | None = None
        self._quota_worker: QuotaWorker | None = None
        self._closing = False
        self._build_ui()
        self._restore_settings()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QGridLayout(central)

        api_group = QGroupBox("懂鸟 API")
        api_form = QFormLayout(api_group)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("请输入 API Key（不会保存到磁盘）")
        self.api_key.setClearButtonEnabled(True)
        api_form.addRow("API Key", self.api_key)
        quota_row = QHBoxLayout()
        self.query_quota_button = QPushButton("查询剩余次数")
        self.query_quota_button.clicked.connect(self.query_quota)
        self.quota_label = QLabel("尚未查询")
        self.quota_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        quota_row.addWidget(self.query_quota_button)
        quota_row.addWidget(self.quota_label, 1)
        api_form.addRow("图像额度", quota_row)
        root.addWidget(api_group, 0, 0)

        filter_group = QGroupBox("识别范围、观测信息与人工复核")
        filter_form = QFormLayout(filter_group)
        self.animal_class = QComboBox()
        for code, label in (("B", "鸟类"), ("M", "哺乳类"), ("A", "两栖类"), ("R", "爬行类")):
            self.animal_class.addItem(f"{label} [{code}]", code)
        filter_form.addRow("识别种类", self.animal_class)
        self.area = QComboBox()
        for code, label in load_areas():
            self.area.addItem(label, code)
        configure_area_search(self.area)
        self.area.setCurrentIndex(0)
        filter_form.addRow("国家 / 地区", self.area)
        self.observation_location = QLineEdit()
        self.observation_location.setPlaceholderText("例如：云南大理")
        self.observation_time = QLineEdit()
        self.observation_time.setPlaceholderText("例如：2026-10-24 1430")
        filter_form.addRow("观测地点", self.observation_location)
        filter_form.addRow("观测时间", self.observation_time)
        self.low_threshold = self._threshold(80)
        self.delta_threshold = self._threshold(10)
        filter_form.addRow("低置信度阈值", self.low_threshold)
        filter_form.addRow("近似并列差值", self.delta_threshold)
        self.result_wait_seconds = QSpinBox()
        self.result_wait_seconds.setRange(1, 600)
        self.result_wait_seconds.setValue(60)
        self.result_wait_seconds.setSuffix(" 秒")
        self.result_wait_seconds.setToolTip("上传后等待识别结果的总时长，包含网络请求时间")
        filter_form.addRow("结果等待时长", self.result_wait_seconds)
        root.addWidget(filter_group, 1, 0)

        path_group = QGroupBox("图片目录")
        path_form = QFormLayout(path_group)
        self.source_dir, source_row = self._path_row("选择待分类图片文件夹")
        self.output_dir, output_row = self._path_row("选择分类后图片存放文件夹")
        path_form.addRow("待分类目录", source_row)
        path_form.addRow("分类后目录", output_row)
        csv_hint = QLabel("处理记录保存在待分类目录的 birdclass_records.csv；分类会向原图写入鸟种元数据，请先备份重要图库。")
        csv_hint.setWordWrap(True)
        path_form.addRow("", csv_hint)
        root.addWidget(path_group, 2, 0)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("开始分类")
        self.start_button.setMinimumHeight(38)
        self.start_button.clicked.connect(self.start_classification)
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_classification)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.progress, 1)
        root.addLayout(action_row, 3, 0)

        status_row = QHBoxLayout()
        self.status_label = QLabel("就绪")
        self.counts_label = QLabel("共 0 · 跳过 0 · 完成 0 · 失败 0 · 待复核 0")
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        status_row.addWidget(self.counts_label)
        root.addLayout(status_row, 4, 0)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setPlaceholderText("运行日志（不会输出 API Key）")
        root.addWidget(self.log, 5, 0)
        root.setRowStretch(5, 1)

        self._run_controls = [
            self.api_key, self.query_quota_button, self.animal_class, self.area,
            self.observation_location, self.observation_time,
            self.low_threshold, self.delta_threshold, self.result_wait_seconds,
            self.source_dir, self.output_dir,
        ]

    @staticmethod
    def _threshold(value: int) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(0, 100)
        widget.setDecimals(2)
        widget.setSingleStep(1)
        widget.setSuffix(" %")
        widget.setValue(value)
        return widget

    def _path_row(self, title: str) -> tuple[QLineEdit, QWidget]:
        editor = QLineEdit()
        editor.setPlaceholderText(title)
        button = QPushButton("浏览…")
        button.clicked.connect(lambda: self._browse(editor, title))
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(editor, 1)
        layout.addWidget(button)
        return editor, container

    @staticmethod
    def _browse(editor: QLineEdit, title: str) -> None:
        selected = QFileDialog.getExistingDirectory(None, title, editor.text())
        if selected:
            editor.setText(selected)

    def query_quota(self) -> None:
        key = self.api_key.text().strip()
        if not key:
            self._show_error("请先填写 API Key")
            return
        if self._quota_worker is not None:
            return
        self.query_quota_button.setEnabled(False)
        self.quota_label.setText("正在查询…")
        worker = QuotaWorker(key, self)
        self._quota_worker = worker
        worker.succeeded.connect(self._quota_succeeded)
        worker.failed.connect(self._quota_failed)
        worker.finished.connect(self._quota_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    @staticmethod
    def _quota_text(quota: Quota) -> str:
        if quota.unlimited:
            return f"不限次数 · 已使用 {quota.used}"
        return f"剩余 {quota.remaining} 次 · 已使用 {quota.used} / 共 {quota.total}"

    def _show_quota(self, quota: Quota) -> str:
        text = self._quota_text(quota)
        self.quota_label.setText(text)
        return text

    def _quota_succeeded(self, quota: Quota) -> None:
        text = self._show_quota(quota)
        self._append_log(f"额度查询成功：{text}")

    def _quota_failed(self, message: str) -> None:
        self.quota_label.setText("查询失败")
        self._show_error(message)

    def _quota_finished(self) -> None:
        self._quota_worker = None
        self.query_quota_button.setEnabled(self._worker is None)

    def start_classification(self) -> None:
        if self._worker is not None:
            return
        try:
            config = self._config()
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self._save_settings()
        self.log.clear()
        self.counts_label.setText("共 0 · 跳过 0 · 完成 0 · 失败 0 · 待复核 0")
        self.status_label.setText("正在分类…")
        self._set_running(True)
        worker = ClassificationWorker(config, self)
        self._worker = worker
        worker.progressed.connect(self._on_progress)
        worker.review_requested.connect(self._on_review)
        worker.succeeded.connect(self._classification_succeeded)
        worker.failed.connect(self._classification_failed)
        worker.finished.connect(self._classification_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _config(self) -> AppConfig:
        if not self.api_key.text().strip():
            raise ValueError("请填写 API Key")
        if not self.source_dir.text().strip() or not self.output_dir.text().strip():
            raise ValueError("请填写待分类目录和分类后目录")
        if not self.observation_location.text().strip() or not self.observation_time.text().strip():
            raise ValueError("请填写观测地点和观测时间")
        return AppConfig(
            api_key=self.api_key.text(),
            animal_class=self.animal_class.currentData(),
            area_code=resolve_area_code(self.area),
            low_confidence_threshold=Decimal(str(self.low_threshold.value())),
            ambiguity_delta_threshold=Decimal(str(self.delta_threshold.value())),
            source_dir=Path(self.source_dir.text().strip()).expanduser(),
            output_dir=Path(self.output_dir.text().strip()).expanduser(),
            observation_location=self.observation_location.text().strip(),
            observation_time=self.observation_time.text().strip(),
            result_wait_seconds=self.result_wait_seconds.value(),
        )

    def stop_classification(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()
            self.stop_button.setEnabled(False)
            self.status_label.setText("正在安全停止…")

    def _on_progress(self, event: str, data: dict) -> None:
        if event == "quota":
            quota = data.get("quota")
            if isinstance(quota, Quota):
                text = self._show_quota(quota)
                label = "批次结束额度" if data.get("final") else "批次开始额度"
                self._append_log(f"{label}：{text}")
            return
        if event == "quota_failed":
            self._append_log(f"额度复查失败：{data.get('error', '')}")
            return
        path = data.get("relative_path", "")
        destinations = data.get("destinations") or [data.get("destination", "")]
        destination_text = "；".join(str(destination) for destination in destinations if destination)
        deferred_text = "、".join(str(index + 1) for index in data.get("deferred_targets", []))
        failure_pending_text = (
            f"；已复制到待复核：{destination_text}"
            if event == "failed" and destination_text else ""
        )
        messages = {
            "uploading": f"上传并识别：{path}",
            "completed": f"已分类：{path} → {destination_text}",
            "partially_completed": (
                f"部分分类：{path} → {destination_text}；待复核目标：{deferred_text}"
            ),
            "deferred": f"待复核：{path} → {destination_text}",
            "skipped": f"跳过已完成：{path}",
            "review_applied": (
                f"人工复核：{path} · 后面同样应用到 "
                f"{len(data.get('target_indices', []))} 个目标"
            ),
            "failed": f"失败：{path}；{data.get('error', '')}{failure_pending_text}",
        }
        if event in messages:
            self._append_log(messages[event])

    def _on_review(self, request_id: str, context) -> None:
        worker = self._worker
        if worker is None:
            return
        dialog = ReviewDialog(context, self)
        dialog.exec()
        result: ReviewResult = dialog.result
        worker.resolve_review(request_id, result)
        if result.action.value == "confirm":
            self._append_log(f"人工确认：{context.relative_path} → {result.candidate.name_cn}")
        elif result.action.value == "custom":
            self._append_log(
                f"人工鸟名：{context.relative_path} · "
                f"目标 {context.target_index + 1}/{context.target_count} → {result.custom_name_cn}"
            )
        elif result.action.value == "defer":
            self._append_log(
                f"稍后处理：{context.relative_path} · "
                f"目标 {context.target_index + 1}/{context.target_count}"
            )
        else:
            self._append_log(f"保留待复核：{context.relative_path}")

    def _classification_succeeded(self, summary: BatchSummary) -> None:
        self.counts_label.setText(
            f"共 {summary.total} · 跳过 {summary.skipped} · 完成 {summary.completed} · "
            f"失败 {summary.failed} · 待复核 {summary.deferred}"
        )
        reasons = {
            "": "本批次处理完成",
            "quota": "可用额度不足，已安全停止；下次可继续",
            "user": "已停止；下次可继续",
            "deferred": "已保留待复核目标；下次启动仅恢复未确认目标",
        }
        self.status_label.setText(reasons.get(summary.stop_reason, "本批次已结束"))
        self._append_log(self.status_label.text())

    def _classification_failed(self, message: str) -> None:
        self.status_label.setText("分类中断")
        self._append_log(message)
        self._show_error(message)

    def _classification_finished(self) -> None:
        self._worker = None
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        for control in self._run_controls:
            control.setEnabled(not running)
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.progress.setVisible(running)

    def _append_log(self, message: str) -> None:
        self.log.appendPlainText(message)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "羽栖 BirdRoost", message)

    def _restore_settings(self) -> None:
        class_index = self.animal_class.findData(self._settings.value("animal_class", "B"))
        area_index = self.area.findData(self._settings.value("area_code", "WORLD"))
        self.animal_class.setCurrentIndex(max(0, class_index))
        self.area.setCurrentIndex(max(0, area_index))
        self.observation_location.setText(str(self._settings.value("observation_location", "")))
        self.observation_time.setText(str(self._settings.value("observation_time", "")))
        self.low_threshold.setValue(float(self._settings.value("low_threshold", 80)))
        self.delta_threshold.setValue(float(self._settings.value("delta_threshold", 10)))
        self.result_wait_seconds.setValue(int(self._settings.value("result_wait_seconds", 60)))
        self.source_dir.setText(str(self._settings.value("source_dir", "")))
        self.output_dir.setText(str(self._settings.value("output_dir", "")))

    def _save_settings(self) -> None:
        self._settings.setValue("animal_class", self.animal_class.currentData())
        self._settings.setValue("area_code", self.area.currentData())
        self._settings.setValue("observation_location", self.observation_location.text().strip())
        self._settings.setValue("observation_time", self.observation_time.text().strip())
        self._settings.setValue("low_threshold", self.low_threshold.value())
        self._settings.setValue("delta_threshold", self.delta_threshold.value())
        self._settings.setValue("result_wait_seconds", self.result_wait_seconds.value())
        self._settings.setValue("source_dir", self.source_dir.text().strip())
        self._settings.setValue("output_dir", self.output_dir.text().strip())
        self._settings.sync()

    def closeEvent(self, event) -> None:
        self._save_settings()
        if self._closing:
            event.ignore()
            return
        if self._worker is None:
            event.accept()
            return
        if not self._confirm_stop_and_exit():
            event.ignore()
            return
        worker = self._worker
        if worker is None or (
            hasattr(worker, "isRunning") and not worker.isRunning()
        ):
            self._worker = None
            event.accept()
            return
        self._closing = True
        worker.request_stop()
        self.stop_button.setEnabled(False)
        self.status_label.setText("正在安全停止…")
        self._append_log("正在停止后台任务，完成当前图片后自动退出…")
        worker.finished.connect(self._close_after_worker)
        event.ignore()

    def _confirm_stop_and_exit(self) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("羽栖 BirdRoost")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("分类仍在进行。")
        box.setInformativeText("停止并退出会等待当前图片处理完成后关闭窗口。")
        stop_button = box.addButton("停止并退出", QMessageBox.ButtonRole.AcceptRole)
        cancel_button = box.addButton("取消关闭", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_button)
        box.exec()
        return box.clickedButton() is stop_button

    def _close_after_worker(self) -> None:
        if not self._closing:
            return
        self._closing = False
        self.close()
