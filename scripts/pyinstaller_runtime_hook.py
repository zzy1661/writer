"""PyInstaller runtime hook — fix SSL certs and mark frozen mode."""

from __future__ import annotations

import os
import sys


def _configure_ssl_bundle() -> None:
    try:
        import certifi
    except ImportError:
        return
    bundle = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", bundle)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)


if getattr(sys, "frozen", False):
    os.environ.setdefault("WRITER_FROZEN", "1")
    _configure_ssl_bundle()
