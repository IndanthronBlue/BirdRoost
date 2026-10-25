from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from birdclass.models import Quota
from birdclass.ui.main_window import MainWindow


class FakeSignal:
    def __init__(self) -> None:
        self._slots = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self) -> None:
        for slot in self._slots:
            slot()


class FakeWorker:
    def __init__(self) -> None:
        self.finished = FakeSignal()
        self.stop_requested = False

    def request_stop(self) -> None:
        self.stop_requested = True


def isolated_settings(tmp_path: Path) -> None:
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings("BirdClass", "BirdClass").clear()


def fill_required_fields(window: MainWindow, tmp_path: Path) -> None:
    window.api_key.setText("test-key")
    window.source_dir.setText(str(tmp_path / "source"))
    window.output_dir.setText(str(tmp_path / "output"))
    window.observation_location.setText("云南大理")
    window.observation_time.setText("2026-10-24 1430")


def test_observation_fields_enter_config(qtbot, tmp_path):
    isolated_settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    fill_required_fields(window, tmp_path)

    config = window._config()

    assert config.observation_location == "云南大理"
    assert config.observation_time == "2026-10-24 1430"


def test_observation_fields_are_required(qtbot, tmp_path):
    isolated_settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    fill_required_fields(window, tmp_path)
    window.observation_time.clear()

    with pytest.raises(ValueError, match="请填写观测地点和观测时间"):
        window._config()


def test_observation_fields_are_saved_and_restored(qtbot, tmp_path):
    isolated_settings(tmp_path)
    first = MainWindow()
    qtbot.addWidget(first)
    fill_required_fields(first, tmp_path)
    first._save_settings()
    first.close()

    second = MainWindow()
    qtbot.addWidget(second)

    assert second.observation_location.text() == "云南大理"
    assert second.observation_time.text() == "2026-10-24 1430"


def test_completed_log_lists_every_archived_species(qtbot, tmp_path):
    isolated_settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    first = tmp_path / "output" / "三趾滨鹬" / "多尼亚那_260501_三趾滨鹬_001.jpg"
    second = tmp_path / "output" / "环颈鸻" / "多尼亚那_260501_环颈鸻_001.jpg"

    window._on_progress("completed", {
        "relative_path": "DSC_0704.jpg",
        "destination": first,
        "destinations": [first, second],
    })

    message = window.log.toPlainText()
    assert "三趾滨鹬/多尼亚那_260501_三趾滨鹬_001.jpg" in message
    assert "环颈鸻/多尼亚那_260501_环颈鸻_001.jpg" in message


def test_partial_completion_log_lists_archived_paths_and_deferred_target(qtbot, tmp_path):
    isolated_settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    archived = tmp_path / "output" / "斑鸠" / "全球_斑鸠_001.jpg"

    window._on_progress("partially_completed", {
        "relative_path": "eight-targets.jpg",
        "destination": archived,
        "destinations": [archived],
        "deferred_targets": [1],
    })

    message = window.log.toPlainText()
    assert "部分分类" in message
    assert "斑鸠/全球_斑鸠_001.jpg" in message
    assert "待复核目标：2" in message


def test_deferred_log_lists_pending_review_copy(qtbot, tmp_path):
    isolated_settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    pending = tmp_path / "output" / "待复核" / "birds.jpg"

    window._on_progress("deferred", {
        "relative_path": "birds.jpg",
        "destination": pending,
        "deferred_targets": [0, 1],
    })

    message = window.log.toPlainText()
    assert "待复核：birds.jpg" in message
    assert "待复核/birds.jpg" in message


def test_result_wait_defaults_to_60_and_enters_config(qtbot, tmp_path):
    isolated_settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    fill_required_fields(window, tmp_path)

    assert window.result_wait_seconds.value() == 60
    window.result_wait_seconds.setValue(45)
    config = window._config()

    assert config.result_wait_seconds == 45


def test_result_wait_is_saved_and_restored(qtbot, tmp_path):
    isolated_settings(tmp_path)
    first = MainWindow()
    qtbot.addWidget(first)
    first.result_wait_seconds.setValue(75)
    first._save_settings()
    first.close()

    second = MainWindow()
    qtbot.addWidget(second)

    assert second.result_wait_seconds.value() == 75


def test_window_uses_birdroost_name(qtbot, tmp_path):
    isolated_settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.windowTitle() == "羽栖 BirdRoost · 鸟图整理"


def test_window_leaves_colors_to_application_system_theme(qtbot, tmp_path):
    isolated_settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.styleSheet() == ""


def test_batch_quota_progress_updates_label_and_log(qtbot, tmp_path):
    isolated_settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)

    window._on_progress("quota", {"quota": Quota(2, 10, 0), "final": True})
    window._on_progress("quota_failed", {"error": "网络请求失败"})

    assert window.quota_label.text() == "剩余 0 次 · 已使用 2 / 共 10"
    message = window.log.toPlainText()
    assert "批次结束额度：剩余 0 次" in message
    assert "额度复查失败：网络请求失败" in message


def test_close_while_running_can_be_cancelled(qtbot, tmp_path, monkeypatch):
    isolated_settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    worker = FakeWorker()
    window._worker = worker
    monkeypatch.setattr(window, "_confirm_stop_and_exit", lambda: False)

    assert window.close() is False
    assert worker.stop_requested is False
    assert window._closing is False


def test_close_while_running_requests_stop_and_waits_for_finish(qtbot, tmp_path, monkeypatch):
    isolated_settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    worker = FakeWorker()
    window._worker = worker
    monkeypatch.setattr(window, "_confirm_stop_and_exit", lambda: True)

    assert window.close() is False
    assert worker.stop_requested is True
    assert window._closing is True
    assert window.status_label.text() == "正在安全停止…"
    assert "自动退出" in window.log.toPlainText()

    window._worker = None
    worker.finished.emit()

    assert window._closing is False
