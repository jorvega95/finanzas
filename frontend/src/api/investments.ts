// Inversiones y patrimonio neto (INV-01..06, PAT-01).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface AccountOut {
  id: string;
  name: string;
  kind: "crypto" | "stocks" | "fixed_income" | "other";
  is_active: boolean;
}

export interface HoldingValuation {
  holding_id: string;
  account_id: string;
  account_name: string;
  kind: string;
  asset_symbol: string;
  asset_name: string;
  quantity: string;
  avg_cost: string;
  currency: string;
  price: string | null;
  price_fetched_at: string | null;
  price_source: string | null;
  value_base: string | null;
  unrealized_pnl: string | null;
  realized_pnl: string;
}

export interface PortfolioOut {
  total_value: string;
  total_unrealized_pnl: string;
  total_realized_pnl: string;
  holdings: HoldingValuation[];
}

export interface SnapshotOut {
  date: string;
  total_value: string;
}

export interface NetWorthOut {
  date: string;
  assets: string;
  liabilities: string;
  net_worth: string;
}

export function useInvestmentAccounts() {
  return useQuery({
    queryKey: ["investments", "accounts"],
    queryFn: () => api<AccountOut[]>("/api/v1/investments/accounts"),
  });
}

export function usePortfolio() {
  return useQuery({
    queryKey: ["investments", "portfolio"],
    queryFn: () => api<PortfolioOut>("/api/v1/investments/portfolio"),
  });
}

export function usePortfolioSnapshots() {
  return useQuery({
    queryKey: ["investments", "snapshots"],
    queryFn: () => api<SnapshotOut[]>("/api/v1/investments/snapshots"),
  });
}

export function useNetWorth() {
  return useQuery({
    queryKey: ["investments", "net-worth"],
    queryFn: () => api<NetWorthOut[]>("/api/v1/investments/net-worth"),
  });
}

function useInvalidateInvestments() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: ["investments"] });
}

export function useCreateInvestmentAccount() {
  const invalidate = useInvalidateInvestments();
  return useMutation({
    mutationFn: (body: { name: string; kind: string }) =>
      api<AccountOut>("/api/v1/investments/accounts", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useRegisterMovement() {
  const invalidate = useInvalidateInvestments();
  return useMutation({
    mutationFn: ({
      accountId,
      ...body
    }: {
      accountId: string;
      type: string;
      asset_symbol: string;
      asset_name?: string;
      quantity: string;
      price?: string | null;
      currency?: string;
      date: string;
    }) =>
      api<PortfolioOut>(`/api/v1/investments/accounts/${accountId}/movements`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useSetManualPrice() {
  const invalidate = useInvalidateInvestments();
  return useMutation({
    mutationFn: (body: { symbol: string; price: string; currency: string }) =>
      api("/api/v1/investments/prices", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useTakeSnapshots() {
  const invalidate = useInvalidateInvestments();
  return useMutation({
    mutationFn: async () => {
      await api("/api/v1/investments/snapshot", { method: "POST" });
      await api("/api/v1/investments/net-worth/snapshot", { method: "POST" });
    },
    onSuccess: invalidate,
  });
}
