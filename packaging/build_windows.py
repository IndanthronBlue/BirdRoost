from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
APP_NAME = "BirdRoost"


def main() -> int:
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller>=6,<7"], check=True)
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    shutil.rmtree(DIST / APP_NAME, ignore_errors=True)
    subprocess.run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed",
        "--name", APP_NAME,
        "--icon", str(ROOT / "packaging" / "AppIcon.ico"),
        "--paths", str(ROOT / "src"),
        "--collect-data", "birdclass",
        "--collect-data", "pypinyin",
        "--collect-data", "certifi",
        "--collect-submodules", "qcloud_cos",
        "--collect-submodules", "keyring",
        "--exclude-module", "tkinter",
        str(ROOT / "packaging" / "launcher.py"),
    ], cwd=ROOT, check=True)
    archive = DIST / f"{APP_NAME}-Windows-x64"
    shutil.make_archive(str(archive), "zip", root_dir=DIST, base_dir=APP_NAME)
    print(f"Built: {DIST / APP_NAME / (APP_NAME + '.exe')}")
    print(f"Built: {archive}.zip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
