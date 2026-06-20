# UKS P2 — Google Sheets round-trip · SMS intake mock · ops-console redesign

**Status:** approved in brainstorming (2026-06-20). Builds on the shipped P2 flagship (`feat/uks`).

## Goal
Make the shipped UKS shift-replacement agent feel like a real product:
1. **Real-world schedule round-trip** — when a shift is filled, the roster update lands in a real **Google Sheet** (live), with an **xlsx write-back** fallback so it works before credentials exist.
2. **Believable intake** — present the inbound sick-call as an **SMS/WhatsApp phone mock** that parses into the structured gap.
3. **Redesign** the `/uks` UI into a polished, UKS-branded **clinical ops console**.

## Decisions (locked)
- Sheets client: **gspread + google-auth** (add to `pyproject.toml` via `uv add`). Service-account auth only (no OAuth user flow).
- Sink falls back to **xlsx** (openpyxl, already a dep) when no Google creds.
- Intake mock is **presentation only** over the existing `createGap` flow — no real inbound webhook.
- UI: **clinical ops console**, UKS deep-red (`#b3122b`), two-column layout. `design-review` skill as the polish pass after build.

## Non-goals
Real inbound SMS/WhatsApp webhooks; Sheets OAuth user consent flow; multi-worker SSE; changing the eligibility engine, lock, or outreach logic (all shipped + tested).

---

## Component 1 — `RosterSink` (schedule round-trip)

**New file `services/roster_sink.py`** (P2-only, disjoint from `services/secure_intake.py`). One small interface, two implementations, a factory:

```python
@dataclass
class SyncResult:
    target: str           # "google_sheets" | "xlsx" | "none"
    ok: bool
    link: str | None      # sheet URL or file path
    detail: str | None = None

class RosterSink(Protocol):
    def push_roster(self, rows: list[dict], day_cols: list[str]) -> SyncResult: ...
    def record_fill(self, *, employee_id: str, name: str, day_label: str,
                    code: str, when: datetime) -> SyncResult: ...

def get_sink() -> RosterSink            # GoogleSheetsSink if creds else XlsxSink
```

- **`GoogleSheetsSink`** — active when `GOOGLE_SHEETS_ID` **and** `GOOGLE_SHEETS_CREDENTIALS_JSON` (path to a service-account key) are set. Uses `gspread.service_account(filename=...)` / `gspread.authorize`. `push_roster` writes a worksheet (employee_id, name, role, dept + one column per day) so there's a grid to flip. `record_fill` finds the row by `employee_id`, the column by `day_label`, sets it to `code` (`N`/`D`); returns the sheet URL. Live-flips on a second screen.
- **`XlsxSink`** (default) — copies the source `hospital_schedule_part_2.xlsx` to `data/hospital_schedule_updated.xlsx` on first use; `record_fill` updates the `Weekly_Schedule` cell, **highlights it green** (openpyxl `PatternFill`), and appends a row to an `Updates` sheet ("emp · name · day · code · when"). Returns the file path.

**Wiring in `services/shift.py`:**
- `seed_staff()` → after DB upsert, best-effort `get_sink().push_roster(...)` (so the sheet has the roster). Never raises.
- `accept()` → after the DB grid flips and the txn commits (outside the lock), best-effort `get_sink().record_fill(...)`. Wrapped in try/except → logged, never crashes a fill. The `SyncResult` is stashed (module-level `_last_sync[gap_id]`) so state can surface it.
- `gap_state()` → add `"roster_sync"`: when the gap is filled, return the last `SyncResult` (or derive `{target, link}` from env so a reload still shows the link).

**Env (added to `.env.example`):**
```
GOOGLE_SHEETS_ID=                      # target spreadsheet id; empty -> xlsx fallback
GOOGLE_SHEETS_CREDENTIALS_JSON=        # path to a service-account key json
GOOGLE_SHEETS_WORKSHEET=Roster         # worksheet name (optional)
```

**Testing (offline):** `XlsxSink.record_fill` writes a temp xlsx → assert the target cell == `N` and an `Updates` row exists. `get_sink()` returns `XlsxSink` when env is unset (and would return `GoogleSheetsSink` when set — asserted via monkeypatched env, without network). `GoogleSheetsSink` import + construction is guarded so the module imports cleanly with no creds. `accept()` still returns `confirmed` and never raises when the sink errors (inject a sink that throws).

---

## Component 2 — SMS/WhatsApp intake mock (web)

**`web/src/app/uks/components/IntakePhone.tsx`** (new, local to the uks subtree). A phone-frame card:
- A header ("📱 UKS staffing line · Ward Sister, ICU · 18:30").
- The sick-call as an inbound chat bubble; an editable field + 2–3 canned sample messages (Felix ICU night; a day-shift RN; a CNA gap).
- A "Find cover" action → calls the existing `createGap({message})` (AI parse) or the deterministic scenario; while busy shows an "agent reading the message…" indicator; on success the **parsed gap chips** (role · ward · shift · certs) animate in.
- No backend change. Replaces the current raw textarea card on `/uks`.

**Testing:** covered by the web `npm run build` type/lint gate + manual visual check (it wraps an already-tested API path).

---

## Component 3 — clinical ops console redesign (web)

Restyle `web/src/app/uks/page.tsx` (+ `accept/page.tsx`) into a two-column, UKS-branded console; add local presentational components under `web/src/app/uks/components/` (e.g. `ScheduleGrid.tsx`, `CandidateRow.tsx`, `StatusPill.tsx`). `@/components/ui` stays untouched (imported read-only).
- **Left rail:** `IntakePhone` + a live **Schedule panel** — `ScheduleGrid` renders the weekly D/N/O grid (from `gap_state` data; the API already returns the gap + we add the winner's row), the gap cell flipping via the existing SSE stream; plus a "roster synced → open Sheet/file" link from `roster_sync`.
- **Main column:** gap header with a status pill (OPEN/FILLED), the ranked candidate board as the hero (rank, score, why bullets, per-candidate outreach pill, OT/rest/headroom meta), outreach controls (Start / Escalate + countdown), and a collapsible excluded-with-reasons list.
- Type scale, spacing system, status color tokens (queued=slate, sent=amber, accepted=green, declined=red). Deep-red brand accents.
- After build, run the `design-review` skill for a designer's-eye QA pass and apply its fixes.

**Schedule panel data:** to render a real grid we need a few staff rows + their week. Minimal approach: `gap_state` already returns `eligible`/`outreach`; add a small `schedule_preview` to `gap_state` = the gap day column for the top ~8 relevant staff (eligible + the filled winner) with their D/N/O for that week, so the grid is real but bounded. (Engine/DB already hold `shift_grid`.)

---

## Build order (for the plan)
1. `RosterSink` + `XlsxSink` (TDD, offline) → wire into `seed`/`accept`/`gap_state` → `.env.example`.
2. `GoogleSheetsSink` (gspread) behind the same interface (`uv add gspread`); selection logic tested, live path manual.
3. Web: `IntakePhone` + redesign components + `ScheduleGrid` (fed by `schedule_preview`).
4. `design-review` polish pass; full `pytest` + `npm run build`; commit in chunks.

## Risks
- gspread/google-auth install: mitigated by the xlsx fallback being the default and the Google path being import-guarded.
- `schedule_preview` payload size: bounded to the relevant staff, not all 100.
- STATE.md/PR: still no git remote (separate, pre-existing blocker).
