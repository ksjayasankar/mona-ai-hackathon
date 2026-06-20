"""Problem 6 — Dr. Theiss: Reel Studio Agent.

Boxes to check (from the customer brief):
  [x] produce a SHORT-FORM VERTICAL reel (1080x1920)
  [x] automatically RESPECT TikTok/Instagram SAFE ZONES (all text inside safe margins)

Approach: Claude reads the real Allgäuer Latschenkiefer brand/product data pack (PDF)
and writes a short reel script (hook, 3-4 scene captions, CTA) grounded in real
products. We then render each scene as a 1080x1920 frame with PIL — every piece of
text is laid out *only* inside the platform-safe rectangle (top ~12% and bottom ~20%
reserved for the platform UI, right ~6% reserved for the action rail). gTTS makes a
free voiceover, and ffmpeg muxes the frames + audio into a vertical MP4.

If ffmpeg muxing fails we fall back to the storyboard frames + script + audio so the
"vertical short-form" + "respects safe zones" boxes are still demonstrably met.
"""
from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

from pydantic import BaseModel, Field

from core import config, ingest, llm

# ---- vertical canvas + platform safe zones -------------------------------
W, H = 1080, 1920                     # TikTok / Instagram Reels canvas
SAFE_TOP = int(H * 0.12)              # 230px — top UI (profile, search)
SAFE_BOTTOM = int(H * 0.20)           # 384px — bottom UI (caption, audio, buttons)
SAFE_RIGHT = int(W * 0.06)            # 64px  — right action rail (like/share)
SAFE_LEFT = 60                        # comfortable left gutter
SAFE_BOX = (SAFE_LEFT, SAFE_TOP, W - SAFE_RIGHT, H - SAFE_BOTTOM)

# Dr. Theiss / Allgäuer Latschenkiefer brand palette (#15803d family)
BRAND_DARK = (16, 78, 47)             # deep pine green
BRAND_MID = (21, 128, 61)             # #15803d
BRAND_LIGHT = (134, 239, 172)         # mint accent
INK = (255, 255, 255)

SCENE_SECS = 2.6                      # seconds per scene → keeps total reel < ~15s

SYSTEM = (
    "You are a social-media creative for Dr. Theiss Naturwaren writing a vertical "
    "short-form reel (TikTok / Instagram) for the Allgäuer Latschenkiefer range "
    "(dwarf mountain-pine oil products for foot, leg and muscle care). Use ONLY "
    "products and benefits found in the supplied brand data pack — do not invent "
    "medical claims. Keep every line punchy and SHORT so it fits inside the platform "
    "safe zone: hook <= 6 words, each scene caption <= 9 words, CTA <= 6 words."
)


class ReelScript(BaseModel):
    """A short-form vertical reel script grounded in the brand data pack."""

    product_name: str = Field(description="The featured Allgäuer Latschenkiefer product, as named in the pack")
    hook: str = Field(description="Opening hook line, <= 6 words")
    scenes: list[str] = Field(description="3-4 scene caption lines, each <= 9 words", min_length=3, max_length=4)
    cta: str = Field(description="Call to action, <= 6 words")
    hashtags: list[str] = Field(description="3-5 short relevant hashtags (no '#')", max_length=5)


class ReelResult(BaseModel):
    product_name: str
    script: ReelScript
    frame_paths: list[str]            # storyboard frames WITH safe-zone guides
    clean_frame_paths: list[str]      # frames WITHOUT guides (used for the video)
    audio_path: str | None
    video_path: str | None
    confidence: float
    safe_zone: dict                   # the reserved margins, for the UI to display
    reasons: list[str]
    voiceover_text: str


