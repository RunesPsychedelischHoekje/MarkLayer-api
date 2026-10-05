"""Create MarkLayer's persistent C2PA signing identity (a private CA + an ES256 signing certificate).

    python scripts/make_signing_cert.py "Your Company Name"

Writes to ./secrets/ (git-ignored). Paste signer-chain.pem into Render's SIGNING_CERT_PEM and
signer-key.pem into SIGNING_KEY_PEM. The CA's private key is never saved: when the signing
certificate expires (397 days), move secrets/ aside and run this again for a fresh identity.
Manifests signed earlier stay valid because each signature carries a trusted timestamp (TSA_URL).

Verifiers will show this signer as "untrusted" (valid signature, not on the C2PA trust list).
Becoming trusted means passing the C2PA conformance programme and buying a certificate from a CA
on the C2PA trust list; then put that certificate and key in the same two variables.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.c2pa_io import make_identity  # noqa: E402


def main() -> None:
    org = sys.argv[1] if len(sys.argv) > 1 else "MarkLayer"
    out = ROOT / "secrets"
    out.mkdir(exist_ok=True)
    chain, key, ca = make_identity(org)
    for name, data in (("signer-chain.pem", chain), ("signer-key.pem", key), ("ca-cert.pem", ca)):
        if (out / name).exists():
            sys.exit(f"secrets/{name} already exists: move it away first, I won't overwrite a signing identity.")
        (out / name).write_bytes(data)
    print(f"Wrote secrets/signer-chain.pem, secrets/signer-key.pem, secrets/ca-cert.pem for '{org}'.")
    print("Set SIGNING_CERT_PEM and SIGNING_KEY_PEM on your host to the contents of the first two files.")


if __name__ == "__main__":
    main()
