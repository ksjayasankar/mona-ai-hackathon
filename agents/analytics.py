"""Problem 7 — Dr. Theiss / Allgäuer Latschenkiefer: Targeting Analytics Agent.

Boxes to check (from the customer brief):
  [x] ingest customer data and DETECT behavioural patterns / segments
  [x] generate targeting signals incl. the OPTIMAL date/time to advertise
  [x] MEASURE afterwards whether it lifted sales for the marketed product

Approach
--------
The data pack (PATHS["theiss"]) is a PDF: brand facts, a product catalogue and a
small *indicative* product table (SKU, line, pack, price, peak season, target
segment). The brief asks us to "build behaviour patterns on the (to-be-generated)
transactions log: RFM, season-of-purchase, category affinity".

So we do exactly that:
  1. read the pack with Claude to confirm the catalogue / segments (core.llm),
  2. SYNTHESISE a small, FIXED-SEED customer + transactions dataset that is
     consistent with the pack (same SKUs, segments, seasonal peaks). Clearly
     labelled INDICATIVE — never presented as real company data.
  3. derive behavioural segments with plain pandas (RFM-style + category affinity),
  4. ask Claude for a targeting plan (segment × product × channel × optimal
     send date/time) with a written rationale,
  5. simulate a campaign and MEASURE lift with a transparent before/after rule:
     lift = (mean weekly sales POST − mean weekly sales PRE) / mean weekly sales PRE.

Everything numeric here is synthetic-but-plausible and deterministic (seeded), so
the demo runs identically every time without an API key for steps 1 & 3 falling
back gracefully.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from core import ingest, llm

TODAY = date(2026, 6, 20)  # hackathon "today"; keep deterministic for the demo
SEED = 20260620            # fixed seed so the synthetic data never changes

SYSTEM = (
    "You are a retail marketing analytics advisor for Allgäuer Latschenkiefer "
    "(a foot/leg/muscle care brand of Dr. Theiss Naturwaren). You are given an "
    "INDICATIVE customer-segment and product table plus the brand's seasonal "
    "timing notes. Recommend a concrete, practical targeting plan. Be specific "
    "about the single best send date and time-of-day and explain the reasoning in "
    "plain language a non-technical marketer can act on. Do not invent products or "
    "segments outside the table you are given."
)

# ---------------------------------------------------------------------------
# Indicative product catalogue — transcribed from the data pack's §3 table.
# (SKU, product, line, price €, peak season, target segment)
# These are the pack's own synthetic/indicative figures.
# ---------------------------------------------------------------------------
_PRODUCTS: list[dict] = [
    {"sku": "ALK-FB-01", "product": "Fuß Butter", "line": "Feet", "price": 7.71, "peak": "Autumn-Winter", "segment": "45+ dry-skin, women"},
    {"sku": "ALK-FB-02", "product": "Sole Fußbad", "line": "Feet", "price": 6.49, "peak": "Winter", "segment": "Wellness, 50+"},
    {"sku": "ALK-FB-03", "product": "Hornhaut Reduziercreme", "line": "Feet", "price": 6.99, "peak": "Spring (sandal prep)", "segment": "Women 30-60"},
    {"sku": "ALK-FB-04", "product": "Hornhaut Entferner Maske", "line": "Feet", "price": 8.49, "peak": "Spring-Summer", "segment": "Women 25-45"},
    {"sku": "ALK-FB-05", "product": "10 % Urea Fußcreme", "line": "Feet", "price": 7.25, "peak": "All year", "segment": "Diabetic / very dry skin"},
    {"sku": "ALK-FB-06", "product": "Fußpflege Deospray", "line": "Feet", "price": 6.10, "peak": "Summer", "segment": "Active / men 20-45"},
    {"sku": "ALK-LG-01", "product": "5 in 1 Beinlotion", "line": "Legs", "price": 9.95, "peak": "Summer", "segment": "Women 35-65"},
    {"sku": "ALK-LG-02", "product": "Bein Frische Gel", "line": "Legs", "price": 8.20, "peak": "Summer", "segment": "Travel / standing jobs"},
    {"sku": "ALK-LG-03", "product": "Besenreiser Pflegebalsam", "line": "Legs", "price": 11.49, "peak": "Spring-Summer", "segment": "Women 40-65"},
    {"sku": "ALK-MG-01", "product": "Mobil Gel", "line": "Muscles/Joints", "price": 5.83, "peak": "Autumn-Winter", "segment": "Active 30+, 55+ joints"},
    {"sku": "ALK-MG-02", "product": "Mobil Einreibung Extra Stark", "line": "Muscles/Joints", "price": 8.90, "peak": "Winter / sport", "segment": "Sport, 25-55"},
    {"sku": "ALK-MG-03", "product": "Mobil Eisspray akut", "line": "Muscles/Joints", "price": 9.40, "peak": "Sport season", "segment": "Athletes, teams"},
    {"sku": "ALK-MG-04", "product": "Franzbranntwein", "line": "Muscles/Joints", "price": 6.75, "peak": "All year", "segment": "Traditional 55+"},
    {"sku": "ALK-MG-05", "product": "Wärmendes Intensiv Gel", "line": "Muscles/Joints", "price": 8.30, "peak": "Winter", "segment": "45+ tension/back"},
    {"sku": "ALK-CB-01", "product": "Ur Bonbons", "line": "Cough drops", "price": 2.49, "peak": "Cold season", "segment": "Mass-market"},
]

# Behavioural segments we cluster customers into (consistent with the pack's
# target-segment language). Each carries the category it leans toward + the month
# its demand peaks (1-12) so timing signals are grounded in the pack.
_SEGMENTS: list[dict] = [
    {"name": "Sandal-Season Foot Care", "line": "Feet", "peak_month": 5, "blurb": "Women 30-60 prepping callus-free feet for spring/summer sandals."},
    {"name": "Diabetic / Dry-Skin Care", "line": "Feet", "peak_month": 11, "blurb": "Year-round buyers of urea creams; medical, repeat-purchase."},
    {"name": "Tired-Legs Summer", "line": "Legs", "peak_month": 7, "blurb": "Standing-job & travel buyers of cooling leg gels in hot months."},
    {"name": "Sport & Recovery", "line": "Muscles/Joints", "peak_month": 9, "blurb": "Athletes/teams buying Eisspray & rubs around the sport season."},
    {"name": "Winter Warmth 55+", "line": "Muscles/Joints", "peak_month": 1, "blurb": "Older buyers of warming gels / baths in cold months."},
]

_CHANNELS = ["Instagram", "Facebook", "Pharmacy e-mail newsletter", "In-pharmacy QR / leaflet"]


# ===========================================================================
# Pydantic schemas
# ===========================================================================
class TargetingPlan(BaseModel):
    """A concrete targeting plan for one segment × product, with optimal timing."""

    headline: str = Field(description="One-line, customer-friendly summary of the plan")
    target_segment: str = Field(description="The behavioural segment to target (use a given segment name)")
    product: str = Field(description="The product/SKU to advertise (use a given product name)")
    channel: str = Field(description="Single best channel to reach this segment")
    optimal_date: str = Field(description="Best calendar date to send, YYYY-MM-DD, in the next ~12 weeks")
    optimal_time: str = Field(description="Best local time-of-day to send, e.g. '19:30'")
    rationale: list[str] = Field(description="3-5 short plain-language reasons (seasonality, behaviour, channel fit)")
    expected_lift_pct: float = Field(description="Rough expected sales uplift %, a small realistic number", ge=0, le=200)
    confidence: float = Field(description="0-100 confidence in this plan", ge=0, le=100)


class SegmentRow(BaseModel):
    segment: str
    customers: int
    avg_recency_days: float
    avg_frequency: float
    avg_monetary_eur: float
    top_product: str
    peak_month: int


class PatternResult(BaseModel):
    """Detected behavioural segments + the customer/transaction tables behind them."""

    segments: list[SegmentRow]
    n_customers: int
    n_transactions: int
    note: str


class LiftResult(BaseModel):
    """Before/after measurement of a simulated campaign."""

    product: str
    segment: str
    pre_mean_weekly: float
    post_mean_weekly: float
    lift_pct: float
    verdict: str           # LIFT | NO_LIFT | DROP
    weeks_pre: int
    weeks_post: int
    note: str


# ===========================================================================
# 1 + 2. Ingest the pack & synthesise a consistent customer dataset
# ===========================================================================
def catalogue_df() -> pd.DataFrame:
    """The indicative product catalogue as a dataframe."""
    return pd.DataFrame(_PRODUCTS)


def segments_meta_df() -> pd.DataFrame:
    """The behavioural-segment definitions as a dataframe."""
    return pd.DataFrame(_SEGMENTS)


def synth_customers(n: int = 600) -> pd.DataFrame:
    """Deterministic synthetic customer base, consistent with the pack's segments.

    Labelled INDICATIVE. Each customer is assigned a behavioural segment and a
    home region; demographics follow the segment's target description loosely.
    """
    rng = np.random.default_rng(SEED)
    seg_names = [s["name"] for s in _SEGMENTS]
    # uneven, realistic segment sizes (foot care is the brand's core)
    weights = np.array([0.30, 0.18, 0.17, 0.20, 0.15])
    seg = rng.choice(seg_names, size=n, p=weights)
    regions = rng.choice(["Saarland", "Bayern", "NRW", "Baden-W.", "Hessen", "online-DE"], size=n)
    ages = np.clip(rng.normal(52, 14, n).round().astype(int), 19, 88)
    rows = pd.DataFrame({
        "customer_id": [f"C{1000 + i}" for i in range(n)],
        "segment": seg,
        "age": ages,
        "region": regions,
    })
    return rows


def synth_transactions(customers: pd.DataFrame | None = None) -> pd.DataFrame:
    """Deterministic synthetic transaction log consistent with seasonal peaks.

    Columns: customer_id, segment, date, sku, product, line, qty, price, channel,
    month. Purchase month is biased toward each segment's peak month so the
    season-of-purchase pattern is real and detectable.
    """
    if customers is None:
        customers = synth_customers()
    rng = np.random.default_rng(SEED + 1)
    prod = catalogue_df()
    seg_meta = {s["name"]: s for s in _SEGMENTS}
    # products available per product line, for affinity
    by_line: dict[str, pd.DataFrame] = {ln: prod[prod["line"] == ln] for ln in prod["line"].unique()}

    start = date(2025, 7, 1)  # ~1 year of history ending near TODAY
    days_span = (TODAY - start).days

    records: list[dict] = []
    for _, cust in customers.iterrows():
        meta = seg_meta[cust["segment"]]
        line = meta["line"]
        peak_m = meta["peak_month"]
        n_orders = int(rng.integers(1, 8))  # frequency varies per customer
        pool = by_line.get(line, prod)
        for _ in range(n_orders):
            # month biased toward the segment's peak (+/- a couple months)
            month = int((peak_m - 1 + rng.integers(-2, 3)) % 12) + 1
            # pick a year so the date falls inside [start, TODAY]
            for yr in (2025, 2026):
                try:
                    day = int(rng.integers(1, 28))
                    d = date(yr, month, day)
                except ValueError:
                    continue
                if start <= d <= TODAY:
                    break
            else:
                d = TODAY - timedelta(days=int(rng.integers(1, days_span)))
            p = pool.sample(1, random_state=int(rng.integers(0, 1_000_000))).iloc[0]
            records.append({
                "customer_id": cust["customer_id"],
                "segment": cust["segment"],
                "date": d,
                "sku": p["sku"],
                "product": p["product"],
                "line": p["line"],
                "qty": int(rng.integers(1, 4)),
                "price": float(p["price"]),
                "channel": rng.choice(_CHANNELS),
            })
    tx = pd.DataFrame(records)
    tx["date"] = pd.to_datetime(tx["date"])
    tx["month"] = tx["date"].dt.month
    tx["revenue"] = (tx["qty"] * tx["price"]).round(2)
    return tx.sort_values("date").reset_index(drop=True)


# ===========================================================================
# 3. DETECT behavioural patterns / segments (plain pandas — transparent)
# ===========================================================================
def detect_patterns(tx: pd.DataFrame | None = None) -> PatternResult:
    """RFM-style + category-affinity segmentation from the transaction log."""
    if tx is None:
        tx = synth_transactions()
    asof = pd.Timestamp(TODAY)
    seg_meta = {s["name"]: s for s in _SEGMENTS}

    rows: list[SegmentRow] = []
    for seg_name, g in tx.groupby("segment"):
        per_cust = g.groupby("customer_id").agg(
            recency=("date", lambda s: (asof - s.max()).days),
            frequency=("date", "count"),
            monetary=("revenue", "sum"),
        )
        top_product = g.groupby("product")["qty"].sum().idxmax()
        rows.append(SegmentRow(
            segment=str(seg_name),
            customers=int(per_cust.shape[0]),
            avg_recency_days=round(float(per_cust["recency"].mean()), 1),
            avg_frequency=round(float(per_cust["frequency"].mean()), 2),
            avg_monetary_eur=round(float(per_cust["monetary"].mean()), 2),
            top_product=str(top_product),
            peak_month=int(seg_meta[str(seg_name)]["peak_month"]),
        ))
    rows.sort(key=lambda r: r.avg_monetary_eur, reverse=True)
    return PatternResult(
        segments=rows,
        n_customers=int(tx["customer_id"].nunique()),
        n_transactions=int(tx.shape[0]),
        note="INDICATIVE / synthetic data, generated from the data pack's segments and seasonal peaks (fixed seed).",
    )


def rfm_table(tx: pd.DataFrame) -> pd.DataFrame:
    """Per-segment RFM summary as a display-ready dataframe."""
    pr = detect_patterns(tx)
    return pd.DataFrame([r.model_dump() for r in pr.segments])


def monthly_demand(tx: pd.DataFrame, segment: str | None = None) -> pd.DataFrame:
    """Units per month (optionally for one segment) — drives the season chart."""
    g = tx if segment is None else tx[tx["segment"] == segment]
    s = g.groupby("month")["qty"].sum().reindex(range(1, 13), fill_value=0)
    return pd.DataFrame({"month": s.index, "units": s.values}).set_index("month")


# ===========================================================================
# 4. Generate targeting signals incl. OPTIMAL date/time
# ===========================================================================
def _next_date_in_month(peak_month: int) -> date:
    """Next occurrence of the 1st of the segment's peak month from TODAY."""
    yr = TODAY.year if peak_month >= TODAY.month else TODAY.year + 1
    # aim ~mid-month for the campaign send
    return date(yr, peak_month, 15)


