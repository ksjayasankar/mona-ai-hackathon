"""Deterministic document forensics for the Persowerk fraud agent — the high-ROI,
explainable layer. NO LLM, NO DB, NO network: every Signal is reproducible from the
bytes. pikepdf is not installed, so incremental-update detection reads the raw bytes
(extra %%EOF / xref generations = save history). ELA is LABELLED weak and capped — a
hint to look closer, never proof.

`Signal` is the shared primitive for the whole agent (forensics, consistency,
verification): {name, severity, category, evidence, why, weak, detail}.
"""
from __future__ import annotations

import base64
import io
import re
from datetime import date, datetime

from pydantic import BaseModel, Field

TODAY = date(2026, 6, 20)

# editor/producer fingerprints -> (severity, human label). Lower-cased substring match.
_EDITOR_FINGERPRINTS = [
    ("photoshop", "high", "Adobe Photoshop (image editor) in a document toolchain"),
    ("gimp", "high", "GIMP (image editor)"),
    ("snapseed", "high", "Snapseed (mobile photo editor)"),
    ("pixelmator", "high", "Pixelmator (image editor)"),
    ("canva", "medium", "Canva (design tool)"),
    ("ilovepdf", "medium", "iLovePDF (online PDF editor)"),
    ("pdfescape", "medium", "PDFescape (online PDF editor)"),
    ("foxit", "medium", "Foxit PDF editor"),
    ("acrobat", "low", "Adobe Acrobat (PDF editor/printer)"),
    ("microsoft® word", "low", "Microsoft Word export"),
    ("libreoffice", "low", "LibreOffice export"),
    ("skia/pdf", "low", "Chrome/Skia 'Print to PDF'"),
    ("weasyprint", "low", "WeasyPrint (HTML-to-PDF; generated, not authored)"),
]


class Signal(BaseModel):
    """One fraud SIGNAL surfaced to a human recruiter, with its exact evidence span."""

    name: str = Field(description="stable signal id, e.g. 'modified_after_creation'")
    severity: str = Field(description="low | medium | high")
    category: str = Field(description="forensic | consistency | verification | injection | certificate")
    evidence: str = Field(description="the exact evidence span in plain language")
    why: str = Field(description="why this matters / how a recruiter should read it")
    weak: bool = Field(default=False, description="labelled weak — capped in scoring, never proof")
    detail: dict | None = Field(default=None, description="structured extras (e.g. ELA heatmap)")


