from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..cloud_backup import test_connection, upload_plan
from ..cloud_export import export_archive


class ExportWorker(QThread):
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


class UploadWorker(QThread):
    progressed = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, plan, secret_id: str, secret_key: str, parent=None, *, force: bool = False) -> None:
        super().__init__(parent)
        self.plan = plan
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.force = force
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            report = upload_plan(
                self.plan,
                secret_id=self.secret_id,
                secret_key=self.secret_key,
                progress=lambda done, total, key: self.progressed.emit(done, total, key),
                cancelled=self.cancel_event.is_set,
                force=self.force,
            )
            self.done.emit(report)
        except Exception as exc:
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")

    def cancel(self) -> None:
        self.cancel_event.set()


class ConnectionWorker(QThread):
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


class SyncWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, archive_root: Path, export_root: Path, kwargs, parent=None, *, force: bool = False) -> None:
        super().__init__(parent)
        self.archive_root = archive_root
        self.export_root = export_root
        self.kwargs = kwargs
        self.force = force

    def run(self) -> None:
        try:
            from ..cloud_sync import sync_manifest

            self.done.emit(sync_manifest(
                self.archive_root, self.export_root,
                force=self.force, **self.kwargs,
            ))
        except Exception as exc:
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")


class CleanupWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, archive_root: Path, export_root: Path, kwargs, *, dry_run: bool, parent=None) -> None:
        super().__init__(parent)
        self.archive_root = archive_root
        self.export_root = export_root
        self.kwargs = kwargs
        self.dry_run = dry_run

    def run(self) -> None:
        try:
            from ..cloud_cleanup import cleanup_tombstones

            self.done.emit(cleanup_tombstones(
                self.archive_root, self.export_root,
                dry_run=self.dry_run, **self.kwargs,
            ))
        except Exception as exc:
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")


class PullWorker(QThread):
    progressed = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, archive_root: Path, kwargs, *, force: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.archive_root = archive_root
        self.kwargs = kwargs
        self.force = force
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            from ..cloud_pull import pull_from_cos

            self.done.emit(pull_from_cos(
                self.archive_root,
                force=self.force,
                progress=lambda done, total, key: self.progressed.emit(done, total, key),
                cancelled=self.cancel_event.is_set,
                **self.kwargs,
            ))
        except Exception as exc:
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")

    def cancel(self) -> None:
        self.cancel_event.set()
