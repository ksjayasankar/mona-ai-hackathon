"""P4 Persowerk — CV & certificate fraud-SIGNALS service (tenant-scoped, persisted).

Pipeline (mirrors services/secure_intake.py):
  1. FORENSICS  — deterministic PDF/image checks (core.tools.forensics). No LLM.
  2. EXTRACT    — core.llm vision reads roles/dates/skills (CV) + issuer/holder/dates (certs).
  3. CONSISTENCY— deterministic timeline/cross-doc/cert-currency signals (agents.fraud).
  4. INJECTION  — guard.scan over CV text; embedded instructions = strong fraud flag.
  5. VERIFY     — core.agent tool-loop: github_lookup + web_search (optional; network).
  6. SCORE      — weighted signals -> LOW/MEDIUM/HIGH + 0-100, each with its evidence span.
  7. PERSIST    — Candidate + Certificate + VerificationRecord (tenant-scoped) + AuditLog.

`build_report` is a PURE seam (no LLM/network/db) so the offline suite can exercise the
whole assembly + scoring. The output is always framed "signal for a recruiter, not a verdict".
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel
from sqlmodel import Session, desc, select

from agents import fraud as A
from agents.fraud import (CertFields, CVClaims, RiskAssessment, VerifyFindings,
                          cert_signals, consistency_signals, cross_signals,
                          findings_to_signals, injection_signals, score_risk)
from core import guard, ingest, llm
from core.agent import Tool, run_agent
from core.db import engine
from core.models import AuditLog, Candidate, Certificate, VerificationRecord
from core.tools.forensics import Signal, analyze_document
from core.tools.web import web_search

log = logging.getLogger("fraud")
TODAY = date(2026, 6, 20)
GITHUB_API = "https://api.github.com"


def parse_github_handle(url_or_handle: str | None) -> str | None:
    if not url_or_handle:
        return None
    t = url_or_handle.strip().strip("@/")
    m = re.search(r"github\.com/([A-Za-z0-9-]+)", t)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9-]+", t):
        return t
    return None


def github_lookup(handle: str) -> str:
    """Public GitHub REST: account age + languages used. Never raises; honest on failure."""
    handle = parse_github_handle(handle) or handle
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        u = httpx.get(f"{GITHUB_API}/users/{handle}", headers=headers, timeout=15)
        u.raise_for_status()
        user = u.json()
        created = user.get("created_at")
        age_years = None
        if created:
            cdt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_years = round((datetime.now(timezone.utc) - cdt).days / 365.25, 1)
        r = httpx.get(f"{GITHUB_API}/users/{handle}/repos",
                      headers=headers, params={"per_page": 100, "sort": "pushed"}, timeout=15)
        r.raise_for_status()
        langs = sorted({repo.get("language") for repo in r.json() if repo.get("language")})
        return json.dumps({"handle": handle, "account_age_years": age_years,
                           "public_repos": user.get("public_repos"), "languages": langs})
    except Exception as e:
        return json.dumps({"handle": handle, "error": f"GitHub lookup failed or user not found: {e}"})


def make_github_tool() -> Tool:
    return Tool(
        name="github_lookup",
        description="Look up a public GitHub account: returns account age (years), public repo count, "
                    "and the programming languages used across their repos. Use to sanity-check claimed "
                    "experience and skills. Input is a GitHub username or profile URL.",
        parameters={"type": "object",
                    "properties": {"handle": {"type": "string", "description": "GitHub username or profile URL"}},
                    "required": ["handle"]},
        fn=lambda handle: github_lookup(handle),
    )
