"""P3 Leistenschneider — work-permit validation tables (tenant-scoped, audited).

The system NEVER issues a binding decision on its own (EU-AI-Act: migration-adjacent =
high-risk AI). Every check is a RECOMMENDATION; below-threshold / implied-by-statute
checks carry needs_review=True and sit in a human-review queue (status='pending') until a
reviewer confirms or overrides — recorded in ReviewAction with reviewer + timestamp.
Security/audit events also flow to the shared AuditLog (core.models.intake).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from core.models.base import new_id, utcnow


class PermitCheck(SQLModel, table=True):
    """One validated permit document + its grounded verdict."""
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    filename: str | None = None

    decision: str = Field(index=True)        # VALID | EXPIRED | NOT_A_PERMIT | NOT_WORK_AUTHORIZED | NEEDS_REVIEW
    confidence: float = 0.0
    valid_until: str | None = None
    days_remaining: int | None = None
    employment_status: str | None = None     # permitted | prohibited | implied | restricted | unknown | n/a
    holder_name: str | None = None
    document_type: str | None = None
    legal_basis: str | None = None
    legal_basis_citation: str | None = None  # the §AufenthG basis cited for the verdict

    needs_review: bool = Field(default=False, index=True)
    status: str = Field(default="pending", index=True)  # pending | confirmed | overridden

    # full grounded payload — quote-spans, rubric breakdown, reasons (rendered in the UI)
    fields: dict = Field(default_factory=dict, sa_column=Column(JSON))   # PermitFields incl. *_quote
    rubric: list = Field(default_factory=list, sa_column=Column(JSON))   # itemized confidence lines
    reasons: list = Field(default_factory=list, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=utcnow)


class ReviewAction(SQLModel, table=True):
    """Human-in-the-loop audit: who decided what, when. The human can always override."""
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    permit_check_id: str = Field(foreign_key="permitcheck.id", index=True)
    reviewer: str                            # principal user_id / email
    outcome: str                             # confirmed | overridden
    override_decision: str | None = None     # the reviewer's decision when overriding
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
