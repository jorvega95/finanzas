// Facturación de ingresos freelance (FAC-01..FAC-14): cobros facturables,
// facturas (CFDI), archivos y configuración del portal del SAT.
// GLO-01: montos y tasas como strings.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getActiveSpaceId } from "./activeSpace";
import { ApiError, api } from "./client";

export type PaymentStatus = "pending_invoice" | "invoiced" | "declared" | "paid" | "excluded";

export interface StoredFileOut {
  id: string;
  original_name: string;
  mime: string;
  size: number;
  created_at: string;
}

export interface InvoiceOut {
  id: string;
  cfdi_uuid: string | null;
  issue_date: string;
  total: string;
  currency: string;
  fx_rate: string | null;
  file: StoredFileOut | null;
  notes: string | null;
}

export interface PaymentOut {
  id: string;
  client_id: string;
  transaction_id: string | null;
  account_id: string | null;
  payment_date: string;
  period: string; // FAC-02: primer día del mes fiscal
  amount: string;
  currency: string;
  fiscal_fx_rate: string | null;
  mxn: string | null; // FAC-06
  work_period_start: string | null;
  work_period_end: string | null;
  description: string;
  notes: string | null;
  is_excluded: boolean;
  status: PaymentStatus; // FAC-04 (calculado)
  invoice: InvoiceOut | null;
  invoice_mismatch: boolean;
  capture_file: StoredFileOut | null;
}

export interface BillingClientOut {
  id: string;
  name: string;
  tax_id: string | null;
  foreign_tax_id: string | null;
  country: string | null;
  fiscal_regime: string | null;
  cfdi_use: string | null;
  product_code: string | null;
  unit_code: string | null;
  postal_code: string | null;
  concept_template: string | null;
  is_active: boolean;
}

export type BillingClientBody = Partial<Omit<BillingClientOut, "id">>;

export interface BillingSettingsOut {
  sat_invoice_url: string | null;
  sat_filing_url: string | null;
  sat_payment_url: string | null;
  rfc_extra_days: number; // FAC-12
}

export interface BillingSummaryOut {
  counts: Record<PaymentStatus, number>;
  pending_amounts: Record<string, string>;
}

export interface InvoiceSheetOut {
  payment: PaymentOut;
  client: BillingClientOut;
  description: string;
  missing: ("work_period" | "fiscal_fx_rate")[];
  sat_invoice_url: string | null;
}

export interface InvoiceBody {
  cfdi_uuid?: string | null;
  issue_date: string;
  total: string;
  currency: string;
  fx_rate?: string | null;
  file_id?: string | null;
  notes?: string | null;
}

export interface OldPaymentBody {
  client_id: string;
  payment_date: string;
  amount: string;
  currency: string;
  fiscal_fx_rate?: string | null;
  work_period_start?: string | null;
  work_period_end?: string | null;
  description?: string;
  notes?: string | null;
  capture_file_id?: string | null;
  invoice?: InvoiceBody | null;
}

export interface PaymentUpdateBody {
  client_id?: string;
  fiscal_fx_rate?: string | null;
  work_period_start?: string | null;
  work_period_end?: string | null;
  description?: string;
  notes?: string | null;
  is_excluded?: boolean;
  capture_file_id?: string | null;
  // Solo pagos anteriores (FAC-02):
  payment_date?: string;
  amount?: string;
  currency?: string;
}

const KEYS = ["billing", "accounts", "transactions", "dashboard", "budgets", "forecast"];

function useInvalidateBilling() {
  const qc = useQueryClient();
  return () => KEYS.forEach((k) => void qc.invalidateQueries({ queryKey: [k] }));
}

export function useBillingPayments(status?: PaymentStatus) {
  return useQuery({
    queryKey: ["billing", "payments", { status }],
    queryFn: () =>
      api<PaymentOut[]>(`/api/v1/billing/payments${status ? `?status=${status}` : ""}`),
  });
}

export function useBillingSummary() {
  return useQuery({
    queryKey: ["billing", "summary"],
    queryFn: () => api<BillingSummaryOut>("/api/v1/billing/summary"),
  });
}

