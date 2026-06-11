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

export function useRecurringRules(includeInactive = false) {
  return useQuery({
    queryKey: ["recurring-rules", includeInactive],
    queryFn: () =>
      api<RecurringRuleOut[]>(
        `/api/v1/recurring-rules?include_inactive=${includeInactive}`,
      ),
  });
}

export function useCreateRecurringRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: RecurringRuleBody) =>
      api<RecurringRuleOut>("/api/v1/recurring-rules", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["recurring-rules"] }),
  });
}

export function useUpdateRecurringRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; is_active?: boolean; amount?: string }) =>
      api<RecurringRuleOut>(`/api/v1/recurring-rules/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["recurring-rules"] }),
  });
}
