from __future__ import annotations

import os
import sys
from pathlib import Path


def _candidates() -> list[Path]:
    result: list[Path] = []
    try:
        import certifi

        result.append(Path(certifi.where()))
    except Exception:
        pass
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        root = Path(meipass)
        result.extend([
            root / "certifi" / "cacert.pem",
            root / "Resources" / "certifi" / "cacert.pem",
        ])
    result.extend([
        Path("/etc/ssl/cert.pem"),
        Path("/usr/local/etc/openssl@3/cert.pem"),
        Path("/opt/homebrew/etc/openssl@3/cert.pem"),
    ])
    return result


def configure_ca_bundle() -> str:
    """Point requests/COS at a CA bundle that actually exists in the bundle."""
    for candidate in _candidates():
        try:
            if candidate.is_file() and candidate.stat().st_size > 0:
                path = str(candidate)
                os.environ["SSL_CERT_FILE"] = path
                os.environ["REQUESTS_CA_BUNDLE"] = path
                os.environ["CURL_CA_BUNDLE"] = path
                return path
        except OSError:
            continue
    return ""
