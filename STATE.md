# STATE.md — Mona AI · living handoff (READ THIS FIRST)

> Single source of truth shared across all Claude Code instances/worktrees.
> Pair it with `CLAUDE.md` (the per-problem build contract). **Update this file whenever
> you finish a phase, change a decision, or claim a flagship** — it's how instances stay in sync.

## North star
Take the working 10-agent prototype → a real, sellable, multi-tenant product. **Productize
2–3 flagships fully** (P10 Rheinmetall secure intake, P2 UKS shift, P4 Persowerk fraud);
keep the other 7 as polished prototypes that migrate in over time.

## Where we are  ← keep this current
- ✅ **Prototype**: 10 customer agents in one Streamlit app, all verified live on Gemini,
  demo pre-baked into a response cache. (see `CLAUDE.md`, `PITCH.md`)
- ✅ **Phase 0 — foundation** (DONE): shared `core/` (provider-switch llm · db · auth ·
  agent tool-loop · rag · tools) + FastAPI `api/` + Next.js `web/`, with **P10 Rheinmetall
  wired end-to-end** (web → API → agent loop → SQLite, tenant-scoped + audited). Runs on
  SQLite + dev-auth locally; Supabase-ready via env. Offline tests green; the foundation is
  the template flagship worktrees copy.
