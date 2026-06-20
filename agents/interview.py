"""Problem 5 — Kohlpharma: Interview Copilot (for a non-technical hirer).

Boxes to check (from the customer brief):
  [x] from a job offer / role, generate RELEVANT interview questions
  [x] help a non-technical manager spot RED FLAGS in answers

Approach: Claude reads the job-offers PDF natively, lists the roles it finds so the
manager can pick one (or paste their own role text). For the chosen role we generate
6-10 interview questions grouped by competency (technical / problem-solving /
behavioural). Each question carries a plain-language "what a strong answer includes"
and a "red flag if…" note written FOR A NON-TECHNICAL interviewer, plus a standalone
red-flag checklist. Everything comes back as validated pydantic objects via
core.llm.extract so the page never hand-parses JSON.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from core import ingest, llm

# ---- schemas -------------------------------------------------------------

ROLES_SYSTEM = (
    "You read recruiting / job-offer documents. List every distinct open ROLE you find. "
    "Be faithful to the document — do not invent roles. If only one role is present, "
    "return just that one. Keep titles short and human."
)


class Role(BaseModel):
    """A single open role found in a job-offer document."""

    title: str = Field(description="Job title, e.g. 'Software Developer (Python)'")
    summary: str | None = Field(description="One short plain sentence on what the role is about")
    seniority: str | None = Field(description="e.g. 'Junior', 'Senior', 'Lead' — null if not stated")


class RoleList(BaseModel):
    """All open roles found in the job-offer document."""

    roles: list[Role] = Field(description="Every distinct open role found, in document order")


KIT_SYSTEM = (
    "You are an interview coach for a NON-TECHNICAL hiring manager. Given a role, you "
    "write a practical interview kit they can run even if they don't understand the "
    "technical details. Every question must be relevant to THIS role. For each question "
    "give a plain-English 'strong answer includes' and a 'red flag if' note — written so "
    "a non-technical person can tell a good answer from a weak one without expertise. "
    "Avoid jargon; when a technical term is unavoidable, explain it in one phrase. "
    "Produce 6 to 10 questions in total, spread across the competency areas."
)


class InterviewQuestion(BaseModel):
    """One interview question with non-technical evaluation guidance."""

    competency: str = Field(
        description="One of: 'Technical', 'Problem-solving', 'Behavioural'"
    )
    question: str = Field(description="The question to ask the candidate, in plain language")
    strong_answer: str = Field(
        description="What a strong answer includes, explained for a non-technical interviewer"
    )
    red_flag: str = Field(
        description="Red flag if… — a concrete warning sign a non-technical person can spot"
    )


class InterviewKit(BaseModel):
    """A complete, plain-language interview kit for one role."""

    role_title: str = Field(description="The role this kit is for")
    role_overview: str = Field(
        description="2-3 plain sentences: what this person will do and what 'good' looks like"
    )
    questions: list[InterviewQuestion] = Field(
        description="6-10 questions grouped by competency (Technical, Problem-solving, Behavioural)"
    )
    red_flag_checklist: list[str] = Field(
        description="Standalone checklist of general warning signs to watch for in ANY candidate"
    )
    confidence: float = Field(
        description="0-100: how confident you are the kit fits this specific role",
        ge=0,
        le=100,
    )


# ---- public API ----------------------------------------------------------

COMPETENCY_ORDER = ["Technical", "Problem-solving", "Behavioural"]


def list_roles(file: str | Path) -> RoleList:
    """Read a job-offer document and list the open roles it contains."""
    blocks = ingest.file_to_blocks(file)
    blocks.append(
        {"type": "text", "text": "List every distinct open role in this document."}
    )
    return llm.extract(RoleList, blocks, system=ROLES_SYSTEM)


def build_kit(role_text: str) -> InterviewKit:
    """Generate a plain-language interview kit for the given role description/title.

    `role_text` may be a short title, a full job-offer paste, or a title + summary.
    """
    prompt = (
        "Create an interview kit a non-technical manager can run for this role.\n\n"
        f"ROLE:\n{role_text.strip()}\n\n"
        "Give 6-10 questions total, mixing Technical, Problem-solving and Behavioural "
        "competencies. For every question include a plain 'strong answer includes' and a "
        "'red flag if' note. Also give a short standalone red-flag checklist of general "
        "warning signs that apply to any candidate."
    )
    return llm.extract(InterviewKit, prompt, system=KIT_SYSTEM)


def role_to_text(role: Role) -> str:
    """Flatten a Role into the free-text `build_kit` expects."""
    parts = [role.title]
    if role.seniority:
        parts.append(f"Seniority: {role.seniority}")
    if role.summary:
        parts.append(role.summary)
    return "\n".join(parts)


def kit_from_file(file: str | Path) -> tuple[RoleList, InterviewKit]:
    """One-shot pipeline for a single upload/click.

    Reads a job-offer document, picks the primary (first) open role it finds, and
    builds the interview kit for it. Exactly two LLM calls (list roles + build kit).
    Returns both the full role list (so the UI can show what was found) and the kit.
    """
    roles = list_roles(file)
    primary = roles.roles[0] if roles.roles else None
    role_text = role_to_text(primary) if primary else "Unspecified role from an uploaded job offer."
    kit = build_kit(role_text)
    return roles, kit


def group_by_competency(kit: InterviewKit) -> dict[str, list[InterviewQuestion]]:
    """Group a kit's questions by competency, in a stable display order."""
    groups: dict[str, list[InterviewQuestion]] = {}
    for q in kit.questions:
        groups.setdefault(q.competency, []).append(q)
    # order known competencies first, then any extras the model produced
    ordered = {k: groups[k] for k in COMPETENCY_ORDER if k in groups}
    for k, v in groups.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


def kit_to_markdown(kit: InterviewKit) -> str:
    """Render the kit as a clean, printable markdown document for download."""
    lines: list[str] = []
    lines.append(f"# Interview Kit — {kit.role_title}")
    lines.append("")
    lines.append("_Prepared for a non-technical hiring manager._")
    lines.append("")
    lines.append("## About this role")
    lines.append(kit.role_overview)
    lines.append("")
    lines.append("## Interview questions")
    for competency, qs in group_by_competency(kit).items():
        lines.append("")
        lines.append(f"### {competency}")
        for i, q in enumerate(qs, 1):
            lines.append("")
            lines.append(f"**{i}. {q.question}**")
            lines.append("")
            lines.append(f"- ✅ Strong answer includes: {q.strong_answer}")
            lines.append(f"- 🚩 Red flag if: {q.red_flag}")
    lines.append("")
    lines.append("## Red-flag checklist (any candidate)")
    for item in kit.red_flag_checklist:
        lines.append(f"- [ ] {item}")
    lines.append("")
    return "\n".join(lines)
