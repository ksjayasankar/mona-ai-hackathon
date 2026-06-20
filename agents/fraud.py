"""Problem 4 — Persowerk: CV & Certificate Authenticity Agent.

Boxes to check (from the customer brief):
  [x] verify real work history & skills plausibility from a CV
  [x] FLAG AI-generated / fabricated / misrepresented content + a fraud-risk score
  [x] confirm certificates are valid and CURRENT (issuer, date, expiry)

Approach (mirrors the golden permits.py template): Claude reads the document
natively (PDF or photo), we extract structured fields with core.llm.extract, then a
small deterministic post-rule turns those fields into a calibrated, plain-language
verdict so the result doesn't depend on the model's mood.

Two flows:
  - CV authenticity: extract the claims (roles/dates/skills), then a second pass
    scores authenticity (date consistency, AI-writing signals, skill plausibility).
  - Certificate check: extract issuer/holder/dates, decide genuine-looking and (the
    box that matters for Persowerk) whether it is still CURRENT vs TODAY.

We treat the document text as untrusted, so the guard wrapping/system prompt protects
against a CV that tries to instruct the checker ("ignore previous instructions…").
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from core import guard, ingest, llm
from core.tools.forensics import Signal

TODAY = date(2026, 6, 20)  # hackathon "today"; keep deterministic for the demo

# --------------------------------------------------------------------------- #
# CV authenticity
# --------------------------------------------------------------------------- #

CV_EXTRACT_SYSTEM = (
    "You are a recruiting analyst reading a candidate CV / résumé. Extract the work "
    "history, skills and summary exactly as written. Do not invent values; use null "
    "when a field is not present. Read dates as written (e.g. 'MM/YYYY' or 'YYYY'). "
    + guard.SAFE_SYSTEM
)

CV_SCORE_SYSTEM = (
    "You are a fraud analyst assessing whether a CV is authentic or AI-generated / "
    "fabricated / misrepresented. Be calibrated and fair, NOT alarmist: a clean, "
    "well-written CV is normal and should score LOW. Only raise risk for concrete, "
    "explainable signals. For every flag, state the specific evidence (the actual "
    "phrase, the impossible date range, the role/skill mismatch) so a non-technical "
    "recruiter understands WHY it is a flag. "
    + guard.SAFE_SYSTEM
)


class CVRole(BaseModel):
    """One position in the candidate's work history."""

    title: str | None = Field(description="Job title")
    employer: str | None = Field(description="Company / organisation")
    start: str | None = Field(description="Start date as written, e.g. '03/2019'")
    end: str | None = Field(description="End date as written, or 'present'")
    achievements_specific: bool | None = Field(
        description="True if this role lists concrete, specific achievements (numbers, named projects), "
        "False if only vague generic duties"
    )


class CVClaims(BaseModel):
    """Structured claims read off a CV / résumé."""

    candidate_name: str | None = Field(description="Candidate's full name")
    roles: list[CVRole] = Field(description="Work-history entries, most recent first")
    skills: list[str] = Field(description="Skills / technologies the candidate claims")
    summary: str | None = Field(description="The CV's profile/summary paragraph, verbatim")
    languages: list[str] = Field(default_factory=list, description="Spoken languages claimed")
    email: str | None = Field(default=None, description="Candidate email if present")
    github: str | None = Field(default=None, description="GitHub URL or handle if present on the CV")
    writing_sample: str | None = Field(
        default=None,
        description="Verbatim representative prose from the CV (the summary plus 2-3 of the most "
        "descriptive sentences), used to assess writing style. Copy exactly, do not paraphrase.")
    ai_writing_likelihood: int | None = Field(
        default=None, ge=0, le=100,
        description="CALIBRATED estimate (0-100) that the prose was AI-generated. Be FAIR: polished "
        "or non-native English is NOT evidence of AI. Only raise it for uniform, generic, "
        "specifics-free phrasing. Leave null if unsure.")
    ai_writing_reasons: list[str] = Field(
        default_factory=list, description="Concrete cues behind ai_writing_likelihood. Empty if none.")
    extraction_confidence: float = Field(
        description="0-100, how legible/complete the CV was", ge=0, le=100
    )