# ---- font loading (graceful) ---------------------------------------------
def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = (
        ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        ["/System/Library/Fonts/Supplemental/Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap_to_width(draw, text: str, font, max_w: int) -> list[str]:
    """Word-wrap `text` so each line fits in max_w pixels."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw_guides(draw):
    """Faint dashed lines marking the safe-zone rectangle."""
    x0, y0, x1, y1 = SAFE_BOX
    dash, gap, col = 22, 16, (255, 255, 255, 0)  # color overridden below
    col = (255, 255, 255)

    def hline(y):
        x = x0
        while x < x1:
            draw.line([(x, y), (min(x + dash, x1), y)], fill=col, width=3)
            x += dash + gap

    def vline(x):
        y = y0
        while y < y1:
            draw.line([(x, y), (x, min(y + dash, y1))], fill=col, width=3)
            y += dash + gap

    hline(y0)
    hline(y1)
    vline(x0)
    vline(x1)


def _render_frame(out_path: Path, *, kicker: str, headline: str, sub: str,
                  product: str, idx: int, total: int, guides: bool) -> Path:
    """Render one 1080x1920 vertical frame; all text strictly inside SAFE_BOX."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), BRAND_DARK)
    draw = ImageDraw.Draw(img)

    # vertical brand gradient so frames look produced, not flat
    for y in range(H):
        t = y / H
        r = int(BRAND_DARK[0] + (BRAND_MID[0] - BRAND_DARK[0]) * t)
        g = int(BRAND_DARK[1] + (BRAND_MID[1] - BRAND_DARK[1]) * t)
        b = int(BRAND_DARK[2] + (BRAND_MID[2] - BRAND_DARK[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    x0, y0, x1, y1 = SAFE_BOX
    safe_w = x1 - x0

    # --- brand strip (inside safe zone, near the top) ---
    f_brand = _font(40, bold=True)
    draw.text((x0, y0), "ALLGÄUER LATSCHENKIEFER", font=f_brand, fill=BRAND_LIGHT)
    draw.line([(x0, y0 + 56), (x0 + 360, y0 + 56)], fill=BRAND_LIGHT, width=5)

    # --- kicker (scene number / hook label) ---
    f_kicker = _font(38, bold=True)
    draw.text((x0, y0 + 100), kicker, font=f_kicker, fill=BRAND_LIGHT)

    # --- headline (the caption itself), wrapped & vertically centred in safe box ---
    f_head = _font(92, bold=True)
    head_lines = _wrap_to_width(draw, headline, f_head, safe_w)
    line_h = int(f_head.size * 1.18)
    block_h = line_h * len(head_lines)
    cy = y0 + (y1 - y0) // 2 - block_h // 2
    for line in head_lines:
        lw = draw.textlength(line, font=f_head)
        draw.text((x0 + (safe_w - lw) / 2, cy), line, font=f_head, fill=INK)
        cy += line_h

    # --- sub line (product / CTA), wrapped, just below headline block ---
    if sub:
        f_sub = _font(52, bold=False)
        sub_lines = _wrap_to_width(draw, sub, f_sub, safe_w)
        cy += 24
        for line in sub_lines:
            lw = draw.textlength(line, font=f_sub)
            draw.text((x0 + (safe_w - lw) / 2, cy), line, font=f_sub, fill=BRAND_LIGHT)
            cy += int(f_sub.size * 1.2)

    # --- product footer pill (still inside safe zone, near the bottom) ---
    f_foot = _font(34, bold=True)
    foot = f"● {product}"
    draw.text((x0, y1 - 50), foot[:48], font=f_foot, fill=INK)

    # --- progress dots (scene N of total), top-right inside safe zone ---
    dot_r, dgap = 9, 30
    dx = x1 - (total * dgap)
    for i in range(total):
        col = BRAND_LIGHT if i == idx else (255, 255, 255, 90)
        col = BRAND_LIGHT if i == idx else (120, 160, 130)
        draw.ellipse([dx, y0 + 6, dx + 2 * dot_r, y0 + 6 + 2 * dot_r], fill=col)
        dx += dgap

    if guides:
        _draw_guides(draw)
        # label the reserved regions
        f_g = _font(30, bold=True)
        draw.text((SAFE_LEFT, SAFE_TOP - 44), "↑ top UI reserved (safe-zone guide)", font=f_g, fill=BRAND_LIGHT)
        draw.text((SAFE_LEFT, H - SAFE_BOTTOM + 12), "↓ bottom UI reserved (caption/audio)", font=f_g, fill=BRAND_LIGHT)

    img.save(out_path, "PNG")
    return out_path


def write_script(file: str | Path | None = None) -> ReelScript:
    """Ask Claude to write a short reel script grounded in the brand data pack."""
    src = Path(file) if file else config.PATHS["theiss"]
    blocks = ingest.file_to_blocks(src)
    blocks.append({
        "type": "text",
        "text": (
            "Using ONLY the product range and benefits in this brand data pack, write a "
            "vertical short-form reel for ONE flagship product. Return a hook, 3-4 short "
            "scene captions and a CTA. Keep every line very short for the safe zone."
        ),
    })
    return llm.extract(ReelScript, blocks, system=SYSTEM, model=config.MODEL)


def _make_voiceover(script: ReelScript, out_dir: Path) -> tuple[str | None, str]:
    """gTTS voiceover from the script. Returns (mp3_path|None, spoken_text)."""
    spoken = ". ".join([script.hook, *script.scenes, script.cta])
    mp3 = out_dir / "reel_voiceover.mp3"
    try:
        from gtts import gTTS

        gTTS(text=spoken, lang="en").save(str(mp3))
        return str(mp3), spoken
    except Exception:
        return None, spoken


def _mux_video(clean_frames: list[Path], audio: str | None, out_dir: Path) -> str | None:
    """Assemble frames (SCENE_SECS each) + audio into a vertical MP4 via ffmpeg."""
    if not shutil.which("ffmpeg") or not clean_frames:
        return None
    # build a concat demuxer file: one image per scene, held for SCENE_SECS
    concat = out_dir / "reel_concat.txt"
    lines = []
    for fp in clean_frames:
        lines.append(f"file '{fp.as_posix()}'")
        lines.append(f"duration {SCENE_SECS}")
    lines.append(f"file '{clean_frames[-1].as_posix()}'")  # last frame needs a final entry
    concat.write_text("\n".join(lines), encoding="utf-8")

    out_mp4 = out_dir / "reel.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat),
    ]
    if audio and Path(audio).exists():
        cmd += ["-i", str(audio), "-shortest"]
    cmd += [
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,format=yuv420p,fps=30",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
    ]
    if audio and Path(audio).exists():
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    cmd += [str(out_mp4)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        return str(out_mp4) if out_mp4.exists() else None
    except Exception:
        return None


def make_reel(file: str | Path | None = None, script: ReelScript | None = None) -> ReelResult:
    """Full pipeline: script -> safe-zone frames -> voiceover -> muxed vertical MP4."""
    if script is None:
        script = write_script(file)

    out_dir = config.DATA_OUT / "reel"
    out_dir.mkdir(parents=True, exist_ok=True)
    # clear any stale frames from a previous run
    for old in out_dir.glob("frame_*.png"):
        old.unlink()

    # storyboard: title (hook) + each scene + outro (CTA)
    captions = [
        ("HOOK", script.hook, ""),
        *[(f"SCENE {i + 1}", s, "") for i, s in enumerate(script.scenes)],
        ("CTA", script.cta, "  ".join(f"#{h.lstrip('#')}" for h in script.hashtags[:3])),
    ]
    total = len(captions)

    frame_paths, clean_paths = [], []
    for i, (kicker, head, sub) in enumerate(captions):
        guided = _render_frame(
            out_dir / f"frame_g_{i:02d}.png", kicker=kicker, headline=head, sub=sub,
            product=script.product_name, idx=i, total=total, guides=True,
        )
        clean = _render_frame(
            out_dir / f"frame_{i:02d}.png", kicker=kicker, headline=head, sub=sub,
            product=script.product_name, idx=i, total=total, guides=False,
        )
        frame_paths.append(str(guided))
        clean_paths.append(str(clean))

    audio_path, spoken = _make_voiceover(script, out_dir)
    video_path = _mux_video([Path(p) for p in clean_paths], audio_path, out_dir)

    reasons = [
        f"Vertical {W}x{H} canvas — native TikTok / Instagram Reels format.",
        f"All text kept inside the safe zone: top {SAFE_TOP}px and bottom {SAFE_BOTTOM}px "
        f"and right {SAFE_RIGHT}px reserved for platform UI.",
        f"Script grounded in the Allgäuer Latschenkiefer data pack — featured product: "
        f"{script.product_name}.",
        f"{total} scenes at {SCENE_SECS:g}s each ≈ {total * SCENE_SECS:g}s reel.",
    ]
    if audio_path:
        reasons.append("Voiceover generated with gTTS (no API key needed).")
    else:
        reasons.append("Voiceover unavailable — storyboard + script still delivered.")
    if video_path:
        reasons.append("Frames + audio muxed into an MP4 with ffmpeg.")
    else:
        reasons.append("ffmpeg mux unavailable — falling back to storyboard frames + audio player.")

    # confidence: high when we have the full pipeline, lower on fallbacks
    confidence = 90.0
    if not video_path:
        confidence -= 20
    if not audio_path:
        confidence -= 10

    return ReelResult(
        product_name=script.product_name,
        script=script,
        frame_paths=frame_paths,
        clean_frame_paths=clean_paths,
        audio_path=audio_path,
        video_path=video_path,
        confidence=round(confidence, 1),
        safe_zone={
            "canvas": f"{W}x{H}",
            "top_reserved_px": SAFE_TOP,
            "bottom_reserved_px": SAFE_BOTTOM,
            "right_reserved_px": SAFE_RIGHT,
            "safe_box": list(SAFE_BOX),
        },
        reasons=reasons,
        voiceover_text=spoken,
    )
