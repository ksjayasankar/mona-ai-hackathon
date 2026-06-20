import { supabase } from "./supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) return {}; // dev mode
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface IntakeReport {
  injection_detected: boolean;
  guard_reports: { source: string; risk: string; hits: string[] }[];
  attacker_tried: string[];
  we_did: string[];
  attachments: { name: string; doc_type: string }[];
  checklist: { key: string; label: string; present: boolean; found_in: string | null }[];
  all_present: boolean;
  present_labels: string[];
  missing_labels: string[];
  summary: string;
  agent_steps: number;
  llm_calls: number;
}

export interface IntakeHistoryRow {
  id: string;
  created_at: string;
  injection_detected: boolean;
  all_present: boolean;
  present_labels: string[];
  missing_labels: string[];
}

export async function postSecureIntake(emailBody: string, files: File[]): Promise<IntakeReport> {
  const fd = new FormData();
  fd.append("email_body", emailBody);
  files.forEach((f) => fd.append("files", f));
  const res = await fetch(`${API}/agents/secure-intake`, {
    method: "POST",
    body: fd,
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

export async function getHistory(): Promise<IntakeHistoryRow[]> {
  const res = await fetch(`${API}/agents/secure-intake/history`, { headers: { ...(await authHeaders()) } });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}
