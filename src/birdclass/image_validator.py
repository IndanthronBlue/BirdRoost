from __future__ import annotations

from PIL import Image, UnidentifiedImageError

from .errors import ImageValidationError
from .models import ImageItem


def validate_image(item: ImageItem) -> tuple[int, int]:
    try:
        with Image.open(item.absolute_path) as image:
            if image.format not in {"JPEG", "PNG"}:
                raise ImageValidationError("图片实际格式不是 JPG 或 PNG")
            width, height = image.size
            if width < 11 or height < 11:
                raise ImageValidationError(f"图片尺寸 {width}×{height} 小于 11 像素下限")
            image.verify()
            return width, height
    except ImageValidationError:
        raise
    except Image.DecompressionBombError as exc:
        raise ImageValidationError(
            f"图片像素过大，已跳过（{exc}）。请先将图片缩小到 8192 像素以内再分类"
        ) from exc
    except (OSError, UnidentifiedImageError) as exc:
        raise ImageValidationError("图片无法解析或已损坏") from exc
