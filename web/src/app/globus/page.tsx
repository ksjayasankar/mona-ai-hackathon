"use client";

import { useEffect, useState } from "react";
import {
  approveInvoice,
  getInvoiceHistory,
  postInvoices,
  type InvoiceHistoryRow,
  type InvoiceRow,
  type TriageReport,
} from "@/lib/api/invoices";

// Globus green (core.config CUSTOMERS["globus"].color)
const GREEN = "#0a7d3f";

// A messy email carrying THREE invoices (different vendors/formats) + a re-sent duplicate.
// One click → the agent splits, extracts, routes, and catches the dup. No file needed.
const SAMPLE_EMAIL =
  "Hi team — March supplier invoices attached (one file, a few invoices in it). " +
  "The Theiss one is a phone photo, sorry about the quality. Thanks!";

const SAMPLE_3IN1 = `=== INVOICE 1 ===
RECHNUNG
Müller GmbH
Rechnungsnummer: MG-2026-0417
Rechnungsdatum: 04.03.2026
Leistung: Spedition / Fracht (freight)
Nettobetrag: 1.041,93 €
MwSt 19%: 198,07 €
Gesamtbetrag: 1.240,00 €

=== INVOICE 2 ===
INVOICE
Adobe Ireland Ltd
Invoice number: ADB-77120
Date: 2026-03-05
Item: Creative Cloud subscription (software)
VAT 19%
Total due: €496.10

=== INVOICE 3 (re-sent, amended total) ===
RECHNUNG
Müller GmbH
Rechnungsnummer: MG-2026-0417
Rechnungsdatum: 04.03.2026
Leistung: Spedition / Fracht (freight)
Gesamtbetrag: 1.420,00 €
`;

function fileFromText(name: string, text: string): File {
  return new File([text], name, { type: "text/plain" });
}

// ---- status → color language (DESIGN.md confidence-color contract) -------
function statusMeta(status: string): { label: string; border: string; chip: string } {
  switch (status) {
    case "pending":
      return { label: "✓ ready to approve", border: "#16a34a", chip: "bg-green-100 text-green-800" };
    case "approved":
      return { label: "✓ approved", border: GREEN, chip: "bg-green-100 text-green-800" };
    case "needs_review":
      return { label: "⚠ needs review", border: "#d97706", chip: "bg-amber-100 text-amber-800" };
    case "duplicate":
      return { label: "⧉ duplicate / amended", border: "#dc2626", chip: "bg-red-100 text-red-800" };
    case "rejected":
      return { label: "✕ rejected", border: "#dc2626", chip: "bg-red-100 text-red-800" };
    default:
      return { label: status, border: "#94a3b8", chip: "bg-slate-100 text-slate-700" };
  }
}

function confClass(c: number): string {
  if (c >= 85) return "bg-green-100 text-green-800";
  if (c >= 70) return "bg-amber-100 text-amber-800";
  return "bg-red-100 text-red-800";
}

const FIELD_ORDER: [keyof InvoiceRow, string][] = [
  ["vendor", "Vendor"],
  ["invoice_number", "Invoice #"],
  ["date", "Date"],
  ["due_date", "Due"],
  ["po_number", "PO"],
  ["total", "Total"],
  ["net_amount", "Net"],
  ["vat_amount", "VAT amount"],
  ["vat_rate", "VAT rate"],
];

