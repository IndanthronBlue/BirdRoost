from birdclass.secret_store import _normalize_secret_key


def test_secret_key_pasted_twice_is_collapsed():
    key = "0123456789abcdef0123456789abcdef"
    assert _normalize_secret_key(key + key) == key


def test_normal_secret_key_is_preserved():
    key = "0123456789abcdef0123456789abcdef"
    assert _normalize_secret_key(key) == key
