"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Signal } from "./api";

// ---- semantic meta -------------------------------------------------------
export const BAND: Record<string, { label: string; verb: string; fg: string; bg: string; ring: string }> = {
  LOW: { label: "Looks clean", verb: "Low risk", fg: "#047857", bg: "#ecfdf5", ring: "#34d399" },
  MEDIUM: { label: "Review advised", verb: "Medium risk", fg: "#b45309", bg: "#fffbeb", ring: "#f59e0b" },
  HIGH: { label: "Examine closely", verb: "High risk", fg: "#be123c", bg: "#fff1f2", ring: "#f43f5e" },
};

const SEV: Record<string, { dot: string; label: string }> = {
  high: { dot: "#f43f5e", label: "high" },
  medium: { dot: "#f59e0b", label: "medium" },
  low: { dot: "#94a3b8", label: "low" },
};

export const LENS: Record<string, { label: string; blurb: string; icon: string }> = {
  forensic: { label: "Document forensics", blurb: "What the files themselves reveal", icon: "🔬" },
  consistency: { label: "Story & timeline", blurb: "Does the history hold together", icon: "🧩" },
  certificate: { label: "Credentials", blurb: "Are the certificates real and current", icon: "🎓" },
  verification: { label: "Public footprint", blurb: "What public sources corroborate", icon: "🌐" },
  injection: { label: "Tampering attempt", blurb: "The document tried to manipulate the screener", icon: "🛡️" },
};
export const LENS_ORDER = ["injection", "forensic", "consistency", "certificate", "verification"];

