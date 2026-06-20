import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

// null when Supabase isn't configured -> dev mode (the API runs AUTH_MODE=dev and needs no token)
export const supabase: SupabaseClient | null = url && anon ? createClient(url, anon) : null;

export const authMode = process.env.NEXT_PUBLIC_AUTH_MODE || "dev";
