// Pronóstico de flujo a futuro (PRO-01..06).
import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

export interface ForecastEvent {
  date: string;
  kind: "income" | "recurring_income" | "card_due" | "recurring_expense" | "manual_expense";
  direction: "in" | "out";
  description: string;
  amount: string; // base, magnitud positiva
  currency: string;
  is_estimate: boolean;
  covered: boolean;
  shortfall: string;
  balance_after: string;
}

export interface ForecastAlert {
  date: string;
  description: string;
  shortfall: string;
}

export interface ForecastSummary {
  horizon_months: number;
  generated_for: string;
  starting_cash: string;
  cash_adjustment: string;
  ending_balance: string;
  min_balance: string;
  min_balance_date: string | null;
  first_overdraft_date: string | null;
  total_shortfall: string;
  events: ForecastEvent[];
  alerts: ForecastAlert[];
}

export function useForecast(horizonMonths: number, cashAdjustment: string) {
  // GLO-01: el ajuste viaja como string decimal; nunca aritmética float aquí.
  const adjustment = cashAdjustment.trim() === "" ? "0" : cashAdjustment;
  return useQuery({
    queryKey: ["forecast", horizonMonths, adjustment],
    queryFn: () =>
      api<ForecastSummary>(
        `/api/v1/dashboard/forecast?horizon_months=${horizonMonths}` +
          `&cash_adjustment=${encodeURIComponent(adjustment)}`,
      ),
  });
}
