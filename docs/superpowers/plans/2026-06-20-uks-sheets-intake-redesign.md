# UKS Sheets round-trip + SMS intake mock + ops-console redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the shipped P2 UKS agent feel like a real product: a Google-Sheets-or-xlsx schedule round-trip when a shift is filled, a believable SMS/WhatsApp intake mock, and a UKS-branded clinical ops-console redesign.

**Architecture:** A pluggable `RosterSink` (`services/roster_sink.py`) abstracts "where the roster update lands" — `GoogleSheetsSink` (gspread, live cell-flip) when service-account creds are set, else `XlsxSink` (openpyxl, writes `data/hospital_schedule_updated.xlsx`). `services/shift.py` calls it best-effort from `seed`/`accept` and surfaces the result in `gap_state.roster_sync`; `gap_state` also gains a bounded `schedule_preview`. The web `/uks` page is rebuilt as a two-column ops console with a phone-mock intake and a live schedule grid.

**Tech Stack:** Python 3.12, SQLModel, openpyxl (present), **gspread + google-auth** (gspread to be added; google-auth already present), pytest; Next.js 16 App Router (`src/app`) + React 19 + Tailwind v4 + TypeScript.

## Global Constraints

- **Own only:** new `services/roster_sink.py`; modify `services/shift.py`, `web/src/app/uks/**` (incl. new `web/src/app/uks/components/*`, `web/src/app/uks/api.ts`), `tests/test_shift.py` (+ new `tests/test_roster_sink.py`). Authorized shared edits: `.env.example` (Google vars), `pyproject.toml` (add `gspread` only). Touch nothing else.
- **No regressions:** the 14 shipped P2 tests + 3 P10 tests stay green. The eligibility engine, race-safe lock, and outreach logic are NOT changed.
- **Tests stay offline/free:** XlsxSink to a temp path, sink-selection via monkeypatched env (no network), accept-never-crashes-on-sink-error. Google live path + the web visuals are manual checks.
- **Best-effort sinks:** a sink error must never fail a fill or a seed — log + continue.
- **Brand:** UKS deep-red `#b3122b`. Reuse `@/components/ui` read-only; add new presentational components locally under `web/src/app/uks/components/`.
- **Demo clock / scenario** unchanged: Sat 2026-06-20, ICU night gap, day columns like `"Sat 06/20"`.

## File Structure

- `services/roster_sink.py` — NEW. `SyncResult`, `RosterSink` protocol, `XlsxSink`, `GoogleSheetsSink`, `get_sink()`.
- `services/shift.py` — call the sink in `seed_staff`/`accept`; add `roster_sync` + `schedule_preview` to `gap_state`.
- `tests/test_roster_sink.py` — NEW. Offline sink tests.
- `tests/test_shift.py` — add: accept-never-crashes-on-sink-error, gap_state has roster_sync + schedule_preview.
- `web/src/app/uks/api.ts` — extend `GapState` with `roster_sync` + `schedule_preview`.
- `web/src/app/uks/components/{IntakePhone,ScheduleGrid,StatusPill,CandidateRow}.tsx` — NEW presentational pieces.
- `web/src/app/uks/page.tsx` — rebuilt ops-console layout using the components.
- `web/src/app/uks/accept/page.tsx` — restyled to match.
- `.env.example`, `pyproject.toml` — additive.

---

### Task 1: `RosterSink` interface + `XlsxSink` + factory

**Files:**
- Create: `services/roster_sink.py`
- Test: `tests/test_roster_sink.py`

**Interfaces:**
- Produces: `SyncResult(target: str, ok: bool, link: str|None, detail: str|None=None)` (dataclass); `XlsxSink(out_path: Path|str|None=None, source_path: Path|str|None=None)` with `.push_roster(rows: list[dict], day_cols: list[str]) -> SyncResult` and `.record_fill(*, employee_id, name, day_label, code, when: datetime) -> SyncResult`; `get_sink() -> RosterSink`.
- Rows passed to `push_roster` look like `{"employee_id","name","role","department", <day_col>: code, ...}`.

- [ ] **Step 1: Write the failing test** (`tests/test_roster_sink.py`)

