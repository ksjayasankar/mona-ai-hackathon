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

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from core import guard, ingest, llm

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
