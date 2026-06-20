"""Central config: paths, model ids, and the customer registry used for per-page branding.

Everything customer-facing reads from CUSTOMERS so each agent page is framed as its
own customer deliverable (fully customer-centric), even though they share one repo.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---- paths ---------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
PROBLEMS_DIR = REPO_ROOT / "hackathon_problems_20260620"
DATA_OUT = REPO_ROOT / "data"  # runtime artifacts (gitignored)
DATA_OUT.mkdir(exist_ok=True)

load_dotenv(REPO_ROOT / ".env")

# ---- provider switch -----------------------------------------------------
# gemini = prod/demo (org key, capped ~20 req/day/model). ollama = free local dev on
# the M2 (llama3.1:8b chat+tools, nomic-embed-text embeddings). Default stays gemini so
# the existing Streamlit demo + its pre-baked cache are untouched; dev/tests opt in with
# LLM_PROVIDER=ollama. Vision (PDF/image) has no local model -> always routed to gemini.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_EMBED = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
GEMINI_EMBED = os.getenv("GEMINI_EMBED_MODEL", "text-embedding-004")

# ---- models (Gemini; override via .env) ----------------------------------
# The free tier caps each model at ~20 requests/DAY. Each model has its OWN bucket, so
# we keep a fallback CHAIN: when one model's daily cap is hit, core.llm rolls to the
# next automatically. Combined with a model-agnostic response cache, the suite keeps
# working across a day of demos on a free key.
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
MODEL_SMART = os.getenv("GEMINI_MODEL_SMART", "gemini-2.5-flash")
MODEL_FALLBACKS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACKS",
    # only models actually available on this key (2.0 models 404 here); ~20/day each
    "gemini-2.5-flash-lite,gemini-2.5-flash,gemini-2.5-pro",
).split(",") if m.strip()]
HAS_KEY = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))

# ---- data file shortcuts -------------------------------------------------
P = PROBLEMS_DIR
PATHS = {
    "invoices": P / "questions" / "invoices_hackathon_20260620_part_1",
    "schedule": P / "questions" / "hospital_schedule_part_2.xlsx",
    "permits": P / "work_permits_part_3",
    "certificates": P / "certificates_part_4",
    "cvs": P / "questions" / "CVs_hackathon_20260620",
    "job_offers": P / "problem5_job_offers.pdf",
    "theiss": P / "dr_theiss_allgaeuer_data_pack_part_6_to_9.pdf",
}

# ---- customer registry (one entry per problem) ---------------------------
# key -> branding + the customer's ask. Pages render from this so the jury sees
# ten distinct customer products, not ten tabs of one tool.
CUSTOMERS: dict[str, dict] = {
    "globus": {
        "n": 1, "company": "Globus Group", "city": "St. Wendel",
        "dept": "Finance", "color": "#0a7d3f", "icon": "🧾",
        "agent": "Invoice Triage Agent",
        "pain": "Finance is buried in supplier invoices, sorting and keying them by hand.",
        "promise": "Reads any invoice (PDF/photo/Word), extracts the key fields and routes it to the right department for a one-click confirm.",
    },
    "uks": {
        "n": 2, "company": "Universitätsklinikum des Saarlandes (UKS)", "city": "Homburg",
        "dept": "HR / Staffing", "color": "#b3122b", "icon": "🏥",
        "agent": "Shift Replacement Agent",
        "pain": "Night-shift gaps open with hours' notice when staff call in sick.",
        "promise": "Message it the gap; it finds available, qualified staff and drafts the outreach automatically.",
    },
    "leistenschneider": {
        "n": 3, "company": "Leistenschneider Personaldienstleistungen", "city": "Saarbrücken",
        "dept": "Compliance", "color": "#1f4e8c", "icon": "🛂",
        "agent": "Work-Permit Validator",
        "pain": "Validating candidate work permits entirely by hand — slow and error-prone.",
        "promise": "Confirms a document really is a work/residence permit, gives a confidence %, and reads the date it's valid until.",
    },
    "persowerk": {
        "n": 4, "company": "Persowerk Deutschland", "city": "Saarbrücken",
        "dept": "Talent / Verification", "color": "#6b21a8", "icon": "🔎",
        "agent": "CV & Certificate Authenticity Agent",
        "pain": "A wave of AI-generated CVs and certificates — candidates misrepresenting skills.",
        "promise": "Cross-checks work history and skills, flags fabrication signals, and verifies certificates are real and current.",
    },
    "kohlpharma": {
        "n": 5, "company": "Kohlpharma", "city": "Merzig",
        "dept": "Hiring Manager", "color": "#0e7490", "icon": "💬",
        "agent": "Interview Copilot",
        "pain": "A non-technical manager posted a technical role and doesn't know what to ask.",
        "promise": "Turns the job offer into role-relevant interview questions and a red-flag checklist.",
    },
    "theiss_reels": {
        "n": 6, "company": "Dr. Theiss Naturwaren — Allgäuer Latschenkiefer", "city": "Homburg",
        "dept": "Marketing", "color": "#15803d", "icon": "🎬",
        "agent": "Reel Studio Agent",
        "pain": "Marketing wants studio-quality short-form reels that respect platform safe zones.",
        "promise": "Generates a vertical reel with script, captions and TTS — text kept inside TikTok/Instagram safe zones.",
    },
    "theiss_analytics": {
        "n": 7, "company": "Dr. Theiss Naturwaren — Allgäuer Latschenkiefer", "city": "Homburg",
        "dept": "Marketing", "color": "#15803d", "icon": "📊",
        "agent": "Targeting Analytics Agent",
        "pain": "Wants to detect customer behavioural patterns and deliver ads at the optimal time.",
        "promise": "Ingests customer data, segments it, and recommends the best date/time to market — then measures lift afterwards.",
    },
    "theiss_pricing": {
        "n": 8, "company": "Dr. Theiss Naturwaren — Allgäuer Latschenkiefer", "city": "Homburg",
        "dept": "Marketing / Pricing", "color": "#15803d", "icon": "💶",
        "agent": "Dynamic Pricing Agent",
        "pain": "Wants prices that react to weather, seasons/events, football and supply shortages.",
        "promise": "A signal-driven pricing engine with guardrails (min/max bounds) and a written rationale for every move.",
    },
    "theiss_gaps": {
        "n": 9, "company": "Dr. Theiss Naturwaren — Allgäuer Latschenkiefer", "city": "Homburg",
        "dept": "Marketing / Strategy", "color": "#15803d", "icon": "🧭",
        "agent": "Competitive Gap Agent",
        "pain": "Wants to see the white-space competitors aren't filling.",
        "promise": "Benchmarks the product set against competitors and surfaces concrete product gaps to capture.",
    },
    "rheinmetall": {
        "n": 10, "company": "Rheinmetall", "city": "—",
        "dept": "Recruiting / Security", "color": "#1e293b", "icon": "🛡️",
        "agent": "Secure Intake Agent",
        "pain": "Got prompt-injected through an applicant email last week — it leaked the applicant database.",
        "promise": "Processes applicant emails + documents safely (injection-resistant) and checks every required document is present.",
    },
}
