"use client";

import { useState } from "react";
import { Badge, Button, Card, Mono } from "@/components/ui";
import {
  runAnalytics,
  type AnalyticsReport,
  type LiftResult,
  type SegmentRow,
  type TargetingPlan,
  type WeeklyPoint,
} from "@/lib/api/analytics";

const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function eur(n: number): string {
  return `€${n.toFixed(2)}`;
}

function pct(n: number): string {
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}

function liftTone(v: LiftResult["verdict"]): "green" | "red" | "slate" {
  return v === "LIFT" ? "green" : v === "DROP" ? "red" : "slate";
}

function fmtDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "long", year: "numeric" });
}

/* ---- Box 1: customer segments (RFM) ----------------------------------- */
function SegmentsTable({ segments }: { segments: SegmentRow[] }) {
  return (
    <Card className="p-5">
      <div className="mb-1 flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">📊 Customer segments</h2>
        <span className="text-xs text-slate-400">RFM + seasonal affinity · sorted by value</span>
      </div>
      <p className="mb-3 text-sm text-slate-600">
        Behavioural segments detected in the transaction log. The top row is the highest-value segment — the one we target.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400">
              <th className="py-2 pr-3 font-semibold">Segment</th>
              <th className="py-2 px-3 font-semibold">Customers</th>
              <th className="py-2 px-3 font-semibold">Avg spend</th>
              <th className="py-2 px-3 font-semibold">Freq</th>
              <th className="py-2 px-3 font-semibold">Recency</th>
              <th className="py-2 px-3 font-semibold">Top product</th>
              <th className="py-2 pl-3 font-semibold">Peak</th>
            </tr>
          </thead>
          <tbody>
            {segments.map((s, i) => (
              <tr key={s.segment} className={`border-b border-slate-100 ${i === 0 ? "bg-green-50" : ""}`}>
                <td className="py-2 pr-3 font-medium text-slate-800">
                  {i === 0 && <span className="mr-1">⭐</span>}
                  {s.segment}
                </td>
                <td className="py-2 px-3 text-slate-700">
                  <Mono>{s.customers}</Mono>
                </td>
                <td className="py-2 px-3 font-semibold text-green-700">
                  <Mono>{eur(s.avg_monetary_eur)}</Mono>
                </td>
                <td className="py-2 px-3 text-slate-700">
                  <Mono>{s.avg_frequency.toFixed(1)}</Mono>
                </td>
                <td className="py-2 px-3 text-slate-700">
                  <Mono>{Math.round(s.avg_recency_days)}d</Mono>
                </td>
                <td className="py-2 px-3 text-slate-600">{s.top_product}</td>
                <td className="py-2 pl-3 text-slate-600">{MONTHS[s.peak_month]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ---- Box 2 + 3: targeting signal + the OPTIMAL date/time -------------- */
function TargetingCard({ plan }: { plan: TargetingPlan }) {
  return (
    <Card className="border-green-300 bg-green-50 p-5">
      <h2 className="text-lg font-semibold">🎯 Targeting recommendation</h2>
      <p className="mt-1 text-sm text-slate-700">{plan.headline}</p>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-green-200 bg-white p-3">
          <div className="text-xs uppercase tracking-wide text-slate-400">Segment</div>
          <div className="mt-0.5 font-semibold text-slate-800">{plan.target_segment}</div>
        </div>
        <div className="rounded-xl border border-green-200 bg-white p-3">
          <div className="text-xs uppercase tracking-wide text-slate-400">Product</div>
          <div className="mt-0.5 font-semibold text-slate-800">{plan.product}</div>
        </div>
        <div className="rounded-xl border border-green-200 bg-white p-3">
          <div className="text-xs uppercase tracking-wide text-slate-400">Channel</div>
          <div className="mt-0.5 font-semibold text-slate-800">{plan.channel}</div>
        </div>
      </div>

      {/* the OPTIMAL date/time — highlighted */}
      <div className="mt-4 rounded-xl border-2 border-green-600 bg-white p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-xs font-semibold uppercase tracking-widest text-green-700">⏰ Optimal send window</span>
          <Badge tone="green">{Math.round(plan.confidence)}% confidence</Badge>
        </div>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-2xl font-bold text-green-700">
            <Mono>{fmtDate(plan.optimal_date)}</Mono>
          </span>
          <span className="text-2xl font-bold text-green-700">
            @ <Mono>{plan.optimal_time}</Mono>
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          Sent just before the segment&apos;s seasonal demand peak, at the best time-of-day for this channel.
        </p>
      </div>

      <ul className="mt-3 space-y-1 text-sm text-slate-700">
        {plan.rationale.map((r, i) => (
          <li key={i}>· {r}</li>
        ))}
      </ul>

      <p className="mt-3 text-xs text-slate-500">
        Expected uplift (forecast): <Mono className="font-semibold text-green-700">{pct(plan.expected_lift_pct)}</Mono>
      </p>
    </Card>
  );
}

/* ---- before/after weekly sparkbars ------------------------------------ */
function WeeklyBars({ weekly }: { weekly: WeeklyPoint[] }) {
  if (weekly.length === 0) return null;
  const max = Math.max(...weekly.map((w) => w.units), 1);
  return (
    <div className="mt-3 flex h-24 items-end gap-1">
      {weekly.map((w, i) => (
        <div
          key={i}
          title={`${w.week} · ${w.units} units (${w.phase})`}
          className={`flex-1 rounded-t ${w.phase === "post" ? "bg-green-600" : "bg-slate-300"}`}
          style={{ height: `${(w.units / max) * 100}%` }}
        />
      ))}
    </div>
  );
}

/* ---- Box 4: MEASURED lift --------------------------------------------- */
function LiftCard({ lift, weekly }: { lift: LiftResult; weekly: WeeklyPoint[] }) {
  return (
    <Card className="p-5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">📈 Measured lift</h2>
        <Badge tone={liftTone(lift.verdict)}>
          {lift.verdict === "LIFT" ? "✅ LIFT" : lift.verdict === "DROP" ? "🔻 DROP" : "▪️ no change"}
        </Badge>
      </div>
      <p className="mt-1 text-sm text-slate-600">
        Weekly unit sales of <strong>{lift.product}</strong>, the {lift.weeks_pre} weeks before vs the {lift.weeks_post}{" "}
        weeks after the campaign send.
      </p>

      <div className="mt-4 grid grid-cols-3 gap-3 text-center">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs uppercase tracking-wide text-slate-400">Before</div>
          <div className="mt-1 text-2xl font-bold text-slate-700">
            <Mono>{lift.pre_mean_weekly.toFixed(0)}</Mono>
          </div>
          <div className="text-xs text-slate-400">units / week</div>
        </div>
        <div className="rounded-xl border border-green-200 bg-green-50 p-3">
          <div className="text-xs uppercase tracking-wide text-slate-400">After</div>
          <div className="mt-1 text-2xl font-bold text-green-700">
            <Mono>{lift.post_mean_weekly.toFixed(0)}</Mono>
          </div>
          <div className="text-xs text-slate-400">units / week</div>
        </div>
        <div className="rounded-xl border-2 border-green-600 bg-white p-3">
          <div className="text-xs uppercase tracking-wide text-slate-400">Uplift</div>
          <div className={`mt-1 text-2xl font-bold ${lift.lift_pct >= 0 ? "text-green-700" : "text-red-600"}`}>
            <Mono>{pct(lift.lift_pct)}</Mono>
          </div>
          <div className="text-xs text-slate-400">measured</div>
        </div>
      </div>

      <WeeklyBars weekly={weekly} />
      <div className="mt-1 flex items-center justify-between text-[11px] text-slate-400">
        <span>
          <span className="inline-block h-2 w-2 rounded-sm bg-slate-300" /> before send
        </span>
        <span>
          <span className="inline-block h-2 w-2 rounded-sm bg-green-600" /> after send
        </span>
      </div>
      <p className="mt-2 text-xs text-slate-500">{lift.note}</p>
    </Card>
  );
}

export default function TheissAnalyticsPage() {
  const [channel, setChannel] = useState("Instagram");
  const [report, setReport] = useState<AnalyticsReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      setReport(await runAnalytics({ channel }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-10 text-slate-900">
      {/* branded header — matches the Dr. Theiss pricing flagship chrome */}
      <div className="mb-8 border-l-4 border-green-700 pl-4">
        <p className="text-xs font-semibold tracking-widest text-green-700">PROBLEM 7 · DR. THEISS · MARKETING</p>
        <h1 className="text-3xl font-bold">📊 Targeting Analytics Agent</h1>
        <p className="mt-1 text-slate-600">
          Ingests customer data, finds behavioural <strong>segments</strong>, recommends <strong>who to target</strong>{" "}
          and the <strong>optimal date &amp; time</strong> to send — then <strong>measures the lift</strong> afterwards.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-[2fr_3fr]">
        {/* input */}
        <Card className="h-fit p-5">
          <h2 className="mb-3 text-lg font-semibold">Run analysis</h2>
          <p className="mb-4 text-sm text-slate-600">
            Analyses the brand&apos;s indicative customer transactions (generated from the data pack&apos;s segments and
            seasonal peaks). One click runs the full flow.
          </p>
          <label className="mb-1 block text-sm font-medium">Preferred channel</label>
          <select
            className="mb-4 w-full rounded-lg border border-slate-300 p-2 text-sm"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
          >
            {(report?.channels ?? ["Instagram", "Facebook", "Pharmacy e-mail newsletter", "In-pharmacy QR / leaflet"]).map(
              (c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ),
            )}
          </select>
          <Button onClick={run} disabled={busy} className="bg-green-700 hover:bg-green-800">
            {busy ? "Crunching segments…" : "Run targeting analysis"}
          </Button>
          {error && <p className="mt-3 text-sm text-red-700">⚠️ {error}</p>}

          {report && (
            <div className="mt-4 grid grid-cols-2 gap-3 border-t border-slate-100 pt-4 text-center">
              <div>
                <div className="text-2xl font-bold text-slate-800">
                  <Mono>{report.n_customers}</Mono>
                </div>
                <div className="text-xs text-slate-400">customers</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">
                  <Mono>{report.n_transactions}</Mono>
                </div>
                <div className="text-xs text-slate-400">transactions</div>
              </div>
            </div>
          )}
          {report && <p className="mt-3 text-[11px] text-slate-400">{report.note}</p>}
        </Card>

        {/* results — all four acceptance boxes */}
        <div className="space-y-4">
          {!report && !busy && (
            <Card className="grid place-items-center border-dashed p-16 text-center text-slate-400">
              Click “Run targeting analysis” to detect segments, get the best date/time to market, and measure the lift.
            </Card>
          )}

          {report && (
            <>
              <SegmentsTable segments={report.segments} />
              <TargetingCard plan={report.plan} />
              <LiftCard lift={report.lift} weekly={report.weekly} />

              <details className="rounded-xl border border-slate-200 bg-white p-4 text-xs">
                <summary className="cursor-pointer font-semibold text-slate-600">Raw analytics report (JSON)</summary>
                <pre className="mt-2 overflow-auto text-[11px] text-slate-600">{JSON.stringify(report, null, 2)}</pre>
              </details>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