def _heuristic_plan(segment: str, product: str, channel: str) -> TargetingPlan:
    """Deterministic fallback plan when no API key is available."""
    meta = next((s for s in _SEGMENTS if s["name"] == segment), _SEGMENTS[0])
    d = _next_date_in_month(meta["peak_month"])
    # newsletter best mid-morning; social best evening
    t = "10:00" if "newsletter" in channel.lower() or "leaflet" in channel.lower() else "19:30"
    return TargetingPlan(
        headline=f"Promote {product} to '{segment}' on {channel} around {d.isoformat()}.",
        target_segment=segment,
        product=product,
        channel=channel,
        optimal_date=d.isoformat(),
        optimal_time=t,
        rationale=[
            f"This segment's demand peaks in month {meta['peak_month']} — send just before the peak.",
            f"{meta['blurb']}",
            f"{channel} matches how this audience engages; evenings/mornings see the best open rates.",
            "Indicative timing derived from the data pack's seasonal notes.",
        ],
        expected_lift_pct=12.0,
        confidence=62.0,
    )


def make_targeting_plan(segment: str, product: str, channel: str | None = None,
                        use_pack: bool = True) -> TargetingPlan:
    """Ask Claude for a targeting plan; fall back to a deterministic heuristic.

    If `use_pack`, the data-pack PDF is ingested so the model grounds its advice in
    the real catalogue/segments. On any error (no key, etc.) we return a transparent
    heuristic so the demo always works.
    """
    from core import config

    meta = next((s for s in _SEGMENTS if s["name"] == segment), _SEGMENTS[0])
    channel = channel or _CHANNELS[0]
    seg_lines = "\n".join(f"- {s['name']} (line {s['line']}, peak month {s['peak_month']}): {s['blurb']}" for s in _SEGMENTS)
    prod_lines = "\n".join(f"- {p['product']} [{p['sku']}], line {p['line']}, €{p['price']}, peak {p['peak']}, segment {p['segment']}" for p in _PRODUCTS)
    brief = (
        f"Today is {TODAY.isoformat()}.\n"
        f"Build a targeting plan for this segment and product.\n\n"
        f"TARGET SEGMENT: {segment}\nPRODUCT: {product}\nPREFERRED CHANNEL: {channel}\n\n"
        f"Behavioural segments (indicative):\n{seg_lines}\n\n"
        f"Product catalogue (indicative):\n{prod_lines}\n\n"
        "Timing notes from the brand: sandal-season callus spike Mar-Jun; winter for "
        "warming/bath SKUs; sport calendar for Mobil/Eisspray. Pick the single best "
        "send DATE (within ~12 weeks of today, just BEFORE the demand peak) and the best "
        "TIME of day for the chosen channel. Keep expected_lift_pct modest and realistic."
    )

    blocks: list[dict] = []
    if use_pack:
        try:
            p = config.PATHS["theiss"]
            if p.exists():
                blocks = ingest.file_to_blocks(p)
        except Exception:
            blocks = []
    blocks.append({"type": "text", "text": brief})

    try:
        plan = llm.extract(TargetingPlan, blocks, system=SYSTEM)
        # make sure the chosen segment/product echo what the user picked
        plan.target_segment = segment
        plan.product = product
        plan.channel = channel
        return plan
    except Exception:
        return _heuristic_plan(segment, product, channel)


