"""Shared fixtures. The Engine (ONNX models + signer) is built once per test session: it's slow to load.

Tests need the models: run `python scripts/fetch_assets.py` once first.
"""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings, get_settings
from app.engine import Engine
from app.main import app
from app.services.c2pa_io import make_identity

SAMPLES = Path(__file__).parent / "samples"


@pytest.fixture(scope="session")
def engine() -> Engine:
    settings = Settings(rapidapi_proxy_secret="")
    if not (settings.model_dir / "encoder_Q.onnx").exists():
        pytest.exit("Models missing: run `python scripts/fetch_assets.py` first.", returncode=2)
    chain, key, ca = make_identity("Test Org")
    settings.signing_cert_pem, settings.signing_key_pem = chain.decode(), key.decode()
    # Trust our own test CA, so the "trusted signer" path is exercised too.
    return Engine(settings, extra_anchors_pem=ca)


@pytest.fixture
def client(engine: Engine):
    app.state.engine = engine
    app.dependency_overrides[get_settings] = lambda: engine.settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


def to_bytes(im: Image.Image, fmt: str, **kw) -> bytes:
    b = io.BytesIO()
    im.save(b, fmt, **kw)
    return b.getvalue()


@pytest.fixture
def photo() -> bytes:
    return sample("photo.jpg")
