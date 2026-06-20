"""P8 Dr. Theiss — dynamic-pricing service (productized, tenant-scoped, persisted).

"LLM proposes, guardrails dispose." Pipeline:

    1. INGEST   core.ingest.bytes_to_blocks(pdf) -> content blocks
    2. EXTRACT  core.llm.extract -> [{product, current_price, category in TAXONOMY, cost?}]   (1 LLM call)
    3. SIGNALS  core.tools.signals.fetch_all(default_connectors)  -> SignalReadings           (HTTP, no LLM)
    4. PROPOSE  core.llm.extract -> per-product {delta%, rationale}                            (1 LLM call)
    5. GATE     agents.pricing_product.decide(...) -> authoritative GatedDecision              (pure)
    6. PERSIST  PriceRun + PriceRecommendation + AuditLog (tenant-scoped)
    7. REPORT   PricingReport for the web cards

The two LLM steps are INJECTABLE (extractor / proposer), so the gating + persistence
logic is fully unit-tested offline (tests/test_pricing.py) with no Ollama and no HTTP.
agents.pricing_product stays the pure engine; persistence lives here, not there.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from sqlmodel import Session, desc, select

from agents.pricing_product import (
    DEFAULT_POLICY,
    TAXONOMY,
    CatalogItem,
    PricingPolicy,
    SignalReading,
    decide,
)
from core import ingest, llm
from core.db import engine
from core.models import AuditLog, PriceRecommendation, PriceRun
from core.tools.signals import default_connectors, fetch_all

_TAXO = set(TAXONOMY)


# ---- LLM IO schemas (kept with the service; the pure engine never sees the SDK) ----
class _ExtractItem(BaseModel):
    product: str
    current_price: float = Field(description="indicative shelf price in EUR")
    category: str = Field(description=f"exactly one of: {', '.join(TAXONOMY)}")
    cost: float | None = Field(default=None, description="unit cost if printed, else null")


class _ExtractedCatalog(BaseModel):
    products: list[_ExtractItem]


class ProposalItem(BaseModel):
    product: str
    delta_pct: float = Field(default=0.0, description="proposed % price change, e.g. 12.5 or -8")
    rationale: str = Field(default="", description="one plain sentence citing the signal(s)")


class Proposal(BaseModel):
    items: list[ProposalItem]


class PricingReport(BaseModel):
    run_id: str
    source_note: str
    summary: str
    product_count: int
    blocked_count: int
    llm_calls: int
    signals: list[dict]
    products: list[dict]


_EXTRACT_SYS = (
    "You read a product catalogue / price list and return each product with its indicative "
    "price in EUR and ONE category from this fixed taxonomy: " + ", ".join(TAXONOMY) + ". "
    "Use 'general' if nothing fits. Include unit cost only if it is explicitly printed. Do not invent products."
)
_PROPOSE_SYS = (
    "You are a demand-responsive pricing analyst for a health-and-wellness brand. Price follows demand. "
    "For each product: if its category's signals point UP, propose a POSITIVE delta (larger when the "
    "signals are stronger, up to about +25%); if they point DOWN, propose a NEGATIVE delta to move stock; "
    "if no signal touches the category, propose 0. Always RAISE the price when demand is clearly rising. "
    "Give a one-sentence rationale naming the signal(s). Do NOT apply fairness or caps yourself — a "
    "separate deterministic guardrail layer enforces those."
)


# ---- step 2: extract the catalogue (LLM) ----
def _extract_catalog(blocks: list[dict], provider: str | None = None) -> list[CatalogItem]:
    blocks = blocks + [{"type": "text", "text":
        "Extract every product with its indicative EUR price and a taxonomy category. Do not invent rows."}]
    cat = llm.extract(_ExtractedCatalog, blocks, system=_EXTRACT_SYS, provider=provider)
    items: list[CatalogItem] = []
    for p in cat.products:
        if p.current_price is None or p.current_price <= 0:
            continue
        category = p.category if p.category in _TAXO else "general"
        items.append(CatalogItem(product=p.product, current_price=p.current_price,
                                 category=category, cost=p.cost))
    return items


# ---- step 4: propose deltas (LLM, single structured pass) ----
def _signal_digest(signals: list[SignalReading]) -> str:
    live = [s for s in signals if s.configured]
    if not live:
        return "No active external signals."
    return "\n".join(
        f"- {s.label} [{s.source}] -> categories {s.affected_categories}, {s.direction} "
        f"(strength {s.magnitude:.1f}): {s.evidence}" for s in live)


def _propose(items: list[CatalogItem], signals: list[SignalReading], provider: str | None = None) -> Proposal:
    # Pre-compute (deterministically) which signals hit each product's category and their
    # direction, so the LLM only has to turn "up signals" into a positive delta. This makes
    # the proposal demand-responsive and reliable instead of leaving the matching to the model.
    from agents.pricing_product import signals_for

    lines = []
    for i in items:
        rel = signals_for(i, signals)
        if rel:
            ctx = ", ".join(f"{s.label} [{s.direction}]" for s in rel)
            lines.append(f"- {i.product} (category={i.category}, EUR {i.current_price:.2f}) — signals on this category: {ctx}")
        else:
            lines.append(f"- {i.product} (category={i.category}, EUR {i.current_price:.2f}) — no signal on this category")
    prompt = (
        "Products, each annotated with the external signals on its category:\n" + "\n".join(lines) +
        "\n\nFor EACH product propose delta_pct and a one-sentence rationale. Raise the price when its "
        "category's signals point up, lower it when they point down, and propose 0 when there is no signal."
    )
    return llm.extract(Proposal, prompt, system=_PROPOSE_SYS, provider=provider)


# ---- step 5: gate (pure) ----
def build_recommendations(items: list[CatalogItem], signals: list[SignalReading],
                          proposals: dict[str, ProposalItem], policy: PricingPolicy):
    out = []
    for item in items:
        p = proposals.get(item.product)
        delta = p.delta_pct if p else 0.0
        rationale = p.rationale if p else "No signal touched this product's category — held at base."
        out.append((decide(item, delta, signals, policy), rationale))
    return out


# ---- orchestration ----
def analyze(*, tenant_id: str, data: bytes | None = None, suffix: str = ".pdf",
            place: str = "Homburg", country: str = "DE", provider: str | None = None,
            policy: PricingPolicy = DEFAULT_POLICY,
            items: list[CatalogItem] | None = None,
            signals: list[SignalReading] | None = None,
            proposer=None, extractor=None) -> PricingReport:
    llm_calls = 0
    source_note = "Catalogue supplied directly."

    # 2) extract (or use injected items)
    if items is None:
        if data is None:
            raise ValueError("analyze() needs either `data` (a catalogue file) or `items`.")
        blocks = ingest.bytes_to_blocks(data, suffix)
        run_extract = extractor or _extract_catalog
        items = run_extract(blocks, provider)
        llm_calls += 0 if extractor else 1
        source_note = "Base prices read from the uploaded catalogue."

    # 3) signals (HTTP, no LLM) — or injected
    if signals is None:
        signals = fetch_all(default_connectors(place=place, country=country))

    # 4) propose (or injected) — single structured pass
    run_propose = proposer or _propose
    proposal = run_propose(items, signals, provider) if items else Proposal(items=[])
    llm_calls += 0 if (proposer or not items) else 1
    by_product = {pi.product: pi for pi in proposal.items}

    # 5) gate (pure)
    decided = build_recommendations(items, signals, by_product, policy)

    # 6) persist + 7) report
    return _persist(tenant_id, source_note, decided, signals, llm_calls)


def _card(rec: PriceRecommendation, rationale: str) -> dict:
    return {
        "rec_id": rec.id, "product": rec.product, "category": rec.category,
        "base_price": rec.base_price, "proposed_delta_pct": rec.proposed_delta_pct,
        "final_delta_pct": rec.final_delta_pct, "final_price": rec.final_price,
        "guardrail_status": rec.guardrail_status, "status": rec.status,
        "reasons": rec.reasons, "signals": rec.signals, "rationale": rationale,
    }


def _persist(tenant_id: str, source_note: str, decided, signals, llm_calls: int) -> PricingReport:
    blocked = sum(1 for d, _ in decided if d.status == "blocked")
    summary = (f"{len(decided)} product(s) analysed; {blocked} price increase(s) blocked by the "
               f"anti-gouging guardrail." if blocked else f"{len(decided)} product(s) analysed; no blocks.")
    with Session(engine) as s:
        run = PriceRun(tenant_id=tenant_id, source_note=source_note, product_count=len(decided),
                       blocked_count=blocked, summary=summary,
                       signals=[sig.model_dump() for sig in signals], report={})
        s.add(run)
        cards = []
        for d, rationale in decided:
            rec = PriceRecommendation(
                tenant_id=tenant_id, run_id=run.id, product=d.product, category=d.category,
                base_price=d.base_price, proposed_delta_pct=d.proposed_delta_pct,
                final_delta_pct=d.final_delta_pct, final_price=d.final_price,
                guardrail_status=d.status, reasons=d.reasons, signals=d.signals, status="pending")
            s.add(rec)
            cards.append(_card(rec, rationale))
        run.report = {"products": cards, "summary": summary, "source_note": source_note}
        s.add(run)
        s.add(AuditLog(tenant_id=tenant_id, action="pricing.analyzed", severity="info",
                       detail={"run_id": run.id, "products": len(decided), "blocked": blocked}))
        if blocked:
            s.add(AuditLog(tenant_id=tenant_id, action="pricing.blocked", severity="warning",
                           detail={"run_id": run.id, "blocked": blocked}))
        s.commit()
        run_id = run.id
    return PricingReport(run_id=run_id, source_note=source_note, summary=summary,
                         product_count=len(decided), blocked_count=blocked, llm_calls=llm_calls,
                         signals=[sig.model_dump() for sig in signals], products=cards)


# ---- approve / reject / history (tenant-scoped) ----
def _set_status(rec_id: str, tenant_id: str, status: str) -> dict:
    with Session(engine) as s:
        rec = s.get(PriceRecommendation, rec_id)
        if rec is None or rec.tenant_id != tenant_id:   # no cross-tenant access
            raise LookupError("recommendation not found")
        rec.status = status
        s.add(rec)
        s.add(AuditLog(tenant_id=tenant_id, action=f"pricing.{status}", severity="info",
                       detail={"rec_id": rec_id, "product": rec.product, "final_price": rec.final_price}))
        s.commit()
        return {"id": rec.id, "product": rec.product, "status": rec.status, "final_price": rec.final_price}


def approve(rec_id: str, tenant_id: str) -> dict:
    return _set_status(rec_id, tenant_id, "approved")


def reject(rec_id: str, tenant_id: str) -> dict:
    return _set_status(rec_id, tenant_id, "rejected")


def history(tenant_id: str, limit: int = 20) -> list[dict]:
    with Session(engine) as s:
        rows = s.exec(select(PriceRun).where(PriceRun.tenant_id == tenant_id)
                      .order_by(desc(PriceRun.created_at)).limit(limit)).all()
        return [{"id": r.id, "created_at": r.created_at.isoformat(), "source_note": r.source_note,
                 "product_count": r.product_count, "blocked_count": r.blocked_count,
                 "summary": r.summary} for r in rows]


def get_run(run_id: str, tenant_id: str) -> dict | None:
    with Session(engine) as s:
        run = s.get(PriceRun, run_id)
        if run is None or run.tenant_id != tenant_id:
            return None
        recs = s.exec(select(PriceRecommendation).where(PriceRecommendation.run_id == run_id)).all()
        return {
            "run": {"id": run.id, "created_at": run.created_at.isoformat(), "summary": run.summary,
                    "source_note": run.source_note, "signals": run.signals},
            "products": [_card(r, "") for r in recs],
        }
