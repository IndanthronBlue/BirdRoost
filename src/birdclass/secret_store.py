from __future__ import annotations

import shutil
from pathlib import Path
import subprocess
import sys

SERVICE = "com.birdclass.birdroost.api-key"
ACCOUNT = "BirdRoost"
SECURITY_PATH = "/usr/bin/security"
_LAST_ERROR = ""


def last_error() -> str:
    return _LAST_ERROR


def _security() -> str | None:
    if sys.platform != "darwin":
        return None
    if Path(SECURITY_PATH).is_file():
        return SECURITY_PATH
    return shutil.which("security")


def save_api_key(key: str) -> bool:
    """Store the API key in the macOS login keychain."""
    executable = _security()
    key = key.strip()
    if executable is None or not key:
        return False
    global _LAST_ERROR
    _LAST_ERROR = ""
    try:
        result = subprocess.run(
            [
                executable, "add-generic-password",
                "-a", ACCOUNT, "-s", SERVICE, "-w", key, "-U",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _LAST_ERROR = str(exc)
        return False
    if result.returncode != 0:
        _LAST_ERROR = (result.stderr or result.stdout or f"security exit {result.returncode}").strip()
    return result.returncode == 0


def load_api_key() -> str:
    global _LAST_ERROR
    _LAST_ERROR = ""
    executable = _security()
    if executable is None:
        _LAST_ERROR = "找不到 macOS security 命令"
        return ""
    try:
        result = subprocess.run(
            [
                executable, "find-generic-password",
                "-a", ACCOUNT, "-s", SERVICE, "-w",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _LAST_ERROR = str(exc)
        return ""
    if result.returncode != 0:
        if result.returncode != 44:
            _LAST_ERROR = (result.stderr or result.stdout or f"security exit {result.returncode}").strip()
        return ""
    return result.stdout.strip()


def delete_api_key() -> bool:
    executable = _security()
    if executable is None:
        return False
    try:
        result = subprocess.run(
            [
                executable, "delete-generic-password",
                "-a", ACCOUNT, "-s", SERVICE,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode in (0, 44)  # 44: item not found


COS_SERVICE = "com.birdclass.birdroost.cos-credentials"
COS_ACCOUNT = "BirdRoost-COS"


def save_cos_credentials(secret_id: str, secret_key: str) -> bool:
    secret_id = secret_id.strip()
    secret_key = secret_key.strip()
    if not secret_id or not secret_key:
        return False
    import json

    return _save_generic(COS_SERVICE, COS_ACCOUNT, json.dumps({
        "secret_id": secret_id,
        "secret_key": secret_key,
    }, ensure_ascii=False))


def load_cos_credentials() -> tuple[str, str]:
    import json

    value = _load_generic(COS_SERVICE, COS_ACCOUNT)
    if not value:
        return "", ""
    try:
        data = json.loads(value)
    except ValueError:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    return str(data.get("secret_id", "")), str(data.get("secret_key", ""))


def delete_cos_credentials() -> bool:
    return _delete_generic(COS_SERVICE, COS_ACCOUNT)


def _run_security(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    executable = _security()
    if executable is None:
        return None
    try:
        return subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _save_generic(service: str, account: str, value: str) -> bool:
    global _LAST_ERROR
    _LAST_ERROR = ""
    result = _run_security([
        "add-generic-password",
        "-a", account, "-s", service, "-w", value, "-U",
    ])
    if result is None:
        _LAST_ERROR = "找不到或无法运行 macOS security 命令"
        return False
    if result.returncode != 0:
        _LAST_ERROR = (result.stderr or result.stdout or f"security exit {result.returncode}").strip()
    return result.returncode == 0


def _load_generic(service: str, account: str) -> str:
    global _LAST_ERROR
    _LAST_ERROR = ""
    result = _run_security([
        "find-generic-password", "-a", account, "-s", service, "-w",
    ])
    if result is None:
        _LAST_ERROR = "找不到或无法运行 macOS security 命令"
        return ""
    if result.returncode != 0:
        if result.returncode != 44:
            _LAST_ERROR = (result.stderr or result.stdout or f"security exit {result.returncode}").strip()
        return ""
    return result.stdout.strip()


def _delete_generic(service: str, account: str) -> bool:
    global _LAST_ERROR
    _LAST_ERROR = ""
    result = _run_security([
        "delete-generic-password", "-a", account, "-s", service,
    ])
    if result is None:
        _LAST_ERROR = "找不到或无法运行 macOS security 命令"
        return False
    if result.returncode not in (0, 44):
        _LAST_ERROR = (result.stderr or result.stdout or f"security exit {result.returncode}").strip()
    return result.returncode in (0, 44)
