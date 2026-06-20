"""Problem 7 — Dr. Theiss / Allgäuer Latschenkiefer: Targeting Analytics (Streamlit).

Branded header -> ingest pack & show detected behavioural segments -> pick a
segment + product + channel -> "Generate targeting plan" (segment × product ×
channel × OPTIMAL date/time) -> "Simulate campaign & measure lift" (pre vs post
weekly sales + headline lift %). All numbers are clearly labelled INDICATIVE.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from agents import analytics
from core import config, ui

c = ui.page_setup("theiss_analytics")

st.info(
    "All figures on this page are **INDICATIVE / synthetic** — generated from the "
    "Dr. Theiss data pack's segments and seasonal peaks with a fixed seed. They are "
    "for demonstration and must not be presented as official company data."
)

# Build the (seeded) synthetic data once and cache it across reruns.
if "tx" not in st.session_state:
    st.session_state.customers = analytics.synth_customers()
    st.session_state.tx = analytics.synth_transactions(st.session_state.customers)

tx = st.session_state.tx
catalogue = analytics.catalogue_df()

tab_patterns, tab_plan, tab_lift = st.tabs(
    ["🔍 1 · Patterns & segments", "🎯 2 · Targeting plan", "📈 3 · Measure lift"]
)

# ---------------------------------------------------------------------------
# TAB 1 — ingest data & DETECT behavioural patterns / segments
# ---------------------------------------------------------------------------
with tab_patterns:
    st.subheader("Detected behavioural segments")
    st.caption(
        "We ingest the data pack and build a transaction log, then cluster customers "
        "into behavioural segments (RFM-style: how recently, how often, how much they "
        "spend) plus their category affinity and the month their demand peaks."
    )

    pack = config.PATHS["theiss"]
    cols = st.columns([2, 1])
    with cols[0]:
        st.write(f"**Data source:** `{pack.name}`  ·  *(brand catalogue is real; prices/segments/sales are synthetic)*")
    with cols[1]:
        up = st.file_uploader("…or upload your own pack (PDF)", type=["pdf"])
        if up is not None:
            (config.DATA_OUT / up.name).write_bytes(up.getbuffer())
            st.success(f"Saved {up.name} — used to ground the targeting plan in tab 2.")

    patterns = analytics.detect_patterns(tx)
    m1, m2, m3 = st.columns(3)
    m1.metric("Customers (indicative)", f"{patterns.n_customers:,}")
    m2.metric("Transactions (indicative)", f"{patterns.n_transactions:,}")
    m3.metric("Behavioural segments", len(patterns.segments))

    st.markdown("**Segment scorecard** — sorted by average spend per customer")
    seg_df = analytics.rfm_table(tx).rename(columns={
        "segment": "Segment", "customers": "Customers",
        "avg_recency_days": "Avg recency (days)", "avg_frequency": "Avg orders",
        "avg_monetary_eur": "Avg spend €", "top_product": "Top product",
        "peak_month": "Peak month",
    })
    st.dataframe(seg_df, use_container_width=True, hide_index=True)

    st.markdown("**Season-of-purchase** — units sold per month (the timing signal)")
    seg_pick = st.selectbox(
        "View seasonality for", ["All segments"] + [s.segment for s in patterns.segments]
    )
    demand = analytics.monthly_demand(tx, None if seg_pick == "All segments" else seg_pick)
    st.line_chart(demand, y="units")
    st.caption(
        "Peaks here are the optimal windows to advertise — e.g. callus/foot-care lifts "
        "before sandal season (spring), warming/bath SKUs before winter, sport rubs "
        "around the sport calendar."
    )

    with st.expander("Raw: customer & transaction samples + segment JSON"):
        st.write("**Customers (head)**")
        st.dataframe(st.session_state.customers.head(20), use_container_width=True, hide_index=True)
        st.write("**Transactions (head)**")
        st.dataframe(tx.head(20), use_container_width=True, hide_index=True)
        st.json(patterns.model_dump())

# ---------------------------------------------------------------------------
# TAB 2 — generate targeting signals incl. OPTIMAL date/time
# ---------------------------------------------------------------------------
with tab_plan:
    st.subheader("Generate a targeting plan")
    st.caption(
        "Pick who to target and what to advertise. The agent reads the data pack and "
        "recommends the best channel and the **optimal send date + time**, with reasons."
    )

    seg_names = [s["name"] for s in analytics._SEGMENTS]
    p1, p2, p3 = st.columns(3)
    with p1:
        segment = st.selectbox("Target segment", seg_names)
    with p2:
        # default the product list to the chosen segment's product line
        seg_line = next(s["line"] for s in analytics._SEGMENTS if s["name"] == segment)
        prods = catalogue[catalogue["line"] == seg_line]["product"].tolist() or catalogue["product"].tolist()
        product = st.selectbox("Product to advertise", prods)
    with p3:
        channel = st.selectbox("Preferred channel", analytics._CHANNELS)

    if not config.HAS_KEY:
        st.caption("No API key set — a transparent heuristic plan will be used so the demo still runs.")
    if st.button("Generate targeting plan", type="primary"):
        with st.spinner("Detecting patterns and planning the send window…"):
            plan = analytics.make_targeting_plan(segment, product, channel)
        st.session_state.plan = plan

    if st.session_state.get("plan"):
        plan = st.session_state.plan
        a, b = st.columns([2, 1])
        with a:
            st.success(plan.headline)
            st.write(f"**Target segment:** {plan.target_segment}")
            st.write(f"**Product:** {plan.product}")
            st.write(f"**Channel:** {plan.channel}")
            o1, o2, o3 = st.columns(3)
            o1.metric("Optimal send date", plan.optimal_date)
            o2.metric("Optimal time", plan.optimal_time)
            o3.metric("Expected lift", f"+{plan.expected_lift_pct:.0f}%")
            st.write("**Why this plan:**")
            for r in plan.rationale:
                st.write(f"- {r}")
        with b:
            ui.confidence(plan.confidence)
        st.caption("Expected lift is an indicative estimate — measure the real lift in tab 3.")
        with st.expander("Raw targeting plan (JSON)"):
            st.json(plan.model_dump())
    else:
        st.info("Choose a segment, product and channel, then click **Generate targeting plan**.")

# ---------------------------------------------------------------------------
# TAB 3 — MEASURE whether the campaign lifted sales
# ---------------------------------------------------------------------------
with tab_lift:
    st.subheader("Simulate the campaign & measure the lift")
    st.caption(
        "After sending, we compare weekly unit sales of the marketed product BEFORE vs "
        "AFTER the campaign. The lift is computed transparently:  "
        "**lift = (mean weekly post − mean weekly pre) / mean weekly pre**."
    )

    plan = st.session_state.get("plan")
    default_seg = plan.target_segment if plan else analytics._SEGMENTS[0]["name"]
    default_prod = plan.product if plan else catalogue["product"].iloc[0]

    l1, l2 = st.columns(2)
    with l1:
        m_segment = st.selectbox("Marketed to segment", [s["name"] for s in analytics._SEGMENTS],
                                 index=[s["name"] for s in analytics._SEGMENTS].index(default_seg)
                                 if default_seg in [s["name"] for s in analytics._SEGMENTS] else 0)
    with l2:
        prod_list = catalogue["product"].tolist()
        m_product = st.selectbox("Marketed product", prod_list,
                                 index=prod_list.index(default_prod) if default_prod in prod_list else 0)

    if st.button("Simulate campaign & measure lift", type="primary"):
        weekly, lift = analytics.simulate_campaign(m_product, m_segment)
        st.session_state.lift = (weekly, lift)

    if st.session_state.get("lift"):
        weekly, lift = st.session_state.lift
        badge = {"LIFT": "✅", "NO_LIFT": "➖", "DROP": "⛔"}.get(lift.verdict, "•")
        verdict_txt = {"LIFT": "Sales went UP", "NO_LIFT": "No meaningful change", "DROP": "Sales went DOWN"}[lift.verdict]

        st.markdown(f"### {badge} {verdict_txt} for **{lift.product}**")
        h1, h2, h3 = st.columns(3)
        h1.metric("Avg weekly sales BEFORE", f"{lift.pre_mean_weekly:.0f} units")
        h2.metric("Avg weekly sales AFTER", f"{lift.post_mean_weekly:.0f} units")
        h3.metric("Sales lift", f"{lift.lift_pct:+.1f}%",
                  delta=f"{lift.post_mean_weekly - lift.pre_mean_weekly:+.0f} units/wk")

        st.markdown("**Weekly unit sales — before vs after the campaign send**")
        st.line_chart(weekly, y="units")
        st.bar_chart(
            weekly.reset_index().assign(label=lambda d: d["week"].dt.strftime("%b %d"))
                  .set_index("label")[["units"]]
        )
        st.caption(
            f"{lift.weeks_pre} weeks before vs {lift.weeks_post} weeks after the send. {lift.note}"
        )
        with st.expander("Raw lift result (JSON)"):
            st.json(lift.model_dump())
    else:
        st.info("Pick the marketed product and segment, then click **Simulate campaign & measure lift**.")
