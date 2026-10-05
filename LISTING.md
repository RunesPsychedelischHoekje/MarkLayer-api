# RapidAPI listing copy for MarkLayer

Paste each block into the matching field on the RapidAPI **General** tab. Import `openapi.json`
on the **Definitions** tab (re-export it after code changes: see the end of this file).

## Name

```
MarkLayer: AI Image Watermark & C2PA Content Credentials (EU AI Act)
```

## Category

Primary: **Artificial Intelligence / Machine Learning** (where AI-app builders browse).
Alternative: **Media**. You can change it later without losing subscribers.

## Short description

```
Mark AI-generated images for the EU AI Act in one call: signed C2PA manifest, invisible watermark and IPTC AI label. Inspect any file's provenance.
```

## Tags

```
AI Act, C2PA, content credentials, watermark, invisible watermark, AI generated, deepfake, provenance, IPTC, TrustMark, SB 942, AI label, image, compliance, metadata
```

## Long description

(Markdown. Replace the host in the example with the one RapidAPI shows you.)

---

# MarkLayer: mark AI-generated images the way the EU AI Act asks

**Generative AI systems on the EU market must mark their output in a machine-readable way** (AI Act Article 50(2)): since August 2, 2026 for new systems, and from December 2, 2026 for systems already on the market. That includes apps built on someone else's model. The EU Code of Practice asks for **at least two layers**, such as signed metadata plus an invisible watermark, so labels survive when metadata is stripped. California's AI Transparency Act asks for the same kind of "latent disclosure".

MarkLayer does it in one API call, using open standards only:

| Layer | What it is | Why it matters |
|---|---|---|
| **C2PA Content Credentials** | A signed manifest: "created", `trainedAlgorithmicMedia`, your app's name | The standard the EU Code names as an example. Shown by LinkedIn, Google and others. |
| **Invisible watermark** (Adobe TrustMark) | A 61-bit ID hidden in the pixels | Survives JPEG compression, resizing, social uploads and screenshots, after the metadata is gone. |
| **IPTC `DigitalSourceType`** | XMP metadata field | What Meta and Google read to show "AI info" labels. |

**Open, not proprietary.** Anyone can verify the result: any C2PA verifier reads the manifest, and Adobe's open-source TrustMark library decodes the watermark. You aren't locked into us for detection.

## Endpoints

- **`POST /v1/mark`**: upload a JPEG, PNG or WebP and get it back marked (same format by default), plus a compliance receipt (hashes, layers applied, watermark ID) for your documentation.
- **`POST /v1/inspect`** (or `GET /v1/inspect?url=`): what provenance evidence does a file carry? It returns:
  - C2PA validity, signer, and whether the signer is on the C2PA trust list
  - watermark
  - IPTC fields
  - generator traces left by Stable Diffusion WebUI, Forge, ComfyUI, InvokeAI, NovelAI, Midjourney, Firefly and others

  You get a verdict (`ai_generated`, `ai_edited`, `captured` or `no_signals`) and **ready-made label text in 10 EU languages**. Reads C2PA in video, audio and PDF too.
- **`POST /v1/strip-check`**: see for yourself which layers survive 9 common edits.

## Example: mark

```bash
curl -X POST https://marklayer.p.rapidapi.com/v1/mark \
  -H "X-RapidAPI-Key: YOUR_KEY" -H "X-RapidAPI-Host: marklayer.p.rapidapi.com" \
  -F "file=@generated.png" -F "generator=Acme Image v2" -o marked.png
```

Response headers: `X-Watermark-Id: 1563503a649f`, `X-Layers: watermark,iptc,c2pa`, `X-Receipt-Id: ...`.
Add `-F response=json` to get the image in base64 together with the full receipt.

## Example: inspect

