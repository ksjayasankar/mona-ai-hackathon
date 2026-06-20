"""Problem 3 — Leistenschneider: Work-Permit Validator (Streamlit page).

GOLDEN TEMPLATE for document-agent pages: branded header -> upload OR sample picker
-> run agent -> show verdict, confidence, valid-until, reasons -> batch accuracy on
the labelled test set.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from agents import permits
from core import config, ui

c = ui.page_setup("leistenschneider")

tab_check, tab_eval = st.tabs(["✅ Check a permit", "📈 Accuracy on test set"])

with tab_check:
    sample_dir = config.PATHS["permits"]
    samples = sorted(sample_dir.glob("*.pdf")) if sample_dir.exists() else []
    col1, col2 = st.columns([2, 1])
    with col1:
        up = st.file_uploader("Upload a permit (PDF or photo)", type=["pdf", "png", "jpg", "jpeg"])
    with col2:
        pick = st.selectbox("…or try a sample", ["—"] + [p.name for p in samples])

    target = None
    if up is not None:
        target = config.DATA_OUT / up.name
        target.write_bytes(up.getbuffer())
    elif pick != "—":
        target = sample_dir / pick

    if target and ui.require_key() and st.button("Validate", type="primary"):
        with st.spinner("Reading the document…"):
            r = permits.validate_permit(target)
        badge = {"VALID": "✅", "EXPIRED": "⛔", "NOT_WORK_AUTHORIZED": "🛑",
                 "NOT_A_PERMIT": "🚫", "NEEDS_REVIEW": "⚠️"}.get(r.decision, "•")
        a, b = st.columns([2, 1])
        with a:
            st.subheader(f"{badge} {r.decision.replace('_', ' ')}")
            st.write(f"**Holder:** {r.fields.holder_name or '—'}  ·  **Nationality:** {r.fields.nationality or '—'}")
            st.write(f"**Type:** {r.fields.document_type or '—'}  ·  **Legal basis:** {r.fields.legal_basis or '—'}")
            st.metric("Valid until", r.valid_until or "—",
                      f"{r.days_remaining} days" if r.days_remaining is not None else None)
            st.write("**Why:**")
            for reason in r.reasons:
                st.write(f"- {reason}")
        with b:
            ui.confidence(r.confidence)
        with st.expander("Raw extracted fields"):
            st.json(r.fields.model_dump())

with tab_eval:
    st.caption("The sample set is labelled in the filenames (valid/invalid) — instant accuracy check.")
    if ui.require_key() and st.button("Run on all samples"):
        rows, correct = [], 0
        samples = sorted(config.PATHS["permits"].glob("*.pdf"))
        prog = st.progress(0.0)
        for i, p in enumerate(samples):
            expected = "VALID" if "valid" in p.name and "invalid" not in p.name else "INVALID"
            r = permits.validate_permit(p)
            got = "VALID" if r.decision == "VALID" else "INVALID"
            ok = got == expected
            correct += ok
            rows.append({"file": p.name, "expected": expected, "agent": r.decision,
                         "valid_until": r.valid_until, "conf": r.confidence, "✓": "✅" if ok else "❌"})
            prog.progress((i + 1) / len(samples))
        st.metric("Accuracy", f"{correct}/{len(samples)} = {100*correct/len(samples):.0f}%")
        st.dataframe(rows, use_container_width=True)
