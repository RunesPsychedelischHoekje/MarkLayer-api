"""POST/GET /v1/inspect on files we didn't mark, generator traces, URL safety, strip-check, auth."""
import io
import json

import pytest
from PIL import Image, PngImagePlugin

from app.config import Settings, get_settings
from app.errors import ApiError
from app.services import fetch as fetch_mod
from app.services.media import sniff
from app.services.watermark import PAYLOAD_BITS, new_payload, parse_payload
from tests.conftest import sample, to_bytes


def inspect(client, data: bytes):
    r = client.post("/v1/inspect", files={"file": ("x", data)})
    assert r.status_code == 200, r.text
    return r.json()


def png_with_text(**chunks) -> bytes:
    info = PngImagePlugin.PngInfo()
    for k, v in chunks.items():
        info.add_text(k, v)
    return to_bytes(Image.new("RGB", (64, 64), "gray"), "PNG", pnginfo=info)


def test_plain_photo_has_no_signals(client, photo):
    j = inspect(client, photo)
    assert j["verdict"] == "no_signals" and j["ai_declared"] is False
    assert j["label_suggestions"] is None
    assert j["c2pa"] == {"present": False} and not j["watermark"]["detected"]
    assert "does not mean" in j["summary"]


def test_third_party_c2pa_is_read_but_algorithmic_media_is_not_ai(client):
    # c2pa-rs test file: valid manifest, untrusted test signer, IPTC "algorithmicMedia" (no AI training).
    j = inspect(client, sample("C.jpg"))
    c = j["c2pa"]
    assert c["present"] and c["valid"] and c["signer"]["trusted"] is False
    assert c["signer"]["issuer"] == "C2PA Test Signing Cert"
    assert c["digital_source_types"] == ["http://cv.iptc.org/newscodes/digitalsourcetype/algorithmicMedia"]
    assert j["verdict"] == "no_signals"


def test_edit_actions_are_listed(client):
    j = inspect(client, sample("CA.jpg"))  # c2pa-rs test file: an opened-and-adjusted image
    assert [a["action"] for a in j["c2pa"]["actions"]] == ["c2pa.opened", "c2pa.color_adjustments"]
    assert j["verdict"] == "no_signals"


@pytest.mark.parametrize(
    "chunks, generator",
    [
        ({"parameters": "a cat\nSteps: 20, Sampler: Euler a, CFG scale: 7, Seed: 1"},
         "Stable Diffusion WebUI (AUTOMATIC1111 or compatible)"),
        ({"parameters": "a cat\nSteps: 20, Sampler: Euler, Version: f2.0.1v1.10.1"}, "Stable Diffusion WebUI Forge"),
        ({"prompt": json.dumps({"3": {"class_type": "KSampler", "inputs": {}}})}, "ComfyUI"),
        ({"invokeai_metadata": "{}"}, "InvokeAI"),
        ({"Software": "NovelAI", "Comment": '{"uc": "lowres"}'}, "NovelAI"),
    ],
)
def test_generator_traces_in_png(client, chunks, generator):
    j = inspect(client, png_with_text(**chunks))
    assert j["verdict"] == "ai_generated" and j["strongest_evidence"] == "metadata"
    assert generator in [g["name"] for g in j["generators"]]


def test_exif_software_matches_whole_words_only(client):
    def with_software(sw: str) -> dict:
        exif = Image.Exif()
        exif[0x0131] = sw
        return inspect(client, to_bytes(Image.new("RGB", (64, 64)), "JPEG", exif=exif.tobytes()))

    assert with_software("Adobe Firefly Image 3")["generators"] == [{"name": "Adobe Firefly", "source": "exif:Software"}]
    assert with_software("Imagenomic Portraiture 4")["verdict"] == "no_signals"


def test_oversized_image_still_gets_c2pa_check(client, engine, monkeypatch):
    monkeypatch.setattr(engine.settings, "max_megapixels", 0.01)
    j = inspect(client, sample("C.jpg"))
    assert j["c2pa"]["present"] and j["watermark"] is None
    assert j["file"]["checks"] == ["c2pa"] and "limit" in j["file"]["image_checks_skipped"]