# ===========================================================================
# 5. MEASURE lift — transparent before/after on weekly sales
# ===========================================================================
def simulate_campaign(product: str, segment: str, true_lift: float = 0.18,
                      weeks: int = 8) -> tuple[pd.DataFrame, LiftResult]:
    """Simulate weekly unit sales of `product` before vs after a campaign send.

    Returns (weekly_df, LiftResult). The series is synthetic-but-plausible and
    seeded, so the chart is stable. `true_lift` is the planted effect; the measured
    lift is computed transparently from the data, NOT just echoed back:

        lift = (mean weekly sales POST − mean weekly sales PRE) / mean weekly sales PRE
    """
    rng = np.random.default_rng(SEED + abs(hash((product, segment))) % 10_000)
    # baseline weekly units with mild noise; campaign send at the boundary
    base = float(rng.integers(80, 160))
    pre = np.clip(rng.normal(base, base * 0.10, weeks), 1, None)
    post = np.clip(rng.normal(base * (1 + true_lift), base * 0.10, weeks), 1, None)
    units = np.concatenate([pre, post]).round().astype(int)

    week_start = TODAY - timedelta(weeks=weeks)
    dates = [pd.Timestamp(week_start) + pd.Timedelta(weeks=i) for i in range(2 * weeks)]
    phase = ["pre"] * weeks + ["post"] * weeks
    weekly = pd.DataFrame({"week": dates, "units": units, "phase": phase}).set_index("week")

    pre_mean = float(np.mean(units[:weeks]))
    post_mean = float(np.mean(units[weeks:]))
    lift = (post_mean - pre_mean) / pre_mean if pre_mean else 0.0
    verdict = "LIFT" if lift >= 0.03 else "DROP" if lift <= -0.03 else "NO_LIFT"

    result = LiftResult(
        product=product,
        segment=segment,
        pre_mean_weekly=round(pre_mean, 1),
        post_mean_weekly=round(post_mean, 1),
        lift_pct=round(lift * 100, 1),
        verdict=verdict,
        weeks_pre=weeks,
        weeks_post=weeks,
        note="INDICATIVE / synthetic weekly sales. Lift = (mean post − mean pre) / mean pre.",
    )
    return weekly, result
