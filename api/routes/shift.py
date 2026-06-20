"""P2 UKS — shift-replacement API (authenticated, tenant-scoped) + SSE live stream."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.auth import Principal, current_principal
from services import shift as svc

router = APIRouter(prefix="/agents/shift", tags=["uks-shift"])


@router.post("/seed")
def seed(principal: Principal = Depends(current_principal)) -> dict:
    return {"seeded": svc.seed_staff(principal.tenant_id)}


@router.post("/gaps")
async def create_gap(payload: dict = Body(...),
                     principal: Principal = Depends(current_principal)) -> dict:
    message = payload.get("message")
    structured = payload.get("structured")
    if not message and not structured:
        raise HTTPException(422, "provide `message` or `structured`")
    try:
        gid = svc.create_gap(principal.tenant_id, message=message, structured=structured)
    except Exception as e:
        raise HTTPException(422, f"could not build gap: {e}")
    state = svc.gap_state(principal.tenant_id, gid)
    await svc.publish(gid, state)
    return state


@router.get("/gaps")
def list_gaps(principal: Principal = Depends(current_principal)) -> list[dict]:
    return svc.list_gaps(principal.tenant_id)


@router.get("/gaps/{gap_id}")
def gap_state(gap_id: str, principal: Principal = Depends(current_principal)) -> dict:
    try:
        return svc.gap_state(principal.tenant_id, gap_id)
    except LookupError:
        raise HTTPException(404, "gap not found")


@router.post("/gaps/{gap_id}/outreach")
async def start_outreach(gap_id: str, principal: Principal = Depends(current_principal)) -> dict:
    try:
        res = svc.start_outreach(principal.tenant_id, gap_id)
    except LookupError:
        raise HTTPException(404, "gap not found")
    await svc.publish(gap_id, svc.gap_state(principal.tenant_id, gap_id))
    return res


@router.post("/gaps/{gap_id}/escalate")
async def escalate(gap_id: str, principal: Principal = Depends(current_principal)) -> dict:
    try:
        res = svc.escalate(principal.tenant_id, gap_id)
    except LookupError:
        raise HTTPException(404, "gap not found")
    await svc.publish(gap_id, svc.gap_state(principal.tenant_id, gap_id))
    return res


async def _publish_gap(gap_id: str | None) -> None:
    """Re-publish the live snapshot after a token-only mutation (accept/decline)."""
    if not gap_id:
        return
    tenant = svc.tenant_of_gap(gap_id)
    if tenant:
        await svc.publish(gap_id, svc.gap_state(tenant, gap_id))


@router.post("/accept")
async def accept(payload: dict = Body(...)) -> dict:
    """Public (no auth): reached from the SMS magic link. The token identifies the gap."""
    token = payload.get("token")
    if not token:
        raise HTTPException(422, "token required")
    res = svc.accept(token)
    await _publish_gap(res.get("gap_id"))
    return res


@router.post("/decline")
async def decline(payload: dict = Body(...)) -> dict:
    token = payload.get("token")
    if not token:
        raise HTTPException(422, "token required")
    res = svc.decline(token)
    await _publish_gap(res.get("gap_id"))
    return res


@router.get("/gaps/{gap_id}/events")
async def events(gap_id: str, request: Request,
                 principal: Principal = Depends(current_principal)) -> StreamingResponse:
    """SSE stream of gap state. Emits the current snapshot immediately, then on every change."""
    async def gen():
        q = svc.subscribe(gap_id)
        try:
            try:
                yield f"data: {json.dumps(svc.gap_state(principal.tenant_id, gap_id))}\n\n"
            except LookupError:
                yield 'data: {"error": "gap not found"}\n\n'
                return
            while True:
                if await request.is_disconnected():
                    break
                try:
                    snap = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(snap)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"      # comment frame keeps the connection open
        finally:
            svc.unsubscribe(gap_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