```python
"""RosterSink tests — fully offline (xlsx write-back; no Google creds)."""
import os
from datetime import datetime

import openpyxl

from services.roster_sink import SyncResult, XlsxSink, get_sink


def _rows():
    return [
        {"employee_id": "HOSP-1059", "name": "Felix Haddad", "role": "Registered Nurse",
         "department": "ICU", "Fri 06/19": "O", "Sat 06/20": "O"},
        {"employee_id": "HOSP-2007", "name": "Anya Lindgren", "role": "Registered Nurse",
         "department": "ICU", "Fri 06/19": "O", "Sat 06/20": "O"},
    ]


def test_xlsx_sink_push_then_record_fill(tmp_path):
    out = tmp_path / "updated.xlsx"
    sink = XlsxSink(out_path=out)
    r = sink.push_roster(_rows(), ["Fri 06/19", "Sat 06/20"])
    assert r.ok and r.target == "xlsx" and out.exists()
    res = sink.record_fill(employee_id="HOSP-2007", name="Anya Lindgren",
                           day_label="Sat 06/20", code="N", when=datetime(2026, 6, 20, 18, 45))
    assert res.ok and res.target == "xlsx"
    wb = openpyxl.load_workbook(out)
    ws = wb["Roster"]
    # find Anya's row, assert Sat 06/20 cell flipped to N
    header = [c.value for c in ws[1]]
    sat = header.index("Sat 06/20")
    anya = next(row for row in ws.iter_rows(min_row=2, values_only=True) if row[0] == "HOSP-2007")
    assert anya[sat] == "N"
    assert "Updates" in wb.sheetnames
    updates = list(wb["Updates"].iter_rows(min_row=2, values_only=True))
    assert any(u[0] == "HOSP-2007" and u[2] == "Sat 06/20" and u[3] == "N" for u in updates)


def test_get_sink_defaults_to_xlsx_without_creds(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEETS_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_CREDENTIALS_JSON", raising=False)
    assert isinstance(get_sink(), XlsxSink)
    assert isinstance(SyncResult("xlsx", True, None), SyncResult)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks && uv run pytest tests/test_roster_sink.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.roster_sink'`.

- [ ] **Step 3: Create `services/roster_sink.py` (XlsxSink + factory; Google stub added in Task 3)**

```python
"""Pluggable roster sink: where a shift-fill lands in the 'real world'.

XlsxSink (default, zero-creds) writes data/hospital_schedule_updated.xlsx with the flipped
cell highlighted + an Updates audit sheet. GoogleSheetsSink (Task 3) flips the same cell in
a live Google Sheet when GOOGLE_SHEETS_ID + a service-account key are configured. Both are
best-effort: callers wrap them so a sync failure never breaks a fill."""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import openpyxl
from openpyxl.styles import PatternFill

from core import config

log = logging.getLogger("roster_sink")
_GREEN = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")


@dataclass
class SyncResult:
    target: str            # "google_sheets" | "xlsx" | "none"
    ok: bool
    link: str | None
    detail: str | None = None


class RosterSink(Protocol):
    def push_roster(self, rows: list[dict], day_cols: list[str]) -> SyncResult: ...
    def record_fill(self, *, employee_id: str, name: str, day_label: str,
                    code: str, when: datetime) -> SyncResult: ...


class XlsxSink:
    """Writes an updated .xlsx the customer can open in Excel / drag into Sheets."""

    def __init__(self, out_path: Path | str | None = None, source_path: Path | str | None = None):
        self.out_path = Path(out_path) if out_path else config.DATA_OUT / "hospital_schedule_updated.xlsx"
        self.source_path = Path(source_path) if source_path else config.PATHS["schedule"]

    def push_roster(self, rows: list[dict], day_cols: list[str]) -> SyncResult:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Roster"
        header = ["employee_id", "name", "role", "department", *day_cols]
        ws.append(header)
        for r in rows:
            ws.append([r.get("employee_id"), r.get("name"), r.get("role"),
                       r.get("department"), *[r.get(c, "") for c in day_cols]])
        up = wb.create_sheet("Updates")
        up.append(["employee_id", "name", "day", "code", "when"])
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(self.out_path)
        return SyncResult("xlsx", True, str(self.out_path))

    def record_fill(self, *, employee_id: str, name: str, day_label: str,
                    code: str, when: datetime) -> SyncResult:
        if not self.out_path.exists():
            # no roster pushed yet — seed a minimal sheet so the fill is recordable
            self.push_roster([{"employee_id": employee_id, "name": name, day_label: "O"}], [day_label])
        wb = openpyxl.load_workbook(self.out_path)
        ws = wb["Roster"]
        header = [c.value for c in ws[1]]
        if day_label not in header:
            ws.cell(row=1, column=len(header) + 1, value=day_label)
            header.append(day_label)
        col = header.index(day_label) + 1
        for row in ws.iter_rows(min_row=2):
            if row[0].value == employee_id:
                cell = ws.cell(row=row[0].row, column=col, value=code)
                cell.fill = _GREEN
                break
        up = wb["Updates"] if "Updates" in wb.sheetnames else wb.create_sheet("Updates")
        up.append([employee_id, name, day_label, code, when.isoformat(timespec="minutes")])
        wb.save(self.out_path)
        return SyncResult("xlsx", True, str(self.out_path))


def get_sink() -> RosterSink:
    """GoogleSheetsSink when creds are configured, else XlsxSink."""
    if os.getenv("GOOGLE_SHEETS_ID") and os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON"):
        try:
            from services.roster_sink_google import GoogleSheetsSink  # added in Task 3
            return GoogleSheetsSink()
        except Exception as e:                       # missing dep / bad creds -> fall back
            log.warning("GoogleSheetsSink unavailable (%s); using xlsx", e)
    return XlsxSink()
```

