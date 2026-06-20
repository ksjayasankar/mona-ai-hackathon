"""Thin Claude wrapper shared by every agent.

Two entry points:
  - ask(): free-form text answer.
  - extract(): forced structured output validated against a pydantic model
    (uses tool-calling so we never parse loose JSON by hand).

Content blocks (images/PDFs/text) come from core.ingest, so the same call works
for a scanned photo, a PDF, or plain text.
"""
from __future__ import annotations

from typing import Type, TypeVar

from anthropic import Anthropic
from pydantic import BaseModel

from core import config

_client: Anthropic | None = None
T = TypeVar("T", bound=BaseModel)


def client() -> Anthropic:
    global _client
    if _client is None:
        if not config.HAS_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Paste your key into the .env file at the repo root."
            )
        _client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def ask(
    prompt: str | list,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 2000,
) -> str:
    """Free-form text completion. `prompt` may be a string or a list of content blocks."""
    content = prompt if isinstance(prompt, list) else [{"type": "text", "text": prompt}]
    resp = client().messages.create(
        model=model or config.MODEL,
        max_tokens=max_tokens,
        system=system or "You are a precise, concise assistant.",
        messages=[{"role": "user", "content": content}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def extract(
    schema: Type[T],
    content: str | list,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 2000,
) -> T:
    """Force Claude to return data matching `schema` (a pydantic model) via tool-use."""
    blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
    tool = {
        "name": "record",
        "description": f"Record the extracted result as structured data: {schema.__doc__ or schema.__name__}",
        "input_schema": schema.model_json_schema(),
    }
    resp = client().messages.create(
        model=model or config.MODEL,
        max_tokens=max_tokens,
        system=system or "Extract the requested fields accurately. If a field is unknown, use null.",
        messages=[{"role": "user", "content": blocks}],
        tools=[tool],
        tool_choice={"type": "tool", "name": "record"},
    )
    for block in resp.content:
        if block.type == "tool_use":
            return schema.model_validate(block.input)
    raise RuntimeError("Model did not return structured output.")
