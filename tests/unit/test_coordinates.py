import piexif
import pytest
from PIL import Image

from birdclass.coordinates import (
    box_to_pixels,
    clamp_box,
    display_size,
    image_orientation,
    normalize_api_box,
    transform_box,
    upload_box_to_display,
)


def test_display_size_swaps_for_quarter_turns():
    assert display_size((4000, 3000), 1) == (4000, 3000)
    assert display_size((4000, 3000), 2) == (4000, 3000)
    assert display_size((4000, 3000), 3) == (4000, 3000)
    assert display_size((4000, 3000), 4) == (4000, 3000)
    assert display_size((4000, 3000), 5) == (3000, 4000)
    assert display_size((4000, 3000), 6) == (3000, 4000)
    assert display_size((4000, 3000), 7) == (3000, 4000)
    assert display_size((4000, 3000), 8) == (3000, 4000)


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        (1, (0.1, 0.2, 0.3, 0.4)),
        (2, (0.7, 0.2, 0.9, 0.4)),
        (3, (0.7, 0.6, 0.9, 0.8)),
        (4, (0.1, 0.6, 0.3, 0.8)),
        (5, (0.2, 0.1, 0.4, 0.3)),
        (6, (0.6, 0.1, 0.8, 0.3)),
        (7, (0.6, 0.7, 0.8, 0.9)),
        (8, (0.2, 0.7, 0.4, 0.9)),
    ],
)
def test_box_transform_for_exif_orientation(orientation, expected):
    assert transform_box((0.1, 0.2, 0.3, 0.4), orientation) == pytest.approx(expected)


def test_compressed_upload_box_is_already_display_oriented():
    box = (0.1, 0.2, 0.3, 0.4)

    assert upload_box_to_display(box, orientation=6, upload_oriented=True) == box
    assert upload_box_to_display(box, orientation=6, upload_oriented=False) == pytest.approx(
        (0.6, 0.1, 0.8, 0.3)
    )


def test_normalized_box_uses_upload_dimensions_and_maps_to_original_pixels():
    normalized = normalize_api_box((100, 160, 500, 640), (1000, 800))

    assert normalized == pytest.approx((0.1, 0.2, 0.5, 0.8))
    assert box_to_pixels(normalized, (4000, 3200)) == pytest.approx(
        (400.0, 640.0, 2000.0, 2560.0)
    )


def test_box_is_clamped_and_reordered():
    assert clamp_box((-0.1, 0.8, 1.2, 0.2)) == pytest.approx((0.0, 0.2, 1.0, 0.8))


def test_image_orientation_reads_exif_tag(tmp_path):
    path = tmp_path / "rotated.jpg"
    Image.new("RGB", (100, 80), "green").save(path)
    exif = piexif.dump({"0th": {piexif.ImageIFD.Orientation: 6}})
    piexif.insert(exif, str(path))

    assert image_orientation(path) == 6