class CVAuthScore(BaseModel):
    """Authenticity assessment of a CV (second LLM pass)."""

    fraud_risk: str = Field(description="One of: LOW, MEDIUM, HIGH")
    risk_score: int = Field(description="0-100, higher = more likely fabricated/AI-generated", ge=0, le=100)
    ai_writing_signals: list[str] = Field(
        description="Concrete AI-writing / generic-phrasing signals, each with the evidence. Empty if none."
    )
    consistency_flags: list[str] = Field(
        description="Concrete timeline problems: overlapping/impossible dates, unexplained gaps. Empty if none."
    )
    plausibility_flags: list[str] = Field(
        description="Skill/role plausibility issues: claims that don't fit the seniority/role. Empty if none."
    )
    positive_signals: list[str] = Field(
        description="Reasons the CV looks authentic (specific achievements, coherent timeline). Empty if none."
    )
    rationale: str = Field(description="One-paragraph plain-language summary of the verdict")


class CVResult(BaseModel):
    """Final CV verdict surfaced to the recruiter."""

    fraud_risk: str
    risk_score: int
    confidence: float
    claims: CVClaims
    score: CVAuthScore
    reasons: list[str]
    injection_note: str | None = None


def analyze_cv(file: str | Path) -> CVResult:
    """Read one CV file and return an authenticity verdict."""
    blocks = ingest.file_to_blocks(file)

    # Pass 1 — extract the claims.
    extract_blocks = blocks + [
        {"type": "text", "text": "Extract the candidate's roles, skills, summary and languages."}
    ]
    claims = llm.extract(CVClaims, extract_blocks, system=CV_EXTRACT_SYSTEM)

    # Cheap injection pre-scan over the text the model saw (summary is the usual vector).
    scan_text = " ".join(
        [claims.summary or ""] + claims.skills + [r.title or "" for r in claims.roles]
    )
    inj = guard.scan(scan_text)
    injection_note = None
    if inj["risk"] != "low":
        injection_note = (
            f"Possible prompt-injection text inside the CV ({inj['risk']} risk): "
            + ", ".join(inj["hits"])
            + " — neutralised; treat as a strong fraud flag."
        )

    # Pass 2 — score authenticity. Feed the extracted claims back as wrapped DATA.
    score_payload = guard.wrap(claims.model_dump_json(indent=2))
    score_blocks = [
        {
            "type": "text",
            "text": (
                "Assess this candidate's CV for authenticity. Check three things and give "
                "the concrete evidence for each flag:\n"
                "1) Internal consistency — overlapping or impossible date ranges, large "
                "unexplained gaps.\n"
                "2) AI-writing / fabrication signals — generic buzzword density, suspiciously "
                "uniform phrasing, vague achievements with no specifics.\n"
                "3) Skill/role plausibility — do the claimed skills fit the roles and seniority?\n"
                "Score LOW unless there is real evidence. CV data follows:\n\n"
                + score_payload
            ),
        }
    ]
    score = llm.extract(CVAuthScore, score_blocks, system=CV_SCORE_SYSTEM)

    # Deterministic post-rule: keep the band and the score in agreement, and let an
    # injection attempt force the risk up (the model can't be allowed to wave it off).
    risk = (score.fraud_risk or "").upper()
    rscore = int(max(0, min(100, score.risk_score)))
    if risk not in ("LOW", "MEDIUM", "HIGH"):
        risk = "HIGH" if rscore >= 67 else "MEDIUM" if rscore >= 34 else "LOW"
    # Re-band from the numeric score so the badge and the number never disagree.
    risk = "HIGH" if rscore >= 67 else "MEDIUM" if rscore >= 34 else "LOW"
    if injection_note:
        rscore = max(rscore, 80)
        risk = "HIGH"

    reasons: list[str] = []
    if injection_note:
        reasons.append(injection_note)
    for f in score.consistency_flags:
        reasons.append(f"Timeline: {f}")
    for f in score.ai_writing_signals:
        reasons.append(f"AI/fabrication signal: {f}")
    for f in score.plausibility_flags:
        reasons.append(f"Plausibility: {f}")
    for s in score.positive_signals:
        reasons.append(f"✓ {s}")
    if not reasons:
        reasons.append("No specific fraud signals found — CV reads as authentic.")

    # Confidence = how sure we are of the verdict; anchored on legibility of the read.
    confidence = round(min(95.0, 0.5 * 90 + 0.5 * claims.extraction_confidence), 1)

    return CVResult(
        fraud_risk=risk,
        risk_score=rscore,
        confidence=confidence,
        claims=claims,
        score=score,
        reasons=reasons,
        injection_note=injection_note,
    )


