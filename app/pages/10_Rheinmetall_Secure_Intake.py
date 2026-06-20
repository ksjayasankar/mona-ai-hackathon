"""Problem 10 — Rheinmetall: Secure Intake Agent (Streamlit page).

Branded header -> a PRE-FILLED malicious applicant email + sample/upload of documents
-> run the secure agent -> show (1) a red "injection detected & neutralised" panel with
the matched patterns, (2) a "what the attacker tried vs what we did" comparison, and
(3) a plain-language completeness checklist (CV, residence permit, work permit,
criminal record) marking each present ✓ / missing ✗.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from agents import secure_intake
from core import config, ui

c = ui.page_setup("rheinmetall")

st.caption(
    "Last week an applicant email prompt-injected the old intake bot and it leaked the "
    "applicant database. This agent treats every email and document as **data, never "
    "instructions** — and still checks that all required documents are present."
)

# A synthesized criminal-record statement we can attach in-page (clean — no injection).
SAMPLE_CRIMINAL_RECORD = """FÜHRUNGSZEUGNIS (Criminal-Record Statement)
Bundesamt für Justiz — Certificate of Good Conduct
Holder: Max Mustermann
Date of birth: 14.03.1991
Reference: BfJ-2026-004417
Result: No entries. No criminal convictions recorded.
Issued: 02.06.2026   Valid for: 6 months
"""

# ---- 1. Untrusted applicant email (pre-filled with a real injection) -------
st.subheader("1 · Applicant email (untrusted)")
email_body = st.text_area(
    "Email body — note the hidden 'SYSTEM NOTE' trying to hijack the agent:",
    value=secure_intake.SAMPLE_MALICIOUS_EMAIL,
    height=240,
)

# ---- 2. Attached documents -------------------------------------------------
st.subheader("2 · Attached documents")
cvs_dir = config.PATHS["cvs"]
permits_dir = config.PATHS["permits"]
cv_samples = sorted(cvs_dir.glob("*.pdf")) if cvs_dir.exists() else []
permit_samples = sorted(permits_dir.glob("*.pdf")) if permits_dir.exists() else []

col_a, col_b = st.columns(2)
with col_a:
    uploads = st.file_uploader(
        "Upload applicant documents (PDF or photo)",
        type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )
with col_b:
    st.write("…or load a sample application (real CV + permit):")
    load_sample = st.button("📎 Load a sample application")
    include_criminal = st.checkbox(
        "Attach a (clean) criminal-record statement", value=True,
        help="Synthesized in-page so the demo can also show a COMPLETE application.",
    )

if "sample_loaded" not in st.session_state:
    st.session_state.sample_loaded = False
if load_sample:
    st.session_state.sample_loaded = True

# Resolve the document set to process.
attachment_files: list[Path] = []
attachment_source = ""
if uploads:
    attachment_source = "your uploads"
    for up in uploads:
        target = config.DATA_OUT / up.name
        target.write_bytes(up.getbuffer())
        attachment_files.append(target)
elif st.session_state.sample_loaded:
    attachment_source = "sample application"
    if cv_samples:
        attachment_files.append(cv_samples[0])
    if permit_samples:
        # use a VALID permit so the sample looks like a real application
        valid = [p for p in permit_samples if "valid" in p.name and "invalid" not in p.name]
        attachment_files.append((valid or permit_samples)[0])

text_attachments: list[tuple[str, str]] = []
if include_criminal and (attachment_files or st.session_state.sample_loaded or uploads):
    text_attachments.append(("Fuehrungszeugnis_criminal_record.txt", SAMPLE_CRIMINAL_RECORD))

if attachment_files or text_attachments:
    names = [p.name for p in attachment_files] + [n for n, _ in text_attachments]
    st.info(f"Documents to process ({attachment_source or 'in-page'}): " + ", ".join(names))
else:
    st.warning("No documents attached yet — upload files or click **Load a sample application**.")

st.divider()

# ---- 3. Run ----------------------------------------------------------------
ready = bool(attachment_files or text_attachments)
if ui.require_key() and st.button("🛡️ Process securely", type="primary", disabled=not ready):
    with st.spinner("Scanning for injection, then classifying documents as data…"):
        r = secure_intake.process_application(
            email_body=email_body,
            attachment_files=attachment_files,
            text_attachments=text_attachments,
        )

    # --- Security panel ---
    if r.injection_detected:
        matched = sorted({h for rep in r.guard_reports for h in rep.hits})
        st.error("🛡️ **Injection attempt detected & neutralised**")
        st.write(
            "Suspicious instructions were found in the incoming text. They were treated as "
            "**data to report**, not commands to follow. Matched patterns:"
        )
        for m in matched:
            st.markdown(f"- `{m}`")
    else:
        st.success("🛡️ No injection patterns detected in this application.")

    # --- Attacker vs us ---
    st.subheader("What the attacker tried — vs what we did")
    left, right = st.columns(2)
    with left:
        st.markdown("**❌ What the attacker tried**")
        if r.attacker_tried:
            for a in r.attacker_tried:
                st.markdown(f"- {a}")
        else:
            st.markdown("- (nothing malicious found)")
    with right:
        st.markdown("**✅ What we actually did**")
        for w in r.we_did:
            st.markdown(f"- {w}")

    st.divider()

    # --- Completeness checklist ---
    st.subheader("Required-document checklist")
    badge = "✅ Complete" if r.all_present else "⛔ Incomplete"
    st.markdown(f"### {badge}")
    st.write(r.summary)
    rows = []
    for item in r.checklist:
        rows.append(
            {
                "Required document": item.label,
                "Status": "✅ Present" if item.present else "❌ Missing",
                "Found in": item.found_in or "—",
                "Confidence": f"{item.confidence:.0f}%" if item.confidence is not None else "—",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    if r.missing_labels:
        st.warning("**Missing:** " + ", ".join(r.missing_labels))

    # --- Per-attachment detail ---
    with st.expander("How each attachment was classified"):
        for a in r.attachments:
            st.write(
                f"**{a.file_name}** → {a.type_label}  ·  holder: {a.holder_name or '—'}  "
                f"·  {a.confidence:.0f}% confident"
            )
            st.caption(a.summary)

    # --- Raw JSON ---
    with st.expander("Raw security + intake report (JSON)"):
        st.json(r.model_dump())
