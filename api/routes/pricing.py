"""P8 Dr. Theiss — dynamic-pricing API routes (authenticated, tenant-scoped)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from agents.pricing_product import DEFAULT_POLICY, PricingPolicy
from core.auth import Principal, current_principal
from services import pricing as svc

router = APIRouter(prefix="/agents/pricing", tags=["pricing"])


@router.post("")
async def run_pricing(
    file: UploadFile = File(...),
    place: str = Form("Homburg"),
    country: str = Form("DE"),
    band_pct: float | None = Form(None),
    margin_floor_pct: float | None = Form(None),
    principal: Principal = Depends(current_principal),
) -> dict:
    data = await file.read()
    suffix = Path(file.filename or "upload.pdf").suffix or ".pdf"
    policy = DEFAULT_POLICY
    if band_pct is not None or margin_floor_pct is not None:
        policy = PricingPolicy(
            band_pct=band_pct if band_pct is not None else DEFAULT_POLICY.band_pct,
            margin_floor_pct=margin_floor_pct if margin_floor_pct is not None else DEFAULT_POLICY.margin_floor_pct,
        )
    report = svc.analyze(tenant_id=principal.tenant_id, data=data, suffix=suffix,
                         place=place, country=country, policy=policy)
    return report.model_dump()


@router.get("/history")
def pricing_history(principal: Principal = Depends(current_principal)) -> list[dict]:
    return svc.history(principal.tenant_id)


@router.get("/run/{run_id}")
def pricing_run(run_id: str, principal: Principal = Depends(current_principal)) -> dict:
    run = svc.get_run(run_id, principal.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post("/{rec_id}/approve")
def pricing_approve(rec_id: str, principal: Principal = Depends(current_principal)) -> dict:
    try:
        return svc.approve(rec_id, principal.tenant_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="recommendation not found")


@router.post("/{rec_id}/reject")
def pricing_reject(rec_id: str, principal: Principal = Depends(current_principal)) -> dict:
    try:
        return svc.reject(rec_id, principal.tenant_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="recommendation not found")
