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


# --------------------------------------------------------------------------
# CREATE GAP + SCREEN
# --------------------------------------------------------------------------
def _extract_emp_id(text_in: str | None) -> str | None:
    if not text_in:
        return None
    m = re.search(r"HOSP-\d+", text_in, re.IGNORECASE)
    return m.group(0).upper() if m else None


def _tonight_label() -> str:
    """The grid column for 'today', matching the xlsx column format, e.g. 'Sat 06/20'."""
    return NOW.strftime("%a ") + f"{NOW.month:02d}/{NOW.day:02d}"


def resolve_gap_spec(req: engine.GapRequest) -> engine.GapSpec:
    role = req.role or "Registered Nurse"
    shift = (req.shift or "night").strip().lower()
    if shift not in SHIFT_TIMES:
        shift = "night"
    start_t, _ = SHIFT_TIMES[shift]
    shift_start = datetime.combine(TODAY, start_t)
    shift_end = shift_start + timedelta(hours=12)
    day_label = (req.day_label or "").strip()
    if day_label.lower() in {"", "tonight", "today", "now"}:
        day_label = _tonight_label()
    return engine.GapSpec(
        role=role, department=req.department, shift=shift, shift_start=shift_start,
        shift_end=shift_end, shift_hours=12.0, day_label=day_label,
        required_certs=req.required_certs or [], person_out=req.person_out,
        person_out_id=_extract_emp_id(req.person_out))


def create_gap(tenant_id: str, *, message: str | None = None,
               structured: dict | None = None, provider: str | None = None) -> str:
    if structured:
        req = engine.GapRequest(**structured)
    elif message:
        req = engine.parse_gap_message(message)          # core.llm (ollama offline / gemini demo)
    else:
        raise ValueError("create_gap needs either `message` or `structured`")
    spec = resolve_gap_spec(req)
    with Session(db_engine) as s:
        gap = ShiftGap(tenant_id=tenant_id, role=spec.role, department=spec.department,
                       shift=spec.shift, day_label=spec.day_label, required_certs=spec.required_certs,
                       person_out=spec.person_out, shift_start=spec.shift_start,
                       shift_end=spec.shift_end, shift_hours=spec.shift_hours, status="open", version=0)
        s.add(gap); s.commit(); s.refresh(gap)
        return gap.id


def _load_gap(s: Session, tenant_id: str, gap_id: str) -> ShiftGap:
    gap = s.get(ShiftGap, gap_id)
    if not gap or gap.tenant_id != tenant_id:
        raise LookupError(f"gap {gap_id} not found for tenant")
    return gap


def _gap_to_spec(gap: ShiftGap) -> engine.GapSpec:
    return engine.GapSpec(
        role=gap.role or "Registered Nurse", department=gap.department, shift=gap.shift or "night",
        shift_start=gap.shift_start or datetime.combine(TODAY, time(19, 0)),
        shift_end=gap.shift_end or datetime.combine(TODAY, time(19, 0)) + timedelta(hours=12),
        shift_hours=gap.shift_hours or 12.0, day_label=gap.day_label or _tonight_label(),
        required_certs=gap.required_certs or [], person_out=gap.person_out,
        person_out_id=_extract_emp_id(gap.person_out))


def screen_gap(tenant_id: str, gap_id: str) -> engine.EligibilityReport:
    with Session(db_engine) as s:
        gap = _load_gap(s, tenant_id, gap_id)
        staff = s.exec(select(Staff).where(Staff.tenant_id == tenant_id)).all()
        last_contacted = {l.staff_id: l.sent_at for l in
                          s.exec(select(OutreachLog).where(OutreachLog.tenant_id == tenant_id)).all()
                          if l.sent_at}
        likes = [staff_to_like(p, last_contacted.get(p.id)) for p in staff]
        spec = _gap_to_spec(gap)
    return engine.screen_candidates(likes, spec)


def gap_state(tenant_id: str, gap_id: str) -> dict:
    rep = screen_gap(tenant_id, gap_id)
    with Session(db_engine) as s:
        gap = _load_gap(s, tenant_id, gap_id)
        logs = s.exec(select(OutreachLog).where(OutreachLog.gap_id == gap_id)
                      .order_by(OutreachLog.seq)).all()
        staff_names = {p.id: p.name for p in s.exec(select(Staff).where(Staff.tenant_id == tenant_id)).all()}
        filled_by = None
        if gap.filled_by_staff_id:
            fb = s.get(Staff, gap.filled_by_staff_id)
            filled_by = {"id": fb.id, "name": fb.name, "employee_id": fb.employee_id} if fb else None
        return {
            "gap": {"id": gap.id, "role": gap.role, "department": gap.department, "shift": gap.shift,
                    "day_label": gap.day_label, "required_certs": gap.required_certs,
                    "person_out": gap.person_out, "status": gap.status, "version": gap.version,
                    "shift_start": gap.shift_start.isoformat() if gap.shift_start else None,
                    "shift_end": gap.shift_end.isoformat() if gap.shift_end else None,
                    "filled_at": gap.filled_at.isoformat() if gap.filled_at else None},
            "filled_by": filled_by,
            "eligible": [c.model_dump() for c in rep.eligible],
            "excluded": [e.model_dump() for e in rep.excluded],
            "counts": {"total": rep.n_total, "active": rep.n_active, "eligible": rep.n_eligible},
            "outreach": [{"id": l.id, "staff_id": l.staff_id, "staff_name": staff_names.get(l.staff_id),
                          "seq": l.seq, "status": l.status, "channel": l.channel, "message": l.message,
                          "sent_at": l.sent_at.isoformat() if l.sent_at else None,
                          "responded_at": l.responded_at.isoformat() if l.responded_at else None}
                         for l in logs],
        }


def list_gaps(tenant_id: str, limit: int = 20) -> list[dict]:
    with Session(db_engine) as s:
        rows = s.exec(select(ShiftGap).where(ShiftGap.tenant_id == tenant_id)
                      .order_by(desc(ShiftGap.created_at)).limit(limit)).all()
        return [{"id": g.id, "role": g.role, "department": g.department, "shift": g.shift,
                 "day_label": g.day_label, "status": g.status,
                 "created_at": g.created_at.isoformat()} for g in rows]
