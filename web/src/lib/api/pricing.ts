// P8 Dr. Theiss — dynamic pricing API client (own module; do not fold into api.ts).
import { supabase } from "@/lib/supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) return {}; // dev mode
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface SignalReading {
  source: string;
  label: string;
  affected_categories: string[];
  direction: string; // up | down | flat
  magnitude: number;
  health_event: boolean;
  evidence: string;
  fetched_at: string;
  source_url?: string | null;
  configured: boolean;
}

export interface PricingCard {
  rec_id: string;
  product: string;
  category: string;
  base_price: number;
  proposed_delta_pct: number;
  final_delta_pct: number;
  final_price: number;
  guardrail_status: "applied" | "clamped" | "rejected" | "blocked";
  status: "pending" | "approved" | "rejected";
  reasons: string[];
  signals: SignalReading[];
  rationale: string;
}

export interface PricingReport {
  run_id: string;
  source_note: string;
  summary: string;
  product_count: number;
  blocked_count: number;
  llm_calls: number;
  signals: SignalReading[];
  products: PricingCard[];
}

export interface PricingHistoryRow {
  id: string;
  created_at: string;
  source_note: string;
  product_count: number;
  blocked_count: number;
  summary: string;
}

export interface PricingOptions {
  place?: string;
  country?: string;
  bandPct?: number;
  marginFloorPct?: number;
}

export async function postPricing(file: File, opts: PricingOptions = {}): Promise<PricingReport> {
  const fd = new FormData();
  fd.append("file", file);
  if (opts.place) fd.append("place", opts.place);
  if (opts.country) fd.append("country", opts.country);
  if (opts.bandPct != null) fd.append("band_pct", String(opts.bandPct));
  if (opts.marginFloorPct != null) fd.append("margin_floor_pct", String(opts.marginFloorPct));
  const res = await fetch(`${API}/agents/pricing`, {
    method: "POST",
    body: fd,
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

export async function getPricingHistory(): Promise<PricingHistoryRow[]> {
  const res = await fetch(`${API}/agents/pricing/history`, { headers: { ...(await authHeaders()) } });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

async function setRecStatus(recId: string, action: "approve" | "reject"): Promise<{ status: string }> {
  const res = await fetch(`${API}/agents/pricing/${recId}/${action}`, {
    method: "POST",
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

export const approveRec = (recId: string) => setRecStatus(recId, "approve");
export const rejectRec = (recId: string) => setRecStatus(recId, "reject");
