"""Shared model helpers. String UUID PKs + UTC timestamps so models are portable
across SQLite (local dev) and Postgres/Supabase (prod). Every domain row carries a
tenant_id for multi-tenant row scoping."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
