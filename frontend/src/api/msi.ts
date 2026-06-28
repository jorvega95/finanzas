// Planes MSI (MSI-01..10).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface InstallmentOut {
  id: string;
  number: number;
  amount: string;
  estimated_charge_date: string;
  statement_id: string | null;
  status: "pending" | "charged" | "paid" | "canceled";
}

export interface PlanOut {
  id: string;
  credit_card_id: string;
  transaction_id: string;
  total_amount: string;
  months: number;
  monthly_amount: string;
  start_date: string;
  status: "active" | "completed" | "settled_early";
}

export interface PlanSummaryOut {
  plan: PlanOut;
  description: string;
  card_alias: string;
  paid_count: number;
  charged_count: number;
  pending_count: number;
  remaining_amount: string;
  projected_payoff: string;
  projected_payment_date: string;
  installments: InstallmentOut[];
}

export interface CurrentInstallmentCreate {
  description: string;
  monthly_amount: string;
  currency: string;
  credit_card_id: string;
  current_number: number;
  total_months: number;
  category_id: string;
  current_is_charged: boolean;
}

export interface ProjectionRow {
  credit_card_id: string;
  card_alias: string;
  month: string;
  amount: string;
}

export function useMsiPlans() {
  return useQuery({
    queryKey: ["msi", "plans"],
    queryFn: () => api<PlanSummaryOut[]>("/api/v1/installment-plans"),
  });
}

export function useMsiProjection() {
  return useQuery({
    queryKey: ["msi", "projection"],
    queryFn: () => api<ProjectionRow[]>("/api/v1/installment-plans/projection"),
  });
}

function useInvalidateMsi() {
  const qc = useQueryClient();
  return () =>
    ["msi", "cards", "statements", "transactions", "forecast"].forEach(
      (k) => void qc.invalidateQueries({ queryKey: [k] }),
    );
}

export function useCreateMsiPlan() {
  const invalidate = useInvalidateMsi();
  return useMutation({
    mutationFn: (body: { transaction_id: string; months: number }) =>
      api<PlanOut>("/api/v1/installment-plans", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useSettleMsiPlan() {
  const invalidate = useInvalidateMsi();
  return useMutation({
    mutationFn: (planId: string) =>
      api<PlanOut>(`/api/v1/installment-plans/${planId}/settle`, { method: "POST" }),
    onSuccess: invalidate,
  });
}

export function useCreateMsiBackfill() {
  const invalidate = useInvalidateMsi();
  return useMutation({
    mutationFn: (body: CurrentInstallmentCreate) =>
      api<PlanOut>("/api/v1/installment-plans/backfill", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}
