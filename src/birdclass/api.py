from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import requests

from .errors import (
    ApiAuthenticationError,
    ApiProtocolError,
    ApiQuotaError,
    ApiRateLimitError,
    ApiTransportError,
    ConfigError,
    RecognitionFailedError,
    RecognitionTimeoutError,
)
from .models import Quota


class DongNiaoClient:
    BASE_URL = "https://ai.open.hhodata.com/api/v2/dongniao"

    def __init__(
        self,
        api_key: str,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key.strip()
        self._session = session or requests.Session()
        self._sleep = sleep
        self._monotonic = monotonic

    def _post(self, data: dict[str, str], files: dict[str, Any] | None = None) -> tuple[int, Any]:
        try:
            response = self._session.post(
                self.BASE_URL,
                headers={"api_key": self._api_key},
                data=data,
                files=files,
                timeout=(10, 30),
            )
        except requests.RequestException as exc:
            raise ApiTransportError(f"网络请求失败：{exc.__class__.__name__}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiProtocolError(f"API 返回非 JSON 响应（HTTP {response.status_code}）") from exc
        if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], int):
            raise ApiProtocolError("API 响应结构不符合 [业务码, 内容]")

        code, body = payload[0], payload[1]
        if response.status_code >= 400 or code == 1007:
            if code == 1007 or response.status_code == 503:
                raise ApiRateLimitError("API 触发限流，请稍后再试")
            if code == 1005:
                raise ApiAuthenticationError("API Key 不匹配或已禁用")
            if code == 1006:
                raise ApiAuthenticationError("当前 IP 不在 API Key 白名单中")
            raise ApiTransportError(f"API HTTP 错误 {response.status_code}：{body}")
        return code, body

    def query_quota(self) -> Quota:
        code, payload = self._post(data={"quota": "1"})
        if code == 1005:
            raise ApiAuthenticationError("API Key 不匹配或已禁用")
        if code == 1006:
            raise ApiAuthenticationError("当前 IP 不在 API Key 白名单中")
        if code != 1000:
            raise ApiQuotaError(f"额度查询失败：{payload}")
        if not isinstance(payload, dict):
            raise ApiProtocolError("额度响应不是对象")
        image = payload.get("image", payload)
        if not isinstance(image, dict):
            raise ApiProtocolError("图像额度响应不是对象")
        try:
            return Quota(
                used=int(image["used"]),
                total=int(image["total"]),
                remaining=int(image["remaining"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiProtocolError("额度响应缺少 used/total/remaining") from exc

    def submit_image(self, image_path: Path, animal_class: str, area_code: str) -> str:
        data = {"upload": "1", "class": animal_class}
        if area_code != "WORLD":
            data["area"] = area_code
        with image_path.open("rb") as handle:
            files = {"image": (image_path.name, handle, "application/octet-stream")}
            code, payload = self._post(data=data, files=files)
        if code == 1000 and isinstance(payload, str) and payload:
            return payload
        if code in (1004, 1005):
            raise ConfigError(f"识别类别或地区配置错误：{payload}")
        raise RecognitionFailedError(f"图片上传失败（{code}）：{payload}")

    def poll_result(self, result_id: str, total_wait_seconds: float = 60) -> list[Any]:
        if total_wait_seconds <= 0:
            raise ValueError("结果等待时长必须大于 0 秒")
        deadline = self._monotonic() + total_wait_seconds
        while True:
            code, payload = self._post(data={"resultid": result_id})
            if code == 1001:
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    break
                self._sleep(min(1.0, remaining))
                continue
            if code == 1000 and isinstance(payload, list):
                return payload
            if code in (1009, 1011):
                raise ConfigError(f"地区筛选未返回可用物种（{code}）：{payload}")
            raise RecognitionFailedError(f"识别失败（{code}）：{payload}")
        raise RecognitionTimeoutError(
            f"识别超时：结果查询等待 {total_wait_seconds:g} 秒仍未完成（resultid: {result_id}）"
        )
