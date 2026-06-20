"""P10 Rheinmetall — secure intake domain tables (the reference flagship)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from core.models.base import new_id, utcnow


class Tenant(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    slug: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utcnow)


class Applicant(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    name: str | None = None
    email: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class IntakeRecord(SQLModel, table=True):
    """One processed applicant submission + its verdict."""
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    applicant_id: str | None = Field(default=None, foreign_key="applicant.id")
    injection_detected: bool = False
    all_present: bool = False
    present_labels: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    missing_labels: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    report: dict = Field(default_factory=dict, sa_column=Column(JSON))  # full IntakeResult
    created_at: datetime = Field(default_factory=utcnow)


class AuditLog(SQLModel, table=True):
    """Append-only security/audit trail — every injection attempt + agent action."""
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    action: str = Field(index=True)          # e.g. intake.processed, injection.detected
    severity: str = Field(default="info")    # info | warning | critical
    detail: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
