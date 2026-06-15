// Dashboard (DSH-01..05) y presupuestos (PRE-01..04).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface Totals {
  income: string;
  expenses: string;
  net: string;
}

export interface CategoryRow {
  category_id: string | null;
  category_name: string;
  total: string;
}

export interface TrendPoint extends Totals {
  month: string;
}

export interface UpcomingItem {
  kind: "card_due" | "msi_quota" | "recurring";
  date: string;
  description: string;
  amount: string;
  ref_id: string;
  is_overdue: boolean;
}

export interface DashboardSummary {
  month: string;
  accrual: Totals;
  cash_flow: Totals;
  by_category: CategoryRow[];
  by_nature: Record<string, string>;
  trend: TrendPoint[];
  upcoming: UpcomingItem[];
}

export function useDashboard(month: string) {
  return useQuery({
    queryKey: ["dashboard", month],
    queryFn: () => api<DashboardSummary>(`/api/v1/dashboard/summary?month=${month}`),
  });
}

export interface BudgetOut {
  id: string;
  category_id: string;
  month: string;
  amount: string;
  alert_threshold: string;
}

export interface BudgetProgress {
  budget: BudgetOut;
  category_name: string;
  consumed: string;
  remaining: string;
}

export function useBudgets(month: string) {
  return useQuery({
    queryKey: ["budgets", month],
    queryFn: () => api<BudgetProgress[]>(`/api/v1/budgets?month=${month}`),
  });
}

function useInvalidateBudgets() {
  const qc = useQueryClient();
  return () =>
    ["budgets", "transactions", "cards"].forEach(
      (k) => void qc.invalidateQueries({ queryKey: [k] }),
    );
}

export function useCreateBudget() {
  const invalidate = useInvalidateBudgets();
  return useMutation({
    mutationFn: (body: { category_id: string; month: string; amount: string }) =>
      api<BudgetOut>("/api/v1/budgets", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useDeleteBudget() {
  const invalidate = useInvalidateBudgets();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/api/v1/budgets/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useCopyBudgets() {
  const invalidate = useInvalidateBudgets();
  return useMutation({
    mutationFn: (body: { from_month: string; to_month: string }) =>
      api<{ copied: number }>("/api/v1/budgets/copy", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}
