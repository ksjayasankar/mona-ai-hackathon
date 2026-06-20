"""P5 Kohlpharma — Interview Copilot service (stateless; no DB, no persistence).

Thin orchestration over `agents.interview`:

    1. INGEST   read the job-offer document (Claude/Gemini reads PDFs natively)
    2. ROLES    list the open roles found                                  (1 LLM call)
    3. KIT      build a plain-language interview kit for the primary role  (1 LLM call)
    4. SHAPE    group questions by competency + attach the red-flag checklist

The agent stays the pure logic; this layer just turns its pydantic objects into the
flat JSON the web page consumes. Exactly two LLM calls per run — no loops.
"""
from __future__ import annotations

from pathlib import Path

from agents import interview as agent
from core import ingest, llm
from core.config import PATHS


def _kit_payload(roles: agent.RoleList, kit: agent.InterviewKit, source_note: str) -> dict:
    grouped = agent.group_by_competency(kit)
    competencies = [
        {
            "competency": name,
            "questions": [q.model_dump() for q in qs],
        }
        for name, qs in grouped.items()
    ]
    return {
        "source_note": source_note,
        "roles_found": [r.model_dump() for r in roles.roles],
        "role_title": kit.role_title,
        "role_overview": kit.role_overview,
        "confidence": kit.confidence,
        "question_count": len(kit.questions),
        "competencies": competencies,
        "red_flag_checklist": list(kit.red_flag_checklist),
    }


def analyze_bytes(data: bytes, suffix: str, *, filename: str | None = None) -> dict:
    """Run the copilot on an uploaded job-offer file."""
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    blocks = ingest.bytes_to_blocks(data, suffix)
    blocks.append({"type": "text", "text": "List every distinct open role in this document."})
    roles = llm.extract(agent.RoleList, blocks, system=agent.ROLES_SYSTEM)
    primary = roles.roles[0] if roles.roles else None
    role_text = agent.role_to_text(primary) if primary else "Unspecified role from an uploaded job offer."
    kit = agent.build_kit(role_text)
    note = f"Read from uploaded file '{filename}'." if filename else "Read from the uploaded job offer."
    return _kit_payload(roles, kit, note)


def analyze_sample() -> dict:
    """Run the copilot on the bundled sample job-offer PDF (PATHS['job_offers'])."""
    path = Path(PATHS["job_offers"])
    roles, kit = agent.kit_from_file(path)
    return _kit_payload(roles, kit, f"Read from the sample job offer ({path.name}).")
