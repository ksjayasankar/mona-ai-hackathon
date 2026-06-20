import { supabase } from "@/lib/supabase";

// P3 Leistenschneider — typed client for the work-permit validation API.
// Own module by design; do NOT fold into the shared lib/api.ts.

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) return {}; // dev mode (AUTH_MODE=dev) — no token needed
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export type Decision = "VALID" | "EXPIRED" | "NOT_A_PERMIT" | "NOT_WORK_AUTHORIZED" | "NEEDS_REVIEW";

export interface RubricItem {
  label: string;
  weight: number;
  earned: number;
  grounded: boolean | null;
  detail: string;
}

export interface PermitFields {
  is_work_permit: boolean;
  document_type: string | null;
  document_type_quote: string | null;
  holder_name: string | null;
  nationality: string | null;
  legal_basis: string | null;
  issue_date: string | null;
  valid_until: string | null;
  valid_until_quote: string | null;
  employment_allowed: boolean | null;
  employment_quote: string | null;
  extraction_confidence: number;
  notes: string | null;
}

export interface PermitCheck {
  id: string;
  filename: string | null;
  decision: Decision;
  confidence: number;
  valid_until: string | null;
  days_remaining: number | null;
  employment_status: string | null;
  holder_name: string | null;
  document_type: string | null;
  legal_basis: string | null;
  legal_basis_citation: string | null;
  needs_review: boolean;
  status: string; // pending | confirmed | overridden
  fields: PermitFields;
  rubric: RubricItem[];
  reasons: string[];
  created_at: string;
}

export interface PermitHistoryRow {
  id: string;
  filename: string | null;
  decision: Decision;
  confidence: number;
  valid_until: string | null;
  employment_status: string | null;
  holder_name: string | null;
  needs_review: boolean;
  status: string;
  created_at: string;
}

export interface ReviewActionRow {
  id: string;
  reviewer: string;
  outcome: string;
  override_decision: string | null;
  note: string | null;
  created_at: string;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { ...(init?.headers ?? {}), ...(await authHeaders()) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

export async function postPermit(file: File): Promise<PermitCheck> {
  const fd = new FormData();
  fd.append("file", file);
  return req<PermitCheck>("/agents/permits", { method: "POST", body: fd });
}

export async function getPermitHistory(): Promise<PermitHistoryRow[]> {
  return req<PermitHistoryRow[]>("/agents/permits/history");
}

export async function getReviewQueue(): Promise<PermitCheck[]> {
  return req<PermitCheck[]>("/agents/permits/review-queue");
}

export async function getPermit(id: string): Promise<PermitCheck> {
  return req<PermitCheck>(`/agents/permits/${id}`);
}

export async function reviewPermit(
  id: string,
  body: { outcome: "confirmed" | "overridden"; override_decision?: Decision; note?: string },
): Promise<PermitCheck> {
  return req<PermitCheck>(`/agents/permits/${id}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
