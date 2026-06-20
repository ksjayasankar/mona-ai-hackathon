"""Problem 3 — Leistenschneider: Work-Permit Validator (productized core).

Boxes to check (from the customer brief):
  [x] take in a document
  [x] validate that it IS actually a work/residence permit
  [x] confirm or deny WITH an accuracy / confidence percentage
  [x] return the date it's valid until

Approach: the model reads the document NATIVELY (PDF or photo — no OCR) and extracts the
permit fields TOGETHER WITH a verbatim quote-span for each critical field, so we can
GROUND every value in the printed text. A deterministic `decide()` then:
  • keeps "is it a permit?" SEPARATE from "is employment allowed?";
  • verifies each value is grounded in its quote (never trusts a hallucinated date);
  • scores an ITEMIZED, explainable confidence rubric (every deduction is surfaced);
  • consults the §AufenthG corpus (agents.aufenthg) to resolve permits where work
    authorization is IMPLIED by statute rather than printed, and cites the legal basis;
  • routes anything below the auto-decision threshold (or implied-by-statute) to a human.

`decide()` is PURE (no LLM, no web, no DB) so the whole verdict is unit-testable offline.
Persistence + the review queue live in services/permits.py, never here. `TODAY` is
injectable (defaults to `date.today()`) so tests and the demo can pin it.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from agents import aufenthg
from core import ingest, llm

# Auto-decide threshold. A would-be VALID verdict below this confidence is routed to a
# human instead (EU-AI-Act high-risk oversight: the system never auto-issues a weak YES).
THRESHOLD = 80.0

# Rubric weights (sum to 100). Each is a transparent, explainable line item.
_W_CLASSIFY = 20.0   # classification certainty / legibility of the read
_W_VALIDUNTIL = 30.0  # 'valid until' date read AND grounded (the load-bearing field)
_W_DOCTYPE = 15.0    # document type read AND grounded
_W_EMPLOY = 20.0     # work-authorization clause explicit AND grounded
_W_LEGAL = 15.0      # legal basis present AND matched to the §AufenthG corpus

SYSTEM = (
    "You are a German immigration-document checker. You are shown a single document. "
    "First decide whether it is a residence/work permit DOCUMENT (Aufenthaltstitel / "
    "Aufenthaltserlaubnis / Blaue Karte EU / Niederlassungserlaubnis / work visa) — it still "
    "COUNTS as one even if it restricts or prohibits employment (e.g. a student permit under "
    "§ 16b AufenthG). Set is_work_permit=True for any such residence-permit document, and record "
    "work authorization SEPARATELY in employment_allowed (look for 'Erwerbstätigkeit/Beschäftigung "
    "gestattet' vs 'nicht gestattet'). "
    "GROUNDING IS MANDATORY: for valid_until, document_type and the employment clause you MUST also "
    "return the EXACT printed text you read each value from, copied VERBATIM into the matching "
    "*_quote field (do not paraphrase, translate or invent). If a value is not printed, set both it "
    "and its quote to null — never guess. Extract fields exactly as printed. Dates are DD.MM.YYYY."
)

_EXTRACT_INSTRUCTION = (
    "Extract the permit fields. Set is_work_permit honestly. For valid_until, document_type and the "
    "employment clause, copy the exact printed text into the *_quote fields verbatim."
)


class PermitFields(BaseModel):
    """Fields read off a (possible) work/residence permit, each critical field grounded."""

    is_work_permit: bool = Field(description="True if this is a residence/work permit document (Aufenthaltstitel/Aufenthaltserlaubnis/Blue Card/Niederlassungserlaubnis/visa), EVEN IF it restricts or bans employment")
    document_type: str | None = Field(default=None, description="Printed document type, e.g. 'Aufenthaltserlaubnis'")
    document_type_quote: str | None = Field(default=None, description="VERBATIM printed text the document_type was read from")
    holder_name: str | None = Field(default=None, description="Full name of the permit holder")
    nationality: str | None = None
    legal_basis: str | None = Field(default=None, description="e.g. '§ 18a AufenthG'")
    issue_date: str | None = Field(default=None, description="Date of issue as printed, DD.MM.YYYY")
    valid_until: str | None = Field(default=None, description="'Gültig bis' / valid-until date, DD.MM.YYYY")
    valid_until_quote: str | None = Field(default=None, description="VERBATIM printed text the valid_until date was read from")
    employment_allowed: bool | None = Field(default=None, description="True if the remarks permit employment, False if prohibited, null if not stated")
    employment_quote: str | None = Field(default=None, description="VERBATIM printed remarks about employment (e.g. 'Beschäftigung gestattet.')")
    extraction_confidence: float = Field(description="0-100, how legible/certain the read was", ge=0, le=100)
    notes: str | None = Field(default=None, description="Anything unusual (forgery signs, missing seal, etc.)")


class RubricItem(BaseModel):
    """One transparent line of the confidence score."""
    label: str
    weight: float            # max points this line can contribute
    earned: float            # points actually earned
    grounded: bool | None    # was the underlying value grounded in the document?
    detail: str              # human-readable explanation, including any deduction


class PermitResult(BaseModel):
    decision: str                       # VALID | EXPIRED | NOT_A_PERMIT | NOT_WORK_AUTHORIZED | NEEDS_REVIEW
    confidence: float
    valid_until: str | None
    days_remaining: int | None
    employment_status: str              # permitted | prohibited | implied | restricted | unknown | n/a
    fields: PermitFields
    rubric: list[RubricItem]
    legal_basis_citation: str | None
    needs_review: bool
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


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def _grounded(value: str | None, quote: str | None) -> bool:
    """A value is grounded only if it appears verbatim inside its quoted printed text."""
    if not value or not quote:
        return False
    return _norm(str(value)) in _norm(quote)


def _employment_grounded(allowed: bool | None, quote: str | None) -> bool:
    """The employment bool is grounded only if the quote actually says so (de/en)."""
    if allowed is None or not quote:
        return False
    q = quote.lower()
    neg = "nicht gestattet" in q or "not permitted" in q or "untersagt" in q or "not allowed" in q
    pos = ("gestattet" in q or "permitted" in q or "erlaubt" in q or "allowed" in q) and not neg
    return neg if allowed is False else pos


def _deduct(weight: float, kept: float, what: str) -> str:
    # only flag a deduction the reviewer would care about; sub-0.5 rounding noise
    # (e.g. a 99% read earning 19.8/20) reads as a passed check, not a "-0".
    return f"-{weight - kept:.0f}: {what}" if (weight - kept) >= 0.5 else what


def decide(fields: PermitFields, *, today: date | None = None,
           use_rag: bool = False, provider: str | None = None) -> PermitResult:
    """Pure, deterministic verdict from extracted fields. No LLM / web / DB."""
    today = today or date.today()
    f = fields
    rule = aufenthg.resolve(f.legal_basis, f.document_type, use_rag=use_rag, provider=provider)
    citation = f"{rule.source}: {rule.note}" if rule else None

    # ---- not a permit: a clean, separate classification verdict --------------
    if not f.is_work_permit:
        conf = round(f.extraction_confidence, 1)
        return PermitResult(
            decision="NOT_A_PERMIT", confidence=conf, valid_until=None, days_remaining=None,
            employment_status="n/a", fields=f, legal_basis_citation=None, needs_review=False,
            rubric=[RubricItem(label="Document classification", weight=100.0, earned=conf,
                               grounded=_grounded(f.document_type, f.document_type_quote),
                               detail=f"Not a residence/work permit (read as '{f.document_type or 'unknown'}').")],
            reasons=["This document is not a residence/work permit."] + ([f.notes] if f.notes else []),
        )

    # ---- grounding checks ----------------------------------------------------
    vu_grounded = _grounded(f.valid_until, f.valid_until_quote)
    dt_grounded = _grounded(f.document_type, f.document_type_quote)
    emp_grounded = _employment_grounded(f.employment_allowed, f.employment_quote)
    valid_until = _parse_de_date(f.valid_until)
    days = (valid_until - today).days if valid_until else None

    # ---- itemized, explainable rubric ---------------------------------------
    rubric: list[RubricItem] = []
    classify = round(_W_CLASSIFY * f.extraction_confidence / 100, 1)
    rubric.append(RubricItem(label="Classification & legibility", weight=_W_CLASSIFY, earned=classify,
                             grounded=None, detail=_deduct(_W_CLASSIFY, classify, f"model read confidence {f.extraction_confidence:.0f}%")))

    if valid_until and vu_grounded:
        vu_earned, vu_detail = _W_VALIDUNTIL, f"'{f.valid_until}' read and grounded in the document"
    elif valid_until:
        vu_earned, vu_detail = round(_W_VALIDUNTIL / 2, 1), f"'valid until' read as '{f.valid_until}' but NOT grounded in any quoted text"
    else:
        vu_earned, vu_detail = 0.0, "no 'valid until' date could be read"
    rubric.append(RubricItem(label="'Valid until' date read & grounded", weight=_W_VALIDUNTIL,
                             earned=vu_earned, grounded=vu_grounded, detail=_deduct(_W_VALIDUNTIL, vu_earned, vu_detail)))

    if f.document_type and dt_grounded:
        dt_earned, dt_detail = _W_DOCTYPE, f"document type '{f.document_type}' grounded"
    elif f.document_type:
        dt_earned, dt_detail = round(_W_DOCTYPE / 2, 1), f"document type '{f.document_type}' not grounded in any quoted text"
    else:
        dt_earned, dt_detail = 0.0, "no document type read"
    rubric.append(RubricItem(label="Document type read & grounded", weight=_W_DOCTYPE,
                             earned=dt_earned, grounded=dt_grounded, detail=_deduct(_W_DOCTYPE, dt_earned, dt_detail)))

    if f.employment_allowed is not None and emp_grounded:
        emp_earned, emp_detail = _W_EMPLOY, "work-authorization clause printed and grounded"
    elif rule and rule.default_work in ("permitted", "restricted", "prohibited"):
        emp_earned = round(_W_EMPLOY / 2, 1)
        emp_detail = f"authorization not printed; {rule.default_work} by statute ({rule.source}) — needs human confirmation"
    else:
        emp_earned, emp_detail = 0.0, "work authorization neither printed nor resolvable from the legal basis"
    rubric.append(RubricItem(label="Work-authorization clause explicit & grounded", weight=_W_EMPLOY,
                             earned=emp_earned, grounded=emp_grounded if f.employment_allowed is not None else False,
                             detail=_deduct(_W_EMPLOY, emp_earned, emp_detail)))

    if f.legal_basis and rule:
        lb_earned, lb_detail = _W_LEGAL, f"legal basis recognised ({rule.source})"
    elif f.legal_basis:
        lb_earned, lb_detail = round(_W_LEGAL / 2, 1), f"legal basis '{f.legal_basis}' printed but not in the §AufenthG corpus"
    else:
        lb_earned, lb_detail = 0.0, "no legal basis printed"
    rubric.append(RubricItem(label="Legal basis present & matched to §AufenthG", weight=_W_LEGAL,
                             earned=lb_earned, grounded=None, detail=_deduct(_W_LEGAL, lb_earned, lb_detail)))

    confidence = round(sum(i.earned for i in rubric), 1)

    # ---- decision (is-a-permit kept separate from employment) ----------------
    reasons: list[str] = []
    employment_status = "unknown"

    if valid_until is None or not vu_grounded:
        decision = "NEEDS_REVIEW"
        reasons.append("No 'valid until' date could be read — manual check required." if valid_until is None
                       else "The 'valid until' date is not grounded in the printed text — could not verify it; manual check required.")
    elif days < 0:
        decision = "EXPIRED"
        reasons.append(f"Expired on {f.valid_until} ({abs(days)} days ago).")
    else:
        reasons.append(f"Permit is current — valid until {f.valid_until} ({days} days remaining).")
        if f.employment_allowed is False and emp_grounded:
            decision, employment_status = "NOT_WORK_AUTHORIZED", "prohibited"
            reasons.append("The remarks PROHIBIT employment ('Erwerbstätigkeit nicht gestattet') — not valid for a work placement.")
        elif f.employment_allowed is True and emp_grounded:
            decision, employment_status = "VALID", "permitted"
            reasons.append("The remarks explicitly permit employment.")
        elif rule and rule.default_work == "permitted":
            decision, employment_status = "NEEDS_REVIEW", "implied"
            reasons.append(f"Employment is permitted by statute ({rule.source}), but the authorization is "
                           "NOT printed on this document — a human must confirm before a binding decision.")
        elif rule and rule.default_work == "prohibited":
            decision, employment_status = "NOT_WORK_AUTHORIZED", "prohibited"
            reasons.append(f"By statute ({rule.source}) this permit type does not authorize employment.")
        elif rule and rule.default_work == "restricted":
            decision, employment_status = "NEEDS_REVIEW", "restricted"
            reasons.append(f"By statute ({rule.source}) employment is restricted for this permit type"
                           + (" — check the Zusatzblatt / Nebenbestimmungen." if rule.zusatzblatt_required else "."))
        else:
            decision = "NEEDS_REVIEW"
            reasons.append("Work authorization is neither printed nor resolvable from the legal basis — manual check required.")

    # ---- threshold: never auto-issue a weak YES ------------------------------
    if decision == "VALID" and confidence < THRESHOLD:
        decision = "NEEDS_REVIEW"
        reasons.append(f"Confidence {confidence:.0f}% is below the {THRESHOLD:.0f}% auto-decision threshold — routed to human review.")

    if rule:
        reasons.append(f"Legal basis: {rule.citation} ({rule.source}).")
    if f.notes:
        reasons.append(f.notes)

    return PermitResult(
        decision=decision, confidence=confidence, valid_until=f.valid_until, days_remaining=days,
        employment_status=employment_status, fields=f, rubric=rubric, legal_basis_citation=citation,
        needs_review=(decision == "NEEDS_REVIEW"), reasons=reasons,
    )


def extract_fields(blocks: list[dict], *, provider: str | None = None) -> PermitFields:
    """Single structured pass: read the grounded permit fields from content blocks."""
    content = [*blocks, {"type": "text", "text": _EXTRACT_INSTRUCTION}]
    return llm.extract(PermitFields, content, system=SYSTEM, provider=provider)


def validate_blocks(blocks: list[dict], *, today: date | None = None,
                    use_rag: bool = True, provider: str | None = None) -> PermitResult:
    """Validate already-ingested content blocks (e.g. an uploaded file's bytes)."""
    f = extract_fields(blocks, provider=provider)
    return decide(f, today=today, use_rag=use_rag, provider=provider)


def validate_permit(file: str | Path, *, today: date | None = None,
                    use_rag: bool = True, provider: str | None = None) -> PermitResult:
    """Read one document NATIVELY (no OCR) and return a grounded verdict."""
    return validate_blocks(ingest.file_to_blocks(file), today=today, use_rag=use_rag, provider=provider)
