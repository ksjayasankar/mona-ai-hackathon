"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card } from "@/components/ui";
import {
  getPermitHistory,
  getReviewQueue,
  postPermit,
  reviewPermit,
  type Decision,
  type PermitCheck,
  type PermitHistoryRow,
  type RubricItem,
} from "@/lib/api/permits";

// ---- Leistenschneider branding (core.config CUSTOMERS["leistenschneider"]) ----
const BRAND = "#1f4e8c";

const SAMPLES: { name: string; file: string; hint: string }[] = [
  { name: "Skilled worker (§ 18a)", file: "permit_wp_valid_01.pdf", hint: "valid · employment permitted" },
  { name: "EU Blue Card (§ 18b)", file: "permit_wp_valid_02.pdf", hint: "different Aufenthaltstitel" },
  { name: "Student permit (§ 16b)", file: "permit_wp_invalid_02.pdf", hint: "employment prohibited" },
  { name: "Expired permit", file: "permit_wp_invalid_01.pdf", hint: "valid-until in the past" },
  { name: "Driver's licence", file: "drivers_license.png", hint: "not a permit" },
  { name: "Blue Card, no work clause", file: "blue_card_implied.png", hint: "authorization implied → review" },
];

const DECISION: Record<Decision, { verdict: string; tone: "green" | "red" | "amber"; icon: string }> = {
  VALID: { verdict: "Work permit: YES", tone: "green", icon: "✅" },
  EXPIRED: { verdict: "Work permit: NO — expired", tone: "red", icon: "⛔" },
  NOT_A_PERMIT: { verdict: "Not a work/residence permit", tone: "red", icon: "🚫" },
  NOT_WORK_AUTHORIZED: { verdict: "Work permit: NO — employment not authorized", tone: "red", icon: "🛑" },
  NEEDS_REVIEW: { verdict: "Needs human review", tone: "amber", icon: "⚠️" },
};

const CARD_TONE: Record<string, string> = {
  green: "border-green-300 bg-green-50",
  red: "border-red-300 bg-red-50",
  amber: "border-amber-300 bg-amber-50",
};

function Quote({ label, value, quote }: { label: string; value: string | null; quote: string | null }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-0.5 text-base font-semibold text-slate-900">{value ?? "—"}</div>
      {quote ? (
        <div className="mt-1.5 rounded bg-slate-50 px-2 py-1 font-mono text-xs text-slate-600">
          📄 read from document: “{quote}”
        </div>
      ) : (
        <div className="mt-1.5 text-xs italic text-slate-400">not printed on the document</div>
      )}
    </div>
  );
}

