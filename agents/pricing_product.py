"""P8 Dr. Theiss — signal-driven dynamic pricing: the PURE product logic.

This module is the "guardrails dispose" half of "LLM proposes, guardrails dispose."
It has NO web/db/network imports — it is deterministic and exhaustively unit-tested
(tests/test_pricing.py). The Streamlit prototype lives in agents/pricing.py and is
left untouched; this is the productized engine the FastAPI service calls.

Decision flow for ONE product (decide()):

    proposed_delta_pct  (from the LLM)   +   signals affecting this category
                 │
                 ▼
        ┌─────────────────────────────────────────────────────────────┐
        │ 1. ANTI-GOUGING BLOCK                                        │
        │    essential category  AND  a health-event up-spike on it    │
        │    AND proposed delta > 0   ->  status=blocked, hold price   │   (terminal)
        ├─────────────────────────────────────────────────────────────┤
        │ 2. %-BAND CLAMP                                              │
        │    |delta| > band  ->  clamp to ±band   (always computable)  │
        ├─────────────────────────────────────────────────────────────┤
        │ 3. MARGIN FLOOR  (only when cost is known)                   │
        │    price < cost*(1+min_margin)  ->  raise to the floor       │
        └─────────────────────────────────────────────────────────────┘
                 │
                 ▼
        GatedDecision{final_delta, final_price, status, reasons}  <- AUTHORITATIVE

Precedence of the reported status: blocked > rejected(margin) > clamped > applied.
The block is terminal; clamp and margin floor can both shape the final price, and
the status reflects the most restrictive intervention that fired.

Signals attach to a FIXED CATEGORY TAXONOMY, never to specific SKUs — that is what
makes the engine work for ANY uploaded catalogue, not just the Theiss sample.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# ---- fixed category taxonomy --------------------------------------------------
# The LLM extractor maps every product to exactly one of these. Signals reference
# these categories, so a cold snap lifts `cold_remedy` in ANY catalogue.
TAXONOMY: list[str] = [
    "cold_remedy",   # essential — flu/cold meds, cough, decongestant
    "pain_relief",   # essential — analgesics, ibuprofen, paracetamol
    "allergy",       # essential — antihistamines, hay-fever
    "digestive",     # essential — stomach, reflux, rehydration
    "first_aid",     # essential — wound care, antiseptics
    "vitamin",       # supplements, immune support
    "sunscreen",     # sun protection
    "skin_care",     # creams, lotions, cosmetic dermatology
    "foot_care",     # foot balms, anti-callus (Theiss "Feet" line)
    "muscle_joint",  # muscle/joint gels, sports recovery (Theiss "Muscles/Joints")
    "cosmetic",      # non-essential beauty
    "general",       # fallback when nothing fits — never treated as essential
]

# Essential-medicine categories: an increase on these during a health-event demand
# spike is gouging, and is BLOCKED outright. `general` is deliberately not here, so
# an un-categorisable product can never trip the block.
ESSENTIAL_CATEGORIES: list[str] = ["cold_remedy", "pain_relief", "allergy", "digestive", "first_aid"]


class PricingPolicy(BaseModel):
    """Per-tenant guardrail config. Hardcoded default for the hackathon (no policy UI);
    structured so a future PricingPolicy table can override it per category."""
    band_pct: float = Field(default=20.0, description="±X% cap vs the catalogue baseline")
    margin_floor_pct: float = Field(default=15.0, description="min gross margin over cost, when cost is known")
    essential_categories: list[str] = Field(default_factory=lambda: list(ESSENTIAL_CATEGORIES))


DEFAULT_POLICY = PricingPolicy()


# ---- value objects ------------------------------------------------------------
class CatalogItem(BaseModel):
    """One product extracted from an uploaded catalogue (PDF-agnostic)."""
    product: str
    current_price: float = Field(gt=0)
    category: str = "general"
    cost: float | None = Field(default=None, description="unit cost, if present in the PDF or supplied")


class SignalReading(BaseModel):
    """One external-signal reading. Connectors in core/tools/signals.py return these.
    `configured=False` means the connector is not wired up — it degrades honestly and
    is ignored by the engine, never fabricated."""
    source: str                      # "Open-Meteo", "Nager.Date", "seeded:supply", ...
    label: str                       # human one-liner, e.g. "Cold snap in Homburg"
    affected_categories: list[str]
    direction: str = "flat"          # "up" | "down" | "flat"
    magnitude: float = 0.0           # 0..1 strength
    health_event: bool = False       # True for weather/health demand spikes (drives anti-gouging)
    evidence: str = ""               # plain-English evidence for the UI
    fetched_at: str = ""             # ISO timestamp
    source_url: str | None = None
    configured: bool = True


class GatedDecision(BaseModel):
    """The authoritative, audited output for one product."""
    product: str
    category: str
    base_price: float
    proposed_delta_pct: float
    final_delta_pct: float
    final_price: float
    status: str                      # applied | clamped | rejected | blocked
    reasons: list[str]
    signals: list[dict] = Field(default_factory=list)   # readings that drove this product

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"


# ---- helpers ------------------------------------------------------------------
def signals_for(item: CatalogItem, signals: list[SignalReading]) -> list[SignalReading]:
    """The configured signals that actually touch this product's category."""
    return [s for s in signals if s.configured and item.category in s.affected_categories]


