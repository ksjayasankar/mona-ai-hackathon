import { supabase } from "@/lib/supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const API_BASE = API;

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) return {}; // dev mode (AUTH_MODE=dev needs no token)
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface Eligible {
  employee_id: string;
  name: string;
  role: string;
  department: string;
  phone: string;
  contract: string;
  scheduled_hours: number;
  max_hours: number;
  overtime_ok: boolean;
  rest_hours: number | null;
  headroom_hours: number;
  persona: string | null;
  score: number;
  why: string[];
}

export interface Excluded {
  employee_id: string;
  name: string;
  role: string;
  department: string;
  rule: string;
  reason: string;
}

export interface Outreach {
  id: string;
  staff_id: string;
  staff_name: string | null;
  employee_id: string | null;
  seq: number;
  status: string;
  channel: string;
  message: string | null;
  sent_at: string | null;
  responded_at: string | null;
}

export interface GapState {
  gap: {
    id: string;
    role: string;
    department: string;
    shift: string;
    day_label: string;
    required_certs: string[];
    person_out: string | null;
    status: string;
    version: number;
    shift_start: string | null;
    shift_end: string | null;
    filled_at: string | null;
  };
  filled_by: { id: string; name: string; employee_id: string } | null;
  eligible: Eligible[];
  excluded: Excluded[];
  counts: { total: number; active: number; eligible: number };
  outreach: Outreach[];
}

async function jsonOrThrow(res: Response) {
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

export async function seed() {
  return jsonOrThrow(await fetch(`${API}/agents/shift/seed`, { method: "POST", headers: await authHeaders() }));
}

export async function createGap(body: { message?: string; structured?: object }): Promise<GapState> {
  return jsonOrThrow(
    await fetch(`${API}/agents/shift/gaps`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify(body),
    }),
  );
}

export async function startOutreach(id: string) {
  return jsonOrThrow(await fetch(`${API}/agents/shift/gaps/${id}/outreach`, { method: "POST", headers: await authHeaders() }));
}

export async function escalate(id: string) {
  return jsonOrThrow(await fetch(`${API}/agents/shift/gaps/${id}/escalate`, { method: "POST", headers: await authHeaders() }));
}

export async function acceptToken(token: string) {
  return jsonOrThrow(
    await fetch(`${API}/agents/shift/accept`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    }),
  );
}

export async function gapState(id: string): Promise<GapState> {
  return jsonOrThrow(await fetch(`${API}/agents/shift/gaps/${id}`, { headers: await authHeaders() }));
}
