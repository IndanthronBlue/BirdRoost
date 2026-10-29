from pathlib import Path

import pytest
from PIL import Image

from birdclass.errors import ImageValidationError
from birdclass.image_validator import validate_image
from birdclass.models import ImageItem


def test_decompression_bomb_becomes_clear_validation_error(tmp_path: Path, monkeypatch):
    path = tmp_path / "large.jpg"
    Image.new("RGB", (100, 100), "green").save(path)
    item = ImageItem(path, "large.jpg", path.stat().st_size, path.stat().st_mtime_ns)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)

    with pytest.raises(ImageValidationError, match="图片像素过大"):
        validate_image(item)
