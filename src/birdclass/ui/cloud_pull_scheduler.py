from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal

from .cloud_workers import PullWorker
from .cos_config_store import load_cos_config, resolve_credentials


class CloudPullScheduler(QObject):
    """Opt-in startup/periodic fast-forward pull. Never forces over local edits."""

    pulled = Signal(object)
    failed = Signal(str)

    def __init__(self, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._worker: PullWorker | None = None

    def maybe_run(self, archive_root: Path) -> None:
        if self._worker is not None:
            return
        enabled = self.settings.value("cloud_auto_pull", False)
        enabled = enabled if isinstance(enabled, bool) else str(enabled).lower() == "true"
        if not enabled:
            return
        last = str(self.settings.value("cloud_auto_pull_last_check", ""))
        if last:
            try:
                previous = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if previous.tzinfo is None:
                    previous = previous.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - previous < timedelta(minutes=30):
                    return
            except ValueError:
                pass
        config = load_cos_config(self.settings)
        secret_id, secret_key = resolve_credentials(config)
        if not config.bucket or not config.region or not secret_id or not secret_key:
            return
        self.settings.setValue("cloud_auto_pull_last_check", datetime.now(timezone.utc).isoformat())
        self.settings.sync()
        worker = PullWorker(
            archive_root,
            {
                "bucket": config.bucket,
                "region": config.region,
                "endpoint": config.endpoint,
                "secret_id": secret_id,
                "secret_key": secret_key,
                "prefix": config.prefix,
            },
            force=False,
            parent=self,
        )
        self._worker = worker
        worker.done.connect(self._done)
        worker.failed.connect(self.failed.emit)
        worker.finished.connect(lambda worker=worker: self._finished(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _done(self, report) -> None:
        if report.action == "pulled":
            self.pulled.emit(report)
        elif report.action in {"conflict", "error"}:
            self.failed.emit("；".join(report.errors) or "自动拉取未完成")

    def _finished(self, worker) -> None:
        if self._worker is worker:
            self._worker = None

    def wait(self, timeout_ms: int = 5000) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(timeout_ms)