- 🟡 **Phase 1 — flagships** (parallel git worktrees): **P2 UKS DONE** (`feat/uks`), P4 Persowerk ⬜.
  - **P2 UKS shift replacement** — deterministic **ArbZG eligibility engine** (qualified + not-on-shift
    + §5 ≥11h rest + §3 weekly cap + Active, with per-candidate **why-eligible / why-excluded**), fairness
    ranking (headroom · last-contacted · overtime · contract · ward · preference); free-text (`core.llm`)
    + structured gap intake; sequential **Twilio-or-simulated SMS** outreach with magic-link accept +
    manual/timer escalate; **race-safe first-accept lock** (single atomic `UPDATE … WHERE status='open'`,
    rowcount guard — a late reply after escalation can't double-fill); **live SSE dashboard** + accept page;
    schedule flips on accept. **Real-world round-trip**: on accept the roster update lands in a live
    **Google Sheet** (gspread, service-account) or an **xlsx write-back** fallback (`data/hospital_schedule_updated.xlsx`,
    highlighted cell + audit sheet) when no creds — `services/roster_sink.py`. **SMS/WhatsApp phone-mock intake**
    + **clinical ops-console redesign** (UKS-branded) + a **live schedule grid** in `web/src/app/uks/`. Tested
    offline (ollama + simulated Twilio + throwaway SQLite): compliance
    exclusions, ranking, the first-accept race (threaded), the roster-sink (xlsx + selection + accept-never-crashes),
    and the API happy path. Run: API
    `LLM_PROVIDER=ollama AUTH_MODE=dev uv run uvicorn api.main:app --port 8000`, web `cd web && npm run dev`,
    open `/uks`. Tests: `uv run pytest tests/test_shift.py`. No new pip deps (Twilio via REST/httpx; SSE
    via StreamingResponse). Files: `agents/shift.py`, `services/shift.py`, `api/routes/shift.py`,
    `web/src/app/uks/**`, `core/models/shift.py` (+ alembic `p2shiftcols01`).
- ⬜ **Phase 2**: Theiss cluster (P7/P8/P9) → lighter (P1/P3/P5) → P6 reels.

## Locked decisions — do not re-litigate
- **Backend** FastAPI (`api/`). **Frontend** Next.js App Router + TypeScript + Tailwind + shadcn/ui (`web/`).
- **DB + Auth** Supabase (Postgres + Supabase Auth, JWT, **multi-tenant**). Local dev MUST
  run on SQLite + `AUTH_MODE=dev` bypass so no one is blocked on credentials.
- **LLM** Google Gemini, isolated entirely in `core/llm.py` (already has a model-agnostic
  response cache + a model fallback chain).
- **UI design** produced in **Claude Design** (claude.ai/design, Opus 4.7, free on the plan)
  → exported as **handoff bundles** → implemented in `web/` by Claude Code.
- **Engineering bar = PRODUCTION-GRADE, not YAGNI-minimal.** Proper input validation,
  error handling, structured logging, DB migrations, automated tests, authz/security,
  end-to-end types, observability. Build it to ship, not to demo.
- `agents/*.py` stay **PURE logic** (no web/db imports). Persistence + auth live in `api/` + services.
- Keep the Streamlit app (`app/`) working during migration; retire it last.

## Flagship decisions — P2 & P4 (locked via /plan-eng-review)
Both EXTEND the monorepo as worktree flagships (reuse core/agent + db + auth + the
shift/fraud tables). Dashboards are Next.js pages under `web/`; P2's needs SSE for live
status, P4's is a static result view + history.

**P2 UKS — shift replacement (action agent)**
- Core = deterministic ELIGIBILITY engine with ArbZG compliance baked in (qualified +
  not-already-on-shift + ≥11h rest since last shift end [§5] + under weekly cap [§3]),
  then fairness ranking (recent overtime, shifts this week). This is the substance beat.
- Outreach = SMS/WhatsApp ONLY, **no live voice call** (deliberate de-risk). Sequential:
  contact #1, escalate to #2 on timeout (short, manually-triggerable for the demo).
- Accept = magic-link in the SMS → accept page → first-accept **transactionally locks**
  the ShiftGap (race-safe); losers told "filled". (default; SMS-reply parse is the alt.)
- Send via real Twilio SMS for the demo (a text lands on a real phone), simulated fallback.
- Live dashboard via SSE: ranked candidates + why-eligible, outreach status, schedule flips on accept.
- Out of scope: voice/Vapi, real WhatsApp Business API (sandbox or SMS only).

**P4 Persowerk — CV/cert fraud SIGNALS (human-review, never auto-reject)**
- Forensics (deterministic): PDF metadata + incremental-update edit history + Producer
  chain; image EXIF; ELA heatmap (labelled a weak signal, not proof).
- Consistency: timeline overlaps/gaps, CV vs cert vs claims.
- Verify (agent tool-loop): github_lookup (public API; handle parsed from the CV) +
  company/role web check (firecrawl). Registry/OpenBadges only where a public API exists, skip honestly.
- Output: risk score with a per-signal EVIDENCE span; UI frames everything as
  "signal for a recruiter, not a verdict". NO AI-text-detector reject signal (unreliable
  + biased against non-native writers — stated openly; this is the maturity beat).
- Out of scope: real issuer-registry verification at scale, LinkedIn scraping.

## Target architecture (monorepo)
```
core/   db · models/ · auth · agent (tool-loop) · rag · tools/ · llm · guard · ingest · config
agents/ pure per-problem logic (already decoupled — keep)
api/    FastAPI — agents exposed as authenticated, tenant-scoped endpoints
web/    Next.js — the product UI (built from Claude Design handoff bundles)
app/    legacy Streamlit — transitional, retire last
```

## Infra map — what each problem actually needs (✅✅ = real multi-agent loop)
| # | Problem | DB | RAG | Agent loop | Firecrawl research |
|---|---------|----|----|-----------|--------------------|
| 10 | Rheinmetall secure intake | ✅ applicants+audit | ◯ policy | ✅✅ | OWASP LLM injection |
| 2 | UKS shift | ✅ staff/quals/history | — | ✅✅ | nurse-rostering rules |
| 4 | Persowerk fraud | ✅ candidates/certs | ✅ issuer registries | ✅✅ | IHK/ISACA/uni registries |
| 7 | Theiss analytics | ✅ events+campaigns | — | ✅ | — |
| 8 | Theiss pricing | ✅ price+signal log | — | ✅ | weather/fixtures/supply |
| 9 | Theiss gaps | ✅ competitor snaps | ✅ competitor corpus | ✅ | competitor catalogs |
| 3 | Leistenschneider permits | ◯ log | ✅ §AufenthG rules | light | German permit/work-auth law |
| 1 | Globus invoices | ✅ records+routing+audit | — | light | ERP export formats |
| 5 | Kohlpharma interview | ◯ kits | ✅ competency frameworks | light | role taxonomies (O*NET) |
| 6 | Theiss reels | ◯ renders | — | medium | text-to-video APIs |

Full per-problem acceptance boxes + sample-data paths are in `CLAUDE.md` and `core.config`.

## LLM budget — HARD CONSTRAINT (the key is given; we cannot raise it)
The Gemini key is provided by the org — **we cannot enable billing or change quotas.**
It allows **~20 requests/DAY per model**, and only the **2.5** models exist on it
(`gemini-2.5-flash-lite` / `flash` / `pro`; 2.0 models 404). Fallback chain ≈ 60 calls/day
total. Agent loops use 5–20 calls each → only a handful of live runs/day. So we design
around it, not against it:
- **Local dev provider.** `core/llm.py` exposes `LLM_PROVIDER=ollama|gemini`. Develop and
  test agent loops against a **local Ollama/MLX model on the M2 (unlimited, free)**; reserve
  the Gemini key for final-quality passes + the demo. Provider stays isolated in `core/llm.py`.
- **Cache is load-bearing.** Every call is cached (model-agnostic, on disk). Re-runs cost 0.
- **Tests never hit the live API** — mock or replay from cached fixtures; the suite runs offline.
- **Frugal loops.** `core/agent.py` uses a low `max_steps`, batches reasoning, prefers a
  single structured pass where multi-step isn't essential, and logs a **per-run call count**.
- **Demo is pre-baked.** Run each demo flow once (cached) → replays free + instant on stage.
- **Budget the day's ~60 Gemini calls** for final verification + pre-baking, not iteration.

## Operational facts every instance must know
- Supabase is also org-provided (free tier is fine for this; don't assume you can raise its limits either).
- **Run prototype (Streamlit):** `uv run streamlit run app/Home.py` (port 8501).
- **Run API:** `uv run uvicorn api.main:app --reload --port 8000` (set `LLM_PROVIDER=ollama` + `AUTH_MODE=dev` for free local dev).
- **Run web:** `cd web && npm install && npm run dev` (port 3000 → talks to the API at :8000).
- **Run tests (offline/free):** `uv run pytest` (forces ollama + a throwaway SQLite; never touches the Gemini quota).
- **Migrations:** `uv run alembic upgrade head` (prod/Postgres). Local/SQLite auto-creates via init_db on API startup.
- **Sample data:** `hackathon_problems_20260620/` (see `core.config.PATHS`).
- **.env:** `GEMINI_API_KEY`; optional `LLM_PROVIDER` (gemini|ollama), `AUTH_MODE` (dev|supabase),
  `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
  `SUPABASE_JWT_SECRET`, `WEB_ORIGIN`, `FIRECRAWL_API_KEY`.

## Cross-instance coordination (worktrees)
- **Phase 0 runs SOLO on `main`** — the foundation is shared, so no parallel work until it lands & is committed.
- **Phase 1 flagships run in git worktrees**, one instance each, owning **disjoint files**:
  - P2 UKS → `agents/shift.py`, `api/routes/shift.py`, `core/models/shift.py`, `web/app/uks/**`
  - P4 Persowerk → `agents/fraud.py`, `api/routes/fraud.py`, `core/models/fraud.py`, `web/app/persowerk/**`
  - **All flagship DB tables are pre-defined in `core/models/` during Phase 0** so worktrees never collide on schema.
- Don't edit shared files (`core/db`, `core/auth`, `core/agent`, `api/main`, `CLAUDE.md`, this file)
  from a flagship worktree without flagging it here first.
- Commit in logical chunks; one PR per flagship; never push straight to `main`.
- **When you finish a phase/flagship: update "Where we are" + fill in the run commands above.**

## Claude Design workflow
Design each screen in claude.ai/design → export a **handoff bundle** → implement in `web/`
with Claude Code. Keep components modular/restylable. Use the per-customer branding in
`core/config.py` `CUSTOMERS` as the design system so each customer page is on-brand.
