"""P1 Globus — invoice-triage API routes (authenticated, tenant-scoped)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from core.auth import Principal, current_principal
from services import invoices as svc

router = APIRouter(prefix="/agents", tags=["invoices"])


@router.post("/invoices")
async def run_invoice_triage(
    email_body: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
    principal: Principal = Depends(current_principal),
) -> dict:
    """Simulated inbox: an email body + attachments → split, route, dedupe, persist."""
    attachments = [(f.filename or "upload", await f.read()) for f in files]
    report = svc.process(email_body, tenant_id=principal.tenant_id, attachment_files=attachments)
    return report.model_dump()


@router.get("/invoices/history")
def invoice_history(principal: Principal = Depends(current_principal)) -> list[dict]:
    return svc.history(principal.tenant_id)


@router.post("/invoices/approve")
def approve_invoice(
    invoice_id: str = Form(...),
    outcome: str = Form(default="approved"),
    note: str | None = Form(default=None),
    principal: Principal = Depends(current_principal),
) -> dict:
    """Record a human decision. The approver is the authenticated principal, not the client."""
    try:
        return svc.approve(principal.tenant_id, invoice_id,
                           approver=principal.email or principal.user_id,
                           outcome=outcome, note=note)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
