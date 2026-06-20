"use client";

import { useEffect, useState } from "react";
import "./persowerk.css";
import { getHistory, postAssess, type FraudReport, type HistoryRow } from "./api";
import { AnalysisPipeline, BAND, Dropzone, LENS, LENS_ORDER, RiskDial, SignalRow, Stat } from "./components";

type Phase = "idle" | "analyzing" | "done" | "error";
const MIN_ANALYSIS_MS = 2400; // let the pipeline read as an investigation, even on a cache hit
const LAST_STAGE = 4;

export default function PersowerkPage() {
  const [cv, setCv] = useState<File[]>([]);
  const [certs, setCerts] = useState<File[]>([]);
  const [github, setGithub] = useState("");
  const [links, setLinks] = useState("");
  const [runVerify, setRunVerify] = useState(false);
  const [report, setReport] = useState<FraudReport | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [phase, setPhase] = useState<Phase>("idle");
  const [stage, setStage] = useState(0);
  const [error, setError] = useState<string | null>(null);

  async function refreshHistory() {
    try {
      setHistory(await getHistory());
    } catch {
      /* API may be down; ignore */
    }
  }
  useEffect(() => {
    let active = true;
    getHistory().then((r) => active && setHistory(r)).catch(() => {});
    return () => { active = false; };
  }, []);

  // drive the analysis pipeline forward while a review is in flight.
  // (stage is reset to 0 in run(), so the effect body never calls setState synchronously.)
  useEffect(() => {
    if (phase !== "analyzing") return;
    const id = setInterval(() => setStage((s) => Math.min(s + 1, LAST_STAGE)), 620);
    return () => clearInterval(id);
  }, [phase]);

  async function run() {
    setStage(0);
    setPhase("analyzing");
    setError(null);
    setReport(null);
    const started = performance.now();
    try {
      const r = await postAssess(cv[0] ?? null, certs, github, links, runVerify);
      const wait = Math.max(0, MIN_ANALYSIS_MS - (performance.now() - started));
      await new Promise((res) => setTimeout(res, wait));
      setReport(r);
      setPhase("done");
      refreshHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }

  const canRun = cv.length > 0 || certs.length > 0;
  const band = report ? BAND[report.risk] ?? BAND.MEDIUM : null;
  const breakdown = report
    ? LENS_ORDER.filter((k) => report.by_category[k]?.length).map(
        (k) => `${report.by_category[k].length} ${LENS[k].label.toLowerCase()}`,
      )
    : [];
  const forensic = report?.by_category.forensic ?? [];

  return (
    <main className="pw min-h-screen">
      <div className="mx-auto max-w-6xl px-6 py-10">
        {/* header */}
        <header className="pw-rise mb-9">
          <p className="pw-eyebrow">Persowerk · Candidate Integrity</p>
          <h1 className="mt-1 text-[34px] font-bold leading-tight tracking-tight">Candidate Authenticity Review</h1>
          <p className="mt-1.5 max-w-2xl text-[15px] text-[var(--muted)]">
            Open a case with a CV and its certificates. We surface the fraud <strong className="text-[var(--ink)]">evidence</strong>{" "}
            for you to weigh — every flag carries the exact span it came from. This is a signal for a recruiter, never an automatic reject.
          </p>
        </header>

        <div className="grid items-start gap-6 lg:grid-cols-[minmax(320px,400px)_1fr]">
          {/* ---- intake ---- */}
          <section className="pw-card pw-rise p-5" style={{ ["--d" as string]: "60ms" }}>
            <h2 className="mb-3 text-base font-semibold">Open a case</h2>
            <div className="space-y-3">
              <Dropzone label="Candidate CV" sublabel="PDF or image · drag & drop or browse" accept=".pdf,image/*"
                files={cv} onFiles={setCv} />
              <Dropzone label="Certificates" sublabel="One or more · diplomas, licences" accept=".pdf,image/*" multiple
                files={certs} onFiles={setCerts} />
            </div>

            <div className="mt-5 border-t border-[var(--line)] pt-4">
              <p className="pw-eyebrow mb-2 text-[var(--muted)]" style={{ color: "var(--muted)" }}>Optional context</p>
              <label className="mb-1 block text-xs font-medium text-[var(--muted)]">GitHub handle or URL</label>
              <input className="mb-3 w-full rounded-lg border border-[var(--line)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--brand-2)]"
                placeholder="github.com/username" value={github} onChange={(e) => setGithub(e.target.value)} />
              <label className="mb-1 block text-xs font-medium text-[var(--muted)]">Other links (comma-separated)</label>
              <input className="mb-3 w-full rounded-lg border border-[var(--line)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--brand-2)]"
                value={links} onChange={(e) => setLinks(e.target.value)} />
              <label className="flex cursor-pointer items-start gap-2 rounded-lg bg-[var(--evidence)] p-2.5 text-sm">
                <input type="checkbox" className="mt-0.5 accent-[var(--brand)]" checked={runVerify} onChange={(e) => setRunVerify(e.target.checked)} />
                <span>
                  <span className="font-medium">Deep verification</span>
                  <span className="block text-xs text-[var(--muted)]">Run the GitHub + web agent loop (uses the LLM quota)</span>
                </span>
              </label>
            </div>

            <button
              onClick={run}
              disabled={phase === "analyzing" || !canRun}
              className="mt-4 w-full rounded-xl px-4 py-3 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50"
              style={{ background: "linear-gradient(180deg, var(--brand-2), var(--brand))" }}
            >
              {phase === "analyzing" ? "Reviewing the case…" : "Run review"}
            </button>
            {error && <p className="mt-3 text-sm text-rose-700">⚠️ {error}</p>}
          </section>

          {/* ---- case file ---- */}
          <section className="space-y-4">
            {phase === "idle" && !report && (
              <div className="pw-card pw-rise grid place-items-center px-6 py-20 text-center" style={{ ["--d" as string]: "120ms" }}>
                <div className="text-4xl">🔎</div>
                <p className="mt-3 text-lg font-semibold">No case open yet</p>
                <p className="mt-1 max-w-md text-sm text-[var(--muted)]">
                  Drop a CV (and any certificates) to open a case. You&apos;ll get evidence-tagged signals to weigh — grouped the way an investigator would.
                </p>
              </div>
            )}

            {phase === "analyzing" && (
              <div className="pw-card p-6">
                <div className="mb-4 flex items-center gap-3">
                  <span className="pw-scan h-9 w-9 rounded-full" />
                  <div>
                    <p className="text-base font-semibold">Investigating the documents…</p>
                    <p className="text-xs text-[var(--muted)]">Deterministic checks run locally; the model only reads the files.</p>
                  </div>
                </div>
                <AnalysisPipeline stage={stage} runVerify={runVerify} />
              </div>
            )}

            {phase !== "analyzing" && report && band && (
              <>
                {/* verdict */}
                <div className="pw-card pw-reveal flex flex-col gap-5 p-6 sm:flex-row sm:items-center" style={{ ["--d" as string]: "0ms" }}>
                  <RiskDial score={report.score} band={report.risk} />
                  <div className="min-w-0 flex-1">
                    <span className="pw-pop inline-block rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wide"
                      style={{ color: band.fg, background: band.bg, boxShadow: `inset 0 0 0 1px ${band.ring}55` }}>
                      {band.verb}
                    </span>
                    <h2 className="mt-2 text-2xl font-bold tracking-tight">{band.label}</h2>
                    <p className="mt-1 text-sm text-[var(--muted)]">
                      {report.candidate_name ? <strong className="text-[var(--ink)]">{report.candidate_name}</strong> : "This candidate"}
                      {breakdown.length ? ` · ${breakdown.join(" · ")}` : " · nothing notable in the review"}
                      {forensic.length ? ` · ${forensic.length} technical check${forensic.length === 1 ? "" : "s"}` : ""}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {report.verify_ran && <Stat>✓ deep-verified</Stat>}
                      <Stat>{report.llm_calls} model call{report.llm_calls === 1 ? "" : "s"}</Stat>
                      {report.agent_steps > 0 && <Stat>{report.agent_steps} agent steps</Stat>}
                    </div>
                  </div>
                </div>

                {/* methodology / trust */}
                <details className="pw-card pw-reveal p-4 text-sm" style={{ ["--d" as string]: "60ms" }}>
                  <summary className="cursor-pointer font-medium">How we read this</summary>
                  <p className="mt-2 text-[13px] leading-relaxed text-[var(--muted)]">{report.methodology_note}</p>
                </details>

                {/* evidence grouped by lens */}
                {LENS_ORDER.filter((k) => report.by_category[k]?.length).map((k, idx) => {
                  const sigs = report.by_category[k];
                  const lens = LENS[k] ?? { label: k, blurb: "", icon: "•" };
                  return (
                    <div key={k} className="pw-card pw-reveal p-5" style={{ ["--d" as string]: `${120 + idx * 60}ms` }}>
                      <div className="mb-3 flex items-center gap-2.5">
                        <span className="grid h-8 w-8 place-items-center rounded-lg bg-[var(--evidence)] text-base">{lens.icon}</span>
                        <div>
                          <h3 className="text-sm font-semibold leading-tight">{lens.label}</h3>
                          <p className="text-xs text-[var(--muted)]">{lens.blurb}</p>
                        </div>
                        <span className="ml-auto pw-mono text-xs text-[var(--muted)]">{sigs.length}</span>
                      </div>
                      <div className="space-y-2.5">
                        {sigs.map((s, i) => <SignalRow key={i} s={s} />)}
                      </div>
                    </div>
                  );
                })}

                {/* certificates */}
                {report.cert_summaries.length > 0 && (
                  <div className="pw-card pw-reveal p-5" style={{ ["--d" as string]: "260ms" }}>
                    <h3 className="mb-3 text-sm font-semibold">🎓 Certificates read</h3>
                    <ul className="space-y-2">
                      {report.cert_summaries.map((c, i) => (
                        <li key={i} className="flex items-center justify-between gap-3 rounded-lg border border-[var(--line)] px-3 py-2.5 text-sm">
                          <span className="min-w-0">
                            <span className="block truncate font-medium">{c.title ?? c.filename}</span>
                            <span className="text-xs text-[var(--muted)]">{c.issuer ?? "issuer unknown"}{c.valid_until ? ` · valid until ${c.valid_until}` : ""}</span>
                          </span>
                          <span className="pw-mono shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold"
                            style={c.is_current ? { color: "#047857", background: "#ecfdf5" } : { color: "#b45309", background: "#fffbeb" }}>
                            {c.decision.replace(/_/g, " ").toLowerCase()}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* low-level forensics — kept out of the recruiter's main flow on purpose */}
                {forensic.length > 0 && (
                  <details className="pw-card pw-reveal p-4" style={{ ["--d" as string]: "300ms" }}>
                    <summary className="cursor-pointer text-sm font-medium">
                      🔬 Technical document checks ({forensic.length})
                      <span className="ml-1 font-normal text-[var(--muted)]">— for a security / IT reviewer, safe to skip</span>
                    </summary>
                    <div className="mt-3 space-y-2.5">
                      {forensic.map((s, i) => <SignalRow key={i} s={s} />)}
                    </div>
                  </details>
                )}

                <details className="pw-card pw-reveal p-4 text-xs" style={{ ["--d" as string]: "340ms" }}>
                  <summary className="cursor-pointer font-medium">Extracted data (raw)</summary>
                  <pre className="pw-mono mt-2 overflow-x-auto rounded-lg bg-[var(--evidence)] p-3 text-[11px] leading-relaxed">
                    {JSON.stringify(report.extraction, null, 2)}
                  </pre>
                </details>
              </>
            )}

            {/* case history */}
            <div className="pw-card pw-rise p-5" style={{ ["--d" as string]: "180ms" }}>
              <h2 className="mb-3 text-sm font-semibold">Case history</h2>
              {history.length === 0 ? (
                <p className="text-sm text-[var(--muted)]">No reviews yet.</p>
              ) : (
                <ul className="divide-y divide-[var(--line)]">
                  {history.map((h) => {
                    const hb = BAND[h.risk] ?? BAND.MEDIUM;
                    return (
                      <li key={h.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{h.candidate_name ?? "Unnamed candidate"}</span>
                          <span className="text-xs text-[var(--muted)]">{new Date(h.created_at).toLocaleString()}</span>
                        </span>
                        <span className="pw-tnum pw-mono shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold"
                          style={{ color: hb.fg, background: hb.bg }}>
                          {h.risk} {Math.round(h.score)}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
