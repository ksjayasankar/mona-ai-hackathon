# UKS Shift-Replacement Action Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build P2 UKS — a production-grade shift-replacement action agent: a deterministic ArbZG-compliant eligibility engine, free-text gap parsing, sequential SMS outreach with magic-link accept, a race-safe first-accept lock, and a live SSE dashboard — wired web → FastAPI → core engine → SQLite/Postgres, tenant-scoped.

**Architecture:** The substance is a PURE, deterministic eligibility+ranking engine in `agents/shift.py` (no DB/web/LLM) that, given a list of staff and a gap, returns ranked eligible candidates (each with a why) AND excluded candidates (each with the rule that excluded them — qualification, already-on-shift, ArbZG §5 rest, ArbZG §3 weekly cap, on-leave). `services/shift.py` seeds `Staff` from the hospital xlsx, persists `ShiftGap`/`OutreachLog`, runs the engine over DB rows, drives sequential outreach (real Twilio SMS via its REST API over httpx, or a logged simulated send), and performs the first-accept lock as a single atomic `UPDATE … WHERE status='open'` (rowcount guard). `api/routes/shift.py` exposes authenticated tenant-scoped endpoints + an SSE stream fed by an in-process event bus. `web/src/app/uks/**` is the live dashboard + accept page.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy 2.0, Alembic, pandas/openpyxl, pydantic v2, pytest; Next.js 16 (App Router, `src/app`) + React 19 + Tailwind v4 + TypeScript; httpx (Twilio REST + tests); Starlette `StreamingResponse` for SSE. LLM via `core.llm` (ollama offline / gemini demo).

## Global Constraints

- **Own only:** `services/shift.py`, `api/routes/shift.py`, `web/src/app/uks/**`, and refine `agents/shift.py` + `core/models/shift.py`. New files allowed: `tests/test_shift.py`, one Alembic migration under `alembic/versions/`, `web/src/app/uks/api.ts`. Explicitly-authorized shared edits (task body): the ONE line `app.include_router(shift.router)` in `api/main.py`; `TWILIO_* + PUBLIC_BASE_URL` in `.env.example`; the Phase-1 status in `STATE.md`. Touch NOTHING else (not `core/db`, `core/auth`, `core/agent`, `core/llm`, `core/models/__init__.py`, P10 files, `web/src/lib/*`, `web/src/components/*`).
- **Keep class names** `Staff`, `ShiftGap`, `OutreachLog` (so `core/models/__init__.py` needs no edit).
- **Backward-compat:** `agents/shift.py` MUST keep `parse_gap_message`, `GapRequest`, `find_replacements(req, top_n=3) -> ShiftResult`, and `ShiftResult`/`Candidate` field shapes working — they're consumed by `app/pages/02_UKS_Shift_Replacement.py` and `scripts/verify_all.py`.
- **No new pip dependencies.** Twilio = call its REST API with `httpx` (no `twilio` SDK). SSE = `starlette.responses.StreamingResponse` (no `sse_starlette`).
- **Tests run OFFLINE + FREE:** `conftest.py` already forces `LLM_PROVIDER=ollama`, `AUTH_MODE=dev`, throwaway SQLite. Tests must not require live Twilio or live Gemini. Drive the engine/service with **structured** gaps (not the LLM parser) so they're deterministic.
- **The canonical demo scenario** (from the xlsx `Scenario` sheet): "now" = **Sat 2026-06-20 18:30**; Felix Haddad (HOSP-1059), Registered Nurse, **ICU**, called in sick for **tonight's NIGHT shift (19:00–07:00, Sat 06/20)**; the gap needs **BLS + ACLS**. Night shift_start = `2026-06-20 19:00`, shift_end = `2026-06-21 07:00`, shift_hours = 12.
- **ArbZG rules baked into the engine:** §5 ≥11h rest between last shift end and the new shift start; §3 weekly cap = `scheduled_hours_next7 + shift_hours ≤ max_hours_week`.

---

## File Structure

- `core/models/shift.py` — extend `Staff`/`ShiftGap`/`OutreachLog` with the columns the engine/outreach/lock need (Task 1).
- `alembic/versions/<rev>_p2_shift_columns.py` — additive migration for those columns (Task 1).
- `agents/shift.py` — add the PURE engine (`StaffLike`, `GapSpec`, `ScoredCandidate`, `ExcludedCandidate`, `EligibilityReport`, `screen_candidates`); refactor `find_replacements` onto it; keep all legacy symbols (Tasks 2).
- `services/shift.py` — seeding, gap creation, screening, outreach (Twilio/sim), race-safe accept/decline, gap state, history, event bus (Tasks 3–6).
- `api/routes/shift.py` — authenticated tenant-scoped routes + SSE (Task 7).
- `api/main.py` — one added line wiring the router (Task 7).
- `.env.example` — TWILIO_* + PUBLIC_BASE_URL (Task 7).
- `web/src/app/uks/page.tsx`, `web/src/app/uks/accept/page.tsx`, `web/src/app/uks/api.ts` — dashboard + accept page + fetch helpers (Task 8).
- `tests/test_shift.py` — all offline tests (Tasks 2–7).
- `STATE.md` — Phase-1 P2-done update (Task 9).

---

### Task 1: Domain models + Alembic migration

**Files:**
- Modify: `core/models/shift.py`
- Create: `alembic/versions/<rev>_p2_shift_columns.py`
- Test: `tests/test_shift.py`

**Interfaces:**
- Produces: `Staff(employee_id, name, role, department, qualifications: list[str], contract, max_hours_week: float|None, scheduled_hours_next7: float, shift_grid: dict, overtime_ok: bool, shift_preference, active, last_shift_end: datetime|None, last_contacted_at: datetime|None, persona, phone, tenant_id, id, created_at)`; `ShiftGap(… role, department, shift, day_label, required_certs: list[str], person_out, shift_start: datetime|None, shift_end: datetime|None, shift_hours: float, status, version: int, filled_by_staff_id: str|None, filled_at: datetime|None, tenant_id, id, created_at)`; `OutreachLog(… gap_id, staff_id, channel, message, status, seq: int, token: str|None, sent_at: datetime|None, responded_at: datetime|None, tenant_id, id, created_at)`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_shift.py`)

```python
"""P2 UKS shift-replacement tests — offline (local ollama, structured gaps, no Twilio)."""
from datetime import datetime

from sqlmodel import Session

from core.db import engine
from core.models import OutreachLog, ShiftGap, Staff


def test_models_roundtrip_new_columns():
    with Session(engine) as s:
        st = Staff(tenant_id="t1", employee_id="HOSP-9001", name="Test Nurse",
                   role="Registered Nurse", department="ICU", qualifications=["BLS", "ACLS"],
                   contract="Per-diem", max_hours_week=48, scheduled_hours_next7=24.0,
                   shift_grid={"Sat 06/20": "O"}, overtime_ok=True, shift_preference="Night",
                   active=True, last_shift_end=datetime(2026, 6, 19, 19, 0), persona="flex",
                   phone="+49 150 0000000")
        s.add(st); s.commit(); s.refresh(st)
        gap = ShiftGap(tenant_id="t1", role="Registered Nurse", department="ICU", shift="night",
                       day_label="Sat 06/20", required_certs=["BLS", "ACLS"], person_out="Felix",
                       shift_start=datetime(2026, 6, 20, 19, 0), shift_end=datetime(2026, 6, 21, 7, 0),
                       shift_hours=12.0, status="open", version=0)
        s.add(gap); s.commit(); s.refresh(gap)
        log = OutreachLog(tenant_id="t1", gap_id=gap.id, staff_id=st.id, channel="sms",
                          message="hi", status="queued", seq=0, token="tok-abc")
        s.add(log); s.commit(); s.refresh(log)
        assert st.shift_grid["Sat 06/20"] == "O" and st.overtime_ok is True
        assert gap.version == 0 and gap.shift_hours == 12.0
        assert log.token == "tok-abc" and log.seq == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_shift.py::test_models_roundtrip_new_columns -v`
Expected: FAIL — `TypeError`/unexpected keyword (e.g. `employee_id`) until the model is extended.

- [ ] **Step 3: Replace `core/models/shift.py` with the extended models**

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_shift.py::test_models_roundtrip_new_columns -v`
Expected: PASS (conftest `init_db()` create_all picks up the new columns on the throwaway SQLite).

