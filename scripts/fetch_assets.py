"""Download the watermark models and C2PA trust lists. Run once locally; the Dockerfile runs it at build.

    python scripts/fetch_assets.py

Models are checked against pinned SHA-256 hashes. Trust lists change over time, so they're not
pinned: re-run (or redeploy) to pick up newly added signers.
"""
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.watermark import MODEL_FILES, MODEL_URL  # noqa: E402

TRUST_LIST_URLS = {
    "C2PA-TRUST-LIST.pem": "https://raw.githubusercontent.com/c2pa-org/conformance-public/main/trust-list/C2PA-TRUST-LIST.pem",
    "ITL-anchors.pem": "https://contentcredentials.org/trust/anchors.pem",
}


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "MarkLayer-build"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def main() -> None:
    models = ROOT / "models"
    models.mkdir(exist_ok=True)
    for name, sha in MODEL_FILES.items():
        path = models / name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
            print(f"ok      {name}")
            continue
        data = get(MODEL_URL + name)
        if hashlib.sha256(data).hexdigest() != sha:
            sys.exit(f"checksum mismatch for {name}: refusing to install it")
        path.write_bytes(data)
        print(f"fetched {name} ({len(data) // 2**20} MB)")

    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    for name, url in TRUST_LIST_URLS.items():
        pem = get(url)
        if b"BEGIN CERTIFICATE" not in pem:
            sys.exit(f"{url} did not return PEM certificates")
        (data_dir / name).write_bytes(pem)
        print(f"fetched {name} ({pem.count(b'BEGIN CERTIFICATE')} anchors)")


if __name__ == "__main__":
    main()
