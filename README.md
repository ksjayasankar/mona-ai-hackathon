# Mona AI Hackathon 2026 — Agent Platform

Ten customer feature requests → ten agents → **one multi-tenant product**. Each customer gets
their own branded agent, sharing one spine: a tool-using agent loop, tenant-scoped data, and
injection-resistant document intake by default.

Started as a 10-agent **Streamlit** prototype, productized into a **FastAPI** backend + **Next.js**
frontend (Supabase-ready, provider-switch LLM). **All 10 agents are live in the web product.**

## Run the demo (for reviewers)

Reviewers on the **same Wi-Fi** can use the live app — one command:

```bash
uv sync                                  # Python deps
echo "GEMINI_API_KEY=…" >> .env          # the LLM key (Google Gemini)
./run.sh                                 # starts API + web, prints a LAN URL
```

`run.sh` binds both services to your network and prints something like
`WEB : http://192.168.1.84:3000` — **open that on any device on the same network.**
Auth runs in dev mode (no login). On first run, macOS may ask to allow incoming
connections — allow it. To run **fully local & free**, use `LLM_PROVIDER=ollama ./run.sh`
(needs [Ollama](https://ollama.com)). Single machine: just open `http://localhost:3000`.

Manual equivalent:
```bash
AUTH_MODE=dev uv run uvicorn api.main:app --host 0.0.0.0 --port 8000     # backend
cd web && NEXT_PUBLIC_API_URL=http://<lan-ip>:8000 npm run dev -- -H 0.0.0.0   # frontend
```

## The 10 agents (all live)

| # | Customer | Agent | Route |
|---|----------|-------|-------|
| 1 | Globus Group | Invoice Triage | `/globus` |
| 2 | Universitätsklinikum des Saarlandes | Shift Replacement | `/uks` |
| 3 | Leistenschneider | Work-Permit Validator | `/leistenschneider` |
| 4 | Persowerk | CV & Certificate Authenticity | `/persowerk` |
| 5 | Kohlpharma | Interview Copilot | `/kohlpharma` |
| 6 | Dr. Theiss | Reel Studio (safe-zone aware) | `/theiss-reels` |
| 7 | Dr. Theiss | Targeting Analytics | `/theiss-analytics` |
| 8 | Dr. Theiss | Dynamic Pricing (guardrails) | `/theiss-pricing` |
| 9 | Dr. Theiss | Competitive Gap | `/theiss-gaps` |
| 10 | Rheinmetall | Secure Intake (injection-resistant) | `/rheinmetall` |

## Architecture

```
core/   shared lib — llm (provider-switch: gemini|ollama) · db · auth · agent (tool loop) · rag · guard · ingest
agents/ pure per-problem logic (testable, no web/db imports)
api/    FastAPI — agents as authenticated, tenant-scoped endpoints  (docs at /docs)
web/    Next.js — the product UI (operations-console design system; color = tenant)
app/    legacy Streamlit prototype (still runs: `uv run streamlit run app/Home.py`)
```

See `CLAUDE.md` (build conventions) and `STATE.md` (the living cross-instance handoff) for detail.

## Tests

```bash
uv run pytest        # 116 offline tests — run on a local Ollama model, no API key or network needed
```

## Note on data

The provided customer data packs (`hackathon_problems_20260620/` — sample invoices, CVs, permits,
certificates) are **excluded from this public repo** as a data-hygiene measure. The app runs on them
locally; agents also accept your own uploads. Stack: Python · [uv](https://docs.astral.sh/uv/) ·
FastAPI · Next.js · Google Gemini (native vision/PDF — no OCR stack) · SQLModel · pydantic.
