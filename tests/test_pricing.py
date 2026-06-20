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
from core.tools.signals import (
    HolidayConnector,
    SeededConnector,
    UnconfiguredConnector,
    WeatherConnector,
    SEED_SUPPLY,
    fetch_all,
)


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


# ----------------------------------------------------------------------------
# Signal connectors (core/tools/signals.py) — pure parse + honest degradation.
# No live HTTP: parse() takes fixture JSON; fetch() takes an injected getter.
# ----------------------------------------------------------------------------
def test_s1_weather_cold_snap_lifts_cold_remedy():
    data = {"daily": {"temperature_2m_min": [-5.0], "temperature_2m_max": [1.0]}}
    r = WeatherConnector(place="Homburg").parse(data, "2026-06-20T00:00:00Z")
    assert r is not None
    assert "cold_remedy" in r.affected_categories
    assert r.direction == "up"
    assert r.health_event is True
    assert r.configured is True


def test_s1b_weather_heatwave_lifts_sunscreen_but_not_a_health_event():
    data = {"daily": {"temperature_2m_min": [18.0], "temperature_2m_max": [31.0]}}
    r = WeatherConnector().parse(data, "2026-06-20T00:00:00Z")
    assert "sunscreen" in r.affected_categories
    assert r.direction == "up"
    assert r.health_event is False


def test_s1c_weather_mild_produces_no_demand_shift():
    data = {"daily": {"temperature_2m_min": [12.0], "temperature_2m_max": [19.0]}}
    r = WeatherConnector().parse(data, "2026-06-20T00:00:00Z")
    assert r.direction == "flat"
    assert r.affected_categories == []


def test_s2_weather_http_failure_degrades_honestly():
    def boom(url, timeout=0):
        raise RuntimeError("network down")

    r = WeatherConnector().fetch(_get=boom)
    # Must NOT fabricate a demand signal when the upstream is down.
    assert r is None or (r.direction == "flat" and r.affected_categories == [])


def test_s3_unconfigured_connector_degrades_honestly():
    r = UnconfiguredConnector("seeded:competitors", "Competitor price scrape").fetch()
    assert r is not None
    assert r.configured is False
    assert r.direction == "flat"
    assert r.affected_categories == []


def test_s4_holiday_connector_flags_an_imminent_holiday():
    data = [{"date": "2026-06-21", "localName": "Sommeranfang", "name": "Summer solstice"}]
    r = HolidayConnector(country="DE").parse(data, today="2026-06-20", fetched_at="2026-06-20T00:00:00Z")
    assert r is not None
    assert r.configured is True
    assert r.direction == "up"


def test_s5_seeded_connector_returns_a_snapshot_reading():
    r = SeededConnector(SEED_SUPPLY).fetch()
    assert r.configured is True
    assert r.source.startswith("seeded")
    assert r.affected_categories  # non-empty


def test_s6_fetch_all_survives_a_failing_connector():
    class Boom:
        name = "boom"

        def fetch(self):
            raise RuntimeError("kaboom")

    out = fetch_all([Boom(), SeededConnector(SEED_SUPPLY)])
    assert any(s.source.startswith("seeded") for s in out)  # the good one still came through


# ----------------------------------------------------------------------------
# Service orchestration (services/pricing.py) — OFFLINE: inject items + signals
# + a fake proposer so no Ollama / no HTTP is touched. Tests persistence,
# guardrail integration, tenant scoping, approve/reject, and fallbacks.
# ----------------------------------------------------------------------------
from core.auth import get_or_create_tenant  # noqa: E402
from services import pricing as svc  # noqa: E402


def _catalog():
    return [
        CatalogItem(product="Erkaeltungstee", current_price=5.00, category="cold_remedy"),
        CatalogItem(product="Fuss Butter", current_price=10.00, category="foot_care"),
    ]


def _fake_proposer(deltas):
    """Build a proposer callable returning fixed deltas keyed by product name."""
    def proposer(items, signals, provider=None):
        return svc.Proposal(items=[
            svc.ProposalItem(product=p, delta_pct=d, rationale="demand up") for p, d in deltas.items()
        ])
    return proposer


def test_p1_analyze_persists_and_gates_with_a_blocked_card():
    tenant = get_or_create_tenant("test-theiss-p1", "Test Theiss")
    spike = _spike(["cold_remedy"])
    report = svc.analyze(
        tenant_id=tenant, items=_catalog(), signals=[spike],
        proposer=_fake_proposer({"Erkaeltungstee": 22.0, "Fuss Butter": 8.0}),
    )
    assert report.product_count == 2
    assert report.blocked_count == 1
    by = {c["product"]: c for c in report.products}
    assert by["Erkaeltungstee"]["guardrail_status"] == "blocked"   # anti-gouging fired
    assert by["Erkaeltungstee"]["final_price"] == 5.00
    assert by["Fuss Butter"]["guardrail_status"] == "applied"
    assert by["Fuss Butter"]["final_price"] == 10.80
    # each card is persisted and approvable
    assert all(c.get("rec_id") for c in report.products)


def test_p2_approve_reject_transition_and_history():
    tenant = get_or_create_tenant("test-theiss-p2", "Test Theiss")
    report = svc.analyze(tenant_id=tenant, items=_catalog(), signals=[],
                         proposer=_fake_proposer({"Fuss Butter": 8.0}))
    rec_id = report.products[0]["rec_id"]
    approved = svc.approve(rec_id, tenant)
    assert approved["status"] == "approved"
    rejected = svc.reject(report.products[1]["rec_id"], tenant)
    assert rejected["status"] == "rejected"
    hist = svc.history(tenant)
    assert any(h["id"] == report.run_id for h in hist)


def test_p3_cross_tenant_access_is_blocked():
    owner = get_or_create_tenant("test-theiss-owner", "Owner")
    attacker = get_or_create_tenant("test-theiss-attacker", "Attacker")
    report = svc.analyze(tenant_id=owner, items=_catalog(), signals=[],
                         proposer=_fake_proposer({"Fuss Butter": 5.0}))
    rec_id = report.products[0]["rec_id"]
    try:
        svc.approve(rec_id, attacker)
        assert False, "cross-tenant approve must not succeed"
    except LookupError:
        pass


def test_p4_empty_catalogue_yields_empty_report_no_crash():
    tenant = get_or_create_tenant("test-theiss-p4", "Test Theiss")
    report = svc.analyze(tenant_id=tenant, items=[], signals=[], proposer=_fake_proposer({}))
    assert report.product_count == 0
    assert report.products == []


def test_p5_missing_proposal_holds_at_base():
    tenant = get_or_create_tenant("test-theiss-p5", "Test Theiss")
    # proposer returns nothing for the product -> default delta 0, applied at base
    report = svc.analyze(tenant_id=tenant, items=_catalog(), signals=[], proposer=_fake_proposer({}))
    by = {c["product"]: c for c in report.products}
    assert by["Fuss Butter"]["final_delta_pct"] == 0.0
    assert by["Fuss Butter"]["final_price"] == 10.00
    assert by["Fuss Butter"]["guardrail_status"] == "applied"
