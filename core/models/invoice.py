"""P1 Globus — invoice-triage domain tables (tenant-scoped).

One row per invoice SPLIT OUT of an email/document, carrying its extracted fields,
grounded per-field evidence + confidence, the dedupe fingerprint, the routed
department, and a lifecycle status. ApprovalAction is the human-decision audit.
The shared append-only AuditLog (core.models.intake) records pipeline + dedupe events.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from core.models.base import new_id, utcnow

# Lifecycle statuses (mirror agents.invoices.STATUS_* + the dedupe/approval states).
STATUS_PENDING = "pending"            # grounded + confident -> ready for one-click approval
STATUS_NEEDS_REVIEW = "needs_review"  # below the grounding/confidence bar -> human must confirm
STATUS_DUPLICATE = "duplicate"        # exact re-send or possible amendment -> held for a human
STATUS_APPROVED = "approved"          # a human approved + routed it


class InvoiceRecord(SQLModel, table=True):
    """One invoice + its triage verdict, scoped to a tenant."""

    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)

    # provenance — where this invoice came from
    source: str | None = Field(default=None, description="email label / attachment filename")
    source_span: str | None = Field(default=None, description="where in the source this invoice began")

    # extracted fields (core + extended)
    vendor: str | None = None
    invoice_number: str | None = None
    date: str | None = None
    due_date: str | None = None
    po_number: str | None = None
    currency: str | None = None
    total: str | None = None
    net_amount: str | None = None
    vat_amount: str | None = None
    vat_rate: str | None = None
    category: str | None = None

    # triage outputs
    department: str | None = Field(default=None, index=True)
    dept_reason: str | None = None        # set when the LLM suggested the dept (table fell through)
    status: str = Field(default=STATUS_PENDING, index=True)
    confidence: float = 0.0
    fingerprint: str = Field(default="", index=True)
    dupe_key: str = Field(default="", index=True)
    duplicate_of: str | None = None       # InvoiceRecord.id this exactly/near matches

    # grounding + raw payload (JSON columns, like IntakeRecord.report)
    evidence: dict = Field(default_factory=dict, sa_column=Column(JSON))
    field_confidence: dict = Field(default_factory=dict, sa_column=Column(JSON))
    line_items: list = Field(default_factory=list, sa_column=Column(JSON))
    fields: dict = Field(default_factory=dict, sa_column=Column(JSON))  # full InvoiceFields dump
    flags: list = Field(default_factory=list, sa_column=Column(JSON))   # plain-language reasons

    created_at: datetime = Field(default_factory=utcnow)


class ApprovalAction(SQLModel, table=True):
    """Append-only audit of a human decision on an invoice."""

    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    invoice_id: str = Field(foreign_key="invoicerecord.id", index=True)
    approver: str
    outcome: str = Field(index=True)      # approved | rejected | kept_both | needs_changes
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
