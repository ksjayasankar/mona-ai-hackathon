"use client";

import { useEffect, useState } from "react";
import { Badge, Card } from "@/components/ui";
import {
  getPermitHistory,
  getReviewQueue,
  postPermit,
  reviewPermit,
  type Decision,
  type PermitCheck,
  type PermitHistoryRow,
} from "@/lib/api/permits";

// ---- Leistenschneider branding (core.config CUSTOMERS["leistenschneider"]) ----
const BRAND = "#1f4e8c";

const SAMPLES: { name: string; file: string }[] = [
  { name: "Skilled worker (§ 18a)", file: "permit_wp_valid_01.pdf" },
  { name: "EU Blue Card (§ 18b)", file: "permit_wp_valid_02.pdf" },
  { name: "Student permit (§ 16b)", file: "permit_wp_invalid_02.pdf" },
  { name: "Expired permit", file: "permit_wp_invalid_01.pdf" },
  { name: "Driver's licence", file: "drivers_license.png" },
  { name: "Blue Card, no work clause", file: "blue_card_implied.png" },
];

type Tone = "green" | "red" | "amber" | "slate";

const VERDICT: Record<Decision, { tone: Tone; icon: string; label: string }> = {
  VALID: { tone: "green", icon: "✓", label: "Work permit: YES" },
  EXPIRED: { tone: "red", icon: "✕", label: "Work permit: NO" },
  NOT_WORK_AUTHORIZED: { tone: "red", icon: "✕", label: "Work permit: NO" },
  NOT_A_PERMIT: { tone: "slate", icon: "—", label: "Not a work permit" },
  NEEDS_REVIEW: { tone: "amber", icon: "⏳", label: "Needs human review" },
};

const TONE: Record<Tone, { band: string; text: string; sub: string; chip: Tone }> = {
  green: { band: "bg-green-50", text: "text-green-800", sub: "text-green-700", chip: "green" },
  red: { band: "bg-red-50", text: "text-red-800", sub: "text-red-700", chip: "red" },
  amber: { band: "bg-amber-50", text: "text-amber-900", sub: "text-amber-800", chip: "amber" },
  slate: { band: "bg-slate-50", text: "text-slate-800", sub: "text-slate-600", chip: "slate" },
};

const EMP: Record<string, { label: string; dot: string }> = {
  permitted: { label: "Permitted", dot: "bg-green-500" },
  prohibited: { label: "Prohibited", dot: "bg-red-500" },
  implied: { label: "Implied by statute", dot: "bg-amber-500" },
  restricted: { label: "Restricted", dot: "bg-amber-500" },
  unknown: { label: "Unknown", dot: "bg-slate-400" },
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtDate(de: string | null): string {
  if (!de) return "—";
  const m = de.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  if (!m) return de;
  return `${parseInt(m[1], 10)} ${MONTHS[parseInt(m[2], 10) - 1] ?? m[2]} ${m[3]}`;
}

function subline(c: PermitCheck): string {
  switch (c.decision) {
    case "VALID":
      return `Valid until ${fmtDate(c.valid_until)}${c.days_remaining != null ? ` · ${c.days_remaining} days left` : ""}`;
    case "EXPIRED":
      return `Expired ${fmtDate(c.valid_until)}${c.days_remaining != null ? ` · ${Math.abs(c.days_remaining)} days ago` : ""}`;
    case "NOT_WORK_AUTHORIZED":
      return `Permit current until ${fmtDate(c.valid_until)}, but employment is not authorized`;
    case "NOT_A_PERMIT":
      return c.document_type ? `Document read as “${c.document_type}”` : "Not a residence / work permit";
    case "NEEDS_REVIEW":
      return "Not auto-decided — a human must confirm";
    default:
      return "";
  }
}

function cleanReasons(reasons: string[]): string[] {
  return reasons.filter((r) => !/synthetic|specimen|test/i.test(r));
}

// ---- small presentational pieces ----
function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2">
      <dt className="shrink-0 text-sm text-slate-500">{label}</dt>
      <dd className="text-right text-sm font-medium text-slate-900">{children}</dd>
    </div>
  );
}

