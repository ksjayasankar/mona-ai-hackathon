"""Problem 2 — UKS: Shift Replacement Agent.

Boxes to check (from the customer brief):
  [x] accept a shift-gap message (who called in sick / role / when)
  [x] find AVAILABLE and QUALIFIED replacement staff
        (not already on that shift, holds the required certs, active, rested,
         won't breach the weekly hours cap)
  [x] reach out automatically = DRAFT the outreach message to the best candidates
        (simulated send — no real SMS/email wired)

Approach: the gap message is free text, so we let Claude read it and pull out the
structured request (role, department, shift, date, certs, who's out). Then we run a
DETERMINISTIC eligibility filter + ranking over the real roster spreadsheet — so the
"who can cover" answer is auditable and never depends on the model's mood. Finally we
draft a friendly SMS-style outreach for the top picks.

Data: core.config.PATHS["schedule"] = hospital_schedule_part_2.xlsx
  - Roster sheet:          Employee ID, First/Last Name, Role, Department, Certifications,
                           Contract, Max Hrs/Week, Shift Preference, Overtime OK, Status,
                           Persona / Notes, Last Clock In, Last Clock Out, Phone
  - Weekly_Schedule sheet: Employee ID, Name, Role, Department, one column per day
                           (e.g. "Sat 06/20" holding D/N/O), Scheduled Hrs (next 7d)
  - Shift_Reference sheet: code -> shift name + times (D=Day 07-19, N=Night 19-07, O=Off)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from core import config, llm

# Hackathon "now": Saturday 20 June 2026, 18:30 (just before the night shift).
NOW = datetime(2026, 6, 20, 18, 30)
TODAY = NOW.date()

SHIFT_TIMES = {"day": ("07:00", "19:00"), "night": ("19:00", "07:00")}


# ---------------------------------------------------------------------------
# 1. Understand the free-text gap message
# ---------------------------------------------------------------------------

SYSTEM_PARSE = (
    "You are a hospital staffing coordinator's assistant. You are given a short, urgent "
    "free-text message reporting that a staff member called in sick. Extract the shift gap "
    "as structured data. Roles are things like 'Registered Nurse', 'Physician', "
    "'Certified Nursing Assistant'. Shift is 'day' or 'night'. Certifications look like "
    "'BLS', 'ACLS', 'PALS'. If a field is not stated, use null. Today is Saturday 20 June 2026."
)


class GapRequest(BaseModel):
    """Structured shift-gap request parsed from the coordinator's message."""

    person_out: str | None = Field(default=None, description="Name (and/or ID) of who called in sick")
    role: str | None = Field(default=None, description="Role that needs covering, e.g. 'Registered Nurse'")
    department: str | None = Field(default=None, description="Ward/department, e.g. 'ICU'")
    shift: str | None = Field(default=None, description="'day' or 'night'")
    day_label: str | None = Field(
        default=None, description="Which day, copied as written if given, e.g. 'tonight', 'Sat 06/20'"
    )
    required_certs: list[str] = Field(
        default_factory=list, description="Certifications the shift needs, e.g. ['BLS','ACLS']"
    )


def parse_gap_message(message: str) -> GapRequest:
    """Use Claude to turn a free-text sick-call message into a structured request."""
    blocks = [{"type": "text", "text": f"Sick-call message:\n{message}"}]
    return llm.extract(GapRequest, blocks, system=SYSTEM_PARSE)


# ---------------------------------------------------------------------------
# 2. The candidate + result schemas
# ---------------------------------------------------------------------------


class Candidate(BaseModel):
    employee_id: str
    name: str
    role: str
    department: str
    certifications: str
    contract: str
    overtime_ok: bool
    scheduled_hrs: float
    max_hrs: float
    phone: str
    persona: str | None = None
    score: float
    why: list[str]                 # plain-language reasons this person qualifies
    draft_message: str | None = None  # outreach SMS draft (top picks only)


