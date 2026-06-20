"""P10 Rheinmetall — secure-intake API routes (authenticated, tenant-scoped)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from core.auth import Principal, current_principal
from services import secure_intake as svc

router = APIRouter(prefix="/agents", tags=["secure-intake"])


@router.post("/secure-intake")
async def run_secure_intake(
    email_body: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    principal: Principal = Depends(current_principal),
) -> dict:
    attachments = [(f.filename or "upload", await f.read()) for f in files]
    report = svc.process(email_body, tenant_id=principal.tenant_id, attachment_files=attachments)
    return report.model_dump()


@router.get("/secure-intake/history")
def secure_intake_history(principal: Principal = Depends(current_principal)) -> list[dict]:
    return svc.history(principal.tenant_id)
