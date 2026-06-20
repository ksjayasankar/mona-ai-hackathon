import type { Eligible, Outreach } from "../api";
import { StatusPill } from "./StatusPill";

export function CandidateRow({ c, rank, outreach }: { c: Eligible; rank: number; outreach?: Outreach }) {
  const top = rank === 1;
  return (
    <div
      className={`rounded-xl border p-4 transition ${
        top ? "border-amber-300 bg-amber-50/60 shadow-sm" : "border-slate-200 bg-white"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-semibold text-slate-900">
            <span className={`grid h-6 w-6 place-items-center rounded-full text-xs font-bold ${top ? "bg-amber-400 text-white" : "bg-slate-200 text-slate-600"}`}>
              {rank}
            </span>
            {c.name}
          </div>
          <div className="mt-0.5 text-xs text-slate-500">
            {c.role} · {c.department} · 📞 {c.phone}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          {outreach && <StatusPill status={outreach.status} />}
          <span className="rounded-md bg-slate-900 px-2 py-0.5 text-xs font-semibold text-white">score {c.score}</span>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
        <Meta>{c.contract}</Meta>
        <Meta>{Math.round(c.scheduled_hours)}/{Math.round(c.max_hours)}h wk</Meta>
        {c.rest_hours != null && <Meta>{Math.round(c.rest_hours)}h rest</Meta>}
        <Meta tone={c.overtime_ok ? "ok" : "muted"}>{c.overtime_ok ? "OT OK" : "no OT"}</Meta>
      </div>

      <ul className="mt-2.5 space-y-1 text-sm text-slate-600">
        {c.why.map((w, i) => (
          <li key={i} className="flex gap-1.5">
            <span className="text-emerald-500">✓</span>
            <span>{w}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Meta({ children, tone = "muted" }: { children: React.ReactNode; tone?: "ok" | "muted" }) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 font-medium ${
        tone === "ok" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"
      }`}
    >
      {children}
    </span>
  );
}
