"""The free checker page: served at /, works without RapidAPI, rate-limited, hidden from the API docs."""
import pytest

from app.config import Settings, get_settings
from app.main import app
from app.ratelimit import RateLimiter
from tests.conftest import sample


@pytest.fixture
def limiter():
    lim = RateLimiter(per_client=3, window_s=3600, daily_cap=1000)
    app.state.public_limiter = lim
    return lim


def check(client, data: bytes):
    return client.post("/public/check", files={"file": ("x.jpg", data)})


def test_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "Is your AI image marked" in r.text and "/public/check" in r.text


def test_check_works_without_rapidapi_secret(client, limiter):
    app.dependency_overrides[get_settings] = lambda: Settings(rapidapi_proxy_secret="s3cret")
    marked = client.post("/v1/mark", files={"file": ("p.jpg", sample("photo.jpg"))},
                         headers={"X-RapidAPI-Proxy-Secret": "s3cret"}).content
    r = check(client, marked)
    assert r.status_code == 200, r.text
    assert r.json()["verdict"] == "ai_generated"
    assert client.post("/v1/inspect", files={"file": ("x", marked)}).status_code == 403  # paid API still locked


def test_per_client_limit(client, limiter):
    for _ in range(3):
        assert check(client, sample("photo.jpg")).status_code == 200
    r = check(client, sample("photo.jpg"))
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert "3 per hour" in r.json()["error"]["message"]


def test_daily_cap(client):
    app.state.public_limiter = RateLimiter(per_client=100, window_s=3600, daily_cap=2)
    assert check(client, sample("photo.jpg")).status_code == 200
    assert check(client, sample("photo.jpg")).status_code == 200
    assert check(client, sample("photo.jpg")).json()["error"]["code"] == "daily_limit"


def test_smaller_upload_limit(client, limiter, engine, monkeypatch):
    monkeypatch.setattr(engine.settings, "public_max_upload_mb", 1)
    r = check(client, b"\xff\xd8\xff" + b"0" * (2**20 + 10))
    assert r.status_code == 413


def test_not_in_api_docs(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/public/check" not in paths and "/" not in paths
