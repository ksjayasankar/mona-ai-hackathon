"""Problem 3 — Leistenschneider: Work-Permit Validator.

Boxes to check (from the customer brief):
  [x] take in a document
  [x] validate that it IS actually a work/residence permit
  [x] confirm or deny WITH an accuracy / confidence percentage
  [x] return the date it's valid until

Approach: Claude reads the document natively (PDF or photo), extracts the permit
fields, then we apply a deterministic validity rule (is it a permit? is "valid until"
in the future? is employment allowed?) so the verdict doesn't depend on the model's
mood. German residence permits ("Aufenthaltstitel") are the primary case.

This module is the GOLDEN TEMPLATE for the other document agents: pydantic schema +
core.llm.extract + a small deterministic post-rule + a plain-language verdict.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from core import ingest, llm

TODAY = date(2026, 6, 20)  # hackathon "today"; keep deterministic for the demo

SYSTEM = (
    "You are a German immigration-document checker. You are shown a single document. "
    "Decide whether it is a residence/work permit (Aufenthaltstitel / Aufenthaltserlaubnis / "
    "Blue Card / work visa) and extract its fields exactly as printed. Do not invent values; "
    "use null when a field is not present. Read dates in DD.MM.YYYY format."
)


class PermitFields(BaseModel):
    """Fields read off a (possible) work/residence permit."""

    is_work_permit: bool = Field(description="True only if this document is a residence/work permit")
    document_type: str | None = Field(description="Printed document type, e.g. 'Aufenthaltserlaubnis'")
    holder_name: str | None = Field(description="Full name of the permit holder")
    nationality: str | None = None
    legal_basis: str | None = Field(description="e.g. '§ 18a AufenthG'")
    issue_date: str | None = Field(description="Date of issue as printed, DD.MM.YYYY")
    valid_until: str | None = Field(description="'Gültig bis' / valid-until date, DD.MM.YYYY")
    employment_allowed: bool | None = Field(description="True if the remarks permit employment")
    extraction_confidence: float = Field(description="0-100, how legible/certain the read was", ge=0, le=100)
    notes: str | None = Field(description="Anything unusual (forgery signs, missing seal, etc.)")


class PermitResult(BaseModel):
    decision: str          # VALID | EXPIRED | NOT_A_PERMIT
    confidence: float
    valid_until: str | None
    days_remaining: int | None
    fields: PermitFields
    reasons: list[str]


def _parse_de_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def validate_permit(file: str | Path) -> PermitResult:
    """Validate one file and return a verdict."""
    blocks = ingest.file_to_blocks(file)
    blocks.append({"type": "text", "text": "Extract the permit fields. Set is_work_permit honestly."})
    f = llm.extract(PermitFields, blocks, system=SYSTEM)

    reasons: list[str] = []
    if not f.is_work_permit:
        return PermitResult(
            decision="NOT_A_PERMIT",
            confidence=round(f.extraction_confidence, 1),
            valid_until=None, days_remaining=None, fields=f,
            reasons=["Document is not a residence/work permit."] + ([f.notes] if f.notes else []),
        )

    valid_until = _parse_de_date(f.valid_until)
    days = (valid_until - TODAY).days if valid_until else None

    if valid_until is None:
        decision, base = "NEEDS_REVIEW", 60.0
        reasons.append("Could not read a 'valid until' date.")
    elif days < 0:
        decision, base = "EXPIRED", 90.0
        reasons.append(f"Expired on {f.valid_until} ({abs(days)} days ago).")
    elif f.employment_allowed is False:
        # current residence permit, but employment is prohibited -> invalid for a work placement
        decision, base = "NOT_WORK_AUTHORIZED", 88.0
        reasons.append(
            f"Residence permit is current (valid until {f.valid_until}), but the remarks "
            f"PROHIBIT employment — not valid for a work placement."
        )
    else:
        decision, base = "VALID", 90.0
        reasons.append(f"Valid until {f.valid_until} ({days} days remaining).")
        if f.employment_allowed:
            reasons.append("Remarks permit employment.")
    if f.legal_basis:
        reasons.append(f"Legal basis: {f.legal_basis}.")
    if f.notes:
        reasons.append(f.notes)

    # blend deterministic rule confidence with the model's read confidence
    confidence = round(min(base, 0.5 * base + 0.5 * f.extraction_confidence), 1)
    return PermitResult(
        decision=decision, confidence=confidence, valid_until=f.valid_until,
        days_remaining=days, fields=f, reasons=reasons,
    )