# --------------------------------------------------------------------------- #
# Certificate check
# --------------------------------------------------------------------------- #

CERT_SYSTEM = (
    "You are a credential-verification analyst examining a scanned certificate / "
    "diploma / licence (often in German: Zertifikat, Zeugnis, Lizenz, Ausbildung). "
    "Extract the printed fields exactly; use null when a field is absent. Then judge "
    "whether the document LOOKS genuine (consistent layout, seal/signature, correct "
    "issuer branding) versus showing forgery or AI-generation signs (warped text, "
    "inconsistent fonts, fabricated issuer, impossible dates). Be calibrated, not "
    "alarmist: most real certificates have no expiry, and that is fine. Read dates in "
    "DD.MM.YYYY or YYYY format. "
    + guard.SAFE_SYSTEM
)


class CertFields(BaseModel):
    """Fields read off a certificate / diploma / licence."""

    is_certificate: bool = Field(description="True if this is a certificate/diploma/licence document")
    cert_type: str | None = Field(description="What kind, e.g. 'ISACA BSIG certificate', 'Bachelor diploma'")
    issuer: str | None = Field(description="Issuing body / institution")
    holder_name: str | None = Field(description="Name of the person it was issued to")
    title: str | None = Field(description="The qualification/title awarded")
    issue_date: str | None = Field(description="Issue date as printed")
    valid_until: str | None = Field(description="Expiry / 'valid until' date, or null if none stated")
    is_genuine_looking: bool = Field(description="True if the document looks authentic")
    forgery_signals: list[str] = Field(
        description="Concrete forgery / AI-generation signs with evidence. Empty if none."
    )
    extraction_confidence: float = Field(description="0-100, how legible/certain the read was", ge=0, le=100)
    notes: str | None = Field(description="Anything else notable")


