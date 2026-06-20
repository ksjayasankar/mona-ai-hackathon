import { supabase } from "@/lib/supabase";

// P5 Kohlpharma — typed client for the Interview Copilot API.
// Own module by design; do NOT fold into the shared lib/api.ts.

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) return {}; // dev mode (AUTH_MODE=dev) — no token needed
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface RoleFound {
  title: string;
  summary: string | null;
  seniority: string | null;
}

export interface InterviewQuestion {
  competency: string;
  question: string;
  strong_answer: string;
  red_flag: string;
}

export interface CompetencyGroup {
  competency: string;
  questions: InterviewQuestion[];
}

export interface InterviewKit {
  source_note: string;
  roles_found: RoleFound[];
  role_title: string;
  role_overview: string;
  confidence: number;
  question_count: number;
  competencies: CompetencyGroup[];
  red_flag_checklist: string[];
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { ...(init?.headers ?? {}), ...(await authHeaders()) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

// Build a kit from an uploaded job offer (or pass null to run on the bundled sample).
export async function postInterview(file: File | null): Promise<InterviewKit> {
  const fd = new FormData();
  if (file) fd.append("file", file);
  return req<InterviewKit>("/agents/interview", { method: "POST", body: fd });
}
