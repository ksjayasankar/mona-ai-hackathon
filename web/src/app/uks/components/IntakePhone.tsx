"use client";

import { useState } from "react";
import type { GapState } from "../api";

const SAMPLES = [
  "Felix Haddad (HOSP-1059) just called in sick for tonight's ICU night shift (Sat 06/20, 19:00-07:00). He's a Registered Nurse, ICU needs BLS + ACLS. Find me cover ASAP.",
  "Need a day-shift RN for Cardiology tomorrow, someone called out. BLS required.",
];

const FELIX = {
  role: "Registered Nurse",
  department: "ICU",
  shift: "night",
  day_label: "Sat 06/20",
  required_certs: ["BLS", "ACLS"],
  person_out: "Felix Haddad (HOSP-1059)",
};

export function IntakePhone({
  onSubmit,
  busy,
  parsed,
}: {
  onSubmit: (b: { message?: string; structured?: object }) => void;
  busy: boolean;
  parsed: GapState["gap"] | null;
}) {
  const [msg, setMsg] = useState(SAMPLES[0]);
  const chips = parsed
    ? [parsed.role, parsed.department, `${parsed.shift} shift`, ...(parsed.required_certs ?? [])].filter(Boolean)
    : [];

  return (
    <div className="rounded-[2rem] border-4 border-slate-800 bg-slate-800 p-2 shadow-xl">
      <div className="flex flex-col rounded-[1.5rem] bg-white">
        {/* phone status bar */}
        <div className="flex items-center justify-between rounded-t-[1.5rem] bg-[#b3122b] px-4 py-2 text-xs font-medium text-white">
          <span>📱 UKS staffing line</span>
          <span>18:30</span>
        </div>
        <div className="px-4 py-1.5 text-[11px] font-semibold text-slate-400">Ward Sister · ICU</div>

        {/* incoming message bubble */}
        <div className="px-4 pb-2">
          <div className="max-w-[88%] rounded-2xl rounded-tl-sm bg-slate-100 px-3 py-2 text-sm text-slate-800">
            {msg}
          </div>
          {busy && <div className="mt-2 text-xs italic text-slate-400">agent reading the message…</div>}
          {chips.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              <span className="text-[11px] font-semibold text-slate-400">parsed →</span>
              {chips.map((chip, i) => (
                <span key={i} className="rounded-full bg-[#b3122b]/10 px-2 py-0.5 text-[11px] font-semibold text-[#b3122b]">
                  {chip}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* composer */}
        <div className="border-t border-slate-100 px-3 py-3">
          <textarea
            className="mb-2 h-20 w-full rounded-lg border border-slate-200 p-2 text-sm focus:border-[#b3122b] focus:outline-none"
            value={msg}
            onChange={(e) => setMsg(e.target.value)}
          />
          <div className="mb-2 flex flex-wrap gap-1.5">
            {SAMPLES.map((s, i) => (
              <button
                key={i}
                onClick={() => setMsg(s)}
                className="rounded border border-slate-200 px-2 py-0.5 text-[11px] text-slate-500 hover:bg-slate-50"
              >
                sample {i + 1}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => onSubmit({ message: msg })}
              disabled={busy}
              className="flex-1 rounded-lg bg-[#b3122b] px-3 py-2 text-sm font-semibold text-white transition hover:bg-[#8f0e22] disabled:opacity-50"
            >
              {busy ? "Working…" : "Find cover (AI parses)"}
            </button>
            <button
              onClick={() => onSubmit({ structured: FELIX })}
              disabled={busy}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
            >
              Scenario
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
