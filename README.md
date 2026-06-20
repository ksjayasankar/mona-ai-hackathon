# Mona AI Hackathon 2026 — Customer Agent Suite

Ten customer feature requests, solved as ten agents in **one Streamlit app**. Built customer-centric: each page is its own branded deliverable.

## Demo

```bash
uv sync
echo "GEMINI_API_KEY=…" >> .env             # paste your key
uv run streamlit run app/Home.py
```

Open the sidebar → pick a customer → upload a file or click a sample.

## The agents

**📄 Document Intelligence** — Globus (invoice triage) · Leistenschneider (work-permit validator) · Persowerk (CV/certificate authenticity) · Rheinmetall (prompt-injection-resistant secure intake)

**📈 Dr. Theiss Marketing** — Reel Studio · Targeting Analytics · Dynamic Pricing · Competitive Gap

**👥 HR Action** — UKS (shift replacement) · Kohlpharma (interview copilot)

## Stack

Python · [uv](https://docs.astral.sh/uv/) · Streamlit · Google Gemini 2.5 Flash (native vision/PDF — no OCR stack) · pydantic. The LLM provider lives entirely in `core/llm.py`. See `CLAUDE.md` for architecture and conventions.

## Layout

`core/` shared lib · `agents/` per-problem logic · `app/pages/` per-problem UI · `evals/` accuracy checks · `hackathon_problems_20260620/` test data.
