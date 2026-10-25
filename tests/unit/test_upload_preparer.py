import os
from pathlib import Path

import piexif
import pytest
from PIL import Image

from birdclass.errors import ImagePreparationError, ImageValidationError
from birdclass.scanner import image_item_from_path
from birdclass.upload_preparer import MAX_UPLOAD_BYTES, UploadPreparer


def make_item(path: Path):
    return image_item_from_path(path, path.parent)


def test_small_image_is_used_directly_without_temp_file(tmp_path: Path):
    path = tmp_path / "small.jpg"
    Image.new("RGB", (100, 80), "green").save(path)
    item = make_item(path)

    with UploadPreparer.prepare(item) as prepared:
        assert prepared.upload_path == path
        assert prepared.original_path == path
        assert not prepared.was_compressed
        assert prepared.temporary_path is None
        assert prepared.upload_bytes == path.stat().st_size
        assert prepared.upload_size == (100, 80)


def test_large_image_uses_temporary_jpeg_and_preserves_original(tmp_path: Path):
    path = tmp_path / "large.png"
    Image.frombytes("RGB", (1000, 1000), os.urandom(1000 * 1000 * 3)).save(path)
    assert path.stat().st_size > MAX_UPLOAD_BYTES
    item = make_item(path)
    before = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    with UploadPreparer.prepare(item) as prepared:
        temporary_path = prepared.temporary_path
        assert prepared.was_compressed
        assert temporary_path is not None and temporary_path.exists()
        assert temporary_path.parent != tmp_path
        assert prepared.upload_path.stat().st_size <= MAX_UPLOAD_BYTES
        with Image.open(prepared.upload_path) as uploaded:
            assert uploaded.format == "JPEG"
            assert 11 <= uploaded.width <= 8192
            assert 11 <= uploaded.height <= 8192

    assert not temporary_path.exists()
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_mtime


def test_oversized_dimensions_are_downscaled_only_in_temporary_upload(tmp_path: Path):
    path = tmp_path / "wide.png"
    Image.new("RGB", (8256, 100), "green").save(path)
    item = make_item(path)
    before = path.read_bytes()

    with UploadPreparer.prepare(item) as prepared:
        assert prepared.was_compressed
        with Image.open(prepared.upload_path) as uploaded:
            assert max(uploaded.size) <= 8192
            assert uploaded.width == 8192
            assert prepared.upload_size == uploaded.size
    assert path.read_bytes() == before


def test_transparent_png_is_composited_and_original_is_untouched(tmp_path: Path):
    path = tmp_path / "alpha.png"
    Image.frombytes("RGBA", (900, 900), os.urandom(900 * 900 * 4)).save(path)
    assert path.stat().st_size > MAX_UPLOAD_BYTES
    item = make_item(path)
    before = path.read_bytes()

    with UploadPreparer.prepare(item) as prepared:
        with Image.open(prepared.upload_path) as uploaded:
            assert uploaded.mode == "RGB"

    assert path.read_bytes() == before


def test_invalid_dimensions_are_rejected_before_upload(tmp_path: Path):
    path = tmp_path / "tiny.png"
    Image.new("RGB", (10, 10)).save(path)

    with pytest.raises(ImageValidationError):
        UploadPreparer.prepare(make_item(path))


def test_unreadable_image_is_controlled_error(tmp_path: Path):
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not an image")

    with pytest.raises((ImageValidationError, ImagePreparationError)):
        UploadPreparer.prepare(make_item(path))


def test_prepared_upload_cleanup_is_idempotent(tmp_path: Path):
    path = tmp_path / "large.png"
    Image.frombytes("RGB", (1000, 1000), os.urandom(1000 * 1000 * 3)).save(path)
    prepared = UploadPreparer.prepare(make_item(path))
    temporary_path = prepared.temporary_path

    assert temporary_path is not None and temporary_path.exists()

    prepared.cleanup()
    prepared.cleanup()

    assert not temporary_path.exists()


def test_small_rotated_image_uses_oriented_temporary_upload(tmp_path: Path):
    path = tmp_path / "rotated.jpg"
    Image.new("RGB", (100, 80), "green").save(path)
    exif = piexif.dump({"0th": {piexif.ImageIFD.Orientation: 6}})
    piexif.insert(exif, str(path))
    original_bytes = path.read_bytes()

    with UploadPreparer.prepare(make_item(path)) as prepared:
        assert prepared.was_compressed is True
        assert prepared.upload_oriented is True
        assert prepared.source_size == (100, 80)
        assert prepared.display_size == (80, 100)
        assert prepared.upload_size == (80, 100)
        assert prepared.temporary_path is not None
        assert prepared.upload_path != path

    assert path.read_bytes() == original_bytes
