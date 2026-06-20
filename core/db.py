"""Database engine + session. DATABASE_URL (Supabase/Postgres) when set, else a local
SQLite file so dev/tests never block on credentials. Alembic owns prod migrations;
init_db() (create_all) is for local dev + tests.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from core import config

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{config.DATA_OUT / 'app.db'}"
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True, connect_args=_connect_args)


def init_db() -> None:
    """Create all tables (local dev / tests). Prod uses Alembic migrations."""
    import core.models  # noqa: F401  — registers every table on the metadata
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yields a scoped session."""
    with Session(engine) as session:
        yield session