def _parse_pdf_date(s: str | None) -> datetime | None:
    if not s:
        return None
    m = re.search(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?", str(s))
    if not m:
        return None
    y, mo, d, hh, mm, ss = (int(g) if g else 0 for g in m.groups())
    try:
        return datetime(y, mo or 1, d or 1, hh, mm, ss)
    except ValueError:
        return None


def analyze_pdf(data: bytes, *, filename: str = "document.pdf", today: date = TODAY) -> list[Signal]:
    from pypdf import PdfReader

    out: list[Signal] = []
    producer = creator = None
    cdate = mdate = None
    try:
        reader = PdfReader(io.BytesIO(data))
        meta = reader.metadata or {}
        producer = str(meta.get("/Producer")) if meta.get("/Producer") else None
        creator = str(meta.get("/Creator")) if meta.get("/Creator") else None
        cdate = _parse_pdf_date(meta.get("/CreationDate"))
        mdate = _parse_pdf_date(meta.get("/ModDate"))
    except Exception as e:  # never raise from forensics
        out.append(Signal(name="unreadable_pdf", severity="medium", category="forensic",
                          evidence=f"PDF structure could not be parsed ({e}).",
                          why="A corrupt or hand-edited PDF can indicate tampering — open it manually."))

    # 1) modified after creation
    if cdate and mdate and mdate > cdate:
        delta_days = (mdate.date() - cdate.date()).days
        when = "yesterday" if (today - mdate.date()).days == 1 else mdate.date().isoformat()
        out.append(Signal(
            name="modified_after_creation", severity="medium", category="forensic",
            evidence=f"Created {cdate.date().isoformat()}, last modified {mdate.date().isoformat()} "
                     f"({when}) — {delta_days} day(s) later.",
            why="The file was edited after it was first generated. Legitimate for re-exports, "
                "but worth checking what changed."))

    # 2) incremental updates (raw-byte save generations)
    eof_count = data.count(b"%%EOF")
    if eof_count > 1:
        out.append(Signal(
            name="incremental_updates", severity="medium" if eof_count == 2 else "high",
            category="forensic",
            evidence=f"{eof_count} save generations found in the file (incremental-update markers).",
            why="A PDF saved once has a single generation. Multiple generations mean the document "
                "carries an edit history — content may have been altered after issue."))

    # 3) editor/producer fingerprint
    chain = " ".join(x for x in (producer, creator) if x)
    low = chain.lower()
    for needle, sev, label in _EDITOR_FINGERPRINTS:
        if needle in low:
            out.append(Signal(
                name="editor_fingerprint", severity=sev, category="forensic",
                evidence=f"Producer/Creator: {chain.strip()} → {label}.",
                why="The tool that wrote the PDF. Image editors on a document are a strong tampering "
                    "signal; print-drivers/HTML-renderers are normal but mean it was not an authored original."))
            break

    # 4) stripped metadata
    if not producer and not creator and not cdate and not mdate and not out:
        out.append(Signal(
            name="stripped_metadata", severity="low", category="forensic",
            evidence="No Producer/Creator/dates in the PDF metadata.",
            why="Metadata is commonly stripped by online tools or re-saves. Mild signal on its own."))
    return out


def analyze_image(data: bytes, *, filename: str = "image.jpg", today: date = TODAY) -> list[Signal]:
    from PIL import Image

    out: list[Signal] = []
    try:
        im = Image.open(io.BytesIO(data))
        exif = im.getexif()
    except Exception as e:
        out.append(Signal(name="unreadable_image", severity="medium", category="forensic",
                          evidence=f"Image could not be parsed ({e}).",
                          why="An unreadable image may be corrupt or disguised — inspect it manually."))
        return out

    software = exif.get(0x0131)  # Software tag
    if software:
        sw = str(software)
        sev = "high" if any(k in sw.lower() for k in ("photoshop", "gimp", "snapseed", "pixelmator")) else "low"
        out.append(Signal(
            name="image_editor_software", severity=sev, category="forensic",
            evidence=f"EXIF Software = {sw}.",
            why="The certificate image was processed by an editor. For a scan that should be untouched, "
                "this is a strong tampering signal."))
    elif len(exif) == 0:
        out.append(Signal(
            name="missing_image_metadata", severity="low", category="forensic",
            evidence="No EXIF metadata at all (no camera/scanner/software fields).",
            why="An original phone photo or scan normally carries EXIF. None present is consistent with a "
                "re-exported or generated image — mild signal, common for downloaded files."))

    ela = ela_signal(data)
    if ela:
        out.append(ela)
    return out


def ela_signal(data: bytes, *, max_px: int = 400) -> Signal | None:
    """Error-Level Analysis: re-save at q90 and measure the difference. Splices/edits often
    re-compress differently. LABELLED weak + capped — a hint to zoom in, NEVER proof."""
    from PIL import Image, ImageChops

    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None
    im.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    resaved = Image.open(io.BytesIO(buf.getvalue()))
    diff = ImageChops.difference(im, resaved)
    extrema = diff.getextrema()
    max_diff = max((hi for _lo, hi in extrema), default=1) or 1
    # crude hotspot ratio: how much of the image differs strongly
    gray = diff.convert("L")
    hist = gray.histogram()
    strong = sum(hist[40:]) / max(sum(hist), 1)
    sev = "medium" if strong > 0.06 else "low"
    # heatmap for the UI (amplified), downscaled + base64
    amp = gray.point(lambda p: min(255, int(p * (255 / max_diff))))
    hb = io.BytesIO()
    amp.save(hb, "PNG")
    return Signal(
        name="ela_recompression", severity=sev, category="forensic", weak=True,
        evidence=f"Error-Level Analysis: {strong*100:.1f}% of the image shows elevated recompression error.",
        why="WEAK signal only. Uneven recompression *can* indicate a pasted region, but compression, "
            "resizing and screenshots cause the same pattern. Use the heatmap to eyeball it — never decide on it alone.",
        detail={"heatmap_png_b64": base64.b64encode(hb.getvalue()).decode(), "strong_ratio": round(strong, 4)})


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def analyze_document(data: bytes, suffix: str, *, filename: str, today: date = TODAY) -> list[Signal]:
    suffix = suffix.lower()
    if suffix == ".pdf":
        return analyze_pdf(data, filename=filename, today=today)
    if suffix in _IMAGE_SUFFIXES:
        return analyze_image(data, filename=filename, today=today)
    return []  # docx/xlsx/txt: no binary forensics
