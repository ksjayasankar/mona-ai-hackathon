"""P4 forensics — deterministic, no LLM. Builds its own edited-PDF fixture so the
'known-edited' signals are reproducible (the sample CVs are clean WeasyPrint output)."""
import io
from datetime import date

from pypdf import PdfWriter

from core.tools import forensics as F

TODAY = date(2026, 6, 20)


def _clean_pdf() -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.add_metadata({"/Producer": "WeasyPrint 69.0", "/CreationDate": "D:20240101120000"})
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _edited_pdf() -> bytes:
    """Created 2024, 'modified' yesterday, with an appended incremental update."""
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.add_metadata({
        "/Producer": "Adobe Photoshop 24.0",
        "/CreationDate": "D:20240101120000",
        "/ModDate": "D:20260619090000",  # 2026-06-19 = yesterday vs TODAY
    })
    buf = io.BytesIO()
    w.write(buf)
    base = buf.getvalue()
    # append a second save generation (incremental-update fingerprint = extra %%EOF)
    return base + b"\n2 0 obj<<>>endobj\nstartxref\n0\n%%EOF\n"


def test_clean_pdf_has_no_high_forensic_signal():
    sigs = F.analyze_pdf(_clean_pdf(), today=TODAY)
    assert all(s.severity != "high" for s in sigs)
    assert all(s.category == "forensic" for s in sigs)


def test_edited_pdf_flags_modification_after_creation():
    sigs = F.analyze_pdf(_edited_pdf(), today=TODAY)
    names = {s.name for s in sigs}
    assert "modified_after_creation" in names
    mod = next(s for s in sigs if s.name == "modified_after_creation")
    assert "2026-06-19" in mod.evidence  # exact date surfaced


def test_edited_pdf_flags_incremental_updates():
    sigs = F.analyze_pdf(_edited_pdf(), today=TODAY)
    assert "incremental_updates" in {s.name for s in sigs}


def test_edited_pdf_flags_image_editor_producer():
    sigs = F.analyze_pdf(_edited_pdf(), today=TODAY)
    prod = next(s for s in sigs if s.name == "editor_fingerprint")
    assert "Photoshop" in prod.evidence
    assert prod.severity in ("medium", "high")


def test_image_missing_exif_is_low_signal():
    # a tiny JPEG with no EXIF (re-exported, not an original scan)
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 200, 200)).save(buf, format="JPEG")
    sigs = F.analyze_image(buf.getvalue(), filename="scan.jpg", today=TODAY)
    s = next(x for x in sigs if x.name == "missing_image_metadata")
    assert s.severity == "low"


def test_ela_is_weak_and_capped_low():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (128, 128), (120, 180, 90)).save(buf, format="JPEG")
    s = F.ela_signal(buf.getvalue())
    assert s is None or (s.weak is True and s.severity in ("low", "medium"))