function Evidence({ label, value, quote }: { label: string; value: string; quote: string | null }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-slate-600">{label}</span>
        <span className="text-sm font-semibold text-slate-900">{value}</span>
      </div>
      {quote ? (
        <p className="mt-1 rounded-md bg-slate-50 px-2.5 py-1.5 font-mono text-xs leading-relaxed text-slate-500">
          “{quote}”
        </p>
      ) : (
        <p className="mt-1 text-xs italic text-amber-700">not found in the document — could not verify</p>
      )}
    </div>
  );
}

function OutlineButton({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-400 disabled:opacity-50"
    >
      {children}
    </button>
  );
}

function PrimaryButton({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      style={{ backgroundColor: BRAND }}
      className="inline-flex items-center rounded-lg px-3.5 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
    >
      {children}
    </button>
  );
}

// ---- the assessment card (the hero) ----
function Assessment({
  check,
  onReview,
  busy,
}: {
  check: PermitCheck;
  onReview: (id: string, outcome: "confirmed" | "overridden", d?: Decision) => void;
  busy: boolean;
}) {
  const v = VERDICT[check.decision];
  const t = TONE[v.tone];
  const f = check.fields;
  const emp = EMP[check.employment_status ?? "unknown"] ?? EMP.unknown;
  const rubric = [...check.rubric].sort((a, b) => a.earned / a.weight - b.earned / b.weight);
  const reasons = cleanReasons(check.reasons);

  return (
    <Card className="overflow-hidden">
      {/* hero verdict */}
      <div className={`px-6 py-5 ${t.band}`}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5">
              <span className={`grid h-7 w-7 place-items-center rounded-full bg-white/70 text-base font-bold ${t.text}`}>
                {v.icon}
              </span>
              <h2 className={`text-2xl font-bold tracking-tight ${t.text}`}>{v.label}</h2>
            </div>
            <p className={`mt-1.5 text-sm ${t.sub}`}>{subline(check)}</p>
          </div>
          <div className="shrink-0 text-right">
            <div className={`text-3xl font-bold tabular-nums ${t.text}`}>{check.confidence.toFixed(0)}%</div>
            <div className="text-[11px] font-medium uppercase tracking-wider text-slate-400">confidence</div>
          </div>
        </div>
      </div>

      {/* key facts */}
      <div className="border-t border-slate-100 px-6 py-4">
        <dl className="divide-y divide-slate-100">
          {f.holder_name && <Fact label="Holder">{f.holder_name}</Fact>}
          {check.document_type && <Fact label="Type">{check.document_type}</Fact>}
          {check.decision !== "NOT_A_PERMIT" && (
            <Fact label="Employment">
              <span className="inline-flex items-center gap-1.5">
                <span className={`h-1.5 w-1.5 rounded-full ${emp.dot}`} />
                {emp.label}
              </span>
            </Fact>
          )}
          {check.legal_basis && <Fact label="Legal basis">{check.legal_basis}</Fact>}
        </dl>
        {check.legal_basis_citation && (
          <p className="mt-3 border-l-2 pl-3 text-xs leading-relaxed text-slate-500" style={{ borderColor: BRAND }}>
            <span className="font-semibold text-slate-600">⚖ Legal basis · </span>
            {check.legal_basis_citation}
          </p>
        )}
      </div>

      {/* grounded evidence */}
      {check.decision !== "NOT_A_PERMIT" && (
        <div className="border-t border-slate-100 px-6 py-4">
          <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Evidence — read directly from the document
          </h3>
          <div className="space-y-3">
            <Evidence label="Valid until" value={fmtDate(check.valid_until)} quote={f.valid_until_quote} />
            <Evidence
              label="Employment clause"
              value={emp.label}
              quote={f.employment_quote}
            />
          </div>
        </div>
      )}

      {/* confidence — collapsed by default */}
      <details className="group border-t border-slate-100 px-6 py-4">
        <summary className="flex cursor-pointer list-none items-center justify-between text-sm text-slate-600">
          <span>
            Confidence breakdown <span className="font-bold text-slate-900">{check.confidence.toFixed(0)}%</span>
          </span>
          <span className="text-xs text-slate-400 group-open:hidden">what we checked ▸</span>
          <span className="hidden text-xs text-slate-400 group-open:inline">hide ▾</span>
        </summary>
        <ul className="mt-3 space-y-2">
          {rubric.map((it, i) => {
            const full = it.earned >= it.weight - 0.5;
            return (
              <li key={i} className="flex items-start gap-2 text-sm">
                <span className={full ? "text-green-600" : "text-amber-600"}>{full ? "✓" : "–"}</span>
                <span className={`flex-1 ${full ? "text-slate-500" : "text-amber-800"}`}>{it.detail}</span>
                <span className="shrink-0 tabular-nums text-xs text-slate-400">
                  {it.earned.toFixed(0)}/{it.weight.toFixed(0)}
                </span>
              </li>
            );
          })}
        </ul>
      </details>

      {/* human-review action */}
      {check.needs_review && (
        <div className="border-t border-amber-200 bg-amber-50 px-6 py-4">
          <h3 className="text-sm font-semibold text-amber-900">Human decision required</h3>
          {reasons[0] && <p className="mt-1 text-sm text-amber-900/90">{reasons[0]}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <PrimaryButton onClick={() => onReview(check.id, "confirmed")} disabled={busy}>
              Confirm recommendation
            </PrimaryButton>
            <OutlineButton onClick={() => onReview(check.id, "overridden", "VALID")} disabled={busy}>
              Override → valid
            </OutlineButton>
            <OutlineButton onClick={() => onReview(check.id, "overridden", "NOT_WORK_AUTHORIZED")} disabled={busy}>
              Override → reject
            </OutlineButton>
          </div>
        </div>
      )}

      {/* raw data */}
      <details className="border-t border-slate-100 px-6 py-3">
        <summary className="cursor-pointer text-xs text-slate-400">Raw extracted fields (JSON)</summary>
        <pre className="mt-2 overflow-auto rounded bg-slate-50 p-3 text-xs text-slate-600">
          {JSON.stringify(check.fields, null, 2)}
        </pre>
      </details>
    </Card>
  );
}

export default function LeistenschneiderPage() {
  const [tab, setTab] = useState<"validate" | "queue">("validate");
  const [check, setCheck] = useState<PermitCheck | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<PermitHistoryRow[]>([]);
  const [queue, setQueue] = useState<PermitCheck[]>([]);

  async function refresh() {
    try {
      const [h, q] = await Promise.all([getPermitHistory(), getReviewQueue()]);
      setHistory(h);
      setQueue(q);
    } catch {
      /* API may be down; ignore */
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  async function runFile(file: File, label: string) {
    setBusy(label);
    setError(null);
    setCheck(null);
    try {
      setCheck(await postPermit(file));
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function runSample(s: { name: string; file: string }) {
    try {
      const res = await fetch(`/samples/${s.file}`);
      const blob = await res.blob();
      await runFile(new File([blob], s.file, { type: blob.type }), s.file);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function act(id: string, outcome: "confirmed" | "overridden", override_decision?: Decision) {
    setBusy(id);
    try {
      const r = await reviewPermit(id, { outcome, override_decision });
      if (check?.id === id) setCheck(r);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const tabBtn = (key: "validate" | "queue", label: React.ReactNode) => (
    <button
      onClick={() => setTab(key)}
      className={`rounded-md px-3.5 py-1.5 text-sm font-semibold transition ${
        tab === key ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"
      }`}
    >
      {label}
    </button>
  );

  return (
    <main className="mx-auto max-w-3xl px-6 py-10 text-slate-900">
      {/* header */}
      <header className="mb-8 border-l-4 pl-4" style={{ borderColor: BRAND }}>
        <p className="text-xs font-semibold tracking-widest" style={{ color: BRAND }}>
          LEISTENSCHNEIDER · COMPLIANCE
        </p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">🛂 Work-Permit Validator</h1>
        <p className="mt-1.5 text-slate-600">
          Confirms a permit, reads its valid-until date, and grounds every value in the document — with a human in
          the loop for anything uncertain.
        </p>
      </header>

      {/* tabs */}
      <div className="mb-6 inline-flex rounded-lg border border-slate-200 bg-slate-100 p-1">
        {tabBtn("validate", "Validate")}
        {tabBtn(
          "queue",
          <span className="inline-flex items-center gap-1.5">
            Review queue
            {queue.length > 0 && (
              <span className="rounded-full bg-amber-400 px-1.5 text-[11px] font-bold text-amber-950">{queue.length}</span>
            )}
          </span>,
        )}
      </div>

      {error && <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">⚠️ {error}</p>}

      {tab === "validate" && (
        <div className="space-y-6">
          {/* input */}
          <Card className="p-5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="mr-1 text-sm font-medium text-slate-700">Try a sample:</span>
              {SAMPLES.map((s) => (
                <button
                  key={s.file}
                  onClick={() => runSample(s)}
                  disabled={busy !== null}
                  className="rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-700 transition hover:border-slate-400 disabled:opacity-50"
                >
                  {busy === s.file ? "reading…" : s.name}
                </button>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4">
              <span className="text-sm text-slate-600">or upload a permit (PDF / photo):</span>
              <input
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.webp"
                className="text-sm text-slate-600 file:mr-2 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-200"
                disabled={busy !== null}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) runFile(file, file.name);
                }}
              />
            </div>
          </Card>

          {/* result */}
          {busy && !check && (
            <Card className="p-6 text-sm text-slate-500">Reading the document…</Card>
          )}
          {check && <Assessment check={check} onReview={act} busy={busy !== null} />}
          {!check && !busy && (
            <Card className="p-6 text-sm text-slate-500">
              Pick a sample or upload a document to see the verdict.
            </Card>
          )}
        </div>
      )}

      {tab === "queue" && (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            Migration decisions are high-risk, so the system never issues a binding verdict. Below-threshold and
            implied-by-statute checks land here for a human to confirm or override.
          </p>
          {queue.length === 0 ? (
            <Card className="p-6 text-sm text-slate-500">The review queue is empty.</Card>
          ) : (
            queue.map((c) => (
              <Card key={c.id} className="overflow-hidden">
                <div className="flex items-center justify-between gap-3 bg-amber-50 px-5 py-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-slate-900">{c.filename ?? c.id}</div>
                    <div className="text-xs text-slate-500">
                      {c.document_type ?? "—"} · valid until {fmtDate(c.valid_until)}
                    </div>
                  </div>
                  <span className="shrink-0 text-right">
                    <span className="text-lg font-bold tabular-nums text-amber-900">{c.confidence.toFixed(0)}%</span>
                  </span>
                </div>
                <div className="px-5 py-3">
                  {c.legal_basis_citation && (
                    <p className="text-xs leading-relaxed text-slate-500">⚖ {c.legal_basis_citation}</p>
                  )}
                  {cleanReasons(c.reasons)[1] && (
                    <p className="mt-1.5 text-sm text-slate-700">{cleanReasons(c.reasons)[1]}</p>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <PrimaryButton onClick={() => act(c.id, "confirmed")} disabled={busy !== null}>
                      Confirm
                    </PrimaryButton>
                    <OutlineButton onClick={() => act(c.id, "overridden", "VALID")} disabled={busy !== null}>
                      Override → valid
                    </OutlineButton>
                    <OutlineButton onClick={() => act(c.id, "overridden", "NOT_WORK_AUTHORIZED")} disabled={busy !== null}>
                      Override → reject
                    </OutlineButton>
                  </div>
                </div>
              </Card>
            ))
          )}
        </div>
      )}

      {/* recent checks */}
      {history.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Recent checks</h2>
          <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
            {history.slice(0, 8).map((h) => {
              const v = VERDICT[h.decision];
              return (
                <li key={h.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
                  <span className="truncate text-slate-600">{h.filename ?? h.id}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="text-xs text-slate-400">{new Date(h.created_at).toLocaleDateString()}</span>
                    {h.needs_review && h.status === "pending" && <Badge tone="amber">review</Badge>}
                    <Badge tone={v?.tone ?? "slate"}>{h.decision.replace(/_/g, " ").toLowerCase()}</Badge>
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </main>
  );
}
