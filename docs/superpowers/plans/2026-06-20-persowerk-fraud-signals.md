# Persowerk CV & Certificate Fraud-Signals Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the P4 Persowerk agent that turns a CV + certificate(s) into a weighted fraud **risk score with per-signal EVIDENCE for a human recruiter** — never an auto-reject verdict.

**Architecture:** A deterministic core (PDF/image forensics + timeline/cross-doc consistency + weighted scoring) that is fully unit-testable offline, wrapped by an LLM-vision extraction step and an optional `core.agent` tool-loop (github_lookup + web_search) for verification. The service assembles signals, scores them, and persists tenant-scoped records; a Next.js dashboard renders each flag with its exact evidence span. Mirrors the P10 secure-intake reference (`services/secure_intake.py` + `api/routes/secure_intake.py` + `web/src/app/rheinmetall/page.tsx`).

**Tech Stack:** Python (pypdf, Pillow, httpx, pydantic, sqlmodel, FastAPI), `core.llm` (Gemini vision / Ollama dev), Next.js 16 + React 19 + Tailwind.

## Global Constraints

- **Own only:** `services/fraud.py`, `api/routes/fraud.py`, `core/tools/forensics.py`, `web/src/app/persowerk/**`; refine `agents/fraud.py` + `core/models/fraud.py`. The ONE shared edit: add the fraud router to `api/main.py`. Sanctioned config edits (named in the task): `.env.example` (add `GITHUB_TOKEN`), `STATE.md` (mark P4 done). Do NOT touch `core/db`, `core/auth`, `core/agent`, `core/llm`, `core/config`, `core/guard`, `core/ingest`, P10 files, `web/src/lib/*`, `web/src/components/*` (import only), `pyproject.toml`, `CLAUDE.md`.
- **No new dependencies.** `pikepdf` is NOT installed — use `pypdf` + raw-byte parsing for incremental-update detection. Note pikepdf as a *wanted* dep in the final report only.
- **Tests run OFFLINE/FREE** under `tests/conftest.py` (forces `LLM_PROVIDER=ollama`, dev auth, throwaway SQLite). Vision routes to Gemini, so **no test may call LLM vision or the live verify loop**: test only deterministic functions, the github tool with mocked httpx, and DB persistence.
- **`agents/*.py` stay PURE** (no db/web/network imports). Network (github/web) lives in `services/fraud.py`. DB lives in `services` + `api`.
- **Today anchor:** `date(2026, 6, 20)` everywhere (matches `agents/fraud.py:TODAY`).
- **Framing rule (the maturity beat):** every output is "a SIGNAL for a recruiter, not a verdict." NO AI-text-detector reject signal — state openly it is unreliable + biased against non-native writers. ELA is LABELLED weak and capped so it can never alone produce HIGH.
- **Signal object shape:** `{name, severity, category, evidence, why, weak, detail}` — `severity ∈ {low,medium,high}`, `category ∈ {forensic,consistency,verification,injection,certificate}`.
- **Web:** Next.js 16.2.9 is non-standard (see `web/AGENTS.md`) — mirror the working `web/src/app/rheinmetall/page.tsx` client-component pattern exactly; reuse `@/components/ui` primitives.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `core/tools/forensics.py` (new) | `Signal` model + deterministic PDF/image forensics + ELA. No LLM/DB/network. |
| `agents/fraud.py` (refine) | Keep LLM extraction models/fns. Add deterministic `consistency_signals`, `cross_signals`, `cert_signals`, `findings_to_signals`, `score_risk` + `RiskAssessment`. Pure. |
| `services/fraud.py` (new) | Orchestrate forensics+extract+verify → `build_report` (pure seam) → persist. Owns `make_github_tool` + the verify agent-loop. `history` / `get_record`. |
| `api/routes/fraud.py` (new) | `POST /agents/fraud/assess`, `GET /agents/fraud/history`, `GET /agents/fraud/records/{id}`. |
| `api/main.py` (1 line) | `from api.routes import fraud` + `app.include_router(fraud.router)`. |
| `core/models/fraud.py` (refine) | Add `email` to Candidate; keep Certificate/VerificationRecord (already fit). |
| `web/src/app/persowerk/page.tsx` (new) | Upload CV+certs+github/links → render risk + grouped signals w/ evidence + history. |
| `web/src/app/persowerk/api.ts` (new) | Co-located fetch client + TS types (avoids editing shared `web/src/lib/api.ts`). |
| `tests/test_fraud_forensics.py` (new) | Edited-PDF fixture, image EXIF, ELA cap. |
| `tests/test_fraud_consistency.py` (new) | Overlaps/gaps/impossible dates, cross-name, cert currency. |
| `tests/test_fraud_scoring.py` (new) | Weights, weak cap, injection override, monotonicity. |
| `tests/test_fraud_verify.py` (new) | `github_lookup` tool w/ mocked httpx → findings; findings→signals. |
| `tests/test_fraud_service.py` (new) | `build_report` (pure) + `persist`/`history` tenant-scoped, offline. |

---

## Task 1: Forensics module + `Signal` primitive

**Files:**
- Create: `core/tools/forensics.py`
- Test: `tests/test_fraud_forensics.py`

**Interfaces:**
- Produces:
  - `class Signal(BaseModel)` fields: `name:str, severity:str, category:str, evidence:str, why:str, weak:bool=False, detail:dict|None=None`
  - `analyze_pdf(data: bytes, *, filename: str = "document.pdf", today: date = TODAY) -> list[Signal]`
  - `analyze_image(data: bytes, *, filename: str = "image.jpg", today: date = TODAY) -> list[Signal]`
  - `ela_signal(data: bytes, *, max_px: int = 400) -> Signal | None`
  - `analyze_document(data: bytes, suffix: str, *, filename: str, today: date = TODAY) -> list[Signal]`
  - `TODAY = date(2026, 6, 20)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fraud_forensics.py
"""P4 forensics — deterministic, no LLM. Builds its own edited-PDF fixture so the
'known-edited' signals are reproducible (the sample CVs are clean WeasyPrint output)."""
import io
from datetime import date

from pypdf import PdfReader, PdfWriter

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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_fraud_forensics.py -q`
Expected: FAIL (module `core.tools.forensics` not found).

- [ ] **Step 3: Implement `core/tools/forensics.py`**

```python
"""Deterministic document forensics for the Persowerk fraud agent — the high-ROI,
explainable layer. NO LLM, NO DB, NO network: every Signal is reproducible from the
bytes. pikepdf is not installed, so incremental-update detection reads the raw bytes
(extra %%EOF / xref generations = save history). ELA is LABELLED weak and capped — a
hint to look closer, never proof.

`Signal` is the shared primitive for the whole agent (forensics, consistency,
verification): {name, severity, category, evidence, why, weak, detail}.
"""
from __future__ import annotations

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
    if im.format and im.format.upper() not in ("JPEG", "JPG") and getattr(im, "format", None):
        pass  # ELA is most meaningful on JPEG but we still compute it on the loaded RGB
    im.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    resaved = Image.open(io.BytesIO(buf.getvalue()))
    diff = ImageChops.difference(im, resaved)
    extrema = diff.getextrema()
    max_diff = max(hi for _lo, hi in extrema) or 1
    # crude hotspot ratio: how much of the image differs strongly
    gray = diff.convert("L")
    hist = gray.histogram()
    strong = sum(hist[40:]) / max(sum(hist), 1)
    sev = "medium" if strong > 0.06 else "low"
    # heatmap for the UI (amplified), downscaled + base64
    import base64
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
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_fraud_forensics.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add core/tools/forensics.py tests/test_fraud_forensics.py
git commit -m "feat(p4): deterministic PDF/image forensics + Signal primitive"
```

