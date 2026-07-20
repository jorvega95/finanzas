// Centro de notificaciones in-app (REM-04..REM-07).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface NotificationOut {
  id: string;
  kind: "card_due" | "budget_alert" | "custom";
  ref_id: string;
  fire_at: string;
  channel: "in_app" | "email";
  message: string;
  status: "pending" | "sent" | "canceled" | "failed" | "dismissed";
  sent_at: string | null;
  /** REM-07: nulo = no leído. */
  read_at: string | null;
  created_at: string;
}

// Cada 60 s: los recordatorios los dispara un job diario, no hay prisa.
const POLL_MS = 60_000;

/** REM-06: inbox del espacio activo (solo avisos disparados y no descartados). */
export function useNotifications() {
  return useQuery({
    queryKey: ["notifications", "inbox"],
    queryFn: () => api<NotificationOut[]>("/api/v1/notifications"),
    refetchInterval: POLL_MS,
  });
}

/** REM-07: badge de la campana. */
export function useUnreadCount() {
  return useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: () => api<{ unread: number }>("/api/v1/notifications/unread-count"),
    refetchInterval: POLL_MS,
  });
}

function useInvalidateNotifications() {
  const qc = useQueryClient();
  // El prefijo invalida inbox y badge a la vez.
  return () => void qc.invalidateQueries({ queryKey: ["notifications"] });
}

/** REM-07: marcar leído no altera el status ni oculta el aviso. */
export function useMarkRead() {
  const invalidate = useInvalidateNotifications();
  return useMutation({
    mutationFn: (id: string) =>
      api<NotificationOut>(`/api/v1/notifications/${id}/read`, { method: "POST" }),
    onSuccess: invalidate,
  });
}

/** REM-07: idempotente. */
export function useMarkAllRead() {
  const invalidate = useInvalidateNotifications();
  return useMutation({
    mutationFn: () => api<{ marked: number }>("/api/v1/notifications/read-all", { method: "POST" }),
    onSuccess: invalidate,
  });
}

/** REM-05: descartar (soft-delete) — desaparece del inbox. */
export function useDismissNotification() {
  const invalidate = useInvalidateNotifications();
  return useMutation({
    mutationFn: (id: string) => api(`/api/v1/notifications/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}
