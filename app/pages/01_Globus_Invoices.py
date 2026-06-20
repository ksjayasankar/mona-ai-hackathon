"""Problem 1 — Globus Group: Invoice Triage Agent (Streamlit page).

Branded header -> upload OR sample picker -> read the invoice (any format/language) ->
show extracted fields, the routed department (prominent), confidence, reasons, and a
"Confirm & route to <dept>" button -> plus a batch accuracy tab vs 00_manifest.csv.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from agents import invoices
from core import config, ui

c = ui.page_setup("globus")

INVOICE_GLOB = ("*.pdf", "*.png", "*.jpg", "*.jpeg", "*.docx")


def _sample_files() -> list[Path]:
    d = config.PATHS["invoices"]
    if not d.exists():
        return []
    files: list[Path] = []
    for pat in INVOICE_GLOB:
        files.extend(d.glob(pat))
    # skip the manifest; only real invoices
    return sorted(f for f in files if not f.name.startswith("00_manifest"))


tab_triage, tab_eval = st.tabs(["🧾 Triage an invoice", "📈 Accuracy vs manifest"])

with tab_triage:
    samples = _sample_files()
    col1, col2 = st.columns([2, 1])
    with col1:
        up = st.file_uploader(
            "Upload an invoice (PDF, photo or Word)",
            type=["pdf", "png", "jpg", "jpeg", "docx"],
        )
    with col2:
        pick = st.selectbox("…or try a sample invoice", ["—"] + [p.name for p in samples])

    target = None
    if up is not None:
        target = config.DATA_OUT / up.name
        target.write_bytes(up.getbuffer())
    elif pick != "—":
        target = config.PATHS["invoices"] / pick

    if target and ui.require_key() and st.button("Read & route", type="primary"):
        with st.spinner("Reading the invoice…"):
            r = invoices.triage_invoice(target)
        st.session_state["globus_result"] = {"dept": r.department, "vendor": r.fields.vendor}

        a, b = st.columns([2, 1])
        with a:
            st.subheader(f"➡️ Route to: {r.department}")
            f = r.fields
            st.write(f"**Vendor:** {f.vendor or '—'}  ·  **Invoice #:** {f.invoice_number or '—'}")
            st.write(f"**Date:** {f.date or '—'}  ·  **Language:** {f.language or '—'}")
            m1, m2, m3 = st.columns(3)
            m1.metric("Total", f"{f.total or '—'}")
            m2.metric("Currency", f.currency or "—")
            m3.metric("VAT rate", f.vat_rate or "—")
            st.write(f"**Category:** {f.category or '—'}")
            st.write("**Why this routing:**")
            for reason in r.reasons:
                st.write(f"- {reason}")
        with b:
            ui.confidence(r.confidence)

        st.info("👤 A human confirms before anything is sent. Click below to approve the routing.")
        if st.button(f"✅ Confirm & route to {r.department}", type="primary"):
            st.success(f"Sent to **{r.department}** for processing. Vendor: {r.fields.vendor or '—'}.")
            st.toast(f"Routed to {r.department}", icon="✅")

        with st.expander("Raw extracted fields"):
            st.json(r.fields.model_dump())

with tab_eval:
    st.caption(
        "Runs all 10 real invoices and compares the agent's extracted vendor & total "
        "against the ground-truth 00_manifest.csv."
    )
    if ui.require_key() and st.button("Run on all 10 invoices"):
        manifest_path = config.PATHS["invoices"] / "00_manifest.csv"
        man = pd.read_csv(manifest_path) if manifest_path.exists() else pd.DataFrame()
        man_by_file = {str(row["file"]): row for _, row in man.iterrows()}

        def _norm(s) -> str:
            return "".join(ch for ch in str(s or "").lower() if ch.isalnum())

        samples = _sample_files()
        rows, vendor_hits, total_hits = [], 0, 0
        prog = st.progress(0.0)
        for i, p in enumerate(samples):
            r = invoices.triage_invoice(p)
            truth = man_by_file.get(p.name, {})
            exp_vendor = truth.get("vendor", "") if len(truth) else ""
            exp_total = truth.get("total", "") if len(truth) else ""

            # vendor match: either side contains the other (handles "Microsoft" vs "Microsoft Ireland")
            gv, ev = _norm(r.fields.vendor), _norm(exp_vendor)
            vendor_ok = bool(gv) and bool(ev) and (gv in ev or ev in gv)
            # total match: compare digits only (ignores symbols, thousands/decimal separators)
            gt = "".join(ch for ch in str(r.fields.total or "") if ch.isdigit())
            et = "".join(ch for ch in str(exp_total or "") if ch.isdigit())
            total_ok = bool(gt) and gt == et

            vendor_hits += vendor_ok
            total_hits += total_ok
            rows.append({
                "file": p.name,
                "exp. vendor": exp_vendor,
                "got vendor": r.fields.vendor,
                "vendor ✓": "✅" if vendor_ok else "❌",
                "exp. total": exp_total,
                "got total": r.fields.total,
                "total ✓": "✅" if total_ok else "❌",
                "→ dept": r.department,
                "conf": r.confidence,
            })
            prog.progress((i + 1) / len(samples))

        n = len(samples) or 1
        cA, cB = st.columns(2)
        cA.metric("Vendor accuracy", f"{vendor_hits}/{n} = {100*vendor_hits/n:.0f}%")
        cB.metric("Total accuracy", f"{total_hits}/{n} = {100*total_hits/n:.0f}%")
        st.dataframe(rows, use_container_width=True)
