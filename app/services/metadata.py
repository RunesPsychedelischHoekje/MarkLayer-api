"""Plain (unsigned) metadata: IPTC digital source type in XMP, and generator traces left by AI tools.

LESSON: unlike C2PA, this metadata isn't signed, so anyone can add or strip it. It still matters:
Meta, Google and others read IPTC `DigitalSourceType` to show "AI info" labels, and many local
generators (Stable Diffusion WebUI, ComfyUI...) write their settings into PNG text chunks.
Inspect reports it as evidence of strength "metadata", weaker than a signature or watermark.
"""
import json
import re
from dataclasses import dataclass

from PIL import Image, PngImagePlugin

IPTC_DST = "http://cv.iptc.org/newscodes/digitalsourcetype/"
XMP_TEMPLATE = (
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about="" xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" '
    'xmlns:xmp="http://ns.adobe.com/xap/1.0/" Iptc4xmpExt:DigitalSourceType="{dst}"{tool}/>'
    '</rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
)

# IPTC digital source types that mean "AI made this" or "AI changed this".
AI_GENERATED_DST = {"trainedAlgorithmicMedia"}
AI_EDITED_DST = {"compositeWithTrainedAlgorithmicMedia"}

_XMP_PACKET = re.compile(rb"<x:xmpmeta.*?</x:xmpmeta>", re.S)
_DST = re.compile(r"DigitalSourceType(?:=\"|>)\s*(?:<rdf:li>)?\s*([^\"<\s]+)")
_CREATOR_TOOL = re.compile(r"CreatorTool(?:=\"|>)([^\"<]+)")
_MJ_JOB = re.compile(r"Job ID:\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

# Names that, found in a Software/CreatorTool field, identify an AI generator.
KNOWN_GENERATORS = [
    ("midjourney", "Midjourney"), ("dall-e", "OpenAI DALL-E"), ("dall·e", "OpenAI DALL-E"),
    ("chatgpt", "OpenAI ChatGPT"), ("gpt-4o", "OpenAI GPT-4o"), ("firefly", "Adobe Firefly"),
    ("imagen", "Google Imagen"), ("gemini", "Google Gemini"), ("stable diffusion", "Stable Diffusion"),
    ("stablediffusion", "Stable Diffusion"), ("comfyui", "ComfyUI"), ("novelai", "NovelAI"),
    ("leonardo", "Leonardo.Ai"), ("ideogram", "Ideogram"), ("flux", "Black Forest Labs FLUX"),
    ("grok", "xAI Grok"), ("runway", "Runway"), ("invokeai", "InvokeAI"), ("fooocus", "Fooocus"),
    ("bing image creator", "Microsoft Designer / Bing Image Creator"),
]


@dataclass
class Signal:
    source: str          # where we found it, e.g. "png:parameters"
    generator: str | None
    kind: str            # ai_generated | ai_edited | other
    detail: str


def xmp_packet(digital_source_type: str, generator: str | None) -> bytes:
    tool = f' xmp:CreatorTool="{_xml_escape(generator)}"' if generator else ""
    return XMP_TEMPLATE.format(dst=IPTC_DST + digital_source_type, tool=tool).encode("utf-8")


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def png_info_with_xmp(src_info: dict, xmp: bytes | None) -> PngImagePlugin.PngInfo:
    """Keep the source PNG's text chunks (except old XMP), and add ours."""
    info = PngImagePlugin.PngInfo()
    for k, v in src_info.items():
        if isinstance(v, str) and k != "XML:com.adobe.xmp":
            info.add_text(k, v)
    if xmp:
        info.add_itxt("XML:com.adobe.xmp", xmp.decode("utf-8"))
    return info


def read_xmp(data: bytes) -> str | None:
    m = _XMP_PACKET.search(data)
    return m.group(0).decode("utf-8", "replace") if m else None


def dst_kind(dst_value: str) -> str:
    term = dst_value.rstrip("/").rsplit("/", 1)[-1]
    if term in AI_GENERATED_DST:
        return "ai_generated"
    if term in AI_EDITED_DST:
        return "ai_edited"
    return "other"


def iptc_signals(data: bytes) -> tuple[str | None, list[Signal]]:
    """Returns (IPTC digital source type or None, signals)."""
    xmp = read_xmp(data)
    if not xmp:
        return None, []
    signals = []
    dst = None
    if m := _DST.search(xmp):
        dst = m.group(1)
        signals.append(Signal("xmp:Iptc4xmpExt:DigitalSourceType", None, dst_kind(dst), dst))
    if m := _CREATOR_TOOL.search(xmp):
        if gen := _match_generator(m.group(1)):
            signals.append(Signal("xmp:CreatorTool", gen, "ai_generated", m.group(1)[:200]))
    if m := _MJ_JOB.search(xmp):
        signals.append(Signal("xmp:Description", "Midjourney", "ai_generated", m.group(0)))
    return dst, signals


_GENERATOR_RES = [(re.compile(r"\b" + re.escape(n) + r"\b", re.I), name) for n, name in KNOWN_GENERATORS]


def _match_generator(text: str) -> str | None:
    # Whole words only: "Imagenomic" must not read as Google Imagen.
    for rx, name in _GENERATOR_RES:
        if rx.search(text):
            return name
    return None


def generator_signals(im: Image.Image) -> list[Signal]:
    """Traces that AI tools leave in PNG text chunks and EXIF fields."""
    out: list[Signal] = []
    info = {k: v for k, v in (im.info or {}).items() if isinstance(v, str)}

    if (p := info.get("parameters")) and ("Steps:" in p or "Sampler:" in p):
        gen = "Stable Diffusion WebUI Forge" if "Version: f" in p else "Stable Diffusion WebUI (AUTOMATIC1111 or compatible)"
        if "Fooocus" in p:
            gen = "Fooocus"
        out.append(Signal("png:parameters", gen, "ai_generated", _excerpt(p)))
    elif p and _looks_json(p) and "fooocus" in p.lower():
        out.append(Signal("png:parameters", "Fooocus", "ai_generated", _excerpt(p)))
    if "workflow" in info or ("prompt" in info and "class_type" in info["prompt"]):
        out.append(Signal("png:prompt/workflow", "ComfyUI", "ai_generated", "ComfyUI graph embedded"))
    if "invokeai_metadata" in info or "sd-metadata" in info:
        out.append(Signal("png:invokeai_metadata", "InvokeAI", "ai_generated", "InvokeAI generation metadata"))
    if info.get("Software", "").strip().lower() == "novelai" or ("Comment" in info and '"uc"' in info["Comment"]):
        out.append(Signal("png:Software/Comment", "NovelAI", "ai_generated", "NovelAI generation metadata"))
    if "Dream" in info:
        out.append(Signal("png:Dream", "Stable Diffusion (dream.py)", "ai_generated", _excerpt(info["Dream"])))

    try:
        exif = im.getexif()
    except Exception:
        exif = {}
    for tag, label in ((0x0131, "exif:Software"), (0x010E, "exif:ImageDescription")):
        val = exif.get(tag) if exif else None
        if isinstance(val, bytes):
            val = val.decode("utf-8", "replace")
        if isinstance(val, str) and (gen := _match_generator(val)):
            out.append(Signal(label, gen, "ai_generated", val[:200]))
    if (sw := info.get("Software")) and (gen := _match_generator(sw)) and gen != "NovelAI":
        out.append(Signal("png:Software", gen, "ai_generated", sw[:200]))
    return out


def _looks_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except ValueError:
        return False


def _excerpt(s: str, n: int = 160) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "..."
