"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card } from "@/components/ui";
import {
  approveRec,
  getPricingHistory,
  postPricing,
  rejectRec,
  type PricingCard,
  type PricingHistoryRow,
  type PricingReport,
  type SignalReading,
} from "@/lib/api/pricing";

const STATUS_TONE: Record<string, "green" | "red" | "amber" | "slate"> = {
  applied: "green",
  clamped: "amber",
  rejected: "amber",
  blocked: "red",
};

const STATUS_LABEL: Record<string, string> = {
  applied: "✅ applied",
  clamped: "🟠 clamped to band",
  rejected: "🟠 margin floor",
  blocked: "⛔ BLOCKED — anti-gouging",
};

function deltaText(pct: number): string {
  return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

function SignalChip({ s }: { s: SignalReading }) {
  const arrow = s.direction === "up" ? "🔺" : s.direction === "down" ? "🔻" : "▪️";
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-2 text-xs">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-slate-700">
          {arrow} {s.label} {s.health_event && <span className="text-red-600">· health event</span>}
        </span>
        <span className="text-slate-400">{s.configured ? s.source : "not configured"}</span>
      </div>
      <p className="mt-0.5 text-slate-500">{s.evidence}</p>
      {s.fetched_at && <p className="mt-0.5 text-[10px] text-slate-400">fetched {new Date(s.fetched_at).toLocaleString()}</p>}
    </li>
  );
}

