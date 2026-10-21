// Transacciones (TXN-01..14). GLO-01: montos como strings, nunca float.
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
  account_id: string; // TAR-03
  account_to_id: string | null; // TXN-02: transfer target
  amount_to: string | null; // TXN-13: received in the target currency
  fee_amount: string | null; // TXN-14: fee of this transfer
  fee_for_id: string | null; // TXN-14: set on the fee row itself
  statement_id: string | null; // TXN-09: set when transfer is a TDC payment
  expense_nature_override: string | null;
  recurring_rule_id: string | null;
  needs_review: boolean;
  original_amount?: string | null; // REC-08: precio en otra moneda (informativo)
  original_currency?: string | null;
  event_id: string | null; // EVT-02
  commitment_id: string | null; // CXP-03: abono a un compromiso
  installment_plan_id: string | null; // MSI-03: compra MSI (madre)
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
  account_id?: string; // TXN-10: movements touching the account
  event_id?: string; // EVT-05
  commitment_id?: string; // CXP-03
  needs_review?: boolean;
  q?: string; // TXN-12: búsqueda por descripción
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
  account_id: string;
  account_to_id?: string | null;
  amount_to?: string | null; // TXN-13
  fee_amount?: string | null; // TXN-14
  cycle_hint?: "current" | "next" | null; // TDC-05a
  target_statement_id?: string | null; // TXN-09: explicit statement for TDC payment
  event_id?: string | null; // EVT-02
  commitment_id?: string | null; // CXP-03
}

export interface DuplicateQuery {
  type: string;
  date: string;
  amount: string;
  currency: string;
  description?: string;
  category_id?: string | null;
}

function toQuery(filters: object): string {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function useTransactions(filters: TransactionFilters, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["transactions", filters],
    queryFn: () => api<TransactionListOut>(`/api/v1/transactions${toQuery(filters)}`),
    enabled: options.enabled ?? true,
    placeholderData: (prev) => prev, // evita parpadeo al teclear la búsqueda
  });
}

/** TXN-11: transacciones existentes que parecen la que se va a registrar
 * (ignora el método de pago). Es un aviso; el alta nunca se bloquea. */
export function fetchPossibleDuplicates(query: DuplicateQuery): Promise<TransactionOut[]> {
  return api<TransactionOut[]>(`/api/v1/transactions/duplicates${toQuery(query)}`);
}

function useInvalidateTransactions() {
  const qc = useQueryClient();
  return () =>
    [
      "transactions",
      "accounts",
      "statements",
      "budgets",
      "forecast",
      "events",
      "dashboard",
      "commitments",
    ].forEach(
      (k) => void qc.invalidateQueries({ queryKey: [k] }),
    );
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
