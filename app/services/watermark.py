"""Invisible watermark: Adobe TrustMark (variant Q), run on onnxruntime instead of PyTorch.

LESSON: TrustMark's neural encoder only ever sees a 256x256 copy of the image. It returns a
watermarked 256x256 version; the *difference* (the residual) is scaled back up to full size and
added to the original pixels. That's why big images cost little extra model time: the expensive
part is fixed-size, only the upscale-and-add grows with the image. We upscale in row strips so a
40 MP image never needs a full-size float copy in memory.

Interoperable by design: these are Adobe's published models and payload format, so the official
TrustMark library (Python, Rust, JS) decodes our marks and we decode theirs.
"""
import secrets
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from app.vendor.trustmark.datalayer import DataLayer

ALG = "com.adobe.trustmark.Q"
SCHEMA = 1  # BCH_5: 61 payload bits, corrects up to 5 flipped bits
PAYLOAD_BITS = 61
RES = 256
ASPECT_RATIO_LIM = 2.0  # wider/taller than 2:1 -> watermark only the centre square (upstream behaviour)
FEATHER = 0.01
MIN_CONFIDENCE = 2.0  # mean |decoder logit|; see detect()
STRIP_ROWS = 128

# Our payload layout: 15-bit MarkLayer tag | 1 bit kind | 45 random bits.
# The tag lets /v1/inspect recognise our own marks without a database (1 in 32768 chance that a
# random third-party TrustMark ID carries it). The kind bit survives even when metadata is stripped.
TAG = 0b101101001101001
TAG_BITS, KIND_BITS, ID_BITS = 15, 1, 45
KINDS = ("ai_generated", "ai_edited")

MODEL_FILES = {
    "encoder_Q.onnx": "19b3d1b25836130ffd78775a8f61539f993375d1823ef0e59ba5b8dffb4f892d",
    "decoder_Q.onnx": "ee3268f057c9dabef680e169302f5973d0589feea86189ed229a896cc3aa88df",
}
MODEL_URL = "https://cai-watermark.adobe.net/watermarking/trustmark-models/"


@dataclass
class Decoded:
    bits: str
    ours: bool
    kind: str | None
    watermark_id: str | None


def new_payload(kind: str) -> tuple[str, str]:
    """Return (61-bit string, public id). The random part is never zero (all-zero is undetectable)."""
    rand = secrets.randbits(ID_BITS) or 1
    bits = format(TAG, f"0{TAG_BITS}b") + str(KINDS.index(kind)) + format(rand, f"0{ID_BITS}b")
    return bits, format(rand, "012x")


def parse_payload(bits: str) -> Decoded:
    if len(bits) == PAYLOAD_BITS and int(bits[:TAG_BITS], 2) == TAG:
        rand = int(bits[TAG_BITS + KIND_BITS:], 2)
        return Decoded(bits, True, KINDS[int(bits[TAG_BITS])], format(rand, "012x"))
    return Decoded(bits, False, None, None)


def _region(w: int, h: int) -> tuple[int, int, int, int]:
    if max(w, h) / min(w, h) > ASPECT_RATIO_LIM:
        s = min(w, h)
        left, top = (w - s) // 2, (h - s) // 2
        return left, top, left + s, top + s
    return 0, 0, w, h


def _to_tensor(im: Image.Image) -> np.ndarray:
    a = np.asarray(im.resize((RES, RES), Image.BILINEAR), dtype=np.float32) / 255.0
    return (a.transpose(2, 0, 1)[None] * 2.0 - 1.0).astype(np.float32)


