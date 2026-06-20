// P7 Dr. Theiss — targeting analytics API client (own module; do not fold into api.ts).
import { supabase } from "@/lib/supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) return {}; // dev mode — the API runs AUTH_MODE=dev and needs no token
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface SegmentRow {
  segment: string;
  customers: number;
  avg_recency_days: number;
  avg_frequency: number;
  avg_monetary_eur: number;
  top_product: string;
  peak_month: number;
}

export interface TargetingPlan {
  headline: string;
  target_segment: string;
  product: string;
  channel: string;
  optimal_date: string; // YYYY-MM-DD
  optimal_time: string; // e.g. "19:30"
  rationale: string[];
  expected_lift_pct: number;
  confidence: number;
}

export interface LiftResult {
  product: string;
  segment: string;
  pre_mean_weekly: number;
  post_mean_weekly: number;
  lift_pct: number;
  verdict: "LIFT" | "NO_LIFT" | "DROP";
  weeks_pre: number;
  weeks_post: number;
  note: string;
}

export interface WeeklyPoint {
  week: string;
  units: number;
  phase: "pre" | "post";
}

export interface SeasonPoint {
  month: number;
  units: number;
}

export interface AnalyticsReport {
  tenant_id: string;
  note: string;
  n_customers: number;
  n_transactions: number;
  segments: SegmentRow[];
  plan: TargetingPlan;
  lift: LiftResult;
  weekly: WeeklyPoint[];
  season: SeasonPoint[];
  channels: string[];
}

export interface AnalyticsOptions {
  channel?: string;
  useLlm?: boolean;
}

export async function runAnalytics(opts: AnalyticsOptions = {}): Promise<AnalyticsReport> {
  const params = new URLSearchParams();
  if (opts.channel) params.set("channel", opts.channel);
  if (opts.useLlm) params.set("use_llm", "true");
  const qs = params.toString();
  const res = await fetch(`${API}/agents/analytics${qs ? `?${qs}` : ""}`, {
    method: "POST",
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}
