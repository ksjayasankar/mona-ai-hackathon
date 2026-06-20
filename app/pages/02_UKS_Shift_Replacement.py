"""Problem 2 — UKS: Shift Replacement Agent (Streamlit page).

Message it the gap (who's sick / role / when) -> it finds AVAILABLE + QUALIFIED staff
from the real roster -> drafts the outreach SMS to the best picks -> "Send" (simulated).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from agents import shift
from core import config, ui

c = ui.page_setup("uks")

# A realistic, pre-filled gap message so the page demos with one click.
DEFAULT_MSG = (
    "Felix Haddad (HOSP-1059) just called in sick for tonight's ICU night shift "
    "(Sat 06/20, 19:00-07:00). He's a Registered Nurse, ICU needs BLS + ACLS. "
    "Find me cover ASAP."
)

st.markdown("### 🚨 Report a shift gap")
st.caption(
    "Paste the sick-call message exactly as it came in. The agent reads it, finds "
    "qualified and available staff from tonight's roster, and drafts the outreach."
)

msg = st.text_area("Sick-call message", value=DEFAULT_MSG, height=110)

# Structured fallbacks let the candidate search run even without an API key.
with st.expander("⚙️ Or set the gap manually (used if no AI key / to override)"):
    col1, col2, col3 = st.columns(3)
    with col1:
        m_role = st.text_input("Role needed", value="Registered Nurse")
        m_person = st.text_input("Who called in sick", value="Felix Haddad (HOSP-1059)")
    with col2:
        m_dept = st.text_input("Department / ward", value="ICU")
        m_shift = st.selectbox("Shift", ["night", "day"], index=0)
    with col3:
        m_day = st.text_input("Which day (or 'tonight')", value="tonight")
        m_certs = st.text_input("Required certifications (comma-sep)", value="BLS, ACLS")

go = st.button("🔎 Find cover", type="primary")

if go:
    # 1) Understand the gap. Use Claude on the free text if a key is present;
    #    otherwise fall back to the manual fields so the demo still works.
    use_ai = config.HAS_KEY and msg.strip()
    if use_ai:
        with st.spinner("Reading the sick-call message…"):
            try:
                req = shift.parse_gap_message(msg)
            except Exception as e:
                st.warning(f"Couldn't reach the AI parser ({e}); using the manual fields.")
                use_ai = False
    if not use_ai:
        req = shift.GapRequest(
            person_out=m_person or None,
            role=m_role or None,
            department=m_dept or None,
            shift=m_shift,
            day_label=m_day or None,
            required_certs=[x.strip() for x in m_certs.split(",") if x.strip()],
        )

    # 2) Deterministic search over the real roster (no API key needed).
    with st.spinner("Screening the roster for qualified, available, rested staff…"):
        r = shift.find_replacements(req, top_n=3)

    st.session_state["shift_result"] = r

# Render the last result (persists across "Send" button clicks).
r = st.session_state.get("shift_result")
if r:
    st.divider()
    top, side = st.columns([3, 1])
    with top:
        st.subheader("✅ Cover options found" if r.candidates else "⚠️ No eligible cover found")
        st.write(f"**Gap:** {r.gap_summary}")
        certs = ", ".join(r.required_certs) if r.required_certs else "role-based"
        st.write(
            f"**Need:** {r.role}"
            f"{(' · ' + r.department) if r.department else ''}"
            f" · {r.shift_window} · certs: {certs}"
        )
        st.write(
            f"Screened **{r.n_screened}** active staff → "
            f"**{len(r.candidates)}** qualified & available."
        )
    with side:
        ui.confidence(r.confidence)

    if r.notes:
        with st.expander("Assumptions the agent made", expanded=False):
            for n in r.notes:
                st.write(f"- {n}")

    if not r.candidates:
        st.error(
            "No one currently qualifies (right role, certs, off tonight, rested, "
            "within weekly hours). Try widening the role or relaxing certs."
        )
    else:
        st.markdown("#### 🏅 Ranked candidates")
        for i, cand in enumerate(r.candidates):
            is_top = cand.draft_message is not None
            with st.container(border=True):
                head = f"**{i+1}. {cand.name}** · {cand.role} · {cand.department}"
                if is_top:
                    head += "  🥇" if i == 0 else "  ⭐"
                st.markdown(head)
                meta = (
                    f"📞 {cand.phone}  ·  {cand.contract}  ·  "
                    f"{int(cand.scheduled_hrs)}/{int(cand.max_hrs)}h this week  ·  "
                    f"{'OT OK ✅' if cand.overtime_ok else 'OT: no'}  ·  match score {cand.score}"
                )
                st.caption(meta)
                if cand.persona:
                    st.caption(f"📝 {cand.persona}")
                with st.expander("Why this person qualifies"):
                    for w in cand.why:
                        st.write(f"- {w}")

                # Drafted outreach for the top picks + simulated send.
                if cand.draft_message:
                    st.markdown("**Drafted outreach (SMS):**")
                    st.info(cand.draft_message)
                    sent_key = f"sent_{cand.employee_id}"
                    cols = st.columns([1, 4])
                    with cols[0]:
                        if st.button("📤 Send", key=f"btn_{cand.employee_id}"):
                            st.session_state[sent_key] = True
                    with cols[1]:
                        if st.session_state.get(sent_key):
                            st.success(f"Sent ✓ to {cand.name} at {cand.phone} (simulated)")

        st.divider()
        if st.button("📤 Send to all top picks"):
            for cand in r.candidates:
                if cand.draft_message:
                    st.session_state[f"sent_{cand.employee_id}"] = True
            sent_names = [c.name for c in r.candidates if c.draft_message]
            st.success(f"Sent ✓ to {', '.join(sent_names)} (simulated — no real SMS dispatched)")

        with st.expander("Raw result (JSON)"):
            st.json(r.model_dump())
else:
    st.info("Press **Find cover** to screen tonight's roster.")
