"""P6 Dr. Theiss — Reel Studio API routes (authenticated, tenant-scoped, STATELESS).

Storyboard-first: write_script → render the 1080×1920 safe-zone frames with PIL (fast)
→ return them as base64 data URLs (no static-file serving, no DB). A full gTTS + ffmpeg
MP4 is attempted only when quick and available, hard-timeboxed; on any failure the page
falls back to the storyboard gracefully. The safe-zone respect is drawn ON the frames so
the acceptance box ("text inside TikTok/IG safe zones") is visibly demonstrated.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile

from agents import reels as agent
from core import config
from core.auth import Principal, current_principal

router = APIRouter(prefix="/agents/reels", tags=["reels"])


@router.post("")
async def run_reels(
    file: UploadFile | None = File(default=None),
    try_video: bool = Form(True),
    principal: Principal = Depends(current_principal),
) -> dict:
    """Generate a vertical safe-zone reel storyboard for the tenant.

    Uses the uploaded brief/catalogue if provided, otherwise the bundled Dr. Theiss
    Allgäuer Latschenkiefer data pack. Tenant-scoped via the principal (no persistence).
    """
    if file is not None and (file.filename or ""):
        data = await file.read()
        suffix = Path(file.filename or "brief.pdf").suffix or ".pdf"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            src: str = tmp.name
        try:
            board = agent.build_storyboard(src, try_video=try_video)
        finally:
            Path(src).unlink(missing_ok=True)
    else:
        board = agent.build_storyboard(config.PATHS["theiss"], try_video=try_video)

    payload = board.model_dump()
    # web-friendly shape (matches web/src/lib/api/reels.ts)
    payload["video"] = payload.pop("video_data_url", None)
    return payload
