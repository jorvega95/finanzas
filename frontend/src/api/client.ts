// Cliente HTTP hacia FastAPI. Adjunta el JWT de Supabase en Authorization.
// Tipos generados con `npm run generate:api` (src/api/schema.d.ts).
import { supabase } from "../auth/supabase";

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const session = supabase ? (await supabase.auth.getSession()).data.session : null;
  const token = session?.access_token;
  // Sin VITE_API_URL se usa el proxy de Vite (/api -> :8000).
  const base = (import.meta.env.VITE_API_URL as string | undefined) ?? "";
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}
