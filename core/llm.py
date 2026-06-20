"""Thin Gemini wrapper shared by every agent.

Provider lives ONLY in this file — agents call ask()/extract() and never see the SDK,
so swapping the model is a one-file change (we moved Anthropic -> Gemini here).

Two entry points:
  - ask():     free-form text answer.
  - extract(): forced structured output validated against a pydantic model
               (Gemini structured output via response_schema, with a JSON fallback).

Content blocks come from core.ingest in Anthropic-style dicts; _to_parts() translates
them to Gemini Parts, so the same call works for a photo, a PDF, or plain text.

Free-tier survival (the key gives ~20 requests/DAY *per model*):
  1. CACHE  — model-AGNOSTIC: identical (system, content) calls are served from disk
     regardless of which model produced them, so re-runs cost zero quota and are instant.
     This is what makes the live demo bulletproof.
  2. FALLBACK CHAIN — when one model's daily cap is hit, roll to the next model
     (config.MODEL_FALLBACKS) automatically. Per-minute 429s and transient 503s just
     back off and retry the same model.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from typing import Type, TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from core import config

_client: genai.Client | None = None
T = TypeVar("T", bound=BaseModel)

_MIN_INTERVAL = float(os.getenv("LLM_MIN_INTERVAL", "0"))  # seconds between calls; 0 = off
_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
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


# ---- cache (model-agnostic) ----------------------------------------------
def _key(kind: str, system: str, content) -> str:
    payload = json.dumps([kind, system, content], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _cache_get(key: str):
    if not _CACHE_ON:
        return None
    f = _CACHE_DIR / f"{key}.json"
    return json.loads(f.read_text()) if f.exists() else None


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
    # Only the 2.5 Flash family supports the "thinking" toggle; 2.0 models reject it.
    if "2.5-flash" in (model or ""):
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


def _retry_delay(msg: str, attempt: int) -> float:
    m = re.search(r"retry(?:Delay)?['\":\s]+([0-9.]+)s", msg) or re.search(r"retry in ([0-9.]+)s", msg)
    base = float(m.group(1)) if m else 2 ** attempt * 8
    return min(base + 2, 65)


def _chain(requested: str) -> list[str]:
    out = []
    for m in [requested, *config.MODEL_FALLBACKS]:
        if m and m not in out:
            out.append(m)
    return out


def _generate(requested: str, parts, system: str, schema, max_tokens: int):
    """Call Gemini, rolling across the model fallback chain on daily-cap exhaustion."""
    last = None
    for model in _chain(requested):
        gconfig = _gen_config(system, model, schema=schema, max_tokens=max_tokens)
        for attempt in range(_MAX_RETRIES + 1):
            if _MIN_INTERVAL > 0:
                wait = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
                if wait > 0:
                    time.sleep(wait)
            _last_call[0] = time.monotonic()
            try:
                return client().models.generate_content(model=model, contents=parts, config=gconfig)
            except errors.ServerError as e:  # 500/503 transient overload
                last = e
                if attempt < _MAX_RETRIES:
                    time.sleep(min(2 ** attempt * 3 + 2, 30))
                    continue
                break  # give this model up, try next in chain
            except errors.ClientError as e:
                last = e
                msg = str(e)
                is429 = getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in msg
                if is429 and "PerDay" in msg:
                    break  # daily cap on this model -> next model in chain
                if is429 and attempt < _MAX_RETRIES:
                    time.sleep(_retry_delay(msg, attempt))
                    continue
                raise
    raise last if last else RuntimeError("generation failed")


# ---- public API ----------------------------------------------------------
def ask(prompt, system: str = "", model: str | None = None, max_tokens: int = 2000) -> str:
    """Free-form text completion. `prompt` may be a string or a list of content blocks."""
    system = system or "You are a precise, concise assistant."
    key = _key("ask", system, prompt)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    parts = _to_parts(prompt) if isinstance(prompt, list) else [types.Part(text=prompt)]
    text = _generate(model or config.MODEL, parts, system, None, max_tokens).text or ""
    _cache_put(key, text)
    return text


def extract(schema: Type[T], content, system: str = "", model: str | None = None, max_tokens: int = 2000) -> T:
    """Force Gemini to return data matching `schema` (a pydantic model)."""
    system = system or "Extract the requested fields accurately. If a field is unknown, use null."
    key = _key(f"extract:{schema.__name__}", system, content)
    cached = _cache_get(key)
    if cached is not None:
        return schema.model_validate(cached)
    parts = _to_parts(content) if isinstance(content, list) else [types.Part(text=content)]
    resp = _generate(model or config.MODEL, parts, system, schema, max_tokens)
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, schema):
        obj = parsed
    else:
        text = (resp.text or "").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1].lstrip("json").strip()
        obj = schema.model_validate(json.loads(text))
    _cache_put(key, obj.model_dump())
    return obj
