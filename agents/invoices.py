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


class InvoiceFields(BaseModel):
    """Key fields read off a supplier invoice."""

    vendor: str | None = Field(description="Supplier / vendor name as printed")
    invoice_number: str | None = Field(description="Invoice number / Rechnungsnummer")
    date: str | None = Field(description="Invoice date as printed")
    currency: str | None = Field(description="Currency code or symbol, e.g. EUR, USD, €, $")
    total: str | None = Field(description="Final gross total payable, as printed incl. symbol")
    vat_rate: str | None = Field(description="VAT / MwSt / USt rate, e.g. '19%' or '0%'")
    category: str | None = Field(description="High-level category of what was bought")
    language: str | None = Field(description="Language of the invoice, e.g. German or English")
    confidence: float = Field(description="0-100: how legible/certain the read was", ge=0, le=100)
    notes: str | None = Field(description="Anything unusual (illegible, stained, ambiguous total)")


class TriageResult(BaseModel):
    department: str
    confidence: float
    fields: InvoiceFields
    reasons: list[str]


def route(category: str | None) -> str:
    """Deterministically map a category string to the destination department."""
    cat = (category or "").lower()
    for keywords, dept in _ROUTING:
        if any(k in cat for k in keywords):
            return dept
    return DEFAULT_DEPT


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
