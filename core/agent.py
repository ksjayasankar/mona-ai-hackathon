"""Provider-agnostic tool-using agent loop — the "real multi-agent" primitive.

run_agent() gives the model a set of tools, lets it call them, feeds results back, and
loops until it stops calling tools (or hits max_steps). It returns a structured result
(if a schema is given) plus a full audit TRACE and a per-run LLM call count — both matter:
the trace is persisted to AuditLog, and the call count keeps us inside the ~20/day Gemini
budget. Develop loops against LLM_PROVIDER=ollama (free); run final/demo on gemini.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Type, TypeVar

from pydantic import BaseModel

from core import llm

log = logging.getLogger("agent")
T = TypeVar("T", bound=BaseModel)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict                 # JSON schema for the args
    fn: Callable[..., object]        # returns anything; stringified for the model


@dataclass
class AgentEvent:
    kind: str                        # "model" | "tool"
    data: dict


@dataclass
class AgentResult:
    text: str
    data: BaseModel | None
    steps: int
    llm_calls: int
    trace: list[AgentEvent] = field(default_factory=list)

    def trace_dicts(self) -> list[dict]:
        return [{"kind": e.kind, **e.data} for e in self.trace]


def _as_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if b.get("type") == "text")


def _render(messages: list[dict]) -> str:
    out = []
    for m in messages:
        if m["role"] == "tool":
            out.append(f"[tool:{m.get('name','?')}] {m['content']}")
        elif m["role"] == "assistant" and m.get("tool_calls"):
            out.append("[assistant called: " + ", ".join(tc.name for tc in m["tool_calls"]) + "]")
        elif m["role"] != "system":
            out.append(f"[{m['role']}] {_as_text(m['content'])}")
    return "\n".join(out)


def run_agent(system: str, content, tools: list[Tool], *, schema: Type[T] | None = None,
              max_steps: int = 6, provider: str | None = None, max_tokens: int = 1500) -> AgentResult:
    tool_map = {t.name: t for t in tools}
    specs = [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools]
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": _as_text(content)},
    ]
    trace: list[AgentEvent] = []
    llm_calls = 0
    final_text = ""
    steps = 0

    for steps in range(1, max_steps + 1):
        turn = llm.chat(messages, tools=specs or None, provider=provider, max_tokens=max_tokens)
        llm_calls += 1
        trace.append(AgentEvent("model", {"text": turn.text,
                                          "tool_calls": [{"name": tc.name, "args": tc.args} for tc in turn.tool_calls]}))
        if not turn.tool_calls:
            final_text = turn.text
            break
        messages.append({"role": "assistant", "content": turn.text, "tool_calls": turn.tool_calls})
        for tc in turn.tool_calls:
            tool = tool_map.get(tc.name)
            try:
                result = tool.fn(**tc.args) if tool else f"ERROR: unknown tool '{tc.name}'"
            except Exception as e:  # tools must never crash the loop
                result = f"ERROR running {tc.name}: {e}"
                log.warning("tool %s failed: %s", tc.name, e)
            result = str(result)[:4000]
            trace.append(AgentEvent("tool", {"name": tc.name, "args": tc.args, "result": result[:600]}))
            messages.append({"role": "tool", "name": tc.name, "content": result})
    else:
        final_text = final_text or "Reached max steps without a final answer."

    data: BaseModel | None = None
    if schema is not None:
        data = llm.extract(schema, f"{_render(messages)}\n\nProduce the final result as structured data.",
                           system=system, provider=provider)
        llm_calls += 1

    log.info("agent done: steps=%d llm_calls=%d tools=%d", steps, llm_calls,
             sum(1 for e in trace if e.kind == "tool"))
    return AgentResult(text=final_text, data=data, steps=steps, llm_calls=llm_calls, trace=trace)
