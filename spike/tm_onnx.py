"""TrustMark (variant Q) on onnxruntime, no PyTorch. Mirrors trustmark.py encode/decode."""
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from tm.datalayer import DataLayer

MODELS = Path(__file__).parent.parent / "models"
ENC_RES, DEC_RES = 256, 256  # the published ONNX decoder takes 256 (PyTorch uses 245)
ASPECT_RATIO_LIM = 2.0
FEATHER = 0.01


class TrustMarkOnnx:
    def __init__(self):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        self.enc = ort.InferenceSession(str(MODELS / "encoder_Q.onnx"), opts, providers=["CPUExecutionProvider"])
        self.dec = ort.InferenceSession(str(MODELS / "decoder_Q.onnx"), opts, providers=["CPUExecutionProvider"])
        self.ecc = DataLayer(100, verbose=False, encoding_mode=1)  # BCH_5: 61 payload bits

    @staticmethod
    def _region(w, h):
        ar = max(w, h) / min(w, h)
        if ar > ASPECT_RATIO_LIM:
            s = min(w, h)
            left, top = (w - s) // 2, (h - s) // 2
            return left, top, left + s, top + s
        return 0, 0, w, h

    @staticmethod
    def _to_tensor(im, res):
        a = np.asarray(im.resize((res, res), Image.BILINEAR), dtype=np.float32) / 255.0
        return (a.transpose(2, 0, 1)[None] * 2.0 - 1.0).astype(np.float32)

    def encode(self, image: Image.Image, bits: str, strength: float = 1.0) -> Image.Image:
        image = image.convert("RGB")
        secret = self.ecc.encode_binary([bits]).astype(np.float32)
        w, h = image.size
        left, top, right, bottom = self._region(w, h)
        crop = image.crop((left, top, right, bottom))
        cw, ch = crop.size
        cover = self._to_tensor(crop, ENC_RES)
        stego = self.enc.run(None, {self.enc.get_inputs()[0].name: cover, self.enc.get_inputs()[1].name: secret})[0]
        residual = np.clip(stego, -1, 1) - cover
        residual -= residual.mean(axis=(2, 3), keepdims=True)
        # Bilinear upsample of the residual, channel by channel, via PIL float images.
        up = np.stack(
            [np.asarray(Image.fromarray(residual[0, c]).resize((cw, ch), Image.BILINEAR)) for c in range(3)], axis=-1
        )
        patch = np.clip(up * strength + np.asarray(crop, dtype=np.float32) / 127.5 - 1.0, -1, 1) * 127.5 + 127.5
        orig = np.asarray(image).astype(np.float32)
        out = orig.copy()
        out[top:bottom, left:right] = patch
        fs = max(1, min(50, int(min(cw, ch) * FEATHER)))
        for i in range(fs):  # feather the patch edges into the original, as upstream does
            a = (i + 1) / fs
            out[top + i, left:right] = a * patch[i] + (1 - a) * orig[top + i, left:right]
            out[bottom - 1 - i, left:right] = a * patch[ch - 1 - i] + (1 - a) * orig[bottom - 1 - i, left:right]
            out[top:bottom, left + i] = a * patch[:, i] + (1 - a) * orig[top:bottom, left + i]
            out[top:bottom, right - 1 - i] = a * patch[:, cw - 1 - i] + (1 - a) * orig[top:bottom, right - 1 - i]
        return Image.fromarray(out.astype(np.uint8))

    def decode(self, image: Image.Image):
        image = image.convert("RGB")
        crop = image.crop(self._region(*image.size))
        logits = self.dec.run(None, {"image": self._to_tensor(crop, DEC_RES)})[0]
        bits = (logits > 0)
        payload, detected, version = self.ecc.decode_bitstream(bits, "binary")[0]
        return payload, detected, version