class CertResult(BaseModel):
    """Final certificate verdict surfaced to the recruiter."""

    decision: str  # GENUINE_CURRENT | GENUINE_EXPIRED | NO_EXPIRY | SUSPECT | NOT_A_CERTIFICATE
    is_current: bool | None
    confidence: float
    valid_until: str | None
    days_remaining: int | None
    fields: CertFields
    reasons: list[str]


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%Y", "%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def check_certificate(file: str | Path) -> CertResult:
    """Read one certificate file and return a validity verdict."""
    blocks = ingest.file_to_blocks(file)
    blocks.append(
        {"type": "text", "text": "Extract the certificate fields and judge whether it looks genuine."}
    )
    f = llm.extract(CertFields, blocks, system=CERT_SYSTEM)

    reasons: list[str] = []
    if not f.is_certificate:
        return CertResult(
            decision="NOT_A_CERTIFICATE",
            is_current=None,
            confidence=round(f.extraction_confidence, 1),
            valid_until=None,
            days_remaining=None,
            fields=f,
            reasons=["Document does not look like a certificate/diploma/licence."]
            + ([f.notes] if f.notes else []),
        )

    valid_until = _parse_date(f.valid_until)
    days = (valid_until - TODAY).days if valid_until else None

    # Decision: forgery first, then currency.
    if not f.is_genuine_looking or len(f.forgery_signals) >= 2:
        decision, base, is_current = "SUSPECT", 80.0, None
        reasons.append("Document shows forgery / AI-generation signs (see flags).")
    elif valid_until is None:
        decision, base, is_current = "NO_EXPIRY", 85.0, True
        reasons.append("No expiry date printed — certificate does not expire (normal for diplomas).")
    elif days is not None and days >= 0:
        decision, base, is_current = "GENUINE_CURRENT", 90.0, True
        reasons.append(f"Currently valid — expires {f.valid_until} ({days} days remaining).")
    else:
        decision, base, is_current = "GENUINE_EXPIRED", 90.0, False
        reasons.append(f"EXPIRED on {f.valid_until} ({abs(days)} days ago) — no longer current.")

    if f.issuer:
        reasons.append(f"Issued by {f.issuer}.")
    for fs in f.forgery_signals:
        reasons.append(f"Forgery signal: {fs}")
    if f.notes:
        reasons.append(f.notes)

    confidence = round(min(base, 0.5 * base + 0.5 * f.extraction_confidence), 1)
    return CertResult(
        decision=decision,
        is_current=is_current,
        confidence=confidence,
        valid_until=f.valid_until,
        days_remaining=days,
        fields=f,
        reasons=reasons,
    )


# --------------------------------------------------------------------------- #
# Deterministic signal engines (no LLM) — the testable substance of P4.
# These power the productized service; the legacy analyze_cv/check_certificate
# above stay for the Streamlit prototype.
# --------------------------------------------------------------------------- #
_PRESENT = {"present", "current", "now", "heute", "ongoing", "till date", "to date"}