---

## Task 2: Deterministic consistency + cert + cross signals (refine `agents/fraud.py`)

**Files:**
- Modify: `agents/fraud.py` (add new pure functions; keep existing extraction models/fns)
- Test: `tests/test_fraud_consistency.py`

**Interfaces:**
- Consumes: `Signal` from `core.tools.forensics`; `CVClaims`, `CVRole`, `CertFields` (existing in `agents/fraud.py`).
- Produces:
  - `consistency_signals(claims: CVClaims, *, today: date = TODAY) -> list[Signal]`
  - `cross_signals(claims: CVClaims, certs: list[CertFields]) -> list[Signal]`
  - `cert_signals(cert: CertFields, *, today: date = TODAY) -> list[Signal]`
  - `_parse_month(s: str|None, *, today: date) -> tuple[date|None, bool]` (returns `(date, is_present_keyword)`)
  - Extend `CVClaims` with `email: str | None`, `github: str | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fraud_consistency.py
from datetime import date

from agents import fraud as A
from agents.fraud import CVClaims, CVRole, CertFields

TODAY = date(2026, 6, 20)


def _claims(roles, name="Jane Doe"):
    return CVClaims(candidate_name=name, roles=roles, skills=[], summary=None,
                    languages=[], extraction_confidence=90.0)


def test_overlapping_roles_flagged():
    roles = [CVRole(title="A", employer="X", start="01/2019", end="06/2022", achievements_specific=True),
             CVRole(title="B", employer="Y", start="01/2021", end="present", achievements_specific=True)]
    sigs = A.consistency_signals(_claims(roles), today=TODAY)
    overlap = next(s for s in sigs if s.name == "timeline_overlap")
    assert overlap.category == "consistency"
    assert "2019" in overlap.evidence and "2021" in overlap.evidence


def test_large_gap_flagged_low():
    roles = [CVRole(title="A", employer="X", start="01/2014", end="06/2016", achievements_specific=True),
             CVRole(title="B", employer="Y", start="01/2020", end="present", achievements_specific=True)]
    sigs = A.consistency_signals(_claims(roles), today=TODAY)
    gap = next(s for s in sigs if s.name == "timeline_gap")
    assert gap.severity == "low"


def test_end_before_start_flagged():
    roles = [CVRole(title="A", employer="X", start="01/2022", end="01/2019", achievements_specific=True)]
    sigs = A.consistency_signals(_claims(roles), today=TODAY)
    assert "impossible_dates" in {s.name for s in sigs}


def test_future_date_flagged():
    roles = [CVRole(title="A", employer="X", start="01/2030", end="present", achievements_specific=True)]
    sigs = A.consistency_signals(_claims(roles), today=TODAY)
    assert "future_dated" in {s.name for s in sigs}


def test_clean_timeline_no_signals():
    roles = [CVRole(title="A", employer="X", start="01/2016", end="12/2019", achievements_specific=True),
             CVRole(title="B", employer="Y", start="01/2020", end="present", achievements_specific=True)]
    assert A.consistency_signals(_claims(roles), today=TODAY) == []


def test_cv_cert_name_mismatch():
    cert = CertFields(is_certificate=True, cert_type="diploma", issuer="Uni", holder_name="John Smith",
                      title="BSc", issue_date="2019", valid_until=None, is_genuine_looking=True,
                      forgery_signals=[], extraction_confidence=90.0, notes=None)
    sigs = A.cross_signals(_claims([], name="Jane Doe"), [cert])
    assert "name_mismatch" in {s.name for s in sigs}


def test_expired_certificate_flagged():
    cert = CertFields(is_certificate=True, cert_type="license", issuer="ISACA", holder_name="Jane Doe",
                      title="CISA", issue_date="2018", valid_until="01.01.2020", is_genuine_looking=True,
                      forgery_signals=[], extraction_confidence=90.0, notes=None)
    sigs = A.cert_signals(cert, today=TODAY)
    s = next(x for x in sigs if x.name == "certificate_expired")
    assert "2020" in s.evidence


def test_forgery_signal_maps_to_high():
    cert = CertFields(is_certificate=True, cert_type="license", issuer="ISACA", holder_name="Jane Doe",
                      title="CISA", issue_date="2018", valid_until=None, is_genuine_looking=False,
                      forgery_signals=["warped seal", "inconsistent fonts"], extraction_confidence=90.0, notes=None)
    sigs = A.cert_signals(cert, today=TODAY)
    assert any(s.severity == "high" for s in sigs)
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_fraud_consistency.py -q`
Expected: FAIL (functions not defined / `email` field absent).

- [ ] **Step 3: Implement — add to `agents/fraud.py`**

Add the import at the top (after existing imports): `from core.tools.forensics import Signal`. Add `from datetime import date, datetime` is already present. Extend `CVClaims` with two optional fields:

```python
    email: str | None = Field(default=None, description="Candidate email if present")
    github: str | None = Field(default=None, description="GitHub URL or handle if present on the CV")
```

Then append the deterministic engine:

