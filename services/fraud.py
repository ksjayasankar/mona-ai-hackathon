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
                          ai_writing_signals, cert_signals, consistency_signals, cross_signals,
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


# --------------------------------------------------------------------------- #
# Extraction (LLM vision) — kept thin; reuses the agents/fraud.py models.
# --------------------------------------------------------------------------- #
CV_EXTRACT_SYSTEM = A.CV_EXTRACT_SYSTEM
CERT_SYSTEM = A.CERT_SYSTEM
METHODOLOGY = (
    "These are SIGNALS to help a human recruiter decide — never an automated accept/reject. "
    "The AI-writing likelihood is a WEAK, capped hint: style-based AI detection is unreliable and "
    "over-flags polished or non-native English writers, so we never reject on it and you should "
    "weight it lightly. Image forensics (ELA) is weak and capped the same way. Low-level document "
    "checks live under 'Technical checks' for a security reviewer — skip them if they don't help you."
)


def _extract_cv(blocks: list[dict], provider: str | None) -> CVClaims:
    payload = blocks + [{"type": "text", "text":
                         "Extract the candidate's name, email, GitHub URL/handle, roles (with dates as "
                         "written), skills, languages and summary. Also copy a verbatim writing_sample "
                         "(the summary plus the 2-3 most descriptive sentences) and give a CALIBRATED "
                         "ai_writing_likelihood (0-100) with concrete reasons — be fair: polished or "
                         "non-native English is NOT evidence of AI; only flag uniform, generic, "
                         "specifics-free phrasing."}]
    return llm.extract(CVClaims, payload, system=CV_EXTRACT_SYSTEM, provider=provider)


def _extract_cert(blocks: list[dict], provider: str | None) -> CertFields:
    payload = blocks + [{"type": "text", "text":
                         "Extract the certificate fields and judge whether it looks genuine."}]
    return llm.extract(CertFields, payload, system=CERT_SYSTEM, provider=provider)


def _cert_summary(filename: str, c: CertFields, today: date) -> dict:
    vu = A._parse_date(c.valid_until)
    days = (vu - today).days if vu else None
    if not c.is_certificate:
        decision = "NOT_A_CERTIFICATE"
    elif not c.is_genuine_looking:
        decision = "SUSPECT"
    elif vu is None:
        decision = "NO_EXPIRY"
    elif days is not None and days >= 0:
        decision = "GENUINE_CURRENT"
    else:
        decision = "GENUINE_EXPIRED"
    return {"filename": filename, "decision": decision, "issuer": c.issuer, "title": c.title,
            "holder_name": c.holder_name, "valid_until": c.valid_until, "days_remaining": days,
            "is_current": (decision in ("GENUINE_CURRENT", "NO_EXPIRY"))}


class FraudReport(BaseModel):
    candidate_name: str | None
    risk: str
    score: int
    summary: str
    signals: list[Signal]
    by_category: dict[str, list[dict]]
    cert_summaries: list[dict]
    extraction: dict
    verify_ran: bool
    methodology_note: str
    llm_calls: int = 0
    agent_steps: int = 0


def build_report(*, claims: CVClaims, cert_fields: list[CertFields], forensic_signals: list[Signal],
                 verify_findings: VerifyFindings | None, today: date = TODAY,
                 verify_ran: bool = False, llm_calls: int = 0, agent_steps: int = 0) -> FraudReport:
    """PURE assembly: combine all signal sources, score, group for the UI."""
    signals: list[Signal] = list(forensic_signals)
    signals += consistency_signals(claims, today=today)
    signals += cross_signals(claims, cert_fields)
    for c in cert_fields:
        signals += cert_signals(c, today=today)
    inj_texts = [claims.summary or ""] + claims.skills + [r.title or "" for r in claims.roles]
    signals += injection_signals(inj_texts)
    signals += ai_writing_signals(claims)
    if verify_findings is not None:
        signals += findings_to_signals(verify_findings)

    assessment: RiskAssessment = score_risk(signals)
    by_category: dict[str, list[dict]] = {}
    for s in assessment.signals:
        by_category.setdefault(s.category, []).append(s.model_dump())
    cert_summaries = [_cert_summary(f"certificate_{i+1}", c, today) for i, c in enumerate(cert_fields)]
    return FraudReport(
        candidate_name=claims.candidate_name, risk=assessment.risk, score=assessment.score,
        summary=assessment.summary, signals=assessment.signals, by_category=by_category,
        cert_summaries=cert_summaries, extraction=claims.model_dump(), verify_ran=verify_ran,
        methodology_note=METHODOLOGY, llm_calls=llm_calls, agent_steps=agent_steps)


# --------------------------------------------------------------------------- #
# Full orchestration (LLM + network) — used by the API, NOT by the offline tests.
# --------------------------------------------------------------------------- #
def _claimed_years(claims: CVClaims) -> float | None:
    spans = []
    for r in claims.roles:
        s, _ = A._parse_month(r.start, today=TODAY)
        e, _ = A._parse_month(r.end, today=TODAY)
        if s and e and e >= s:
            spans.append((e - s).days / 365.25)
    return round(sum(spans), 1) if spans else None