> Note: Task 3 will introduce `GoogleSheetsSink`. To keep imports clean and the default path dependency-free, it lives in a sibling module `services/roster_sink_google.py`, imported lazily inside `get_sink()`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks && uv run pytest tests/test_roster_sink.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add services/roster_sink.py tests/test_roster_sink.py
git commit -m "P2: RosterSink interface + XlsxSink write-back + factory"
```

---

### Task 2: Wire the sink into `seed`/`accept`/`gap_state`

**Files:**
- Modify: `services/shift.py`
- Test: `tests/test_shift.py`

**Interfaces:**
- Consumes: `services.roster_sink.get_sink`, `SyncResult`.
- Produces: `seed_staff` pushes the roster best-effort; `accept` records the fill best-effort and never raises on sink error; `gap_state` returns `"roster_sync": {"target","ok","link"}|None`.
- Internal: module-level `_last_sync: dict[gap_id, dict]`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_shift.py`)

```python
def test_accept_survives_sink_error_and_reports_sync(monkeypatch):
    import services.shift as svc
    import services.roster_sink as rs

    class BoomSink:
        def push_roster(self, *a, **k):
            raise RuntimeError("sheets down")
        def record_fill(self, **k):
            raise RuntimeError("sheets down")

    monkeypatch.setattr(rs, "get_sink", lambda: BoomSink())
    tenant, gid = _seed_gap_with_outreach("sink-boom")
    tok = _tokens(gid, 1)[0]
    assert svc.accept(tok)["result"] == "confirmed"     # a sink crash must NOT break the fill
    state = svc.gap_state(tenant, gid)
    assert state["gap"]["status"] == "filled"
    assert "roster_sync" in state                       # key always present


def test_gap_state_reports_xlsx_sync_after_fill(tmp_path, monkeypatch):
    import services.shift as svc
    import services.roster_sink as rs
    monkeypatch.setattr(rs, "get_sink", lambda: rs.XlsxSink(out_path=tmp_path / "u.xlsx"))
    tenant, gid = _seed_gap_with_outreach("sink-xlsx")
    tok = _tokens(gid, 1)[0]
    svc.accept(tok)
    sync = svc.gap_state(tenant, gid)["roster_sync"]
    assert sync and sync["target"] == "xlsx" and sync["ok"] is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks && uv run pytest tests/test_shift.py -k "sink" -v`
