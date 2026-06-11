// Contexto del espacio activo (GLO-05). Carga /me y fija X-Space-Id antes
// de renderizar el resto de la app.
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { setActiveSpaceId } from "../../api/activeSpace";
import { useMe, type MeOut, type SpaceOut } from "../../api/me";
import { useAuth } from "../../auth/AuthProvider";

interface SpaceContextValue {
  me: MeOut;
  activeSpace: SpaceOut;
  setActiveSpace: (id: string) => void;
}

const SpaceContext = createContext<SpaceContextValue | null>(null);

export function SpaceProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const me = useMe(Boolean(session));
  const queryClient = useQueryClient();
  const [spaceId, setSpaceId] = useState<string | null>(null);

  function switchSpace(id: string) {
    setSpaceId(id);
    setActiveSpaceId(id);
    // GLO-05: al cambiar de espacio, todo el caché es de otro tenant.
    void queryClient.invalidateQueries();
  }

  const resolved =
    me.data &&
    (me.data.spaces.find((s) => s.id === (spaceId ?? me.data!.profile.default_space_id)) ??
      me.data.spaces[0]);

  useEffect(() => {
    setActiveSpaceId(resolved?.id ?? null);
  }, [resolved?.id]);

  if (me.isLoading || !me.data || !resolved) {
    return (
      <main className="grid min-h-screen place-items-center text-sm text-ink-muted">
        {me.isError ? "No se pudo cargar tu perfil. ¿El backend está corriendo?" : "Cargando…"}
      </main>
    );
  }

  return (
    <SpaceContext.Provider
      value={{ me: me.data, activeSpace: resolved, setActiveSpace: switchSpace }}
    >
      {children}
    </SpaceContext.Provider>
  );
}

export function useSpace(): SpaceContextValue {
  const ctx = useContext(SpaceContext);
  if (!ctx) throw new Error("useSpace debe usarse dentro de <SpaceProvider>");
  return ctx;
}
