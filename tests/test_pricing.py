"""P8 Dr. Theiss dynamic pricing — OFFLINE tests (no network, no LLM).

The headline tests are the deterministic guardrail engine in agents/pricing_product.py:
"LLM proposes, guardrails dispose." These are pure functions, so they run with no
Ollama and no HTTP — they ARE the product.

Coverage map (see plan-eng-review test diagram):
  T-G1  anti-gouging BLOCKs a large increase on an essential med during a health spike
  T-G2  anti-gouging BLOCKs even a SMALL increase (any increase, not just over-band)
  T-G3  %-band CLAMPs an over-aggressive increase on a non-essential
  T-G4  margin FLOOR rejects a decrease that breaches cost + min margin
  T-G5  a proposal inside all guardrails is APPLIED as-is
  T-G6  a DECREASE on an essential during a spike is allowed (anti-gouging blocks rises only)
  T-G7  a non-essential / general category is never blocked (band only)
  T-G8  BLOCK takes precedence over clamp and margin floor
"""
from agents.pricing_product import CatalogItem, SignalReading, decide


def _spike(categories, *, direction="up", health_event=True):
    return SignalReading(
        source="Open-Meteo", label="Cold snap in Homburg",
        affected_categories=categories, direction=direction, magnitude=0.8,
        health_event=health_event, evidence="Forecast low of -5 C, demand for cold remedies up.",
        fetched_at="2026-06-20T00:00:00Z",
    )


def test_g1_antigouging_blocks_large_increase_on_essential_during_spike():
    item = CatalogItem(product="Erkaeltungstee", current_price=5.00, category="cold_remedy")
    d = decide(item, 22.0, [_spike(["cold_remedy"])])
    assert d.status == "blocked"
    assert d.final_delta_pct == 0.0
    assert d.final_price == 5.00
    assert any("gouging" in r.lower() or "essential" in r.lower() for r in d.reasons)


def test_g2_antigouging_blocks_even_a_small_increase():
    item = CatalogItem(product="Ibuprofen 400", current_price=4.00, category="pain_relief")
    d = decide(item, 5.0, [_spike(["pain_relief"])])
    assert d.status == "blocked"
    assert d.final_price == 4.00


def test_g3_band_clamps_overaggressive_increase_on_nonessential():
    item = CatalogItem(product="Sonnencreme LSF50", current_price=10.00, category="sunscreen")
    heat = _spike(["sunscreen"], health_event=False)
    d = decide(item, 40.0, [heat])
    assert d.status == "clamped"
    assert d.final_delta_pct == 20.0
    assert d.final_price == 12.00


def test_g4_margin_floor_rejects_decrease_below_cost_plus_margin():
    # cost 8.00 + 15% min margin => floor price 9.20. A -18% proposal (8.20) breaches it.
    item = CatalogItem(product="Vitamin C Depot", current_price=10.00, category="vitamin", cost=8.00)
    d = decide(item, -18.0, [])
    assert d.status == "rejected"
    assert d.final_price == 9.20
    assert any("margin" in r.lower() for r in d.reasons)


def test_g5_applies_proposal_within_all_guardrails():
    item = CatalogItem(product="Fuss Butter", current_price=10.00, category="foot_care")
    d = decide(item, 8.0, [])
    assert d.status == "applied"
    assert d.final_delta_pct == 8.0
    assert d.final_price == 10.80


def test_g6_decrease_on_essential_during_spike_is_allowed():
    item = CatalogItem(product="Hustensaft", current_price=6.00, category="cold_remedy")
    d = decide(item, -10.0, [_spike(["cold_remedy"])])
    assert d.status != "blocked"
    assert d.final_delta_pct == -10.0
    assert d.final_price == 5.40


def test_g7_general_category_is_never_blocked():
    item = CatalogItem(product="Mystery Item", current_price=10.00, category="general")
    # the spike affects cold_remedy, not this item's category, so no block; band applies
    d = decide(item, 30.0, [_spike(["cold_remedy"])])
    assert d.status == "clamped"
    assert d.final_price == 12.00


def test_g8_block_takes_precedence_over_clamp_and_margin():
    item = CatalogItem(product="Nasenspray", current_price=5.00, category="cold_remedy", cost=4.00)
    d = decide(item, 50.0, [_spike(["cold_remedy"])])
    assert d.status == "blocked"
    assert d.final_price == 5.00
