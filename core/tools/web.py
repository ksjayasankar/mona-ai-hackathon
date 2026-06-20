"""Generic web tools for agents. Use Firecrawl's HTTP API when FIRECRAWL_API_KEY is set,
otherwise degrade gracefully (return a clear 'unavailable' string — never raise)."""
from __future__ import annotations

import os

import httpx


def web_search(query: str, limit: int = 5) -> str:
    """Search the web; returns a compact text digest of results."""
    key = os.getenv("FIRECRAWL_API_KEY")
    if not key:
        return f"[web_search unavailable: no FIRECRAWL_API_KEY] query was: {query!r}"
    try:
        r = httpx.post(
            "https://api.firecrawl.dev/v1/search",
            headers={"Authorization": f"Bearer {key}"},
            json={"query": query, "limit": limit},
            timeout=30,
        )
        r.raise_for_status()
        items = r.json().get("data", []) or []
        if not items:
            return f"No results for {query!r}."
        return "\n".join(f"- {it.get('title','')}: {it.get('description','')} ({it.get('url','')})" for it in items[:limit])
    except Exception as e:
        return f"[web_search error: {e}]"


def fetch_url(url: str) -> str:
    """Fetch a URL and return up to ~4k chars of text."""
    try:
        r = httpx.get(url, timeout=30, follow_redirects=True)
        r.raise_for_status()
        return r.text[:4000]
    except Exception as e:
        return f"[fetch_url error: {e}]"