- [ ] **Step 5: Write the Alembic migration (for Postgres/prod)**

Find the current head, then create the file. Run: `uv run alembic heads` → confirm `acc981dd630a (head)`. Create `alembic/versions/p2shiftcols_p2_shift_columns.py`:

```python
"""p2 shift columns

Revision ID: p2shiftcols01
Revises: acc981dd630a
Create Date: 2026-06-20

Additive columns for the P2 UKS shift-replacement flagship. Batch ops keep SQLite happy.
"""
from alembic import op
import sqlalchemy as sa

revision = "p2shiftcols01"
down_revision = "acc981dd630a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("staff") as b:
        b.add_column(sa.Column("employee_id", sa.String(), nullable=True))
        b.add_column(sa.Column("contract", sa.String(), nullable=True))
        b.add_column(sa.Column("scheduled_hours_next7", sa.Float(), nullable=False, server_default="0"))
        b.add_column(sa.Column("shift_grid", sa.JSON(), nullable=True))
        b.add_column(sa.Column("overtime_ok", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("shift_preference", sa.String(), nullable=True))
        b.add_column(sa.Column("last_shift_end", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("last_contacted_at", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("persona", sa.String(), nullable=True))
        b.create_index("ix_staff_employee_id", ["employee_id"])

    with op.batch_alter_table("shiftgap") as b:
        b.add_column(sa.Column("person_out", sa.String(), nullable=True))
        b.add_column(sa.Column("shift_start", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("shift_end", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("shift_hours", sa.Float(), nullable=False, server_default="12"))
        b.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("filled_by_staff_id", sa.String(), nullable=True))
        b.add_column(sa.Column("filled_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("outreachlog") as b:
        b.add_column(sa.Column("seq", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("token", sa.String(), nullable=True))
        b.add_column(sa.Column("sent_at", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("responded_at", sa.DateTime(), nullable=True))
        b.create_index("ix_outreachlog_token", ["token"])
        b.create_index("ix_outreachlog_gap_id", ["gap_id"])


def downgrade() -> None:
    with op.batch_alter_table("outreachlog") as b:
        b.drop_index("ix_outreachlog_gap_id")
        b.drop_index("ix_outreachlog_token")
        for c in ("responded_at", "sent_at", "token", "seq"):
            b.drop_column(c)
    with op.batch_alter_table("shiftgap") as b:
        for c in ("filled_at", "filled_by_staff_id", "version", "shift_hours", "shift_end", "shift_start", "person_out"):
            b.drop_column(c)
    with op.batch_alter_table("staff") as b:
        b.drop_index("ix_staff_employee_id")
        for c in ("persona", "last_contacted_at", "last_shift_end", "shift_preference",
                  "overtime_ok", "shift_grid", "scheduled_hours_next7", "contract", "employee_id"):
            b.drop_column(c)
```

- [ ] **Step 6: Verify the migration applies on a clean SQLite DB**

Run: `DATABASE_URL=sqlite:////tmp/p2_mig.db uv run alembic upgrade head && DATABASE_URL=sqlite:////tmp/p2_mig.db uv run alembic downgrade -1 && rm -f /tmp/p2_mig.db`
Expected: both upgrade then downgrade succeed with no errors.

- [ ] **Step 7: Commit**

```bash
git add core/models/shift.py alembic/versions/p2shiftcols_p2_shift_columns.py tests/test_shift.py
git commit -m "P2: extend shift domain models + alembic migration"
```

---

### Task 2: Pure ArbZG eligibility + ranking engine

**Files:**
- Modify: `agents/shift.py` (add the engine; refactor `find_replacements` onto it; keep all legacy symbols)
- Test: `tests/test_shift.py`

**Interfaces:**
- Consumes: nothing from prior tasks (pure, in-memory).
- Produces: `StaffLike` (dataclass), `GapSpec` (pydantic), `ScoredCandidate`, `ExcludedCandidate`, `EligibilityReport` (pydantic), `screen_candidates(staff: list[StaffLike], gap: GapSpec) -> EligibilityReport`, and `REST_MIN_HOURS = 11.0`. Preserves: `GapRequest`, `parse_gap_message`, `find_replacements`, `ShiftResult`, `Candidate`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_shift.py`)

```python
from datetime import datetime as _dt

from agents import shift as shift_agent


def _night_gap(**over):
    base = dict(role="Registered Nurse", department="ICU", shift="night",
                shift_start=_dt(2026, 6, 20, 19, 0), shift_end=_dt(2026, 6, 21, 7, 0),
                shift_hours=12.0, day_label="Sat 06/20", required_certs=["BLS", "ACLS"],
                person_out_id="HOSP-1059", person_out="Felix Haddad")
    base.update(over)
    return shift_agent.GapSpec(**base)


def _staff(emp, role="Registered Nurse", dept="ICU", certs=("BLS", "ACLS"), active=True,
           grid_today="O", sched=24.0, maxh=48.0, last_end=_dt(2026, 6, 19, 19, 0),
           ot=True, contract="Full-time", pref="Flexible", last_contacted=None):
    return shift_agent.StaffLike(
        employee_id=emp, name=f"Nurse {emp}", role=role, department=dept,
        certifications=list(certs), contract=contract, max_hours_week=maxh,
        scheduled_hours_next7=sched, shift_grid={"Sat 06/20": grid_today}, overtime_ok=ot,
        shift_preference=pref, active=active, last_shift_end=last_end, phone="+49 150 1",
        persona=None, last_contacted_at=last_contacted)


def test_engine_excludes_each_arbzg_rule():
    staff = [
        _staff("HOSP-1059"),                                   # the person who is OUT -> never listed
        _staff("HOSP-2001", active=False),                     # on leave
        _staff("HOSP-2002", role="Pharmacist"),                # wrong role
        _staff("HOSP-2003", certs=("BLS",)),                   # missing ACLS
        _staff("HOSP-2004", grid_today="N"),                   # already on a night shift that day
        _staff("HOSP-2005", last_end=_dt(2026, 6, 20, 14, 0)), # 5h rest -> §5 fail
        _staff("HOSP-2006", sched=40.0, maxh=48.0),            # 40+12=52 > 48 -> §3 fail
        _staff("HOSP-2007"),                                   # fully eligible
    ]
    rep = shift_agent.screen_candidates(staff, _night_gap())
    elig_ids = {c.employee_id for c in rep.eligible}
    excl = {e.employee_id: e.rule for e in rep.excluded}
    assert "HOSP-1059" not in elig_ids and "HOSP-1059" not in excl       # the sick person is dropped entirely
    assert "HOSP-2007" in elig_ids
    assert excl["HOSP-2001"] == "active"
    assert excl["HOSP-2002"] == "role"
    assert excl["HOSP-2003"] == "certs"
    assert excl["HOSP-2004"] == "already_on_shift"
    assert excl["HOSP-2005"] == "rest_§5"
    assert excl["HOSP-2006"] == "weekly_cap_§3"
    # every exclusion carries a human reason that names the rule
    assert all(e.reason for e in rep.excluded)
    assert any("§5" in e.reason for e in rep.excluded)
    assert any("§3" in e.reason for e in rep.excluded)


