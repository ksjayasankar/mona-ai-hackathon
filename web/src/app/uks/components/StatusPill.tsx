const TONE: Record<string, string> = {
  queued: "bg-slate-100 text-slate-600 ring-slate-200",
  sent: "bg-amber-100 text-amber-800 ring-amber-200",
  accepted: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  declined: "bg-rose-100 text-rose-800 ring-rose-200",
  closed: "bg-slate-100 text-slate-400 ring-slate-200",
  open: "bg-amber-100 text-amber-800 ring-amber-200",
  filled: "bg-emerald-100 text-emerald-800 ring-emerald-200",
};

export function StatusPill({ status, label }: { status: string; label?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset ${
        TONE[status] ?? "bg-slate-100 text-slate-600 ring-slate-200"
      }`}
    >
      {(status === "open" || status === "filled") && (
        <span className={`h-1.5 w-1.5 rounded-full ${status === "open" ? "bg-amber-500" : "bg-emerald-500"}`} />
      )}
      {label ?? status}
    </span>
  );
}
