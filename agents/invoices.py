"""Problem 1 — Globus Group: Invoice Triage Agent.

Boxes to check (from the customer brief):
  [x] read an invoice in ANY format (PDF, PNG photo, DOCX) and language (DE/EN)
  [x] extract vendor, invoice number, date, currency, total, VAT rate, category
  [x] ROUTE it to the correct department
  [x] flag it for a human to confirm ("Confirm & route to <dept>")

Approach (mirrors the golden permit agent): Claude reads the document natively (PDF
or photo) or via light text extraction (DOCX), extracts the invoice fields with
core.llm.extract, then a deterministic category -> department map decides routing so
the destination never depends on the model's mood. Messy scans (coffee stain, angled
photo, faded copy) are handled by Claude's native vision — no OCR stack needed.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from core import ingest, llm

SYSTEM = (
    "You are an accounts-payable clerk for Globus Group. You are shown a single supplier "
    "invoice, which may be a clean PDF, a Word document, or a messy phone photo / scan "
    "(coffee stain, faded, angled). It may be in German or English. Read the fields exactly "
    "as printed. Do not invent values; use null when a field is not present. The 'total' is "
    "the final gross amount payable (incl. VAT). Pick the single best high-level 'category' "
    "for what was bought (e.g. Energy, Gas, Electricity, Utilities, Software, Cloud, SaaS, "
    "Subscription, Hardware, IT, Hotel, Travel, Office supplies, Consulting, Professional "
    "services)."
)

# category keyword -> department. First match wins; everything else -> Finance Review.
_ROUTING: list[tuple[tuple[str, ...], str]] = [
    (("energy", "gas", "electricity", "strom", "utilit", "power", "water"), "Facilities"),
    (("software", "cloud", "saas", "subscription", "hardware", "it", "license", "licence",
      "internet", "telephone", "telekom"), "IT"),
    (("hotel", "travel", "flight", "train", "lodging", "accommodation"), "Travel & Expenses"),
    (("office supplies", "office supply", "stationery", "bürobedarf", "buerobedarf", "supplies"),
     "Procurement"),
    (("consulting", "professional services", "advisory", "legal", "audit"), "Finance Approval"),
]
DEFAULT_DEPT = "Finance Review"


class LineItem(BaseModel):
    """One line on the invoice (best-effort — many scans won't itemize cleanly)."""

    description: str | None = Field(default=None, description="What the line is for")
    quantity: str | None = Field(default=None, description="Quantity as printed")
    amount: str | None = Field(default=None, description="Line amount as printed, incl. symbol")


class InvoiceFields(BaseModel):
    """Key fields read off a supplier invoice, with per-field grounding + confidence.

    `evidence` maps a field name -> the VERBATIM printed text the value was read from
    (the "we read it here" span). `field_confidence` maps a field name -> 0-100. A field
    that is low-confidence or has no evidence is treated as ungrounded and flagged for a
    human (see `invoice_status`)."""

    # Core identifying fields are REQUIRED keys (nullable values). Requiring them in the
    # JSON schema forces a constrained/small model to actually look for each value instead
    # of silently omitting it; it may still emit null when a field is genuinely absent.
    vendor: str | None = Field(description="Supplier / vendor name as printed")
    invoice_number: str | None = Field(description="Invoice number / Rechnungsnummer")
    date: str | None = Field(description="Invoice date as printed")
    currency: str | None = Field(description="Currency code or symbol, e.g. EUR, USD, €, $")
    total: str | None = Field(description="Final gross total payable, as printed incl. symbol")
    vat_rate: str | None = Field(description="VAT / MwSt / USt rate, e.g. '19%' or '0%'")
    category: str | None = Field(description="High-level category of what was bought")
    # Extended fields — optional (richer when the model/scan supports it).
    due_date: str | None = Field(default=None, description="Payment due date / Fälligkeit, if printed")
    po_number: str | None = Field(default=None, description="Purchase-order number / Bestellnummer, if printed")
    net_amount: str | None = Field(default=None, description="Net amount (before VAT), as printed")
    vat_amount: str | None = Field(default=None, description="VAT amount (the money, not the rate), as printed")
    language: str | None = Field(default=None, description="Language of the invoice, e.g. German or English")
    line_items: list[LineItem] = Field(default_factory=list, description="Line items, if legible")
    confidence: float = Field(default=0.0, description="0-100: overall legibility/certainty", ge=0, le=100)
    source_span: str | None = Field(
        default=None, description="Where this invoice came from in the source — a page/heading or "
        "verbatim snippet that marks the start of THIS invoice (for multi-invoice documents)")
    evidence: dict[str, str] = Field(
        default_factory=dict, description="field name -> the verbatim printed text it was read from")
    field_confidence: dict[str, float] = Field(
        default_factory=dict, description="field name -> 0-100 confidence for that single field")
    notes: str | None = Field(default=None, description="Anything unusual (illegible, stained, ambiguous total)")


class TriageResult(BaseModel):
    department: str
    confidence: float
    fields: InvoiceFields
    reasons: list[str]


# Fields that must be grounded + confident before an invoice can skip human review.
CRITICAL_FIELDS: tuple[str, ...] = ("vendor", "total", "date")
CONF_THRESHOLD = 70.0
STATUS_PENDING = "pending"            # grounded + confident -> ready for one-click approval
STATUS_NEEDS_REVIEW = "needs_review"  # something below the bar -> a human must confirm first


def route(category: str | None) -> str:
    """Deterministically map a category string to the destination department."""
    cat = (category or "").lower()
    for keywords, dept in _ROUTING:
        if any(k in cat for k in keywords):
            return dept
    return DEFAULT_DEPT


def _norm(s) -> str:
    """Lowercase, strip everything but alphanumerics (case/space/punct-insensitive)."""
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _digits(s) -> str:
    """Digits only — normalizes money across DE/EN formatting (1.240,00 € == €1,240.00)."""
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def dupe_key(f: InvoiceFields) -> str:
    """Near-match key: vendor + invoice number only. A second invoice sharing this key
    but with a different total is a 'possible duplicate / amended', not an exact re-send."""
    return "·".join([_norm(f.vendor), _norm(f.invoice_number)])


def fingerprint(f: InvoiceFields) -> str:
    """Exact-duplicate fingerprint: normalized vendor + invoice number + total + date."""
    return "·".join([_norm(f.vendor), _norm(f.invoice_number), _digits(f.total), _digits(f.date)])


def invoice_status(f: InvoiceFields, threshold: float = CONF_THRESHOLD) -> str:
    """The human-confirm gate. An invoice is PENDING (ready for one-click approval) only
    when every critical field is grounded (has evidence) AND at/above the confidence
    threshold; otherwise it is held for human review."""
    for k in CRITICAL_FIELDS:
        conf = f.field_confidence.get(k, f.confidence)
        grounded = bool(f.evidence.get(k))
        if conf < threshold or not grounded:
            return STATUS_NEEDS_REVIEW
    return STATUS_PENDING


class InvoiceBatch(BaseModel):
    """Wrapper so the model can return a LIST of invoices from one email/document."""

    invoices: list[InvoiceFields] = Field(
        default_factory=list,
        description="One object per DISTINCT invoice found. If the content holds several "
                    "invoices (multiple pages, or several invoices concatenated in one file "
                    "or email), return one object for EACH of them.")


class SuggestedDept(BaseModel):
    department: str = Field(description="Best destination department for this invoice")
    reason: str = Field(description="One short sentence explaining the choice")


_SPLIT_SYSTEM = SYSTEM + (
    " The content may contain MORE THAN ONE invoice (several pages, or several invoices in "
    "one file or email). Return one object per DISTINCT invoice. For every field you fill, "
    "also add an entry to `evidence` with the exact printed text you read it from, and an "
    "entry to `field_confidence` with a 0-100 score for that single field. Set `source_span` "
    "to a short snippet that marks where each invoice begins."
)

_DEPT_SYSTEM = (
    "You are an accounts-payable lead deciding which internal department should own a "
    "supplier invoice that did not match any routing rule. Choose ONE concrete department "
    "(e.g. Facilities, IT, Marketing, Procurement, HR, Travel & Expenses, Legal, Finance "
    "Approval) and give a one-line reason. Be decisive."
)


def split_invoices(content, *, provider: str | None = None) -> list[InvoiceFields]:
    """Segment an email/document into N invoices, each with grounded fields + confidence.

    `content` is Claude/Gemini content blocks (text and/or pdf/image). One invoice in →
    a 1-element list; a 3-invoice document in → a 3-element list. Routing + dedupe happen
    downstream (deterministically), per invoice."""
    blocks = list(content)
    blocks.append({"type": "text", "text": "List EVERY invoice in the content as a separate object."})
    batch = llm.extract(InvoiceBatch, blocks, system=_SPLIT_SYSTEM, provider=provider)
    return batch.invoices


def suggest_department(f: InvoiceFields, *, provider: str | None = None) -> SuggestedDept:
    """LLM fallback used only when the deterministic table falls through to Finance Review:
    suggest a destination department + a one-line reason (a hint for the human, not a rule)."""
    prompt = (
        f"Invoice vendor: {f.vendor or 'unknown'}. Category read as: {f.category or 'unknown'}. "
        f"VAT rate: {f.vat_rate or 'n/a'}. Total: {f.total or 'unknown'}.\n"
        "It did not match any routing rule. Which department should own it, and why?"
    )
    return llm.extract(SuggestedDept, prompt, system=_DEPT_SYSTEM, provider=provider)


def triage_invoice(file: str | Path) -> TriageResult:
    """Read one invoice file and return the extracted fields + routed department."""
    blocks = ingest.file_to_blocks(file)
    blocks.append({"type": "text", "text": "Extract the invoice fields and pick one category."})
    f = llm.extract(InvoiceFields, blocks, system=SYSTEM)

    dept = route(f.category)
    reasons: list[str] = []
    reasons.append(f"Vendor: {f.vendor or 'unknown'} · Total: {f.total or 'unknown'} "
                   f"({f.currency or '—'}).")
    if f.category:
        reasons.append(f"Category read as '{f.category}' → routed to {dept}.")
    else:
        reasons.append(f"No clear category → routed to {dept} for a human to sort.")
    if f.vat_rate:
        reasons.append(f"VAT rate {f.vat_rate}.")
    if dept == DEFAULT_DEPT:
        reasons.append("Did not match a known department rule — flagged for Finance to review.")
    if f.notes:
        reasons.append(f.notes)

    return TriageResult(
        department=dept,
        confidence=round(f.confidence, 1),
        fields=f,
        reasons=reasons,
    )
