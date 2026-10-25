from pathlib import Path

import pytest

from birdclass.errors import ConfigError
from birdclass.scanner import image_item_from_path, scan_images, validate_directories


def test_scan_recurses_filters_extensions_and_prunes_output(tmp_path: Path):
    source = tmp_path / "source"
    nested = source / "nested"
    output = source / "sorted"
    nested.mkdir(parents=True)
    output.mkdir()
    (source / "z.JPG").write_bytes(b"z")
    (source / "ignore.gif").write_bytes(b"g")
    (nested / "a.PnG").write_bytes(b"a")
    (output / "b.jpg").write_bytes(b"b")

    items = scan_images(source, output)

    assert [item.relative_path for item in items] == ["nested/a.PnG", "z.JPG"]
    assert all(item.size > 0 for item in items)


def test_image_item_uses_relative_path_and_native_identity(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "bird.jpeg"
    path.write_bytes(b"1234")

    item = image_item_from_path(path, source)

    assert item.relative_path == "bird.jpeg"
    assert item.identity.file_size == 4
    assert item.identity.file_mtime_ns == path.stat().st_mtime_ns


def test_unreadable_source_directory_is_rejected(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "output"

    def deny_source(path, mode):
        return Path(path) != source

    monkeypatch.setattr("birdclass.scanner.os.access", deny_source)

    with pytest.raises(ConfigError, match="不可读"):
        validate_directories(source, output)


def test_unwritable_output_directory_is_rejected(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()

    def deny_output(path, mode):
        return Path(path) != output

    monkeypatch.setattr("birdclass.scanner.os.access", deny_output)

    with pytest.raises(ConfigError, match="不可写"):
        validate_directories(source, output)
