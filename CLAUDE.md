# Mona AI Hackathon 2026 — Agent Suite

Ten customer feature requests → ten agents → **one Streamlit app**. Deadline **18:00 today**.
Goal: a *plausible prototype* of each that **checks every box in the customer's brief**.
Principles: **KISS · YAGNI · customer-centric**. No bonus for over-solving — hit the boxes, make it demoable by a non-technical customer (no terminal/Postman), and move on.

## Architecture (read before writing code)

One repo, one app. Three clusters, shared core.

```
core/        SHARED lib — do NOT fork. config, llm (Claude), ingest, guard, schemas, ui
agents/      one module per problem = pure logic, returns pydantic objects (testable)
app/Home.py  landing page (cluster cards)
app/pages/   one Streamlit page per problem = thin UI calling its agent
evals/       headless accuracy checks against the labelled sample data
hackathon_problems_20260620/  the customer test data (read-only)
```

**Golden template** — copy its shape: `agents/permits.py` + `app/pages/03_Leistenschneider_Work_Permits.py` + `evals/permits_eval.py`.

### Use the core lib (don't reinvent)
- `core.llm.ask(prompt, system=…)` → text. `core.llm.extract(PydanticModel, content, system=…)` → **validated structured output** (tool-use; never parse JSON by hand).
- `core.ingest.file_to_blocks(path)` / `bytes_to_blocks(data, suffix)` → Claude content blocks for **pdf / png / jpg / docx / xlsx / txt**. Claude reads PDFs & images **natively — do not add OCR (Tesseract etc.)**.
- `core.guard` → prompt-injection defense. Any agent that reads third-party email/docs: put `guard.SAFE_SYSTEM` in the system prompt and `guard.wrap(text)` around untrusted text; surface `guard.scan(text)`.
- `core.ui.page_setup("<customer_key>")` renders the branded header; `ui.require_key()`, `ui.confidence(pct)`.
- `core.config.CUSTOMERS` = branding/brief per problem. `core.config.PATHS` = data file shortcuts. `core.config.MODEL` (Sonnet 4.6 default) / `MODEL_SMART` (Opus 4.8).

## HARD RULES for subagents (prevent merge conflicts)
1. **Own only your two files**: `agents/<name>.py` and `app/pages/<NN>_<...>.py` (+ optional `evals/<name>_eval.py`). Touch nothing else.
2. **Never edit** `core/*`, `pyproject.toml`, `CLAUDE.md`, `app/Home.py`, `core/config.py`. All deps are pre-installed (see pyproject). Need a new dep? **Don't add it** — note it in your final report instead.
3. Every page starts with the 3-line `sys.path` shim (see golden template), then `ui.page_setup("<key>")`.
4. Output must be **plain-language for a non-technical customer**: a clear verdict + confidence + reasons, not raw JSON (raw JSON goes in an expander).
5. Prefer `core.llm.extract` with a small pydantic schema over free-text. Keep it simple.
6. Don't write tests-as-ceremony. If there's labelled data, write a tiny `evals/` accuracy script instead.

## The 10 problems — acceptance boxes + data

| # | key | Customer | Must do (boxes) | Data (`core.config.PATHS`) |
|---|-----|----------|------------------|------|
| 1 | `globus` | Globus Group | read invoice (pdf/png/docx) → extract vendor/total/category → **route to dept** → flag for human confirm | `invoices/` (+`00_manifest.csv` = ground truth) |
| 2 | `uks` | UKS | receive a shift-gap message → find **available qualified** staff → **draft outreach** automatically | `schedule` (xlsx) |
| 3 | `leistenschneider` | Leistenschneider | confirm doc **is** a permit → confirm/deny **+ confidence %** → **valid-until date** | `permits/` (labelled valid/invalid) ✅ done |
| 4 | `persowerk` | Persowerk | verify work history & skills plausibility → **flag AI-generated/fraud** → certificate valid & current | `cvs/`, `certificates/` |
| 5 | `kohlpharma` | Kohlpharma | job offer → **role-relevant interview questions** → **red-flag checklist** | `job_offers` (pdf) |
| 6 | `theiss_reels` | Dr. Theiss | produce **vertical short-form reel** → **respect TikTok/IG safe zones** (text margins) | `theiss` (pdf) |
| 7 | `theiss_analytics` | Dr. Theiss | ingest customer data → **patterns/segments** → targeting signal + **optimal date/time** → **measure lift** | `theiss` (pdf) |
| 8 | `theiss_pricing` | Dr. Theiss | adjust price on **external signals** (weather/season/football/supply) → **guardrails (min/max)** + rationale | `theiss` (pdf) |
| 9 | `theiss_gaps` | Dr. Theiss | product set vs **competitors** → surface **white-space gaps** | `theiss` (pdf) |
| 10 | `rheinmetall` | Rheinmetall | process email+docs **injection-resistant** → check **all required docs present** (CV, residence permit, work permit, criminal record) → report missing | reuse `cvs/`, `permits/` |

Notes: P2 "reach out automatically" = **draft + show the message** (simulate send; don't wire real SMS). P6 = templated render (Claude script + slides + gTTS + ffmpeg) with safe-zone overlay; hard-timebox, fall back to storyboard. P7/P8/P9 may use the `firecrawl` MCP for live web signals/competitor data; figures in the data pack are synthetic.

## Commands
```bash
uv sync                                   # install (done)
uv run streamlit run app/Home.py          # launch the whole suite
uv run python -m evals.permits_eval       # headless accuracy check
```

## Setup / keys
Put your key in `.env` at repo root: `ANTHROPIC_API_KEY=…` (optional `ELEVENLABS_API_KEY` for nicer P6 TTS; gTTS is the free fallback). `.env` is gitignored.

## Definition of done (per agent)
Page loads in the suite · customer-branded header · runs on its sample data with **one upload/click** · returns a verdict a non-technical customer understands · checks every box in its row above.
