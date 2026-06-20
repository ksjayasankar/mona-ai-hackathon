"""Shared Streamlit helpers so every page looks like a branded customer product."""
from __future__ import annotations

import streamlit as st

from core import config


def page_setup(customer_key: str) -> dict:
    """Set page config + render the customer-branded header. Returns the customer dict."""
    c = config.CUSTOMERS[customer_key]
    st.set_page_config(page_title=f"{c['agent']} · {c['company']}", page_icon=c["icon"], layout="wide")
    st.markdown(
        f"""
        <div style="border-left:6px solid {c['color']};padding:0.4rem 1rem;margin-bottom:0.6rem">
          <div style="font-size:0.85rem;color:#888">PROBLEM {c['n']} · {c['company']} · {c['city']} · {c['dept']}</div>
          <div style="font-size:1.7rem;font-weight:700">{c['icon']} {c['agent']}</div>
          <div style="color:#aaa;margin-top:0.2rem">{c['promise']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("📋 What the customer asked for", expanded=False):
        st.write(f"**Pain:** {c['pain']}")
        st.write(f"**Our promise:** {c['promise']}")
    return c


def require_key() -> bool:
    """Show a friendly banner if the API key is missing. Returns True if ok to run."""
    if config.HAS_KEY:
        return True
    st.warning("🔑 No `ANTHROPIC_API_KEY` set. Paste your key into the `.env` file at the repo root, then rerun.")
    return False


def confidence(pct: float) -> None:
    color = "#0a7d3f" if pct >= 75 else "#b58900" if pct >= 50 else "#b3122b"
    st.markdown(
        f"<div style='font-size:0.8rem;color:#888'>Confidence</div>"
        f"<div style='font-size:2rem;font-weight:700;color:{color}'>{pct:.0f}%</div>",
        unsafe_allow_html=True,
    )