class ShiftResult(BaseModel):
    gap_summary: str               # one-line plain summary of the gap
    shift_window: str              # e.g. "19:00–07:00"
    role: str
    department: str | None
    required_certs: list[str]
    day_label: str
    candidates: list[Candidate]    # ranked, eligible only
    n_screened: int                # how many active staff were considered
    confidence: float
    notes: list[str]               # assumptions / edge cases surfaced to the user


# ===========================================================================
# DETERMINISTIC ELIGIBILITY ENGINE (the substance beat) — pure, ArbZG-compliant
# ===========================================================================
# This is intentionally framework-free: no DB, no pandas, no LLM. Given a normalized
# roster and a gap, it returns ranked-eligible candidates (each with a plain-language
# WHY) and excluded candidates (each with the rule that excluded them + a human reason),
# so the "who can cover" answer is auditable and ArbZG-compliant by construction.
REST_MIN_HOURS = 11.0   # ArbZG §5: ≥11h rest between the end of one shift and the next
_NURSE_FAMILY = {"registered nurse", "charge nurse", "nurse practitioner"}


@dataclass
class StaffLike:
    """One staff member, normalized for the engine (decoupled from DB/pandas)."""
    employee_id: str
    name: str
    role: str
    department: str
    certifications: list[str]
    contract: str
    max_hours_week: float | None
    scheduled_hours_next7: float
    shift_grid: dict          # "Sat 06/20" -> "D"|"N"|"O"
    overtime_ok: bool
    shift_preference: str
    active: bool
    last_shift_end: datetime | None
    phone: str = ""
    persona: str | None = None
    last_contacted_at: datetime | None = None


class GapSpec(BaseModel):
    """A fully-resolved shift gap the engine screens against."""
    role: str
    department: str | None = None
    shift: str                       # "day" | "night"
    shift_start: datetime
    shift_end: datetime
    shift_hours: float = 12.0
    day_label: str
    required_certs: list[str] = Field(default_factory=list)
    person_out_id: str | None = None
    person_out: str | None = None


class ScoredCandidate(BaseModel):
    employee_id: str
    name: str
    role: str
    department: str
    phone: str
    contract: str
    scheduled_hours: float
    max_hours: float
    overtime_ok: bool
    rest_hours: float | None
    headroom_hours: float
    persona: str | None = None
    score: float
    why: list[str]


class ExcludedCandidate(BaseModel):
    employee_id: str
    name: str
    role: str
    department: str
    rule: str          # active | role | certs | already_on_shift | rest_§5 | weekly_cap_§3
    reason: str


class EligibilityReport(BaseModel):
    eligible: list[ScoredCandidate]
    excluded: list[ExcludedCandidate]
    n_total: int
    n_active: int
    n_eligible: int


def _role_ok(candidate_role: str, required_role: str) -> bool:
    cand, req = str(candidate_role).strip().lower(), str(required_role).strip().lower()
    if req in cand or cand in req:
        return True
    # nurse-family equivalence so a Charge Nurse / NP can cover an RN gap
    return req in _NURSE_FAMILY and cand in _NURSE_FAMILY


def _has_certs(held: list[str], required: list[str]) -> bool:
    hu = {c.strip().upper() for c in held}
    return all(c.strip().upper() in hu for c in required if c.strip())


def _rest_hours(last_end: datetime | None, shift_start: datetime) -> float | None:
    if last_end is None:
        return None
    return (shift_start - last_end).total_seconds() / 3600.0


