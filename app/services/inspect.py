"""POST /v1/inspect: which provenance signals does a file carry, and what do they declare?

This is NOT a pixel classifier guessing "looks AI". It reports evidence that is actually present:
signed C2PA manifests, invisible watermarks, IPTC metadata, and generator traces. No signals means
"nothing declared", not "human-made".
"""
from app.errors import ApiError
from app.services import metadata
from app.services.c2pa_io import C2pa
from app.services.media import MIME, open_image
from app.services.watermark import Watermarker

IMAGE_FORMATS = {"jpeg", "png", "webp", "gif", "tiff"}  # what Pillow decodes for watermark/metadata checks

# Strongest evidence first.
STRENGTH_ORDER = ("cryptographic", "watermark", "metadata")

LABELS = {
    "ai_generated": {
        "en": "AI-generated", "nl": "Gegenereerd met AI", "fr": "Généré par IA", "de": "KI-generiert",
        "es": "Generado con IA", "it": "Generato con IA", "pt": "Gerado por IA",
        "pl": "Wygenerowane przez AI", "sv": "AI-genererad", "da": "AI-genereret",
    },
    "ai_edited": {
        "en": "Edited with AI", "nl": "Bewerkt met AI", "fr": "Modifié avec l'IA", "de": "Mit KI bearbeitet",
        "es": "Editado con IA", "it": "Modificato con IA", "pt": "Editado com IA",
        "pl": "Edytowane przez AI", "sv": "Redigerad med AI", "da": "Redigeret med AI",
    },
}


def inspect(data: bytes, fmt: str, *, wm: Watermarker, reader: C2pa, max_megapixels: float) -> dict:
    signals: list[dict] = []
    c2pa_section = _c2pa_section(reader.read(data, MIME[fmt]), signals)

    watermark_section = None
    iptc_section = None
    generators: list[dict] = []
    image_info = None
    skipped = None
    im = None
    if fmt in IMAGE_FORMATS:
        try:
            im = open_image(data, max_megapixels)
        except ApiError as exc:  # still worth returning the C2PA result
            skipped = exc.message
    if im is not None:
        image_info = {"width": im.width, "height": im.height}
        frame = im.convert("RGB")
        found = wm.detect(frame)
        watermark_section = {"algorithm": "com.adobe.trustmark.Q", "detected": found is not None}
        if found:
            watermark_section.update({"issuer": "MarkLayer" if found.ours else "unknown (third-party TrustMark)",
                                      "watermark_id": found.watermark_id, "payload_bits": found.bits})
            if found.ours:
                watermark_section["declares"] = found.kind
                signals.append(_sig("watermark", "trustmark", found.kind, None,
                                    f"MarkLayer watermark {found.watermark_id}"))
            else:
                # Adobe and others use TrustMark to re-find Content Credentials for ANY image, AI or not.
                signals.append(_sig("watermark", "trustmark", "other", None,
                                    "TrustMark watermark: look up its C2PA manifest by the payload"))
        dst, iptc = metadata.iptc_signals(data)
        iptc_section = {"digital_source_type": dst}
        gen = metadata.generator_signals(im)
        for s in iptc + gen:
            signals.append(_sig("metadata", s.source, s.kind, s.generator, s.detail))
            if s.generator:
                generators.append({"name": s.generator, "source": s.source})

    ai = [s for s in signals if s["declares"] in ("ai_generated", "ai_edited")]
    if any(s["declares"] == "ai_generated" for s in ai):
        verdict = "ai_generated"
    elif ai:
        verdict = "ai_edited"
    elif c2pa_section.get("capture"):
        verdict = "captured"
    else:
        verdict = "no_signals"
    basis = next((st for st in STRENGTH_ORDER if any(s["strength"] == st for s in ai)), None) if ai else None

    return {
        "verdict": verdict,
        "ai_declared": bool(ai),
        "strongest_evidence": basis,
        "summary": _summary(verdict, basis, c2pa_section),
        "label_suggestions": LABELS.get(verdict),
        "signals": signals,
        "c2pa": c2pa_section,
        "watermark": watermark_section,
        "iptc": iptc_section,
        "generators": _dedupe(generators),
        "file": {"format": fmt, "mime": MIME[fmt], "bytes": len(data), "image": image_info,
                 "checks": ["c2pa"] + (["watermark", "iptc", "generator_metadata"] if im is not None else []),
                 "image_checks_skipped": skipped},
    }