function ProductCard({ card, onDecide }: { card: PricingCard; onDecide: (recId: string, status: string) => void }) {
  const [busy, setBusy] = useState(false);
  const tone = STATUS_TONE[card.guardrail_status] ?? "slate";
  const moved = Math.abs(card.proposed_delta_pct - card.final_delta_pct) > 0.05;

  async function decide(action: "approve" | "reject") {
    setBusy(true);
    try {
      const r = action === "approve" ? await approveRec(card.rec_id) : await rejectRec(card.rec_id);
      onDecide(card.rec_id, r.status);
    } catch {
      /* surface nothing fancy; the row just stays pending */
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className={`p-4 ${card.guardrail_status === "blocked" ? "border-red-300 bg-red-50" : ""}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold text-slate-900">{card.product}</h3>
          <Badge tone="slate">{card.category}</Badge>
        </div>
        <Badge tone={tone}>{STATUS_LABEL[card.guardrail_status] ?? card.guardrail_status}</Badge>
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        <span className="text-slate-400 line-through">€{card.base_price.toFixed(2)}</span>
        <span className="text-2xl font-bold text-green-700">€{card.final_price.toFixed(2)}</span>
        <span className={`text-sm font-semibold ${card.final_delta_pct > 0 ? "text-green-700" : card.final_delta_pct < 0 ? "text-red-600" : "text-slate-500"}`}>
          {deltaText(card.final_delta_pct)}
        </span>
      </div>

      {moved && (
        <p className="mt-1 text-xs text-slate-500">
          LLM proposed <span className="font-semibold">{deltaText(card.proposed_delta_pct)}</span> → guardrail set{" "}
          <span className="font-semibold">{deltaText(card.final_delta_pct)}</span>
        </p>
      )}

      <p className="mt-2 text-sm text-slate-600">{card.rationale}</p>

      <ul className="mt-2 space-y-1 text-xs text-slate-700">
        {card.reasons.map((r, i) => (
          <li key={i}>🛡️ {r}</li>
        ))}
      </ul>

      {card.signals.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {card.signals.map((s, i) => (
            <SignalChip key={i} s={s} />
          ))}
        </ul>
      )}

      <div className="mt-3 flex items-center gap-2">
        {card.status === "pending" ? (
          <>
            <Button onClick={() => decide("approve")} disabled={busy} className="bg-green-700 hover:bg-green-800">
              Approve
            </Button>
            <button
              onClick={() => decide("reject")}
              disabled={busy}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Reject
            </button>
          </>
        ) : (
          <Badge tone={card.status === "approved" ? "green" : "red"}>{card.status}</Badge>
        )}
      </div>
    </Card>
  );
}

export default function TheissPricingPage() {
  const [file, setFile] = useState<File | null>(null);
  const [place, setPlace] = useState("Homburg");
  const [band, setBand] = useState(20);
  const [report, setReport] = useState<PricingReport | null>(null);
  const [history, setHistory] = useState<PricingHistoryRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshHistory() {
    try {
      setHistory(await getPricingHistory());
    } catch {
      /* API may be down; ignore */
    }
  }
  useEffect(() => {
    refreshHistory();
  }, []);

  async function run() {
    if (!file) {
      setError("Choose a catalogue PDF first.");
      return;
    }
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const r = await postPricing(file, { place, bandPct: band });
      setReport(r);
      refreshHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function onDecide(recId: string, status: string) {
    setReport((prev) =>
      prev
        ? { ...prev, products: prev.products.map((p) => (p.rec_id === recId ? { ...p, status: status as PricingCard["status"] } : p)) }
        : prev,
    );
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-10 text-slate-900">
      {/* branded header */}
      <div className="mb-8 border-l-4 border-green-700 pl-4">
        <p className="text-xs font-semibold tracking-widest text-green-700">PROBLEM 8 · DR. THEISS · MARKETING / PRICING</p>
        <h1 className="text-3xl font-bold">💶 Dynamic Pricing Agent</h1>
        <p className="mt-1 text-slate-600">
          Adjusts prices on <strong>external signals</strong> (weather · season · football · supply) with deterministic{" "}
          <strong>guardrails</strong>. The LLM proposes; the guardrails dispose. An increase on an essential medicine
          during a health-event spike is <strong>blocked</strong>, not just capped.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-[2fr_3fr]">
        {/* input */}
        <Card className="h-fit p-5">
          <h2 className="mb-3 text-lg font-semibold">Catalogue</h2>
          <label className="mb-1 block text-sm font-medium">Price list / catalogue (PDF — any catalogue works)</label>
          <input
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.docx,.xlsx,.txt,.csv"
            className="mb-4 block w-full text-sm"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <label className="mb-1 block text-sm font-medium">Location (live weather signal)</label>
          <input
            className="mb-4 w-full rounded-lg border border-slate-300 p-2 text-sm"
            value={place}
            onChange={(e) => setPlace(e.target.value)}
          />
          <label className="mb-1 block text-sm font-medium">Guardrail band: ±{band}% of base (hard min/max)</label>
          <input
            type="range"
            min={5}
            max={30}
            value={band}
            onChange={(e) => setBand(Number(e.target.value))}
            className="mb-4 w-full"
          />
          <Button onClick={run} disabled={busy} className="bg-green-700 hover:bg-green-800">
            {busy ? "Fetching signals & gating…" : "Analyze prices"}
          </Button>
          {error && <p className="mt-3 text-sm text-red-700">⚠️ {error}</p>}
        </Card>

        {/* result */}
        <div className="space-y-4">
          {report && (
            <Card className={`p-5 ${report.blocked_count > 0 ? "border-red-300 bg-red-50" : "border-green-300 bg-green-50"}`}>
              <h2 className="text-lg font-semibold">
                {report.blocked_count > 0
                  ? `⛔ ${report.blocked_count} price increase(s) BLOCKED by the anti-gouging guardrail`
                  : "✅ All recommendations within guardrails"}
              </h2>
              <p className="mt-1 text-sm text-slate-600">{report.summary}</p>
              <p className="mt-1 text-xs text-slate-400">
                {report.source_note} · {report.signals.filter((s) => s.configured).length} signal(s) live · LLM calls:{" "}
                {report.llm_calls}
              </p>
            </Card>
          )}

          {report?.products.map((card) => (
            <ProductCard key={card.rec_id} card={card} onDecide={onDecide} />
          ))}

          {report && (
            <details className="rounded-xl border border-slate-200 bg-white p-4 text-xs">
              <summary className="cursor-pointer font-semibold text-slate-600">Raw pricing report (JSON)</summary>
              <pre className="mt-2 overflow-auto text-[11px] text-slate-600">{JSON.stringify(report, null, 2)}</pre>
            </details>
          )}

          <Card className="p-5">
            <h2 className="mb-2 text-lg font-semibold">Run history</h2>
            {history.length === 0 ? (
              <p className="text-sm text-slate-500">No runs yet.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {history.map((h) => (
                  <li key={h.id} className="flex items-center justify-between">
                    <span>{new Date(h.created_at).toLocaleString()}</span>
                    <span className="flex gap-1.5">
                      <Badge tone="slate">{h.product_count} products</Badge>
                      {h.blocked_count > 0 && <Badge tone="red">{h.blocked_count} blocked</Badge>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </main>
  );
}
