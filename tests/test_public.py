"""The free checker page: served at /, works without RapidAPI, rate-limited, hidden from the API docs."""
import json
import xml.etree.ElementTree as ET

import pytest

from app.config import Settings, get_settings
from app.main import app
from app.ratelimit import RateLimiter
from app.routers import public
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


def test_page_has_seo_tags(client):
    html = client.get("/").text
    base = "https://marklayer-api.onrender.com"
    assert f'<link rel="canonical" href="{base}/">' in html
    assert f'<meta property="og:image" content="{base}/og.png">' in html
    assert "{{BASE_URL}}" not in html
    start = html.index('<script type="application/ld+json">') + len('<script type="application/ld+json">')
    ld = json.loads(html[start:html.index("</script>", start)])
    types = {node["@type"] for node in ld["@graph"]}
    assert types == {"WebApplication", "FAQPage"}
    faq = next(n for n in ld["@graph"] if n["@type"] == "FAQPage")
    visible = html[html.index("<body>"):]  # Google requires FAQ markup to match text on the page
    for q in faq["mainEntity"]:
        assert q["acceptedAnswer"]["text"] in visible


def test_robots_and_sitemap(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "Disallow: /v1/" in r.text and "Disallow: /public/" in r.text
    assert "Sitemap: https://marklayer-api.onrender.com/sitemap.xml" in r.text
    s = client.get("/sitemap.xml")
    assert s.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(s.text)
    locs = [e.text for e in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert locs == ["https://marklayer-api.onrender.com/"]


def test_base_url_follows_setting(client):
    app.dependency_overrides[get_settings] = lambda: Settings(public_base_url="https://marklayer.eu/")
    public._page.cache_clear()
    assert '<link rel="canonical" href="https://marklayer.eu/">' in client.get("/").text
    assert "Sitemap: https://marklayer.eu/sitemap.xml" in client.get("/robots.txt").text
    public._page.cache_clear()


def test_search_engine_verification_tags(client):
    html = client.get("/").text
    assert '<meta name="google-site-verification" content="IZPzAZVVMYufE84qDPvQL-AV0DTpY5dTaDK_l_fyvT8">' in html
    assert "msvalidate.01" not in html  # no Bing code configured
    assert "{{VERIFY_TAGS}}" not in html
    app.dependency_overrides[get_settings] = lambda: Settings(google_site_verification="", bing_site_verification='b"<x')
    public._page.cache_clear()
    html = client.get("/").text
    assert "google-site-verification" not in html
    assert '<meta name="msvalidate.01" content="b&quot;&lt;x">' in html  # escaped, can't break out of the tag
    public._page.cache_clear()


def test_share_image_and_head(client):
    r = client.get("/og.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    for path in ("/", "/robots.txt", "/sitemap.xml"):
        assert client.head(path).status_code == 200


def test_not_in_api_docs(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/public/check" not in paths and "/" not in paths
