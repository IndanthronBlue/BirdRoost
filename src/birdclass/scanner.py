from __future__ import annotations

import os
from pathlib import Path

from .errors import ConfigError
from .models import ImageItem

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
HISTORY_FILENAME = "birdclass_records.csv"


def image_item_from_path(path: Path, source_dir: Path) -> ImageItem:
    stat = path.stat()
    return ImageItem(
        absolute_path=path,
        relative_path=path.relative_to(source_dir).as_posix(),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def validate_directories(source_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    source = source_dir.expanduser().resolve()
    output = output_dir.expanduser().resolve()
    if not source.is_dir():
        raise ConfigError("待分类图片路径不存在或不是目录")
    if not os.access(source, os.R_OK | os.X_OK):
        raise ConfigError("待分类图片路径不可读或不可进入")
    if source == output:
        raise ConfigError("源目录和目标目录不能相同")
    if source.is_relative_to(output):
        raise ConfigError("源目录不能位于目标目录内部")
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"无法创建分类后图片目录：{exc}") from exc
    if not output.is_dir():
        raise ConfigError("分类后图片路径不是目录")
    if not os.access(output, os.W_OK | os.X_OK):
        raise ConfigError("分类后图片路径不可写或不可进入")
    return source, output


def scan_images(source_dir: Path, output_dir: Path) -> list[ImageItem]:
    source, output = validate_directories(source_dir, output_dir)
    items: list[ImageItem] = []
    for root, dirnames, filenames in os.walk(source, followlinks=False):
        root_path = Path(root)
        kept_dirs = []
        for dirname in sorted(dirnames):
            candidate = root_path / dirname
            if candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            if resolved == output or resolved.is_relative_to(output):
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        for filename in sorted(filenames):
            path = root_path / filename
            if filename == HISTORY_FILENAME or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if path.is_symlink() or not path.is_file():
                continue
            try:
                items.append(image_item_from_path(path, source))
            except OSError:
                continue
    items.sort(key=lambda item: item.relative_path)
    return items
