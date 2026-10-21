// Reglas recurrentes y suscripciones (REC-01..14).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { TransactionOut } from "./transactions";

export type RecurringKind = "generic" | "subscription" | "bill"; // REC-07
export type RecurringFrequency =
  | "weekly"
  | "biweekly"
  | "semimonthly"
  | "monthly"
  | "bimonthly" // REC-06b
  | "yearly";
export type RuleStatus = "active" | "trial" | "paused" | "canceled"; // REC-09

export interface RecurringRuleOut {
  id: string;
  kind: RecurringKind;
  type: "expense" | "income";
  /** REC-11: nulo en un servicio variable sin estimado. */
  amount: string | null;
  amount_is_estimate: boolean;
  /** REC-08: moneda del precio (puede diferir de la cuenta en gastos). */
  currency: string;
  description: string;
  category_id: string | null;
  account_id: string;
  frequency: RecurringFrequency;
  start_date: string;
  end_date: string | null;
  max_occurrences: number | null;
  month_day: number | null;
  use_last_day: boolean;
  is_active: boolean;
  is_trial: boolean; // REC-10
  canceled_at: string | null;
  reminder_days: number[]; // REC-12
  cancel_url: string | null;
  notes: string | null;
  status: RuleStatus;
  next_date: string | null;
  account_currency: string | null;
  /** REC-08: precio en la moneda de la cuenta con la tasa de hoy. */
  account_amount_today: string | null;
}

export interface RecurringRuleBody {
  kind?: RecurringKind;
  type: string;
  amount: string | null;
  currency: string;
  description: string;
  category_id?: string | null;
  account_id?: string;
  frequency: string;
  start_date: string;
  month_day?: number | null;
  use_last_day?: boolean;
  amount_is_estimate?: boolean;
  is_trial?: boolean;
  reminder_days?: number[];
  cancel_url?: string | null;
  notes?: string | null;
}

export interface RecurringRuleUpdate {
  id: string;
  amount?: string | null;
  currency?: string;
  description?: string;
  category_id?: string | null;
  account_id?: string;
  end_date?: string | null;
  max_occurrences?: number | null;
  use_last_day?: boolean;
  is_active?: boolean;
  reminder_days?: number[];
  cancel_url?: string | null;
  notes?: string | null;
}

export interface PendingBillOut {
  rule_id: string;
  description: string;
  scheduled_date: string;
  estimate: string | null;
  currency: string;
  account_id: string;
  category_id: string | null;
}

export interface SubscriptionSummaryOut {
  monthly_total: string;
  yearly_total: string;
  currency: string;
  is_approximate: boolean;
  missing_rate: boolean;
  active_count: number;
  trial_count: number;
  paused_count: number;
  canceled_count: number;
}

export function useRecurringRules(includeInactive = false) {
  return useQuery({
    queryKey: ["recurring-rules", includeInactive],
    queryFn: () =>
      api<RecurringRuleOut[]>(
        `/api/v1/recurring-rules?include_inactive=${includeInactive}`,
      ),
  });
}

/** REC-11: bandeja "Por capturar". */
export function usePendingBills() {
  return useQuery({
    queryKey: ["recurring-rules", "pending-bills"],
    queryFn: () => api<PendingBillOut[]>("/api/v1/recurring-rules/pending-bills"),
  });
}

/** REC-13: costo mensual de las suscripciones. */
export function useSubscriptionSummary() {
  return useQuery({
    queryKey: ["recurring-rules", "summary"],
    queryFn: () => api<SubscriptionSummaryOut>("/api/v1/recurring-rules/summary"),
  });
}

function useInvalidateRecurring() {
  const qc = useQueryClient();
  // El pronóstico proyecta nómina/domiciliados desde las reglas (PRO-03/04);
  // los avisos (REC-12) y los recibos capturados (REC-11) cambian con ellas.
  return () =>
    ["recurring-rules", "forecast", "notifications", "transactions", "dashboard"].forEach(
      (k) => void qc.invalidateQueries({ queryKey: [k] }),
    );
}

export function useCreateRecurringRule() {
  const invalidate = useInvalidateRecurring();
  return useMutation({
    mutationFn: (body: RecurringRuleBody) =>
      api<RecurringRuleOut>("/api/v1/recurring-rules", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useUpdateRecurringRule() {
  const invalidate = useInvalidateRecurring();
  return useMutation({
    mutationFn: ({ id, ...body }: RecurringRuleUpdate) =>
      api<RecurringRuleOut>(`/api/v1/recurring-rules/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useDeleteRecurringRule() {
  const invalidate = useInvalidateRecurring();
  return useMutation({
    mutationFn: (id: string) =>
      api<void>(`/api/v1/recurring-rules/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

/** REC-09: cancelar (`cancel`) o deshacer la cancelación/pausa (`reactivate`). */
export function useSetRuleCanceled() {
  const invalidate = useInvalidateRecurring();
  return useMutation({
    mutationFn: ({ id, canceled }: { id: string; canceled: boolean }) =>
      api<RecurringRuleOut>(
        `/api/v1/recurring-rules/${id}/${canceled ? "cancel" : "reactivate"}`,
        { method: "POST" },
      ),
    onSuccess: invalidate,
  });
}

export function useCaptureBill() {
  const invalidate = useInvalidateRecurring();
  return useMutation({
    mutationFn: ({
      ruleId,
      ...body
    }: {
      ruleId: string;
      scheduled_date: string;
      amount: string;
      date?: string;
    }) =>
      api<TransactionOut>(`/api/v1/recurring-rules/${ruleId}/capture`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useSkipBill() {
  const invalidate = useInvalidateRecurring();
  return useMutation({
    mutationFn: ({ ruleId, scheduled_date }: { ruleId: string; scheduled_date: string }) =>
      api<void>(`/api/v1/recurring-rules/${ruleId}/skip`, {
        method: "POST",
        body: JSON.stringify({ scheduled_date }),
      }),
    onSuccess: invalidate,
  });
}
