"""Unified LLM access — the ONLY place that talks to a model provider.

Providers (switch with LLM_PROVIDER, or per-call `provider=`):
  - gemini  : prod/demo. Org key, capped ~20 req/day/model, model-fallback chain. Has vision.
  - ollama  : free local dev (llama3.1:8b chat+tools, nomic-embed-text). No vision.

Public API (provider-agnostic — agents never see the SDK):
  - ask(prompt, system)            -> str
  - extract(schema, content, ...)  -> pydantic instance (structured output)
  - chat(messages, tools, schema)  -> ChatTurn(text, tool_calls)   # the agent-loop primitive
  - embed(texts)                   -> list[list[float]]            # for core.rag

Free-tier survival: vision (PDF/image) always routes to gemini and is cached; a
provider-namespaced disk cache makes repeat ask/extract/embed calls free + instant.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Type, TypeVar

from pydantic import BaseModel

from core import config

T = TypeVar("T", bound=BaseModel)

_MIN_INTERVAL = float(os.getenv("LLM_MIN_INTERVAL", "0"))
_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "4"))
_CACHE_ON = os.getenv("LLM_CACHE", "1") != "0"
_CACHE_DIR = config.DATA_OUT / "llm_cache"
_last_call = [0.0]


# ---- normalized chat types ----------------------------------------------
@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ChatTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


# ---- routing + cache -----------------------------------------------------
def _has_media(content) -> bool:
    return isinstance(content, list) and any(b.get("type") in ("image", "document") for b in content)


def _route(content, provider: str | None) -> str:
    if _has_media(content):
        return "gemini"  # no local vision model
    return provider or config.LLM_PROVIDER


def _key(kind: str, system: str, content, ns: str) -> str:
    # gemini keys stay in the legacy format so the pre-baked demo cache still hits;
    # ollama (and any future provider) gets its own namespace so dev never poisons it.
    base = [kind, system, content]
    payload = json.dumps(base if ns == "gemini" else [ns, *base], sort_keys=True, default=str)
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


def _blocks_to_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b["text"] for b in content if b.get("type") == "text")


# ======================================================================
# GEMINI
# ======================================================================
from google import genai  # noqa: E402
from google.genai import errors, types  # noqa: E402

_gclient: genai.Client | None = None


def _gemini() -> genai.Client:
    global _gclient
    if _gclient is None:
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("No Gemini key set. Put GEMINI_API_KEY=... in .env.")
        _gclient = genai.Client(api_key=key)
    return _gclient


def _to_parts(blocks) -> list:
    parts = []
    for b in blocks:
        k = b.get("type")
        if k == "text":
            parts.append(types.Part(text=b["text"]))
        elif k in ("image", "document"):
            s = b["source"]
            parts.append(types.Part(inline_data=types.Blob(mime_type=s["media_type"], data=base64.b64decode(s["data"]))))
    return parts


def _gem_cfg(system: str, model: str, *, schema=None, tools=None, max_tokens=2000):
    kw: dict = {"system_instruction": system, "max_output_tokens": max_tokens}
    if schema is not None:
        kw["response_mime_type"] = "application/json"
        kw["response_schema"] = schema
    if tools:
        kw["tools"] = [types.Tool(function_declarations=[
            types.FunctionDeclaration(name=t["name"], description=t.get("description", ""), parameters=t["parameters"])
            for t in tools])]
    if "2.5-flash" in (model or ""):
        kw["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kw)


def _retry_delay(msg: str, attempt: int) -> float:
    m = re.search(r"retry(?:Delay)?['\":\s]+([0-9.]+)s", msg) or re.search(r"retry in ([0-9.]+)s", msg)
    return min((float(m.group(1)) if m else 2 ** attempt * 8) + 2, 65)


def _gem_chain(requested: str) -> list[str]:
    out = []
    for m in [requested, *config.MODEL_FALLBACKS]:
        if m and m not in out:
            out.append(m)
    return out


def _gem_generate(requested, contents, system, *, schema=None, tools=None, max_tokens=2000):
    last = None
    for model in _gem_chain(requested):
        cfg = _gem_cfg(system, model, schema=schema, tools=tools, max_tokens=max_tokens)
        for attempt in range(_MAX_RETRIES + 1):
            if _MIN_INTERVAL > 0:
                wait = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
                if wait > 0:
                    time.sleep(wait)
            _last_call[0] = time.monotonic()
            try:
                return _gemini().models.generate_content(model=model, contents=contents, config=cfg)
            except errors.ServerError as e:
                last = e
                if attempt < _MAX_RETRIES:
                    time.sleep(min(2 ** attempt * 3 + 2, 30))
                    continue
                break
            except errors.ClientError as e:
                last = e
                msg = str(e)
                is429 = getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in msg
                if is429 and "PerDay" in msg:
                    break
                if is429 and attempt < _MAX_RETRIES:
                    time.sleep(_retry_delay(msg, attempt))
                    continue
                raise
    raise last if last else RuntimeError("gemini generation failed")


def _gem_chat(messages, tools, schema, max_tokens) -> ChatTurn:
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = []
    for m in messages:
        if m["role"] == "system":
            continue
        if m["role"] == "tool":
            contents.append(types.Content(role="user", parts=[types.Part.from_function_response(
                name=m.get("name", "tool"), response={"result": m["content"]})]))
        elif m["role"] == "assistant" and m.get("tool_calls"):
            contents.append(types.Content(role="model", parts=[
                types.Part(function_call=types.FunctionCall(name=tc.name, args=tc.args)) for tc in m["tool_calls"]]))
        else:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=m["content"] or "")]))
    resp = _gem_generate(config.MODEL, contents, system or "You are a helpful agent.",
                         schema=schema, tools=tools, max_tokens=max_tokens)
    turn = ChatTurn()
    cand = resp.candidates[0] if resp.candidates else None
    for part in (cand.content.parts if cand and cand.content else []):
        if getattr(part, "function_call", None):
            fc = part.function_call
            turn.tool_calls.append(ToolCall(id=fc.name, name=fc.name, args=dict(fc.args or {})))
        elif getattr(part, "text", None):
            turn.text += part.text
    return turn


def _gem_embed(texts: list[str]) -> list[list[float]]:
    r = _gemini().models.embed_content(model=config.GEMINI_EMBED, contents=texts)
    return [list(e.values) for e in r.embeddings]


# ======================================================================
# OLLAMA
# ======================================================================
import ollama  # noqa: E402

_oclient = None


def _ollama() -> "ollama.Client":
    global _oclient
    if _oclient is None:
        _oclient = ollama.Client(host=config.OLLAMA_HOST)
    return _oclient


def _to_ollama_msgs(messages) -> list[dict]:
    out = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content", "") or "",
                        "tool_calls": [{"function": {"name": tc.name, "arguments": tc.args}} for tc in m["tool_calls"]]})
        elif m["role"] == "tool":
            out.append({"role": "tool", "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": _blocks_to_text(m["content"])})
    return out


def _extract_json_objects(text: str) -> list[str]:
    """Pull brace-balanced JSON substrings out of free text."""
    objs, depth, start = [], 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                objs.append(text[start:i + 1])
                start = -1
    return objs


def _text_toolcall(text: str, tool_names: list[str]) -> "ToolCall | None":
    """Some local models emit a tool call as TEXT instead of structured tool_calls.
    Recover it: parse a JSON object naming a known tool (exact or fuzzy match)."""
    low = {n.lower(): n for n in tool_names}
    for cand in [_strip_fence(text), *_extract_json_objects(text)]:
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        raw = obj.get("name") or obj.get("tool") or obj.get("function")
        if not isinstance(raw, str):
            continue
        rl = raw.lower()
        match = low.get(rl) or next((n for nl, n in low.items() if nl in rl or rl in nl), None)
        if not match:
            continue
        args = obj.get("parameters") or obj.get("arguments") or obj.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        return ToolCall(id=match, name=match, args=dict(args) if isinstance(args, dict) else {})
    return None


def _ollama_chat(messages, tools, schema, max_tokens) -> ChatTurn:
    kw: dict = {"model": config.OLLAMA_MODEL, "messages": _to_ollama_msgs(messages),
                "options": {"num_predict": max_tokens}}
    if tools:
        kw["tools"] = [{"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""), "parameters": t["parameters"]}} for t in tools]
    if schema is not None:
        kw["format"] = schema.model_json_schema()
    resp = _ollama().chat(**kw)
    msg = resp.message
    turn = ChatTurn(text=msg.content or "")
    for tc in (msg.tool_calls or []):
        f = tc.function
        args = f.arguments if isinstance(f.arguments, dict) else json.loads(f.arguments or "{}")
        turn.tool_calls.append(ToolCall(id=f.name, name=f.name, args=dict(args)))
    # local models sometimes emit the tool call as plain text — recover it
    if tools and not turn.tool_calls and turn.text:
        recovered = _text_toolcall(turn.text, [t["name"] for t in tools])
        if recovered:
            turn.tool_calls.append(recovered)
            turn.text = ""
    return turn


def _ollama_embed(texts: list[str]) -> list[list[float]]:
    r = _ollama().embed(model=config.OLLAMA_EMBED, input=texts)
    return [list(v) for v in r.embeddings]


# ======================================================================
# PUBLIC API
# ======================================================================
def ask(prompt, system: str = "", provider: str | None = None, max_tokens: int = 2000) -> str:
    system = system or "You are a precise, concise assistant."
    ns = _route(prompt, provider)
    key = _key("ask", system, prompt, ns)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    if ns == "ollama":
        text = _ollama_chat([{"role": "system", "content": system},
                             {"role": "user", "content": _blocks_to_text(prompt)}], None, None, max_tokens).text
    else:
        parts = _to_parts(prompt) if isinstance(prompt, list) else [types.Part(text=prompt)]
        text = _gem_generate(config.MODEL, parts, system, max_tokens=max_tokens).text or ""
    _cache_put(key, text)
    return text


def extract(schema: Type[T], content, system: str = "", provider: str | None = None, max_tokens: int = 2000) -> T:
    system = system or "Extract the requested fields accurately. If a field is unknown, use null."
    ns = _route(content, provider)
    key = _key(f"extract:{schema.__name__}", system, content, ns)
    hit = _cache_get(key)
    if hit is not None:
        return schema.model_validate(hit)
    if ns == "ollama":
        turn = _ollama_chat([{"role": "system", "content": system},
                             {"role": "user", "content": _blocks_to_text(content)}], None, schema, max_tokens)
        obj = schema.model_validate(json.loads(_strip_fence(turn.text)))
    else:
        parts = _to_parts(content) if isinstance(content, list) else [types.Part(text=content)]
        resp = _gem_generate(config.MODEL, parts, system, schema=schema, max_tokens=max_tokens)
        parsed = getattr(resp, "parsed", None)
        obj = parsed if isinstance(parsed, schema) else schema.model_validate(json.loads(_strip_fence(resp.text or "")))
    _cache_put(key, obj.model_dump())
    return obj


def chat(messages: list[dict], tools: list[dict] | None = None, schema: Type[T] | None = None,
         provider: str | None = None, max_tokens: int = 2000) -> ChatTurn:
    """One model turn for the agent loop. Not cached (history/tool-result varies)."""
    ns = provider or config.LLM_PROVIDER
    if ns == "ollama":
        return _ollama_chat(messages, tools, schema, max_tokens)
    return _gem_chat(messages, tools, schema, max_tokens)


def embed(texts: list[str], provider: str | None = None) -> list[list[float]]:
    ns = provider or config.LLM_PROVIDER
    out, todo, idx = [None] * len(texts), [], []
    for i, t in enumerate(texts):
        hit = _cache_get(_key("embed", "", t, ns))
        if hit is not None:
            out[i] = hit
        else:
            todo.append(t)
            idx.append(i)
    if todo:
        vecs = _ollama_embed(todo) if ns == "ollama" else _gem_embed(todo)
        for j, v in zip(idx, vecs):
            out[j] = v
            _cache_put(_key("embed", "", texts[j], ns), v)
    return out  # type: ignore


def _strip_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].lstrip("json").strip()
    return text
