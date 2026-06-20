"""P2 UKS — shift replacement domain tables (productized by the P2 flagship).

Keeps the class names Staff / ShiftGap / OutreachLog so core/models/__init__ is unchanged.
Columns carry everything the deterministic eligibility engine, sequential outreach, and the
race-safe first-accept lock need. SQLite (local/tests) + Postgres (prod via Alembic)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from core.models.base import new_id, utcnow


class Staff(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    employee_id: str | None = Field(default=None, index=True)   # external roster id, e.g. HOSP-1059
    name: str
    role: str | None = None
    department: str | None = None
    qualifications: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    contract: str | None = None
    max_hours_week: float | None = None
    scheduled_hours_next7: float = 0.0
    shift_grid: dict = Field(default_factory=dict, sa_column=Column(JSON))   # "Sat 06/20" -> D|N|O
    overtime_ok: bool = False
    shift_preference: str | None = None
    active: bool = True
    last_shift_end: datetime | None = None      # for ArbZG §5 rest calc
    last_contacted_at: datetime | None = None   # fairness: spread the asks
    persona: str | None = None
    phone: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ShiftGap(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    role: str | None = None
    department: str | None = None
    shift: str | None = None            # day | night
    day_label: str | None = None
    required_certs: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    person_out: str | None = None
    shift_start: datetime | None = None
    shift_end: datetime | None = None
    shift_hours: float = 12.0
    status: str = Field(default="open")  # open | filled | cancelled
    version: int = 0                     # optimistic lock for race-safe first-accept
    filled_by_staff_id: str | None = Field(default=None, foreign_key="staff.id")
    filled_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class OutreachLog(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    gap_id: str | None = Field(default=None, foreign_key="shiftgap.id", index=True)
    staff_id: str | None = Field(default=None, foreign_key="staff.id")
    channel: str = Field(default="sms")  # sms | email
    message: str | None = None
    status: str = Field(default="queued")  # queued | sent | accepted | declined | closed
    seq: int = 0                          # contact order (0 = first)
    token: str | None = Field(default=None, index=True)   # magic-link accept token
    sent_at: datetime | None = None
    responded_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