def test_engine_ranks_fairly():
    # two eligible; the one with more headroom + never contacted should rank first
    a = _staff("HOSP-3001", sched=36.0, ot=False, last_contacted=_dt(2026, 6, 20, 9, 0))
    b = _staff("HOSP-3002", sched=12.0, ot=True, last_contacted=None)
    rep = shift_agent.screen_candidates([a, b], _night_gap())
    assert [c.employee_id for c in rep.eligible][0] == "HOSP-3002"
    assert rep.eligible[0].score >= rep.eligible[1].score
    assert rep.eligible[0].why  # reasons present


def test_charge_nurse_can_cover_rn_gap():
    cn = _staff("HOSP-4001", role="Charge Nurse")
    rep = shift_agent.screen_candidates([cn], _night_gap())
    assert {c.employee_id for c in rep.eligible} == {"HOSP-4001"}


def test_find_replacements_backcompat_shape():
    req = shift_agent.GapRequest(person_out="Felix Haddad (HOSP-1059)", role="Registered Nurse",
                                 department="ICU", shift="night", day_label="tonight",
                                 required_certs=["BLS", "ACLS"])
    res = shift_agent.find_replacements(req, top_n=3)
    assert isinstance(res, shift_agent.ShiftResult)
    assert res.role == "Registered Nurse" and res.shift_window == "19:00–07:00"
    assert res.candidates and res.candidates[0].why
    assert res.candidates[0].draft_message  # top picks get an outreach draft
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_shift.py -k "engine or charge or backcompat" -v`
Expected: FAIL — `AttributeError: module 'agents.shift' has no attribute 'screen_candidates'` etc.

- [ ] **Step 3: Add the engine to `agents/shift.py`**

Insert (after the existing imports / `Candidate` block; keep everything else intact). Add `from dataclasses import dataclass` to the imports at top.

```python
# ===========================================================================
# DETERMINISTIC ELIGIBILITY ENGINE (the substance beat) — pure, ArbZG-compliant
# ===========================================================================
REST_MIN_HOURS = 11.0   # ArbZG §5: ≥11h rest between shifts
_NURSE_FAMILY = {"registered nurse", "charge nurse", "nurse practitioner"}


@dataclass
class StaffLike:
    """One staff member, normalized for the engine (no DB/pandas coupling)."""
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

        def excl(rule: str, reason: str):
            excluded.append(ExcludedCandidate(employee_id=p.employee_id, name=p.name,
                                              role=p.role, department=p.department,
                                              rule=rule, reason=reason))

        if not p.active:
            excl("active", "On leave / inactive — not available.")
            continue
        n_active += 1
        if not _role_ok(p.role, gap.role):
            excl("role", f"{p.role} can't staff a {gap.role} {gap.department or ''} shift.".strip())
            continue
        if gap.required_certs and not _has_certs(p.certifications, gap.required_certs):
            missing = [c for c in gap.required_certs if c.strip().upper() not in {x.upper() for x in p.certifications}]
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

        # ---- eligible: build why + fairness/practicality score --------------
        headroom = (maxh - (sched + gap.shift_hours)) if maxh else 0.0
        same_dept = bool(gap.department) and str(p.department).strip().lower() == gap.department.strip().lower()
        pref = str(p.shift_preference or "").lower()
        why = [
            f"{p.role} — qualified for the {gap.role} gap",
            ("holds " + ", ".join(gap.required_certs)) if gap.required_certs else f"certs: {', '.join(p.certifications)}",
            f"off on {gap.day_label} (not already scheduled)",
            (f"{rest:.0f}h rest before the shift — meets ArbZG §5" if rest is not None
             else "no recent shift on record — well rested"),
            f"{headroom:.0f}h weekly-hours headroom after this shift (cap {maxh:.0f}h) — within ArbZG §3",
        ]
        score = min(headroom, 24.0)
        if p.last_contacted_at is None:
            score += 6.0; why.append("not contacted recently — fair to ask")
        else:
            days = max(0.0, (gap.shift_start - p.last_contacted_at).total_seconds() / 86400.0)
            score += min(days, 7.0)
            why.append(f"last asked {days:.0f}d ago")
        if p.overtime_ok:
            score += 8.0; why.append("flagged Overtime OK")
        if same_dept:
            score += 6.0; why.append(f"works in {p.department} — knows the ward")
        c = (p.contract or "").lower()
        if "per-diem" in c or "per diem" in c:
            score += 5.0; why.append("per-diem — quick to call in")
        elif "part" in c:
            score += 3.0
        if gap.shift in pref or "flexible" in pref:
            score += 4.0; why.append(f"prefers/flexible on {gap.shift} shifts")

        eligible.append(ScoredCandidate(
            employee_id=p.employee_id, name=p.name, role=p.role, department=p.department,
            phone=p.phone, contract=p.contract or "", scheduled_hours=sched, max_hours=maxh,
            overtime_ok=p.overtime_ok, rest_hours=rest, headroom_hours=headroom,
            persona=p.persona, score=round(score, 1), why=why))

    eligible.sort(key=lambda x: x.score, reverse=True)
    return EligibilityReport(eligible=eligible, excluded=excluded, n_total=len(staff),
                             n_active=n_active, n_eligible=len(eligible))
```

- [ ] **Step 4: Refactor `find_replacements` onto the engine (preserve `ShiftResult`/`Candidate`)**

Replace the body of `find_replacements` (keep its signature and the helper functions it uses). It now builds `StaffLike`s from the roster, calls `screen_candidates`, and maps the result back to the legacy `Candidate`/`ShiftResult` shapes (drafting outreach for the top N):

```python
def _staff_from_roster(roster, weekly, day_col) -> list[StaffLike]:
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
            shift_grid={day_col: str(r.get(day_col, "O"))}, overtime_ok=str(r.get("Overtime OK", "")).strip().lower() in {"yes", "true", "1"},
            shift_preference=str(r.get("Shift Preference", "")), active=str(r.get("Status", "")).strip().lower() == "active",
            last_shift_end=last_end, phone=str(r.get("Phone", "")),
            persona=(str(r["Persona / Notes"]) if "Persona / Notes" in r and pd.notna(r["Persona / Notes"]) else None)))
    return out


def find_replacements(req: GapRequest, path: str | Path | None = None, top_n: int = 3) -> ShiftResult:
    roster, weekly = load_schedule(path)
    notes: list[str] = []
    role = req.role or "Registered Nurse"
    if not req.role:
        notes.append("No role was stated — assumed Registered Nurse.")
    shift = (req.shift or "night").strip().lower()
    if shift not in SHIFT_TIMES:
        shift = "night"; notes.append("Shift unclear — assumed Night (19:00–07:00).")
    start, end = SHIFT_TIMES[shift]
    day_col = _resolve_day_column(weekly, req.day_label)
    notes.append(f"Matched the gap to schedule column '{day_col}'.")
    if not req.required_certs:
        notes.append("No certifications were stated — qualification judged on role only.")

    shift_start = datetime.combine(TODAY, time(19, 0)) if shift == "night" else datetime.combine(TODAY, time(7, 0))
    shift_end = shift_start + timedelta(hours=12)
    gap = GapSpec(role=role, department=req.department, shift=shift, shift_start=shift_start,
                  shift_end=shift_end, shift_hours=12.0, day_label=day_col,
                  required_certs=req.required_certs, person_out_id=_extract_id(req.person_out),
                  person_out=req.person_out)
    staff = _staff_from_roster(roster, weekly, day_col)
    rep = screen_candidates(staff, gap)

    candidates = [
        Candidate(employee_id=c.employee_id, name=c.name, role=c.role, department=c.department,
                  certifications=", ".join(req.required_certs) if req.required_certs else "",
                  contract=c.contract, overtime_ok=c.overtime_ok, scheduled_hrs=c.scheduled_hours,
                  max_hrs=c.max_hours, phone=c.phone, persona=c.persona, score=c.score, why=c.why)
        for c in rep.eligible
    ]
    dept = req.department or ""
    for c in candidates[:top_n]:
        c.draft_message = _draft_outreach(c, role, dept, shift, start, end, day_col)
    return ShiftResult(
        gap_summary=f"{(req.person_out or 'A staff member')} called in sick — "
                    f"{role}{(' · ' + dept) if dept else ''}, {shift} shift ({start}–{end}), {day_col}.",
        shift_window=f"{start}–{end}", role=role, department=req.department,
        required_certs=req.required_certs, day_label=day_col, candidates=candidates,
        n_screened=rep.n_active, confidence=_confidence(candidates, req), notes=notes)