def screen_candidates(staff: list[StaffLike], gap: GapSpec) -> EligibilityReport:
    """Filter + rank a roster against a gap. Pure & deterministic: every eligible carries a
    `why`, every excluded carries the `rule` + a human `reason` (ArbZG §5/§3 cited)."""
    eligible: list[ScoredCandidate] = []
    excluded: list[ExcludedCandidate] = []
    n_active = 0

    for p in staff:
        # the person who called in sick is never a candidate (dropped, not "excluded")
        if gap.person_out_id and p.employee_id == gap.person_out_id:
            continue

        def excl(rule: str, reason: str) -> None:
            excluded.append(ExcludedCandidate(employee_id=p.employee_id, name=p.name,
                                              role=p.role, department=p.department,
                                              rule=rule, reason=reason))

        # ---- hard gates, in order; first failure records the reason ----------
        if not p.active:
            excl("active", "On leave / inactive — not available.")
            continue
        n_active += 1
        if not _role_ok(p.role, gap.role):
            excl("role", f"{p.role} can't staff a {gap.role} {gap.department or ''} shift.".strip())
            continue
        if gap.required_certs and not _has_certs(p.certifications, gap.required_certs):
            missing = [c for c in gap.required_certs
                       if c.strip().upper() not in {x.upper() for x in p.certifications}]
            excl("certs", f"Missing required certification(s): {', '.join(missing)}.")
            continue
        assigned = str(p.shift_grid.get(gap.day_label, "O")).strip().upper()
        if assigned and assigned != "O":
            code = {"D": "day", "N": "night"}.get(assigned, assigned)
            excl("already_on_shift", f"Already scheduled on the {code} shift {gap.day_label} — not available.")
            continue
        rest = _rest_hours(p.last_shift_end, gap.shift_start)
        if rest is not None and rest < REST_MIN_HOURS:
            excl("rest_§5", f"Only {rest:.0f}h rest before {gap.shift_start:%a %H:%M} "
                            f"(last shift ended {p.last_shift_end:%a %H:%M}) — ArbZG §5 needs ≥{REST_MIN_HOURS:.0f}h.")
            continue
        sched, maxh = float(p.scheduled_hours_next7 or 0), float(p.max_hours_week or 0)
        if maxh and (sched + gap.shift_hours) > maxh:
            excl("weekly_cap_§3", f"{sched:.0f}h scheduled + {gap.shift_hours:.0f}h shift = "
                                  f"{sched + gap.shift_hours:.0f}h > {maxh:.0f}h weekly cap — ArbZG §3.")
            continue

        # ---- eligible: build the why + fairness/practicality score -----------
        headroom = (maxh - (sched + gap.shift_hours)) if maxh else 0.0
        same_dept = bool(gap.department) and str(p.department).strip().lower() == gap.department.strip().lower()
        pref = str(p.shift_preference or "").lower()
        why = [
            f"{p.role} — qualified for the {gap.role} gap",
            ("holds " + ", ".join(gap.required_certs)) if gap.required_certs
            else f"certs: {', '.join(p.certifications)}",
            f"off on {gap.day_label} (not already scheduled)",
            (f"{rest:.0f}h rest before the shift — meets ArbZG §5" if rest is not None
             else "no recent shift on record — well rested"),
            f"{headroom:.0f}h weekly-hours headroom after this shift (cap {maxh:.0f}h) — within ArbZG §3",
        ]
        score = min(headroom, 24.0)
        if p.last_contacted_at is None:
            score += 6.0
            why.append("not contacted recently — fair to ask")
        else:
            days = max(0.0, (gap.shift_start - p.last_contacted_at).total_seconds() / 86400.0)
            score += min(days, 7.0)
            why.append(f"last asked {days:.0f}d ago")
        if p.overtime_ok:
            score += 8.0
            why.append("flagged Overtime OK")
        if same_dept:
            score += 6.0
            why.append(f"works in {p.department} — knows the ward")
        c = (p.contract or "").lower()
        if "per-diem" in c or "per diem" in c:
            score += 5.0
            why.append("per-diem — quick to call in")
        elif "part" in c:
            score += 3.0
        if gap.shift in pref or "flexible" in pref:
            score += 4.0
            why.append(f"prefers/flexible on {gap.shift} shifts")

        eligible.append(ScoredCandidate(
            employee_id=p.employee_id, name=p.name, role=p.role, department=p.department,
            phone=p.phone, contract=p.contract or "", scheduled_hours=sched, max_hours=maxh,
            overtime_ok=p.overtime_ok, rest_hours=rest, headroom_hours=headroom,
            persona=p.persona, score=round(score, 1), why=why))

    eligible.sort(key=lambda x: x.score, reverse=True)
    return EligibilityReport(eligible=eligible, excluded=excluded, n_total=len(staff),
                             n_active=n_active, n_eligible=len(eligible))


