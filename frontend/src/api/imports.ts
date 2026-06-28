// Importación CSV y export (IMP-01..07).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface MappingConfig {
  date_column: string;
  amount_column: string;
  description_column?: string | null;
  date_format: string;
  decimal_separator: string;
  delimiter: string;
  negative_is_expense: boolean;
  currency: string;
}

export interface PreviewRow {
  row: number;
  date: string | null;
  type: string | null;
  amount: string | null;
  currency: string | null;
  description: string;
  error: string | null;
  is_duplicate: boolean;
  selected: boolean;
}

export interface PreviewResponse {
  rows: PreviewRow[];
  total: number;
  duplicates: number;
  invalid: number;
}

export interface BatchOut {
  id: string;
  source: string;
  file_name: string;
  row_count: number;
  status: "confirmed" | "rolled_back" | "partially_rolled_back";
}

export function usePreviewImport() {
  return useMutation({
    mutationFn: (body: { content: string; mapping: MappingConfig }) =>
      api<PreviewResponse>("/api/v1/imports/preview", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  });
}

function useInvalidateImports() {
  const qc = useQueryClient();
  return () =>
    ["imports", "transactions", "cards", "statements", "budgets", "forecast"].forEach(
      (k) => void qc.invalidateQueries({ queryKey: [k] }),
    );
}

export function useConfirmImport() {
  const invalidate = useInvalidateImports();
  return useMutation({
    mutationFn: (body: {
      file_name: string;
      source: string;
      mapping: MappingConfig;
      rows: PreviewRow[];
      payment_method_id: string;
    }) =>
      api<BatchOut>("/api/v1/imports/confirm", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useImportBatches() {
  return useQuery({
    queryKey: ["imports"],
    queryFn: () => api<BatchOut[]>("/api/v1/imports"),
  });
}

export function useRollbackBatch() {
  const invalidate = useInvalidateImports();
  return useMutation({
    mutationFn: (batchId: string) =>
      api<{ removed: number; kept_edited: number }>(
        `/api/v1/imports/${batchId}/rollback`,
        { method: "POST" },
      ),
    onSuccess: invalidate,
  });
}
