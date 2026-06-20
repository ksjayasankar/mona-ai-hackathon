"""Problem 5 — Kohlpharma: Interview Copilot (Streamlit page).

Branded header -> pick a role from the job-offers PDF (or paste your own) ->
"Generate interview kit" -> role-relevant questions grouped by competency with
plain-language "strong answer / red flag" notes -> a standalone red-flag checklist ->
download the whole kit as markdown. Built for a NON-TECHNICAL hiring manager.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from agents import interview
from core import config, ui

c = ui.page_setup("kohlpharma")

BADGE = {"Technical": "🔧", "Problem-solving": "🧩", "Behavioural": "💬"}

st.write(
    "Pick the role you're hiring for — from your job offer or pasted in — and get a "
    "ready-to-run set of interview questions, what a good answer looks like, and the "
    "red flags to watch for. No technical background needed."
)

# ---- 1. choose a role ----------------------------------------------------

st.subheader("1 · Choose the role")

job_pdf = config.PATHS["job_offers"]
mode = st.radio(
    "Where is the role coming from?",
    ["📄 From a job offer (PDF)", "✍️ Paste my own role"],
    horizontal=True,
)

role_text = None

if mode.startswith("📄"):
    up = st.file_uploader("Upload a job-offer PDF (optional)", type=["pdf", "docx", "png", "jpg", "jpeg"])
    source = None
    if up is not None:
        source = config.DATA_OUT / up.name
        source.write_bytes(up.getbuffer())
    elif job_pdf.exists():
        source = job_pdf
        st.caption(f"Using the sample job offers: **{job_pdf.name}**")

    if source and ui.require_key():
        if "roles" not in st.session_state or st.session_state.get("roles_src") != str(source):
            if st.button("📂 Read roles from this document"):
                with st.spinner("Reading the job offer(s)…"):
                    rl = interview.list_roles(source)
                st.session_state["roles"] = rl.roles
                st.session_state["roles_src"] = str(source)

        roles = st.session_state.get("roles")
        if st.session_state.get("roles_src") == str(source) and roles:
            labels = [r.title + (f" — {r.seniority}" if r.seniority else "") for r in roles]
            idx = st.selectbox(
                "Which role are you hiring for?",
                range(len(roles)),
                format_func=lambda i: labels[i],
            )
            chosen = roles[idx]
            if chosen.summary:
                st.info(chosen.summary)
            role_text = chosen.title + (f"\nSeniority: {chosen.seniority}" if chosen.seniority else "")
            if chosen.summary:
                role_text += f"\nSummary: {chosen.summary}"
else:
    role_text = st.text_area(
        "Describe the role (a title is enough; more detail = sharper questions)",
        placeholder="e.g. Senior Pharmacovigilance Specialist — reviews drug safety reports, "
        "works with regulators, manages case deadlines.",
        height=140,
    )
    role_text = role_text.strip() or None

# ---- 2. generate the kit -------------------------------------------------

st.subheader("2 · Generate the interview kit")

if not role_text:
    st.caption("Pick or paste a role above to enable this.")

if role_text and ui.require_key() and st.button("✨ Generate interview kit", type="primary"):
    with st.spinner("Writing role-relevant questions and red flags…"):
        kit = interview.build_kit(role_text)
    st.session_state["kit"] = kit

kit = st.session_state.get("kit")
if kit is not None:
    head, conf = st.columns([3, 1])
    with head:
        st.markdown(f"### Interview kit · {kit.role_title}")
        st.write(kit.role_overview)
    with conf:
        ui.confidence(kit.confidence)

    st.markdown("#### Questions to ask")
    groups = interview.group_by_competency(kit)
    for competency, qs in groups.items():
        badge = BADGE.get(competency, "•")
        st.markdown(f"**{badge} {competency}**")
        for q in qs:
            with st.expander(q.question):
                st.markdown(f"✅ **What a strong answer includes:** {q.strong_answer}")
                st.markdown(f"🚩 **Red flag if:** {q.red_flag}")

    st.markdown("#### 🚩 Red-flag checklist (use for every candidate)")
    for item in kit.red_flag_checklist:
        st.checkbox(item, key=f"rf_{hash(item)}")

    md = interview.kit_to_markdown(kit)
    st.download_button(
        "⬇️ Download this kit (Markdown)",
        data=md,
        file_name=f"interview_kit_{kit.role_title[:40].replace(' ', '_')}.md",
        mime="text/markdown",
    )

    with st.expander("Raw kit data"):
        st.json(kit.model_dump())
