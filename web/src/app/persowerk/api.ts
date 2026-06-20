const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface Signal {
  name: string;
  severity: "low" | "medium" | "high";
  category: string;
  evidence: string;
  why: string;
  weak: boolean;
  detail?: { heatmap_png_b64?: string; strong_ratio?: number } | null;
}

export interface FraudReport {
  candidate_name: string | null;
  risk: "LOW" | "MEDIUM" | "HIGH";
  score: number;
  summary: string;
  signals: Signal[];
  by_category: Record<string, Signal[]>;
  cert_summaries: {
    filename: string;
    decision: string;
    issuer: string | null;
    title: string | null;
    holder_name: string | null;
    valid_until: string | null;
    days_remaining: number | null;
    is_current: boolean;
  }[];
  extraction: Record<string, unknown>;
  verify_ran: boolean;
  methodology_note: string;
  llm_calls: number;
  agent_steps: number;
}

export interface HistoryRow {
  id: string;
  created_at: string;
  risk: string;
  score: number;
  candidate_name: string | null;
  flags: string[];
}

export async function postAssess(
  cv: File | null,
  certs: File[],
  githubHandle: string,
  links: string,
  runVerify: boolean,
): Promise<FraudReport> {
  const fd = new FormData();
  if (cv) fd.append("cv", cv);
  certs.forEach((c) => fd.append("certs", c));
  fd.append("github_handle", githubHandle);
  fd.append("links", links);
  fd.append("run_verify", String(runVerify));
  const res = await fetch(`${API}/agents/fraud/assess`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

export async function getHistory(): Promise<HistoryRow[]> {
  const res = await fetch(`${API}/agents/fraud/history`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}