Expected: FAIL — `KeyError: 'roster_sync'` (and/or the BoomSink isn't called yet).

- [ ] **Step 3: Wire the sink in `services/shift.py`**

Add the import near the top (after `from core.models import ...`):

```python
from services import roster_sink
```

Add a module-level cache near `_subscribers` (or after `_now`):

```python
_last_sync: dict[str, dict] = {}   # gap_id -> SyncResult-as-dict (for gap_state.roster_sync)
```

In `seed_staff`, after `s.commit()` and before the `log.info(...)`/`return n`, push the roster best-effort:

```python
    try:
        day_cols2 = day_cols
        push_rows = [{"employee_id": str(r["Employee ID"]),
                      "name": f"{str(r.get('First Name','')).strip()} {str(r.get('Last Name','')).strip()}".strip(),
                      "role": str(r["Role"]), "department": str(r["Department"]),
                      **{c: str(grid_by_id.get(str(r["Employee ID"]), {}).get(c, "")) for c in day_cols2}}
                     for _, r in roster.iterrows()]
        roster_sink.get_sink().push_roster(push_rows, day_cols2)
    except Exception as e:                       # best-effort; never block seeding
        log.warning("roster push failed: %s", e)
```

In `accept`, in the winning branch, AFTER the `# confirmation SMS` block computes `staff_name`/`gap_day`, record the fill best-effort. Replace the confirmation tail so it also syncs and stores the result:

```python
    # confirmation SMS (real or simulated), outside the txn
    if staff_name:
        send_sms(staff_phone or "", f"Thanks {staff_name.split()[0]}! You're confirmed for the "
                                    f"{gap_shift} shift {gap_day}. See you then. — UKS staffing")
    # roster round-trip (Google Sheets or xlsx) — best-effort, never breaks the fill
    sync = {"target": "none", "ok": False, "link": None}
    if staff_name:
        try:
            code = "N" if gap_shift == "night" else "D"
            res = roster_sink.get_sink().record_fill(
                employee_id=emp_id_val, name=staff_name, day_label=gap_day, code=code, when=_now())
            sync = {"target": res.target, "ok": res.ok, "link": res.link}
        except Exception as e:
            log.warning("roster sync failed: %s", e)
    _last_sync[gap_id_val] = sync
    return {"result": "confirmed", "gap_id": gap_id_val,
            "staff_id": staff_id_val, "staff_name": staff_name, "roster_sync": sync}
```

This needs the winner's external employee_id. In the winning branch where `staff` is loaded, capture it alongside the other values — change the capture line:

```python
        gap_shift, gap_day, gap_id_val, staff_id_val = gap.shift, gap.day_label, gap.id, log_row.staff_id
        emp_id_val = staff.employee_id if staff else None
```

In `gap_state`, add `roster_sync` to the returned dict (right after `"filled_by": filled_by,`):

```python
            "roster_sync": _last_sync.get(gap_id) if gap.status == "filled" else None,
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks && uv run pytest tests/test_shift.py -k "sink" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Full P2 suite stays green**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks && uv run pytest tests/test_shift.py -q`
Expected: all PASS (16 now).

- [ ] **Step 6: Commit**

```bash
git add services/shift.py tests/test_shift.py
git commit -m "P2: wire RosterSink into seed/accept + expose roster_sync in gap_state"
```

---

### Task 3: `GoogleSheetsSink` (gspread) + env + selection

**Files:**
- Create: `services/roster_sink_google.py`
- Modify: `pyproject.toml` (add `gspread`), `.env.example`
- Test: `tests/test_roster_sink.py`

**Interfaces:**
- Produces: `GoogleSheetsSink(sheet_id=None, creds_path=None, worksheet=None)` implementing `push_roster` + `record_fill`, returning `SyncResult(target="google_sheets", ...)` with `link` = the spreadsheet URL.

- [ ] **Step 1: Add the dependency**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks && uv add gspread`
Expected: `pyproject.toml` gains `gspread>=…`; `uv.lock` updates; install succeeds.

- [ ] **Step 2: Write the failing test** (append to `tests/test_roster_sink.py`)

```python
def test_get_sink_selects_google_when_env_set(monkeypatch, tmp_path):
    # a dummy creds file so construction doesn't need a real key; no network is hit (we
    # monkeypatch the gspread client factory)
    creds = tmp_path / "svc.json"
    creds.write_text("{}")
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "sheet123")
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_JSON", str(creds))
    import services.roster_sink_google as g
    monkeypatch.setattr(g, "_open_spreadsheet", lambda sid, creds_path: object())  # no network
    from services.roster_sink import get_sink
    sink = get_sink()
    assert type(sink).__name__ == "GoogleSheetsSink"


def test_google_sink_import_is_safe_without_creds():
    # importing the module must never require creds or network
    import services.roster_sink_google as g
    assert hasattr(g, "GoogleSheetsSink")
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks && uv run pytest tests/test_roster_sink.py -k "google" -v`
Expected: FAIL — `ModuleNotFoundError: services.roster_sink_google`.

- [ ] **Step 4: Create `services/roster_sink_google.py`**

```python
"""GoogleSheetsSink — flips the roster cell in a live Google Sheet via gspread.

Lazy: gspread is imported inside the client factory so this module imports cleanly even if
gspread isn't installed. Auth is service-account only (GOOGLE_SHEETS_CREDENTIALS_JSON)."""
from __future__ import annotations

import logging
import os
from datetime import datetime

from services.roster_sink import SyncResult

log = logging.getLogger("roster_sink")


def _open_spreadsheet(sheet_id: str, creds_path: str):
    import gspread  # imported lazily; only needed when Google sync is active
    gc = gspread.service_account(filename=creds_path)
    return gc.open_by_key(sheet_id)