def _has_health_spike(item: CatalogItem, relevant: list[SignalReading]) -> bool:
    """A health-event demand spike pushing this product's category UP."""
    return any(s.health_event and s.direction == "up" for s in relevant)


# ---- the guardrail engine -----------------------------------------------------
def decide(
    item: CatalogItem,
    proposed_delta_pct: float,
    signals: list[SignalReading],
    policy: PricingPolicy = DEFAULT_POLICY,
) -> GatedDecision:
    """Gate one LLM-proposed delta through the deterministic guardrails."""
    base = round(item.current_price, 2)
    relevant = signals_for(item, signals)
    is_essential = item.category in policy.essential_categories
    reasons: list[str] = []

    # 1. ANTI-GOUGING BLOCK (terminal) — no price rise on an essential med during a spike.
    if is_essential and proposed_delta_pct > 0 and _has_health_spike(item, relevant):
        return GatedDecision(
            product=item.product, category=item.category, base_price=base,
            proposed_delta_pct=round(proposed_delta_pct, 1), final_delta_pct=0.0, final_price=base,
            status="blocked",
            reasons=[
                f"BLOCKED: '{item.category}' is an essential medicine and a health-event demand "
                f"spike is active, so a price increase would be gouging. Price held at €{base:.2f} "
                f"(the LLM proposed {proposed_delta_pct:+.1f}%)."
            ],
            signals=[s.model_dump() for s in relevant],
        )

    status = "applied"
    delta = proposed_delta_pct

    # 2. %-BAND CLAMP — primary guardrail, always computable from the baseline.
    if abs(delta) > policy.band_pct:
        delta = policy.band_pct if delta > 0 else -policy.band_pct
        status = "clamped"
        reasons.append(
            f"Clamped to the ±{policy.band_pct:.0f}% guardrail band "
            f"(LLM proposed {proposed_delta_pct:+.1f}%, allowed {delta:+.1f}%)."
        )

    price = round(base * (1 + delta / 100.0), 2)

    # 3. MARGIN FLOOR — only when cost is known; never sell below cost + min margin.
    if item.cost is not None:
        floor_price = round(item.cost * (1 + policy.margin_floor_pct / 100.0), 2)
        if price < floor_price:
            price = floor_price
            delta = round((price - base) / base * 100, 1)
            status = "rejected"
            reasons.append(
                f"Margin floor: price cannot fall below €{floor_price:.2f} "
                f"(cost €{item.cost:.2f} + {policy.margin_floor_pct:.0f}% min margin); raised to protect margin."
            )

    if not reasons:
        reasons.append(f"Applied the proposed {delta:+.1f}% — inside every guardrail.")

    return GatedDecision(
        product=item.product, category=item.category, base_price=base,
        proposed_delta_pct=round(proposed_delta_pct, 1), final_delta_pct=round(delta, 1),
        final_price=price, status=status, reasons=reasons,
        signals=[s.model_dump() for s in relevant],
    )
