// P1 Globus — invoice-triage API client. Own module; does NOT touch the shared api.ts.
import { supabase } from "../supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) return {}; // dev mode — API runs AUTH_MODE=dev, no token needed
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export type InvoiceStatus = "pending" | "needs_review" | "duplicate" | "approved" | "rejected";

export interface LineItem {
  description?: string | null;
  quantity?: string | null;
  amount?: string | null;
}

export interface InvoiceRow {
  id: string;
  source: string | null;
  source_span: string | null;
  vendor: string | null;
  invoice_number: string | null;
  date: string | null;
  due_date: string | null;
  po_number: string | null;
  currency: string | null;
  total: string | null;
  net_amount: string | null;
  vat_amount: string | null;
  vat_rate: string | null;
  category: string | null;
  department: string | null;
  dept_reason: string | null;
  status: InvoiceStatus;
  confidence: number;
  duplicate_of: string | null;
  evidence: Record<string, string>;
  field_confidence: Record<string, number>;
  line_items: LineItem[];
  flags: string[];
}

export interface TriageCounts {
  found: number;
  pending: number;
  needs_review: number;
  duplicate: number;
}

export interface TriageReport {
  invoices: InvoiceRow[];
  counts: TriageCounts;
  summary: string;
}

export interface InvoiceHistoryRow {
  id: string;
  created_at: string;
  vendor: string | null;
  invoice_number: string | null;
  total: string | null;
  currency: string | null;
  department: string | null;
  status: InvoiceStatus;
  source: string | null;
  duplicate_of: string | null;
}

export async function postInvoices(emailBody: string, files: File[]): Promise<TriageReport> {
  const fd = new FormData();
  fd.append("email_body", emailBody);
  files.forEach((f) => fd.append("files", f));
  const res = await fetch(`${API}/agents/invoices`, {
    method: "POST",
    body: fd,
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

export async function getInvoiceHistory(): Promise<InvoiceHistoryRow[]> {
  const res = await fetch(`${API}/agents/invoices/history`, { headers: { ...(await authHeaders()) } });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

export async function approveInvoice(
  invoiceId: string,
  outcome: "approved" | "rejected" = "approved",
  note?: string,
): Promise<{ id: string; status: InvoiceStatus; outcome: string }> {
  const fd = new FormData();
  fd.append("invoice_id", invoiceId);
  fd.append("outcome", outcome);
  if (note) fd.append("note", note);
  const res = await fetch(`${API}/agents/invoices/approve`, {
    method: "POST",
    body: fd,
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}
