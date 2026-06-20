"""P4 Persowerk — CV & certificate fraud domain tables. Schema defined now (Phase 0) so
the P4 worktree never collides on core/models. Filled out by the P4 flagship later."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from core.models.base import new_id, utcnow


class Candidate(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    name: str | None = None
    email: str | None = None
    github: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Certificate(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    candidate_id: str | None = Field(default=None, foreign_key="candidate.id")
    issuer: str | None = None
    title: str | None = None
    issue_date: str | None = None
    valid_until: str | None = None
    is_genuine: bool | None = None
    is_current: bool | None = None
    created_at: datetime = Field(default_factory=utcnow)


class VerificationRecord(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    candidate_id: str | None = Field(default=None, foreign_key="candidate.id")
    kind: str = Field(default="cv")        # cv | certificate
    risk: str | None = None                # LOW | MEDIUM | HIGH
    score: float | None = None             # 0-100
    flags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    report: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