export function useInvoiceSheet(paymentId: string | null) {
  return useQuery({
    queryKey: ["billing", "sheet", paymentId],
    queryFn: () => api<InvoiceSheetOut>(`/api/v1/billing/payments/${paymentId}/sheet`),
    enabled: paymentId !== null,
  });
}

export function useBillingClients(includeInactive = false) {
  return useQuery({
    queryKey: ["billing", "clients", { includeInactive }],
    queryFn: () =>
      api<BillingClientOut[]>(
        `/api/v1/billing/clients${includeInactive ? "?include_inactive=true" : ""}`,
      ),
  });
}

export function useBillingSettings() {
  return useQuery({
    queryKey: ["billing", "settings"],
    queryFn: () => api<BillingSettingsOut>("/api/v1/billing/settings"),
  });
}

export function useSaveBillingSettings() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: (body: Partial<BillingSettingsOut>) =>
      api<BillingSettingsOut>("/api/v1/billing/settings", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useSaveBillingClient() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: ({ id, ...body }: BillingClientBody & { id?: string }) =>
      id
        ? api<BillingClientOut>(`/api/v1/billing/clients/${id}`, {
            method: "PATCH",
            body: JSON.stringify(body),
          })
        : api<BillingClientOut>("/api/v1/billing/clients", {
            method: "POST",
            body: JSON.stringify(body),
          }),
    onSuccess: invalidate,
  });
}

export function useDeleteBillingClient() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/api/v1/billing/clients/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

// FAC-01: marca (o desmarca con null) una cuenta facturable; opcionalmente
// importa sus ingresos existentes desde una fecha.
export function useSetInvoiceableAccount() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: ({
      accountId,
      ...body
    }: {
      accountId: string;
      client_id: string | null;
      import_since?: string | null;
    }) =>
      api<{ account_id: string; client_id: string | null; imported: number }>(
        `/api/v1/billing/accounts/${accountId}`,
        { method: "PUT", body: JSON.stringify(body) },
      ),
    onSuccess: invalidate,
  });
}

