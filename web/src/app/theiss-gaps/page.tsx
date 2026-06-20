"use client";

import { useMemo, useState } from "react";
import { Badge, Button, Card } from "@/components/ui";
import {
  postGaps,
  type BenchmarkCell,
  type GapResult,
  type GapRow,
} from "@/lib/api/gaps";

// Fixed grid axes mirror agents/gaps.py (NEEDS × FORMATS) so the matrix is dense + readable.
const NEEDS = [
  "callus",
  "dry skin",
  "cold feet",
  "heavy legs",
  "spider veins",
  "muscle pain",
  "joint pain",
  "recovery",
  "cough/cold",
];
const FORMATS = ["cream", "gel", "spray", "bath", "foam", "balm", "device", "drops"];

type Coverage = "both" | "allgaeuer" | "competitor" | "white" | "none";

function coverageOf(cell: BenchmarkCell | undefined): Coverage {
  if (!cell) return "none";
  if (cell.allgaeuer && cell.competitors) return "both";
  if (cell.allgaeuer) return "allgaeuer";
  if (cell.competitors) return "white"; // competitor-only = the white-space we care about
  return "none";
}

// Heatmap-ish cell styling: green = Allgäuer present, amber = competitor-only WHITE-SPACE.
const CELL_STYLE: Record<Coverage, string> = {
  both: "bg-green-600 text-white",
  allgaeuer: "bg-green-200 text-green-900",
  white: "bg-amber-300 text-amber-950 ring-1 ring-amber-500",
  competitor: "bg-amber-300 text-amber-950 ring-1 ring-amber-500",
  none: "bg-slate-50 text-slate-300",
};
const CELL_GLYPH: Record<Coverage, string> = {
  both: "●",
  allgaeuer: "●",
  white: "○",
  competitor: "○",
  none: "·",
};