```

Also add `timedelta` to the `from datetime import …` line at the top of the file.

- [ ] **Step 5: Run the full engine test set + the existing parse smoke**

Run: `uv run pytest tests/test_shift.py -k "engine or charge or backcompat" -v`
Expected: PASS (4 tests). Then `uv run python -c "from agents import shift; print(shift.find_replacements(shift.GapRequest(role='Registered Nurse', department='ICU', shift='night', day_label='tonight', required_certs=['BLS','ACLS'])).candidates[0].name)"` prints a name without error.

- [ ] **Step 6: Commit**

```bash
git add agents/shift.py tests/test_shift.py
git commit -m "P2: pure ArbZG eligibility + ranking engine; refactor find_replacements onto it"
```

---

### Task 3: Seed Staff from the hospital xlsx

**Files:**
- Create: `services/shift.py`
- Test: `tests/test_shift.py`

**Interfaces:**
- Consumes: `core.models.Staff`, `core.db.engine`, `core.config.PATHS`, `agents.shift.NOW`.
- Produces: `seed_staff(tenant_id: str, path=None) -> int` (rows upserted), `staff_to_like(s: Staff, last_contacted=None) -> agents.shift.StaffLike`.

- [ ] **Step 1: Write the failing test**

```python
from core.auth import get_or_create_tenant
from services import shift as shift_svc


def test_seed_staff_idempotent_and_parsed():
    tenant = get_or_create_tenant("test-uks", "Test UKS")
    n1 = shift_svc.seed_staff(tenant)
    n2 = shift_svc.seed_staff(tenant)          # re-seed must not duplicate
    assert n1 == n2 == 100
    from sqlmodel import Session, select
    from core.models import Staff
    with Session(engine) as s:
        rows = s.exec(select(Staff).where(Staff.tenant_id == tenant)).all()
        assert len(rows) == 100
        felix = next(r for r in rows if r.employee_id == "HOSP-1059")
        assert felix.role == "Registered Nurse" and felix.department == "ICU"
        assert "ACLS" in felix.qualifications
        # an "— on shift —" person has last_shift_end set to today 19:00 (finishing a day shift)
        on_shift = [r for r in rows if r.last_shift_end == _dt(2026, 6, 20, 19, 0)]
        assert on_shift
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_shift.py::test_seed_staff_idempotent_and_parsed -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.shift'`.

- [ ] **Step 3: Create `services/shift.py` with the seeding section**

```python
"""P2 UKS — shift-replacement service (tenant-scoped, persisted, production-grade).

Pipeline: SEED staff from the hospital xlsx -> CREATE a gap (free-text via core.llm or
structured) -> SCREEN with the pure ArbZG engine -> sequential OUTREACH (Twilio SMS or a
logged simulated send, each with a magic-link) -> race-safe ACCEPT (single atomic UPDATE
guarded on status/version) -> live state for the SSE dashboard. agents/shift.py stays pure
logic; this is the product version."""
from __future__ import annotations

import asyncio
import logging
import os
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
        existing = {r.employee_id: r for r in s.exec(select(Staff).where(Staff.tenant_id == tenant_id)).all()}
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_shift.py::test_seed_staff_idempotent_and_parsed -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/shift.py tests/test_shift.py
git commit -m "P2: seed Staff from hospital xlsx (idempotent upsert)"
```

---

### Task 4: Gap creation + screening service

**Files:**
- Modify: `services/shift.py`
- Test: `tests/test_shift.py`

