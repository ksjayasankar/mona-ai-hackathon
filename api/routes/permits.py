"""P3 Leistenschneider — work-permit validation API (authenticated, tenant-scoped).

The system produces a RECOMMENDATION only. Below-threshold / implied-by-statute checks
land in GET /agents/permits/review-queue; a human confirms or overrides via
POST /agents/permits/{id}/review (recorded with reviewer + timestamp).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from core.auth import Principal, current_principal
from services import permits as svc

router = APIRouter(prefix="/agents", tags=["permits"])


class ReviewBody(BaseModel):
    outcome: str                          # "confirmed" | "overridden"
    override_decision: str | None = None  # required when outcome == "overridden"
    note: str | None = None


@router.post("/permits")
async def run_permit_check(
    file: UploadFile = File(...),
    principal: Principal = Depends(current_principal),
) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    return svc.process(data, file.filename or "upload", tenant_id=principal.tenant_id)


@router.get("/permits/history")
def permits_history(principal: Principal = Depends(current_principal)) -> list[dict]:
    return svc.history(principal.tenant_id)


@router.get("/permits/review-queue")
def permits_review_queue(principal: Principal = Depends(current_principal)) -> list[dict]:
    return svc.review_queue(principal.tenant_id)


@router.get("/permits/{check_id}")
def permit_detail(check_id: str, principal: Principal = Depends(current_principal)) -> dict:
    out = svc.get_check(principal.tenant_id, check_id)
    if out is None:
        raise HTTPException(status_code=404, detail="Permit check not found")
    return out


@router.post("/permits/{check_id}/review")
def review_permit(check_id: str, body: ReviewBody,
                  principal: Principal = Depends(current_principal)) -> dict:
    reviewer = principal.email or principal.user_id
    try:
        out = svc.review(principal.tenant_id, check_id, reviewer=reviewer, outcome=body.outcome,
                         override_decision=body.override_decision, note=body.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Permit check not found")
    return out
