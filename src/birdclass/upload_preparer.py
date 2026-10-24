from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from .errors import ImagePreparationError
from .image_validator import validate_image
from .models import ImageItem

MAX_UPLOAD_BYTES = 2_000_000
INITIAL_QUALITIES = (85, 75, 65, 55, 45, 35, 25, 15)
RESIZE_QUALITIES = (75, 55, 35, 20)


class PreparedUpload:
    def __init__(
        self,
        original_path: Path,
        upload_path: Path,
        was_compressed: bool,
        temporary_path: Path | None,
        temporary_dir: tempfile.TemporaryDirectory[str] | None,
    ) -> None:
        self.original_path = original_path
        self.upload_path = upload_path
        self.was_compressed = was_compressed
        self.temporary_path = temporary_path
        self.upload_bytes = upload_path.stat().st_size
        with Image.open(upload_path) as uploaded:
            self.upload_size = uploaded.size
        self._temporary_dir = temporary_dir

    def cleanup(self) -> None:
        if self._temporary_dir is not None:
            self._temporary_dir.cleanup()
            self._temporary_dir = None

    def __enter__(self) -> "PreparedUpload":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.cleanup()


class UploadPreparer:
    @staticmethod
    def prepare(item: ImageItem) -> PreparedUpload:
        width, height = validate_image(item)
        original = item.absolute_path
        if item.size <= MAX_UPLOAD_BYTES and max(width, height) <= 8192:
            return PreparedUpload(original, original, False, None, None)

        temporary_dir: tempfile.TemporaryDirectory[str] | None = None
        try:
            temporary_dir = tempfile.TemporaryDirectory(prefix="birdclass-upload-")
            temporary_path = Path(temporary_dir.name) / "upload.jpg"
            with Image.open(original) as opened:
                image = ImageOps.exif_transpose(opened)
                image = _to_rgb_on_white(image)
                current = image.copy()
            if max(current.size) > 8192:
                scale = 8192 / max(current.size)
                current = current.resize(
                    (max(11, int(current.width * scale)), max(11, int(current.height * scale))),
                    Image.Resampling.LANCZOS,
                )

            if _save_within_limit(current, temporary_path, INITIAL_QUALITIES):
                return PreparedUpload(original, temporary_path, True, temporary_path, temporary_dir)

            for _ in range(20):
                width = int(current.width * 0.85)
                height = int(current.height * 0.85)
                if width < 11 or height < 11 or (width, height) == current.size:
                    break
                current = current.resize((width, height), Image.Resampling.LANCZOS)
                if _save_within_limit(current, temporary_path, RESIZE_QUALITIES):
                    return PreparedUpload(original, temporary_path, True, temporary_path, temporary_dir)
            raise ImagePreparationError("无法将临时图片压缩到 2 MB 以内")
        except Exception:
            if temporary_dir is not None:
                temporary_dir.cleanup()
            raise

    @staticmethod
    def cleanup_stale() -> None:
        """预留严格前缀的过期清理入口；正常运行依赖上下文即时清理。"""


def _to_rgb_on_white(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


def _save_within_limit(image: Image.Image, path: Path, qualities: tuple[int, ...]) -> bool:
    for quality in qualities:
        image.save(path, format="JPEG", quality=quality, optimize=True)
        if path.stat().st_size <= MAX_UPLOAD_BYTES:
            with Image.open(path) as uploaded:
                if uploaded.format != "JPEG":
                    raise ImagePreparationError("临时图片格式校验失败")
                width, height = uploaded.size
                if not (11 <= width <= 8192 and 11 <= height <= 8192):
                    raise ImagePreparationError("临时图片尺寸校验失败")
                uploaded.verify()
            return True
    return False
