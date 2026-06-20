"""Shared output shapes. Agent-specific models live in their own agents/*.py module;
these are the common pieces several agents reuse.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Verdict(BaseModel):
    """A human-readable decision with a confidence score and reasons."""

    decision: str = Field(description="Short verdict label, e.g. VALID / INVALID / NEEDS REVIEW")
    confidence: float = Field(description="Confidence 0-100", ge=0, le=100)
    reasons: list[str] = Field(default_factory=list, description="Bullet reasons supporting the decision")
