// Dashboard (DSH-01..06) y presupuestos (PRE-01..04). EVT-04: `excludeEvents`
// saca los movimientos ligados a eventos de los agregados.
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
  kind: "card_due" | "msi_quota" | "recurring" | "commitment"; // CXP-08
  date: string;
  description: string;
  amount: string;
  ref_id: string;
  is_overdue: boolean;
}

export interface DashboardSummary {
  month: string;
  totals: Totals;
  by_category: CategoryRow[];
  by_nature: Record<string, string>;
  trend: TrendPoint[];
  upcoming: UpcomingItem[];
}

export function useDashboard(month: string, excludeEvents = false) {
  return useQuery({
    queryKey: ["dashboard", month, { excludeEvents }],
    queryFn: () =>
      api<DashboardSummary>(
        `/api/v1/dashboard/summary?month=${month}${excludeEvents ? "&exclude_events=true" : ""}`,
      ),
  });
}

// DSH-06: drill-down de una naturaleza del pie.
export interface NatureDetailItem {
  kind: "transaction" | "msi_quota";
  id: string;
  date: string;
  description: string;
  category_id: string | null;
  category_name: string;
  account_name: string | null;
  amount: string;
  original_amount: string | null;
  currency: string;
  installment_number: number | null;
  installment_total: number | null;
}

export interface NatureDetail {
  nature: string;
  month: string;
  total: string;
  by_category: CategoryRow[];
  items: NatureDetailItem[];
}

export function useNatureDetail(month: string, nature: string | null, excludeEvents = false) {
  return useQuery({
    queryKey: ["dashboard", "by-nature", month, nature, { excludeEvents }],
    enabled: nature !== null,
    queryFn: () =>
      api<NatureDetail>(
        `/api/v1/dashboard/by-nature/${nature}?month=${month}${excludeEvents ? "&exclude_events=true" : ""}`,
      ),
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

export function useBudgets(month: string, excludeEvents = false) {
  return useQuery({
    queryKey: ["budgets", month, { excludeEvents }],
    queryFn: () =>
      api<BudgetProgress[]>(
        `/api/v1/budgets?month=${month}${excludeEvents ? "&exclude_events=true" : ""}`,
      ),
  });
}

function useInvalidateBudgets() {
  const qc = useQueryClient();
  return () =>
    ["budgets", "transactions", "accounts"].forEach(
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
