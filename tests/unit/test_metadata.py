from pathlib import Path

import piexif
from PIL import Image, PngImagePlugin

from birdclass.metadata import write_species_metadata


def pixels(path: Path):
    with Image.open(path) as image:
        return image.convert("RGB").tobytes()


def test_jpeg_writes_chinese_species_without_changing_pixels(tmp_path):
    path = tmp_path / "bird.jpg"
    Image.new("RGB", (40, 30), "green").save(path)
    exif = {"0th": {piexif.ImageIFD.Make: b"Canon"}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    piexif.insert(piexif.dump(exif), str(path))
    before = pixels(path)

    write_species_metadata(path, "短趾雕")

    metadata = piexif.load(str(path))
    assert metadata["0th"][piexif.ImageIFD.ImageDescription].decode("utf-8") == "短趾雕"
    assert bytes(metadata["0th"][piexif.ImageIFD.XPKeywords]).decode("utf-16le").rstrip("\x00") == "短趾雕"
    assert metadata["0th"][piexif.ImageIFD.Make] == b"Canon"
    assert pixels(path) == before


def test_same_species_metadata_is_idempotent(tmp_path):
    path = tmp_path / "bird.jpg"
    Image.new("RGB", (40, 30), "green").save(path)

    assert write_species_metadata(path, "麻雀") is True
    before = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    assert write_species_metadata(path, "麻雀") is False
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_mtime


def test_png_writes_chinese_species_and_preserves_existing_text_and_pixels(tmp_path):
    path = tmp_path / "bird.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "tester")
    Image.new("RGB", (40, 30), "blue").save(path, pnginfo=info)
    before = pixels(path)

    write_species_metadata(path, "短趾雕")

    with Image.open(path) as image:
        assert image.text["Description"] == "短趾雕"
        assert image.text["Keywords"] == "短趾雕"
        assert image.text["Author"] == "tester"
    assert pixels(path) == before
