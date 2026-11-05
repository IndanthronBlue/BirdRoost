from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal

from .cloud_workers import CleanupWorker
from .cos_config_store import load_cos_config, resolve_credentials


class CloudCleanupScheduler(QObject):
    """Opt-in periodic tombstone cleanup for the active archive."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._worker: CleanupWorker | None = None

    def maybe_run(self, archive_root: Path, export_root: Path) -> None:
        if self._worker is not None:
            return
        enabled = self.settings.value("cloud_cleanup_auto", False)
        enabled = enabled if isinstance(enabled, bool) else str(enabled).lower() == "true"
        if not enabled:
            return
        last = str(self.settings.value("cloud_cleanup_last_run", ""))
        if last:
            try:
                previous = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if previous.tzinfo is None:
                    previous = previous.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - previous < timedelta(days=7):
                    return
            except ValueError:
                pass
        config = load_cos_config(self.settings)
        secret_id, secret_key = resolve_credentials(config)
        if not config.bucket or not config.region or not secret_id or not secret_key:
            return
        retention = int(self.settings.value("cloud_cleanup_retention_days", 30) or 30)
        worker = CleanupWorker(
            archive_root,
            export_root,
            {
                "bucket": config.bucket,
                "region": config.region,
                "endpoint": config.endpoint,
                "secret_id": secret_id,
                "secret_key": secret_key,
                "prefix": config.prefix,
                "retention_days": retention,
            },
            dry_run=False,
            parent=self,
        )
        self._worker = worker
        worker.done.connect(self._done)
        worker.failed.connect(self._failed)
        worker.finished.connect(lambda worker=worker: self._finished(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _done(self, report) -> None:
        self.settings.setValue("cloud_cleanup_last_run", datetime.now(timezone.utc).isoformat())
        self.settings.sync()
        self.finished.emit(report)

    def _failed(self, message: str) -> None:
        self.failed.emit(message)

    def wait(self, timeout_ms: int = 5000) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(timeout_ms)

    def _finished(self, worker) -> None:
        if self._worker is worker:
            self._worker = None
