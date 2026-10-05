# Spike findings (2026-10-05)

Question: can MarkLayer do C2PA + TrustMark + IPTC marking on a small server, without PyTorch, and is the watermark robust?

## TrustMark on onnxruntime (`tm_onnx.py`)
- Adobe publishes ONNX models: `https://cai-watermark.adobe.net/watermarking/trustmark-models/{encoder,decoder}_Q.onnx`
  (17 MB + 47 MB). The ONNX decoder takes 256x256 input (the PyTorch one uses 245).
- ECC (`datalayer.py`, `bchecc.py`) is pure numpy, MIT licensed; vendored. BCH_5 = 61 payload bits.
- **Interop: 8/8 both ways.** Official PyTorch TrustMark decodes our ONNX marks and we decode theirs.
- **An all-zero payload is never reported as detected.** Always use random IDs.

## Robustness (8 photos, 800x2000 to 1600x1067, variant Q, strength 1.0)
PSNR 42.4 dB mean (min 39.3). No false positives on the 8 unmarked originals.

| Edit | Survived |
|---|---|
| none, JPEG 90/75/50, WebP 80, scale 50%/25%, 1080w + JPEG 80, grayscale, 75% screenshot | 8/8 |
| brightness +20%, contrast +20% | 7/8 |
| crop 5% each side | 8/8 |
| crop 15% each side | **0/8** (known TrustMark limit without its localisation model) |

## C2PA (`c2pa_spike.py`, c2pa-python 0.38)
- Signing with our own ES256 CA + leaf chain works. `validation_state: Valid`, status `signingCredential.untrusted`
  (expected: not on the C2PA trust list). `set_intent(CREATE, TRAINED_ALGORITHMIC_MEDIA)` writes the
  `c2pa.created` action with the IPTC digital source type.
- Soft-binding assertion `{"alg": "com.adobe.trustmark.Q", "blocks": [{"scope": {}, "value": "1*<bits>"}]}`
  (same shape as Adobe's example). Watermark still decodes after signing.
- Signing added ~140 KB to a 450 KB JPEG (includes a thumbnail).

## IPTC XMP
Pillow writes XMP for JPEG and WebP via `save(xmp=...)`. PNG needs an iTXt `XML:com.adobe.xmp` chunk.

## Speed and memory (Windows laptop, 1 ORT thread)
- Models loaded: ~185 MB RSS. Encode ~340 ms, decode ~120 ms for 1600 px images.
- Naive full-frame float math: 6000x4000 peaks at ~490 MB, 8192² at ~830 MB. Too close to Render's 512 MB, so
  the app upsamples the residual in row strips and caps input megapixels.

## False positives (found by the test suite) and the confidence gate
BCH error correction alone accepted random bits on **3 of 27** unmarked variants (all as schema 3, the
weakest). The decoder's mean |logit| separates cleanly: unmarked max 0.61, marked min 5.3. The app now
requires mean |logit| >= 2.0, and retries as schema 1 when the uncorrected version bits flipped
(accepting only if the MarkLayer tag decodes). `fp_check.py` on 46 photos (38 more from picsum):

| | Result |
|---|---|
| False positives (unmarked, as-is / JPEG 60 / half size) | **0/138** |
| Marked, as-is | 46/46 |
| JPEG 50 | 45/46 |
| 1080 px + JPEG 80 (social) | 46/46 |
| 25% downscale | 43/46 |
| brightness +20% | 41/46 |
| grayscale | 41/46 |
