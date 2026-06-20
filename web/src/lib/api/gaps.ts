// P9 Dr. Theiss — Competitive Gap Agent API client (own module; do NOT fold into api.ts).
import { supabase } from "@/lib/supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) return {}; // dev mode (AUTH_MODE=dev) — no token needed
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ---- Allgäuer's own product set --------------------------------------------
export interface OwnProduct {
  name: string;
  line: string;
  need: string;
  format: string;
  price_eur: number | null;
}

export interface ProductSet {
  brand: string;
  products: OwnProduct[];
  needs_covered: string[];
  formats_covered: string[];
}

// ---- competitor landscape --------------------------------------------------
export interface Competitor {
  name: string;
  owner: string | null;
  overlaps_in: string;
  positioning: string;
}

export interface CompetitorLandscape {
  competitors: Competitor[];
}

// ---- the gap analysis (the deliverable) ------------------------------------
export interface GapRow {
  need: string;
  format: string;
  covered_by_competitors: string;
  allgaeuer_present: boolean;
  rationale: string;
  product_idea: string;
  priority: number; // 0-100 = category size × margin × brand-fit
}

export interface BenchmarkCell {
  need: string;
  format: string;
  allgaeuer: boolean;
  competitors: boolean;
}

export interface GapAnalysis {
  headline: string;
  confidence: number;
  benchmark: BenchmarkCell[];
  strengths: string[];
  white_space: GapRow[];
}

export interface GapResult {
  tenant_id?: string;
  product_set: ProductSet;
  landscape: CompetitorLandscape;
  analysis: GapAnalysis;
}

/**
 * Run the competitive-gap analysis. With no `file`, the API runs on the bundled
 * Dr. Theiss data pack so the page is demoable with one click.
 */
export async function postGaps(file?: File | null): Promise<GapResult> {
  const fd = new FormData();
  if (file) fd.append("file", file);
  const res = await fetch(`${API}/agents/gaps`, {
    method: "POST",
    body: fd,
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}