```python
# --------------------------------------------------------------------------- #
# Deterministic signal engines (no LLM) — the testable substance.
# --------------------------------------------------------------------------- #
_PRESENT = {"present", "current", "now", "heute", "ongoing", "till date", "to date"}


def _parse_month(s: str | None, *, today: date) -> tuple[date | None, bool]:
    """Parse a CV date as written. Returns (date, is_present_keyword)."""
    if not s:
        return None, False
    t = s.strip().lower()
    if any(p in t for p in _PRESENT):
        return today, True
    for fmt in ("%m/%Y", "%Y-%m", "%m.%Y", "%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date().replace(day=1), False
        except ValueError:
            continue
    m = re.search(r"(19|20)\d{2}", t)
    if m:
        return date(int(m.group(0)), 1, 1), False
    return None, False


def _fmt(role: CVRole) -> str:
    return f"'{role.title or role.employer or '?'}' ({role.start or '?'}–{role.end or '?'})"


def consistency_signals(claims: CVClaims, *, today: date = TODAY) -> list[Signal]:
    """Timeline analysis: overlaps, large gaps, impossible/future dates. All deterministic."""
    out: list[Signal] = []
    parsed = []
    for r in claims.roles:
        s, _ = _parse_month(r.start, today=today)
        e, is_present = _parse_month(r.end, today=today)
        parsed.append((r, s, e, is_present))
        if s and e and e < s:
            out.append(Signal(name="impossible_dates", severity="medium", category="consistency",
                              evidence=f"Role {_fmt(r)} ends before it starts.",
                              why="An end date earlier than the start is internally impossible — likely a typo or fabrication."))
        for label, dt in (("start", s), ("end", None if is_present else e)):
            if dt and dt > today:
                out.append(Signal(name="future_dated", severity="medium", category="consistency",
                                  evidence=f"Role {_fmt(r)} has a {label} date in the future ({dt.year}).",
                                  why="A date after today cannot describe past employment."))

    # overlaps (>1 month) between any two datable roles
    datable = [(r, s, e) for (r, s, e, _p) in parsed if s and e]
    for i in range(len(datable)):
        for j in range(i + 1, len(datable)):
            (ra, sa, ea), (rb, sb, eb) = datable[i], datable[j]
            overlap_days = (min(ea, eb) - max(sa, sb)).days
            if overlap_days > 31:
                out.append(Signal(name="timeline_overlap", severity="medium", category="consistency",
                                  evidence=f"{_fmt(ra)} overlaps {_fmt(rb)} by ~{overlap_days // 30} month(s).",
                                  why="Concurrent full-time roles can be legitimate (freelance/part-time) but often "
                                      "indicate padding — confirm with the candidate."))

    # gaps > 12 months between consecutive (sorted by start) roles
    seq = sorted([(r, s, e) for (r, s, e, _p) in parsed if s and e], key=lambda x: x[1])
    for (ra, _sa, ea), (rb, sb, _eb) in zip(seq, seq[1:]):
        gap_days = (sb - ea).days
        if gap_days > 365:
            out.append(Signal(name="timeline_gap", severity="low", category="consistency",
                              evidence=f"~{gap_days // 30}-month gap between {_fmt(ra)} and {_fmt(rb)}.",
                              why="Unexplained gaps are common and rarely fraud, but worth a question in interview."))
    return out


def _norm_name(n: str | None) -> set[str]:
    return {t for t in re.split(r"\s+", (n or "").lower().strip()) if len(t) > 1}


def cross_signals(claims: CVClaims, certs: list[CertFields]) -> list[Signal]:
    """Cross-document: does the CV name match the certificate holder?"""
    out: list[Signal] = []
    cv_tokens = _norm_name(claims.candidate_name)
    if not cv_tokens:
        return out
    for c in certs:
        h_tokens = _norm_name(c.holder_name)
        if h_tokens and not (cv_tokens & h_tokens):
            out.append(Signal(name="name_mismatch", severity="medium", category="consistency",
                              evidence=f"CV name '{claims.candidate_name}' does not match certificate holder "
                                       f"'{c.holder_name}' on {c.cert_type or 'a certificate'}.",
                              why="A certificate issued to a different person may be borrowed or fabricated — verify identity."))
    return out


def cert_signals(cert: CertFields, *, today: date = TODAY) -> list[Signal]:
    """Certificate forgery + currency signals (deterministic over the extracted fields)."""
    out: list[Signal] = []
    if not cert.is_certificate:
        return out
    if not cert.is_genuine_looking:
        out.append(Signal(name="certificate_suspect", severity="high", category="certificate",
                          evidence=f"Document '{cert.title or cert.cert_type}' shows authenticity problems: "
                                   + "; ".join(cert.forgery_signals or ["model judged it not genuine-looking"]) + ".",
                          why="The visual layout/seal/fonts look inconsistent with a genuine credential — examine the original."))
    elif len(cert.forgery_signals or []) >= 2:
        out.append(Signal(name="certificate_suspect", severity="medium", category="certificate",
                          evidence="Multiple forgery hints: " + "; ".join(cert.forgery_signals) + ".",
                          why="Several small anomalies together warrant a manual look."))
    vu = _parse_date(cert.valid_until)
    if vu and vu < today:
        out.append(Signal(name="certificate_expired", severity="medium", category="certificate",
                          evidence=f"Certificate '{cert.title or cert.cert_type}' expired on {cert.valid_until} "
                                   f"({(today - vu).days} days ago).",
                          why="An expired credential does not meet a 'valid & current' requirement."))
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_fraud_consistency.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add agents/fraud.py tests/test_fraud_consistency.py
git commit -m "feat(p4): deterministic timeline/cross-doc/certificate signal engines"
```

---

## Task 3: Weighted risk scoring + findings mapping (refine `agents/fraud.py`)

**Files:**
- Modify: `agents/fraud.py`
- Test: `tests/test_fraud_scoring.py`

**Interfaces:**
- Produces:
  - `class RiskAssessment(BaseModel)`: `risk:str, score:int, signals:list[Signal], summary:str`
  - `score_risk(signals: list[Signal]) -> RiskAssessment`
  - `class VerifyFindings(BaseModel)` (for the agent loop output) + `findings_to_signals(f: VerifyFindings) -> list[Signal]`
  - `injection_signals(texts: list[str]) -> list[Signal]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fraud_scoring.py
from agents import fraud as A
from core.tools.forensics import Signal


def _sig(sev, cat="forensic", weak=False):
    return Signal(name="x", severity=sev, category=cat, evidence="e", why="w", weak=weak)


def test_no_signals_is_low_zero():
    r = A.score_risk([])
    assert r.risk == "LOW" and r.score == 0


def test_two_high_signals_is_high():
    r = A.score_risk([_sig("high"), _sig("high")])
    assert r.risk == "HIGH" and r.score >= 67


def test_weak_only_never_high():
    r = A.score_risk([_sig("high", weak=True), _sig("high", weak=True), _sig("medium", weak=True)])
    assert r.risk != "HIGH"


def test_injection_forces_high():
    r = A.score_risk([_sig("high", cat="injection")])
    assert r.risk == "HIGH" and r.score >= 85


def test_monotonic_adding_signal_never_lowers():
    base = A.score_risk([_sig("medium")]).score
    more = A.score_risk([_sig("medium"), _sig("low")]).score
    assert more >= base


def test_findings_to_signals_skill_gap_is_weak():
    f = A.VerifyFindings(github_account_age_years=1.0, github_languages=["python"],
                         claimed_experience_years=10.0, skills_not_found=["rust"],
                         company_web_findings=[], notes=None)
    sigs = A.findings_to_signals(f)
    assert any(s.category == "verification" for s in sigs)
    assert any(s.weak for s in sigs)  # absence-of-evidence stays weak
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_fraud_scoring.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement — append to `agents/fraud.py`**

```python
# --------------------------------------------------------------------------- #
# Risk scoring — weighted, deterministic, calibrated NOT alarmist. Output is a
# SIGNAL summary for a recruiter, never an auto-reject.
# --------------------------------------------------------------------------- #
_BASE = {"high": 0.60, "medium": 0.30, "low": 0.12}
_WEAK_MULT = 0.40
_WEAK_CAP = 0.15  # all weak signals together can lift at most this much


def _noisy_or(contribs: list[float]) -> float:
    p = 1.0
    for c in contribs:
        p *= (1.0 - max(0.0, min(1.0, c)))
    return 1.0 - p


class RiskAssessment(BaseModel):
    risk: str
    score: int
    signals: list[Signal]
    summary: str


def score_risk(signals: list[Signal]) -> RiskAssessment:
    strong = [_BASE.get(s.severity, 0.0) for s in signals if not s.weak]
    weak = [_BASE.get(s.severity, 0.0) * _WEAK_MULT for s in signals if s.weak]
    p_strong = _noisy_or(strong)
    p_weak = min(_WEAK_CAP, _noisy_or(weak))
    p = 1.0 - (1.0 - p_strong) * (1.0 - p_weak)
    score = round(100 * p)

    # weak/low evidence can lift within a band but never CREATE a HIGH
    if p_strong < 0.67:
        score = min(score, 66)

    # an injection attempt embedded in the CV is a concrete, strong fraud flag
    if any(s.category == "injection" and s.severity == "high" for s in signals):
        score = max(score, 85)

    risk = "HIGH" if score >= 67 else "MEDIUM" if score >= 34 else "LOW"
    by_sev = {k: sum(1 for s in signals if s.severity == k and not s.weak) for k in ("high", "medium", "low")}
    if not signals:
        summary = "No fraud signals detected — the documents read as authentic. (A clean result is normal.)"
    else:
        summary = (f"{risk} risk ({score}/100): {by_sev['high']} high, {by_sev['medium']} medium, "
                   f"{by_sev['low']} low signal(s). These are SIGNALS for a recruiter to review — not an automated verdict.")
    return RiskAssessment(risk=risk, score=score, signals=signals, summary=summary)


# --------------------------------------------------------------------------- #
# Verification findings (from the core.agent tool-loop) -> signals.
# Absence of evidence stays WEAK/low — we never reject on "not found online".
# --------------------------------------------------------------------------- #
class VerifyFindings(BaseModel):
    """Structured result of the github/web verification agent loop."""

    github_account_age_years: float | None = Field(default=None)
    github_languages: list[str] = Field(default_factory=list)
    claimed_experience_years: float | None = Field(default=None)
    skills_not_found: list[str] = Field(default_factory=list, description="claimed skills with no public evidence")
    company_web_findings: list[str] = Field(default_factory=list, description="short notes on employer web checks")
    notes: str | None = Field(default=None)


