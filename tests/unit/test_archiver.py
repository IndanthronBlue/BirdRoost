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


def test_archive_pending_is_idempotent_and_never_overwrites_name_collision(tmp_path: Path):
    first_source = tmp_path / "first-source"
    second_source = tmp_path / "second-source"
    first_source.mkdir()
    second_source.mkdir()
    first_image = first_source / "bird.jpg"
    second_image = second_source / "bird.jpg"
    make_image(first_image, "green")
    make_image(second_image, "red")
    archiver = FileArchiver(tmp_path / "output")

    first = archiver.archive_pending(item(first_image, first_source))
    repeated = archiver.archive_pending(item(first_image, first_source))
    second = archiver.archive_pending(item(second_image, second_source))
    second_repeated = archiver.archive_pending(item(second_image, second_source))

    assert first == repeated == tmp_path / "output" / "待复核" / "bird.jpg"
    assert second == second_repeated == tmp_path / "output" / "待复核" / "bird_002.jpg"
    assert len(list(first.parent.glob("*.jpg"))) == 2
    assert pixels(first) != pixels(second)


def test_archive_pending_preview_draws_boxes_and_keeps_original(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "bird.png"
    Image.new("RGB", (100, 80), "green").save(path)
    original_pixels = pixels(path)
    archiver = FileArchiver(tmp_path / "output")
    boxes = (
        (0, (0.1, 0.2, 0.5, 0.8)),
        (1, (0.5, 0.2, 0.9, 0.8)),
    )

    original, annotated = archiver.archive_pending_with_preview(item(path, source), boxes)

    assert original == tmp_path / "output" / "待复核" / "bird.png"
    assert annotated == tmp_path / "output" / "待复核" / "bird_待确认框.png"
    assert pixels(original) == original_pixels
    assert annotated is not None and annotated.is_file()
    with Image.open(annotated) as image:
        colors = image.convert("RGB").getcolors(maxcolors=1_000_000) or []
    assert any(color == (255, 176, 32) for _, color in colors)


def test_archive_pending_preview_is_skipped_when_no_boxes(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "bird.png"
    Image.new("RGB", (100, 80), "green").save(path)
    archiver = FileArchiver(tmp_path / "output")

    original, annotated = archiver.archive_pending_with_preview(item(path, source), ())

    assert original.is_file()
    assert annotated is None
    assert not list(original.parent.glob("*_待确认框*"))


def test_archive_pending_preview_is_idempotent_and_numbers_changed_boxes(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "bird.png"
    Image.new("RGB", (100, 80), "green").save(path)
    archiver = FileArchiver(tmp_path / "output")
    first_boxes = ((0, (0.1, 0.2, 0.5, 0.8)),)

    original, first = archiver.archive_pending_with_preview(item(path, source), first_boxes)
    repeated_original, repeated = archiver.archive_pending_with_preview(
        item(path, source), first_boxes
    )
    _, changed = archiver.archive_pending_with_preview(
        item(path, source), ((1, (0.5, 0.2, 0.9, 0.8)),)
    )

    assert repeated_original == original
    assert repeated == first
    assert changed == tmp_path / "output" / "待复核" / "bird_待确认框_002.png"
    assert len(list(original.parent.glob("bird_待确认框*.png"))) == 2


def test_archive_pending_preview_degrades_to_original_when_drawing_fails(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "bird.png"
    Image.new("RGB", (100, 80), "green").save(path)
    archiver = FileArchiver(tmp_path / "output")

    def fail(*_args, **_kwargs):
        raise OSError("模拟标注失败")

    monkeypatch.setattr("birdclass.archiver._draw_pending_boxes", fail)

    original, annotated = archiver.archive_pending_with_preview(
        item(path, source), ((0, (0.1, 0.2, 0.5, 0.8)),)
    )

    assert original.is_file()
    assert annotated is None
    assert not list(original.parent.glob("*_待确认框*"))
