"""Mona AI Hackathon 2026 — landing page.

Ten customer agents, grouped into three clusters. Each card is its own customer
deliverable; the sidebar pages are the live demos.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from core import config

st.set_page_config(page_title="Mona AI · Agent Suite", page_icon="🤖", layout="wide")

st.title("🤖 Mona AI — Customer Agent Suite")
st.caption("Ten customer feature requests, ten agents, one app. Pick a customer from the sidebar to run their demo.")

if not config.HAS_KEY:
    st.warning("🔑 No `GEMINI_API_KEY` set yet. Paste your Gemini key into `.env` at the repo root to run the live demos.")

CLUSTERS = [
    ("📄 Document Intelligence", "Ingest → read with Claude vision → validate → verdict. Injection-resistant.",
     ["globus", "leistenschneider", "persowerk", "rheinmetall"]),
    ("📈 Dr. Theiss Marketing Suite", "One customer, one data pack, four marketing agents.",
     ["theiss_reels", "theiss_analytics", "theiss_pricing", "theiss_gaps"]),
    ("👥 HR Action Agents", "Time-sensitive, action-taking HR helpers.",
     ["uks", "kohlpharma"]),
]

for title, sub, keys in CLUSTERS:
    st.markdown(f"### {title}")
    st.caption(sub)
    cols = st.columns(len(keys))
    for col, key in zip(cols, keys):
        c = config.CUSTOMERS[key]
        with col:
            st.markdown(
                f"<div style='border:1px solid #333;border-left:5px solid {c['color']};"
                f"border-radius:8px;padding:0.8rem;height:100%'>"
                f"<div style='font-size:0.75rem;color:#888'>P{c['n']} · {c['company']}</div>"
                f"<div style='font-size:1.1rem;font-weight:700'>{c['icon']} {c['agent']}</div>"
                f"<div style='color:#aaa;font-size:0.85rem;margin-top:0.3rem'>{c['promise']}</div></div>",
                unsafe_allow_html=True,
            )
    st.write("")

st.divider()
st.caption("Built for the Mona AI Hackathon 2026 · powered by Claude · KISS / YAGNI / customer-centric.")
