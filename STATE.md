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
- ⬜ **Phase 0 — foundation** (SOLO, on `main`): shared `core/` (db · auth · agent-loop ·
  rag · tools) + FastAPI `api/` + Next.js `web/` + Supabase, with **P10 wired end-to-end**
  as the reference template. _Status: NOT STARTED._
- ⬜ **Phase 1 — flagships** (parallel git worktrees): P2 UKS, P4 Persowerk.
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

## Operational facts every instance must know
- **Gemini free key = ~20 requests/DAY per model**, and only the **2.5** models exist on it
  (`gemini-2.5-flash-lite` / `flash` / `pro`; the 2.0 models 404). Agent loops blow this fast →
  use a **billed key for heavy work**; otherwise lean on the `core/llm` cache. Don't thrash on 429s.
- **Run prototype:** `uv run streamlit run app/Home.py` (port 8501).
- **Run API:** _Phase 0 fills this in._   **Run web:** _Phase 0 fills this in._
- **Sample data:** `hackathon_problems_20260620/` (see `core.config.PATHS`).
- **.env:** `GEMINI_API_KEY` today; Phase 0 adds `DATABASE_URL`, `SUPABASE_URL`,
  `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `AUTH_MODE`.

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
