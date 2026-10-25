from pathlib import Path

import pytest

from birdclass.api import DongNiaoClient
from birdclass.errors import (
    ApiProtocolError,
    ConfigError,
    RecognitionFailedError,
    RecognitionTimeoutError,
    SpeciesNotFoundError,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_normal_quota_prefers_image_payload():
    client = DongNiaoClient("secret")
    client._post = lambda **_: (1000, {
        "image": {"used": 7, "total": 10, "remaining": 3},
        "used": 99, "total": 100, "remaining": 1,
    })

    quota = client.query_quota()

    assert (quota.used, quota.total, quota.remaining) == (7, 10, 3)
    assert not quota.unlimited


def test_unlimited_quota():
    client = DongNiaoClient("secret")
    client._post = lambda **_: (1000, {
        "image": {"used": 0, "total": -1, "remaining": -1}
    })

    quota = client.query_quota()

    assert quota.unlimited
    assert quota.total == -1


def test_submit_uses_required_fields_and_closes_file(tmp_path: Path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"jpg")
    client = DongNiaoClient("secret")
    seen = {}

    def fake_post(**kwargs):
        seen.update(kwargs)
        assert kwargs["files"]["image"][1].read() == b"jpg"
        return 1000, "result-1"

    client._post = fake_post

    assert client.submit_image(image, "B", "WORLD") == "result-1"
    assert seen["data"] == {"upload": "1", "class": "B"}
    assert seen["files"]["image"][1].closed


def test_poll_waits_then_returns_result():
    clock = FakeClock()
    client = DongNiaoClient("secret", sleep=clock.sleep, monotonic=clock.monotonic)
    responses = iter([(1001, "result-1"), (1000, [{"box": [], "list": []}])])
    client._post = lambda **_: next(responses)

    result = client.poll_result("result-1", total_wait_seconds=5)

    assert result == [{"box": [], "list": []}]
    assert clock.sleeps == [1.0]


def test_poll_times_out_at_configurable_total_wait_deadline():
    clock = FakeClock()
    client = DongNiaoClient("secret", sleep=clock.sleep, monotonic=clock.monotonic)
    calls = 0

    def pending(**_):
        nonlocal calls
        calls += 1
        return 1001, "result-1"

    client._post = pending

    with pytest.raises(RecognitionTimeoutError, match="2 秒.*result-1"):
        client.poll_result("result-1", total_wait_seconds=2)
    assert calls == 3
    assert clock.sleeps == [1.0, 1.0]


def test_non_array_business_response_is_protocol_error():
    client = DongNiaoClient("secret")
    client._post = lambda **_: (1000, {"unexpected": True})

    with pytest.raises(ApiProtocolError):
        client.query_quota()


def test_species_not_found_is_a_single_image_failure():
    client = DongNiaoClient("secret")
    client._post = lambda **_: (1011, "Species not found in this area")

    with pytest.raises(SpeciesNotFoundError, match="1011"):
        client.poll_result("result-1")


def test_invalid_area_remains_a_configuration_error():
    client = DongNiaoClient("secret")
    client._post = lambda **_: (1009, "Invalid area")

    with pytest.raises(ConfigError, match="1009"):
        client.poll_result("result-1")


@pytest.mark.parametrize(
    ("code", "error"),
    [
        (1002, RecognitionFailedError),
        (1003, RecognitionFailedError),
        (1004, ConfigError),
        (1005, ConfigError),
    ],
)
def test_submit_known_business_errors(tmp_path: Path, code: int, error):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"jpg")
    client = DongNiaoClient("secret")
    client._post = lambda **_: (code, "business error")

    with pytest.raises(error):
        client.submit_image(image, "B", "WORLD")


@pytest.mark.parametrize(
    ("code", "error"),
    [
        (1008, RecognitionFailedError),
        (1009, ConfigError),
        (1010, RecognitionFailedError),
    ],
)
def test_poll_known_business_errors(code: int, error):
    client = DongNiaoClient("secret")
    client._post = lambda **_: (code, "business error")

    with pytest.raises(error):
        client.poll_result("result-1", total_wait_seconds=1)
