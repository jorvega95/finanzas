// Catálogos (CAT-01..07).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface CategoryOut {
  id: string;
  name: string;
  kind: "expense" | "income";
  expense_nature: "fixed" | "variable" | "discretionary" | null;
  parent_id: string | null;
  icon: string | null;
  color: string | null;
  is_active: boolean;
}

export interface PaymentMethodOut {
  id: string;
  name: string;
  type: "cash" | "debit" | "credit_card" | "transfer" | "other";
  credit_card_id: string | null;
  is_active: boolean;
}

export function useCategories(includeInactive = false) {
  return useQuery({
    queryKey: ["categories", includeInactive],
    queryFn: () =>
      api<CategoryOut[]>(
        `/api/v1/catalogs/categories?include_inactive=${includeInactive}`,
      ),
  });
}

export function usePaymentMethods(includeInactive = false) {
  return useQuery({
    queryKey: ["payment-methods", includeInactive],
    queryFn: () =>
      api<PaymentMethodOut[]>(
        `/api/v1/catalogs/payment-methods?include_inactive=${includeInactive}`,
      ),
  });
}

function useInvalidate(keys: string[]) {
  const qc = useQueryClient();
  return () => keys.forEach((k) => void qc.invalidateQueries({ queryKey: [k] }));
}

export function useCreateCategory() {
  const invalidate = useInvalidate(["categories"]);
  return useMutation({
    mutationFn: (body: {
      name: string;
      kind: "expense" | "income";
      expense_nature?: string | null;
      parent_id?: string | null;
    }) =>
      api<CategoryOut>("/api/v1/catalogs/categories", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useUpdateCategory() {
  const invalidate = useInvalidate(["categories"]);
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name?: string; is_active?: boolean }) =>
      api<CategoryOut>(`/api/v1/catalogs/categories/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useCreatePaymentMethod() {
  const invalidate = useInvalidate(["payment-methods"]);
  return useMutation({
    mutationFn: (body: { name: string; type: PaymentMethodOut["type"] }) =>
      api<PaymentMethodOut>("/api/v1/catalogs/payment-methods", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useUpdatePaymentMethod() {
  const invalidate = useInvalidate(["payment-methods"]);
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name?: string; is_active?: boolean }) =>
      api<PaymentMethodOut>(`/api/v1/catalogs/payment-methods/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}
