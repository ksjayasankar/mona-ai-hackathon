"""P8 Dr. Theiss dynamic-pricing tables (tenant-scoped).

Two tables + the reused AuditLog. Guardrail policy is a hardcoded DEFAULT_POLICY in
agents.pricing_product (no per-tenant policy UI for the hackathon), so no policy table.

    PriceRun  1───*  PriceRecommendation
    (one upload/analysis;        (one product's gated decision; a human
     signals + full report JSON)  approves/rejects each — status field)

Two distinct status fields, deliberately named apart:
  guardrail_status : applied | clamped | rejected | blocked   (what the engine did — authoritative)
  status           : pending | approved | rejected            (the human decision)
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from core.models.base import new_id, utcnow


class PriceRun(SQLModel, table=True):
    """One catalogue upload + signal fetch + gated recommendation set."""
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    source_note: str = ""
    product_count: int = 0
    blocked_count: int = 0
    summary: str = ""
    signals: list = Field(default_factory=list, sa_column=Column(JSON))   # SignalReading dicts fetched this run
    report: dict = Field(default_factory=dict, sa_column=Column(JSON))    # full PricingReport
    created_at: datetime = Field(default_factory=utcnow)


class PriceRecommendation(SQLModel, table=True):
    """One product's authoritative, gated price decision — the audited number."""
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    run_id: str = Field(foreign_key="pricerun.id", index=True)
    product: str
    category: str = "general"
    base_price: float
    proposed_delta_pct: float = 0.0      # the raw LLM proposal (pre-guardrail)
    final_delta_pct: float = 0.0         # after guardrails — authoritative
    final_price: float
    guardrail_status: str = "applied"    # applied | clamped | rejected | blocked
    reasons: list = Field(default_factory=list, sa_column=Column(JSON))
    signals: list = Field(default_factory=list, sa_column=Column(JSON))  # readings that drove this product
    status: str = "pending"              # pending | approved | rejected (human decision)
    created_at: datetime = Field(default_factory=utcnow)
