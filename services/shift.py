"""P2 UKS — shift-replacement service (tenant-scoped, persisted, production-grade).

Pipeline: SEED staff from the hospital xlsx -> CREATE a gap (free-text via core.llm or
structured) -> SCREEN with the pure ArbZG engine -> sequential OUTREACH (Twilio SMS or a
logged simulated send, each with a magic-link) -> race-safe ACCEPT (single atomic UPDATE
guarded on status) -> live state for the SSE dashboard. agents/shift.py stays pure logic;
this is the product version."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlmodel import Session, desc, select

from agents import shift as engine
from core import config
from core.db import engine as db_engine
from core.models import OutreachLog, ShiftGap, Staff

log = logging.getLogger("shift")

NOW = engine.NOW                       # Sat 2026-06-20 18:30 (demo clock)
TODAY = NOW.date()
SHIFT_TIMES = {"day": (time(7, 0), time(19, 0)), "night": (time(19, 0), time(7, 0))}


# --------------------------------------------------------------------------
# SEED
# --------------------------------------------------------------------------
def _parse_last_end(value) -> datetime | None:
    if isinstance(value, str) and "on shift" in value.lower():
        return datetime.combine(TODAY, time(19, 0))     # finishing today's day shift
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return pd.to_datetime(value).to_pydatetime()
    except Exception:
        return None


def seed_staff(tenant_id: str, path: str | Path | None = None) -> int:
    """Idempotent upsert of the roster (+ weekly grid) into Staff for this tenant."""
    p = Path(path) if path else config.PATHS["schedule"]
    roster = pd.read_excel(p, sheet_name="Roster")
    weekly = pd.read_excel(p, sheet_name="Weekly_Schedule")
    day_cols = [c for c in weekly.columns
                if c not in {"Employee ID", "Name", "Role", "Department"}
                and not str(c).lower().startswith("scheduled")]
    sched_by_id = dict(zip(weekly["Employee ID"], weekly["Scheduled Hrs (next 7d)"]))
    grid_by_id = {row["Employee ID"]: {c: str(row[c]) for c in day_cols} for _, row in weekly.iterrows()}

    with Session(db_engine) as s:
        existing = {r.employee_id: r for r in
                    s.exec(select(Staff).where(Staff.tenant_id == tenant_id)).all()}
        n = 0
        for _, r in roster.iterrows():
            emp = str(r["Employee ID"])
            fields = dict(
                tenant_id=tenant_id, employee_id=emp,
                name=f"{str(r.get('First Name','')).strip()} {str(r.get('Last Name','')).strip()}".strip(),
                role=str(r["Role"]), department=str(r["Department"]),
                qualifications=[c.strip() for c in str(r.get("Certifications", "")).split(",") if c.strip()],
                contract=str(r.get("Contract", "")), max_hours_week=float(r.get("Max Hrs/Week") or 0),
                scheduled_hours_next7=float(sched_by_id.get(emp) or 0),
                shift_grid=grid_by_id.get(emp, {}),
                overtime_ok=str(r.get("Overtime OK", "")).strip().lower() in {"yes", "true", "1"},
                shift_preference=str(r.get("Shift Preference", "")),
                active=str(r.get("Status", "")).strip().lower() == "active",
                last_shift_end=_parse_last_end(r.get("Last Clock Out")),
                persona=(str(r["Persona / Notes"]) if pd.notna(r.get("Persona / Notes")) else None),
                phone=str(r.get("Phone", "")))
            row = existing.get(emp)
            if row:
                for k, v in fields.items():
                    setattr(row, k, v)
                s.add(row)
            else:
                s.add(Staff(**fields))
            n += 1
        s.commit()
    log.info("seeded %d staff for tenant %s", n, tenant_id)
    return n


def staff_to_like(s: Staff, last_contacted: datetime | None = None) -> engine.StaffLike:
    return engine.StaffLike(
        employee_id=s.employee_id or s.id, name=s.name, role=s.role or "", department=s.department or "",
        certifications=list(s.qualifications or []), contract=s.contract or "", max_hours_week=s.max_hours_week,
        scheduled_hours_next7=s.scheduled_hours_next7, shift_grid=dict(s.shift_grid or {}),
        overtime_ok=bool(s.overtime_ok), shift_preference=s.shift_preference or "", active=bool(s.active),
        last_shift_end=s.last_shift_end, phone=s.phone or "", persona=s.persona,
        last_contacted_at=last_contacted or s.last_contacted_at)