def _sig(strength: str, source: str, declares: str, generator: str | None, detail: str) -> dict:
    return {"strength": strength, "source": source, "declares": declares, "generator": generator, "detail": detail}


def _c2pa_section(store: dict | None, signals: list[dict]) -> dict:
    if store is None:
        return {"present": False}
    if "error" in store:
        return {"present": True, "valid": False, "error": store["error"]}
    manifests = store.get("manifests", {})
    active = manifests.get(store.get("active_manifest"), {})
    status = [v.get("code") for v in store.get("validation_status", []) or []]
    state = store.get("validation_state")
    valid = state in ("Valid", "Trusted")
    trusted_by = store.get("_trusted_by")
    sig = active.get("signature_info") or {}

    # Walk every manifest in the chain: an edited photo whose ingredient was AI-generated still counts.
    dsts, agents, actions = [], [], []
    for label, m in manifests.items():
        for a in m.get("assertions", []):
            if not a.get("label", "").startswith("c2pa.actions"):
                continue
            for act in a.get("data", {}).get("actions", []):
                actions.append({"manifest": "active" if label == store.get("active_manifest") else "ingredient",
                                "action": act.get("action"), "digital_source_type": act.get("digitalSourceType")})
                if d := act.get("digitalSourceType"):
                    dsts.append(d)
                agent = act.get("softwareAgent")
                if isinstance(agent, dict):
                    agent = agent.get("name")
                if agent:
                    agents.append(agent)
    soft = [
        {"alg": a["data"].get("alg"), "value": b.get("value")}
        for a in active.get("assertions", []) if a.get("label", "").startswith("c2pa.soft-binding")
        for b in a.get("data", {}).get("blocks", [])
    ]
    generator_info = [g.get("name") for g in active.get("claim_generator_info", []) if g.get("name")]
    capture = any(d.rsplit("/", 1)[-1] in ("digitalCapture", "computationalCapture") for d in dsts)

    if valid:
        kinds = {metadata.dst_kind(d) for d in dsts}
        kind = "ai_generated" if "ai_generated" in kinds else "ai_edited" if "ai_edited" in kinds else "other"
        if kind != "other":
            signals.append(_sig("cryptographic", "c2pa", kind, agents[0] if agents else None,
                                f"Signed by {sig.get('issuer') or 'unknown'}"
                                f"{' (on the ' + trusted_by + ' trust list)' if trusted_by else ' (signer not on a trust list)'}"))

    return {
        "present": True,
        "valid": valid,
        "validation_state": state,
        "signer": {"issuer": sig.get("issuer"), "common_name": sig.get("common_name"), "signed_at": sig.get("time"),
                   "trusted": trusted_by is not None, "trust_list": trusted_by},
        "claim_generator": generator_info or active.get("claim_generator"),
        "digital_source_types": sorted(set(dsts)),
        "software_agents": sorted(set(agents)),
        "actions": actions,
        "soft_bindings": soft,
        "manifest_count": len(manifests),
        "validation_codes": status,
        "capture": capture and valid,
    }


def _summary(verdict: str, basis: str | None, c2pa_section: dict) -> str:
    if verdict in ("ai_generated", "ai_edited"):
        what = "AI-generated" if verdict == "ai_generated" else "edited with AI"
        how = {"cryptographic": "a signed C2PA manifest", "watermark": "an invisible watermark",
               "metadata": "unsigned metadata (easy to add or remove)"}[basis]
        return f"Declared {what}, based on {how}."
    if verdict == "captured":
        return "A valid C2PA manifest declares a camera capture, and no AI signals were found."
    if c2pa_section.get("present") and not c2pa_section.get("valid"):
        return "A C2PA manifest is present but failed validation; no other AI signals were found."
    return "No provenance signals found. This does not mean the content is human-made: metadata is often stripped."


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for i in items:
        if i["name"] not in seen:
            seen.add(i["name"])
            out.append(i)
    return out
