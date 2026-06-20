"""P5 Kohlpharma — Interview Copilot API route (authenticated, tenant-scoped).

Stateless: turns a job offer into role-relevant interview questions (grouped by
competency) plus a red-flag checklist. POST a file, or POST with no file to run on
the bundled sample job offer. Exactly two LLM calls per run.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile

from core.auth import Principal, current_principal
from services import interview as svc

router = APIRouter(prefix="/agents/interview", tags=["interview"])


@router.post("")
async def run_interview(
    file: UploadFile | None = File(default=None),
    principal: Principal = Depends(current_principal),
) -> dict:
    """Build an interview kit from the uploaded job offer, or the sample if none given."""
    if file is not None and file.filename:
        data = await file.read()
        if data:
            suffix = Path(file.filename).suffix or ".pdf"
            return svc.analyze_bytes(data, suffix, filename=file.filename)
    return svc.analyze_sample()
