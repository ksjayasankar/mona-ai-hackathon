"""Minimal RAG: embed (via the provider switch — nomic-embed-text local / Gemini prod)
and retrieve from a local Chroma store. Collections are namespaced by provider so dev
(local) and prod (Gemini) vectors never mix. We always pass embeddings explicitly, so
Chroma never downloads its own embedding model.

Used by the problems that need it (P3 permit rules, P4 issuer registries, P9 competitors,
P10 required-docs policy). Not needed elsewhere.
"""
from __future__ import annotations

import chromadb

from core import config, llm

_client: chromadb.ClientAPI | None = None


def _store() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(config.DATA_OUT / "chroma"))
    return _client


def _collection(corpus: str, provider: str | None):
    prov = provider or config.LLM_PROVIDER
    return _store().get_or_create_collection(f"{corpus}__{prov}")


def index(corpus: str, docs: list, provider: str | None = None, reset: bool = False) -> int:
    """Index docs (each a str, or {'id','text','meta'}). Returns the count indexed."""
    prov = provider or config.LLM_PROVIDER
    if reset:
        try:
            _store().delete_collection(f"{corpus}__{prov}")
        except Exception:
            pass
    col = _collection(corpus, prov)
    items = [{"id": str(i), "text": d} if isinstance(d, str) else d for i, d in enumerate(docs)]
    ids = [it.get("id", str(i)) for i, it in enumerate(items)]
    texts = [it["text"] for it in items]
    metas = [it.get("meta") or {} for it in items]
    col.upsert(ids=ids, documents=texts, embeddings=llm.embed(texts, provider=prov), metadatas=metas)
    return len(texts)


def retrieve(corpus: str, query: str, k: int = 4, provider: str | None = None) -> list[dict]:
    """Return up to k most similar docs as [{'text','meta','distance'}]."""
    prov = provider or config.LLM_PROVIDER
    col = _collection(corpus, prov)
    n = col.count()
    if n == 0:
        return []
    res = col.query(query_embeddings=llm.embed([query], provider=prov), n_results=min(k, n))
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    return [{"text": d, "meta": m or {}, "distance": dist} for d, m, dist in zip(docs, metas, dists)]
