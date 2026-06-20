"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card } from "@/components/ui";
import { getHistory, postAssess, type FraudReport, type HistoryRow, type Signal } from "./api";

const SEV_TONE: Record<string, "red" | "amber" | "slate"> = { high: "red", medium: "amber", low: "slate" };
const RISK_BG: Record<string, string> = {
  HIGH: "border-red-300 bg-red-50",
  MEDIUM: "border-amber-300 bg-amber-50",
  LOW: "border-green-300 bg-green-50",
};
const CATEGORY_LABEL: Record<string, string> = {
  forensic: "📄 Document forensics",
  consistency: "🧩 Consistency",
  certificate: "🎓 Certificate",
  verification: "🔗 Public-footprint verification",
  injection: "🛡️ Prompt-injection",
};

function SignalCard({ s }: { s: Signal }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="flex items-center justify-between">
        <span className="font-medium">{s.name.replace(/_/g, " ")}</span>
        <span className="flex gap-1.5">
          {s.weak && <Badge tone="slate">weak</Badge>}
          <Badge tone={SEV_TONE[s.severity]}>{s.severity}</Badge>
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-800">{s.evidence}</p>
      <p className="mt-1 text-xs text-slate-500">{s.why}</p>
      {s.detail?.heatmap_png_b64 && (
        // eslint-disable-next-line @next/next/no-img-element -- inline base64 data URI; next/image adds no value here
        <img
          alt="ELA heatmap"
          className="mt-2 max-h-48 rounded border"
          src={`data:image/png;base64,${s.detail.heatmap_png_b64}`}
        />
      )}
    </div>
  );
}

export default function PersowerkPage() {
  const [cv, setCv] = useState<File | null>(null);
  const [certs, setCerts] = useState<File[]>([]);
  const [github, setGithub] = useState("");
  const [links, setLinks] = useState("");
  const [runVerify, setRunVerify] = useState(false);
  const [report, setReport] = useState<FraudReport | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshHistory() {
    try {
      setHistory(await getHistory());
    } catch {
      /* API may be down; ignore */
    }
  }
  // Load history on mount. setState lives in the promise continuation (async), and the
  // cancellation flag avoids a state update after unmount.
  useEffect(() => {
    let active = true;
    getHistory()
      .then((rows) => {
        if (active) setHistory(rows);
      })
      .catch(() => {
        /* API may be down; ignore */
      });
    return () => {
      active = false;
    };
  }, []);

  async function run() {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const r = await postAssess(cv, certs, github, links, runVerify);
      setReport(r);
      refreshHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 text-slate-900">
      <div className="mb-8 border-l-4 pl-4" style={{ borderColor: "#6b21a8" }}>
        <p className="text-xs font-semibold tracking-widest text-slate-500">
          PROBLEM 4 · PERSOWERK · TALENT / VERIFICATION
        </p>
        <h1 className="text-3xl font-bold">🔎 CV &amp; Certificate Authenticity Agent</h1>
        <p className="mt-1 text-slate-600">
          Cross-checks work history and skills, flags fabrication signals, and verifies certificates are real and
          current — <strong>each flag carries its exact evidence for a recruiter to review.</strong>
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-5">
          <h2 className="mb-3 text-lg font-semibold">Upload</h2>
          <label className="mb-1 block text-sm font-medium">CV (PDF / image)</label>
          <input
            type="file"
            className="mb-4 block w-full text-sm"
            onChange={(e) => setCv(e.target.files?.[0] ?? null)}
          />
          <label className="mb-1 block text-sm font-medium">Certificate(s) (PDF / image)</label>
          <input
            type="file"
            multiple
            className="mb-4 block w-full text-sm"
            onChange={(e) => setCerts(Array.from(e.target.files ?? []))}
          />
          <label className="mb-1 block text-sm font-medium">GitHub handle / URL (optional)</label>
          <input
            className="mb-4 w-full rounded-lg border border-slate-300 p-2 text-sm"
            placeholder="github.com/username"
            value={github}
            onChange={(e) => setGithub(e.target.value)}
          />
          <label className="mb-1 block text-sm font-medium">Other links (comma-separated, optional)</label>
          <input
            className="mb-4 w-full rounded-lg border border-slate-300 p-2 text-sm"
            value={links}
            onChange={(e) => setLinks(e.target.value)}
          />
          <label className="mb-4 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={runVerify} onChange={(e) => setRunVerify(e.target.checked)} />
            Run live GitHub/web verification (uses the LLM agent loop)
          </label>
          <Button onClick={run} disabled={busy || (!cv && certs.length === 0)}>
            {busy ? "Analysing…" : "Analyse documents"}
          </Button>
          {error && <p className="mt-3 text-sm text-red-700">⚠️ {error}</p>}
        </Card>

        <div className="space-y-4">
          {report && (
            <>
              <Card className={`p-5 ${RISK_BG[report.risk]}`}>
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold">Fraud-signal risk: {report.risk}</h2>
                  <span className="text-2xl font-bold">
                    {report.score}
                    <span className="text-base text-slate-500">/100</span>
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-700">{report.summary}</p>
                <p className="mt-3 rounded bg-white/70 p-2 text-xs text-slate-600">{report.methodology_note}</p>
              </Card>

              {Object.entries(report.by_category).map(([cat, sigs]) => (
                <Card key={cat} className="p-5">
                  <h3 className="mb-2 text-sm font-semibold">{CATEGORY_LABEL[cat] ?? cat}</h3>
                  <div className="space-y-2">
                    {sigs.map((s, i) => (
                      <SignalCard key={i} s={s} />
                    ))}
                  </div>
                </Card>
              ))}

              {report.cert_summaries.length > 0 && (
                <Card className="p-5">
                  <h3 className="mb-2 text-sm font-semibold">🎓 Certificates</h3>
                  <ul className="space-y-1.5 text-sm">
                    {report.cert_summaries.map((c, i) => (
                      <li key={i} className="flex items-center justify-between">
                        <span>
                          {c.title ?? c.filename} {c.issuer ? `· ${c.issuer}` : ""}
                        </span>
                        <Badge tone={c.is_current ? "green" : "amber"}>{c.decision.replace(/_/g, " ")}</Badge>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              <details className="rounded-xl border border-slate-200 bg-white p-4 text-xs">
                <summary className="cursor-pointer font-medium">Extracted data (raw)</summary>
                <pre className="mt-2 overflow-x-auto">{JSON.stringify(report.extraction, null, 2)}</pre>
              </details>
              <p className="text-xs text-slate-400">
                LLM calls: {report.llm_calls} · agent steps: {report.agent_steps}
              </p>
            </>
          )}

          <Card className="p-5">
            <h2 className="mb-2 text-lg font-semibold">History</h2>
            {history.length === 0 ? (
              <p className="text-sm text-slate-500">No assessments yet.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {history.map((h) => (
                  <li key={h.id} className="flex items-center justify-between">
                    <span>
                      {new Date(h.created_at).toLocaleString()} · {h.candidate_name ?? "—"}
                    </span>
                    <Badge tone={h.risk === "HIGH" ? "red" : h.risk === "MEDIUM" ? "amber" : "green"}>
                      {h.risk} {h.score}
                    </Badge>
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
