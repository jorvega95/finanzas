// Cuentas (TAR-01..11): tarjetas, efectivo, billeteras, ahorro, préstamos; statements y
// pagos de crédito (TDC-01..16, REM-04).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface DebtSummary {
  statement_balance: string;
  current_cycle_spend: string;
  committed_msi: string;
  total_debt: string;
}

// CAT-08: clasificador de sistema del tipo de cuenta.
export type AccountBehavior = "credit" | "debit" | "prepaid" | "cash" | "savings" | "loan";

// TAR-01: todo lo que no es crédito lleva saldo (TAR-05).
export function hasBalance(behavior: AccountBehavior | null | undefined): boolean {
  return behavior != null && behavior !== "credit";
}

// TAR-11: un préstamo lleva saldo, pero es deuda (negativo) o cuenta por cobrar
// (positivo), nunca dinero disponible.
export function isLoan(behavior: AccountBehavior | null | undefined): boolean {
  return behavior === "loan";
}

// TAR-02: los datos de plástico (banco, red, last4) aplican a tarjetas.
export function isPlastic(behavior: AccountBehavior | null | undefined): boolean {
  return behavior === "credit" || behavior === "debit" || behavior === "prepaid";
}

export interface AccountOut {
  id: string;
  account_type_id: string;
  name: string;
  bank: string | null;
  network: string | null;
  last4: string | null;
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
  color: string | null; // TAR-08: #RRGGBB
  image: string | null; // TAR-08: front-art data URL
  is_active: boolean;
  // AccountWithDebtOut extras (list/detail endpoints):
  behavior: AccountBehavior | null;
  debt: DebtSummary | null;
  balance: string | null; // TAR-05, balance accounts only
  signed_balance: string | null; // TAR-06: +asset or -liability for PAT-01
  next_payment: { amount: string; due_date: string } | null; // TDC-14
  opening_balance: string | null; // TDC-14: synthetic previous-cut debt
}

export interface StatementOut {
  id: string;
  account_id: string;
  period_start: string;
  period_end: string;
  due_date: string;
  computed_total: string;
  applied_credit: string;
  paid_amount: string;
  status: "open" | "closed" | "paid" | "partially_paid";
  is_overdue: boolean;
}

// Los recordatorios se exponen en src/api/notifications.ts (REM-04..REM-07).

export interface AccountBody {
  account_type_id: string;
  name: string;
  bank?: string | null;
  network?: string | null;
  last4?: string | null;
  currency?: string; // TAR-10
  color?: string | null; // TAR-08
  image?: string | null; // TAR-08
  // Credit-only (TAR-02):
  statement_day?: number | string | null;
  cutoff_day_policy?: string;
  payment_due_days?: number | null;
  payment_day?: number | string | null;
  credit_limit?: string | null;
  opening_balance?: string | null; // TDC-14
  // Balance accounts (TAR-05):
  initial_balance?: string | null;
  allow_overdraft?: boolean;
}

// TDC-15: full edit. Only the fields sent are applied.
export interface AccountUpdateBody {
  name?: string;
  bank?: string | null;
  network?: string | null;
  last4?: string | null;
  currency?: string;
  color?: string | null; // TAR-08
  image?: string | null; // TAR-08
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

export function useAccounts(enabled = true, includeInactive = false) {
  return useQuery({
    // includeInactive is part of the key so toggling refetches; the broad
    // ["accounts"] invalidation still matches by prefix.
    queryKey: ["accounts", { includeInactive }],
    queryFn: () =>
      api<AccountOut[]>(`/api/v1/accounts${includeInactive ? "?include_inactive=true" : ""}`),
    enabled,
  });
}

export function useStatements(accountId: string | null) {
  return useQuery({
    queryKey: ["statements", accountId],
    queryFn: () => api<StatementOut[]>(`/api/v1/accounts/${accountId}/statements`),
    enabled: accountId !== null,
  });
}

function useInvalidateAccounts() {
  const qc = useQueryClient();
  return () =>
    ["accounts", "statements", "transactions", "notifications", "msi", "forecast"].forEach(
      (k) => void qc.invalidateQueries({ queryKey: [k] }),
    );
}

export function useCreateAccount() {
  const invalidate = useInvalidateAccounts();
  return useMutation({
    mutationFn: (body: AccountBody) =>
      api<AccountOut>("/api/v1/accounts", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useUpdateAccount() {
  const invalidate = useInvalidateAccounts();
  return useMutation({
    mutationFn: ({ accountId, ...body }: { accountId: string } & AccountUpdateBody) =>
      api<AccountOut>(`/api/v1/accounts/${accountId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

// GLO-03: borrado físico solo sin movimientos (409 si los tiene).
export function useDeleteAccount() {
  const invalidate = useInvalidateAccounts();
  return useMutation({
    mutationFn: (accountId: string) =>
      api<void>(`/api/v1/accounts/${accountId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

// TAR-09: fija el saldo del efectivo al dinero real que hay.
export function useAdjustCashBalance() {
  const invalidate = useInvalidateAccounts();
  return useMutation({
    mutationFn: ({ accountId, balance }: { accountId: string; balance: string }) =>
      api<AccountOut>(`/api/v1/accounts/${accountId}/balance`, {
        method: "POST",
        body: JSON.stringify({ balance }),
      }),
    onSuccess: invalidate,
  });
}

export function usePayCard() {
  const invalidate = useInvalidateAccounts();
  return useMutation({
    mutationFn: ({
      accountId,
      ...body
    }: {
      accountId: string;
      amount: string;
      from_account_id: string;
      date: string;
      statement_id?: string | null;
    }) =>
      api(`/api/v1/accounts/${accountId}/payments`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

// TAR-07: secciones de la página Cuentas (fijas por behavior), orden default.
export type AccountGroupKey = "cash" | "savings" | "credit" | "loan";
export const DEFAULT_GROUP_ORDER: AccountGroupKey[] = ["cash", "savings", "credit", "loan"];

export interface AccountLayout {
  account_ids: string[];
  group_order: AccountGroupKey[];
}

export function useAccountLayout() {
  return useQuery({
    // Bajo "accounts" para que cualquier invalidación de cuentas lo refresque.
    queryKey: ["accounts", "layout"],
    queryFn: () => api<AccountLayout>("/api/v1/accounts/layout"),
  });
}

// TAR-07: persist the current user's account (and section) order. Raw request
// so it can be fired during unmount (auto-save on leaving the module) without
// depending on a mutation hook's lifecycle.
export function saveAccountLayoutRequest(accountIds: string[], groupOrder?: AccountGroupKey[]) {
  return api("/api/v1/accounts/layout", {
    method: "PUT",
    body: JSON.stringify({ account_ids: accountIds, group_order: groupOrder }),
  });
}

export function useSaveAccountLayout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ accountIds, groupOrder }: { accountIds: string[]; groupOrder?: AccountGroupKey[] }) =>
      saveAccountLayoutRequest(accountIds, groupOrder),
    // Only the order changed: invalidate just accounts, not the broad debt/MSI set.
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useCloseCycles() {
  const invalidate = useInvalidateAccounts();
  return useMutation({
    mutationFn: () => api<StatementOut[]>("/api/v1/accounts/close-cycles", { method: "POST" }),
    onSuccess: invalidate,
  });
}
