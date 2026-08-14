// Cliente HTTP hacia FastAPI. Adjunta el JWT de Supabase en Authorization.
// Tipos generados con `npm run generate:api` (src/api/schema.d.ts).
import { supabase } from "../auth/supabase";
import { translateValidationErrors } from "../lib/apiErrors";
import { getActiveSpaceId } from "./activeSpace";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const session = supabase ? (await supabase.auth.getSession()).data.session : null;
  const token = session?.access_token;
  const spaceId = getActiveSpaceId();
  // Sin VITE_API_URL se usa el proxy de Vite (/api -> :8000).
  const base = (import.meta.env.VITE_API_URL as string | undefined) ?? "";
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(spaceId ? { "X-Space-Id": spaceId } : {}),
      ...init.headers,
    },
  });
  if (!res.ok) {
    let detail = `Error ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else {
        // 422 de Pydantic: lista de errores en inglés (GLO-06).
        detail = translateValidationErrors(body.detail) ?? detail;
      }
    } catch {
      // sin cuerpo JSON
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
