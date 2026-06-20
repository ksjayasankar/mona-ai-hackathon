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
from datetime import datetime, time, timedelta, timezone
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


def _now() -> datetime:
    """Naive UTC 'now' — consistent with the naive datetimes elsewhere (shift_start etc.)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


# --------------------------------------------------------------------------
# OUTREACH — Twilio SMS (real, via REST/httpx) or a logged simulated send
# --------------------------------------------------------------------------
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:3000")
_TW_SID = os.getenv("TWILIO_ACCOUNT_SID")
_TW_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
_TW_FROM = os.getenv("TWILIO_FROM")


def magic_link(token: str) -> str:
    return f"{PUBLIC_BASE_URL}/uks/accept?token={token}"


def send_sms(to: str, body: str) -> dict:
    """Real Twilio SMS when creds are present; otherwise a logged simulated send.
    Uses the Twilio REST API directly over httpx (no extra SDK dependency)."""
    if _TW_SID and _TW_TOKEN and _TW_FROM and to:
        import httpx
        url = f"https://api.twilio.com/2010-04-01/Accounts/{_TW_SID}/Messages.json"
        try:
            r = httpx.post(url, auth=(_TW_SID, _TW_TOKEN),
                           data={"From": _TW_FROM, "To": to, "Body": body}, timeout=15)
            r.raise_for_status()
            return {"simulated": False, "sid": r.json().get("sid"), "to": to, "body": body}
        except Exception as e:                              # never let a send crash the flow
            log.warning("twilio send failed (%s); falling back to simulated", e)
    log.info("SIMULATED SMS to %s: %s", to, body)
    return {"simulated": True, "sid": "SIMULATED", "to": to, "body": body}


def _draft_sms(gap: ShiftGap, staff: Staff, link: str) -> str:
    first = (staff.name or "there").split()[0] if staff.name else "there"
    ward = f"{gap.department} " if gap.department else ""
    window = (f"{gap.shift_start:%H:%M}-{gap.shift_end:%H:%M}"
              if gap.shift_start and gap.shift_end else (gap.shift or ""))
    return (f"Hi {first}, UKS staffing here. Urgent {ward}{gap.shift}-shift gap {gap.day_label} "
            f"({window}, 12h) — a colleague called in sick. You're qualified & off. "
            f"Tap to accept: {link}")


def _send_seq(s: Session, gap: ShiftGap, log_row: OutreachLog, staff: Staff) -> dict:
    link = magic_link(log_row.token)
    body = _draft_sms(gap, staff, link)
    res = send_sms(staff.phone or "", body)
    log_row.message = body
    log_row.status = "sent"
    log_row.sent_at = _now()
    staff.last_contacted_at = log_row.sent_at
    s.add(log_row); s.add(staff); s.commit()
    return {"seq": log_row.seq, "staff_id": staff.id, "staff_name": staff.name,
            "magic_link": link, "message": body, "simulated": res["simulated"], "sid": res["sid"]}


def start_outreach(tenant_id: str, gap_id: str) -> dict:
    """Queue an OutreachLog (with a magic-link token) for every eligible candidate in rank
    order, then send to candidate #0. Idempotent: returns existing state if already started."""
    rep = screen_gap(tenant_id, gap_id)
    with Session(db_engine) as s:
        gap = _load_gap(s, tenant_id, gap_id)
        if gap.status != "open":
            return {"already": True, "sent": None, **gap_state(tenant_id, gap_id)}
        existing = s.exec(select(OutreachLog).where(OutreachLog.gap_id == gap_id)).all()
        if existing:
            return {"already": True, "sent": None, **gap_state(tenant_id, gap_id)}
        if not rep.eligible:
            return {"sent": None, "note": "no eligible candidates", **gap_state(tenant_id, gap_id)}
        by_emp = {p.employee_id: p for p in
                  s.exec(select(Staff).where(Staff.tenant_id == tenant_id)).all()}
        rows: list[OutreachLog] = []
        for i, c in enumerate(rep.eligible):
            rows.append(OutreachLog(tenant_id=tenant_id, gap_id=gap_id, staff_id=by_emp[c.employee_id].id,
                                    channel="sms", status="queued", seq=i, token=secrets.token_urlsafe(16)))
        s.add_all(rows); s.commit()
        for r in rows:
            s.refresh(r)
        sent = _send_seq(s, gap, rows[0], by_emp[rep.eligible[0].employee_id])
    return {"sent": sent, **gap_state(tenant_id, gap_id)}


def escalate(tenant_id: str, gap_id: str) -> dict:
    """Send to the next queued candidate (manual 'escalate now' / dashboard timer)."""
    with Session(db_engine) as s:
        gap = _load_gap(s, tenant_id, gap_id)
        if gap.status != "open":
            return {"sent": None, "note": "gap already filled/closed", **gap_state(tenant_id, gap_id)}
        nxt = s.exec(select(OutreachLog).where(OutreachLog.gap_id == gap_id,
                     OutreachLog.status == "queued").order_by(OutreachLog.seq)).first()
        if not nxt:
            return {"sent": None, "note": "no more candidates to escalate to", **gap_state(tenant_id, gap_id)}
        staff = s.get(Staff, nxt.staff_id)
        sent = _send_seq(s, gap, nxt, staff)
    return {"sent": sent, **gap_state(tenant_id, gap_id)}


