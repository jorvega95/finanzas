// Tarjetas de crédito, statements y pagos (TDC-01..12, REM-04).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface DebtSummary {
  statement_balance: string;
  current_cycle_spend: string;
  committed_msi: string;
  total_debt: string;
}

export type CardBehavior = "credit" | "debit" | "prepaid";

export interface CardOut {
  id: string;
  card_type_id: string;
  alias: string;
  bank: string;
  network: string;
  last4: string;
  currency: string;
  credit_limit: string | null;
  statement_day: number | null;
  statement_day_is_last: boolean;
  cutoff_day_policy: "include" | "next_cycle";
  payment_due_days: number | null;
  payment_day: number | null;
  payment_day_is_last: boolean;
  reminder_days: number[];
  initial_balance: string | null;
  allow_overdraft: boolean;
  color: string | null;
  payment_method_id: string | null;
  is_active: boolean;
  // CardWithDebtOut extras (list/detail endpoints):
  behavior: CardBehavior | null;
  debt: DebtSummary | null;
  balance: string | null; // TAR-05, debit/prepaid only
  next_payment: { amount: string; due_date: string } | null; // TDC-14
  opening_balance: string | null; // TDC-14: synthetic previous-cut debt
}

export interface StatementOut {
  id: string;
  credit_card_id: string;
  period_start: string;
  period_end: string;
  due_date: string;
  computed_total: string;
  applied_credit: string;
  paid_amount: string;
  status: "open" | "closed" | "paid" | "partially_paid";
  is_overdue: boolean;
}

export interface ReminderOut {
  id: string;
  kind: string;
  fire_at: string;
  channel: string;
  message: string;
  status: string;
}

export interface CardBody {
  card_type_id: string;
  alias: string;
  bank: string;
  network: string;
  last4: string;
  // Credit-only (TAR-02):
  statement_day?: number | string | null;
  cutoff_day_policy?: string;
  payment_due_days?: number | null;
  payment_day?: number | string | null;
  credit_limit?: string | null;
  opening_balance?: string | null; // TDC-14
  // Non-credit (TAR-05):
  initial_balance?: string | null;
  allow_overdraft?: boolean;
}

// TDC-15: full edit. Only the fields sent are applied.
export interface CardUpdateBody {
  alias?: string;
  bank?: string;
  network?: string;
  last4?: string;
  currency?: string;
  color?: string | null;
  statement_day?: number | string | null;
  cutoff_day_policy?: string;
  payment_due_days?: number | null;
  payment_day?: number | string | null;
  credit_limit?: string | null;
  reminder_days?: number[];
  opening_balance?: string | null; // TDC-14
  initial_balance?: string | null;
  allow_overdraft?: boolean;
  is_active?: boolean;
}

export function useCards() {
  return useQuery({
    queryKey: ["cards"],
    queryFn: () => api<CardOut[]>("/api/v1/cards"),
  });
}

export function useCardStatements(cardId: string | null) {
  return useQuery({
    queryKey: ["statements", cardId],
    queryFn: () => api<StatementOut[]>(`/api/v1/cards/${cardId}/statements`),
    enabled: cardId !== null,
  });
}

export function useNotifications() {
  return useQuery({
    queryKey: ["notifications"],
    queryFn: () => api<ReminderOut[]>("/api/v1/cards/notifications/inbox"),
  });
}

function useInvalidateCards() {
  const qc = useQueryClient();
  return () =>
    ["cards", "statements", "transactions", "notifications", "msi"].forEach(
      (k) => void qc.invalidateQueries({ queryKey: [k] }),
    );
}

export function useCreateCard() {
  const invalidate = useInvalidateCards();
  return useMutation({
    mutationFn: (body: CardBody) =>
      api<CardOut>("/api/v1/cards", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useUpdateCard() {
  const invalidate = useInvalidateCards();
  return useMutation({
    mutationFn: ({ cardId, ...body }: { cardId: string } & CardUpdateBody) =>
      api<CardOut>(`/api/v1/cards/${cardId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function usePayCard() {
  const invalidate = useInvalidateCards();
  return useMutation({
    mutationFn: ({
      cardId,
      ...body
    }: {
      cardId: string;
      amount: string;
      from_payment_method_id: string;
      date: string;
      statement_id?: string | null;
    }) =>
      api(`/api/v1/cards/${cardId}/payments`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useCloseCycles() {
  const invalidate = useInvalidateCards();
  return useMutation({
    mutationFn: () => api<StatementOut[]>("/api/v1/cards/close-cycles", { method: "POST" }),
    onSuccess: invalidate,
  });
}
