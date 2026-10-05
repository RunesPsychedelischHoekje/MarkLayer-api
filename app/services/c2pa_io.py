"""C2PA Content Credentials: sign a manifest into a file, and read/validate one back.

LESSON: a C2PA manifest is a signed JSON-like record embedded in the file. It's bound to the exact
bytes by a hash, so ANY re-encode (a social upload, a screenshot) breaks or drops it. That's why
MarkLayer pairs it with a watermark in the pixels, and why the manifest carries a "soft binding"
pointing at that watermark.
"""
import datetime as dt
import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import c2pa
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from PIL import Image

log = logging.getLogger(__name__)

IPTC_DST = "http://cv.iptc.org/newscodes/digitalsourcetype/"
TRUST_LISTS = {
    # Official list for products that passed the C2PA conformance programme (2025+).
    "c2pa": "C2PA-TRUST-LIST.pem",
    # Interim list, frozen on 2026-01-01; most existing Adobe/OpenAI/Google credentials chain to it.
    "interim": "ITL-anchors.pem",
}


@dataclass
class SigningIdentity:
    cert_chain_pem: bytes
    key_pem: bytes
    issuer: str
    ephemeral: bool


def make_identity(org: str = "MarkLayer", days: int = 397) -> tuple[bytes, bytes, bytes]:
    """Create a CA + leaf ES256 chain. Returns (leaf+CA chain PEM, leaf key PEM, CA cert PEM).

    C2PA requires the leaf to be an end-entity cert (not self-signed) with a C2PA-allowed EKU.
    """
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{org} Root CA"),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, org)])
    ca = (
        x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=days * 5))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{org} Signer"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, org)])
    leaf = (
        x509.CertificateBuilder().subject_name(name).issuer_name(ca_name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    pem = lambda c: c.public_bytes(serialization.Encoding.PEM)  # noqa: E731
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    return pem(leaf) + pem(ca), key_pem, pem(ca)


def load_identity(cert_pem: str, key_pem: str) -> SigningIdentity:
    if cert_pem and key_pem:
        # Env vars often arrive with literal "\n" instead of newlines.
        cert_b = cert_pem.replace("\\n", "\n").encode()
        key_b = key_pem.replace("\\n", "\n").encode()
        leaf = x509.load_pem_x509_certificate(cert_b)
        issuer = leaf.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
        return SigningIdentity(cert_b, key_b, issuer[0].value if issuer else "unknown", ephemeral=False)
    log.warning("No SIGNING_CERT_PEM/SIGNING_KEY_PEM set: using a throwaway signing identity (dev only).")
    chain, key, _ = make_identity("MarkLayer (development)")
    return SigningIdentity(chain, key, "MarkLayer (development)", ephemeral=True)


class C2pa:
    def __init__(self, identity: SigningIdentity, tsa_url: str, data_dir: Path,
                 extra_anchors_pem: bytes | None = None):
        self.identity = identity
        self.tsa_url = tsa_url or None
        self._build_settings = c2pa.Settings.from_dict({"builder": {"thumbnail": {"enabled": False}}})
        # One reader context per trust list, so we can say WHICH list a signer is on.
        self._trust_contexts: dict[str, c2pa.Context] = {}
        for name, fname in TRUST_LISTS.items():
            path = data_dir / fname
            if path.exists():
                self._trust_contexts[name] = self._trust_context(path.read_text())
        if extra_anchors_pem:  # tests: trust our own CA
            self._trust_contexts["custom"] = self._trust_context(extra_anchors_pem.decode())
        self._plain = c2pa.Context()
        self.own_trust_list = self._own_trust_list()

    @staticmethod
    def _trust_context(anchors: str) -> "c2pa.Context":
        settings = c2pa.Settings.from_dict({"trust": {"trust_anchors": anchors}, "verify": {"verify_trust": True}})
        return c2pa.Context(settings=settings)

    def _own_trust_list(self) -> str | None:
        """Sign a tiny image once at startup to learn whether verifiers will trust our signer."""
        buf = io.BytesIO()
        Image.new("RGB", (8, 8)).save(buf, "JPEG")
        signed = self.sign(buf.getvalue(), "image/jpeg", digital_source_type="trainedAlgorithmicMedia",
                           generator=None, soft_binding=None, title="selftest.jpg")
        store = self.read(signed, "image/jpeg") or {}
        return store.get("_trusted_by")

    @property
    def trust_lists_loaded(self) -> list[str]:
        return sorted(self._trust_contexts)

    def sign(self, data: bytes, mime: str, *, digital_source_type: str, generator: str | None,
             soft_binding: str | None, title: str) -> bytes:
        action = {"action": "c2pa.created", "digitalSourceType": IPTC_DST + digital_source_type}
        if generator:
            action["softwareAgent"] = {"name": generator}
        manifest = {
            "claim_generator_info": [{"name": "MarkLayer", "version": "1"}],
            "title": title,
            "assertions": [{"label": "c2pa.actions.v2", "data": {"actions": [action]}}],
        }
        if soft_binding:  # points at the watermark, so the credential can be re-found after stripping
            manifest["assertions"].append({
                "label": "c2pa.soft-binding",
                "data": {"alg": "com.adobe.trustmark.Q", "blocks": [{"scope": {}, "value": soft_binding}]},
            })
        signer = c2pa.Signer.from_info(c2pa.C2paSignerInfo(
            c2pa.C2paSigningAlg.ES256, self.identity.cert_chain_pem, self.identity.key_pem, self.tsa_url))
        with c2pa.Builder(json.dumps(manifest), context=c2pa.Context(settings=self._build_settings)) as builder:
            dst = io.BytesIO()
            builder.sign(signer, mime, io.BytesIO(data), dst)
        return dst.getvalue()

    def read(self, data: bytes, mime: str) -> dict | None:
        """Parsed manifest store plus which trust list (if any) vouches for the active signer."""
        try:
            reader = c2pa.Reader.try_create(mime, io.BytesIO(data), None, self._plain)
        except c2pa.C2paError as exc:
            return {"error": str(exc)}
        if reader is None:
            return None
        with reader:
            store = json.loads(reader.json())
        store["_trusted_by"] = None
        for name, ctx in self._trust_contexts.items():
            try:
                r = c2pa.Reader.try_create(mime, io.BytesIO(data), None, ctx)
            except c2pa.C2paError:
                continue
            if r is not None:
                with r:
                    if r.get_validation_state() == "Trusted":
                        store = json.loads(r.json())  # its validation_status no longer says "untrusted"
                        store["_trusted_by"] = name
                        break
        return store
