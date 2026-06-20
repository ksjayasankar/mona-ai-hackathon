"""Thin Gemini wrapper shared by every agent.

Provider lives ONLY in this file — agents call ask()/extract() and never see the SDK,
so swapping the model is a one-file change (we moved Anthropic -> Gemini here).

Two entry points:
  - ask():     free-form text answer.
  - extract(): forced structured output validated against a pydantic model
               (Gemini structured output via response_schema, with a JSON fallback).

Content blocks come from core.ingest in Anthropic-style dicts; _to_parts() translates
them to Gemini Parts, so the same call works for a photo, a PDF, or plain text.

Two defences against the Gemini FREE-TIER limits (~5 req/min AND a small daily cap):
  1. CACHE  — identical (model, system, content) calls are served from disk, so a
     re-run of the same document costs zero quota and returns instantly. This is what
     makes the live demo bulletproof: pre-run a doc once, it replays free forever.
  2. RETRY  — 429s retry with backoff (honouring the server delay), and an optional
     LLM_MIN_INTERVAL throttle spaces calls out, so a batch never crashes — it waits.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Type, TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from core import config

_client: genai.Client | None = None
T = TypeVar("T", bound=BaseModel)

_MIN_INTERVAL = float(os.getenv("LLM_MIN_INTERVAL", "0"))  # seconds between calls; 0 = off
_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "4"))
_CACHE_ON = os.getenv("LLM_CACHE", "1") != "0"
_CACHE_DIR = config.DATA_OUT / "llm_cache"
_last_call = [0.0]


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


# ---- cache ---------------------------------------------------------------
def _key(kind: str, model: str, system: str, content) -> str:
    payload = json.dumps([kind, model, system, content], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _cache_get(key: str):
    if not _CACHE_ON:
        return None
    f = _CACHE_DIR / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text())
    return None


def _cache_put(key: str, value) -> None:
    if not _CACHE_ON:
        return
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (_CACHE_DIR / f"{key}.json").write_text(json.dumps(value, default=str))


# ---- content translation -------------------------------------------------
def _to_parts(blocks) -> list:
    """Translate Anthropic-style content blocks -> Gemini Parts."""
    parts = []
    for b in blocks:
        kind = b.get("type")
        if kind == "text":
            parts.append(types.Part(text=b["text"]))
        elif kind in ("image", "document"):
            src = b["source"]
            parts.append(types.Part(inline_data=types.Blob(
                mime_type=src["media_type"], data=base64.b64decode(src["data"]),
            )))
    return parts


def _gen_config(system: str, model: str, *, schema=None, max_tokens: int = 2000) -> types.GenerateContentConfig:
    kwargs: dict = {"system_instruction": system, "max_output_tokens": max_tokens}
    if schema is not None:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_schema"] = schema
    # Flash/Flash-Lite let us disable "thinking" — faster, cheaper, no thinking tokens
    # eating the output budget on simple extraction.
    if "flash" in (model or ""):
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


def _retry_delay(msg: str, attempt: int) -> float:
    m = re.search(r"retry(?:Delay)?['\":\s]+([0-9.]+)s", msg) or re.search(r"retry in ([0-9.]+)s", msg)
    base = float(m.group(1)) if m else 2 ** attempt * 8
    return min(base + 2, 65)


def _generate(model: str, contents, gconfig):
    """Call Gemini with throttle + 429 retry/backoff."""
    for attempt in range(_MAX_RETRIES + 1):
        if _MIN_INTERVAL > 0:
            wait = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
            if wait > 0:
                time.sleep(wait)
        _last_call[0] = time.monotonic()
        try:
            return client().models.generate_content(model=model, contents=contents, config=gconfig)
        except errors.ClientError as e:
            msg = str(e)
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            # daily-cap 429s won't clear by waiting — only retry the per-minute kind
            per_minute = "PerMinute" in msg or "PerDay" not in msg
            if (code == 429 or "RESOURCE_EXHAUSTED" in msg) and per_minute and attempt < _MAX_RETRIES:
                time.sleep(_retry_delay(msg, attempt))
                continue
            raise


# ---- public API ----------------------------------------------------------
def ask(prompt, system: str = "", model: str | None = None, max_tokens: int = 2000) -> str:
    """Free-form text completion. `prompt` may be a string or a list of content blocks."""
    model = model or config.MODEL
    system = system or "You are a precise, concise assistant."
    key = _key("ask", model, system, prompt)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    parts = _to_parts(prompt) if isinstance(prompt, list) else [types.Part(text=prompt)]
    text = _generate(model, parts, _gen_config(system, model, max_tokens=max_tokens)).text or ""
    _cache_put(key, text)
    return text


def extract(schema: Type[T], content, system: str = "", model: str | None = None, max_tokens: int = 2000) -> T:
    """Force Gemini to return data matching `schema` (a pydantic model)."""
    model = model or config.MODEL
    system = system or "Extract the requested fields accurately. If a field is unknown, use null."
    key = _key(f"extract:{schema.__name__}", model, system, content)
    cached = _cache_get(key)
    if cached is not None:
        return schema.model_validate(cached)
    parts = _to_parts(content) if isinstance(content, list) else [types.Part(text=content)]
    resp = _generate(model, parts, _gen_config(system, model, schema=schema, max_tokens=max_tokens))
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, schema):
        _cache_put(key, parsed.model_dump())
        return parsed
    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].lstrip("json").strip()
    obj = schema.model_validate(json.loads(text))
    _cache_put(key, obj.model_dump())
    return obj
