"""P3 Leistenschneider — Work-Permit Validation service (tenant-scoped, persisted, audited).

Pipeline:
  1. INGEST   — uploaded bytes -> content blocks (PDF/image read NATIVELY, no OCR).
  2. VALIDATE — agents.permits.validate_blocks: one structured pass -> grounded fields ->
                deterministic verdict + itemized rubric + §AufenthG consult.
  3. PERSIST  — PermitCheck (+ full grounded payload) + AuditLog, scoped to the tenant.
  4. OVERSIGHT— below-threshold / implied-by-statute checks (needs_review) sit in a
                human-review queue; a reviewer confirm/override is recorded in ReviewAction.
                The system never auto-issues a binding decision; the human can always override.

agents/permits.py stays PURE logic; all persistence lives here.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlmodel import Session, desc, select

from agents import permits
from agents.permits import PermitResult
from core import ingest
from core.db import engine
from core.models import AuditLog, PermitCheck, ReviewAction

_DECISIONS = {"VALID", "EXPIRED", "NOT_A_PERMIT", "NOT_WORK_AUTHORIZED", "NEEDS_REVIEW"}


# --------------------------------------------------------------------------- #
# process: ingest -> validate -> persist
# --------------------------------------------------------------------------- #
def process(data: bytes, filename: str, *, tenant_id: str,
            today: date | None = None, provider: str | None = None) -> dict:
    blocks = ingest.bytes_to_blocks(data, Path(filename).suffix, filename)
    result = permits.validate_blocks(blocks, today=today, provider=provider)
    return save_check(tenant_id, filename, result)


def save_check(tenant_id: str, filename: str | None, r: PermitResult) -> dict:
    """Persist a validated result + audit it. Returns the stored check as a dict."""
    with Session(engine) as s:
        check = PermitCheck(
            tenant_id=tenant_id, filename=filename,
            decision=r.decision, confidence=r.confidence, valid_until=r.valid_until,
            days_remaining=r.days_remaining, employment_status=r.employment_status,
            holder_name=r.fields.holder_name, document_type=r.fields.document_type,
            legal_basis=r.fields.legal_basis, legal_basis_citation=r.legal_basis_citation,
            needs_review=r.needs_review, status="pending",
            fields=r.fields.model_dump(), rubric=[i.model_dump() for i in r.rubric], reasons=r.reasons,
        )
        s.add(check)
        s.add(AuditLog(tenant_id=tenant_id, action="permit.checked", severity="info",
                       detail={"decision": r.decision, "confidence": r.confidence,
                               "valid_until": r.valid_until, "needs_review": r.needs_review}))
        if r.needs_review:
            s.add(AuditLog(tenant_id=tenant_id, action="permit.review_required", severity="warning",
                           detail={"confidence": r.confidence, "reasons": r.reasons}))
        s.commit()
        s.refresh(check)
        return _check_dict(check)


# --------------------------------------------------------------------------- #
# read: history, review queue, single check
# --------------------------------------------------------------------------- #
def history(tenant_id: str, limit: int = 20) -> list[dict]:
    with Session(engine) as s:
        rows = s.exec(select(PermitCheck).where(PermitCheck.tenant_id == tenant_id)
                      .order_by(desc(PermitCheck.created_at)).limit(limit)).all()
        return [_check_summary(c) for c in rows]


def review_queue(tenant_id: str, limit: int = 50) -> list[dict]:
    with Session(engine) as s:
        rows = s.exec(select(PermitCheck)
                      .where(PermitCheck.tenant_id == tenant_id, PermitCheck.needs_review == True,  # noqa: E712
                             PermitCheck.status == "pending")
                      .order_by(desc(PermitCheck.created_at)).limit(limit)).all()
        return [_check_dict(c) for c in rows]


def get_check(tenant_id: str, check_id: str) -> dict | None:
    with Session(engine) as s:
        c = s.get(PermitCheck, check_id)
        return _check_dict(c) if c and c.tenant_id == tenant_id else None


def review_history(tenant_id: str, check_id: str) -> list[dict]:
    with Session(engine) as s:
        rows = s.exec(select(ReviewAction)
                      .where(ReviewAction.tenant_id == tenant_id, ReviewAction.permit_check_id == check_id)
                      .order_by(desc(ReviewAction.created_at))).all()
        return [{"id": a.id, "reviewer": a.reviewer, "outcome": a.outcome,
                 "override_decision": a.override_decision, "note": a.note,
                 "created_at": a.created_at.isoformat()} for a in rows]


# --------------------------------------------------------------------------- #
# oversight: confirm / override (human-in-the-loop)
# --------------------------------------------------------------------------- #
def review(tenant_id: str, check_id: str, *, reviewer: str, outcome: str,
           override_decision: str | None = None, note: str | None = None) -> dict | None:
    """Record a human decision. outcome='confirmed' keeps the recommendation;
    'overridden' replaces the decision with override_decision. Always audited."""
    if outcome not in ("confirmed", "overridden"):
        raise ValueError("outcome must be 'confirmed' or 'overridden'")
    if outcome == "overridden" and override_decision not in _DECISIONS:
        raise ValueError(f"override_decision must be one of {sorted(_DECISIONS)}")
    with Session(engine) as s:
        check = s.get(PermitCheck, check_id)
        if not check or check.tenant_id != tenant_id:
            return None
        if outcome == "overridden":
            check.decision = override_decision
            check.status = "overridden"
        else:
            check.status = "confirmed"
        check.needs_review = False
        s.add(check)
        s.add(ReviewAction(tenant_id=tenant_id, permit_check_id=check_id, reviewer=reviewer,
                           outcome=outcome, override_decision=override_decision, note=note))
        s.add(AuditLog(tenant_id=tenant_id, action="permit.reviewed", severity="info",
                       detail={"check_id": check_id, "reviewer": reviewer, "outcome": outcome,
                               "override_decision": override_decision}))
        s.commit()
        s.refresh(check)
        return _check_dict(check)


# --------------------------------------------------------------------------- #
# serialization
# --------------------------------------------------------------------------- #
def _check_summary(c: PermitCheck) -> dict:
    return {"id": c.id, "filename": c.filename, "decision": c.decision, "confidence": c.confidence,
            "valid_until": c.valid_until, "employment_status": c.employment_status,
            "holder_name": c.holder_name, "needs_review": c.needs_review, "status": c.status,
            "created_at": c.created_at.isoformat()}


def _check_dict(c: PermitCheck) -> dict:
    return {**_check_summary(c), "days_remaining": c.days_remaining,
            "document_type": c.document_type, "legal_basis": c.legal_basis,
            "legal_basis_citation": c.legal_basis_citation, "fields": c.fields,
            "rubric": c.rubric, "reasons": c.reasons}