function Rubric({ items, confidence }: { items: RubricItem[]; confidence: number }) {
  return (
    <Card className="p-5">
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Confidence rubric</h2>
        <span className="text-2xl font-bold" style={{ color: BRAND }}>{confidence.toFixed(0)}%</span>
      </div>
      <p className="mb-3 text-xs text-slate-500">
        Every point is itemized — and every deduction is shown. No hidden score.
      </p>
      <ul className="space-y-2">
        {items.map((it, i) => {
          const full = it.earned >= it.weight;
          return (
            <li key={i} className="text-sm">
              <div className="flex items-center justify-between">
                <span className="text-slate-700">{it.label}</span>
                <span className={full ? "font-semibold text-green-700" : "font-semibold text-amber-700"}>
                  {it.earned.toFixed(0)}/{it.weight.toFixed(0)}
                </span>
              </div>
              <div className="mt-1 h-1.5 w-full rounded-full bg-slate-100">
                <div
                  className={`h-1.5 rounded-full ${full ? "bg-green-500" : "bg-amber-500"}`}
                  style={{ width: `${Math.max(4, (it.earned / it.weight) * 100)}%` }}
                />
              </div>
              <div className={`mt-0.5 text-xs ${full ? "text-slate-500" : "text-amber-700"}`}>{it.detail}</div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function Verdict({ check }: { check: PermitCheck }) {
  const d = DECISION[check.decision];
  return (
    <Card className={`p-5 ${CARD_TONE[d.tone]}`}>
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">{d.icon} {d.verdict}</h2>
        <Badge tone={d.tone}>{check.confidence.toFixed(0)}% confidence</Badge>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div>
          <div className="text-xs text-slate-500">Valid until</div>
          <div className="font-semibold">{check.valid_until ?? "—"}</div>
          {check.days_remaining != null && (
            <div className="text-xs text-slate-500">
              {check.days_remaining >= 0 ? `${check.days_remaining} days left` : `${-check.days_remaining} days ago`}
            </div>
          )}
        </div>
        <div>
          <div className="text-xs text-slate-500">Employment</div>
          <div className="font-semibold capitalize">{check.employment_status ?? "—"}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Holder</div>
          <div className="font-semibold">{check.holder_name ?? "—"}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Type</div>
          <div className="font-semibold">{check.document_type ?? "—"}</div>
        </div>
      </div>
      {check.legal_basis_citation && (
        <div className="mt-3 rounded-lg border border-slate-200 bg-white/70 p-3 text-sm">
          <span className="font-semibold">⚖️ Legal basis: </span>
          {check.legal_basis_citation}
        </div>
      )}
      <div className="mt-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Why</div>
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-slate-700">
          {check.reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      </div>
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
      const r = await postPermit(file);
      setCheck(r);
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
      setCheck(r);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 text-slate-900">
      {/* branded header */}
      <div className="mb-8 border-l-4 pl-4" style={{ borderColor: BRAND }}>
        <p className="text-xs font-semibold tracking-widest" style={{ color: BRAND }}>
          PROBLEM 3 · LEISTENSCHNEIDER PERSONALDIENSTLEISTUNGEN · COMPLIANCE
        </p>
        <h1 className="text-3xl font-bold">🛂 Work-Permit Validator</h1>
        <p className="mt-1 text-slate-600">
          Confirms a document really is a work/residence permit, gives a confidence %, reads the date
          it&apos;s valid until — and grounds every value in the printed text, citing the §AufenthG basis.
          Legal stakes mean nothing is auto-decided below the bar: it routes to a human.
        </p>
      </div>

      {/* tabs */}
      <div className="mb-6 flex gap-2">
        <button
          onClick={() => setTab("validate")}
          className={`rounded-lg px-4 py-2 text-sm font-semibold ${tab === "validate" ? "text-white" : "bg-slate-100 text-slate-700"}`}
          style={tab === "validate" ? { backgroundColor: BRAND } : undefined}
        >
          Validate a permit
        </button>
        <button
          onClick={() => setTab("queue")}
          className={`rounded-lg px-4 py-2 text-sm font-semibold ${tab === "queue" ? "text-white" : "bg-slate-100 text-slate-700"}`}
          style={tab === "queue" ? { backgroundColor: BRAND } : undefined}
        >
          Human-review queue {queue.length > 0 && <span className="ml-1 rounded-full bg-amber-400 px-1.5 text-xs text-amber-950">{queue.length}</span>}
        </button>
      </div>

      {error && <p className="mb-4 text-sm text-red-700">⚠️ {error}</p>}

      {tab === "validate" && (
        <div className="grid gap-6 md:grid-cols-2">
          {/* input */}
          <div className="space-y-4">
            <Card className="p-5">
              <h2 className="mb-3 text-lg font-semibold">Try a sample</h2>
              <div className="grid grid-cols-1 gap-2">
                {SAMPLES.map((s) => (
                  <button
                    key={s.file}
                    onClick={() => runSample(s)}
                    disabled={busy !== null}
                    className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-left text-sm transition hover:border-slate-400 disabled:opacity-50"
                  >
                    <span className="font-medium">{s.name}</span>
                    <span className="text-xs text-slate-500">{busy === s.file ? "reading…" : s.hint}</span>
                  </button>
                ))}
              </div>
            </Card>
            <Card className="p-5">
              <h2 className="mb-2 text-lg font-semibold">…or upload your own</h2>
              <p className="mb-2 text-xs text-slate-500">Any work/residence permit — PDF or photo. Read natively, no OCR.</p>
              <input
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.webp"
                className="block w-full text-sm"
                disabled={busy !== null}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) runFile(f, f.name);
                }}
              />
            </Card>
          </div>

          {/* result */}
          <div className="space-y-4">
            {busy && !check && <Card className="p-5 text-sm text-slate-500">Reading the document…</Card>}
            {check && (
              <>
                <Verdict check={check} />
                <Card className="p-5">
                  <h2 className="mb-3 text-lg font-semibold">Grounded evidence</h2>
                  <div className="space-y-2">
                    <Quote label="Document type" value={check.fields.document_type} quote={check.fields.document_type_quote} />
                    <Quote label="Valid until" value={check.fields.valid_until} quote={check.fields.valid_until_quote} />
                    <Quote
                      label="Employment clause"
                      value={
                        check.fields.employment_allowed === true ? "permitted"
                          : check.fields.employment_allowed === false ? "prohibited" : "not stated"
                      }
                      quote={check.fields.employment_quote}
                    />
                  </div>
                </Card>
                <Rubric items={check.rubric} confidence={check.confidence} />
                {check.needs_review && (
                  <Card className="border-amber-300 bg-amber-50 p-5">
                    <h2 className="text-base font-semibold">⚠️ Routed to a human</h2>
                    <p className="mt-1 text-sm text-slate-700">
                      This was not auto-decided. Confirm or override it in the human-review queue.
                    </p>
                    <div className="mt-3 flex gap-2">
                      <Button onClick={() => act(check.id, "confirmed")} disabled={busy !== null}>Confirm recommendation</Button>
                      <Button onClick={() => act(check.id, "overridden", "VALID")} disabled={busy !== null}>Override → VALID</Button>
                    </div>
                  </Card>
                )}
                <details className="rounded-xl border border-slate-200 bg-white p-4">
                  <summary className="cursor-pointer text-sm font-medium text-slate-600">Raw extracted fields (JSON)</summary>
                  <pre className="mt-2 overflow-auto rounded bg-slate-50 p-3 text-xs">{JSON.stringify(check.fields, null, 2)}</pre>
                </details>
              </>
            )}
            {!check && !busy && (
              <Card className="p-5 text-sm text-slate-500">Pick a sample or upload a document to see the verdict.</Card>
            )}
          </div>
        </div>
      )}

      {tab === "queue" && (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            EU-AI-Act oversight: migration-adjacent decisions are high-risk, so the system never issues a
            binding verdict. Below-threshold and implied-by-statute checks land here. A reviewer can always override.
          </p>
          {queue.length === 0 ? (
            <Card className="p-5 text-sm text-slate-500">The review queue is empty.</Card>
          ) : (
            queue.map((c) => (
              <Card key={c.id} className="border-amber-200 p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-semibold">{c.filename ?? c.id}</div>
                    <div className="text-xs text-slate-500">
                      {c.document_type ?? "—"} · valid until {c.valid_until ?? "—"} · {c.confidence.toFixed(0)}% confidence
                    </div>
                  </div>
                  <Badge tone="amber">{c.decision}</Badge>
                </div>
                {c.legal_basis_citation && (
                  <p className="mt-2 text-sm text-slate-700">⚖️ {c.legal_basis_citation}</p>
                )}
                <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-slate-600">
                  {c.reasons.slice(0, 3).map((r, i) => <li key={i}>{r}</li>)}
                </ul>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button onClick={() => act(c.id, "confirmed")} disabled={busy !== null}>Confirm</Button>
                  <Button onClick={() => act(c.id, "overridden", "VALID")} disabled={busy !== null}>Override → VALID</Button>
                  <Button onClick={() => act(c.id, "overridden", "NOT_WORK_AUTHORIZED")} disabled={busy !== null}>Override → NOT AUTHORIZED</Button>
                </div>
              </Card>
            ))
          )}
        </div>
      )}

      {/* history */}
      <Card className="mt-6 p-5">
        <h2 className="mb-2 text-lg font-semibold">Recent checks</h2>
        {history.length === 0 ? (
          <p className="text-sm text-slate-500">No checks yet.</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {history.map((h) => (
              <li key={h.id} className="flex items-center justify-between">
                <span className="truncate">{new Date(h.created_at).toLocaleString()} · {h.filename ?? h.id}</span>
                <span className="flex shrink-0 gap-1.5">
                  {h.needs_review && h.status === "pending" && <Badge tone="amber">review</Badge>}
                  <Badge tone={h.decision === "VALID" ? "green" : h.decision === "NEEDS_REVIEW" ? "amber" : "red"}>
                    {h.decision}
                  </Badge>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </main>
  );
}