# --------------------------------------------------------------------------
# ACCEPT — race-safe first-accept lock (single atomic UPDATE, rowcount guard)
# --------------------------------------------------------------------------
def accept(token: str) -> dict:
    """First accept wins. The claim is one atomic SQL UPDATE guarded on status='open';
    the DB guarantees exactly one concurrent statement matches, so a late reply after
    escalation (or two simultaneous taps) can never double-fill the gap."""
    with Session(db_engine) as s:
        log_row = s.exec(select(OutreachLog).where(OutreachLog.token == token)).first()
        if not log_row:
            return {"result": "invalid", "detail": "unknown or expired link"}
        gap = s.get(ShiftGap, log_row.gap_id)
        if not gap:
            return {"result": "invalid", "detail": "gap missing"}

        # atomic claim: only the first caller flips open -> filled (filled_at set via ORM after)
        res = s.execute(
            text("UPDATE shiftgap SET status='filled', version=version+1, "
                 "filled_by_staff_id=:sid WHERE id=:gid AND status='open'"),
            {"sid": log_row.staff_id, "gid": gap.id})
        won = res.rowcount == 1
        s.commit()

        if not won:
            log_row.status = "closed"
            log_row.responded_at = _now()
            s.add(log_row); s.commit()
            s.refresh(gap)
            winner = s.get(Staff, gap.filled_by_staff_id) if gap.filled_by_staff_id else None
            return {"result": "already_filled", "gap_id": gap.id,
                    "filled_by": winner.name if winner else None}

        # we won: stamp filled_at, accept this log, close the others, flip the schedule
        s.refresh(gap)
        gap.filled_at = _now()
        s.add(gap)
        log_row.status = "accepted"
        log_row.responded_at = _now()
        s.add(log_row)
        for other in s.exec(select(OutreachLog).where(OutreachLog.gap_id == gap.id,
                            OutreachLog.id != log_row.id)).all():
            if other.status in ("queued", "sent"):
                other.status = "closed"
                s.add(other)
        staff = s.get(Staff, log_row.staff_id)
        if staff and gap.day_label:                      # schedule flip (reassign dict so JSON change is tracked)
            grid = dict(staff.shift_grid or {})
            grid[gap.day_label] = "N" if gap.shift == "night" else "D"
            staff.shift_grid = grid
            staff.scheduled_hours_next7 = (staff.scheduled_hours_next7 or 0) + (gap.shift_hours or 12)
            s.add(staff)
        s.commit()
        staff_name = staff.name if staff else None
        staff_phone = staff.phone if staff else ""
        gap_shift, gap_day, gap_id_val, staff_id_val = gap.shift, gap.day_label, gap.id, log_row.staff_id
    # confirmation SMS (real or simulated), outside the txn
    if staff_name:
        send_sms(staff_phone or "", f"Thanks {staff_name.split()[0]}! You're confirmed for the "
                                    f"{gap_shift} shift {gap_day}. See you then. — UKS staffing")
    return {"result": "confirmed", "gap_id": gap_id_val,
            "staff_id": staff_id_val, "staff_name": staff_name}


def decline(token: str) -> dict:
    with Session(db_engine) as s:
        log_row = s.exec(select(OutreachLog).where(OutreachLog.token == token)).first()
        if not log_row:
            return {"result": "invalid"}
        if log_row.status in ("queued", "sent"):
            log_row.status = "declined"
            log_row.responded_at = _now()
            s.add(log_row); s.commit()
        return {"result": "declined", "gap_id": log_row.gap_id}


def tenant_of_gap(gap_id: str) -> str | None:
    """Resolve a gap's tenant (used by the public, token-only accept/decline routes)."""
    with Session(db_engine) as s:
        gap = s.get(ShiftGap, gap_id)
        return gap.tenant_id if gap else None


# --------------------------------------------------------------------------
# SSE EVENT BUS — in-process pub/sub (single-worker dev/demo). A multi-worker
# prod deploy would swap this for Redis pub/sub; that's documented as out-of-scope.
# --------------------------------------------------------------------------
_subscribers: dict[str, set[asyncio.Queue]] = {}


def subscribe(gap_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=32)
    _subscribers.setdefault(gap_id, set()).add(q)
    return q


def unsubscribe(gap_id: str, q: asyncio.Queue) -> None:
    subs = _subscribers.get(gap_id)
    if subs:
        subs.discard(q)
        if not subs:
            _subscribers.pop(gap_id, None)


async def publish(gap_id: str, snapshot: dict) -> None:
    for q in list(_subscribers.get(gap_id, ())):
        try:
            q.put_nowait(snapshot)
        except asyncio.QueueFull:
            pass