class GoogleSheetsSink:
    def __init__(self, sheet_id: str | None = None, creds_path: str | None = None,
                 worksheet: str | None = None):
        self.sheet_id = sheet_id or os.environ["GOOGLE_SHEETS_ID"]
        self.creds_path = creds_path or os.environ["GOOGLE_SHEETS_CREDENTIALS_JSON"]
        self.worksheet = worksheet or os.getenv("GOOGLE_SHEETS_WORKSHEET", "Roster")

    def _ws(self):
        ss = _open_spreadsheet(self.sheet_id, self.creds_path)
        try:
            return ss, ss.worksheet(self.worksheet)
        except Exception:
            return ss, ss.add_worksheet(self.worksheet, rows=200, cols=20)

    def push_roster(self, rows: list[dict], day_cols: list[str]) -> SyncResult:
        ss, ws = self._ws()
        header = ["employee_id", "name", "role", "department", *day_cols]
        data = [header] + [[r.get("employee_id"), r.get("name"), r.get("role"),
                            r.get("department"), *[r.get(c, "") for c in day_cols]] for r in rows]
        ws.clear()
        ws.update(data, "A1")
        return SyncResult("google_sheets", True, ss.url)

    def record_fill(self, *, employee_id: str, name: str, day_label: str,
                    code: str, when: datetime) -> SyncResult:
        ss, ws = self._ws()
        header = ws.row_values(1)
        if day_label not in header:
            return SyncResult("google_sheets", False, ss.url, f"column '{day_label}' not in sheet")
        col = header.index(day_label) + 1
        cell = ws.find(employee_id, in_column=1)
        if not cell:
            return SyncResult("google_sheets", False, ss.url, f"{employee_id} not found")
        ws.update_cell(cell.row, col, code)
        return SyncResult("google_sheets", True, ss.url)
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks && uv run pytest tests/test_roster_sink.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Add the env vars to `.env.example`** (append under the P2 UKS section)

```bash
# ---- P2 UKS roster sync (Google Sheets; empty -> writes data/hospital_schedule_updated.xlsx) ----
GOOGLE_SHEETS_ID=                       # target spreadsheet id (share it with the service account)
GOOGLE_SHEETS_CREDENTIALS_JSON=         # path to a Google service-account key json
GOOGLE_SHEETS_WORKSHEET=Roster          # worksheet/tab name (optional)
```

- [ ] **Step 7: Commit**

```bash
git add services/roster_sink_google.py tests/test_roster_sink.py pyproject.toml uv.lock .env.example
git commit -m "P2: GoogleSheetsSink (gspread) behind the sink interface + env + selection"
```

---

### Task 4: `schedule_preview` in `gap_state`

**Files:**
- Modify: `services/shift.py`
- Test: `tests/test_shift.py`

**Interfaces:**
- Produces: `gap_state(...)["schedule_preview"] = {"days": [...], "gap_day": str, "rows": [{"employee_id","name","role","is_winner": bool, "grid": {day: code}}]}`. Bounded to the eligible candidates + the filled winner (deduped).

- [ ] **Step 1: Write the failing test** (append to `tests/test_shift.py`)

```python
def test_gap_state_has_bounded_schedule_preview():
    tenant = get_or_create_tenant("sched-preview", "Sched Preview")
    shift_svc.seed_staff(tenant)
    gid = shift_svc.create_gap(tenant, structured=dict(_FELIX))
    sp = shift_svc.gap_state(tenant, gid)["schedule_preview"]
    assert sp["gap_day"] == "Sat 06/20"
    assert "Sat 06/20" in sp["days"]
    assert 1 <= len(sp["rows"]) <= 40            # bounded, not all 100 staff
    assert all("Sat 06/20" in row["grid"] for row in sp["rows"])


def test_schedule_preview_marks_winner_after_fill():
    tenant, gid = _seed_gap_with_outreach("sched-winner")
    tok = _tokens(gid, 1)[0]
    shift_svc.accept(tok)
    sp = shift_svc.gap_state(tenant, gid)["schedule_preview"]
    winners = [r for r in sp["rows"] if r["is_winner"]]
    assert len(winners) == 1
    assert winners[0]["grid"]["Sat 06/20"] == "N"   # the flipped cell shows in the preview
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks && uv run pytest tests/test_shift.py -k "schedule_preview or preview_marks" -v`
Expected: FAIL — `KeyError: 'schedule_preview'`.

- [ ] **Step 3: Build `schedule_preview` in `gap_state`**

In `gap_state`, the `with Session(...)` block already loads `gap`, `logs`, `staff_rows`. Build the preview from the eligible set (from `rep`, already computed at the top of `gap_state` via `screen_gap`) + the winner. Add, inside the `with` block, before the `return {`:

```python
        elig_emp = [c.employee_id for c in rep.eligible]
        winner_emp = filled_by["employee_id"] if filled_by else None
        keep_emp = list(dict.fromkeys([*elig_emp, *( [winner_emp] if winner_emp else [] )]))
        by_emp_row = {p.employee_id: p for p in staff_rows}
        # day columns: take the (ordered) grid keys from any staff row
        any_grid = next((dict(p.shift_grid or {}) for p in staff_rows if p.shift_grid), {})
        days = list(any_grid.keys())
        preview_rows = []
        for emp in keep_emp[:40]:
            p = by_emp_row.get(emp)
            if not p:
                continue
            preview_rows.append({"employee_id": emp, "name": p.name, "role": p.role,
                                 "is_winner": emp == winner_emp, "grid": dict(p.shift_grid or {})})
        schedule_preview = {"days": days, "gap_day": gap.day_label, "rows": preview_rows}
```

