// Bootstrap de sesión: perfil + espacios (ESP-01). Tipos espejo del backend;
// se reemplazan por los generados (npm run generate:api) cuando crezca la API.
import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

export interface SpaceOut {
  id: string;
  name: string;
  type: "personal" | "shared";
  base_currency: string;
  timezone: string;
  role: "owner" | "editor" | "viewer";
}

export interface ProfileOut {
  id: string;
  display_name: string;
  email: string | null;
  default_space_id: string | null;
  locale: string;
}

export interface MeOut {
  profile: ProfileOut;
  spaces: SpaceOut[];
}

export function useMe(enabled: boolean) {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => api<MeOut>("/api/v1/me"),
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}
