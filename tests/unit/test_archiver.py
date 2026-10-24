from pathlib import Path

from PIL import Image

from birdclass.archiver import FileArchiver, sanitize_species_directory
from birdclass.models import ArchiveSelection, ImageItem, Recognition, RecognitionCandidate


def recognition(name="短趾雕"):
    candidate = RecognitionCandidate("1", "B", name, "", "", "97.6", __import__("decimal").Decimal("97.6"))
    return Recognition("result-1", candidate, "auto")


def item(path: Path, root: Path):
    stat = path.stat()
    return ImageItem(path, path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns)


def make_image(path: Path, color: str) -> None:
    Image.new("RGB", (40, 30), color).save(path)


def pixels(path: Path):
    with Image.open(path) as image:
        return image.convert("RGB").tobytes()


def test_archive_uses_area_species_sequence_and_does_not_overwrite(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    source_path = source / "a.jpg"
    make_image(source_path, "green")
    output = tmp_path / "output"
    archiver = FileArchiver(output)

    first = archiver.archive(item(source_path, source), recognition(), area_name="中国")
    make_image(source_path, "red")
    second = archiver.archive(item(source_path, source), recognition(), area_name="中国")

    assert first.name == "中国_短趾雕_001.jpg"
    assert second.name == "中国_短趾雕_002.jpg"
    assert pixels(first) != pixels(second)
    assert second.parent == output / "短趾雕"


def test_sequence_increases_across_image_extensions(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    jpg = source / "a.jpg"
    png = source / "b.png"
    make_image(jpg, "green")
    make_image(png, "blue")
    archiver = FileArchiver(tmp_path / "output")

    first = archiver.archive(item(jpg, source), recognition(), area_name="中国")
    second = archiver.archive(item(png, source), recognition(), area_name="中国")

    assert first.name == "中国_短趾雕_001.jpg"
    assert second.name == "中国_短趾雕_002.png"


def test_saved_destination_is_reused_without_duplicate(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "a.jpg"
    make_image(path, "green")
    output = tmp_path / "output"
    archiver = FileArchiver(output)

    first = archiver.archive(item(path, source), recognition(), area_name="中国")
    second = archiver.archive(
        item(path, source), recognition(), area_name="中国",
        destination_path=first.relative_to(output).as_posix(),
    )

    assert first == second
    assert list(first.parent.iterdir()) == [first]


def test_windows_species_names_are_sanitized():
    assert sanitize_species_directory('CON') != "CON"
    assert "/" not in sanitize_species_directory("鸟/名")
    assert not sanitize_species_directory("name. ").endswith((".", " "))
    assert sanitize_species_directory("") == "未命名物种_unknown"


def test_archive_many_writes_multi_species_source_and_single_species_copies(tmp_path: Path):
    import piexif

    source = tmp_path / "source"
    source.mkdir()
    source_path = source / "a.jpg"
    make_image(source_path, "green")
    archiver = FileArchiver(tmp_path / "output")
    selections = [
        ArchiveSelection(recognition("短趾雕").candidate, (0,)),
        ArchiveSelection(recognition("麻雀").candidate, (1,)),
    ]

    planned = archiver.plan_many(selections, "中国")
    paths = archiver.archive_many(item(source_path, source), planned, "中国")
    repeated = archiver.archive_many(item(source_path, source), planned, "中国")

    assert [path.name for path in paths] == ["中国_短趾雕_001.jpg", "中国_麻雀_001.jpg"]
    assert repeated == paths
    assert len(list((tmp_path / "output").rglob("*.jpg"))) == 2
    source_exif = piexif.load(str(source_path))
    assert source_exif["0th"][piexif.ImageIFD.ImageDescription].decode("utf-8") == "短趾雕、麻雀"
    for path, species in zip(paths, ["短趾雕", "麻雀"]):
        exif = piexif.load(str(path))
        assert exif["0th"][piexif.ImageIFD.ImageDescription].decode("utf-8") == species
        assert pixels(path) == pixels(source_path)


def test_plan_many_preserves_source_extension(tmp_path: Path):
    archiver = FileArchiver(tmp_path / "output")
    selections = [ArchiveSelection(recognition("麻雀").candidate, (0,))]

    planned = archiver.plan_many(selections, "中国", ".png")

    assert planned[0].destination_path == "麻雀/中国_麻雀_001.png"


def test_observation_naming_has_independent_sequences_and_preserves_extension(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    jpg = source / "a.jpg"
    png = source / "b.png"
    make_image(jpg, "green")
    make_image(png, "blue")
    archiver = FileArchiver(tmp_path / "output")

    first = archiver.archive(
        item(jpg, source), recognition("麻雀"), observation_location="云南大理",
        observation_time="2026-10-24 1430",
    )
    second = archiver.archive(
        item(png, source), recognition("麻雀"), observation_location="云南大理",
        observation_time="2026-10-24 1430",
    )
    other_time = archiver.archive(
        item(jpg, source), recognition("麻雀"), observation_location="云南大理",
        observation_time="2026-10-25 0800",
    )

    assert first.name == "云南大理_2026-10-24 1430_麻雀_001.jpg"
    assert second.name == "云南大理_2026-10-24 1430_麻雀_002.png"
    assert other_time.name == "云南大理_2026-10-25 0800_麻雀_001.jpg"


def test_observation_components_are_sanitized(tmp_path: Path):
    archiver = FileArchiver(tmp_path / "output")
    selections = [ArchiveSelection(recognition("麻雀").candidate, (0,))]

    planned = archiver.plan_many(
        selections, "中国", ".jpg", observation_location="云南/大理", observation_time="2026:10:24",
    )

    assert planned[0].destination_path == "麻雀/云南_大理_2026_10_24_麻雀_001.jpg"


def test_plan_many_uses_observation_for_every_species(tmp_path: Path):
    archiver = FileArchiver(tmp_path / "output")
    selections = [
        ArchiveSelection(recognition("短趾雕").candidate, (0,)),
        ArchiveSelection(recognition("麻雀").candidate, (1,)),
    ]

    planned = archiver.plan_many(
        selections, "中国", observation_location="云南大理", observation_time="2026-10-24 1430",
    )

    assert [selection.destination_path for selection in planned] == [
        "短趾雕/云南大理_2026-10-24 1430_短趾雕_001.jpg",
        "麻雀/云南大理_2026-10-24 1430_麻雀_001.jpg",
    ]