def findings_to_signals(f: VerifyFindings) -> list[Signal]:
    out: list[Signal] = []
    if (f.github_account_age_years is not None and f.claimed_experience_years
            and f.github_account_age_years + 2 < f.claimed_experience_years):
        out.append(Signal(name="github_age_vs_claim", severity="medium", category="verification",
                          evidence=f"GitHub account is ~{f.github_account_age_years:.0f} year(s) old but the CV "
                                   f"claims ~{f.claimed_experience_years:.0f} years of experience.",
                          why="A much younger developer footprint than claimed seniority is worth probing — "
                              "though developers do work privately."))
    if f.skills_not_found:
        out.append(Signal(name="skills_unverified", severity="low", category="verification", weak=True,
                          evidence=f"Claimed skills with no public evidence: {', '.join(f.skills_not_found)}.",
                          why="WEAK: absence of public proof is not proof of absence (private/enterprise work). "
                              "Treat as a question, not a finding."))
    for note in f.company_web_findings:
        if "no results" in note.lower() or "not found" in note.lower():
            out.append(Signal(name="employer_unverified", severity="low", category="verification", weak=True,
                              evidence=note,
                              why="WEAK: small or non-English employers often have no web footprint."))
    return out


def injection_signals(texts: list[str]) -> list[Signal]:
    """Prompt-injection text inside a CV is a strong, concrete fraud flag."""
    from core import guard
    out: list[Signal] = []
    for i, t in enumerate(texts):
        scan = guard.scan(t or "")
        if scan["hits"]:
            out.append(Signal(name="prompt_injection", severity="high", category="injection",
                              evidence="Injection-style text embedded in the CV: " + ", ".join(scan["hits"]) + ".",
                              why="The document tries to instruct the screening system (e.g. 'ignore previous "
                                  "instructions'). Legitimate CVs never do this — strong tampering/fraud flag."))
            break
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_fraud_scoring.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add agents/fraud.py tests/test_fraud_scoring.py
git commit -m "feat(p4): weighted risk scoring + verification-findings mapping"
```

---

## Task 4: `github_lookup` tool + verify loop wiring (`services/fraud.py` part 1)

**Files:**
- Create: `services/fraud.py` (github tool + verify; rest added in Task 5)
- Test: `tests/test_fraud_verify.py`

**Interfaces:**
- Produces:
  - `parse_github_handle(url_or_handle: str | None) -> str | None`
  - `github_lookup(handle: str) -> str` (JSON string; never raises; uses `GITHUB_TOKEN` if set)
  - `make_github_tool() -> core.agent.Tool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fraud_verify.py
import json

import services.fraud as svc


def test_parse_github_handle_variants():
    assert svc.parse_github_handle("https://github.com/torvalds") == "torvalds"
    assert svc.parse_github_handle("github.com/torvalds/") == "torvalds"
    assert svc.parse_github_handle("@torvalds") == "torvalds"
    assert svc.parse_github_handle("torvalds") == "torvalds"
    assert svc.parse_github_handle(None) is None


def test_github_lookup_parses_account_age_and_languages(monkeypatch):
    class _Resp:
        def __init__(self, payload):
            self._p = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self._p

    def fake_get(url, **kw):
        if url.endswith("/users/jane"):
            return _Resp({"created_at": "2022-06-20T00:00:00Z", "public_repos": 3})
        if "/repos" in url:
            return _Resp([{"language": "Python"}, {"language": "Python"}, {"language": "Go"}])
        return _Resp({})

    monkeypatch.setattr(svc.httpx, "get", fake_get)
    out = json.loads(svc.github_lookup("jane"))
    assert out["account_age_years"] >= 3.9  # 2022-06-20 -> 2026-06-20 ≈ 4y
    assert "Python" in out["languages"]


def test_github_lookup_handles_missing_user(monkeypatch):
    import httpx as _httpx

    def fake_get(url, **kw):
        raise _httpx.HTTPError("404")

    monkeypatch.setattr(svc.httpx, "get", fake_get)
    out = svc.github_lookup("nope")
    assert "error" in out.lower() or "not" in out.lower()  # graceful, no raise
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_fraud_verify.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `services/fraud.py` (part 1 — top of file)**

```python
"""P4 Persowerk — CV & certificate fraud-SIGNALS service (tenant-scoped, persisted).

Pipeline (mirrors services/secure_intake.py):
  1. FORENSICS  — deterministic PDF/image checks (core.tools.forensics). No LLM.
  2. EXTRACT    — core.llm vision reads roles/dates/skills (CV) + issuer/holder/dates (certs).
  3. CONSISTENCY— deterministic timeline/cross-doc/cert-currency signals (agents.fraud).
  4. INJECTION  — guard.scan over CV text; embedded instructions = strong fraud flag.
  5. VERIFY     — core.agent tool-loop: github_lookup + web_search (optional; network).
  6. SCORE      — weighted signals -> LOW/MEDIUM/HIGH + 0-100, each with its evidence span.
  7. PERSIST    — Candidate + Certificate + VerificationRecord (tenant-scoped) + AuditLog.

`build_report` is a PURE seam (no LLM/network/db) so the offline suite can exercise the
whole assembly + scoring. The output is always framed "signal for a recruiter, not a verdict".
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel, Field
from sqlmodel import Session, desc, select

from agents import fraud as A
from agents.fraud import (CertFields, CVClaims, RiskAssessment, VerifyFindings,
                          cert_signals, consistency_signals, cross_signals,
                          findings_to_signals, injection_signals, score_risk)
from core import guard, ingest, llm
from core.agent import Tool, run_agent
from core.db import engine
from core.models import AuditLog, Candidate, Certificate, VerificationRecord
from core.tools.forensics import Signal, analyze_document
from core.tools.web import web_search

log = logging.getLogger("fraud")
TODAY = date(2026, 6, 20)
GITHUB_API = "https://api.github.com"


def parse_github_handle(url_or_handle: str | None) -> str | None:
    if not url_or_handle:
        return None
    t = url_or_handle.strip().strip("@/")
    m = re.search(r"github\.com/([A-Za-z0-9-]+)", t)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9-]+", t):
        return t
    return None


def github_lookup(handle: str) -> str:
    """Public GitHub REST: account age + languages used. Never raises; honest on failure."""
    handle = parse_github_handle(handle) or handle
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        u = httpx.get(f"{GITHUB_API}/users/{handle}", headers=headers, timeout=15)
        u.raise_for_status()
        user = u.json()
        created = user.get("created_at")
        age_years = None
        if created:
            cdt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_years = round((datetime.now(timezone.utc) - cdt).days / 365.25, 1)
        r = httpx.get(f"{GITHUB_API}/users/{handle}/repos",
                      headers=headers, params={"per_page": 100, "sort": "pushed"}, timeout=15)
        r.raise_for_status()
        langs = sorted({repo.get("language") for repo in r.json() if repo.get("language")})
        return json.dumps({"handle": handle, "account_age_years": age_years,
                           "public_repos": user.get("public_repos"), "languages": langs})
    except Exception as e:
        return json.dumps({"handle": handle, "error": f"GitHub lookup failed or user not found: {e}"})


def make_github_tool() -> Tool:
    return Tool(
        name="github_lookup",
        description="Look up a public GitHub account: returns account age (years), public repo count, "
                    "and the programming languages used across their repos. Use to sanity-check claimed "
                    "experience and skills. Input is a GitHub username or profile URL.",
        parameters={"type": "object",
                    "properties": {"handle": {"type": "string", "description": "GitHub username or profile URL"}},
                    "required": ["handle"]},
        fn=lambda handle: github_lookup(handle),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_fraud_verify.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/fraud.py tests/test_fraud_verify.py
git commit -m "feat(p4): github_lookup verification tool (public REST, graceful)"
```

