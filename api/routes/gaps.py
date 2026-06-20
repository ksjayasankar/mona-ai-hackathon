"""P9 Dr. Theiss — Competitive Gap Agent API route (authenticated, tenant-scoped).

Stateless by design: no DB. One endpoint benchmarks Allgäuer Latschenkiefer's product
set against the competitor landscape and returns the ranked white-space gaps.

The agent ingests the Dr. Theiss data pack (a vision PDF that auto-routes to Gemini,
which is daily-capped), so this route runs the analysis once per request and returns the
full GapResult. The caller may upload their own catalogue; otherwise PATHS["theiss"] (the
sample data pack) is used so the page is demoable with a single click.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from agents.gaps import run_gap_analysis
from core.auth import Principal, current_principal
from core.config import PATHS

router = APIRouter(prefix="/agents/gaps", tags=["gaps"])


@router.post("")
async def run_gaps(
    file: UploadFile | None = File(default=None),
    principal: Principal = Depends(current_principal),
) -> dict:
    """Benchmark the product set vs competitors → ranked white-space gaps.

    With no upload, runs on the bundled Dr. Theiss data pack (PATHS["theiss"]).
    Tenant-scoped via current_principal; stateless (nothing persisted).
    """
    # Upload path: write to a temp file so ingest can detect the suffix natively.
    if file is not None:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty file")
        suffix = Path(file.filename or "upload.pdf").suffix or ".pdf"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(data)
            tmp.flush()
            tmp.close()
            result = run_gap_analysis(tmp.name)
        finally:
            Path(tmp.name).unlink(missing_ok=True)
    else:
        pack = PATHS["theiss"]
        if not Path(pack).exists():
            raise HTTPException(status_code=404, detail="Sample data pack not found on server")
        result = run_gap_analysis(pack)

    return {"tenant_id": principal.tenant_id, **result.model_dump()}
