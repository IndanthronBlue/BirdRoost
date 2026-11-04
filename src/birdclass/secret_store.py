from __future__ import annotations

import shutil
import subprocess
import sys

SERVICE = "com.birdclass.birdroost.api-key"
ACCOUNT = "BirdRoost"


def _security() -> str | None:
    if sys.platform != "darwin":
        return None
    return shutil.which("security")


def save_api_key(key: str) -> bool:
    """Store the API key in the macOS login keychain."""
    executable = _security()
    key = key.strip()
    if executable is None or not key:
        return False
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
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def load_api_key() -> str:
    executable = _security()
    if executable is None:
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
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
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
