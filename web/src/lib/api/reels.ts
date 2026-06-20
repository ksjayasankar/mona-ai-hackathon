// P6 Dr. Theiss — Reel Studio API client (own module; do not fold into api.ts).
import { supabase } from "@/lib/supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) return {}; // dev mode
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface ReelScript {
  product_name: string;
  hook: string;
  scenes: string[];
  cta: string;
  hashtags: string[];
}

export interface StoryboardFrame {
  kicker: string; // HOOK / SCENE n / CTA
  caption: string; // the on-frame text
  sub: string; // secondary line (CTA hashtags, etc.)
  data_url: string; // data:image/png;base64,… (safe-zone guides drawn ON)
}

export interface SafeZone {
  canvas: string; // e.g. "1080x1920"
  top_reserved_px: number;
  bottom_reserved_px: number;
  right_reserved_px: number;
  safe_box: number[]; // [x0, y0, x1, y1]
}

export interface ReelStoryboard {
  product_name: string;
  script: ReelScript;
  captions: string[];
  frames: StoryboardFrame[];
  video: string | null; // data:video/mp4;base64,… when a quick mux succeeded, else null
  safe_zone: SafeZone;
  safe_zone_note: string;
  confidence: number;
  reasons: string[];
  voiceover_text: string;
}

export interface ReelsOptions {
  file?: File | null;
  tryVideo?: boolean;
}

export async function postReels(opts: ReelsOptions = {}): Promise<ReelStoryboard> {
  const fd = new FormData();
  if (opts.file) fd.append("file", opts.file);
  fd.append("try_video", String(opts.tryVideo ?? true));
  const res = await fetch(`${API}/agents/reels`, {
    method: "POST",
    body: fd,
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}
