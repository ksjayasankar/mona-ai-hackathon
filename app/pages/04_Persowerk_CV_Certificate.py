"""Problem 4 — Persowerk: CV & Certificate Authenticity Agent (Streamlit page).

Two tabs:
  - CV authenticity: ingest a CV PDF -> extract claims -> fraud-risk score + flags.
  - Certificate check: ingest a certificate JPG -> verify it's genuine & still current.

Mirrors the golden permits page: branded header -> upload OR sample picker -> run
agent -> plain-language verdict + confidence + reasons -> raw fields in an expander.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from agents import fraud
from core import config, ui

c = ui.page_setup("persowerk")

tab_cv, tab_cert = st.tabs(["🔎 CV authenticity", "📜 Certificate check"])

RISK_BADGE = {"LOW": "✅", "MEDIUM": "⚠️", "HIGH": "🚫"}
RISK_COLOR = {"LOW": "#0a7d3f", "MEDIUM": "#b58900", "HIGH": "#b3122b"}


# --------------------------------------------------------------------------- #
# Tab 1 — CV authenticity
# --------------------------------------------------------------------------- #
with tab_cv:
    st.caption(
        "Verifies work-history & skill plausibility and flags AI-generated / fabricated / "
        "misrepresented content with a fraud-risk score."
    )
    cv_dir = config.PATHS["cvs"]
    cv_samples = sorted(cv_dir.glob("*.pdf")) if cv_dir.exists() else []

    col1, col2 = st.columns([2, 1])
    with col1:
        up = st.file_uploader("Upload a CV (PDF or photo)", type=["pdf", "png", "jpg", "jpeg"], key="cv_up")
    with col2:
        pick = st.selectbox("…or try a sample CV", ["—"] + [p.name for p in cv_samples], key="cv_pick")

    target = None
    if up is not None:
        target = config.DATA_OUT / up.name
        target.write_bytes(up.getbuffer())
    elif pick != "—":
        target = cv_dir / pick

    if target and ui.require_key() and st.button("Check this CV", type="primary", key="cv_btn"):
        with st.spinner("Reading the CV and checking authenticity…"):
            r = fraud.analyze_cv(target)

        badge = RISK_BADGE.get(r.fraud_risk, "•")
        color = RISK_COLOR.get(r.fraud_risk, "#888")
        a, b = st.columns([2, 1])
        with a:
            st.subheader(f"{badge} Fraud risk: {r.fraud_risk}")
            st.write(f"**Candidate:** {r.claims.candidate_name or '—'}")
            st.markdown(
                f"<div style='font-size:0.8rem;color:#888'>Fraud-risk score (0 = clean, 100 = fabricated)</div>"
                f"<div style='font-size:2rem;font-weight:700;color:{color}'>{r.risk_score}/100</div>",
                unsafe_allow_html=True,
            )
            if r.injection_note:
                st.error(f"🛡️ {r.injection_note}")
            st.write("**Plain-language summary:**")
            st.write(r.score.rationale)
            st.write("**Why this verdict:**")
            for reason in r.reasons:
                st.write(f"- {reason}")
        with b:
            ui.confidence(r.confidence)
            st.metric("Roles found", len(r.claims.roles))
            st.metric("Skills claimed", len(r.claims.skills))

        st.write("**Work history read off the CV:**")
        st.dataframe(
            [
                {
                    "Title": role.title or "—",
                    "Employer": role.employer or "—",
                    "From": role.start or "—",
                    "To": role.end or "—",
                    "Specific achievements?": "yes" if role.achievements_specific else "no",
                }
                for role in r.claims.roles
            ]
            or [{"Title": "—", "Employer": "—", "From": "—", "To": "—", "Specific achievements?": "—"}],
            use_container_width=True,
        )
        if r.claims.skills:
            st.write("**Skills claimed:** " + ", ".join(r.claims.skills))

        with st.expander("Raw extracted claims + score"):
            st.json({"claims": r.claims.model_dump(), "score": r.score.model_dump()})


# --------------------------------------------------------------------------- #
# Tab 2 — Certificate check
# --------------------------------------------------------------------------- #
with tab_cert:
    st.caption(
        "Confirms a certificate is genuine-looking and CURRENT — reads issuer, holder, "
        "issue date and expiry, and checks it against today (2026-06-20)."
    )
    cert_dir = config.PATHS["certificates"]
    cert_samples = (
        sorted([p for p in cert_dir.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")])
        if cert_dir.exists()
        else []
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        cup = st.file_uploader(
            "Upload a certificate (JPG/PNG/PDF)", type=["jpg", "jpeg", "png", "pdf"], key="cert_up"
        )
    with col2:
        cpick = st.selectbox("…or try a sample certificate", ["—"] + [p.name for p in cert_samples], key="cert_pick")

    ctarget = None
    if cup is not None:
        ctarget = config.DATA_OUT / cup.name
        ctarget.write_bytes(cup.getbuffer())
    elif cpick != "—":
        ctarget = cert_dir / cpick

    if ctarget is not None and ctarget.suffix.lower() in (".jpg", ".jpeg", ".png"):
        st.image(str(ctarget), caption=ctarget.name, width=320)

    if ctarget and ui.require_key() and st.button("Verify this certificate", type="primary", key="cert_btn"):
        with st.spinner("Reading the certificate…"):
            r = fraud.check_certificate(ctarget)

        badge = {
            "GENUINE_CURRENT": "✅",
            "NO_EXPIRY": "✅",
            "GENUINE_EXPIRED": "⛔",
            "SUSPECT": "🚫",
            "NOT_A_CERTIFICATE": "❓",
        }.get(r.decision, "•")
        a, b = st.columns([2, 1])
        with a:
            st.subheader(f"{badge} {r.decision.replace('_', ' ').title()}")
            st.write(f"**Holder:** {r.fields.holder_name or '—'}  ·  **Type:** {r.fields.cert_type or '—'}")
            st.write(f"**Issuer:** {r.fields.issuer or '—'}  ·  **Title:** {r.fields.title or '—'}")
            cur = "Yes" if r.is_current else ("No" if r.is_current is False else "—")
            st.write(f"**Issued:** {r.fields.issue_date or '—'}  ·  **Still current:** {cur}")
            st.metric(
                "Valid until",
                r.valid_until or "no expiry",
                f"{r.days_remaining} days" if r.days_remaining is not None else None,
            )
            st.write("**Why this verdict:**")
            for reason in r.reasons:
                st.write(f"- {reason}")
        with b:
            ui.confidence(r.confidence)

        with st.expander("Raw extracted fields"):
            st.json(r.fields.model_dump())