**Interfaces:**
- Consumes: `seed_staff`, `staff_to_like`, `agents.shift.{GapSpec, screen_candidates, parse_gap_message, GapRequest, NOW}`.
- Produces: `resolve_gap_spec(req: GapRequest) -> GapSpec`; `create_gap(tenant_id, *, message=None, structured: dict|None=None, provider=None) -> str` (gap_id); `screen_gap(tenant_id, gap_id) -> EligibilityReport`; `gap_state(tenant_id, gap_id) -> dict` (gap + eligible + excluded + outreach + filled_by); `list_gaps(tenant_id, limit=20) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

```python
def test_create_and_screen_felix_gap():
    tenant = get_or_create_tenant("test-uks2", "Test UKS 2")
    shift_svc.seed_staff(tenant)
    gid = shift_svc.create_gap(tenant, structured=dict(
        role="Registered Nurse", department="ICU", shift="night", day_label="Sat 06/20",
        required_certs=["BLS", "ACLS"], person_out="Felix Haddad (HOSP-1059)"))
    rep = shift_svc.screen_gap(tenant, gid)
    assert rep.n_eligible >= 1
    # every eligible is RN-family, off tonight, rested, under cap (the engine guarantees it)
    assert all(c.max_hours >= c.scheduled_hours + 12 for c in rep.eligible)
    # Felix himself is never offered his own shift
    assert all(c.employee_id != "HOSP-1059" for c in rep.eligible)
    # the board exposes excluded-with-reason
    assert rep.excluded and all(e.reason for e in rep.excluded)
    state = shift_svc.gap_state(tenant, gid)
    assert state["gap"]["status"] == "open" and state["eligible"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_shift.py::test_create_and_screen_felix_gap -v`
Expected: FAIL — `AttributeError: module 'services.shift' has no attribute 'create_gap'`.

- [ ] **Step 3: Add gap creation + screening to `services/shift.py`**

```python
# --------------------------------------------------------------------------
# CREATE GAP + SCREEN
# --------------------------------------------------------------------------
def resolve_gap_spec(req: engine.GapRequest) -> engine.GapSpec:
    role = req.role or "Registered Nurse"
    shift = (req.shift or "night").strip().lower()
    if shift not in SHIFT_TIMES:
        shift = "night"
    start_t, _ = SHIFT_TIMES[shift]
    shift_start = datetime.combine(TODAY, start_t)
    shift_end = shift_start + timedelta(hours=12)
    day_label = req.day_label or TODAY.strftime("%a %m/%d")
    # normalize fuzzy labels like "tonight" -> the dated grid column
    if day_label.strip().lower() in {"tonight", "today", "now", ""}:
        day_label = TODAY.strftime("%a %m/%d").replace(" 0", " ")  # "Sat 6/20" -> match below
        day_label = NOW.strftime("%a ") + f"{NOW.month:02d}/{NOW.day:02d}"
    return engine.GapSpec(
        role=role, department=req.department, shift=shift, shift_start=shift_start,
        shift_end=shift_end, shift_hours=12.0, day_label=day_label,
        required_certs=req.required_certs or [], person_out=req.person_out,
        person_out_id=_extract_emp_id(req.person_out))


def _extract_emp_id(text_in: str | None) -> str | None:
    import re
    if not text_in:
        return None
    m = re.search(r"HOSP-\d+", text_in, re.IGNORECASE)
    return m.group(0).upper() if m else None


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


def screen_gap(tenant_id: str, gap_id: str) -> engine.EligibilityReport:
    with Session(db_engine) as s:
        gap = _load_gap(s, tenant_id, gap_id)
        staff = s.exec(select(Staff).where(Staff.tenant_id == tenant_id)).all()
        last_contacted = {l.staff_id: l.sent_at for l in
                          s.exec(select(OutreachLog).where(OutreachLog.tenant_id == tenant_id)).all() if l.sent_at}
        likes = [staff_to_like(p, last_contacted.get(p.id)) for p in staff]
    spec = engine.GapSpec(role=gap.role, department=gap.department, shift=gap.shift,
                          shift_start=gap.shift_start, shift_end=gap.shift_end,
                          shift_hours=gap.shift_hours, day_label=gap.day_label,
                          required_certs=gap.required_certs, person_out=gap.person_out,
                          person_out_id=_extract_emp_id(gap.person_out))
    return engine.screen_candidates(likes, spec)


def gap_state(tenant_id: str, gap_id: str) -> dict:
    rep = screen_gap(tenant_id, gap_id)
    with Session(db_engine) as s:
        gap = _load_gap(s, tenant_id, gap_id)
        logs = s.exec(select(OutreachLog).where(OutreachLog.gap_id == gap_id)
                      .order_by(OutreachLog.seq)).all()
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
            "outreach": [{"id": l.id, "staff_id": l.staff_id, "seq": l.seq, "status": l.status,
                          "channel": l.channel, "message": l.message,
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
```

Note on `resolve_gap_spec` day_label: the seeded `shift_grid` keys come from the xlsx columns, which look like `"Sat 06/20"`. Build the "tonight" label to match that exact format: `NOW.strftime("%a ") + f"{NOW.month:02d}/{NOW.day:02d}"` → `"Sat 06/20"`. Replace the messy two-line block above with just that single assignment.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_shift.py::test_create_and_screen_felix_gap -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/shift.py tests/test_shift.py
git commit -m "P2: gap creation + screening service (structured + free-text)"
```

---

### Task 5: Outreach — Twilio(httpx)/simulated send + magic links

**Files:**
- Modify: `services/shift.py`
- Test: `tests/test_shift.py`

**Interfaces:**
- Consumes: `screen_gap`, `_load_gap`, models.
- Produces: `send_sms(to: str, body: str) -> dict` (real Twilio if creds, else `{"simulated": True, "sid": "SIMULATED", ...}`); `magic_link(token: str) -> str`; `start_outreach(tenant_id, gap_id) -> dict` (queues all eligible, sends seq 0); `escalate(tenant_id, gap_id) -> dict` (sends the next queued).

- [ ] **Step 1: Write the failing test** (no Twilio creds in test env → simulated send)

```python
def test_outreach_simulated_send_and_escalate():
    tenant = get_or_create_tenant("test-uks3", "Test UKS 3")
    shift_svc.seed_staff(tenant)
    gid = shift_svc.create_gap(tenant, structured=dict(
        role="Registered Nurse", department="ICU", shift="night", day_label="Sat 06/20",
        required_certs=["BLS", "ACLS"], person_out="Felix Haddad (HOSP-1059)"))
    out = shift_svc.start_outreach(tenant, gid)
    assert out["sent"]["seq"] == 0 and out["sent"]["simulated"] is True
    assert "token=" in out["sent"]["magic_link"]
    from sqlmodel import Session, select
    from core.models import OutreachLog
    with Session(engine) as s:
        logs = s.exec(select(OutreachLog).where(OutreachLog.gap_id == gid).order_by(OutreachLog.seq)).all()
        assert len(logs) >= 2
        assert logs[0].status == "sent" and logs[0].token and logs[1].status == "queued"
    esc = shift_svc.escalate(tenant, gid)
    assert esc["sent"]["seq"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_shift.py::test_outreach_simulated_send_and_escalate -v`
Expected: FAIL — `AttributeError: ... 'start_outreach'`.

- [ ] **Step 3: Add the outreach section to `services/shift.py`**

```python
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
    """Real Twilio SMS when creds are present; otherwise a logged simulated send."""
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
    first = (staff.name or "there").split()[0]
    ward = f"{gap.department} " if gap.department else ""
    window = (f"{gap.shift_start:%H:%M}-{gap.shift_end:%H:%M}" if gap.shift_start and gap.shift_end else gap.shift)
    return (f"Hi {first}, UKS staffing here. Urgent {ward}{gap.shift}-shift gap {gap.day_label} "
            f"({window}, 12h) — a colleague called in sick. You're qualified & off. "
            f"Tap to accept: {link}")


def _send_seq(s: Session, gap: ShiftGap, log_row: OutreachLog, staff: Staff) -> dict:
    link = magic_link(log_row.token)
    body = _draft_sms(gap, staff, link)
    res = send_sms(staff.phone or "", body)
    log_row.message = body
    log_row.status = "sent"
    log_row.sent_at = datetime.utcnow()
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
            return {"already": True, **gap_state(tenant_id, gap_id)}
        existing = s.exec(select(OutreachLog).where(OutreachLog.gap_id == gap_id)).all()
        if existing:
            return {"already": True, **gap_state(tenant_id, gap_id)}
        if not rep.eligible:
            return {"sent": None, "note": "no eligible candidates", **gap_state(tenant_id, gap_id)}
        # map engine employee_id -> Staff row
        by_emp = {p.employee_id: p for p in s.exec(select(Staff).where(Staff.tenant_id == tenant_id)).all()}
        rows: list[OutreachLog] = []
        for i, c in enumerate(rep.eligible):
            rows.append(OutreachLog(tenant_id=tenant_id, gap_id=gap_id, staff_id=by_emp[c.employee_id].id,
                                    channel="sms", status="queued", seq=i, token=secrets.token_urlsafe(16)))
        s.add_all(rows); s.commit()
        for r in rows:
            s.refresh(r)
        first, staff0 = rows[0], by_emp[rep.eligible[0].employee_id]
        sent = _send_seq(s, gap, first, staff0)
    return {"sent": sent, **gap_state(tenant_id, gap_id)}


def escalate(tenant_id: str, gap_id: str) -> dict:
    """Send to the next queued candidate (manual 'escalate now' / timer)."""
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_shift.py::test_outreach_simulated_send_and_escalate -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/shift.py tests/test_shift.py
git commit -m "P2: sequential SMS outreach (Twilio REST or simulated) + magic links + escalate"
```

---

### Task 6: Race-safe first-accept lock + decline

**Files:**
- Modify: `services/shift.py`
- Test: `tests/test_shift.py`

**Interfaces:**
- Consumes: models, `db_engine`.
- Produces: `accept(token: str) -> dict` (`{"result": "confirmed"|"already_filled"|"invalid", ...}`); `decline(token: str) -> dict`.

- [ ] **Step 1: Write the failing tests (including a true threaded race)**

```python
import threading


def _seed_gap_with_outreach(slug):
    tenant = get_or_create_tenant(slug, slug)
    shift_svc.seed_staff(tenant)
    gid = shift_svc.create_gap(tenant, structured=dict(
        role="Registered Nurse", department="ICU", shift="night", day_label="Sat 06/20",
        required_certs=["BLS", "ACLS"], person_out="Felix Haddad (HOSP-1059)"))
    shift_svc.start_outreach(tenant, gid)
    return tenant, gid


def _tokens(gid, n=2):
    from sqlmodel import Session, select
    from core.models import OutreachLog
    with Session(engine) as s:
        return [l.token for l in s.exec(select(OutreachLog).where(OutreachLog.gap_id == gid)
                                        .order_by(OutreachLog.seq)).all()][:n]


def test_first_accept_locks_gap_and_flips_schedule():
    tenant, gid = _seed_gap_with_outreach("race-uks1")
    t0, t1 = _tokens(gid, 2)
    r0 = shift_svc.accept(t0)
    assert r0["result"] == "confirmed"
    # a late reply from candidate #1 (e.g. after escalation) must NOT double-fill
    r1 = shift_svc.accept(t1)
    assert r1["result"] == "already_filled"
    state = shift_svc.gap_state(tenant, gid)
    assert state["gap"]["status"] == "filled" and state["filled_by"]
    # schedule flipped: the winner now shows the night shift on that day
    from sqlmodel import Session
    from core.models import Staff
    with Session(engine) as s:
        winner = s.get(Staff, state["filled_by"]["id"])
        assert winner.shift_grid.get("Sat 06/20") == "N"


def test_concurrent_accepts_exactly_one_winner():
    tenant, gid = _seed_gap_with_outreach("race-uks2")
    toks = _tokens(gid, 3)
    results, barrier = [], threading.Barrier(len(toks))
    def go(tok):
        barrier.wait()                       # maximize contention
        results.append(shift_svc.accept(tok)["result"])
    threads = [threading.Thread(target=go, args=(t,)) for t in toks]
    for t in threads: t.start()
    for t in threads: t.join()
    assert results.count("confirmed") == 1
    assert results.count("already_filled") == len(toks) - 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_shift.py -k "accept or concurrent" -v`
Expected: FAIL — `AttributeError: ... 'accept'`.

- [ ] **Step 3: Add the race-safe accept/decline to `services/shift.py`**

The lock is a single atomic SQL `UPDATE … WHERE id=:id AND status='open'`; the DB guarantees only one concurrent statement matches, so exactly one caller sees `rowcount == 1`.

```python
# --------------------------------------------------------------------------
# ACCEPT — race-safe first-accept lock (single atomic UPDATE, rowcount guard)
# --------------------------------------------------------------------------
def accept(token: str) -> dict:
    with Session(db_engine) as s:
        log_row = s.exec(select(OutreachLog).where(OutreachLog.token == token)).first()
        if not log_row:
            return {"result": "invalid", "detail": "unknown or expired link"}
        gap = s.get(ShiftGap, log_row.gap_id)
        if not gap:
            return {"result": "invalid", "detail": "gap missing"}

        # atomic claim: only the first caller flips open -> filled
        res = s.exec(text(
            "UPDATE shiftgap SET status='filled', version=version+1, "
            "filled_by_staff_id=:sid, filled_at=:now WHERE id=:gid AND status='open'"
        ), params={"sid": log_row.staff_id, "now": datetime.utcnow().isoformat(), "gid": gap.id})
        won = res.rowcount == 1
        s.commit()

        if not won:
            log_row.status = "closed"
            log_row.responded_at = datetime.utcnow()
            s.add(log_row); s.commit()
            s.refresh(gap)
            winner = s.get(Staff, gap.filled_by_staff_id) if gap.filled_by_staff_id else None
            return {"result": "already_filled", "gap_id": gap.id,
                    "filled_by": winner.name if winner else None}

        # we won: mark this log accepted, close the others, flip the schedule
        log_row.status = "accepted"
        log_row.responded_at = datetime.utcnow()
        s.add(log_row)
        for other in s.exec(select(OutreachLog).where(OutreachLog.gap_id == gap.id,
                            OutreachLog.id != log_row.id)).all():
            if other.status in ("queued", "sent"):
                other.status = "closed"
                s.add(other)
        staff = s.get(Staff, log_row.staff_id)
        if staff and gap.day_label:                      # schedule flip
            grid = dict(staff.shift_grid or {})
            grid[gap.day_label] = "N" if gap.shift == "night" else "D"
            staff.shift_grid = grid
            staff.scheduled_hours_next7 = (staff.scheduled_hours_next7 or 0) + (gap.shift_hours or 12)
            s.add(staff)
        s.commit()
        # confirmation SMS (real or simulated)
        if staff:
            send_sms(staff.phone or "", f"Thanks {staff.name.split()[0]}! You're confirmed for the "
                                        f"{gap.shift} shift {gap.day_label}. See you then. — UKS staffing")
        return {"result": "confirmed", "gap_id": gap.id,
                "staff_id": log_row.staff_id, "staff_name": staff.name if staff else None}


def decline(token: str) -> dict:
    with Session(db_engine) as s:
        log_row = s.exec(select(OutreachLog).where(OutreachLog.token == token)).first()
        if not log_row:
            return {"result": "invalid"}
        if log_row.status in ("queued", "sent"):
            log_row.status = "declined"
            log_row.responded_at = datetime.utcnow()
            s.add(log_row); s.commit()
        return {"result": "declined", "gap_id": log_row.gap_id}
```

- [ ] **Step 4: Run to verify the lock + race tests pass**

Run: `uv run pytest tests/test_shift.py -k "accept or concurrent" -v`
Expected: PASS (including the threaded race: exactly one "confirmed").

- [ ] **Step 5: Run the entire shift suite**

Run: `uv run pytest tests/test_shift.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add services/shift.py tests/test_shift.py
git commit -m "P2: race-safe first-accept lock (atomic UPDATE) + schedule flip + decline"
```

---

### Task 7: API routes + SSE + wire-up + .env.example

**Files:**
- Create: `api/routes/shift.py`
- Modify: `api/main.py` (one line), `.env.example`, `services/shift.py` (add the SSE event bus)
- Test: `tests/test_shift.py`

**Interfaces:**
- Consumes: `core.auth.{Principal, current_principal}`, all `services.shift` functions.
- Produces: `router` (prefix `/agents/shift`) with: `POST /seed`, `POST /gaps` (message|structured), `GET /gaps`, `GET /gaps/{id}` (state), `POST /gaps/{id}/outreach`, `POST /gaps/{id}/escalate`, `POST /accept` (token), `POST /decline` (token), `GET /gaps/{id}/events` (SSE). Plus `services.shift.{subscribe, unsubscribe, publish}`.

- [ ] **Step 1: Write the failing test (FastAPI TestClient, end-to-end happy path)**

```python
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_api_end_to_end_flow():
    assert client.post("/agents/shift/seed").json()["seeded"] == 100
    gap = client.post("/agents/shift/gaps", json={"structured": {
        "role": "Registered Nurse", "department": "ICU", "shift": "night",
        "day_label": "Sat 06/20", "required_certs": ["BLS", "ACLS"],
        "person_out": "Felix Haddad (HOSP-1059)"}}).json()
    gid = gap["gap"]["id"]
    assert gap["eligible"] and gap["excluded"]
    out = client.post(f"/agents/shift/gaps/{gid}/outreach").json()
    tok = out["sent"]["magic_link"].split("token=")[1]
    acc = client.post("/agents/shift/accept", json={"token": tok}).json()
    assert acc["result"] == "confirmed"
    state = client.get(f"/agents/shift/gaps/{gid}").json()
    assert state["gap"]["status"] == "filled"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_shift.py::test_api_end_to_end_flow -v`
Expected: FAIL — 404 (router not mounted yet).

- [ ] **Step 3: Add the SSE event bus to `services/shift.py`**

```python
# --------------------------------------------------------------------------
# SSE EVENT BUS — in-process pub/sub (single-worker dev/demo). Prod multi-worker
# would swap this for Redis pub/sub; documented as out-of-scope.
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
```

- [ ] **Step 4: Create `api/routes/shift.py`**

```python
"""P2 UKS — shift-replacement API (authenticated, tenant-scoped) + SSE live stream."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.auth import Principal, current_principal
from services import shift as svc

router = APIRouter(prefix="/agents/shift", tags=["uks-shift"])


@router.post("/seed")
def seed(principal: Principal = Depends(current_principal)) -> dict:
    return {"seeded": svc.seed_staff(principal.tenant_id)}


@router.post("/gaps")
async def create_gap(payload: dict = Body(...), principal: Principal = Depends(current_principal)) -> dict:
    message = payload.get("message")
    structured = payload.get("structured")
    if not message and not structured:
        raise HTTPException(422, "provide `message` or `structured`")
    try:
        gid = svc.create_gap(principal.tenant_id, message=message, structured=structured)
    except Exception as e:
        raise HTTPException(422, f"could not build gap: {e}")
    state = svc.gap_state(principal.tenant_id, gid)
    await svc.publish(gid, state)
    return state


@router.get("/gaps")
def list_gaps(principal: Principal = Depends(current_principal)) -> list[dict]:
    return svc.list_gaps(principal.tenant_id)


@router.get("/gaps/{gap_id}")
def gap_state(gap_id: str, principal: Principal = Depends(current_principal)) -> dict:
    try:
        return svc.gap_state(principal.tenant_id, gap_id)
    except LookupError:
        raise HTTPException(404, "gap not found")


@router.post("/gaps/{gap_id}/outreach")
async def start_outreach(gap_id: str, principal: Principal = Depends(current_principal)) -> dict:
    try:
        res = svc.start_outreach(principal.tenant_id, gap_id)
    except LookupError:
        raise HTTPException(404, "gap not found")
    await svc.publish(gap_id, svc.gap_state(principal.tenant_id, gap_id))
    return res


@router.post("/gaps/{gap_id}/escalate")
async def escalate(gap_id: str, principal: Principal = Depends(current_principal)) -> dict:
    try:
        res = svc.escalate(principal.tenant_id, gap_id)
    except LookupError:
        raise HTTPException(404, "gap not found")
    await svc.publish(gap_id, svc.gap_state(principal.tenant_id, gap_id))
    return res


@router.post("/accept")
async def accept(payload: dict = Body(...)) -> dict:
    """Public (no auth): reached from the SMS magic link. Tenant comes from the token."""
    token = payload.get("token")
    if not token:
        raise HTTPException(422, "token required")
    res = svc.accept(token)
    gid = res.get("gap_id")
    if gid:
        # publish the post-accept snapshot so the dashboard flips instantly
        from sqlmodel import Session
        from core.models import ShiftGap
        from core.db import engine as _eng
        with Session(_eng) as s:
            gap = s.get(ShiftGap, gid)
        if gap:
            await svc.publish(gid, svc.gap_state(gap.tenant_id, gid))
    return res


@router.post("/decline")
async def decline(payload: dict = Body(...)) -> dict:
    token = payload.get("token")
    if not token:
        raise HTTPException(422, "token required")
    res = svc.decline(token)
    gid = res.get("gap_id")
    if gid:
        from sqlmodel import Session
        from core.models import ShiftGap
        from core.db import engine as _eng
        with Session(_eng) as s:
            gap = s.get(ShiftGap, gid)
        if gap:
            await svc.publish(gid, svc.gap_state(gap.tenant_id, gid))
    return res


@router.get("/gaps/{gap_id}/events")
async def events(gap_id: str, request: Request, principal: Principal = Depends(current_principal)) -> StreamingResponse:
    """SSE stream of gap state. Emits the current snapshot immediately, then on every change."""
    async def gen():
        q = svc.subscribe(gap_id)
        try:
            snap = svc.gap_state(principal.tenant_id, gap_id)
            yield f"data: {json.dumps(snap)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    snap = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(snap)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"      # comment frame keeps the connection open
        finally:
            svc.unsubscribe(gap_id, q)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

- [ ] **Step 5: Wire the router in `api/main.py`**

Change the import line `from api.routes import secure_intake` → `from api.routes import secure_intake, shift` and add at the end (after the secure_intake include):

```python
app.include_router(shift.router)
```

- [ ] **Step 6: Add Twilio + base URL to `.env.example`** (append under a new section)

```bash
# ---- P2 UKS outreach (Twilio SMS; empty -> simulated send that still makes a magic link) ----
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM=                   # your Twilio number, e.g. +49...
PUBLIC_BASE_URL=http://localhost:3000   # base for the SMS accept magic-link
```

- [ ] **Step 7: Run the API test + the whole suite**

Run: `uv run pytest tests/test_shift.py -v && uv run pytest -q`
Expected: all PASS (P2 + the existing P10 secure-intake tests).

- [ ] **Step 8: Commit**

```bash
git add api/routes/shift.py api/main.py services/shift.py .env.example tests/test_shift.py
git commit -m "P2: shift API routes + SSE live stream; wire router; .env.example Twilio"
```

---

### Task 8: Web dashboard + accept page

**Files:**
- Create: `web/src/app/uks/api.ts`, `web/src/app/uks/page.tsx`, `web/src/app/uks/accept/page.tsx`
- Test: `cd web && npm run build` (type/lint gate) + manual end-to-end verify

**Interfaces:**
- Consumes: the API endpoints from Task 7; `@/components/ui` (Card/Button/Badge, read-only); `@/lib/supabase` (authHeaders pattern, read-only).
- Produces: `/uks` (live SSE dashboard) and `/uks/accept?token=…` (accept page).

> **Before writing any web code, read** `web/node_modules/next/dist/docs/01-app` relevant pages (this is a modified Next.js 16 — App Router, `src/app`, React 19 client components with `"use client"`). Mirror the patterns in `web/src/app/rheinmetall/page.tsx` (client component, fetch helpers, Card/Badge usage). EventSource is a browser API — use it inside a `useEffect` in a `"use client"` component.

- [ ] **Step 1: Create `web/src/app/uks/api.ts`** (fetch helpers + types, kept inside the uks subtree so no shared file is touched)

```typescript
import { supabase } from "@/lib/supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) return {};
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface Eligible {
  employee_id: string; name: string; role: string; department: string; phone: string;
  contract: string; scheduled_hours: number; max_hours: number; overtime_ok: boolean;
  rest_hours: number | null; headroom_hours: number; persona: string | null;
  score: number; why: string[];
}
export interface Excluded { employee_id: string; name: string; role: string; department: string; rule: string; reason: string; }
export interface Outreach { id: string; staff_id: string; seq: number; status: string; channel: string; message: string | null; sent_at: string | null; responded_at: string | null; }
export interface GapState {
  gap: { id: string; role: string; department: string; shift: string; day_label: string;
    required_certs: string[]; person_out: string | null; status: string; version: number;
    shift_start: string | null; shift_end: string | null; filled_at: string | null; };
  filled_by: { id: string; name: string; employee_id: string } | null;
  eligible: Eligible[]; excluded: Excluded[];
  counts: { total: number; active: number; eligible: number };
  outreach: Outreach[];
}

export const API_BASE = API;
export async function seed() { return (await fetch(`${API}/agents/shift/seed`, { method: "POST", headers: await authHeaders() })).json(); }
export async function createGap(body: object): Promise<GapState> {
  const r = await fetch(`${API}/agents/shift/gaps`, { method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`API ${r.status}: ${await r.text()}`);
  return r.json();
}
export async function startOutreach(id: string) {
  return (await fetch(`${API}/agents/shift/gaps/${id}/outreach`, { method: "POST", headers: await authHeaders() })).json();
}
export async function escalate(id: string) {
  return (await fetch(`${API}/agents/shift/gaps/${id}/escalate`, { method: "POST", headers: await authHeaders() })).json();
}
export async function acceptToken(token: string) {
  return (await fetch(`${API}/agents/shift/accept`, { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) })).json();
}
export async function gapState(id: string): Promise<GapState> {
  return (await fetch(`${API}/agents/shift/gaps/${id}`, { headers: await authHeaders() })).json();
}
```

- [ ] **Step 2: Create `web/src/app/uks/page.tsx`** (the live dashboard)

Render: the branded UKS header (red `#b3122b`, 🏥), a one-click "Load the tonight ICU scenario" that seeds + creates the Felix gap with the prefilled message, then a live board with three columns/sections — (a) ranked eligible candidates each with their `why` bullets + outreach status badge (queued/sent/accepted/declined/closed), (b) excluded candidates each with `rule` + `reason`, (c) the schedule cell for the gap day that flips to the shift code when filled. Subscribe to `GET /agents/shift/gaps/{id}/events` via `EventSource` in a `useEffect`; update state on each `data:` frame. Buttons: "Start outreach", "Escalate now" (also auto-escalates via a visible countdown timer that calls `escalate` once when it hits 0 if still open). Use `Card`/`Button`/`Badge` from `@/components/ui`. Default message prefilled: `"Felix Haddad (HOSP-1059) just called in sick for tonight's ICU night shift (Sat 06/20, 19:00-07:00). He's a Registered Nurse, ICU needs BLS + ACLS. Find me cover ASAP."` (Full component code: client component; `useState` for gapId/state/message/busy; `useEffect([gapId])` opening EventSource to `${API_BASE}/agents/shift/gaps/${gapId}/events` and `es.onmessage = e => setState(JSON.parse(e.data))`, cleanup `es.close()`.)

- [ ] **Step 3: Create `web/src/app/uks/accept/page.tsx`** (the magic-link target)

Client component: read `token` from `useSearchParams()`, show "Accept this shift?" with a confirm Button that calls `acceptToken(token)`, then render the result — `confirmed` → green "You're confirmed for the {shift} {day}"; `already_filled` → amber "This shift was just filled by {filled_by} — thank you anyway"; `invalid` → red "This link is no longer valid". (App-Router note: wrap `useSearchParams()` usage in a `<Suspense>` boundary per the bundled Next 16 docs.)

- [ ] **Step 4: Build/type-check the web app**

Run: `cd web && npm run build`
Expected: build succeeds (no type errors). Fix any types to match `web/src/app/uks/api.ts`.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/uks
git commit -m "P2: UKS live SSE dashboard + magic-link accept page"
```

---

### Task 9: End-to-end verification, STATE.md, PR

**Files:**
- Modify: `STATE.md`
- Verify: full test suite + a live manual drive

- [ ] **Step 1: Full offline test suite**

Run: `uv run pytest -q`
Expected: all PASS (P2 `tests/test_shift.py` + P10 `tests/test_secure_intake.py`). Capture the count.

- [ ] **Step 2: Live manual end-to-end (simulated send, no Twilio creds)**

In one shell: `LLM_PROVIDER=ollama AUTH_MODE=dev uv run uvicorn api.main:app --port 8000`. In another: `cd web && npm run dev`. In the browser open `http://localhost:3000/uks` → "Load tonight's ICU scenario" → see ranked eligible (with why) + excluded (with reasons) → "Start outreach" → the API log prints `SIMULATED SMS to … : … token=…` → copy the magic link → open `http://localhost:3000/uks/accept?token=…` → Confirm → return to `/uks` and confirm the board flipped to **filled** and the winner's schedule cell shows **N**, live (no refresh). Confirm a second open of a different candidate's link shows "already filled".

- [ ] **Step 3: Update `STATE.md`** — in "Where we are", change the Phase 1 line to record P2 as done and fill the run commands:

```markdown
- 🟡 **Phase 1 — flagships** (parallel git worktrees): **P2 UKS DONE** (feat/uks) — deterministic
  ArbZG eligibility engine (§5 rest + §3 weekly cap, with per-candidate why-eligible / why-excluded),
  free-text + structured gap intake, sequential Twilio-or-simulated SMS outreach with magic-link accept,
  race-safe first-accept lock (atomic UPDATE), live SSE dashboard + accept page. Run: API
  `LLM_PROVIDER=ollama AUTH_MODE=dev uv run uvicorn api.main:app --port 8000`, web `cd web && npm run dev`,
  open `/uks`. Tests: `uv run pytest tests/test_shift.py`. P4 Persowerk still ⬜.
```

- [ ] **Step 4: Commit + push + open PR**

```bash
git add STATE.md && git commit -m "STATE.md: Phase 1 — P2 UKS shift replacement done"
git push -u origin feat/uks
gh pr create --base main --head feat/uks --title "P2 UKS — shift-replacement action agent" \
  --body "$(cat <<'EOF'
## P2 UKS — Shift-Replacement Action Agent

Built on the Phase 0 foundation (core/agent · core/db · core/auth · shift models), end-to-end:

- **Eligibility engine** (pure, deterministic, `agents/shift.py`): qualification (RN-family), not-already-on-shift, **ArbZG §5** ≥11h rest, **ArbZG §3** weekly-hours cap, Active — every eligible carries a *why*, every excluded carries the *rule + reason*. Fairness ranking (headroom, last-contacted, overtime, contract, ward, preference).
- **Trigger:** free-text gap message (`core.llm`) or structured form → `GapSpec`.
- **Outreach:** sequential SMS via real Twilio REST (httpx) when creds are set, else a logged simulated send; each carries a magic-link. Manual "escalate now" + a dashboard timer advance to the next candidate.
- **Accept:** magic link → `/uks/accept` → first-accept **transactionally locks** the gap (single atomic `UPDATE … WHERE status='open'`, rowcount guard) so a late reply after escalation can't double-fill; losers get "already filled". Schedule flips on accept.
- **Dashboard:** `web/src/app/uks` — live SSE board (ranked eligible + why, excluded + reason, per-candidate outreach status, schedule flip on accept).

### Tests (offline, free — ollama + simulated Twilio + throwaway SQLite)
Compliance exclusions (rest §5 / qualification / certs / weekly cap §3 / on-leave / already-on-shift), fairness ranking, the **first-accept lock race** (threaded — exactly one winner), and the API happy path. `uv run pytest tests/test_shift.py`.

### Notes
- No new pip deps (Twilio via REST/httpx; SSE via StreamingResponse).
- Web pages live at `web/src/app/uks/**` (repo uses the `src/` App Router layout).
- One shared edit: `app.include_router(shift.router)` in `api/main.py`. Also added Twilio/PUBLIC_BASE_URL to `.env.example` and the Phase-1 status to `STATE.md` (per task brief).
- Out of scope: voice/Vapi, real WhatsApp Business API, multi-worker SSE (would need Redis pub/sub).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- Eligibility engine (qualified + not-on-shift + §5 rest + §3 cap + active, with per-candidate include/exclude reasons + fairness ranking) → Task 2. Seeding from the xlsx → Task 3. ✅
- Trigger (free-text via LLM + structured) → Task 4. ✅
- Outreach (sequential SMS only, Twilio real + simulated fallback, escalate timer + manual) → Task 5. ✅
- Accept (magic link → accept page → transactional first-accept lock with status/version guard; losers "already filled"; OutreachLog + schedule persisted; confirmation) → Task 6 (service) + Task 7 (route) + Task 8 (page). ✅
- Dashboard (SSE live: gap, ranked candidates with why-eligible/why-excluded, per-candidate outreach status, schedule flips on accept) → Task 7 (SSE) + Task 8 (UI). ✅
- Tests offline on ollama + no real Twilio, covering compliance exclusions, ranking, first-accept race → Tasks 2,5,6. ✅
- Alembic migration for added columns → Task 1. ✅ `.env.example` TWILIO_*+PUBLIC_BASE_URL → Task 7. ✅ STATE.md + commits-in-chunks + PR → all tasks commit; Task 9 PR. ✅
- Out of scope (voice/Vapi, WhatsApp) honored. ✅

**Placeholder scan:** `resolve_gap_spec`'s day-label normalization had a messy two-line draft — Task 4 Step 3's trailing note replaces it with the single canonical assignment `NOW.strftime("%a ") + f"{NOW.month:02d}/{NOW.day:02d}"`. Apply that during execution. No other TODO/TBD placeholders.

**Type consistency:** `screen_candidates(staff: list[StaffLike], gap: GapSpec) -> EligibilityReport` is used identically in agents tests, `find_replacements`, and `screen_gap`. `ScoredCandidate`/`ExcludedCandidate` field names match the web `Eligible`/`Excluded` interfaces (Task 8). `accept`/`decline` return `{"result", "gap_id", ...}` consumed consistently by Task 7 routes and Task 8 accept page. OutreachLog status vocabulary (queued|sent|accepted|declined|closed) is consistent across Tasks 5–8. The atomic UPDATE column names match the Task 1 model (`status`, `version`, `filled_by_staff_id`, `filled_at`).
