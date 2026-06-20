"""Problem 8 — Dr. Theiss: Dynamic Pricing Agent (Streamlit page).

Pick a product (with its indicative base price), set the external signals
(weather / season-event / football / supply), and the agent suggests a price —
base → adjusted, with a per-signal breakdown, a visible guardrail clamp, and a
plain-language rationale.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from agents import pricing
from core import config, ui

c = ui.page_setup("theiss_pricing")

# ---- load the product catalogue (from the data pack, cached) --------------
@st.cache_data(show_spinner=False)
def _load(path_str: str | None):
    products, note = pricing.load_catalogue(path_str)
    return [p.model_dump() for p in products], note


theiss_path = config.PATHS.get("theiss")
path_str = str(theiss_path) if theiss_path and theiss_path.exists() else None

# Offline fallback catalogue is instant; reading the PDF needs a key, so only do
# the live read on demand to keep the page snappy and demoable with no key.
products_raw, source_note = pricing.FALLBACK_CATALOGUE, (
    "Showing the indicative catalogue from the brief. Use the button to read live base prices from the data pack."
)
if "catalogue" in st.session_state:
    products_raw, source_note = st.session_state["catalogue"]

products = [pricing.Product(**p) for p in products_raw]

st.caption(source_note)
if path_str and ui.require_key():
    if st.button("📄 Read live base prices from the data pack (PDF)"):
        with st.spinner("Reading the Dr. Theiss data pack…"):
            st.session_state["catalogue"] = _load(path_str)
        st.rerun()

st.divider()

# ---- product picker -------------------------------------------------------
left, right = st.columns([3, 2])
with left:
    names = [f"{p.name}  ·  €{p.base_price:.2f}  ({p.line or '—'})" for p in products]
    idx = st.selectbox("Product", range(len(products)), format_func=lambda i: names[i])
    product = products[idx]
    base_override = st.number_input(
        "Base price (€) — edit if you have a newer one",
        min_value=0.10, value=float(product.base_price), step=0.10, format="%.2f",
    )
    product = product.model_copy(update={"base_price": round(base_override, 2)})

with right:
    st.markdown("**External signals** — set what's happening in the world")
    weather = st.radio("Weather", ["mild", "cold", "hot"], horizontal=True)
    season = st.selectbox(
        "Season / religious-seasonal event",
        ["none", "winter", "summer", "christmas", "ramadan", "fathers_day"],
        format_func=lambda s: {
            "none": "None", "winter": "Winter", "summer": "Summer",
            "christmas": "Christmas (gifting)", "ramadan": "Ramadan",
            "fathers_day": "Father's Day",
        }[s],
    )
    football = st.selectbox(
        "Football fixture nearby",
        ["none", "home", "away"],
        format_func=lambda f: {"none": "No", "home": "Yes — home match", "away": "Yes — away match"}[f],
    )
    supply = st.select_slider("Supply-chain shortage (key active)", ["none", "moderate", "severe"], value="none")

st.markdown("**Guardrails**")
band = st.slider(
    "Permitted price band: ± % of base price (hard min/max — never exceeded)",
    min_value=5, max_value=30, value=20, step=1,
)
st.caption(
    f"Suggested price is clamped to €{product.base_price * (1 - band/100):.2f} – "
    f"€{product.base_price * (1 + band/100):.2f}. No price gouging on health items; every move is logged."
)

st.divider()

# ---- run ------------------------------------------------------------------
if st.button("💶 Suggest a price", type="primary"):
    with st.spinner("Applying signals and guardrails…"):
        r = pricing.compute_price(
            product,
            weather=weather, season=season, football=football, supply=supply,
            band_pct=float(band), source_note=source_note,
        )

    # ---- prominent base -> adjusted ----
    m1, m2, m3 = st.columns(3)
    m1.metric("Base price", f"€{r.base_price:.2f}")
    m2.metric(
        "Suggested price",
        f"€{r.suggested_price:.2f}",
        f"{r.net_pct:+.1f}% vs base",
        delta_color="normal",
    )
    with m3:
        # confidence here = how clean the signal was (clamped => less direct, lower conf)
        conf = 70.0 if r.clamped else 88.0 if any(e.direction != "flat" for e in r.effects) else 95.0
        ui.confidence(conf)

    if r.clamped:
        st.warning(
            f"⚠️ Guardrail engaged: the raw signal price was €{r.raw_price:.2f}, "
            f"clamped to €{r.suggested_price:.2f} (band €{r.floor:.2f} – €{r.ceiling:.2f})."
        )
    else:
        st.success(f"✅ Within the guardrail band €{r.floor:.2f} – €{r.ceiling:.2f} — no clamp needed.")

    # ---- per-signal breakdown table ----
    st.subheader("How each external signal moved the price")
    arrow = {"up": "🔺 up", "down": "🔻 down", "flat": "▪️ no change"}
    rows = [
        {
            "Signal": e.signal,
            "Setting": e.setting,
            "Effect": arrow[e.direction],
            "Multiplier": f"×{e.multiplier:.2f}",
            "Why": e.reason,
        }
        for e in r.effects
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(
        f"Combined raw move: base €{r.base_price:.2f} × signals = €{r.raw_price:.2f} "
        f"→ after guardrails €{r.suggested_price:.2f}."
    )

    # ---- guardrail note ----
    st.subheader("🛡️ Guardrails")
    st.info(r.guardrail_note)

    # ---- rationale ----
    st.subheader("📝 Rationale (for the customer)")
    st.write(r.rationale)
    st.caption(r.source_note)

    with st.expander("Raw pricing result (JSON)"):
        st.json(r.model_dump())
else:
    st.info("Pick a product, set the signals, then press **Suggest a price**.")