function humanize(name: string) {
  const s = name.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---- risk dial (animated sweep + count-up) -------------------------------
export function RiskDial({ score, band }: { score: number; band: string }) {
  const R = 56;
  const C = 2 * Math.PI * R;
  const [shown, setShown] = useState(0);
  const meta = BAND[band] ?? BAND.MEDIUM;

  useEffect(() => {
    // count the number up alongside the arc sweep
    let raf = 0;
    const start = performance.now();
    const dur = 1100;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      setShown(Math.round(eased * score));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [score]);

  const offset = C * (1 - score / 100);
  return (
    <div className="relative grid h-[148px] w-[148px] shrink-0 place-items-center">
      <svg width="148" height="148" viewBox="0 0 148 148" className="-rotate-90">
        <circle cx="74" cy="74" r={R} fill="none" stroke="#ece8f4" strokeWidth="12" />
        <circle
          cx="74" cy="74" r={R} fill="none" stroke={meta.ring} strokeWidth="12" strokeLinecap="round"
          strokeDasharray={C} strokeDashoffset={offset} className="pw-dial-arc"
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="pw-tnum text-4xl font-bold leading-none" style={{ color: meta.fg }}>{shown}</span>
        <span className="pw-mono text-[10px] tracking-widest text-[var(--muted)]">/ 100</span>
      </div>
    </div>
  );
}

// ---- analysis pipeline (the signature motion moment) ---------------------
export function AnalysisPipeline({ stage, runVerify }: { stage: number; runVerify: boolean }) {
  const stages = [
    { key: "read", label: "Reading the documents", note: "Vision model extracts roles, dates, issuers" },
    { key: "forensic", label: "Forensic analysis", note: "Metadata, edit history, EXIF, error-level scan" },
    { key: "timeline", label: "Timeline & cross-checks", note: "Overlaps, gaps, name across documents" },
    { key: "footprint", label: "Public-footprint check", note: runVerify ? "GitHub + web corroboration" : "Skipped — enable deep verification", skipped: !runVerify },
    { key: "score", label: "Weighing the evidence", note: "Calibrated signal score — not a verdict" },
  ];
  return (
    <div aria-live="polite" className="space-y-1.5">
      {stages.map((s, i) => {
        const done = i < stage || (s.skipped && stage > i - 1);
        const active = i === stage && !s.skipped;
        return (
          <div key={s.key} className="flex items-start gap-3 rounded-xl px-2.5 py-2" style={{ background: active ? "var(--evidence)" : "transparent" }}>
            <div className="relative mt-0.5 grid h-5 w-5 shrink-0 place-items-center">
              {done && !active ? (
                <span className="grid h-5 w-5 place-items-center rounded-full text-[11px] font-bold text-white" style={{ background: s.skipped ? "#cbd5e1" : "var(--brand)" }}>
                  {s.skipped ? "–" : "✓"}
                </span>
              ) : active ? (
                <span className="pw-node-active grid h-5 w-5 place-items-center rounded-full" style={{ background: "var(--brand-2)" }}>
                  <span className="h-2 w-2 rounded-full bg-white" />
                </span>
              ) : (
                <span className="h-5 w-5 rounded-full border-2" style={{ borderColor: "var(--line)" }} />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className="pw-stage text-sm font-semibold" style={{ color: active ? "var(--ink)" : done ? "var(--ink)" : "var(--muted)", opacity: !done && !active ? 0.65 : 1 }}>
                {s.label}
              </p>
              <p className="text-xs text-[var(--muted)]">{s.note}</p>
              {active && <div className="pw-scan mt-1.5 h-1 rounded-full" />}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---- dropzone ------------------------------------------------------------
export function Dropzone({
  label, sublabel, accept, multiple, files, onFiles,
}: {
  label: string; sublabel: string; accept: string; multiple?: boolean; files: File[];
  onFiles: (f: File[]) => void;
}) {
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div>
      <div
        className="pw-drop flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-4 py-5 text-center"
        style={{ borderColor: "var(--line)" }}
        data-drag={drag}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault(); setDrag(false);
          const dropped = Array.from(e.dataTransfer.files);
          onFiles(multiple ? [...files, ...dropped] : dropped.slice(0, 1));
        }}
      >
        <span className="text-xl">{multiple ? "📑" : "📄"}</span>
        <span className="mt-1 text-sm font-semibold">{label}</span>
        <span className="text-xs text-[var(--muted)]">{sublabel}</span>
        <input
          ref={inputRef} type="file" accept={accept} multiple={multiple} className="hidden"
          onChange={(e) => {
            const picked = Array.from(e.target.files ?? []);
            onFiles(multiple ? [...files, ...picked] : picked.slice(0, 1));
          }}
        />
      </div>
      {files.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {files.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1.5 rounded-full bg-[var(--evidence)] px-2.5 py-1 text-xs">
              <span className="max-w-[160px] truncate">{f.name}</span>
              <button
                type="button" aria-label={`Remove ${f.name}`}
                className="text-[var(--muted)] hover:text-[var(--ink)]"
                onClick={(e) => { e.stopPropagation(); onFiles(files.filter((_, j) => j !== i)); }}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- a single evidence signal -------------------------------------------
export function SignalRow({ s }: { s: Signal }) {
  const sev = SEV[s.severity] ?? SEV.low;
  return (
    <div className="pw-signal rounded-xl border border-[var(--line)] p-3.5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: sev.dot }} />
          <span className="text-sm font-semibold">{humanize(s.name)}</span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {s.weak && (
            <span className="rounded-full border border-[var(--line)] px-2 py-0.5 text-[10px] font-medium text-[var(--muted)]">weak signal</span>
          )}
          <span className="pw-mono rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
            style={{ color: sev.dot, background: `${sev.dot}1a` }}>{sev.label}</span>
        </div>
      </div>
      <div className="pw-evidence mt-2.5 px-3 py-2">
        <p className="pw-eyebrow mb-0.5 text-[var(--muted)]" style={{ color: "var(--muted)" }}>Evidence</p>
        <p className="pw-mono text-[13px] leading-snug text-[var(--ink)]">{s.evidence}</p>
      </div>
      <p className="mt-2 text-[13px] leading-snug text-[var(--muted)]">{s.why}</p>
      {s.detail?.heatmap_png_b64 && (
        // eslint-disable-next-line @next/next/no-img-element -- inline base64 data URI; next/image adds no value here
        <img alt="Error-level analysis heatmap" className="mt-2 max-h-44 rounded-lg border border-[var(--line)]"
          src={`data:image/png;base64,${s.detail.heatmap_png_b64}`} />
      )}
    </div>
  );
}

export function Stat({ children }: { children: ReactNode }) {
  return <span className="rounded-full bg-white/70 px-2.5 py-1 text-xs font-medium text-[var(--ink)]">{children}</span>;
}
