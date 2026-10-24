from pathlib import Path

from birdclass.scanner import image_item_from_path, scan_images


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
