"""P2 UKS — shift replacement domain tables. Schema defined now (during Phase 0) so the
P2 worktree never collides on core/models. Filled out by the P2 flagship later."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from core.models.base import new_id, utcnow


class Staff(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    name: str
    role: str | None = None
    department: str | None = None
    qualifications: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    max_hours_week: int | None = None
    phone: str | None = None
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class ShiftGap(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    role: str | None = None
    department: str | None = None
    shift: str | None = None            # day | night
    day_label: str | None = None
    required_certs: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = Field(default="open")  # open | filled | cancelled
    created_at: datetime = Field(default_factory=utcnow)


class OutreachLog(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    gap_id: str | None = Field(default=None, foreign_key="shiftgap.id")
    staff_id: str | None = Field(default=None, foreign_key="staff.id")
    channel: str = Field(default="sms")  # sms | email
    message: str | None = None
    status: str = Field(default="drafted")  # drafted | sent | accepted | declined
    created_at: datetime = Field(default_factory=utcnow)