```json
{
  "verdict": "ai_generated",
  "strongest_evidence": "cryptographic",
  "summary": "Declared AI-generated, based on a signed C2PA manifest.",
  "label_suggestions": { "en": "AI-generated", "de": "KI-generiert", "fr": "Généré par IA", "nl": "Gegenereerd met AI" },
  "signals": [
    { "strength": "cryptographic", "source": "c2pa", "declares": "ai_generated", "generator": "Acme Image v2" },
    { "strength": "watermark", "source": "trustmark", "declares": "ai_generated", "detail": "MarkLayer watermark 1563503a649f" },
    { "strength": "metadata", "source": "xmp:Iptc4xmpExt:DigitalSourceType", "declares": "ai_generated" }
  ],
  "c2pa": { "present": true, "valid": true, "signer": { "issuer": "MarkLayer", "trusted": false }, "software_agents": ["Acme Image v2"] },
  "watermark": { "detected": true, "issuer": "MarkLayer", "watermark_id": "1563503a649f", "declares": "ai_generated" }
}
```

(Response shortened for display.)

## Quick start (Python)

```python
import requests

headers = {"X-RapidAPI-Key": "YOUR_KEY", "X-RapidAPI-Host": "marklayer.p.rapidapi.com"}
with open("generated.png", "rb") as f:
    r = requests.post("https://marklayer.p.rapidapi.com/v1/mark", headers=headers,
                      files={"file": f}, data={"generator": "Acme Image v2"})
r.raise_for_status()
open("marked.png", "wb").write(r.content)
print("watermark id:", r.headers["X-Watermark-Id"])
```

## Parameters for `/v1/mark`

| Field | Description |
|---|---|
| `file` | JPEG, PNG or WebP, up to 25 MB. Transparency is kept for PNG and WebP. |
| `kind` | `ai_generated` (default) or `ai_edited` (a real image changed with AI). |
| `generator` | Your AI system's name, recorded in the C2PA manifest and XMP. |
| `layers` | Comma list of `c2pa`, `watermark`, `iptc` (default all three). |
| `format` | `jpeg`, `png` or `webp` (default: same as input). |
| `quality` | JPEG/WebP quality 50-100 (default 92). |
| `response` | `image` (default) or `json`. |

## Measured robustness

Tested on 46 photos (watermark only, since every re-encode strips metadata on any service):

| Edit | Watermark recovered |
|---|---|
| Social upload (1080 px + JPEG 80) | 46/46 |
| JPEG quality 50 | 45/46 |
| Downscaled to 25% | 43/46 |
| Brightness +20% / grayscale | 41/46 |

No false detections on 138 unmarked image variants. Invisible to the eye: PSNR ~42 dB.

## Good to know

- **Technical marking, not legal advice.** MarkLayer supplies the layers the AI Act's Code of Practice describes. It doesn't certify your compliance.
- **Signer trust:** signatures are valid, but until MarkLayer completes the C2PA conformance programme, verifiers show the signer as "not recognised".
- **Image size:** up to 4.5 megapixels (covers 1024-2048 px generator output). Larger limits are coming.
- **Watermark limits:** heavy crops (more than ~10% per side) remove it. On images wider or taller than 2:1 only the centre square is marked. No watermark resists a determined attacker.
- **Inspect reports evidence, not guesses.** `no_signals` means nothing was declared, not that a human made the image.
- **Privacy:** files are processed in memory and never stored. Hosted in the EU (Frankfurt).

Questions or a format you need (audio, video)? Open a thread in the **Discussions** tab.

---

## Pricing (Monetize tab)

One quota for all endpoints. `/v1/mark` is the costly call (about 1 s of CPU at 4 MP).

| Plan | Price | Requests / month | Overage | Rate limit |
|---|---|---|---|---|
| Basic | Free | 50 | hard limit | 1 / s |
| Pro | $19 | 5,000 | $0.005 | 5 / s |
| Ultra | $79 | 30,000 | $0.003 | 10 / s |
| Mega | $249 | 150,000 | $0.002 | 20 / s |

For reference: Steg.AI starts around $0.10 per image; Imatag and Digimarc are sales-call only.

## Regenerating openapi.json

```bash
.venv/Scripts/python -c "import json; from app.main import app; open('openapi.json','w').write(json.dumps(app.openapi(), indent=2))"
```
