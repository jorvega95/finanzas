// Reglas recurrentes (REC-01..05).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface RecurringRuleOut {
  id: string;
  type: "expense" | "income";
  amount: string;
  amount_is_estimate: boolean;
  currency: string;
  description: string;
  category_id: string | null;
  payment_method_id: string | null;
  frequency: "weekly" | "biweekly" | "monthly" | "yearly";
  start_date: string;
  end_date: string | null;
  max_occurrences: number | null;
  month_day: number | null;
  use_last_day: boolean;
  is_active: boolean;
}

export interface RecurringRuleBody {
  type: string;
  amount: string;
  currency: string;
  description: string;
  category_id?: string | null;
  payment_method_id?: string | null;
  frequency: string;
  start_date: string;
  month_day?: number | null;
  use_last_day?: boolean;
  amount_is_estimate?: boolean;
}

export interface RecurringRuleUpdate {
  id: string;
  amount?: string;
  description?: string;
  category_id?: string | null;
  payment_method_id?: string | null;
  end_date?: string | null;
  max_occurrences?: number | null;
  is_active?: boolean;
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

function useInvalidateRecurring() {
  const qc = useQueryClient();
  // El pronóstico proyecta nómina/domiciliados desde las reglas (PRO-03/04).
  return () =>
    ["recurring-rules", "forecast"].forEach(
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
