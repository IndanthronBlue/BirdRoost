from __future__ import annotations

from pathlib import Path

from PIL import Image

NormalizedBox = tuple[float, float, float, float]

_EXIF_ORIENTATION = 0x0112
_SWAPPED_ORIENTATIONS = {5, 6, 7, 8}


def image_orientation(path: Path) -> int:
    try:
        with Image.open(path) as image:
            value = image.getexif().get(_EXIF_ORIENTATION, 1)
    except (OSError, ValueError):
        return 1
    try:
        orientation = int(value)
    except (TypeError, ValueError):
        return 1
    return orientation if 1 <= orientation <= 8 else 1


def display_size(raw_size: tuple[int, int], orientation: int) -> tuple[int, int]:
    width, height = raw_size
    if orientation in _SWAPPED_ORIENTATIONS:
        return height, width
    return width, height


def clamp_box(box: NormalizedBox) -> NormalizedBox:
    left, top, right, bottom = (max(0.0, min(1.0, float(value))) for value in box)
    left, right = sorted((left, right))
    top, bottom = sorted((top, bottom))
    return left, top, right, bottom


def _map_point(x: float, y: float, orientation: int) -> tuple[float, float]:
    if orientation == 2:
        return 1.0 - x, y
    if orientation == 3:
        return 1.0 - x, 1.0 - y
    if orientation == 4:
        return x, 1.0 - y
    if orientation == 5:
        return y, x
    if orientation == 6:
        return 1.0 - y, x
    if orientation == 7:
        return 1.0 - y, 1.0 - x
    if orientation == 8:
        return y, 1.0 - x
    return x, y


def transform_box(box: NormalizedBox, orientation: int) -> NormalizedBox:
    """Map a normalized box from raw image space to display-oriented space."""
    left, top, right, bottom = clamp_box(box)
    points = (
        _map_point(left, top, orientation),
        _map_point(right, top, orientation),
        _map_point(left, bottom, orientation),
        _map_point(right, bottom, orientation),
    )
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return clamp_box((min(xs), min(ys), max(xs), max(ys)))


def upload_box_to_display(
    box: NormalizedBox,
    *,
    orientation: int,
    upload_oriented: bool,
) -> NormalizedBox:
    """Convert an upload-normalized box to display-oriented normalized space."""
    if upload_oriented:
        return clamp_box(box)
    return transform_box(box, orientation)


def box_to_pixels(
    box: NormalizedBox,
    size: tuple[int, int],
) -> tuple[float, float, float, float]:
    width, height = size
    left, top, right, bottom = clamp_box(box)
    return left * width, top * height, right * width, bottom * height


def normalize_api_box(
    box: tuple[float, float, float, float],
    upload_size: tuple[int, int],
) -> NormalizedBox:
    width, height = upload_size
    if width <= 0 or height <= 0:
        raise ValueError("上传图片尺寸无效")
    left, top, right, bottom = (float(value) for value in box)
    return clamp_box((left / width, top / height, right / width, bottom / height))
