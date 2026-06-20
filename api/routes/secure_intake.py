"""P10 Rheinmetall — secure-intake routes. (Built out in the next layer.)"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/agents", tags=["secure-intake"])
