"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { acceptToken } from "../api";
import { StatusPill } from "../components/StatusPill";

interface AcceptResult {
  result: "confirmed" | "already_filled" | "invalid" | "declined";
  staff_name?: string | null;
  filled_by?: string | null;
  detail?: string;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="grid min-h-screen place-items-center bg-slate-50 px-6 py-16 text-slate-900">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#b3122b] text-lg text-white">🏥</div>
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">UKS · Staffing</div>
            <h1 className="text-lg font-bold leading-tight">Shift offer</h1>
          </div>
        </div>
        {children}
      </div>
    </main>
  );
}

function Card({ children, tone = "white" }: { children: React.ReactNode; tone?: "white" | "green" | "amber" | "red" }) {
  const tones = {
    white: "border-slate-200 bg-white",
    green: "border-emerald-200 bg-emerald-50",
    amber: "border-amber-200 bg-amber-50",
    red: "border-rose-200 bg-rose-50",
  };
  return <div className={`rounded-2xl border p-6 shadow-sm ${tones[tone]}`}>{children}</div>;
}

function AcceptInner() {
  const token = useSearchParams().get("token") ?? "";
  const [res, setRes] = useState<AcceptResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setErr(null);
    try {
      setRes((await acceptToken(token)) as AcceptResult);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <Shell>
        <Card tone="red">This link is missing its token.</Card>
      </Shell>
    );
  }

  return (
    <Shell>
      {!res && (
        <Card>
          <p className="mb-5 text-slate-700">
            You&apos;ve been asked to cover an urgent shift. The first qualified colleague to accept gets it.
          </p>
          <button
            onClick={confirm}
            disabled={busy}
            className="w-full rounded-lg bg-[#b3122b] px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#8f0e22] disabled:opacity-50"
          >
            {busy ? "Confirming…" : "✅ Accept this shift"}
          </button>
          {err && <p className="mt-3 text-sm text-rose-700">⚠️ {err}</p>}
        </Card>
      )}

      {res?.result === "confirmed" && (
        <Card tone="green">
          <StatusPill status="accepted" label="confirmed" />
          <p className="mt-3 text-slate-800">
            Thank you{res.staff_name ? `, ${res.staff_name.split(" ")[0]}` : ""}! You&apos;re confirmed for the shift.
            The roster has been updated and the coordinator notified.
          </p>
        </Card>
      )}

      {res?.result === "already_filled" && (
        <Card tone="amber">
          <StatusPill status="closed" label="already filled" />
          <p className="mt-3 text-slate-800">
            This shift was just filled{res.filled_by ? ` by ${res.filled_by}` : ""} — thank you anyway. No action needed.
          </p>
        </Card>
      )}

      {res?.result === "invalid" && (
        <Card tone="red">
          <StatusPill status="declined" label="invalid" />
          <p className="mt-3 text-slate-800">This link is no longer valid{res.detail ? ` (${res.detail})` : ""}.</p>
        </Card>
      )}
    </Shell>
  );
}

export default function AcceptPage() {
  return (
    <Suspense fallback={<main className="grid min-h-screen place-items-center text-slate-500">Loading…</main>}>
      <AcceptInner />
    </Suspense>
  );
}
