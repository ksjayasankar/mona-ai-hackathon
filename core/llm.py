"""Thin Gemini wrapper shared by every agent.

Provider lives ONLY in this file — agents call ask()/extract() and never see the SDK,
so swapping the model is a one-file change (we moved Anthropic -> Gemini here).

Two entry points:
  - ask():     free-form text answer.
  - extract(): forced structured output validated against a pydantic model
               (Gemini structured output via response_schema, with a JSON fallback).

Content blocks come from core.ingest in Anthropic-style dicts; _to_parts() translates
them to Gemini Parts, so the same call works for a photo, a PDF, or plain text.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Type, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from core import config

_client: genai.Client | None = None
T = TypeVar("T", bound=BaseModel)


def client() -> genai.Client:
    global _client
    if _client is None:
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError(
                "No Gemini key set. Put GEMINI_API_KEY=... in the .env file at the repo root."
            )
        _client = genai.Client(api_key=key)
    return _client


def _to_parts(blocks) -> list:
    """Translate Anthropic-style content blocks -> Gemini Parts."""
    parts = []
    for b in blocks:
        kind = b.get("type")
        if kind == "text":
            parts.append(types.Part(text=b["text"]))
        elif kind in ("image", "document"):
            src = b["source"]
            parts.append(
                types.Part(inline_data=types.Blob(
                    mime_type=src["media_type"],
                    data=base64.b64decode(src["data"]),
                ))
            )
    return parts


def _gen_config(system: str, model: str, *, schema=None, max_tokens: int = 2000) -> types.GenerateContentConfig:
    kwargs: dict = {"system_instruction": system, "max_output_tokens": max_tokens}
    if schema is not None:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_schema"] = schema
    # Flash supports disabling "thinking" — faster, cheaper, and avoids thinking tokens
    # eating the output budget on simple extraction. Leave Pro to think.
    if "flash" in (model or ""):
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


def ask(prompt, system: str = "", model: str | None = None, max_tokens: int = 2000) -> str:
    """Free-form text completion. `prompt` may be a string or a list of content blocks."""
    model = model or config.MODEL
    parts = _to_parts(prompt) if isinstance(prompt, list) else [types.Part(text=prompt)]
    resp = client().models.generate_content(
        model=model,
        contents=parts,
        config=_gen_config(system or "You are a precise, concise assistant.", model, max_tokens=max_tokens),
    )
    return resp.text or ""


def extract(schema: Type[T], content, system: str = "", model: str | None = None, max_tokens: int = 2000) -> T:
    """Force Gemini to return data matching `schema` (a pydantic model)."""
    model = model or config.MODEL
    parts = _to_parts(content) if isinstance(content, list) else [types.Part(text=content)]
    resp = client().models.generate_content(
        model=model,
        contents=parts,
        config=_gen_config(
            system or "Extract the requested fields accurately. If a field is unknown, use null.",
            model, schema=schema, max_tokens=max_tokens,
        ),
    )
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, schema):
        return parsed
    # fallback: parse the JSON text ourselves
    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].lstrip("json").strip()
    return schema.model_validate(json.loads(text))
