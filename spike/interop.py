"""Spike: official TrustMark (PyTorch) must decode what our ONNX port encodes, and vice versa."""
import secrets
import sys
from pathlib import Path

from PIL import Image
from trustmark import TrustMark

sys.path.insert(0, str(Path(__file__).parent))
from tm_onnx import TrustMarkOnnx  # noqa: E402

ref = TrustMark(verbose=False, model_type="Q", encoding_type=TrustMark.Encoding.BCH_5, loadRemover=False)
ours = TrustMarkOnnx()
ok_a = ok_b = 0
imgs = sorted((Path(__file__).parent / "images").glob("*.jpg"))
for p in imgs:
    im = Image.open(p).convert("RGB")
    bits = format(secrets.randbits(61), "061b")
    got, det, _ = ref.decode(ours.encode(im, bits), MODE="binary")
    ok_a += det and got == bits
    got, det, _ = ours.decode(ref.encode(im, bits, MODE="binary"))
    ok_b += det and got == bits
print(f"ours->official decode: {ok_a}/{len(imgs)}   official->ours decode: {ok_b}/{len(imgs)}")
