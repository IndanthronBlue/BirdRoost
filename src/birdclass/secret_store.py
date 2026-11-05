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
