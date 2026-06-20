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
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from core import config, llm

# Hackathon "now": Saturday 20 June 2026, 18:30 (just before the night shift).
NOW = datetime(2026, 6, 20, 18, 30)
TODAY = NOW.date()
# A coverer should not have clocked out from a long shift this morning past this time.
RESTED_CUTOFF = datetime.combine(TODAY, time(8, 30))

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
# 4. Eligibility + ranking (deterministic, auditable)
# ---------------------------------------------------------------------------

# Roles considered competent for a nursing shift (robust to slight naming).
_NURSE_EQUIVALENTS = {"registered nurse", "charge nurse", "nurse practitioner"}


def _role_matches(candidate_role: str, required_role: str) -> bool:
    cand = str(candidate_role).strip().lower()
    req = str(required_role).strip().lower()
    if req in cand or cand in req:
        return True
    # nurse-family equivalence so a Charge Nurse can cover an RN gap
    if req in _NURSE_EQUIVALENTS and cand in _NURSE_EQUIVALENTS:
        return True
    return False


def _has_all_certs(held: str, required: list[str]) -> bool:
    hu = str(held).upper()
    return all(c.strip().upper() in hu for c in required if c.strip())


def _is_rested(last_clock_out) -> tuple[bool, str]:
    """Rule 5: not currently on shift, and last clock-out before ~08:30 today."""
    if last_clock_out is None or (isinstance(last_clock_out, float) and pd.isna(last_clock_out)):
        return True, "no recent long shift on record"
    s = str(last_clock_out)
    if "on shift" in s.lower():
        return False, "currently on a day shift — would not be rested"
    if isinstance(last_clock_out, datetime):
        co = last_clock_out
    elif isinstance(last_clock_out, pd.Timestamp):
        co = last_clock_out.to_pydatetime()
    else:
        try:
            co = pd.to_datetime(last_clock_out).to_pydatetime()
        except Exception:
            return True, "clock-out unreadable — treated as rested"
    if co > RESTED_CUTOFF:
        return False, f"clocked out at {co:%H:%M} today — too recent to be rested"
    return True, f"last clocked out {co:%a %H:%M} — well rested"


def find_replacements(req: GapRequest, path: str | Path | None = None, top_n: int = 3) -> ShiftResult:
    """Run the full pipeline: filter the roster, rank, and draft outreach for the top picks."""
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
    shift_code = "N" if shift == "night" else "D"

    day_col = _resolve_day_column(weekly, req.day_label)
    notes.append(f"Matched the gap to schedule column '{day_col}'.")
    if not req.required_certs:
        notes.append("No certifications were stated — qualification judged on role only.")

    # join the day's assignment + scheduled hours onto the roster
    keep = ["Employee ID", day_col, "Scheduled Hrs (next 7d)"]
    merged = roster.merge(weekly[keep], on="Employee ID", how="left")

    person_out_id = _extract_id(req.person_out)

    candidates: list[Candidate] = []
    screened = 0
    for _, r in merged.iterrows():
        emp_id = str(r["Employee ID"])
        # never offer the shift to the person who called in sick
        if person_out_id and emp_id == person_out_id:
            continue
        if req.person_out and _name_of(r).lower() in str(req.person_out).lower():
            continue

        # only consider active staff for the screened count
        active = str(r.get("Status", "")).strip().lower() == "active"
        if active:
            screened += 1

        # ---- hard eligibility gates ----
        if not active:
            continue
        if not _role_matches(r["Role"], role):
            continue
        if req.required_certs and not _has_all_certs(r["Certifications"], req.required_certs):
            continue
        # already assigned that day (working a D or N) -> not available
        assigned = str(r.get(day_col, "")).strip().upper()
        if assigned and assigned != "O":
            continue
        rested, rest_reason = _is_rested(r.get("Last Clock Out"))
        if not rested:
            continue
        # weekly hours cap: current scheduled + this 12h shift must fit
        sched = float(r.get("Scheduled Hrs (next 7d)") or 0)
        maxh = float(r.get("Max Hrs/Week") or 0)
        if maxh and (sched + 12) > maxh:
            continue

        # ---- passed all gates -> build reasons + score ----
        headroom = (maxh - sched) if maxh else 0
        ot_ok = str(r.get("Overtime OK", "")).strip().lower() in {"yes", "true", "1"}
        why = [
            f"{r['Role']} — qualified for the {role} gap",
            "holds " + (", ".join(req.required_certs) if req.required_certs else str(r["Certifications"])),
            f"off tonight ({day_col} = Off)",
            rest_reason,
            f"{int(headroom)}h of weekly hours headroom (cap {int(maxh)}h)",
        ]
        same_dept = str(r["Department"]).strip().lower() == str(req.department or "").strip().lower()
        if same_dept and req.department:
            why.append(f"already works in {r['Department']} — knows the ward")
        if ot_ok:
            why.append("flagged Overtime OK")

        # score: rested-headroom + willingness + same-dept + cheap-to-call signals
        score = 0.0
        score += min(headroom, 24)              # more rest/hours headroom is better
        score += 8 if ot_ok else 0
        score += 6 if same_dept else 0
        contract = str(r.get("Contract", "")).lower()
        if "per-diem" in contract or "per diem" in contract:
            score += 5                          # per-diem = easy/cheap to call in
        elif "part" in contract:
            score += 3
        pref = str(r.get("Shift Preference", "")).lower()
        if shift in pref or "flexible" in pref:
            score += 4                          # prefers this shift / flexible

        candidates.append(
            Candidate(
                employee_id=emp_id,
                name=_name_of(r),
                role=str(r["Role"]),
                department=str(r["Department"]),
                certifications=str(r["Certifications"]),
                contract=str(r.get("Contract", "")),
                overtime_ok=ot_ok,
                scheduled_hrs=sched,
                max_hrs=maxh,
                phone=str(r.get("Phone", "")),
                persona=(str(r["Persona / Notes"]) if "Persona / Notes" in r and pd.notna(r["Persona / Notes"]) else None),
                score=round(score, 1),
                why=why,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)

    # draft outreach for the top picks
    dept = req.department or ""
    for c in candidates[:top_n]:
        c.draft_message = _draft_outreach(c, role, dept, shift, start, end, day_col)

    confidence = _confidence(candidates, req)
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
        n_screened=screened,
        confidence=confidence,
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