def _interp_weights(n_out: int, n_in: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bilinear sample positions, matching torch.interpolate(mode='bilinear', align_corners=False)."""
    src = np.clip((np.arange(n_out, dtype=np.float32) + 0.5) * (n_in / n_out) - 0.5, 0, n_in - 1)
    i0 = np.floor(src).astype(np.int64)
    i1 = np.minimum(i0 + 1, n_in - 1)
    return i0, i1, (src - i0).astype(np.float32)


class Watermarker:
    def __init__(self, model_dir: Path):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        providers = ["CPUExecutionProvider"]
        self._enc = ort.InferenceSession(str(model_dir / "encoder_Q.onnx"), opts, providers=providers)
        self._dec = ort.InferenceSession(str(model_dir / "decoder_Q.onnx"), opts, providers=providers)
        self._enc_in = [i.name for i in self._enc.get_inputs()]
        self._ecc = DataLayer(100, verbose=False, encoding_mode=SCHEMA)

    def embed(self, image: Image.Image, bits: str, strength: float = 1.0) -> Image.Image:
        """Return an RGB copy of `image` carrying `bits` (61 chars of 0/1)."""
        if image.mode != "RGB":
            image = image.convert("RGB")
        left, top, right, bottom = _region(*image.size)
        crop = image.crop((left, top, right, bottom))
        cw, ch = crop.size
        cover = _to_tensor(crop)
        secret = self._ecc.encode_binary([bits]).astype(np.float32)
        stego = self._enc.run(None, {self._enc_in[0]: cover, self._enc_in[1]: secret})[0]
        residual = np.clip(stego, -1, 1) - cover
        residual = (residual - residual.mean(axis=(2, 3), keepdims=True))[0].transpose(1, 2, 0)  # (256,256,3)

        out = np.array(image, dtype=np.uint8)  # writable copy
        x0, x1, xw = _interp_weights(cw, RES)
        y0, y1, yw = _interp_weights(ch, RES)
        rows_h = residual[:, x0] * (1 - xw)[None, :, None] + residual[:, x1] * xw[None, :, None]  # (256, cw, 3)
        fs = max(1, min(50, int(min(cw, ch) * FEATHER)))
        ramp = (np.arange(fs, dtype=np.float32) + 1) / fs
        alpha_x = np.ones(cw, dtype=np.float32)
        alpha_x[:fs] = np.minimum(alpha_x[:fs], ramp)
        alpha_x[cw - fs:] = np.minimum(alpha_x[cw - fs:], ramp[::-1])
        for s in range(0, ch, STRIP_ROWS):
            e = min(ch, s + STRIP_ROWS)
            wy = yw[s:e, None, None]
            res = rows_h[y0[s:e]] * (1 - wy) + rows_h[y1[s:e]] * wy  # (strip, cw, 3)
            orig = out[top + s: top + e, left:right].astype(np.float32)
            patch = np.clip(res * strength + orig / 127.5 - 1.0, -1, 1) * 127.5 + 127.5
            # Feather the patch edges into the original so no seam shows (alpha 0..1 over ~1% of the side).
            ay = np.ones(e - s, dtype=np.float32)
            rows = np.arange(s, e)
            ay = np.minimum(ay, np.where(rows < fs, (rows + 1) / fs, 1))
            ay = np.minimum(ay, np.where(rows >= ch - fs, (ch - rows) / fs, 1))
            a = np.minimum(ay[:, None], alpha_x[None, :])[..., None]
            blended = a * patch + (1 - a) * orig
            out[top + s: top + e, left:right] = np.clip(blended, 0, 255).astype(np.uint8)
        return Image.fromarray(out)

    def detect(self, image: Image.Image) -> Decoded | None:
        """Decode a TrustMark watermark, or None when there is none (or it's damaged beyond repair)."""
        if image.mode != "RGB":
            image = image.convert("RGB")
        crop = image.crop(_region(*image.size))
        logits = self._dec.run(None, {"image": _to_tensor(crop)})[0]
        # Error correction alone lets ~1 in 10 unmarked photos "decode" (random bits that happen to
        # pass the weakest schema). The decoder's confidence separates the two cleanly: mean |logit|
        # stayed under 0.61 on unmarked photos and over 5.3 on marked ones, even after JPEG 50,
        # 25% downscale and grayscale (spike/FINDINGS.md).
        if float(np.abs(logits).mean()) < MIN_CONFIDENCE:
            return None
        raw = logits > 0
        bits, detected, _version = self._ecc.decode_bitstream(raw, "binary")[0]
        if detected:
            return parse_payload(bits)
        # The 4 version bits have no error correction: if they flipped, retry as our own schema and
        # accept only if the MarkLayer tag comes out.
        forced = raw.copy()
        forced[0, -4:] = [int(b) for b in format(SCHEMA, "04b")]
        bits, detected, _version = self._ecc.decode_bitstream(forced, "binary")[0]
        if detected and (d := parse_payload(bits)).ours:
            return d
        return None
