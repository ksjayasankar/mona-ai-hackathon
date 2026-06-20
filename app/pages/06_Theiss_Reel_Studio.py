"""Problem 6 — Dr. Theiss: Reel Studio Agent (Streamlit page).

Branded header -> pick the brand data pack (or upload) -> write a grounded reel script
-> render safe-zone-respecting vertical frames + gTTS voiceover -> mux a 1080x1920 MP4.
Shows the final reel video, the safe-zone guide storyboard, and the script in plain
language. Falls back to storyboard + audio if ffmpeg muxing is unavailable.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from agents import reels
from core import config, ui

c = ui.page_setup("theiss_reels")

st.caption(
    "Generates a vertical short-form reel (1080x1920) for Allgäuer Latschenkiefer with "
    "captions kept strictly inside TikTok / Instagram safe zones."
)

# --- input: sample data pack (one click) OR upload -----------------------
sample = config.PATHS["theiss"]
col1, col2 = st.columns([2, 1])
with col1:
    up = st.file_uploader("Upload a brand / product data pack (PDF)", type=["pdf"])
with col2:
    use_sample = st.checkbox("Use the Allgäuer data pack", value=True,
                             help=str(sample.name))

target = None
if up is not None:
    target = config.DATA_OUT / up.name
    target.write_bytes(up.getbuffer())
elif use_sample and sample.exists():
    target = sample

if not sample.exists() and up is None:
    st.warning(f"Sample data pack not found at {sample}. Upload a PDF to continue.")

go = st.button("🎬 Generate reel", type="primary", disabled=target is None)

if go and target and ui.require_key():
    with st.spinner("Writing the script and rendering the reel…"):
        result = reels.make_reel(target)
    st.session_state["reel"] = result

result = st.session_state.get("reel")

if result:
    st.divider()
    a, b = st.columns([2, 1])
    with a:
        st.subheader(f"🎬 Reel ready — {result.product_name}")
        st.write("**Why this meets the brief:**")
        for reason in result.reasons:
            st.write(f"- {reason}")
    with b:
        ui.confidence(result.confidence)

    # --- the deliverables ---
    vid_col, board_col = st.columns([1, 2])

    with vid_col:
        st.markdown("**📱 Final vertical reel**")
        if result.video_path and Path(result.video_path).exists():
            st.video(result.video_path)
        else:
            st.info("MP4 muxing unavailable in this environment — showing the storyboard "
                    "and voiceover below instead (still vertical + safe-zone-correct).")
        if result.audio_path and Path(result.audio_path).exists():
            st.markdown("**🔊 Voiceover (gTTS)**")
            st.audio(result.audio_path)
            st.caption(f"“{result.voiceover_text}”")

    with board_col:
        st.markdown("**🟢 Safe-zone storyboard** — dashed lines mark the platform-safe area; "
                    "all captions stay inside it.")
        sz = result.safe_zone
        st.caption(
            f"Canvas {sz['canvas']} · top {sz['top_reserved_px']}px reserved · "
            f"bottom {sz['bottom_reserved_px']}px reserved · right {sz['right_reserved_px']}px reserved"
        )
        cols = st.columns(3)
        for i, fp in enumerate(result.frame_paths):
            with cols[i % 3]:
                if Path(fp).exists():
                    st.image(fp, use_container_width=True)

    # --- the script in plain language ---
    st.divider()
    st.markdown("### 📝 The script")
    s = result.script
    st.markdown(f"**Hook:** {s.hook}")
    for i, scene in enumerate(s.scenes, 1):
        st.markdown(f"**Scene {i}:** {scene}")
    st.markdown(f"**Call to action:** {s.cta}")
    if s.hashtags:
        st.markdown("**Hashtags:** " + "  ".join(f"`#{h.lstrip('#')}`" for h in s.hashtags))

    with st.expander("Raw script + safe-zone data (JSON)"):
        st.json({
            "script": s.model_dump(),
            "safe_zone": result.safe_zone,
            "video_path": result.video_path,
            "audio_path": result.audio_path,
        })
else:
    st.info("Pick the data pack (or upload one) and press **Generate reel** to start.")
