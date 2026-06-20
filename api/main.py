"""FastAPI app — exposes the agents as authenticated, tenant-scoped endpoints.

Run:  uv run uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.auth import Principal, current_principal
from core.db import DATABASE_URL, init_db
from api.routes import secure_intake, shift

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")

app = FastAPI(title="Mona AI — Agent API", version="0.1.0")

WEB_ORIGIN = os.getenv("WEB_ORIGIN", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[WEB_ORIGIN, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    # local/dev convenience: create tables on SQLite. Prod (Postgres) uses Alembic.
    if DATABASE_URL.startswith("sqlite"):
        init_db()
    log.info("API up · db=%s · auth=%s", DATABASE_URL.split("://")[0], os.getenv("AUTH_MODE", "dev"))


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": "internal_error", "detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/me")
def me(principal: Principal = Depends(current_principal)) -> dict:
    return {"user_id": principal.user_id, "tenant_id": principal.tenant_id,
            "email": principal.email, "role": principal.role}


app.include_router(secure_intake.router)
app.include_router(shift.router)
