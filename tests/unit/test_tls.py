import os
from pathlib import Path

from birdclass.tls import configure_ca_bundle


def test_configure_ca_bundle_sets_existing_bundle(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    path = configure_ca_bundle()

    assert path
    assert Path(path).is_file()
    assert os.environ["SSL_CERT_FILE"] == path
    assert os.environ["REQUESTS_CA_BUNDLE"] == path
