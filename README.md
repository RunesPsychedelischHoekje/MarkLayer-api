# MarkLayer API

Machine-readable marking for AI-generated images, built for EU AI Act Article 50(2) and California's
AI Transparency Act (SB 942). Built with FastAPI.

| Endpoint | What it does |
|---|---|
| `POST /v1/mark` | Adds three layers in one call: a signed **C2PA** manifest, an invisible **TrustMark** watermark, and the **IPTC** `DigitalSourceType`. Returns the image (or JSON with a receipt). |
| `POST /v1/inspect` / `GET /v1/inspect?url=` | Reports the provenance evidence in a file: C2PA validity, signer and trust list, watermark, IPTC fields, generator traces (A1111, Forge, ComfyUI, InvokeAI, NovelAI, Midjourney, EXIF names). Verdict plus label text in 10 EU languages. |
| `POST /v1/strip-check` | Re-encodes a marked image 9 ways (JPEG, WebP, social resize, screenshot, crop, grayscale...) and reports which layers survive. |

Why three layers: the EU Code of Practice on marking AI content (June 2026) expects at least two.
Metadata (C2PA, IPTC) is what platforms read, but any re-encode strips it. The watermark sits in the
pixels and survives. The C2PA manifest's soft binding points at the watermark, so the two stay linked.

All three are open standards. Adobe's official TrustMark library decodes our watermark, and any
C2PA verifier (e.g. contentcredentials.org/verify) reads our manifest.

## Run locally

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python scripts/fetch_assets.py    # watermark models (64 MB) + C2PA trust lists
.venv/Scripts/python -m pytest                  # 44 tests, no network needed after fetch_assets
.venv/Scripts/fastapi dev app/main.py           # docs at http://127.0.0.1:8000/docs
```

Without `SIGNING_CERT_PEM`/`SIGNING_KEY_PEM` the app signs with a throwaway identity that changes
on every restart. For production run `python scripts/make_signing_cert.py "Your Name"` once and put
the two PEM files in the host's environment variables (see `.env.example`).

## Deploy (Render)

`render.yaml` is a Blueprint: free plan for a test deploy (switch to Starter, $7/mo, before selling:
the free plan sleeps when idle), Frankfurt, models fetched at Docker build. Set
`RAPIDAPI_PROXY_SECRET`, `SIGNING_CERT_PEM` and `SIGNING_KEY_PEM` when Render asks.

Memory decides the plan. Measured peak RSS while marking (models alone ~215 MB):

| Image | Peak |
|---|---|
| 4.2 MP (2048²) | 375 MB |
| 8.4 MP | 480 MB |
| 16.8 MP (4096²) | 625 MB |

So Free or Starter (512 MB) run with `MAX_MEGAPIXELS=4.5`, one job at a time. Standard (2 GB) runs the
defaults (17 MP) with `MAX_CONCURRENT_JOBS=2`.

## How it works

- `app/services/watermark.py`: TrustMark variant Q on **onnxruntime** (Adobe's published ONNX models), no
  PyTorch. The residual is upscaled in row strips to keep memory flat. Detection requires decoder
  confidence ≥ 2.0 on top of error correction (otherwise ~1 in 10 unmarked photos "decodes").
  Our 61-bit payload = 15-bit MarkLayer tag + 1 bit (generated/edited) + 45 random bits.
- `app/services/c2pa_io.py`: signing and reading with `c2pa-python`. Reads are checked against the C2PA
  trust list and the (frozen) interim list separately, so inspect can say which one vouches for a signer.
- `app/services/metadata.py`: IPTC XMP writing/reading and generator fingerprints.
- `app/services/fetch.py`: URL download for inspect, with SSRF protection (public addresses only,
  every redirect re-checked).
- `app/vendor/trustmark/`: Adobe's BCH error-correction code (MIT).
- `spike/`: the feasibility tests and measurements behind these choices (`FINDINGS.md`).

## Known limits (v1)

- **Signer not on the C2PA trust list.** Signatures validate, but verifiers show "unrecognized signer"
  until the product passes the C2PA conformance programme and uses a certificate from a listed CA.
  `/health` reports `signer_trust_list` (null until then).
- **Images only for marking** (JPEG, PNG, WebP). Inspect reads C2PA in video, audio and PDF too, but
  watermark and metadata checks are image-only.
- **Watermark limits:** crops of more than ~10% per side, and very wide or tall images (aspect > 2:1),
  where only the centre square is marked. Brightness/contrast edits and grayscale lose it on ~1 in 10
  images (`spike/FINDINGS.md`). A determined attacker can remove any watermark.
- **Inspect is evidence, not detection.** "no_signals" means nothing was declared, not that a human
  made it.
- Not legal advice: MarkLayer supplies the technical layers, not a compliance certificate.

Data attribution: TrustMark models and ECC © Adobe, MIT licence. C2PA trust lists from the C2PA
conformance programme and contentcredentials.org.