Add to the returned dict (after `"roster_sync": ...`):

```python
            "schedule_preview": schedule_preview,
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks && uv run pytest tests/test_shift.py -k "schedule_preview or preview_marks" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Full suite green**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks && uv run pytest -q`
Expected: all PASS (P2 + P10 + roster_sink).

- [ ] **Step 6: Commit**

```bash
git add services/shift.py tests/test_shift.py
git commit -m "P2: bounded schedule_preview in gap_state (feeds the live grid)"
```

---

### Task 5: Web — extend types + intake phone mock + ops-console redesign

**Files:**
- Modify: `web/src/app/uks/api.ts`
- Create: `web/src/app/uks/components/StatusPill.tsx`, `CandidateRow.tsx`, `ScheduleGrid.tsx`, `IntakePhone.tsx`
- Modify: `web/src/app/uks/page.tsx`
- Test: `cd web && npm run build`

**Interfaces:**
- Consumes: `GapState` (now with `roster_sync`, `schedule_preview`), `createGap`, `startOutreach`, `escalate`, `seed`, `API_BASE`.
- `ScheduleGrid` props: `{ preview: GapState["schedule_preview"] }`. `IntakePhone` props: `{ onSubmit: (body:{message?:string;structured?:object})=>void; busy: boolean; parsed: GapState["gap"] | null }`. `StatusPill` props: `{ status: string }`. `CandidateRow` props: `{ c: Eligible; rank: number; outreach?: Outreach }`.

> Read `web/node_modules/next/dist/docs/01-app` for the App Router / client-component conventions (this is a modified Next.js 16). Mirror existing patterns; all four components are `"use client"`-free pure presentational components except where they hold no state (they receive props). The page stays the only stateful client component.

- [ ] **Step 1: Extend `web/src/app/uks/api.ts` types**

Add to the `GapState` interface:

```typescript
  roster_sync: { target: string; ok: boolean; link: string | null } | null;
  schedule_preview: {
    days: string[];
    gap_day: string;
    rows: { employee_id: string; name: string; role: string; is_winner: boolean; grid: Record<string, string> }[];
  };
```

- [ ] **Step 2: Create the presentational components**

`web/src/app/uks/components/StatusPill.tsx` — maps a status string to a colored pill:

```tsx
const TONE: Record<string, string> = {
  queued: "bg-slate-100 text-slate-700",
  sent: "bg-amber-100 text-amber-800",
  accepted: "bg-green-100 text-green-800",
  declined: "bg-red-100 text-red-800",
  closed: "bg-slate-100 text-slate-500",
  open: "bg-amber-100 text-amber-800",
  filled: "bg-green-100 text-green-800",
};
export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${TONE[status] ?? "bg-slate-100 text-slate-700"}`}>
      {status}
    </span>
  );
}
```

`web/src/app/uks/components/ScheduleGrid.tsx` — renders the bounded weekly grid, highlighting the gap day + the winner:

```tsx
import type { GapState } from "../api";

