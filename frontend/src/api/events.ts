// Eventos (EVT-01..05): agrupan los movimientos de algo extraordinario (boda,
// mudanza, viaje) sin cambiar sus categorías. GLO-01: montos como strings.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { CategoryRow } from "./dashboard";

export interface EventOut {
  id: string;
  name: string;
  date: string | null; // YYYY-MM-DD
  budget: string | null; // en la moneda base
  notes: string | null;
  is_active: boolean;
}

export interface EventLoan {
  account_id: string;
  name: string;
  currency: string;
  balance: string; // TAR-11: negativo = debes
}

// EVT-03: totales del evento en moneda base (tasa congelada).
export interface EventSummary {
  event: EventOut;
  spent: string;
  received: string;
  net: string;
  budget_remaining: string | null;
  pending_commitments: string; // CXP-03: lo que aún se debe a sus proveedores
  movements: number;
  by_category: CategoryRow[];
  loans: EventLoan[];
}

export interface EventBody {
  name?: string;
  date?: string | null;
  budget?: string | null;
  notes?: string | null;
  is_active?: boolean;
}

export function useEvents(includeInactive = false) {
  return useQuery({
    queryKey: ["events", { includeInactive }],
    queryFn: () =>
      api<EventSummary[]>(`/api/v1/events${includeInactive ? "?include_inactive=true" : ""}`),
  });
}

function useInvalidateEvents() {
  const qc = useQueryClient();
  return () =>
    ["events", "transactions", "dashboard", "budgets"].forEach(
      (k) => void qc.invalidateQueries({ queryKey: [k] }),
    );
}

export function useCreateEvent() {
  const invalidate = useInvalidateEvents();
  return useMutation({
    mutationFn: (body: EventBody) =>
      api<EventOut>("/api/v1/events", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useUpdateEvent() {
  const invalidate = useInvalidateEvents();
  return useMutation({
    mutationFn: ({ id, ...body }: EventBody & { id: string }) =>
      api<EventOut>(`/api/v1/events/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useDeleteEvent() {
  const invalidate = useInvalidateEvents();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/api/v1/events/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

// EVT-02: ligar/desligar un movimiento sin editarlo completo (sirve también
// para una compra MSI, cuya edición completa bloquea MSI-08).
export function useSetTransactionEvent() {
  const invalidate = useInvalidateEvents();
  return useMutation({
    mutationFn: ({ id, event_id }: { id: string; event_id: string | null }) =>
      api(`/api/v1/transactions/${id}/event`, {
        method: "PATCH",
        body: JSON.stringify({ event_id }),
      }),
    onSuccess: invalidate,
  });
}
