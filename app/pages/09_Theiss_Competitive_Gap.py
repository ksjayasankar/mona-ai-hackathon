"""Problem 9 — Dr. Theiss / Allgäuer: Competitive Gap Agent (Streamlit page).

Benchmark the Allgäuer product set against competitors and surface the white-space
gaps competitors fill but Allgäuer does not — each with a concrete own-brand idea.
Thin UI: branded header -> sample/upload -> run agent -> benchmark matrix + ranked
white-space opportunities. Raw JSON lives in an expander.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from agents import gaps
from core import config, ui

c = ui.page_setup("theiss_gaps")

st.write(
    "Reads the Allgäuer Latschenkiefer catalogue **and** the competitor landscape from the "
    "Dr. Theiss data pack, then benchmarks them on a need × format grid to find the "
    "**white-space** competitors fill but Allgäuer does not — with a product idea for each."
)

# --- pick the source: the real data pack (one click) or upload your own ----
sample = config.PATHS["theiss"]
col1, col2 = st.columns([2, 1])
with col1:
    up = st.file_uploader("Upload a brand/competitor data pack (PDF)", type=["pdf"])
with col2:
    use_sample = st.checkbox("Use the Allgäuer data pack", value=True,
                             help=f"Loads {sample.name}")

target = None
if up is not None:
    target = config.DATA_OUT / up.name
    target.write_bytes(up.getbuffer())
elif use_sample and sample.exists():
    target = sample

if target:
    st.caption(f"Source: `{target.name}`")
else:
    st.info("Tick the box to load the sample, or upload a PDF.")

# --- optional: enrich with live web competitor signals ---------------------
with st.expander("🌐 Optional: enrich with live web competitor signals (firecrawl)"):
    st.caption(
        "The data pack already contains a competitor landscape, which is enough. If you have "
        "fresh notes from a web search of the competitors' current ranges, paste one per line "
        "and they'll be folded in as extra signals."
    )
    extra_raw = st.text_area("Extra competitor signals (one per line)", height=100,
                             placeholder="e.g. Scholl launched a foam-format diabetic foot cream in 2026")
extra_signals = [ln.strip() for ln in (extra_raw or "").splitlines() if ln.strip()]

# --- run --------------------------------------------------------------------
if target and ui.require_key() and st.button("Run competitive gap analysis", type="primary"):
    with st.spinner("Reading the catalogue and competitor landscape, then benchmarking…"):
        res = gaps.run_gap_analysis(target, extra_signals=extra_signals or None)
    st.session_state["gap_res"] = res

res = st.session_state.get("gap_res")
if res is not None:
    a = res.analysis

    # headline verdict + confidence
    top, side = st.columns([3, 1])
    with top:
        st.subheader("🧭 Where the white-space is")
        st.success(a.headline)
        st.write(
            f"**{a.product_set.brand}** covers "
            f"**{len(a.product_set.products)} products** across "
            f"**{len(a.product_set.needs_covered)} needs** and "
            f"**{len(a.product_set.formats_covered)} formats**, benchmarked against "
            f"**{len(a.landscape.competitors)} competitors**."
        )
    with side:
        ui.confidence(a.confidence)

    # --- ranked white-space opportunities (the core deliverable) -----------
    st.markdown("### 🎯 White-space opportunities (ranked)")
    st.caption("Gaps competitors fill but Allgäuer does not. Each has an own-brand product idea.")
    for i, g in enumerate(a.white_space, 1):
        with st.container(border=True):
            h, p = st.columns([4, 1])
            with h:
                st.markdown(f"**{i}. {g.need.title()} · {g.format}**")
                st.write(f"💡 **Product idea:** {g.product_idea}")
                st.caption(f"Why: {g.rationale}")
                st.caption(f"Covered today by: {g.covered_by_competitors or '—'}")
            with p:
                st.metric("Priority", f"{g.priority:.0f}")

    # --- where Allgäuer is already strong ----------------------------------
    if a.strengths:
        st.markdown("### 💪 Where Allgäuer already leads")
        for s in a.strengths:
            st.write(f"- {s}")

    # --- benchmark matrix: need × format, who covers what ------------------
    st.markdown("### 📊 Benchmark matrix (need × format)")
    st.caption("✅ Allgäuer · 🟠 competitor only · ⬜ nobody. Orange cells are the opportunity.")

    def _mark(cell):
        if cell.allgaeuer:
            return "✅"
        if cell.competitors:
            return "🟠"
        return "⬜"

    grid: dict[str, dict[str, str]] = {}
    for cell in a.benchmark:
        grid.setdefault(cell.need.title(), {})[cell.format] = _mark(cell)
    if grid:
        formats = sorted({c.format for c in a.benchmark})
        matrix = pd.DataFrame(
            [{"Need": need, **{f: row.get(f, "") for f in formats}} for need, row in grid.items()]
        ).set_index("Need")
        st.dataframe(matrix, use_container_width=True)

    # --- supporting tables -------------------------------------------------
    t1, t2 = st.tabs(["Allgäuer product set", "Competitor landscape"])
    with t1:
        st.dataframe(
            [p.model_dump() for p in a.product_set.products], use_container_width=True
        )
    with t2:
        st.dataframe(
            [cmp.model_dump() for cmp in a.landscape.competitors], use_container_width=True
        )

    with st.expander("Raw analysis (JSON)"):
        st.json(res.model_dump())
