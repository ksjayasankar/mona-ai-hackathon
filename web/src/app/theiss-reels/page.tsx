"use client";

import { useState } from "react";
import { Badge, Button, Card } from "@/components/ui";
import { postReels, type ReelStoryboard, type StoryboardFrame } from "@/lib/api/reels";

// Convert the agent's reserved-px margins into % insets so the on-page phone mockup
// overlays the SAME safe zone the frames were rendered against (visible confirmation).
function safeInsets(z: ReelStoryboard["safe_zone"]) {
  const [w, h] = z.canvas.split("x").map(Number);
  return {
    top: `${(z.top_reserved_px / h) * 100}%`,
    bottom: `${(z.bottom_reserved_px / h) * 100}%`,
    right: `${(z.right_reserved_px / w) * 100}%`,
    left: `${(60 / w) * 100}%`, // SAFE_LEFT gutter in the agent
  };
}

function PhoneFrame({
  frame,
  insets,
}: {
  frame: StoryboardFrame;
  insets: ReturnType<typeof safeInsets>;
}) {
  return (
    <div className="relative mx-auto w-[230px] shrink-0">
      {/* phone shell */}
      <div className="relative aspect-[9/16] overflow-hidden rounded-[28px] border-[6px] border-slate-800 bg-black shadow-xl">
        {/* the rendered 1080×1920 frame (safe-zone guides already drawn ON it) */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={frame.data_url} alt={frame.caption} className="h-full w-full object-cover" />
        {/* live safe-zone overlay that matches the rendered margins exactly */}
        <div
          className="pointer-events-none absolute rounded-[4px] border border-dashed border-green-300/80"
          style={{ top: insets.top, bottom: insets.bottom, left: insets.left, right: insets.right }}
        />
        <div
          className="pointer-events-none absolute inset-x-0 top-0 bg-red-500/15"
          style={{ height: insets.top }}
        />
        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 bg-red-500/15"
          style={{ height: insets.bottom }}
        />
        <div
          className="pointer-events-none absolute inset-y-0 right-0 bg-red-500/10"
          style={{ width: insets.right }}
        />
        {/* notch */}
        <div className="absolute left-1/2 top-1.5 h-4 w-16 -translate-x-1/2 rounded-full bg-slate-900" />
      </div>
      <p className="mt-2 text-center text-xs font-semibold text-slate-500">{frame.kicker}</p>
    </div>
  );
}

export default function TheissReelsPage() {
  const [file, setFile] = useState<File | null>(null);
  const [tryVideo, setTryVideo] = useState(true);
  const [board, setBoard] = useState<ReelStoryboard | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    setBoard(null);
    try {
      const r = await postReels({ file, tryVideo });
      setBoard(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const insets = board ? safeInsets(board.safe_zone) : null;

  return (
    <main className="mx-auto max-w-6xl px-6 py-10 text-slate-900">
      {/* branded header (Theiss green) */}
      <div className="mb-8 border-l-4 border-green-700 pl-4">
        <p className="text-xs font-semibold tracking-widest text-green-700">PROBLEM 6 · DR. THEISS · MARKETING</p>
        <h1 className="text-3xl font-bold">🎬 Reel Studio Agent</h1>
        <p className="mt-1 text-slate-600">
          Turns the Allgäuer Latschenkiefer brand pack into a <strong>vertical short-form reel</strong> — script,
          captions and voiceover — with every line laid out <strong>inside the TikTok / Instagram safe zones</strong>{" "}
          so nothing is hidden behind the platform UI.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-[2fr_3fr]">
        {/* input */}
        <Card className="h-fit p-5">
          <h2 className="mb-3 text-lg font-semibold">Brief</h2>
          <label className="mb-1 block text-sm font-medium">
            Brand / product pack (optional — defaults to the Dr. Theiss data pack)
          </label>
          <input
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.docx,.xlsx,.txt"
            className="mb-4 block w-full text-sm"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <label className="mb-4 flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={tryVideo} onChange={(e) => setTryVideo(e.target.checked)} />
            Also render the full MP4 (gTTS voiceover + ffmpeg) — falls back to storyboard if unavailable
          </label>
          <Button onClick={run} disabled={busy} className="bg-green-700 hover:bg-green-800">
            {busy ? "Writing script & rendering frames…" : "Generate reel"}
          </Button>
          {error && <p className="mt-3 text-sm text-red-700">⚠️ {error}</p>}

          <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
            <p className="font-semibold text-slate-700">How safe zones work</p>
            <p className="mt-1">
              The red bands mark the regions TikTok / Instagram overlay with their own UI (profile, caption, action
              rail). Every caption is kept inside the dashed green box, so it stays readable on-platform.
            </p>
          </div>
        </Card>

        {/* result */}
        <div className="space-y-4">
          {board && insets && (
            <>
              {/* safe-zone confirmation */}
              <Card className="border-green-300 bg-green-50 p-5">
                <h2 className="text-lg font-semibold">✅ Safe zones respected</h2>
                <p className="mt-1 text-sm text-slate-600">{board.safe_zone_note}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <Badge tone="green">Vertical {board.safe_zone.canvas}</Badge>
                  <Badge tone="slate">top {board.safe_zone.top_reserved_px}px reserved</Badge>
                  <Badge tone="slate">bottom {board.safe_zone.bottom_reserved_px}px reserved</Badge>
                  <Badge tone="slate">right {board.safe_zone.right_reserved_px}px reserved</Badge>
                  <Badge tone="green">{board.confidence}% confidence</Badge>
                </div>
              </Card>

              {/* the script */}
              <Card className="p-5">
                <div className="flex items-start justify-between gap-2">
                  <h2 className="text-lg font-semibold">📝 Script — {board.product_name}</h2>
                  <Badge tone="green">{board.frames.length} scenes</Badge>
                </div>
                <ol className="mt-3 space-y-1.5 text-sm">
                  <li>
                    <span className="font-semibold text-green-700">HOOK</span> · {board.script.hook}
                  </li>
                  {board.script.scenes.map((s, i) => (
                    <li key={i}>
                      <span className="font-semibold text-green-700">SCENE {i + 1}</span> · {s}
                    </li>
                  ))}
                  <li>
                    <span className="font-semibold text-green-700">CTA</span> · {board.script.cta}
                  </li>
                </ol>
                {board.script.hashtags.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {board.script.hashtags.map((h, i) => (
                      <Badge key={i} tone="slate">#{h.replace(/^#/, "")}</Badge>
                    ))}
                  </div>
                )}
                <ul className="mt-3 space-y-1 text-xs text-slate-600">
                  {board.reasons.map((r, i) => (
                    <li key={i}>📐 {r}</li>
                  ))}
                </ul>
              </Card>

              {/* the storyboard — phone frames with the safe-zone overlay */}
              <Card className="p-5">
                <h2 className="mb-1 text-lg font-semibold">📱 Storyboard — safe-zone preview</h2>
                <p className="mb-4 text-sm text-slate-600">
                  Each frame as it appears in-app. Captions never enter the red platform-UI bands.
                </p>
                <div className="flex gap-4 overflow-x-auto pb-2">
                  {board.frames.map((f, i) => (
                    <PhoneFrame key={i} frame={f} insets={insets} />
                  ))}
                </div>
              </Card>

              {/* optional MP4 */}
              <Card className="p-5">
                <h2 className="mb-2 text-lg font-semibold">🎞️ Rendered reel</h2>
                {board.video ? (
                  <video src={board.video} controls className="mx-auto w-[230px] rounded-2xl border border-slate-200" />
                ) : (
                  <p className="text-sm text-slate-500">
                    Storyboard-only this run — the MP4 mux was skipped or ffmpeg/gTTS was unavailable. The vertical
                    frames above fully demonstrate the safe-zone layout.
                  </p>
                )}
              </Card>

              {/* voiceover */}
              <Card className="p-5">
                <h2 className="mb-1 text-lg font-semibold">🎙️ Voiceover track</h2>
                <p className="text-sm text-slate-600">{board.voiceover_text}</p>
              </Card>

              {/* raw JSON */}
              <details className="rounded-xl border border-slate-200 bg-white p-4 text-xs">
                <summary className="cursor-pointer font-semibold text-slate-600">Raw storyboard (JSON)</summary>
                <pre className="mt-2 max-h-96 overflow-auto text-[11px] text-slate-600">
                  {JSON.stringify({ ...board, frames: board.frames.map((f) => ({ ...f, data_url: "<base64 png>" })), video: board.video ? "<base64 mp4>" : null }, null, 2)}
                </pre>
              </details>
            </>
          )}

          {!board && !busy && (
            <Card className="p-8 text-center text-slate-500">
              Click <span className="font-semibold text-green-700">Generate reel</span> to build a vertical
              safe-zone storyboard from the Dr. Theiss data pack.
            </Card>
          )}
        </div>
      </div>
    </main>
  );
}