---

## Task 5: Orchestration `build_report` + persistence (`services/fraud.py` part 2) + models

**Files:**
- Modify: `services/fraud.py` (append assembly, extract, verify, persist, history)
- Modify: `core/models/fraud.py` (add `email` to `Candidate`)
- Test: `tests/test_fraud_service.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces:
  - `class CertResultLite(BaseModel)`: `{filename, is_certificate, decision, valid_until, days_remaining, fields_dump}`
  - `class FraudReport(BaseModel)`: `candidate_name, risk, score, summary, signals:list[Signal], by_category:dict, cert_summaries:list[dict], extraction:dict, verify_ran:bool, methodology_note:str, llm_calls:int, agent_steps:int`
  - `build_report(*, claims, cert_fields, forensic_signals, verify_findings, today=TODAY, verify_ran=False, llm_calls=0, agent_steps=0) -> FraudReport` (PURE)
  - `assess(*, tenant_id, cv=None, certs=(), github_handle=None, links=(), provider=None, run_verify=True) -> FraudReport`
  - `persist(tenant_id, report, claims, cert_fields) -> str`
  - `history(tenant_id, limit=20) -> list[dict]`
  - `get_record(tenant_id, record_id) -> dict | None`

- [ ] **Step 1: Add `email` to `Candidate` in `core/models/fraud.py`**

```python
class Candidate(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    name: str | None = None
    email: str | None = None
    github: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
```

(`Certificate` + `VerificationRecord` already fit — no change.)

- [ ] **Step 2: Write the failing test**

```python
# tests/test_fraud_service.py
from datetime import date

import services.fraud as svc
from agents.fraud import CVClaims, CVRole, CertFields
from core.auth import get_or_create_tenant
from core.tools.forensics import Signal

TODAY = date(2026, 6, 20)


def _claims():
    return CVClaims(candidate_name="Jane Doe", email="jane@x.com", github="github.com/jane",
                    roles=[CVRole(title="Dev", employer="X", start="01/2019", end="06/2022",
                                  achievements_specific=True),
                           CVRole(title="Dev2", employer="Y", start="01/2021", end="present",
                                  achievements_specific=True)],
                    skills=["python"], summary="Engineer", languages=["English"], extraction_confidence=90.0)


def _cert():
    return CertFields(is_certificate=True, cert_type="diploma", issuer="Uni", holder_name="Jane Doe",
                      title="BSc", issue_date="2018", valid_until=None, is_genuine_looking=True,
                      forgery_signals=[], extraction_confidence=90.0, notes=None)


def test_build_report_assembles_and_scores():
    forensic = [Signal(name="incremental_updates", severity="medium", category="forensic",
                       evidence="2 generations", why="edit history")]
    rep = svc.build_report(claims=_claims(), cert_fields=[_cert()], forensic_signals=forensic,
                           verify_findings=None, today=TODAY)
    # the overlap (consistency) + the forensic signal are both present
    names = {s["name"] for s in rep.by_category.get("consistency", [])}
    assert "timeline_overlap" in names
    assert rep.risk in ("LOW", "MEDIUM", "HIGH")
    assert "not an automated verdict" in rep.summary or "signal" in rep.methodology_note.lower()
    assert "AI-text" in rep.methodology_note  # the disclosure is present


def test_persist_and_history_tenant_scoped():
    tenant = get_or_create_tenant("test-persowerk", "Test Persowerk")
    rep = svc.build_report(claims=_claims(), cert_fields=[_cert()], forensic_signals=[],
                           verify_findings=None, today=TODAY)
    rid = svc.persist(tenant, rep, _claims(), [_cert()])
    rows = svc.history(tenant)
    assert any(r["id"] == rid for r in rows)
    full = svc.get_record(tenant, rid)
    assert full and full["report"]["candidate_name"] == "Jane Doe"
    # isolation: another tenant cannot see it
    other = get_or_create_tenant("test-persowerk-other", "Other")
    assert svc.get_record(other, rid) is None
```

- [ ] **Step 3: Run to verify fail**

Run: `uv run pytest tests/test_fraud_service.py -q`
Expected: FAIL.

- [ ] **Step 4: Implement — append to `services/fraud.py`**

```python
# --------------------------------------------------------------------------- #
# Extraction (LLM vision) — kept thin; reuses the agents/fraud.py models.
# --------------------------------------------------------------------------- #
CV_EXTRACT_SYSTEM = A.CV_EXTRACT_SYSTEM
CERT_SYSTEM = A.CERT_SYSTEM
METHODOLOGY = (
    "These are SIGNALS to help a human recruiter decide — not an automated accept/reject. "
    "We deliberately do NOT run an AI-text 'detector': those tools are unreliable and biased "
    "against non-native English writers, so a clean-but-polished CV is never penalised here. "
    "Forensic image analysis (ELA) is labelled a weak hint and capped — never proof on its own."
)


def _extract_cv(blocks: list[dict], provider: str | None) -> CVClaims:
    payload = blocks + [{"type": "text", "text":
                         "Extract the candidate's name, email, GitHub URL/handle, roles (with dates as "
                         "written), skills, languages and summary."}]
    return llm.extract(CVClaims, payload, system=CV_EXTRACT_SYSTEM, provider=provider)


def _extract_cert(blocks: list[dict], provider: str | None) -> CertFields:
    payload = blocks + [{"type": "text", "text":
                         "Extract the certificate fields and judge whether it looks genuine."}]
    return llm.extract(CertFields, payload, system=CERT_SYSTEM, provider=provider)


def _cert_summary(filename: str, c: CertFields, today: date) -> dict:
    vu = A._parse_date(c.valid_until)
    days = (vu - today).days if vu else None
    if not c.is_certificate:
        decision = "NOT_A_CERTIFICATE"
    elif not c.is_genuine_looking:
        decision = "SUSPECT"
    elif vu is None:
        decision = "NO_EXPIRY"
    elif days is not None and days >= 0:
        decision = "GENUINE_CURRENT"
    else:
        decision = "GENUINE_EXPIRED"
    return {"filename": filename, "decision": decision, "issuer": c.issuer, "title": c.title,
            "holder_name": c.holder_name, "valid_until": c.valid_until, "days_remaining": days,
            "is_current": (decision in ("GENUINE_CURRENT", "NO_EXPIRY"))}


class FraudReport(BaseModel):
    candidate_name: str | None
    risk: str
    score: int
    summary: str
    signals: list[Signal]
    by_category: dict[str, list[dict]]
    cert_summaries: list[dict]
    extraction: dict
    verify_ran: bool
    methodology_note: str
    llm_calls: int = 0
    agent_steps: int = 0


def build_report(*, claims: CVClaims, cert_fields: list[CertFields], forensic_signals: list[Signal],
                 verify_findings: VerifyFindings | None, today: date = TODAY,
                 verify_ran: bool = False, llm_calls: int = 0, agent_steps: int = 0) -> FraudReport:
    """PURE assembly: combine all signal sources, score, group for the UI."""
    signals: list[Signal] = list(forensic_signals)
    signals += consistency_signals(claims, today=today)
    signals += cross_signals(claims, cert_fields)
    for c in cert_fields:
        signals += cert_signals(c, today=today)
    inj_texts = [claims.summary or ""] + claims.skills + [r.title or "" for r in claims.roles]
    signals += injection_signals(inj_texts)
    if verify_findings is not None:
        signals += findings_to_signals(verify_findings)

    assessment: RiskAssessment = score_risk(signals)
    by_category: dict[str, list[dict]] = {}
    for s in assessment.signals:
        by_category.setdefault(s.category, []).append(s.model_dump())
    cert_summaries = [_cert_summary(f"certificate_{i+1}", c, today) for i, c in enumerate(cert_fields)]
    return FraudReport(
        candidate_name=claims.candidate_name, risk=assessment.risk, score=assessment.score,
        summary=assessment.summary, signals=assessment.signals, by_category=by_category,
        cert_summaries=cert_summaries, extraction=claims.model_dump(), verify_ran=verify_ran,
        methodology_note=METHODOLOGY, llm_calls=llm_calls, agent_steps=agent_steps)


# --------------------------------------------------------------------------- #
# Full orchestration (LLM + network) — used by the API, NOT by the offline tests.
# --------------------------------------------------------------------------- #
def _run_verify(claims: CVClaims, github_handle: str | None, provider: str | None) -> tuple[VerifyFindings | None, int, int]:
    handle = parse_github_handle(github_handle) or parse_github_handle(claims.github)
    if not handle:
        return None, 0, 0
    tools = [make_github_tool(),
             Tool(name="web_search",
                  description="Search the web to check an employer/company or role exists.",
                  parameters={"type": "object", "properties": {"query": {"type": "string"}},
                              "required": ["query"]},
                  fn=lambda query: web_search(query))]
    years = _claimed_years(claims)
    user = (
        f"Verify this candidate. GitHub handle: {handle}. Claimed skills: {', '.join(claims.skills) or 'none'}. "
        f"Roughly {years or '?'} years of claimed experience. Employers: "
        f"{', '.join(r.employer for r in claims.roles if r.employer) or 'none'}.\n"
        "1) Call github_lookup(handle) — compare account age to claimed experience and languages to claimed skills.\n"
        "2) For up to two employers, call web_search to check they exist.\n"
        "Then report findings as structured data. Be fair: missing public evidence is NOT proof of fraud.")
    agent = run_agent(guard.SAFE_SYSTEM + " You verify a candidate's public footprint.",
                      user, tools, schema=VerifyFindings, max_steps=5, provider=provider)
    findings = agent.data if isinstance(agent.data, VerifyFindings) else None
    if findings is not None and findings.claimed_experience_years is None:
        findings.claimed_experience_years = years
    return findings, agent.llm_calls, agent.steps


def _claimed_years(claims: CVClaims) -> float | None:
    spans = []
    for r in claims.roles:
        s, _ = A._parse_month(r.start, today=TODAY)
        e, _ = A._parse_month(r.end, today=TODAY)
        if s and e and e >= s:
            spans.append((e - s).days / 365.25)
    return round(sum(spans), 1) if spans else None


def assess(*, tenant_id: str, cv: tuple[str, bytes] | None = None,
           certs: list[tuple[str, bytes]] | None = None, github_handle: str | None = None,
           links: list[str] | None = None, provider: str | None = None,
           run_verify: bool = True) -> FraudReport:
    certs = certs or []
    forensic: list[Signal] = []
    claims = CVClaims(candidate_name=None, roles=[], skills=[], summary=None, languages=[],
                      extraction_confidence=0.0)
    if cv:
        name, data = cv
        forensic += analyze_document(data, Path(name).suffix, filename=name)
        claims = _extract_cv(ingest.bytes_to_blocks(data, Path(name).suffix, name), provider)
    cert_fields: list[CertFields] = []
    for name, data in certs:
        forensic += analyze_document(data, Path(name).suffix, filename=name)
        cert_fields.append(_extract_cert(ingest.bytes_to_blocks(data, Path(name).suffix, name), provider))

    findings, vcalls, vsteps = (None, 0, 0)
    if run_verify:
        try:
            findings, vcalls, vsteps = _run_verify(claims, github_handle, provider)
        except Exception as e:  # verification is best-effort; never fail the whole assessment
            log.warning("verify loop failed: %s", e)

    report = build_report(claims=claims, cert_fields=cert_fields, forensic_signals=forensic,
                          verify_findings=findings, verify_ran=findings is not None,
                          llm_calls=(1 if cv else 0) + len(cert_fields) + vcalls, agent_steps=vsteps)
    persist(tenant_id, report, claims, cert_fields)
    return report


def persist(tenant_id: str, report: FraudReport, claims: CVClaims, cert_fields: list[CertFields]) -> str:
    with Session(engine) as s:
        cand = Candidate(tenant_id=tenant_id, name=claims.candidate_name, email=claims.email,
                         github=parse_github_handle(claims.github))
        s.add(cand)
        s.commit()
        s.refresh(cand)
        for i, c in enumerate(cert_fields):
            summ = report.cert_summaries[i] if i < len(report.cert_summaries) else {}
            s.add(Certificate(tenant_id=tenant_id, candidate_id=cand.id, issuer=c.issuer, title=c.title,
                              issue_date=c.issue_date, valid_until=c.valid_until,
                              is_genuine=c.is_genuine_looking, is_current=summ.get("is_current")))
        rec = VerificationRecord(tenant_id=tenant_id, candidate_id=cand.id, kind="cv",
                                 risk=report.risk, score=float(report.score),
                                 flags=[s_.name for s_ in report.signals], report=report.model_dump())
        s.add(rec)
        s.add(AuditLog(tenant_id=tenant_id, action="fraud.assessed", severity="info",
                       detail={"risk": report.risk, "score": report.score, "signals": len(report.signals)}))
        s.commit()
        s.refresh(rec)
        return rec.id


def history(tenant_id: str, limit: int = 20) -> list[dict]:
    with Session(engine) as s:
        rows = s.exec(select(VerificationRecord).where(VerificationRecord.tenant_id == tenant_id)
                      .order_by(desc(VerificationRecord.created_at)).limit(limit)).all()
        return [{"id": r.id, "created_at": r.created_at.isoformat(), "risk": r.risk,
                 "score": r.score, "candidate_name": r.report.get("candidate_name"),
                 "flags": r.flags} for r in rows]


def get_record(tenant_id: str, record_id: str) -> dict | None:
    with Session(engine) as s:
        r = s.get(VerificationRecord, record_id)
        if not r or r.tenant_id != tenant_id:
            return None
        return {"id": r.id, "created_at": r.created_at.isoformat(), "risk": r.risk,
                "score": r.score, "report": r.report}
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_fraud_service.py tests/test_fraud_forensics.py tests/test_fraud_consistency.py tests/test_fraud_scoring.py tests/test_fraud_verify.py -q`
Expected: PASS (all). Then full suite: `uv run pytest -q` (P10 tests still green).

- [ ] **Step 6: Commit**

```bash
git add services/fraud.py core/models/fraud.py tests/test_fraud_service.py
git commit -m "feat(p4): fraud assessment orchestration + tenant-scoped persistence"
```

---

## Task 6: API routes + main wiring

**Files:**
- Create: `api/routes/fraud.py`
- Modify: `api/main.py` (the ONE allowed shared edit)

**Interfaces:**
- Consumes: `services.fraud`, `core.auth.current_principal`.
- Produces routes: `POST /agents/fraud/assess`, `GET /agents/fraud/history`, `GET /agents/fraud/records/{record_id}`.

- [ ] **Step 1: Implement `api/routes/fraud.py`**

```python
"""P4 Persowerk — CV & certificate fraud-signals API (authenticated, tenant-scoped)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from core.auth import Principal, current_principal
from services import fraud as svc

router = APIRouter(prefix="/agents/fraud", tags=["fraud"])


@router.post("/assess")
async def run_assess(
    cv: UploadFile | None = File(default=None),
    certs: list[UploadFile] = File(default=[]),
    github_handle: str = Form(default=""),
    links: str = Form(default=""),
    run_verify: bool = Form(default=True),
    principal: Principal = Depends(current_principal),
) -> dict:
    cv_in = (cv.filename or "cv", await cv.read()) if cv is not None else None
    cert_in = [(c.filename or "certificate", await c.read()) for c in certs]
    link_list = [x.strip() for x in links.split(",") if x.strip()]
    report = svc.assess(tenant_id=principal.tenant_id, cv=cv_in, certs=cert_in,
                        github_handle=github_handle or None, links=link_list, run_verify=run_verify)
    return report.model_dump()


@router.get("/history")
def fraud_history(principal: Principal = Depends(current_principal)) -> list[dict]:
    return svc.history(principal.tenant_id)


@router.get("/records/{record_id}")
def fraud_record(record_id: str, principal: Principal = Depends(current_principal)) -> dict:
    rec = svc.get_record(principal.tenant_id, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return rec
```

- [ ] **Step 2: Wire into `api/main.py`**

Change the import line `from api.routes import secure_intake` to `from api.routes import fraud, secure_intake`, and after `app.include_router(secure_intake.router)` add `app.include_router(fraud.router)`.

- [ ] **Step 3: Verify the app imports + routes register**

Run:
```bash
uv run python -c "from api.main import app; print([r.path for r in app.routes if 'fraud' in r.path])"
```
Expected: lists `/agents/fraud/assess`, `/agents/fraud/history`, `/agents/fraud/records/{record_id}`.

- [ ] **Step 4: Commit**

```bash
git add api/routes/fraud.py api/main.py
git commit -m "feat(p4): fraud API routes + router wiring"
```

---

## Task 7: Persowerk dashboard (Next.js)

**Files:**
- Create: `web/src/app/persowerk/page.tsx`
- Create: `web/src/app/persowerk/api.ts`

> Note: the task wrote `web/app/persowerk/**`; the real app uses `web/src/app/` (where `rheinmetall/page.tsx` lives). Follow the real structure. Co-locate the API client under the page dir so no shared `web/src/lib/*` file is edited.

**Interfaces:**
- Consumes the API from Task 6; reuses `@/components/ui` (`Card`, `Button`, `Badge`).

- [ ] **Step 1: Implement `web/src/app/persowerk/api.ts`**

```typescript
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface Signal {
  name: string;
  severity: "low" | "medium" | "high";
  category: string;
  evidence: string;
  why: string;
  weak: boolean;
  detail?: { heatmap_png_b64?: string; strong_ratio?: number } | null;
}

export interface FraudReport {
  candidate_name: string | null;
  risk: "LOW" | "MEDIUM" | "HIGH";
  score: number;
  summary: string;
  signals: Signal[];
  by_category: Record<string, Signal[]>;
  cert_summaries: {
    filename: string; decision: string; issuer: string | null; title: string | null;
    holder_name: string | null; valid_until: string | null; days_remaining: number | null; is_current: boolean;
  }[];
  extraction: Record<string, unknown>;
  verify_ran: boolean;
  methodology_note: string;
  llm_calls: number;
  agent_steps: number;
}

export interface HistoryRow {
  id: string; created_at: string; risk: string; score: number;
  candidate_name: string | null; flags: string[];
}

export async function postAssess(
  cv: File | null, certs: File[], githubHandle: string, links: string, runVerify: boolean,
): Promise<FraudReport> {
  const fd = new FormData();
  if (cv) fd.append("cv", cv);
  certs.forEach((c) => fd.append("certs", c));
  fd.append("github_handle", githubHandle);
  fd.append("links", links);
  fd.append("run_verify", String(runVerify));
  const res = await fetch(`${API}/agents/fraud/assess`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

export async function getHistory(): Promise<HistoryRow[]> {
  const res = await fetch(`${API}/agents/fraud/history`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}
```

- [ ] **Step 2: Implement `web/src/app/persowerk/page.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card } from "@/components/ui";
import { getHistory, postAssess, type FraudReport, type HistoryRow, type Signal } from "./api";

const SEV_TONE: Record<string, "red" | "amber" | "slate"> = { high: "red", medium: "amber", low: "slate" };
const RISK_BG: Record<string, string> = {
  HIGH: "border-red-300 bg-red-50", MEDIUM: "border-amber-300 bg-amber-50", LOW: "border-green-300 bg-green-50",
};
const CATEGORY_LABEL: Record<string, string> = {
  forensic: "📄 Document forensics", consistency: "🧩 Consistency", certificate: "🎓 Certificate",
  verification: "🔗 Public-footprint verification", injection: "🛡️ Prompt-injection",
};

function SignalCard({ s }: { s: Signal }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="flex items-center justify-between">
        <span className="font-medium">{s.name.replace(/_/g, " ")}</span>
        <span className="flex gap-1.5">
          {s.weak && <Badge tone="slate">weak</Badge>}
          <Badge tone={SEV_TONE[s.severity]}>{s.severity}</Badge>
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-800">{s.evidence}</p>
      <p className="mt-1 text-xs text-slate-500">{s.why}</p>
      {s.detail?.heatmap_png_b64 && (
        <img alt="ELA heatmap" className="mt-2 max-h-48 rounded border"
             src={`data:image/png;base64,${s.detail.heatmap_png_b64}`} />
      )}
    </div>
  );
}

export default function PersowerkPage() {
  const [cv, setCv] = useState<File | null>(null);
  const [certs, setCerts] = useState<File[]>([]);
  const [github, setGithub] = useState("");
  const [links, setLinks] = useState("");
  const [runVerify, setRunVerify] = useState(false);
  const [report, setReport] = useState<FraudReport | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshHistory() {
    try { setHistory(await getHistory()); } catch { /* API may be down */ }
  }
  useEffect(() => { refreshHistory(); }, []);

  async function run() {
    setBusy(true); setError(null); setReport(null);
    try {
      const r = await postAssess(cv, certs, github, links, runVerify);
      setReport(r);
      refreshHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 text-slate-900">
      <div className="mb-8 border-l-4 pl-4" style={{ borderColor: "#6b21a8" }}>
        <p className="text-xs font-semibold tracking-widest text-slate-500">PROBLEM 4 · PERSOWERK · TALENT / VERIFICATION</p>
        <h1 className="text-3xl font-bold">🔎 CV &amp; Certificate Authenticity Agent</h1>
        <p className="mt-1 text-slate-600">
          Cross-checks work history and skills, flags fabrication signals, and verifies certificates are real and
          current — <strong>each flag carries its exact evidence for a recruiter to review.</strong>
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-5">
          <h2 className="mb-3 text-lg font-semibold">Upload</h2>
          <label className="mb-1 block text-sm font-medium">CV (PDF / image)</label>
          <input type="file" className="mb-4 block w-full text-sm"
                 onChange={(e) => setCv(e.target.files?.[0] ?? null)} />
          <label className="mb-1 block text-sm font-medium">Certificate(s) (PDF / image)</label>
          <input type="file" multiple className="mb-4 block w-full text-sm"
                 onChange={(e) => setCerts(Array.from(e.target.files ?? []))} />
          <label className="mb-1 block text-sm font-medium">GitHub handle / URL (optional)</label>
          <input className="mb-4 w-full rounded-lg border border-slate-300 p-2 text-sm"
                 placeholder="github.com/username" value={github} onChange={(e) => setGithub(e.target.value)} />
          <label className="mb-1 block text-sm font-medium">Other links (comma-separated, optional)</label>
          <input className="mb-4 w-full rounded-lg border border-slate-300 p-2 text-sm"
                 value={links} onChange={(e) => setLinks(e.target.value)} />
          <label className="mb-4 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={runVerify} onChange={(e) => setRunVerify(e.target.checked)} />
            Run live GitHub/web verification (uses the LLM agent loop)
          </label>
          <Button onClick={run} disabled={busy || (!cv && certs.length === 0)}>
            {busy ? "Analysing…" : "Analyse documents"}
          </Button>
          {error && <p className="mt-3 text-sm text-red-700">⚠️ {error}</p>}
        </Card>

        <div className="space-y-4">
          {report && (
            <>
              <Card className={`p-5 ${RISK_BG[report.risk]}`}>
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold">Fraud-signal risk: {report.risk}</h2>
                  <span className="text-2xl font-bold">{report.score}<span className="text-base text-slate-500">/100</span></span>
                </div>
                <p className="mt-2 text-sm text-slate-700">{report.summary}</p>
                <p className="mt-3 rounded bg-white/70 p-2 text-xs text-slate-600">{report.methodology_note}</p>
              </Card>

              {Object.entries(report.by_category).map(([cat, sigs]) => (
                <Card key={cat} className="p-5">
                  <h3 className="mb-2 text-sm font-semibold">{CATEGORY_LABEL[cat] ?? cat}</h3>
                  <div className="space-y-2">{sigs.map((s, i) => <SignalCard key={i} s={s} />)}</div>
                </Card>
              ))}

              {report.cert_summaries.length > 0 && (
                <Card className="p-5">
                  <h3 className="mb-2 text-sm font-semibold">🎓 Certificates</h3>
                  <ul className="space-y-1.5 text-sm">
                    {report.cert_summaries.map((c, i) => (
                      <li key={i} className="flex items-center justify-between">
                        <span>{c.title ?? c.filename} {c.issuer ? `· ${c.issuer}` : ""}</span>
                        <Badge tone={c.is_current ? "green" : "amber"}>{c.decision.replace(/_/g, " ")}</Badge>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              <details className="rounded-xl border border-slate-200 bg-white p-4 text-xs">
                <summary className="cursor-pointer font-medium">Extracted data (raw)</summary>
                <pre className="mt-2 overflow-x-auto">{JSON.stringify(report.extraction, null, 2)}</pre>
              </details>
              <p className="text-xs text-slate-400">LLM calls: {report.llm_calls} · agent steps: {report.agent_steps}</p>
            </>
          )}

          <Card className="p-5">
            <h2 className="mb-2 text-lg font-semibold">History</h2>
            {history.length === 0 ? (
              <p className="text-sm text-slate-500">No assessments yet.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {history.map((h) => (
                  <li key={h.id} className="flex items-center justify-between">
                    <span>{new Date(h.created_at).toLocaleString()} · {h.candidate_name ?? "—"}</span>
                    <Badge tone={h.risk === "HIGH" ? "red" : h.risk === "MEDIUM" ? "amber" : "green"}>
                      {h.risk} {h.score}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </main>
  );
}
```

- [ ] **Step 3: Verify the web app builds/lints**

Run:
```bash
cd web && npx tsc --noEmit && npm run lint
```
Expected: no type errors / lint passes for the new files. (If `node_modules` missing: `npm install` first.)

- [ ] **Step 4: Commit**

```bash
git add web/src/app/persowerk/
git commit -m "feat(p4): Persowerk fraud-signals dashboard (Next.js)"
```

---

## Task 8: `.env.example`, `STATE.md`, manual verification

**Files:**
- Modify: `.env.example` (add `GITHUB_TOKEN`)
- Modify: `STATE.md` (mark Phase 1 P4 done; fill run notes)

- [ ] **Step 1: Add `GITHUB_TOKEN` to `.env.example`**

Under `# ---- Optional integrations ----`, after `FIRECRAWL_API_KEY=…`, add:
```
GITHUB_TOKEN=                  # raises the github_lookup rate limit (P4 verification); optional
```

- [ ] **Step 2: Update `STATE.md`** — in "Where we are", change the Phase 1 line to show P4 Persowerk done (forensics + consistency + verify + dashboard, offline tests green), and add the run note: web page at `/persowerk`, API `POST /agents/fraud/assess`.

- [ ] **Step 3: Full offline test suite**

Run: `uv run pytest -q`
Expected: all green (P4 + P10).

- [ ] **Step 4: Manual end-to-end (live, Gemini) — the demo proof**

```bash
# terminal 1
LLM_PROVIDER=gemini AUTH_MODE=dev uv run uvicorn api.main:app --port 8000
# terminal 2
cd web && npm run dev
```
Open `http://localhost:3000/persowerk`. Upload `hackathon_problems_20260620/questions/CVs_hackathon_20260620/CV_arjun_nair.pdf` + a certificate from `certificates_part_4/`. Confirm: risk badge + score render; forensic signals (Producer: WeasyPrint; certificate image: missing-EXIF) appear with evidence; consistency/cert signals render; methodology note + "no AI-text detector" disclosure visible; history updates. Optionally tick "Run live verification" with a real GitHub handle.

- [ ] **Step 5: Commit**

```bash
git add .env.example STATE.md docs/superpowers/plans/2026-06-20-persowerk-fraud-signals.md
git commit -m "docs(p4): env + STATE update; mark Persowerk flagship done"
```

- [ ] **Step 6: Open the PR** for `feat/fraud` (base `main`) summarising the agent, the deterministic/testable core, the "signals not verdict" framing, and the wanted-dep note (pikepdf for richer xref/incremental analysis).

---

## Self-Review

**1. Spec coverage:**
- Forensics (PDF metadata CreationDate vs ModDate, incremental updates, Producer/Creator chain, EXIF, missing-EXIF, ELA weak+capped) → Task 1. ✓
- Extract roles/dates/skills/cert issuer/id → existing `agents/fraud.py` extraction + `_extract_cv`/`_extract_cert` in Task 5. ✓ (QR-from-image is read by vision via the cert fields `notes`; explicit QR-decode is out of scope — no zbar dep; noted.)
- Consistency (overlaps/gaps, CV vs cert vs claims) → Task 2. ✓
- Verify (github_lookup public API w/ GITHUB_TOKEN, company/role web check; registry/OpenBadges only where public API exists — skipped honestly) → Tasks 4–5. ✓
- Risk score weighted LOW/MED/HIGH 0-100 + per-signal evidence; persist Candidate/Certificate/VerificationRecord tenant-scoped → Tasks 3, 5. ✓
- Dashboard upload + flags w/ evidence + "signal not verdict" + NO AI-text-detector (stated why) + history → Task 7. ✓
- Tests offline on ollama: forensics on known-edited PDF, consistency on overlaps, mocked github_lookup → Tasks 1,2,4 + service persistence Task 5. ✓
- `.env.example` GITHUB_TOKEN + reuse FIRECRAWL; STATE update; chunked commits; PR → Task 8. ✓

**2. Placeholder scan:** No TBD/TODO; every code step has complete code. ✓

**3. Type consistency:** `Signal` defined once (Task 1), imported by agents/services; `VerifyFindings`, `RiskAssessment`, `CVClaims(+email,+github)`, `CertFields`, `FraudReport`, `build_report`/`assess`/`persist`/`history`/`get_record` signatures match across Tasks 3–6. `by_category` is `dict[str, list[dict]]` (model_dump'd signals) consistently in `build_report` and the TS `FraudReport`. ✓

**Out of scope (stated honestly):** real issuer-registry verification at scale, LinkedIn scraping, AI-text detection, QR/barcode decoding (no zbar dep), pikepdf-level xref/object-stream forensics (dep not installed).