def _parse_month(s: str | None, *, today: date) -> tuple[date | None, bool]:
    """Parse a CV date as written. Returns (date, is_present_keyword)."""
    if not s:
        return None, False
    t = s.strip().lower()
    if any(p in t for p in _PRESENT):
        return today, True
    for fmt in ("%m/%Y", "%Y-%m", "%m.%Y", "%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date().replace(day=1), False
        except ValueError:
            continue
    m = re.search(r"(19|20)\d{2}", t)
    if m:
        return date(int(m.group(0)), 1, 1), False
    return None, False


def _fmt(role: CVRole) -> str:
    return f"'{role.title or role.employer or '?'}' ({role.start or '?'}–{role.end or '?'})"


def consistency_signals(claims: CVClaims, *, today: date = TODAY) -> list[Signal]:
    """Timeline analysis: overlaps, large gaps, impossible/future dates. All deterministic."""
    out: list[Signal] = []
    parsed = []
    for r in claims.roles:
        s, _ = _parse_month(r.start, today=today)
        e, is_present = _parse_month(r.end, today=today)
        parsed.append((r, s, e, is_present))
        if s and e and e < s:
            out.append(Signal(name="impossible_dates", severity="medium", category="consistency",
                              evidence=f"Role {_fmt(r)} ends before it starts.",
                              why="An end date earlier than the start is internally impossible — likely a typo or fabrication."))
        for label, dt in (("start", s), ("end", None if is_present else e)):
            if dt and dt > today:
                out.append(Signal(name="future_dated", severity="medium", category="consistency",
                                  evidence=f"Role {_fmt(r)} has a {label} date in the future ({dt.year}).",
                                  why="A date after today cannot describe past employment."))

    # overlaps (>1 month) between any two datable roles
    datable = [(r, s, e) for (r, s, e, _p) in parsed if s and e]
    for i in range(len(datable)):
        for j in range(i + 1, len(datable)):
            (ra, sa, ea), (rb, sb, eb) = datable[i], datable[j]
            overlap_days = (min(ea, eb) - max(sa, sb)).days
            if overlap_days > 31:
                out.append(Signal(name="timeline_overlap", severity="medium", category="consistency",
                                  evidence=f"{_fmt(ra)} overlaps {_fmt(rb)} by ~{overlap_days // 30} month(s).",
                                  why="Concurrent full-time roles can be legitimate (freelance/part-time) but often "
                                      "indicate padding — confirm with the candidate."))

    # gaps > 12 months between consecutive (sorted by start) roles
    seq = sorted([(r, s, e) for (r, s, e, _p) in parsed if s and e], key=lambda x: x[1])
    for (ra, _sa, ea), (rb, sb, _eb) in zip(seq, seq[1:]):
        gap_days = (sb - ea).days
        if gap_days > 365:
            out.append(Signal(name="timeline_gap", severity="low", category="consistency",
                              evidence=f"~{gap_days // 30}-month gap between {_fmt(ra)} and {_fmt(rb)}.",
                              why="Unexplained gaps are common and rarely fraud, but worth a question in interview."))
    return out


def _norm_name(n: str | None) -> set[str]:
    return {t for t in re.split(r"\s+", (n or "").lower().strip()) if len(t) > 1}


def cross_signals(claims: CVClaims, certs: list[CertFields]) -> list[Signal]:
    """Cross-document: does the CV name match the certificate holder?"""
    out: list[Signal] = []
    cv_tokens = _norm_name(claims.candidate_name)
    if not cv_tokens:
        return out
    for c in certs:
        h_tokens = _norm_name(c.holder_name)
        if h_tokens and not (cv_tokens & h_tokens):
            out.append(Signal(name="name_mismatch", severity="medium", category="consistency",
                              evidence=f"CV name '{claims.candidate_name}' does not match certificate holder "
                                       f"'{c.holder_name}' on {c.cert_type or 'a certificate'}.",
                              why="A certificate issued to a different person may be borrowed or fabricated — verify identity."))
    return out


def cert_signals(cert: CertFields, *, today: date = TODAY) -> list[Signal]:
    """Certificate forgery + currency signals (deterministic over the extracted fields)."""
    out: list[Signal] = []
    if not cert.is_certificate:
        return out
    if not cert.is_genuine_looking:
        out.append(Signal(name="certificate_suspect", severity="high", category="certificate",
                          evidence=f"Document '{cert.title or cert.cert_type}' shows authenticity problems: "
                                   + "; ".join(cert.forgery_signals or ["model judged it not genuine-looking"]) + ".",
                          why="The visual layout/seal/fonts look inconsistent with a genuine credential — examine the original."))
    elif len(cert.forgery_signals or []) >= 2:
        out.append(Signal(name="certificate_suspect", severity="medium", category="certificate",
                          evidence="Multiple forgery hints: " + "; ".join(cert.forgery_signals) + ".",
                          why="Several small anomalies together warrant a manual look."))
    vu = _parse_date(cert.valid_until)
    if vu and vu < today:
        out.append(Signal(name="certificate_expired", severity="medium", category="certificate",
                          evidence=f"Certificate '{cert.title or cert.cert_type}' expired on {cert.valid_until} "
                                   f"({(today - vu).days} days ago).",
                          why="An expired credential does not meet a 'valid & current' requirement."))
    return out


# --------------------------------------------------------------------------- #
# Risk scoring — weighted, deterministic, calibrated NOT alarmist. Output is a
# SIGNAL summary for a recruiter, never an auto-reject.
# --------------------------------------------------------------------------- #
_BASE = {"high": 0.60, "medium": 0.30, "low": 0.12}
_WEAK_MULT = 0.40
_WEAK_CAP = 0.15  # all weak signals together can lift at most this much


def _noisy_or(contribs: list[float]) -> float:
    p = 1.0
    for c in contribs:
        p *= (1.0 - max(0.0, min(1.0, c)))
    return 1.0 - p


class RiskAssessment(BaseModel):
    risk: str
    score: int
    signals: list[Signal]
    summary: str


def score_risk(signals: list[Signal]) -> RiskAssessment:
    strong = [_BASE.get(s.severity, 0.0) for s in signals if not s.weak]
    weak = [_BASE.get(s.severity, 0.0) * _WEAK_MULT for s in signals if s.weak]
    p_strong = _noisy_or(strong)
    p_weak = min(_WEAK_CAP, _noisy_or(weak))
    p = 1.0 - (1.0 - p_strong) * (1.0 - p_weak)
    score = round(100 * p)

    # weak/low evidence can lift within a band but never CREATE a HIGH
    if p_strong < 0.67:
        score = min(score, 66)

    # an injection attempt embedded in the CV is a concrete, strong fraud flag
    if any(s.category == "injection" and s.severity == "high" for s in signals):
        score = max(score, 85)

    risk = "HIGH" if score >= 67 else "MEDIUM" if score >= 34 else "LOW"
    by_sev = {k: sum(1 for s in signals if s.severity == k and not s.weak) for k in ("high", "medium", "low")}
    if not signals:
        summary = "No fraud signals detected — the documents read as authentic. (A clean result is normal.)"
    else:
        summary = (f"{risk} risk ({score}/100): {by_sev['high']} high, {by_sev['medium']} medium, "
                   f"{by_sev['low']} low signal(s). These are SIGNALS for a recruiter to review — not an automated verdict.")
    return RiskAssessment(risk=risk, score=score, signals=signals, summary=summary)


# --------------------------------------------------------------------------- #
# Verification findings (from the core.agent tool-loop) -> signals.
# Absence of evidence stays WEAK/low — we never reject on "not found online".
# --------------------------------------------------------------------------- #
class VerifyFindings(BaseModel):
    """Structured result of the github/web verification agent loop."""

    github_account_age_years: float | None = Field(default=None)
    github_languages: list[str] = Field(default_factory=list)
    claimed_experience_years: float | None = Field(default=None)
    skills_not_found: list[str] = Field(default_factory=list, description="claimed skills with no public evidence")
    company_web_findings: list[str] = Field(default_factory=list, description="short notes on employer web checks")
    notes: str | None = Field(default=None)


def findings_to_signals(f: VerifyFindings) -> list[Signal]:
    out: list[Signal] = []
    if (f.github_account_age_years is not None and f.claimed_experience_years
            and f.github_account_age_years + 2 < f.claimed_experience_years):
        out.append(Signal(name="github_age_vs_claim", severity="medium", category="verification",
                          evidence=f"GitHub account is ~{f.github_account_age_years:.0f} year(s) old but the CV "
                                   f"claims ~{f.claimed_experience_years:.0f} years of experience.",
                          why="A much younger developer footprint than claimed seniority is worth probing — "
                              "though developers do work privately."))
    if f.skills_not_found:
        out.append(Signal(name="skills_unverified", severity="low", category="verification", weak=True,
                          evidence=f"Claimed skills with no public evidence: {', '.join(f.skills_not_found)}.",
                          why="WEAK: absence of public proof is not proof of absence (private/enterprise work). "
                              "Treat as a question, not a finding."))
    for note in f.company_web_findings:
        if "no results" in note.lower() or "not found" in note.lower():
            out.append(Signal(name="employer_unverified", severity="low", category="verification", weak=True,
                              evidence=note,
                              why="WEAK: small or non-English employers often have no web footprint."))
    return out


def injection_signals(texts: list[str]) -> list[Signal]:
    """Prompt-injection text inside a CV is a strong, concrete fraud flag."""
    out: list[Signal] = []
    for t in texts:
        scan = guard.scan(t or "")
        if scan["hits"]:
            out.append(Signal(name="prompt_injection", severity="high", category="injection",
                              evidence="Injection-style text embedded in the CV: " + ", ".join(scan["hits"]) + ".",
                              why="The document tries to instruct the screening system (e.g. 'ignore previous "
                                  "instructions'). Legitimate CVs never do this — strong tampering/fraud flag."))
            break
    return out


# --------------------------------------------------------------------------- #
# AI-writing likelihood — deterministic stylometry, optionally blended with the
# model's holistic read. DELIBERATELY surfaced as a WEAK, capped signal: style-based
# AI detection is unreliable and over-flags polished / non-native English writing, so
# it can never alone reach HIGH and the UI frames it as a hint, never a reject.
# --------------------------------------------------------------------------- #
_AI_LEXICON = [
    "results-driven", "results oriented", "detail-oriented", "detail oriented", "leverage",
    "leveraged", "cutting-edge", "cutting edge", "seamless", "synergy", "synergies",
    "passionate about", "spearheaded", "proven track record", "team player", "fast-paced",
    "fast paced", "robust", "comprehensive", "deliver value", "value-add", "innovative",
    "thrive", "thrives", "demonstrated ability", "strong work ethic", "self-starter",
    "go-getter", "stakeholder", "holistic", "best-in-class", "world-class", "game-changer",
    "empower", "tapestry", "underscore", "testament", "delve", "actionable insights",
    "mission-critical", "at the forefront", "commitment to excellence", "deep dive",
    "wide range of", "dynamic", "drive value", "driving synergy",
]


def ai_writing_heuristic(text: str) -> tuple[int, list[str]]:
    """Stylometric AI-likelihood (0-100) + concrete reasons. Deterministic, explainable."""
    import statistics

    text = text or ""
    words = re.findall(r"[A-Za-z']+", text)
    nw = len(words)
    if nw < 25:
        return 0, ["too little prose to assess writing style"]
    low = text.lower()
    reasons: list[str] = []
    score = 0

    lex = sum(low.count(k) for k in _AI_LEXICON)
    if lex:
        score += min(40, round(lex / nw * 100 * 8))
        reasons.append(f"{lex} generic buzzword/phrase(s)")

    em = text.count("—") + text.count(" – ")
    if em / nw * 100 > 0.8:
        score += min(20, round(em / nw * 100 * 12))
        reasons.append(f"em-dash overuse ({em} in {nw} words)")

    sents = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    lens = [len(s.split()) for s in sents]
    if len(lens) >= 4 and statistics.pstdev(lens) < 3.0:
        score += 15
        reasons.append("very uniform sentence length (low burstiness)")

    triads = len(re.findall(r"\b[\w-]+,\s+[\w-]+,?\s+and\s+[\w-]+", text))
    if triads:
        score += min(15, triads * 5)
        reasons.append(f"{triads} 'rule-of-three' list(s)")

    if re.search(r"\bnot (just|only)\b[^.]*\bbut\b", low):
        score += 10
        reasons.append("negative parallelism ('not just X but Y')")

    return min(100, score), reasons


def ai_writing_signals(claims: CVClaims) -> list[Signal]:
    """Blend the stylometric heuristic with the model's read (if any) into one WEAK signal."""
    text = (claims.writing_sample or claims.summary or "").strip()
    if len(text.split()) < 25:
        return []
    h_score, h_reasons = ai_writing_heuristic(text)
    model = claims.ai_writing_likelihood
    if model is not None:
        combined = round(0.5 * h_score + 0.5 * max(0, min(100, model)))
        reasons = list(claims.ai_writing_reasons) + h_reasons
    else:
        combined = h_score
        reasons = h_reasons
    if combined < 35:
        return []
    sev = "medium" if combined >= 60 else "low"
    top = "; ".join(dict.fromkeys(r for r in reasons if r)) or "stylometric cues"
    return [Signal(
        name="ai_generated_writing", severity=sev, category="writing", weak=True,
        evidence=f"AI-writing likelihood ~{combined}%. Indicators: {top}.",
        why="WEAK signal — shown to inform, never to reject. Style-based AI detection is unreliable "
            "and over-flags polished or non-native English writers, so we cap it and you should "
            "weight it lightly. Treat it as a prompt to read the prose closely, not as proof.")]
