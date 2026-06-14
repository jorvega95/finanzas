// Transacciones (TXN-01..06). GLO-01: montos como strings, nunca float.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface TransactionOut {
  id: string;
  type: "expense" | "income" | "transfer";
  date: string;
  amount: string;
  currency: string;
  fx_rate_to_base: string | null;
  description: string;
  notes: string | null;
  category_id: string | null;
  payment_method_id: string | null;
  payment_method_to_id: string | null;
  card_id: string | null;
  expense_nature_override: string | null;
  recurring_rule_id: string | null;
  needs_review: boolean;
}

export interface TransactionListOut {
  items: TransactionOut[];
  total: number;
}

export interface TransactionFilters {
  date_from?: string;
  date_to?: string;
  type?: string;
  category_id?: string;
  needs_review?: boolean;
  limit?: number;
  offset?: number;
}

export interface TransactionBody {
  type: string;
  date: string;
  amount: string;
  currency: string;
  description?: string;
  category_id?: string | null;
  payment_method_id?: string | null;
  payment_method_to_id?: string | null;
}

function toQuery(filters: TransactionFilters): string {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function useTransactions(filters: TransactionFilters) {
  return useQuery({
    queryKey: ["transactions", filters],
    queryFn: () => api<TransactionListOut>(`/api/v1/transactions${toQuery(filters)}`),
  });
}

function useInvalidateTransactions() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: ["transactions"] });
}

export function useCreateTransaction() {
  const invalidate = useInvalidateTransactions();
  return useMutation({
    mutationFn: (body: TransactionBody) =>
      api<TransactionOut>("/api/v1/transactions", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useDeleteTransaction() {
  const invalidate = useInvalidateTransactions();
  return useMutation({
    mutationFn: (id: string) =>
      api<void>(`/api/v1/transactions/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useUpdateTransaction() {
  const invalidate = useInvalidateTransactions();
  return useMutation({
    mutationFn: ({ id, ...body }: TransactionBody & { id: string }) =>
      api<TransactionOut>(`/api/v1/transactions/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useConfirmTransaction() {
  const invalidate = useInvalidateTransactions();
  return useMutation({
    mutationFn: ({ id, amount }: { id: string; amount?: string }) =>
      api<TransactionOut>(`/api/v1/transactions/${id}/confirm`, {
        method: "POST",
        body: JSON.stringify(amount ? { amount } : {}),
      }),
    onSuccess: invalidate,
  });
}
