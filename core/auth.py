"""Authentication + multi-tenant scoping.

Two modes (AUTH_MODE):
  - dev      : no token needed — returns a fixed dev tenant so local dev/tests never block.
  - supabase : verify a Supabase Auth JWT (HS256, SUPABASE_JWT_SECRET) and derive the
               tenant from the token claims.

Every request resolves to a Principal carrying tenant_id; all DB queries scope by it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException
from sqlmodel import Session, select

from core.db import engine
from core.models import Tenant

AUTH_MODE = os.getenv("AUTH_MODE", "dev")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")


@dataclass
class Principal:
    user_id: str
    tenant_id: str
    email: str | None = None
    role: str = "user"


def get_or_create_tenant(slug: str, name: str | None = None) -> str:
    with Session(engine) as s:
        t = s.exec(select(Tenant).where(Tenant.slug == slug)).first()
        if not t:
            t = Tenant(name=name or slug.title(), slug=slug)
            s.add(t)
            s.commit()
            s.refresh(t)
        return t.id


def _principal_from_token(token: str) -> Principal:
    if not SUPABASE_JWT_SECRET:
        raise RuntimeError("SUPABASE_JWT_SECRET is not set")
    payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
    uid = payload["sub"]
    email = payload.get("email")
    app_meta = payload.get("app_metadata") or {}
    # tenant comes from a JWT claim; fall back to per-user tenancy
    tenant_slug = app_meta.get("tenant") or app_meta.get("tenant_id") or f"user-{uid[:8]}"
    tenant_id = get_or_create_tenant(tenant_slug, name=app_meta.get("tenant_name"))
    return Principal(user_id=uid, tenant_id=tenant_id, email=email, role=payload.get("role", "user"))


async def current_principal(authorization: str = Header(default="")) -> Principal:
    """FastAPI dependency. Resolves the caller + their tenant."""
    if AUTH_MODE == "dev":
        return Principal(user_id="dev-user", tenant_id=get_or_create_tenant("dev", "Dev Tenant"),
                         email="dev@local", role="admin")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        return _principal_from_token(authorization.split(" ", 1)[1])
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
