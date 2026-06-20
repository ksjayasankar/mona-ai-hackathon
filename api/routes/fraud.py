"""P4 Persowerk — CV & certificate fraud-signals API (authenticated, tenant-scoped)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from core.auth import Principal, current_principal
from services import fraud as svc

router = APIRouter(prefix="/agents/fraud", tags=["fraud"])


@router.post("/assess")
async def run_assess(
    cv: UploadFile | None = File(default=None),
    certs: list[UploadFile] = File(default=[]),
    github_handle: str = Form(default=""),
    links: str = Form(default=""),
    run_verify: bool = Form(default=True),
    principal: Principal = Depends(current_principal),
) -> dict:
    cv_in = (cv.filename or "cv", await cv.read()) if cv is not None else None
    cert_in = [(c.filename or "certificate", await c.read()) for c in certs]
    link_list = [x.strip() for x in links.split(",") if x.strip()]
    report = svc.assess(tenant_id=principal.tenant_id, cv=cv_in, certs=cert_in,
                        github_handle=github_handle or None, links=link_list, run_verify=run_verify)
    return report.model_dump()


@router.get("/history")
def fraud_history(principal: Principal = Depends(current_principal)) -> list[dict]:
    return svc.history(principal.tenant_id)


@router.get("/records/{record_id}")
def fraud_record(record_id: str, principal: Principal = Depends(current_principal)) -> dict:
    rec = svc.get_record(principal.tenant_id, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return rec