def _run_verify(claims: CVClaims, github_handle: str | None,
                provider: str | None) -> tuple[VerifyFindings | None, int, int]:
    handle = parse_github_handle(github_handle) or parse_github_handle(claims.github)
    if not handle:
        return None, 0, 0
    tools = [make_github_tool(),
             Tool(name="web_search",
                  description="Search the web to check an employer/company or role exists.",
                  parameters={"type": "object", "properties": {"query": {"type": "string"}},
                              "required": ["query"]},
                  fn=lambda query: web_search(query))]
    years = _claimed_years(claims)
    user = (
        f"Verify this candidate. GitHub handle: {handle}. Claimed skills: {', '.join(claims.skills) or 'none'}. "
        f"Roughly {years or '?'} years of claimed experience. Employers: "
        f"{', '.join(r.employer for r in claims.roles if r.employer) or 'none'}.\n"
        "1) Call github_lookup(handle) — compare account age to claimed experience and languages to claimed skills.\n"
        "2) For up to two employers, call web_search to check they exist.\n"
        "Then report findings as structured data. Be fair: missing public evidence is NOT proof of fraud.")
    agent = run_agent(guard.SAFE_SYSTEM + " You verify a candidate's public footprint.",
                      user, tools, schema=VerifyFindings, max_steps=5, provider=provider)
    findings = agent.data if isinstance(agent.data, VerifyFindings) else None
    if findings is not None and findings.claimed_experience_years is None:
        findings.claimed_experience_years = years
    return findings, agent.llm_calls, agent.steps


def assess(*, tenant_id: str, cv: tuple[str, bytes] | None = None,
           certs: list[tuple[str, bytes]] | None = None, github_handle: str | None = None,
           links: list[str] | None = None, provider: str | None = None,
           run_verify: bool = True) -> FraudReport:
    certs = certs or []
    forensic: list[Signal] = []
    claims = CVClaims(candidate_name=None, roles=[], skills=[], summary=None, languages=[],
                      extraction_confidence=0.0)
    if cv:
        name, data = cv
        forensic += analyze_document(data, Path(name).suffix, filename=name)
        claims = _extract_cv(ingest.bytes_to_blocks(data, Path(name).suffix, name), provider)
    cert_fields: list[CertFields] = []
    for name, data in certs:
        forensic += analyze_document(data, Path(name).suffix, filename=name)
        cert_fields.append(_extract_cert(ingest.bytes_to_blocks(data, Path(name).suffix, name), provider))

    findings, vcalls, vsteps = (None, 0, 0)
    if run_verify:
        try:
            findings, vcalls, vsteps = _run_verify(claims, github_handle, provider)
        except Exception as e:  # verification is best-effort; never fail the whole assessment
            log.warning("verify loop failed: %s", e)

    report = build_report(claims=claims, cert_fields=cert_fields, forensic_signals=forensic,
                          verify_findings=findings, verify_ran=findings is not None,
                          llm_calls=(1 if cv else 0) + len(cert_fields) + vcalls, agent_steps=vsteps)
    persist(tenant_id, report, claims, cert_fields)
    return report


def persist(tenant_id: str, report: FraudReport, claims: CVClaims, cert_fields: list[CertFields]) -> str:
    with Session(engine) as s:
        cand = Candidate(tenant_id=tenant_id, name=claims.candidate_name, email=claims.email,
                         github=parse_github_handle(claims.github))
        s.add(cand)
        s.commit()
        s.refresh(cand)
        for i, c in enumerate(cert_fields):
            summ = report.cert_summaries[i] if i < len(report.cert_summaries) else {}
            s.add(Certificate(tenant_id=tenant_id, candidate_id=cand.id, issuer=c.issuer, title=c.title,
                              issue_date=c.issue_date, valid_until=c.valid_until,
                              is_genuine=c.is_genuine_looking, is_current=summ.get("is_current")))
        rec = VerificationRecord(tenant_id=tenant_id, candidate_id=cand.id, kind="cv",
                                 risk=report.risk, score=float(report.score),
                                 flags=[s_.name for s_ in report.signals], report=report.model_dump())
        s.add(rec)
        s.add(AuditLog(tenant_id=tenant_id, action="fraud.assessed", severity="info",
                       detail={"risk": report.risk, "score": report.score, "signals": len(report.signals)}))
        s.commit()
        s.refresh(rec)
        return rec.id


def history(tenant_id: str, limit: int = 20) -> list[dict]:
    with Session(engine) as s:
        rows = s.exec(select(VerificationRecord).where(VerificationRecord.tenant_id == tenant_id)
                      .order_by(desc(VerificationRecord.created_at)).limit(limit)).all()
        return [{"id": r.id, "created_at": r.created_at.isoformat(), "risk": r.risk,
                 "score": r.score, "candidate_name": r.report.get("candidate_name"),
                 "flags": r.flags} for r in rows]


def get_record(tenant_id: str, record_id: str) -> dict | None:
    with Session(engine) as s:
        r = s.get(VerificationRecord, record_id)
        if not r or r.tenant_id != tenant_id:
            return None
        return {"id": r.id, "created_at": r.created_at.isoformat(), "risk": r.risk,
                "score": r.score, "report": r.report}