def test_inspect_needs_exactly_one_input(client, photo):
    assert client.post("/v1/inspect").status_code == 422
    r = client.post("/v1/inspect", files={"file": ("x", photo)}, data={"url": "https://example.com/a.jpg"})
    assert r.json()["error"]["code"] == "file_or_url"
    assert client.post("/v1/inspect", files={"file": ("x", b"hello world")}).status_code == 415


@pytest.mark.parametrize("url", ["http://127.0.0.1/a.jpg", "http://169.254.169.254/latest/meta-data",
                                 "http://[::1]/a.png", "http://10.0.0.5/x", "file:///etc/passwd", "ftp://example.com/x"])
def test_url_fetch_blocks_private_and_non_http(client, url):
    r = client.get("/v1/inspect", params={"url": url})
    assert r.status_code == 422
    assert r.json()["error"]["code"] in ("forbidden_url", "invalid_url")


def test_url_inspect_uses_fetched_bytes(client, monkeypatch, photo):
    monkeypatch.setattr(fetch_mod, "fetch", lambda url, *a: photo)
    r = client.get("/v1/inspect", params={"url": "https://example.com/photo.jpg"})
    assert r.status_code == 200 and r.json()["file"]["format"] == "jpeg"


def test_strip_check_watermark_survives_common_edits(client):
    marked = client.post("/v1/mark", files={"file": ("p.jpg", sample("photo.jpg"))}).content
    r = client.post("/v1/strip-check", files={"file": ("m.jpg", marked)})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["original_layers"] == {"c2pa": True, "iptc": True, "watermark": True}
    survived, total = map(int, j["watermark_survival"].split("/"))
    assert total == 9 and survived >= 8
    assert not any(row["c2pa"] for row in j["results"][1:])  # re-encoding always drops metadata


def test_rapidapi_secret_enforced(client, engine):
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: Settings(rapidapi_proxy_secret="s3cret")
    r = client.post("/v1/inspect", files={"file": ("x", sample("photo.jpg"))})
    assert r.status_code == 403
    assert r.json() == {"error": {"code": "direct_access",
                                  "message": "Direct access is not allowed. Subscribe via RapidAPI."}}
    r = client.post("/v1/inspect", files={"file": ("x", sample("photo.jpg"))},
                    headers={"X-RapidAPI-Proxy-Secret": "s3cret"})
    assert r.status_code == 200
    assert client.get("/health").json()["status"] == "ok"  # health stays open


def test_payload_tag_and_kind_roundtrip():
    for kind in ("ai_generated", "ai_edited"):
        bits, wid = new_payload(kind)
        assert len(bits) == PAYLOAD_BITS and set(bits) <= {"0", "1"}
        d = parse_payload(bits)
        assert d.ours and d.kind == kind and d.watermark_id == wid
    assert not parse_payload("0" * PAYLOAD_BITS).ours


@pytest.mark.parametrize("head, fmt", [
    (b"\xff\xd8\xff\xe0", "jpeg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"RIFF\0\0\0\0WEBPVP8 ", "webp"),
    (b"\0\0\0\x18ftypavif", "avif"), (b"\0\0\0\x18ftypheic", "heic"), (b"\0\0\0\x18ftypisom", "mp4"),
    (b"\0\0\0\x14ftypqt  ", "mov"), (b"%PDF-1.7", "pdf"), (b"ID3\x04", "mp3"), (b"RIFF\0\0\0\0WAVEfmt ", "wav"),
    (b"<html>", None),
])
def test_sniff(head, fmt):
    assert sniff(head + b"\0" * 16) == fmt


def test_check_public_rejects_unresolvable():
    with pytest.raises(ApiError) as e:
        fetch_mod._check_public("http://does-not-exist.invalid/x.jpg")
    assert e.value.code == "unresolvable_url"