export function ScheduleGrid({ preview }: { preview: GapState["schedule_preview"] }) {
  if (!preview?.rows?.length) return <p className="text-sm text-slate-400">No schedule yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="text-slate-500">
            <th className="px-2 py-1 text-left font-medium">Staff</th>
            {preview.days.map((d) => (
              <th key={d} className={`px-2 py-1 font-medium ${d === preview.gap_day ? "text-[#b3122b]" : ""}`}>
                {d.replace(/^\w+ /, "")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((r) => (
            <tr key={r.employee_id} className={r.is_winner ? "bg-green-50" : ""}>
              <td className="whitespace-nowrap px-2 py-1 font-medium">
                {r.is_winner ? "✅ " : ""}{r.name}
              </td>
              {preview.days.map((d) => {
                const code = r.grid[d] ?? "";
                const isGap = d === preview.gap_day;
                const flipped = r.is_winner && isGap;
                return (
                  <td
                    key={d}
                    className={`px-2 py-1 text-center ${
                      flipped ? "rounded bg-green-200 font-bold text-green-900"
                      : isGap ? "bg-amber-50"
                      : code === "O" ? "text-slate-300" : "text-slate-600"
                    }`}
                  >
                    {code}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

`web/src/app/uks/components/CandidateRow.tsx` — extract the ranked candidate card from the current page (richer styling):

```tsx
import type { Eligible, Outreach } from "../api";
import { StatusPill } from "./StatusPill";

export function CandidateRow({ c, rank, outreach }: { c: Eligible; rank: number; outreach?: Outreach }) {
  return (
    <div className={`rounded-lg border p-3 ${rank === 1 ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-white"}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold">
          {rank === 1 ? "🥇 " : `${rank}. `}{c.name}
          <span className="font-normal text-slate-500"> · {c.role} / {c.department}</span>
        </div>
        <div className="flex items-center gap-2">
          {outreach && <StatusPill status={outreach.status} />}
          <span className="rounded-full bg-slate-900 px-2 py-0.5 text-xs font-semibold text-white">score {c.score}</span>
        </div>
      </div>
      <div className="mt-1 text-xs text-slate-500">
        📞 {c.phone} · {c.contract} · {Math.round(c.scheduled_hours)}/{Math.round(c.max_hours)}h ·{" "}
        {c.overtime_ok ? "OT OK ✅" : "OT: no"}{c.rest_hours != null ? ` · ${Math.round(c.rest_hours)}h rest` : ""}
      </div>
      <ul className="mt-2 list-disc pl-5 text-sm text-slate-700">
        {c.why.map((w, i) => <li key={i}>{w}</li>)}
      </ul>
    </div>
  );
}
```

`web/src/app/uks/components/IntakePhone.tsx` — the SMS/WhatsApp mock:

```tsx
"use client";
import { useState } from "react";
import type { GapState } from "../api";

const SAMPLES = [
  "Felix Haddad (HOSP-1059) just called in sick for tonight's ICU night shift (Sat 06/20, 19:00-07:00). He's a Registered Nurse, ICU needs BLS + ACLS. Find me cover ASAP.",
  "Need a day-shift RN for Cardiology tomorrow, someone called out. BLS required.",
];
const FELIX = { role: "Registered Nurse", department: "ICU", shift: "night", day_label: "Sat 06/20", required_certs: ["BLS", "ACLS"], person_out: "Felix Haddad (HOSP-1059)" };

export function IntakePhone({ onSubmit, busy, parsed }:
  { onSubmit: (b: { message?: string; structured?: object }) => void; busy: boolean; parsed: GapState["gap"] | null }) {
  const [msg, setMsg] = useState(SAMPLES[0]);
  return (
    <div className="rounded-2xl border border-slate-300 bg-slate-900 p-3 shadow-lg">
      <div className="rounded-xl bg-white p-3">
        <div className="mb-2 border-b border-slate-100 pb-2 text-xs font-semibold text-slate-500">
          📱 UKS staffing line · Ward Sister, ICU · 18:30
        </div>
        <div className="mb-3 max-w-[85%] rounded-2xl rounded-tl-sm bg-slate-100 px-3 py-2 text-sm text-slate-800">
          {msg}
        </div>
        {busy && <div className="mb-2 text-xs italic text-slate-400">agent reading the message…</div>}
        {parsed && (
          <div className="mb-2 flex flex-wrap gap-1">
            {[parsed.role, parsed.department, `${parsed.shift} shift`, ...(parsed.required_certs ?? [])]
              .filter(Boolean)
              .map((chip, i) => (
                <span key={i} className="rounded-full bg-[#b3122b]/10 px-2 py-0.5 text-xs font-medium text-[#b3122b]">{chip}</span>
              ))}
          </div>
        )}
        <textarea
          className="mb-2 h-20 w-full rounded-lg border border-slate-200 p-2 text-sm"
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
        />
        <div className="flex flex-wrap gap-2">
          {SAMPLES.map((s, i) => (
            <button key={i} onClick={() => setMsg(s)} className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-500 hover:bg-slate-50">
              sample {i + 1}
            </button>
          ))}
        </div>
        <div className="mt-2 flex gap-2">
          <button onClick={() => onSubmit({ message: msg })} disabled={busy}
            className="flex-1 rounded-lg bg-[#b3122b] px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
            {busy ? "Working…" : "Find cover (AI parses)"}
          </button>
          <button onClick={() => onSubmit({ structured: FELIX })} disabled={busy}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            Scenario
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Rebuild `web/src/app/uks/page.tsx` as the ops console**

Replace the page body: keep the existing state/effects (gapId, st, busy, err, SSE EventSource, escalate countdown), swap the JSX to the two-column layout: left rail = `<IntakePhone onSubmit={load} busy={busy} parsed={st?.gap ?? null} />` + a Schedule card wrapping `<ScheduleGrid preview={st.schedule_preview} />` + the `roster_sync` link; main = gap header with `<StatusPill status={st.gap.status} />`, outreach controls (Start/Escalate + countdown — unchanged logic), the candidate board using `<CandidateRow .../>`, and the collapsible excluded list. `load(body)` now takes the `IntakePhone` payload (`{message}` or `{structured}`) and calls `seed()` then `createGap(body)` (as today). Add the roster-sync link block:

```tsx
{st.roster_sync?.link && (
  <p className="mt-2 text-xs text-slate-500">
    ✅ Roster updated in {st.roster_sync.target === "google_sheets" ? "Google Sheets" : "the schedule file"} —{" "}
    {st.roster_sync.target === "google_sheets"
      ? <a className="text-[#b3122b] underline" href={st.roster_sync.link} target="_blank" rel="noreferrer">open sheet</a>
      : <code className="text-slate-600">{st.roster_sync.link}</code>}
  </p>
)}
```

- [ ] **Step 4: Build / type-check**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks/web && npm run build`
Expected: build succeeds; `/uks` + `/uks/accept` compile with no type errors. Fix types until green.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/uks
git commit -m "P2 web: SMS intake mock + live schedule grid + ops-console redesign"
```

---

### Task 6: Restyle accept page · design-review polish · final verification

**Files:**
- Modify: `web/src/app/uks/accept/page.tsx`
- Verify: full `pytest` + `npm run build` + a live manual drive
- Optional: run the `design-review` skill on `/uks`

- [ ] **Step 1: Restyle `accept/page.tsx`** to match the brand (deep-red header, `StatusPill`, card states for confirmed/already_filled/invalid). Keep the existing `useSearchParams` + `<Suspense>` structure and the `acceptToken` call; only the presentation changes.

- [ ] **Step 2: Full offline test suite**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks && uv run pytest -q`
Expected: all PASS (P2 shift + roster_sink + P10).

- [ ] **Step 3: Web build**

Run: `cd /Users/jayasankarks/Documents/GitHub/hk-uks/web && npm run build`
Expected: succeeds.

- [ ] **Step 4: Live manual drive (xlsx fallback path, no Google creds)**

Start API (`LLM_PROVIDER=ollama AUTH_MODE=dev uv run uvicorn api.main:app --port 8000`) + web (`cd web && npm run dev`). On `/uks`: use the phone mock → "Find cover" (or Scenario) → Start outreach → accept the magic link → confirm the board flips to filled, the schedule grid cell turns **N**, and the "Roster updated → `data/hospital_schedule_updated.xlsx`" link shows. Open that xlsx and confirm the green-highlighted cell + the `Updates` audit row.

- [ ] **Step 5: design-review polish pass**

Invoke the `design-review` skill against `http://localhost:3000/uks`; apply the spacing/hierarchy/contrast fixes it reports (within `web/src/app/uks/**` only).

- [ ] **Step 6: Commit + update STATE.md note**

```bash
git add web/src/app/uks STATE.md
git commit -m "P2: restyle accept page + design-review polish; STATE note for Sheets/intake"
```

(Append a one-line note to the P2 entry in `STATE.md`: "+ Google-Sheets/xlsx roster round-trip, SMS intake mock, ops-console redesign.")

---

## Self-Review

**Spec coverage:**
- Google Sheets live + xlsx fallback round-trip → Tasks 1 (XlsxSink), 2 (wiring), 3 (GoogleSheetsSink). ✅
- SMS/WhatsApp intake mock → Task 5 (`IntakePhone`). ✅
- Clinical ops-console redesign → Tasks 5 (page + components) + 6 (accept page + design-review). ✅
- `roster_sync` surfaced in UI → Task 2 (state) + Task 5 (link block). ✅
- `schedule_preview` for the live grid → Task 4 (data) + Task 5 (`ScheduleGrid`). ✅
- Offline tests (XlsxSink, selection, accept-never-crashes) → Tasks 1–4. ✅ `gspread` added → Task 3. ✅ Env vars → Task 3. ✅
- Out of scope (inbound webhooks, OAuth flow) honored. ✅

**Placeholder scan:** No TBD/TODO. Every code step shows full code. The page.tsx rebuild (Task 5 Step 3) is described as a targeted swap of the JSX with the exact new blocks given (roster-sync link) reusing the already-shipped state/effects — the existing page is in the repo, so this is a real, bounded edit, not a placeholder.

**Type consistency:** `SyncResult(target, ok, link, detail)` is identical across `roster_sink.py`, `roster_sink_google.py`, and the `roster_sync` dict (`{target, ok, link}`) in `gap_state` and the web `GapState.roster_sync`. `get_sink()` return type is `RosterSink` (XlsxSink | GoogleSheetsSink) everywhere. `schedule_preview` shape (`days/gap_day/rows[{employee_id,name,role,is_winner,grid}]`) matches between `gap_state` (Task 4) and `ScheduleGrid`/`GapState` (Task 5). `record_fill(*, employee_id, name, day_label, code, when)` keyword signature matches the call site in `accept` (Task 2) and both sink implementations.
