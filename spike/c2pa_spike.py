"""Spike: sign a watermarked image with a C2PA manifest (AI-generated + TrustMark soft binding), read it back."""
import datetime as dt
import io
import json
import secrets
import sys
from pathlib import Path

import c2pa
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from tm_onnx import TrustMarkOnnx  # noqa: E402


def make_chain():
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MarkLayer Spike CA"),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MarkLayer")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + dt.timedelta(days=3650))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MarkLayer Signer"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MarkLayer")])
    leaf = (x509.CertificateBuilder().subject_name(name).issuer_name(ca_name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    pem = lambda c: c.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return pem(leaf) + pem(ca), key_pem


chain, key_pem = make_chain()
signer = c2pa.Signer.from_info(c2pa.C2paSignerInfo(c2pa.C2paSigningAlg.ES256, chain, key_pem, None))

tm = TrustMarkOnnx()
src = Image.open(Path(__file__).parent / "images" / "p10.jpg").convert("RGB")
bits = format(secrets.randbits(61), "061b")
marked = tm.encode(src, bits)
buf = io.BytesIO()
marked.save(buf, "JPEG", quality=92)

manifest = {
    "claim_generator_info": [{"name": "MarkLayer", "version": "0.0.1"}],
    "title": "generated.jpg",
    "assertions": [
        {"label": "c2pa.soft-binding",
         "data": {"alg": "com.adobe.trustmark.Q", "blocks": [{"scope": {}, "value": f"1*{bits}"}]}},
    ],
}
builder = c2pa.Builder(json.dumps(manifest))
builder.set_intent(c2pa.C2paBuilderIntent.CREATE, c2pa.C2paDigitalSourceType.TRAINED_ALGORITHMIC_MEDIA)
dst = io.BytesIO()
buf.seek(0)
builder.sign(signer, "image/jpeg", buf, dst)
out = dst.getvalue()
(Path(__file__).parent / "out" / "signed.jpg").write_bytes(out)
print("signed bytes:", len(out), "vs unsigned", len(buf.getvalue()))

reader = c2pa.Reader("image/jpeg", io.BytesIO(out))
store = json.loads(reader.json())
active = store["manifests"][store["active_manifest"]]
print("validation_state:", reader.get_validation_state())
print("validation_status:", json.dumps(store.get("validation_status"), indent=1)[:800])
print("assertions:", [a["label"] for a in active["assertions"]])
print(json.dumps([a for a in active["assertions"] if a["label"].startswith("c2pa.actions")], indent=1)[:800])
print("signature_info:", active.get("signature_info"))
print("watermark still decodes after signing:", tm.decode(Image.open(io.BytesIO(out))))