function BenchmarkMatrix({ cells }: { cells: BenchmarkCell[] }) {
  const byKey = useMemo(() => {
    const m = new Map<string, BenchmarkCell>();
    for (const c of cells) m.set(`${c.need.toLowerCase()}|${c.format.toLowerCase()}`, c);
    return m;
  }, [cells]);

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-0.5 text-center text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-paper p-2 text-left font-semibold text-slate-600">need ↓ / format →</th>
            {FORMATS.map((f) => (
              <th key={f} className="p-2 font-mono font-medium text-slate-500">
                {f}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {NEEDS.map((need) => (
            <tr key={need}>
              <td className="sticky left-0 z-10 bg-paper py-1.5 pr-3 text-left font-medium text-slate-700">{need}</td>
              {FORMATS.map((fmt) => {
                const cov = coverageOf(byKey.get(`${need}|${fmt}`));
                return (
                  <td
                    key={fmt}
                    title={`${need} · ${fmt} — ${
                      cov === "both"
                        ? "Allgäuer + competitors"
                        : cov === "allgaeuer"
                          ? "Allgäuer only"
                          : cov === "white" || cov === "competitor"
                            ? "WHITE-SPACE (competitors only)"
                            : "no one"
                    }`}
                    className={`h-7 w-9 rounded-md text-[13px] leading-7 ${CELL_STYLE[cov]}`}
                  >
                    {CELL_GLYPH[cov]}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-slate-600">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3.5 w-3.5 rounded bg-green-600" /> Allgäuer present
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3.5 w-3.5 rounded bg-amber-300 ring-1 ring-amber-500" /> White-space
          (competitors only)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3.5 w-3.5 rounded bg-slate-100" /> Nobody
        </span>
      </div>
    </div>
  );
}

function priorityTone(p: number): "red" | "amber" | "green" | "slate" {
  if (p >= 75) return "green";
  if (p >= 50) return "amber";
  if (p >= 25) return "slate";
  return "slate";
}

function GapCard({ gap, rank }: { gap: GapRow; rank: number }) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-semibold text-slate-400">#{rank}</span>
            <h3 className="font-semibold text-slate-900">
              {gap.need} · <span className="font-normal text-slate-600">{gap.format}</span>
            </h3>
          </div>
          {gap.covered_by_competitors && (
            <p className="mt-0.5 text-xs text-slate-500">
              Occupied today by: <span className="text-slate-700">{gap.covered_by_competitors}</span>
            </p>
          )}
        </div>
        <div className="shrink-0 text-right">
          <Badge tone={priorityTone(gap.priority)}>priority {Math.round(gap.priority)}</Badge>
          {gap.allgaeuer_present && (
            <div className="mt-1">
              <Badge tone="blue">already covered</Badge>
            </div>
          )}
        </div>
      </div>

      {/* priority bar */}
      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-green-600"
          style={{ width: `${Math.max(0, Math.min(100, gap.priority))}%` }}
        />
      </div>

      <p className="mt-3 text-sm text-slate-600">{gap.rationale}</p>

      <div className="mt-3 rounded-lg border border-green-200 bg-green-50 p-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-green-700">💡 Own-brand product idea</p>
        <p className="mt-1 text-sm text-slate-800">{gap.product_idea}</p>
      </div>
    </Card>
  );
}

export default function TheissGapsPage() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<GapResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await postGaps(file);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const analysis = result?.analysis;

  return (
    <main className="mx-auto max-w-6xl px-6 py-10 text-slate-900">
      {/* branded header — Theiss green, matches theiss-pricing chrome */}
      <div className="mb-8 border-l-4 border-green-700 pl-4">
        <p className="text-xs font-semibold tracking-widest text-green-700">
          PROBLEM 9 · DR. THEISS · MARKETING / STRATEGY
        </p>
        <h1 className="text-3xl font-bold">🧭 Competitive Gap Agent</h1>
        <p className="mt-1 text-slate-600">
          Benchmarks the <strong>Allgäuer Latschenkiefer</strong> product set against the{" "}
          <strong>competitor landscape</strong> on a need × format grid, then surfaces the ranked{" "}
          <strong>white-space gaps</strong> — concrete own-brand opportunities competitors fill but Allgäuer does not yet.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-[2fr_3fr]">
        {/* input */}
        <Card className="h-fit p-5">
          <h2 className="mb-3 text-lg font-semibold">Data pack</h2>
          <label className="mb-1 block text-sm font-medium">
            Catalogue + competitor pack (PDF — optional)
          </label>
          <input
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.docx,.xlsx,.txt,.csv"
            className="mb-3 block w-full text-sm"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <p className="mb-4 text-xs text-slate-500">
            Leave empty to run on the bundled Dr. Theiss data pack — one click, no upload needed.
          </p>
          <Button onClick={run} disabled={busy} className="bg-green-700 hover:bg-green-800">
            {busy ? "Benchmarking vs competitors…" : file ? "Analyze uploaded pack" : "Find white-space gaps"}
          </Button>
          {error && <p className="mt-3 text-sm text-red-700">⚠️ {error}</p>}

          {result && (
            <div className="mt-5 border-t border-slate-100 pt-4 text-sm">
              <h3 className="mb-2 font-semibold text-slate-700">Brand vs market</h3>
              <ul className="space-y-1.5 text-slate-600">
                <li className="flex justify-between">
                  <span>Own products read</span>
                  <Badge tone="green">{result.product_set.products.length}</Badge>
                </li>
                <li className="flex justify-between">
                  <span>Needs covered</span>
                  <Badge tone="slate">{result.product_set.needs_covered.length}</Badge>
                </li>
                <li className="flex justify-between">
                  <span>Competitors mapped</span>
                  <Badge tone="amber">{result.landscape.competitors.length}</Badge>
                </li>
                <li className="flex justify-between">
                  <span>White-space gaps</span>
                  <Badge tone="red">{analysis?.white_space.length ?? 0}</Badge>
                </li>
              </ul>
            </div>
          )}
        </Card>

        {/* result */}
        <div className="space-y-4">
          {analysis && (
            <Card className="border-green-300 bg-green-50 p-5">
              <h2 className="text-lg font-semibold">🧭 {analysis.headline}</h2>
              <p className="mt-1 text-sm text-slate-600">
                {analysis.white_space.length} white-space opportunit
                {analysis.white_space.length === 1 ? "y" : "ies"} ranked by category size × margin × brand-fit.
              </p>
              <p className="mt-1 text-xs text-slate-400">
                Confidence in benchmark (indicative data): {Math.round(analysis.confidence)}%
              </p>
            </Card>
          )}

          {analysis && (
            <Card className="p-5">
              <h2 className="mb-1 text-lg font-semibold">Benchmark grid — Allgäuer vs competitors</h2>
              <p className="mb-3 text-sm text-slate-500">
                Each cell = a need × format. Green = Allgäuer is present; amber = competitors cover it but Allgäuer
                does not (the white-space).
              </p>
              <BenchmarkMatrix cells={analysis.benchmark} />
            </Card>
          )}

          {analysis && analysis.strengths.length > 0 && (
            <Card className="p-5">
              <h2 className="mb-2 text-lg font-semibold">Where Allgäuer already out-covers competitors</h2>
              <ul className="space-y-1.5 text-sm text-slate-700">
                {analysis.strengths.map((s, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-green-700">✓</span>
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {analysis && (
            <div>
              <h2 className="mb-3 text-lg font-semibold">Prioritized white-space gaps</h2>
              <div className="space-y-3">
                {analysis.white_space.map((g, i) => (
                  <GapCard key={`${g.need}-${g.format}-${i}`} gap={g} rank={i + 1} />
                ))}
              </div>
            </div>
          )}

          {result && (
            <details className="rounded-xl border border-slate-200 bg-white p-4 text-xs">
              <summary className="cursor-pointer font-semibold text-slate-600">Raw gap analysis (JSON)</summary>
              <pre className="mt-2 overflow-auto text-[11px] text-slate-600">{JSON.stringify(result, null, 2)}</pre>
            </details>
          )}

          {!result && !busy && (
            <Card className="p-8 text-center text-sm text-slate-500">
              Click <span className="font-semibold text-green-700">Find white-space gaps</span> to benchmark the product
              set against competitors and surface the opportunities.
            </Card>
          )}
        </div>
      </div>
    </main>
  );
}