# ---------------------------------------------------------------------------
# 3. Load the roster + weekly schedule
# ---------------------------------------------------------------------------


def load_schedule(path: str | Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (roster, weekly_schedule) dataframes from the xlsx."""
    p = Path(path) if path else config.PATHS["schedule"]
    roster = pd.read_excel(p, sheet_name="Roster")
    weekly = pd.read_excel(p, sheet_name="Weekly_Schedule")
    return roster, weekly


def day_columns(weekly: pd.DataFrame) -> list[str]:
    """The per-day shift-grid columns, e.g. ['Fri 06/19', 'Sat 06/20', ...]."""
    skip = {"Employee ID", "Name", "Role", "Department"}
    return [
        col
        for col in weekly.columns
        if col not in skip and not str(col).lower().startswith("scheduled")
    ]


def _resolve_day_column(weekly: pd.DataFrame, day_label: str | None) -> str:
    """Map a fuzzy day label ('tonight', 'Sat 06/20', '06/20') to a real grid column."""
    cols = day_columns(weekly)
    label = (day_label or "").strip().lower()
    # 'tonight' / 'today' -> today's column by date
    today_token = TODAY.strftime("%m/%d")
    if not label or label in {"tonight", "today", "now"}:
        for c in cols:
            if today_token in str(c):
                return c
        return cols[1] if len(cols) > 1 else cols[0]
    # try to match a written column (case-insensitive contains, either direction)
    for c in cols:
        cl = str(c).lower()
        if label in cl or cl in label:
            return c
    # try a bare date token like 06/20
    m = re.search(r"(\d{1,2})[/.](\d{1,2})", label)
    if m:
        token = f"{int(m.group(1)):02d}/{int(m.group(2)):02d}"
        for c in cols:
            if token in str(c):
                return c
    # fallback: today's column
    for c in cols:
        if today_token in str(c):
            return c
    return cols[1] if len(cols) > 1 else cols[0]


# ---------------------------------------------------------------------------
# 4. Eligibility + ranking — see screen_candidates() above (the pure engine).
#    find_replacements() adapts the roster/weekly xlsx to it for the Streamlit page.
# ---------------------------------------------------------------------------


def _staff_from_roster(roster: pd.DataFrame, weekly: pd.DataFrame, day_col: str) -> list[StaffLike]:
    """Normalize the roster + weekly grid into the engine's StaffLike inputs."""
    keep = ["Employee ID", day_col, "Scheduled Hrs (next 7d)"]
    merged = roster.merge(weekly[keep], on="Employee ID", how="left")
    out: list[StaffLike] = []
    for _, r in merged.iterrows():
        last_out = r.get("Last Clock Out")
        if isinstance(last_out, str) and "on shift" in last_out.lower():
            last_end = datetime.combine(TODAY, time(19, 0))     # finishing today's day shift
        elif last_out is None or (isinstance(last_out, float) and pd.isna(last_out)):
            last_end = None
        else:
            try:
                last_end = pd.to_datetime(last_out).to_pydatetime()
            except Exception:
                last_end = None
        out.append(StaffLike(
            employee_id=str(r["Employee ID"]), name=_name_of(r), role=str(r["Role"]),
            department=str(r["Department"]),
            certifications=[c.strip() for c in str(r.get("Certifications", "")).split(",") if c.strip()],
            contract=str(r.get("Contract", "")), max_hours_week=float(r.get("Max Hrs/Week") or 0),
            scheduled_hours_next7=float(r.get("Scheduled Hrs (next 7d)") or 0),
            shift_grid={day_col: str(r.get(day_col, "O"))},
            overtime_ok=str(r.get("Overtime OK", "")).strip().lower() in {"yes", "true", "1"},
            shift_preference=str(r.get("Shift Preference", "")),
            active=str(r.get("Status", "")).strip().lower() == "active",
            last_shift_end=last_end, phone=str(r.get("Phone", "")),
            persona=(str(r["Persona / Notes"]) if "Persona / Notes" in r and pd.notna(r["Persona / Notes"]) else None)))
    return out


def find_replacements(req: GapRequest, path: str | Path | None = None, top_n: int = 3) -> ShiftResult:
    """Run the full pipeline: filter the roster (via the pure engine), rank, and draft
    outreach for the top picks. Kept as the legacy/Streamlit contract (ShiftResult shape)."""
    roster, weekly = load_schedule(path)
    notes: list[str] = []

    role = req.role or "Registered Nurse"
    if not req.role:
        notes.append("No role was stated — assumed Registered Nurse.")
    shift = (req.shift or "night").strip().lower()
    if shift not in SHIFT_TIMES:
        shift = "night"
        notes.append("Shift unclear — assumed Night (19:00–07:00).")
    start, end = SHIFT_TIMES[shift]

    day_col = _resolve_day_column(weekly, req.day_label)
    notes.append(f"Matched the gap to schedule column '{day_col}'.")
    if not req.required_certs:
        notes.append("No certifications were stated — qualification judged on role only.")

    shift_start = datetime.combine(TODAY, time(19, 0)) if shift == "night" else datetime.combine(TODAY, time(7, 0))
    gap = GapSpec(role=role, department=req.department, shift=shift, shift_start=shift_start,
                  shift_end=shift_start + timedelta(hours=12), shift_hours=12.0, day_label=day_col,
                  required_certs=req.required_certs, person_out_id=_extract_id(req.person_out),
                  person_out=req.person_out)
    rep = screen_candidates(_staff_from_roster(roster, weekly, day_col), gap)

    candidates = [
        Candidate(
            employee_id=c.employee_id, name=c.name, role=c.role, department=c.department,
            certifications=", ".join(req.required_certs) if req.required_certs else "",
            contract=c.contract, overtime_ok=c.overtime_ok, scheduled_hrs=c.scheduled_hours,
            max_hrs=c.max_hours, phone=c.phone, persona=c.persona, score=c.score, why=c.why)
        for c in rep.eligible
    ]
    dept = req.department or ""
    for c in candidates[:top_n]:
        c.draft_message = _draft_outreach(c, role, dept, shift, start, end, day_col)

    gap_summary = (
        f"{(req.person_out or 'A staff member')} called in sick — "
        f"{role}{(' · ' + dept) if dept else ''}, {shift} shift ({start}–{end}), {day_col}."
    )
    return ShiftResult(
        gap_summary=gap_summary,
        shift_window=f"{start}–{end}",
        role=role,
        department=req.department,
        required_certs=req.required_certs,
        day_label=day_col,
        candidates=candidates,
        n_screened=rep.n_active,
        confidence=_confidence(candidates, req),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 5. Outreach drafting (simulated send)
# ---------------------------------------------------------------------------


def _draft_outreach(c: Candidate, role: str, dept: str, shift: str, start: str, end: str, day_col: str) -> str:
    """Friendly SMS-style outreach for one candidate. Short, warm, gives a one-tap reply."""
    first = c.name.split()[0]
    ward = f"{dept} " if dept else ""
    return (
        f"Hi {first}, it's UKS staffing. We have an urgent {ward}{shift}-shift gap "
        f"{day_col} ({start}-{end}, 12h) — a colleague just called in sick. "
        f"You're qualified and off tonight; could you cover? "
        f"Reply YES to take it or NO if you can't. Thank you so much! 🙏"
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _name_of(row) -> str:
    fn = str(row.get("First Name", "")).strip()
    ln = str(row.get("Last Name", "")).strip()
    name = (fn + " " + ln).strip()
    return name or str(row.get("Name", "")).strip()


def _extract_id(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(r"HOSP-\d+", text, re.IGNORECASE)
    return m.group(0).upper() if m else None


def _confidence(candidates: list[Candidate], req: GapRequest) -> float:
    """Plain-language confidence: do we have qualified, rested, willing options?"""
    if not candidates:
        return 20.0
    base = 70.0
    if req.required_certs:
        base += 10  # we matched on explicit certs, not just role
    if len(candidates) >= 3:
        base += 10
    if any(c.overtime_ok for c in candidates[:3]):
        base += 5
    if candidates[0].score >= 20:
        base += 5
    return float(min(base, 97.0))
