from __future__ import annotations

import threading
import uuid

from PySide6.QtCore import QThread, Signal

from ..api import DongNiaoClient
from ..errors import BirdClassError
from ..models import AppConfig, ReviewAction, ReviewContext, ReviewResult
from ..service import ClassificationService


class QuotaWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, api_key: str, parent=None) -> None:
        super().__init__(parent)
        self._api_key = api_key

    def run(self) -> None:
        try:
            self.succeeded.emit(DongNiaoClient(self._api_key).query_quota())
        except BirdClassError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"额度查询出现未预期错误：{exc.__class__.__name__}")


class ClassificationWorker(QThread):
    progressed = Signal(str, object)
    review_requested = Signal(str, object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.stop_event = threading.Event()
        self._review_event = threading.Event()
        self._review_lock = threading.Lock()
        self._request_id = ""
        self._review_result: ReviewResult | None = None

    def run(self) -> None:
        try:
            summary = ClassificationService().run(
                self._config,
                self._request_review,
                lambda event, data: self.progressed.emit(event, data),
                self.stop_event,
            )
            self.succeeded.emit(summary)
        except BirdClassError as exc:
            self.failed.emit(str(exc))
        except ValueError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"分类出现未预期错误：{exc.__class__.__name__}")

    def _request_review(self, context: ReviewContext) -> ReviewResult:
        with self._review_lock:
            self._request_id = uuid.uuid4().hex
            self._review_result = None
            request_id = self._request_id
            self._review_event.clear()
        self.review_requested.emit(request_id, context)
        while not self._review_event.wait(0.1):
            if self.stop_event.is_set():
                return ReviewResult(ReviewAction.STOP)
        with self._review_lock:
            assert self._review_result is not None
            return self._review_result

    def resolve_review(self, request_id: str, result: ReviewResult) -> None:
        with self._review_lock:
            if request_id != self._request_id:
                return
            self._review_result = result
            self._review_event.set()

    def request_stop(self) -> None:
        self.stop_event.set()
        with self._review_lock:
            if self._request_id:
                self._review_result = ReviewResult(ReviewAction.STOP)
                self._review_event.set()