function FieldRow({ inv, key_, label }: { inv: InvoiceRow; key_: string; label: string }) {
  const value = inv[key_ as keyof InvoiceRow] as string | null;
  if (!value) return null;
  const ev = inv.evidence?.[key_];
  const conf = inv.field_confidence?.[key_];
  const isNum = ["total", "net_amount", "vat_amount", "invoice_number", "vat_rate"].includes(key_);
  return (
    <div className="grid grid-cols-[88px_1fr_auto] items-start gap-3 border-t border-slate-100 py-1.5 first:border-t-0">
      <div className="pt-0.5 text-xs text-slate-500">{label}</div>
      <div>
        <div className={`text-sm font-semibold ${isNum ? "font-mono tabular-nums" : ""}`}>{value}</div>
        {ev && (
          <span className="mt-0.5 inline-block rounded bg-[#ecfdf3] px-1.5 py-0.5 font-mono text-[11px] text-slate-500">
            “{ev}”
          </span>
        )}
      </div>
      {typeof conf === "number" && conf > 0 ? (
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${confClass(conf)}`}>
          {Math.round(conf)}%
        </span>
      ) : (
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-400">
          ungrounded
        </span>
      )}
    </div>
  );
}

function InvoiceCard({ inv, idx, onApprove, busy }: {
  inv: InvoiceRow; idx: number; onApprove: (id: string) => void; busy: boolean;
}) {
  const m = statusMeta(inv.status);
  const fellThrough = inv.department === "Finance Review";
  return (
    <article
      className="mb-3.5 overflow-hidden rounded-lg border border-l-4 border-slate-200 bg-white"
      style={{ borderLeftColor: m.border }}
    >
      <div className="flex items-start justify-between gap-2 px-4 pb-2 pt-3.5">
        <div>
          <span className="mr-2 font-bold text-slate-400">{["①", "②", "③", "④", "⑤", "⑥"][idx] ?? `#${idx + 1}`}</span>
          <span className="text-[15px] font-semibold">{inv.vendor || "Unknown vendor"}</span>
          <div className="mt-0.5 text-xs text-slate-500">
            {[inv.invoice_number, inv.source, inv.source_span].filter(Boolean).join(" · ") || "—"}
          </div>
        </div>
        <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${m.chip}`}>{m.label}</span>
      </div>

      <div className="px-4 pb-3.5">
        {inv.flags?.map((f, i) => (
          <div
            key={i}
            className={`mb-2 rounded px-2.5 py-2 text-[12.5px] leading-snug ${
              inv.status === "duplicate"
                ? "border border-red-200 bg-red-50 text-red-800"
                : "border border-amber-200 bg-amber-50 text-amber-800"
            }`}
          >
            {f}
          </div>
        ))}

        {FIELD_ORDER.map(([k, label]) => (
          <FieldRow key={k as string} inv={inv} key_={k as string} label={label} />
        ))}

        {/* routing */}
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <span
            className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold"
            style={fellThrough
              ? { borderColor: "#fde68a", background: "#fffbeb", color: "#92400e" }
              : { borderColor: "#d2e9dc", background: "#e9f4ee", color: GREEN }}
          >
            → {inv.department || "unrouted"}
          </span>
          {inv.category && <span className="text-xs text-slate-400">category: {inv.category}</span>}
          {inv.dept_reason && <span className="text-xs italic text-slate-500">{inv.dept_reason}</span>}
        </div>
      </div>

      <div className="flex items-center gap-2 border-t border-slate-100 bg-slate-50 px-4 py-2.5">
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer select-none">raw</summary>
          <pre className="mt-2 max-h-56 overflow-auto rounded bg-slate-900 p-2 text-[11px] text-slate-100">
            {JSON.stringify(inv, null, 2)}
          </pre>
        </details>
        <div className="flex-1" />
        {inv.status === "pending" && (
          <button
            onClick={() => onApprove(inv.id)}
            disabled={busy}
            className="rounded-lg px-3.5 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
            style={{ background: GREEN }}
          >
            Approve & route →
          </button>
        )}
        {inv.status === "needs_review" && (
          <button
            onClick={() => onApprove(inv.id)}
            disabled={busy}
            className="rounded-lg border border-amber-300 bg-amber-50 px-3.5 py-1.5 text-xs font-semibold text-amber-800 disabled:opacity-50"
          >
            Confirm & approve
          </button>
        )}
        {inv.status === "duplicate" && (
          <span className="text-xs font-medium text-red-700">held for a human</span>
        )}
        {inv.status === "approved" && (
          <span className="text-xs font-semibold" style={{ color: GREEN }}>✓ sent to {inv.department}</span>
        )}
      </div>
    </article>
  );
}

export default function GlobusInvoicePage() {
  const [email, setEmail] = useState(SAMPLE_EMAIL);
  const [files, setFiles] = useState<File[]>([]);
  const [report, setReport] = useState<TriageReport | null>(null);
  const [history, setHistory] = useState<InvoiceHistoryRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshHistory() {
    try {
      setHistory(await getInvoiceHistory());
    } catch {
      /* API may be down; ignore */
    }
  }
  useEffect(() => {
    let active = true;
    getInvoiceHistory()
      .then((h) => active && setHistory(h))
      .catch(() => {/* API may be down; ignore */});
    return () => {
      active = false;
    };
  }, []);

  async function run(withFiles: File[]) {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const r = await postInvoices(email, withFiles);
      setReport(r);
      refreshHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function approve(id: string) {
    setBusy(true);
    try {
      await approveInvoice(id, "approved");
      setReport((prev) =>
        prev
          ? { ...prev, invoices: prev.invoices.map((iv) => (iv.id === id ? { ...iv, status: "approved" } : iv)) }
          : prev,
      );
      refreshHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const c = report?.counts;

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 text-slate-900">
      {/* branded header */}
      <div className="mb-8 border-l-4 pl-4" style={{ borderColor: GREEN }}>
        <p className="text-xs font-semibold tracking-widest text-slate-500">
          PROBLEM 1 · GLOBUS GROUP · ST. WENDEL · FINANCE / AP
        </p>
        <h1 className="text-3xl font-bold">🧾 Invoice Triage Agent</h1>
        <p className="mt-1 text-slate-600">
          Reads any invoice (PDF / photo / Word, DE/EN, even messy scans), extracts the key fields,
          and routes each to the right department — and <strong>keeps a human in control</strong>:
          every number is grounded to the printed text and nothing is approved automatically.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-[0.82fr_1.18fr]">
        {/* intake */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-lg font-semibold">Inbox submission</h2>
          <label className="mb-1 block text-sm font-medium">Email body</label>
          <textarea
            className="mb-4 h-24 w-full rounded-lg border border-slate-300 p-2 text-sm"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <label className="mb-1 block text-sm font-medium">Attachments (PDF / photo / Word)</label>
          <input
            type="file"
            multiple
            className="mb-2 block w-full text-sm"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          />
          {files.length > 0 && (
            <p className="mb-3 font-mono text-[11px] text-slate-500">{files.map((f) => f.name).join(" · ")}</p>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              onClick={() => run(files)}
              disabled={busy || files.length === 0}
              className="rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
              style={{ background: GREEN }}
            >
              {busy ? "Triaging…" : "Run triage"}
            </button>
            <button
              onClick={() => run([fileFromText("march_invoices.txt", SAMPLE_3IN1)])}
              disabled={busy}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-50"
            >
              Try a 3-in-1 sample
            </button>
          </div>
          {error && <p className="mt-3 text-sm text-red-700">⚠️ {error}</p>}
          <p className="mt-4 text-[11px] text-slate-400">
            Simulated inbox — a pluggable IMAP / Gmail connector is defined but not wired, so it&apos;s
            demoable with no credentials.
          </p>
        </div>

        {/* results */}
        <div>
          {!report && !busy && (
            <div className="rounded-xl border border-dashed border-slate-200 p-8 text-center text-slate-400">
              Drop an email with invoices, or hit <strong>Try a 3-in-1 sample</strong> — the agent splits
              every invoice out, extracts each with evidence + confidence, routes it, and flags duplicates.
            </div>
          )}
          {busy && <div className="rounded-xl border border-slate-200 p-8 text-center text-slate-500">Reading invoices…</div>}

          {report && (
            <>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-lg font-semibold">Detected invoices</h2>
                <span className="text-sm text-slate-500">
                  <b className="text-slate-900">{c?.found ?? 0}</b> found · {c?.pending ?? 0} ready ·{" "}
                  {c?.needs_review ?? 0} review · {c?.duplicate ?? 0} duplicate
                </span>
              </div>
              {report.invoices.map((inv, i) => (
                <InvoiceCard key={inv.id} inv={inv} idx={i} onApprove={approve} busy={busy} />
              ))}
              {report.invoices.length === 0 && (
                <p className="rounded-xl border border-slate-200 p-5 text-sm text-slate-500">
                  No invoices found in that submission.
                </p>
              )}
            </>
          )}

          {/* history */}
          <div className="mt-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-2 text-lg font-semibold">Recent triage</h2>
            {history.length === 0 ? (
              <p className="text-sm text-slate-500">No invoices processed yet.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {history.slice(0, 8).map((h) => {
                  const m = statusMeta(h.status);
                  return (
                    <li key={h.id} className="flex items-center justify-between">
                      <span className="truncate">
                        <span className="font-mono text-[11px] text-slate-400">
                          {new Date(h.created_at).toLocaleString()}
                        </span>{" "}
                        {h.vendor || "—"}{" "}
                        {h.total && <span className="font-mono tabular-nums text-slate-600">{h.total}</span>}
                      </span>
                      <span className="flex shrink-0 gap-1.5">
                        {h.department && (
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                            {h.department}
                          </span>
                        )}
                        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${m.chip}`}>
                          {h.status}
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