export function useCreateOldPayment() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: (body: OldPaymentBody) =>
      api<PaymentOut>("/api/v1/billing/payments", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useUpdatePayment() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: ({ id, ...body }: PaymentUpdateBody & { id: string }) =>
      api<PaymentOut>(`/api/v1/billing/payments/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useDeletePayment() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/api/v1/billing/payments/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useSaveInvoice() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: ({ paymentId, ...body }: InvoiceBody & { paymentId: string }) =>
      api<PaymentOut>(`/api/v1/billing/payments/${paymentId}/invoice`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useDeleteInvoice() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: (paymentId: string) =>
      api<PaymentOut>(`/api/v1/billing/payments/${paymentId}/invoice`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

// --- Declaraciones (FAC-06/07/08/12/13) ---------------------------------------------

export type FilingKind = "normal" | "complementary";
export type PeriodStatus = "open" | "to_declare" | "to_pay" | "paid";

export interface FilingOut {
  id: string;
  period: string;
  kind: FilingKind;
  filed_date: string;
  operation_number: string | null;
  capture_line: string | null;
  declared_income: string | null;
  isr_amount: string;
  iva_amount: string;
  amount_due: string;
  valid_until: string | null;
  ack_file: StoredFileOut | null;
  paid_date: string | null;
  paid_amount: string | null;
  receipt_file: StoredFileOut | null;
  expense_transaction_id: string | null;
  notes: string | null;
}

export interface PrefillItem {
  payment_id: string;
  payment_date: string;
  issue_date: string;
  mxn: string | null;
}

export interface PeriodOut {
  period: string;
  status: PeriodStatus;
  is_overdue: boolean;
  deadline: string;
  payment_deadline: string | null;
  to_declare: string; // FAC-06: pesos sin centavos
  missing_rates: number;
  pending_invoice: number;
  isr_rate: string; // FAC-07
  isr_estimate: string;
  sat_prefill: string; // FAC-08
  prefill_unknown: number;
  exclude_from_prefill: PrefillItem[];
  add_to_prefill: PrefillItem[];
  amount_due: string;
  payment_ids: string[];
  filings: FilingOut[];
}

export interface FilingPaymentBody {
  paid_date: string;
  paid_amount: string;
  receipt_file_id?: string | null;
  account_id?: string | null; // FAC-13: crea el gasto "Impuestos"
}

export interface FilingBody {
  period?: string;
  kind?: FilingKind;
  filed_date?: string;
  operation_number?: string | null;
  capture_line?: string | null;
  declared_income?: string | null;
  isr_amount?: string;
  iva_amount?: string;
  amount_due?: string;
  valid_until?: string | null;
  ack_file_id?: string | null;
  notes?: string | null;
  payment?: FilingPaymentBody | null;
}

export function useBillingPeriods() {
  return useQuery({
    queryKey: ["billing", "periods"],
    queryFn: () => api<PeriodOut[]>("/api/v1/billing/periods"),
  });
}

export function useSaveFiling() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: ({ id, ...body }: FilingBody & { id?: string }) =>
      id
        ? api<FilingOut>(`/api/v1/billing/filings/${id}`, {
            method: "PATCH",
            body: JSON.stringify(body),
          })
        : api<FilingOut>("/api/v1/billing/filings", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useDeleteFiling() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/api/v1/billing/filings/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useSetFilingPayment() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: ({ filingId, ...body }: FilingPaymentBody & { filingId: string }) =>
      api<FilingOut>(`/api/v1/billing/filings/${filingId}/payment`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useRemoveFilingPayment() {
  const invalidate = useInvalidateBilling();
  return useMutation({
    mutationFn: (filingId: string) =>
      api<FilingOut>(`/api/v1/billing/filings/${filingId}/payment`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

// --- CFDI y exportación (FAC-15/16) ---------------------------------------------------

export type CfdiWarning = "total" | "currency" | "fx_rate" | "issue_month" | "iva" | "receiver";

export interface CfdiCheckOut {
  uuid: string | null;
  issue_date: string | null;
  total: string | null;
  currency: string | null;
  fx_rate: string | null;
  issuer_rfc: string | null;
  receiver_rfc: string | null;
  receiver_name: string | null;
  iva_rates: string[];
  warnings: CfdiWarning[];
}

// FAC-15: lee el CFDI del archivo subido y lo compara con el cobro.
export function checkCfdi(paymentId: string, fileId: string): Promise<CfdiCheckOut> {
  return api<CfdiCheckOut>(
    `/api/v1/billing/payments/${paymentId}/cfdi?file_id=${encodeURIComponent(fileId)}`,
  );
}

// FAC-16: .zip del año con una carpeta por mes y resúmenes CSV.
export async function downloadExport(year: number): Promise<void> {
  const spaceId = getActiveSpaceId();
  const base = (import.meta.env.VITE_API_URL as string | undefined) ?? "";
  const res = await fetch(`${base}/api/v1/billing/export?year=${year}`, {
    headers: spaceId ? { "X-Space-Id": spaceId } : {},
  });
  if (!res.ok) throw new ApiError(res.status, "No se pudo generar la exportación");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `facturacion-${year}.zip`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// FAC-10: el archivo viaja crudo en el cuerpo (sin multipart); el backend
// detecta el tipo por su contenido.
export async function uploadFile(file: File): Promise<StoredFileOut> {
  return api<StoredFileOut>(`/api/v1/billing/files?filename=${encodeURIComponent(file.name)}`, {
    method: "POST",
    body: file,
    headers: { "Content-Type": "application/octet-stream" },
  });
}

// FAC-10: descarga con el header del espacio activo (un <a href> no lo manda).
export async function openFile(file: StoredFileOut, inline = false): Promise<void> {
  const spaceId = getActiveSpaceId();
  const base = (import.meta.env.VITE_API_URL as string | undefined) ?? "";
  const res = await fetch(`${base}/api/v1/billing/files/${file.id}${inline ? "?inline=true" : ""}`, {
    headers: spaceId ? { "X-Space-Id": spaceId } : {},
  });
  if (!res.ok) throw new ApiError(res.status, "No se pudo abrir el archivo");
  const url = URL.createObjectURL(await res.blob());
  if (inline) {
    window.open(url, "_blank", "noopener,noreferrer");
  } else {
    const a = document.createElement("a");
    a.href = url;
    a.download = file.original_name;
    a.click();
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
