// Compromisos con proveedores (CXP-01..08): total pactado, abonos (gastos con
// `commitment_id`, CXP-03) y calendario de pagos. GLO-01: montos como strings.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { TransactionOut } from "./transactions";

export interface ScheduleRow {
  id: string;
  due_date: string;
  amount: string;
  covered: string;
  uncovered: string;
  is_covered: boolean;
  is_overdue: boolean;
}

export interface CommitmentOut {
  id: string;
  name: string;
  total_amount: string;
  currency: string;
  event_id: string | null;
  category_id: string | null;
  paid_before_tracking: string;
  due_date: string | null;
  notes: string | null;
  is_canceled: boolean;
  // Calculados (CXP-03/05):
  paid: string;
  pending: string;
  status: "pending" | "paid" | "canceled";
  is_overdue: boolean;
  abonos: number;
  schedule: ScheduleRow[];
  unscheduled_pending: string;
}

export interface CommitmentBody {
  name?: string;
  total_amount?: string;
  currency?: string;
  event_id?: string | null;
  category_id?: string | null;
  paid_before_tracking?: string;
  due_date?: string | null;
  notes?: string | null;
  is_canceled?: boolean;
  schedule?: { due_date: string; amount: string }[];
}

export interface ThirdPartyBody {
  amount: string;
  date: string;
  account_id: string;
  description?: string;
  category_id?: string | null;
}

export function useCommitments(includeClosed = false) {
  return useQuery({
    queryKey: ["commitments", { includeClosed }],
    queryFn: () =>
      api<CommitmentOut[]>(`/api/v1/commitments${includeClosed ? "?include_closed=true" : ""}`),
  });
}

function useInvalidateCommitments() {
  const qc = useQueryClient();
  return () =>
    [
      "commitments",
      "transactions",
      "accounts",
      "events",
      "dashboard",
      "budgets",
      "forecast",
      "notifications",
    ].forEach((k) => void qc.invalidateQueries({ queryKey: [k] }));
}

export function useCreateCommitment() {
  const invalidate = useInvalidateCommitments();
  return useMutation({
    mutationFn: (body: CommitmentBody) =>
      api<CommitmentOut>("/api/v1/commitments", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useUpdateCommitment() {
  const invalidate = useInvalidateCommitments();
  return useMutation({
    mutationFn: ({ id, ...body }: CommitmentBody & { id: string }) =>
      api<CommitmentOut>(`/api/v1/commitments/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useDeleteCommitment() {
  const invalidate = useInvalidateCommitments();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/api/v1/commitments/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

// CXP-04: alguien le pagó directo al proveedor como regalo.
export function usePayByThirdParty() {
  const invalidate = useInvalidateCommitments();
  return useMutation({
    mutationFn: ({ id, ...body }: ThirdPartyBody & { id: string }) =>
      api<{ income: TransactionOut; expense: TransactionOut; commitment: CommitmentOut }>(
        `/api/v1/commitments/${id}/third-party`,
        { method: "POST", body: JSON.stringify(body) },
      ),
    onSuccess: invalidate,
  });
}
