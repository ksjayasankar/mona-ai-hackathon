"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Badge, Button, Card } from "@/components/ui";
import { acceptToken } from "../api";

interface AcceptResult {
  result: "confirmed" | "already_filled" | "invalid" | "declined";
  staff_name?: string | null;
  filled_by?: string | null;
  detail?: string;
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

  return (
    <main className="mx-auto max-w-lg px-6 py-16 text-slate-900">
      <div className="mb-6 border-l-4 pl-4" style={{ borderColor: "#b3122b" }}>
        <p className="text-xs font-semibold tracking-widest text-slate-500">UKS · STAFFING</p>
        <h1 className="text-2xl font-bold">🏥 Shift offer</h1>
      </div>

      {!token && <Card className="p-6 text-sm text-red-700">This link is missing its token.</Card>}

      {token && !res && (
        <Card className="p-6">
          <p className="mb-4 text-slate-700">
            You&apos;ve been asked to cover an urgent shift. Tap below to accept it — the first qualified colleague to
            accept gets the shift.
          </p>
          <Button onClick={confirm} disabled={busy}>
            {busy ? "Confirming…" : "✅ Accept this shift"}
          </Button>
          {err && <p className="mt-3 text-sm text-red-700">⚠️ {err}</p>}
        </Card>
      )}

      {res?.result === "confirmed" && (
        <Card className="border-green-300 bg-green-50 p-6">
          <Badge tone="green">Confirmed</Badge>
          <p className="mt-3 text-slate-800">
            Thank you{res.staff_name ? `, ${res.staff_name.split(" ")[0]}` : ""}! You&apos;re confirmed for the shift.
            The roster has been updated and the coordinator notified.
          </p>
        </Card>
      )}

      {res?.result === "already_filled" && (
        <Card className="border-amber-300 bg-amber-50 p-6">
          <Badge tone="amber">Already filled</Badge>
          <p className="mt-3 text-slate-800">
            This shift was just filled{res.filled_by ? ` by ${res.filled_by}` : ""} — thank you anyway. No action
            needed.
          </p>
        </Card>
      )}

      {res?.result === "invalid" && (
        <Card className="border-red-300 bg-red-50 p-6">
          <Badge tone="red">Invalid link</Badge>
          <p className="mt-3 text-slate-800">This link is no longer valid{res.detail ? ` (${res.detail})` : ""}.</p>
        </Card>
      )}
    </main>
  );
}

export default function AcceptPage() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-lg px-6 py-16 text-slate-500">Loading…</main>}>
      <AcceptInner />
    </Suspense>
  );
}
