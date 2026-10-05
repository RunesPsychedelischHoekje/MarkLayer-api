"""POST /v1/mark, checked by reading the output back with /v1/inspect (the same path customers use)."""
import base64
import io

from PIL import Image

from tests.conftest import sample, to_bytes


def mark(client, data: bytes, name: str = "in.jpg", **form):
    return client.post("/v1/mark", files={"file": (name, data)}, data=form)


def inspect(client, data: bytes):
    r = client.post("/v1/inspect", files={"file": ("x", data)})
    assert r.status_code == 200, r.text
    return r.json()


def test_default_mark_returns_image_with_all_three_layers(client, photo):
    r = mark(client, photo, generator="Acme Image v2")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-layers"] == "watermark,iptc,c2pa"
    wid = r.headers["x-watermark-id"]

    out = Image.open(io.BytesIO(r.content))
    assert out.size == (800, 533)

    j = inspect(client, r.content)
    assert j["verdict"] == "ai_generated"
    assert j["strongest_evidence"] == "cryptographic"
    assert {s["strength"] for s in j["signals"]} == {"cryptographic", "watermark", "metadata"}
    assert j["c2pa"]["valid"] and j["c2pa"]["signer"]["trust_list"] == "custom"
    assert j["c2pa"]["software_agents"] == ["Acme Image v2"]
    assert j["c2pa"]["soft_bindings"][0]["alg"] == "com.adobe.trustmark.Q"
    assert j["watermark"]["watermark_id"] == wid and j["watermark"]["declares"] == "ai_generated"
    assert j["iptc"]["digital_source_type"].endswith("/trainedAlgorithmicMedia")
    assert j["label_suggestions"]["nl"] == "Gegenereerd met AI"


def test_json_response_has_receipt_and_quality(client, photo):
    r = mark(client, photo, response="json")
    assert r.status_code == 200
    body = r.json()
    receipt = body["receipt"]
    assert base64.b64decode(body["image_base64"])[:3] == b"\xff\xd8\xff"
    assert receipt["layers"]["watermark"]["psnr_db"] > 38  # invisible to the eye
    assert receipt["layers"]["c2pa"]["signer"] == "Test Org"
    assert receipt["layers"]["c2pa"]["signer_trust_list"] == "custom"
    assert receipt["input"]["had_c2pa_manifest"] is False
    assert receipt["output"]["sha256"] and receipt["notes"] == []


def test_ai_edited_png_keeps_transparency(client):
    rgba = Image.open(io.BytesIO(sample("photo.jpg"))).convert("RGBA")
    rgba.putalpha(Image.linear_gradient("L").resize(rgba.size))
    r = mark(client, to_bytes(rgba, "PNG"), name="cut.png", kind="ai_edited")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    out = Image.open(io.BytesIO(r.content))
    assert out.mode == "RGBA"
    assert out.getchannel("A").getextrema() == rgba.getchannel("A").getextrema()

    j = inspect(client, r.content)
    assert j["verdict"] == "ai_edited"
    assert j["watermark"]["declares"] == "ai_edited"
    assert j["iptc"]["digital_source_type"].endswith("/compositeWithTrainedAlgorithmicMedia")
    assert j["label_suggestions"]["en"] == "Edited with AI"


def test_format_conversion_to_webp(client, photo):
    r = mark(client, photo, format="webp")
    assert r.headers["content-type"] == "image/webp"
    j = inspect(client, r.content)
    assert j["c2pa"]["valid"] and j["watermark"]["detected"] and j["iptc"]["digital_source_type"]


def test_wide_image_marks_centre_square(client):
    tall = sample("tall.jpg")  # 400x1000: aspect > 2, TrustMark marks the centre square
    r = mark(client, tall)
    assert r.status_code == 200
    assert inspect(client, r.content)["watermark"]["detected"]


def test_watermark_only_still_declares_ai(client, photo):
    r = mark(client, photo, layers="watermark")
    assert r.headers["x-layers"] == "watermark"
    j = inspect(client, r.content)
    assert j["c2pa"] == {"present": False}
    assert j["iptc"]["digital_source_type"] is None
    assert j["verdict"] == "ai_generated" and j["strongest_evidence"] == "watermark"


def test_metadata_only_has_no_watermark_or_soft_binding(client, photo):
    r = mark(client, photo, layers="c2pa,iptc")
    assert "x-watermark-id" not in r.headers
    j = inspect(client, r.content)
    assert not j["watermark"]["detected"]
    assert j["c2pa"]["valid"] and j["c2pa"]["soft_bindings"] == []


def test_exif_orientation_is_applied_and_reset(client, photo):
    im = Image.open(io.BytesIO(photo))
    exif = im.getexif()
    exif[0x0112] = 6  # rotate 90 on display
    r = mark(client, to_bytes(im, "JPEG", exif=exif.tobytes(), quality=90))
    out = Image.open(io.BytesIO(r.content))
    assert out.size == (533, 800)
    assert out.getexif().get(0x0112, 1) == 1


def test_remarking_reports_replaced_manifest(client, photo):
    first = mark(client, photo).content
    r = mark(client, first, response="json")
    assert r.json()["receipt"]["input"]["had_c2pa_manifest"] is True
    assert any("replaced" in n for n in r.json()["receipt"]["notes"])


def test_rejects_bad_input(client, photo, engine, monkeypatch):
    assert mark(client, b"").status_code == 422
    assert mark(client, photo, layers="c2pa,blockchain").json()["error"]["code"] == "invalid_layers"
    gif = to_bytes(Image.new("RGB", (32, 32)), "GIF")
    assert mark(client, gif, name="a.gif").status_code == 415
    assert mark(client, b"\xff\xd8\xff" + b"0" * 100).json()["error"]["code"] == "unreadable_image"
    monkeypatch.setattr(engine.settings, "max_megapixels", 0.1)
    r = mark(client, photo)
    assert r.status_code == 413 and r.json()["error"]["code"] == "image_too_large"


def test_parameter_errors_use_the_standard_shape(client, photo):
    r = mark(client, photo, kind="hand_drawn", quality="200")
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_request"
    assert {f["field"] for f in err["fields"]} == {"kind", "quality"}
    assert "kind:" in err["message"] and "quality:" in err["message"]
    r = client.post("/v1/mark")  # no file at all
    assert r.json()["error"]["fields"] == [{"field": "file", "message": "Field required"}]


def test_upload_size_limit(client, engine, monkeypatch):
    monkeypatch.setattr(engine.settings, "max_upload_mb", 1)
    r = mark(client, b"\xff\xd8\xff" + b"0" * (2**20 + 10))
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
