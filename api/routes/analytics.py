"""P7 Dr. Theiss — Targeting Analytics API route (authenticated, tenant-scoped).

Stateless and DETERMINISTIC: no DB, no LLM. One POST runs the whole flow on the
data pack's INDICATIVE synthetic transactions and returns, in a single response,
all four acceptance boxes:

  1. INGEST + SEGMENT   detect_patterns()  -> per-segment RFM rows
  2. TARGETING SIGNAL   a recommended segment x product x channel
  3. OPTIMAL DATE/TIME  the best send date + time-of-day (grounded in the pack's peaks)
  4. MEASURED LIFT      simulate_campaign() -> before/after weekly sales + % uplift

The targeting plan uses the agent's deterministic heuristic (no LLM call) so the
demo is instant and never burns the Gemini budget. The optional `use_llm` flag
can ask Claude/Gemini for a richer rationale, but the default is fully offline.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from agents import analytics
from core.auth import Principal, current_principal

router = APIRouter(prefix="/agents/analytics", tags=["analytics"])


def _weekly_points(weekly) -> list[dict]:
    """Flatten the weekly before/after dataframe to JSON-friendly points."""
    out: list[dict] = []
    for idx, row in weekly.reset_index().iterrows():
        out.append({
            "week": row["week"].date().isoformat(),
            "units": int(row["units"]),
            "phase": str(row["phase"]),
        })
    return out


@router.post("")
def run_analytics(
    channel: str | None = None,
    use_llm: bool = False,
    principal: Principal = Depends(current_principal),
) -> dict:
    """Run the full targeting-analytics flow on the indicative transactions.

    Returns segments + the recommended targeting plan (segment/product/channel +
    optimal date/time) + a measured campaign lift. Deterministic by default.
    """
    tx = analytics.synth_transactions()

    # 1. patterns / segments (plain pandas RFM)
    patterns = analytics.detect_patterns(tx)

    # 2 + 3. pick the highest-value segment, advertise its top product, optimal date/time
    top = patterns.segments[0]
    chosen_channel = channel or analytics._CHANNELS[0]
    if use_llm:
        plan = analytics.make_targeting_plan(top.segment, top.top_product, chosen_channel)
    else:
        plan = analytics._heuristic_plan(top.segment, top.top_product, chosen_channel)

    # 4. simulate + MEASURE lift for that segment x product
    weekly, lift = analytics.simulate_campaign(plan.product, plan.target_segment)

    # monthly demand for the chosen segment — shows the seasonal pattern behind the date
    season = analytics.monthly_demand(tx, plan.target_segment)
    season_points = [
        {"month": int(m), "units": int(u)}
        for m, u in zip(season.index, season["units"])
    ]

    return {
        "tenant_id": principal.tenant_id,
        "note": patterns.note,
        "n_customers": patterns.n_customers,
        "n_transactions": patterns.n_transactions,
        "segments": [s.model_dump() for s in patterns.segments],
        "plan": plan.model_dump(),
        "lift": lift.model_dump(),
        "weekly": _weekly_points(weekly),
        "season": season_points,
        "channels": analytics._CHANNELS,
    }
