// Facturación de ingresos freelance (RESICO, FAC-01..FAC-14). Cada ingreso en
// una cuenta facturable (XTRM) aparece aquí como cobro por facturar (FAC-01);
// la ficha arma lo que se captura en el portal del SAT (FAC-11) y la factura
// (.zip) se sube al cobro (FAC-03/10). Los pagos que ya no están en la
// billetera se capturan a mano como "pagos anteriores" (FAC-01b).
import { useMemo, useState, type FormEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { hasBalance, useAccounts } from "../../api/accounts";
import {
  downloadExport,
  useBillingClients,
  useBillingPayments,
  useBillingPeriods,
  useBillingSettings,
  useBillingSummary,
  useCreateOldPayment,
  useDeleteBillingClient,
  useSaveBillingClient,
  useSaveBillingSettings,
  useSetInvoiceableAccount,
  type BillingClientOut,
  type PaymentOut,
  type StoredFileOut,
} from "../../api/billing";
import Icon from "../../components/ui/Icon";
import Modal from "../../components/ui/Modal";
import ConfirmDialog from "../../components/ui/ConfirmDialog";
import Spinner from "../../components/ui/Spinner";
import { useToast } from "../../components/ui/Toast";
import { formatDate, todayISO } from "../../lib/dates";
import { formatMoney, isPositiveAmount, sanitizeDecimal } from "../../lib/money";
import DeclarationsTab from "./DeclarationsTab";
import PaymentDetail from "./PaymentDetail";
import {
  BanxicoButton,
  ErrorLine,
  FilePicker,
  SatLink,
  StatusBadge,
  errorText,
  monthLabel,
} from "./shared";

const CURRENCIES = ["USD", "MXN"];
const RATE_PATTERN = /^\d+(\.\d{1,4})?$/;
const TASK_RATE_PATTERN = /^(?!0+(\.0+)?$)\d+(\.\d{1,2})?$/;
const CFDI_UUID_PATTERN =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
// Valores genéricos del SAT para un cliente extranjero (no son datos personales).
const CLIENT_DEFAULTS = {
  tax_id: "XEXX010101000",
  fiscal_regime: "616 · Sin obligaciones fiscales",
  cfdi_use: "S01 · Sin efectos fiscales",
  product_code: "81112000",
  unit_code: "E48 · Unidad de servicio",
  concept_template:
    "Servicios de entrenamiento y evaluación de modelos de IA periodo {periodo} pago recibido el {fecha_pago}",
};

// FAC-01b: un cobro que ya no está en la billetera; puede venir ya facturado.
function OldPaymentForm({ clients, onDone }: { clients: BillingClientOut[]; onDone: () => void }) {
  const toast = useToast();
  const create = useCreateOldPayment();
  const banxicoUrl = useBillingSettings().data?.banxico_fx_url ?? null;
  const [clientId, setClientId] = useState(clients[0]?.id ?? "");
  const [date, setDate] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [rate, setRate] = useState("");
  const [workStart, setWorkStart] = useState("");
  const [workEnd, setWorkEnd] = useState("");
  const [invoiced, setInvoiced] = useState(false);
  const [issueDate, setIssueDate] = useState("");
  const [cfdiUuid, setCfdiUuid] = useState("");
  const [file, setFile] = useState<StoredFileOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isUsd = currency !== "MXN";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!clientId) return setError("Primero da de alta al cliente en Configuración.");
    if (!isPositiveAmount(amount)) return setError("El monto debe ser mayor a 0.");
    if (date > todayISO()) return setError("La fecha del cobro no puede ser futura.");
    if (isUsd && rate && !RATE_PATTERN.test(rate))
      return setError("El tipo de cambio admite hasta 4 decimales.");
    if (Boolean(workStart) !== Boolean(workEnd))
      return setError("Captura el inicio y el fin del periodo trabajado.");
    if (cfdiUuid && !CFDI_UUID_PATTERN.test(cfdiUuid.trim()))
      return setError("El folio fiscal tiene el formato XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX.");
    try {
      await create.mutateAsync({
        client_id: clientId,
        payment_date: date,
        amount,
        currency,
        fiscal_fx_rate: isUsd ? rate || null : null,
        work_period_start: workStart || null,
        work_period_end: workEnd || null,
        invoice: invoiced
          ? {
              issue_date: issueDate || date,
              total: amount,
              currency,
              fx_rate: isUsd ? rate || null : null,
              cfdi_uuid: cfdiUuid.trim() || null,
              file_id: file?.id ?? null,
            }
          : null,
      });
      toast.success(`Pago anterior del ${formatDate(date)} registrado.`);
      onDone();
    } catch (err) {
      setError(errorText(err));
      toast.error(`No se registró el pago anterior: ${errorText(err)}`);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div className="col-span-2">
        <label className="label" htmlFor="o-client">Cliente</label>
        <select
          id="o-client"
          className="input"
          required
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
        >
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>
      <div className="col-span-2">
        <label className="label" htmlFor="o-date">Fecha en que cayó en la billetera</label>
        <input
          id="o-date"
          type="date"
          className="input"
          required
          max={todayISO()}
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="o-amount">Monto</label>
        <input
          id="o-amount"
          className="input"
          inputMode="decimal"
          required
          placeholder="0.00"
          value={amount}
          onChange={(e) => setAmount(sanitizeDecimal(e.target.value))}
        />
      </div>
      <div>
        <label className="label" htmlFor="o-currency">Moneda</label>
        <select
          id="o-currency"
          className="input"
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
        >
          {CURRENCIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </div>
      {isUsd && (
        <div className="col-span-2">
          <label className="label" htmlFor="o-rate">Tipo de cambio Banxico</label>
          <div className="flex gap-2">
            <input
              id="o-rate"
              className="input"
              inputMode="decimal"
              placeholder="Para solventar obligaciones"
              value={rate}
              onChange={(e) => setRate(sanitizeDecimal(e.target.value, 4))}
            />
            <BanxicoButton url={banxicoUrl} />
          </div>
        </div>
      )}
      <div>
        <label className="label" htmlFor="o-ws">Periodo trabajado: inicio</label>
        <input
          id="o-ws"
          type="date"
          className="input"
          value={workStart}
          onChange={(e) => setWorkStart(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="o-we">Fin</label>
        <input
          id="o-we"
          type="date"
          className="input"
          value={workEnd}
          onChange={(e) => setWorkEnd(e.target.value)}
        />
      </div>
      <label className="col-span-2 flex items-center gap-2 text-sm md:col-span-4">
        <input type="checkbox" checked={invoiced} onChange={(e) => setInvoiced(e.target.checked)} />
        Ya está facturado
      </label>
      {invoiced && (
        <>
          <div>
            <label className="label" htmlFor="o-issue">Fecha de emisión</label>
            <input
              id="o-issue"
              type="date"
              className="input"
              value={issueDate}
              onChange={(e) => setIssueDate(e.target.value)}
            />
          </div>
          <div className="col-span-2 md:col-span-3">
            <label className="label" htmlFor="o-uuid">Folio fiscal (UUID)</label>
            <input
              id="o-uuid"
              className="input font-mono text-xs"
              placeholder="Opcional"
              value={cfdiUuid}
              onChange={(e) => setCfdiUuid(e.target.value)}
            />
          </div>
          <div className="col-span-2 md:col-span-4">
            <FilePicker
              label="Factura (.zip, .xml o .pdf, opcional)"
              accept=".zip,.xml,.pdf"
              file={file}
              onUploaded={setFile}
            />
          </div>
        </>
      )}
      <div className="col-span-2 flex flex-wrap items-center justify-end gap-2 md:col-span-4">
        <ErrorLine error={error} />
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cancelar
        </button>
        <button className="btn-primary" disabled={create.isPending}>
          Registrar pago anterior
        </button>
      </div>
    </form>
  );
}

function PaymentList({
  payments,
  clients,
  onOpen,
}: {
  payments: PaymentOut[];
  clients: Map<string, string>;
  onOpen: (p: PaymentOut) => void;
}) {
  // Agrupado por periodo fiscal (FAC-02), el más reciente arriba.
  const groups = useMemo(() => {
    const byPeriod = new Map<string, PaymentOut[]>();
    for (const p of payments) byPeriod.set(p.period, [...(byPeriod.get(p.period) ?? []), p]);
    return [...byPeriod.entries()];
  }, [payments]);

  return (
    <div className="space-y-4">
      {groups.map(([period, rows]) => (
        <section key={period} className="card overflow-hidden">
          <h2 className="border-b border-line px-4 py-2.5 text-sm font-semibold">{monthLabel(period)}</h2>
          <ul className="divide-y divide-line">
            {rows.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  className="flex w-full flex-wrap items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-muted/60"
                  onClick={() => onOpen(p)}
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium">
                      {formatDate(p.payment_date)} · {clients.get(p.client_id) ?? "Cliente"}
                    </p>
                    <p className="truncate text-xs text-ink-muted">
                      {[
                        p.transaction_id === null ? "Pago anterior" : p.description || "Ingreso",
                        p.invoice ? `Factura del ${formatDate(p.invoice.issue_date)}` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    <StatusBadge payment={p} />
                    <div className="w-36 shrink-0 text-right">
                      <p className="tabular text-sm font-semibold">{formatMoney(p.amount, p.currency)}</p>
                      {p.currency !== "MXN" && (
                        <p className="tabular text-xs text-ink-muted">
                          {p.mxn ? `≈ ${formatMoney(p.mxn, "MXN")}` : "Sin tipo de cambio"}
                        </p>
                      )}
                    </div>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function ClientForm({ client, onDone }: { client: BillingClientOut | null; onDone: () => void }) {
  const toast = useToast();
  const save = useSaveBillingClient();
  const remove = useDeleteBillingClient();
  // GLO-09: borrar el cliente se confirma.
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const initial = client ?? {
    name: "",
    foreign_tax_id: "",
    country: "",
    postal_code: "",
    task_rate: "",
    ...CLIENT_DEFAULTS,
  };
  const [form, setForm] = useState({
    name: initial.name ?? "",
    tax_id: initial.tax_id ?? "",
    foreign_tax_id: initial.foreign_tax_id ?? "",
    country: initial.country ?? "",
    fiscal_regime: initial.fiscal_regime ?? "",
    cfdi_use: initial.cfdi_use ?? "",
    product_code: initial.product_code ?? "",
    unit_code: initial.unit_code ?? "",
    postal_code: initial.postal_code ?? "",
    concept_template: initial.concept_template ?? "",
    task_rate: initial.task_rate ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const field = (key: keyof typeof form, label: string, maxLength = 60, hint?: string) => (
    <div>
      <label className="label" htmlFor={`cl-${key}`}>{label}</label>
      <input
        id={`cl-${key}`}
        className="input"
        maxLength={maxLength}
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
      />
      {hint && <p className="mt-1 text-xs text-ink-muted">{hint}</p>}
    </div>
  );

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.name.trim()) return setError("El nombre o razón social es obligatorio.");
    if (form.task_rate.trim() && !TASK_RATE_PATTERN.test(form.task_rate.trim()))
      return setError("La tarifa por task debe ser un monto mayor a 0 con hasta 2 decimales.");
    const body = Object.fromEntries(
      Object.entries(form).map(([k, v]) => [k, v.trim() || null]),
    ) as Record<keyof typeof form, string | null>;
    try {
      await save.mutateAsync({ id: client?.id, ...body, name: form.name.trim() });
      toast.success(`Cliente «${form.name.trim()}» guardado.`);
      onDone();
    } catch (err) {
      setError(errorText(err));
      toast.error(`No se guardó el cliente: ${errorText(err)}`);
    }
  }

  // FAC-11: mismas etiquetas y acomodo que "Genera tu factura" del portal.
  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <fieldset className="space-y-3">
        <legend className="mb-3 text-sm font-semibold">Datos del cliente</legend>
        <div className="grid gap-3 md:grid-cols-3">
          <div className="space-y-3">
            {field("tax_id", "Cliente Frecuente (RFC)", 13, "Para un extranjero, XEXX010101000")}
            {field("country", "País de Residencia Fiscal")}
          </div>
          <div className="space-y-3">
            {field("name", "Nombre o Razón Social", 120)}
            {field("postal_code", "Código Postal", 10)}
            {field("fiscal_regime", "Régimen Fiscal")}
            {field("foreign_tax_id", "Clave de Identidad Fiscal", 40, "El tax ID del cliente en su país")}
          </div>
          <div className="space-y-3">{field("cfdi_use", "Uso de la Factura")}</div>
        </div>
      </fieldset>
      <fieldset className="space-y-3">
        <legend className="mb-3 text-sm font-semibold">Producto y Servicio</legend>
        <div className="grid gap-3 md:grid-cols-3">
          {field("product_code", "Producto o Servicio")}
          {field("unit_code", "Unidad de Medida")}
          {field(
            "task_rate",
            "Tarifa por task (opcional)",
            14,
            "En la moneda de sus cobros",
          )}
        </div>
        <div>
          <label className="label" htmlFor="cl-template">Descripción Detallada (plantilla)</label>
          <textarea
            id="cl-template"
            className="input"
            rows={2}
            maxLength={1000}
            value={form.concept_template}
            onChange={(e) => setForm({ ...form, concept_template: e.target.value })}
          />
          <p className="mt-1 text-xs text-ink-muted">
            <code>{"{periodo}"}</code> = "21 al 27 de septiembre de 2026" ·{" "}
            <code>{"{fecha_pago}"}</code> = "02/10/2026"
          </p>
        </div>
      </fieldset>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <ErrorLine error={error} />
        {client && (
          <button
            type="button"
            className="btn-danger"
            title="Si ya tiene cobros, se desactiva en lugar de borrarse"
            disabled={remove.isPending}
            onClick={() => setConfirmingDelete(true)}
          >
            Borrar cliente
          </button>
        )}
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cancelar
        </button>
        <button className="btn-primary" disabled={save.isPending}>
          Guardar cliente
        </button>
      </div>

      {client && (
        <ConfirmDialog
          open={confirmingDelete}
          title="Borrar cliente"
          confirmLabel="Eliminar"
          pending={remove.isPending}
          onClose={() => setConfirmingDelete(false)}
          onConfirm={() => {
            setConfirmingDelete(false);
            void remove
              .mutateAsync(client.id)
              .then(() => {
                toast.success(`Cliente «${client.name}» borrado o desactivado.`);
                onDone();
              })
              .catch((err) => setError(errorText(err)));
          }}
        >
          <p>
            ¿Borrar a <strong>{client.name}</strong>? Si ya tiene cobros, se desactiva en lugar de
            borrarse y sus cuentas dejan de generar cobros nuevos.
          </p>
        </ConfirmDialog>
      )}
    </form>
  );
}

// FAC-01: cuentas facturables. Se listan solo las que ya facturan; para agregar
// otra se elige la cuenta y, ya elegida, el cliente y desde cuándo importar.
function InvoiceableAccounts({ clients }: { clients: BillingClientOut[] }) {
  const toast = useToast();
  const accounts = useAccounts();
  const setInvoiceable = useSetInvoiceableAccount();
  const [accountId, setAccountId] = useState("");
  const [clientId, setClientId] = useState("");
  const [importSince, setImportSince] = useState("");
  // GLO-10: importar ingresos o dejar de facturar una cuenta se confirma.
  const [confirming, setConfirming] = useState<"import" | { id: string; name: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const balanceAccounts = (accounts.data ?? []).filter((a) => a.is_active && hasBalance(a.behavior));
  const invoiceable = balanceAccounts.filter((a) => a.invoice_client_id);
  const available = balanceAccounts.filter((a) => !a.invoice_client_id);
  const selected = available.find((a) => a.id === accountId) ?? null;
  const clientNames = new Map(clients.map((c) => [c.id, c.name]));
  const chosenClient = clientId || clients[0]?.id || "";

  function resetForm() {
    setAccountId("");
    setClientId("");
    setImportSince("");
  }

  async function change(id: string, client: string | null, since: string | null) {
    setError(null);
    try {
      const res = await setInvoiceable.mutateAsync({
        accountId: id,
        client_id: client,
        import_since: since,
      });
      toast.success(
        !client
          ? "La cuenta ya no es facturable."
          : res.imported > 0
            ? `Cuenta facturable: se importaron ${res.imported} ingresos como cobros por facturar.`
            : "Cuenta marcada como facturable.",
      );
      if (client) resetForm();
    } catch (err) {
      setError(errorText(err));
      toast.error(errorText(err));
    }
  }

  function handleAdd(e: FormEvent) {
    e.preventDefault();
    if (!selected) return setError("Elige la cuenta.");
    if (!chosenClient) return setError("Primero da de alta al cliente.");
    if (importSince && importSince > todayISO()) return setError("La fecha de importación no puede ser futura.");
    if (importSince) setConfirming("import");
    else void change(selected.id, chosenClient, null);
  }

  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <div>
        <h2 className="font-semibold">Cuentas facturables</h2>
        <p className="text-sm text-ink-muted">
          Cada ingreso que registres en una cuenta facturable (p. ej. tu billetera XTRM) aparece como
          cobro por facturar.
        </p>
      </div>

      {invoiceable.length > 0 ? (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {invoiceable.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">
                  {a.name} <span className="text-xs font-normal text-ink-muted">{a.currency}</span>
                </p>
                <p className="truncate text-xs text-ink-muted">
                  Factura a {clientNames.get(a.invoice_client_id ?? "") ?? "un cliente inactivo"}
                </p>
              </div>
              <button
                type="button"
                className="btn-secondary h-8 px-2.5"
                disabled={setInvoiceable.isPending}
                onClick={() => setConfirming({ id: a.id, name: a.name })}
              >
                Dejar de facturar
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-lg border border-dashed border-line-strong px-3 py-4 text-center text-sm text-ink-muted">
          Ninguna cuenta es facturable todavía.
        </p>
      )}

      {clients.length === 0 ? (
        <p className="text-sm text-ink-muted">Da de alta un cliente arriba para poder agregar una cuenta.</p>
      ) : available.length > 0 ? (
        <form onSubmit={handleAdd} className="space-y-3 border-t border-line pt-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className="label" htmlFor="inv-account">Agregar cuenta facturable</label>
              <select
                id="inv-account"
                className="input"
                value={accountId}
                onChange={(e) => {
                  setAccountId(e.target.value);
                  setError(null);
                }}
              >
                <option value="">Elige una cuenta…</option>
                {available.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} · {a.currency}
                  </option>
                ))}
              </select>
            </div>
            {selected && (
              <>
                <div>
                  <label className="label" htmlFor="inv-client">Facturar a</label>
                  <select
                    id="inv-client"
                    className="input"
                    value={chosenClient}
                    onChange={(e) => setClientId(e.target.value)}
                  >
                    {clients.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor="inv-since">Importar ingresos desde</label>
                  <input
                    id="inv-since"
                    type="date"
                    className="input"
                    max={todayISO()}
                    value={importSince}
                    onChange={(e) => setImportSince(e.target.value)}
                  />
                  <p className="mt-1 text-xs text-ink-muted">
                    Opcional: trae los ingresos ya registrados desde esa fecha.
                  </p>
                </div>
              </>
            )}
          </div>
          {selected && (
            <div className="flex flex-wrap items-center justify-end gap-2">
              <ErrorLine error={error} />
              <button type="button" className="btn-secondary" onClick={resetForm}>
                Cancelar
              </button>
              <button className="btn-primary" disabled={setInvoiceable.isPending}>
                {setInvoiceable.isPending && <Spinner className="size-4" />}
                Marcar como facturable
              </button>
            </div>
          )}
        </form>
      ) : null}
      {!selected && <ErrorLine error={error} />}

      <ConfirmDialog
        open={confirming !== null}
        title={confirming === "import" ? "Importar ingresos" : "Dejar de facturar la cuenta"}
        confirmLabel={confirming === "import" ? "Marcar e importar" : "Sí, dejar de facturar"}
        tone={confirming === "import" ? "primary" : "danger"}
        pending={setInvoiceable.isPending}
        onClose={() => setConfirming(null)}
        onConfirm={() => {
          if (confirming === "import" && selected) void change(selected.id, chosenClient, importSince);
          else if (confirming && confirming !== "import") void change(confirming.id, null, null);
          setConfirming(null);
        }}
      >
        {confirming === "import" ? (
          <p>
            <strong>{selected?.name}</strong> quedará facturable a{" "}
            <strong>{clientNames.get(chosenClient)}</strong> y sus ingresos desde el{" "}
            {importSince ? formatDate(importSince) : ""} se agregarán como cobros por facturar. Los que
            ya estén importados no se duplican.
          </p>
        ) : (
          <p>
            Los ingresos nuevos de <strong>{confirming?.name}</strong> dejarán de crear cobros por
            facturar. Los cobros que ya existen se conservan.
          </p>
        )}
      </ConfirmDialog>
    </section>
  );
}

const SAT_URLS = [
  ["sat_invoice_url", "Factura electrónica (Genera tu factura)"],
  ["sat_filing_url", "Declaración provisional mensual"],
  ["sat_payment_url", "Pago (línea de captura)"],
  ["banxico_fx_url", "Banxico · tipo de cambio para solventar obligaciones"],
] as const;
type SatUrlKey = (typeof SAT_URLS)[number][0];

const RFC_DIGIT_OPTIONS = [
  "Sin días extra (vence el 17)",
  "1 o 2 · un día hábil extra",
  "3 o 4 · dos días hábiles extra",
  "5 o 6 · tres días hábiles extra",
  "7 o 8 · cuatro días hábiles extra",
  "9 o 0 · cinco días hábiles extra",
];

// FAC-06/12/14: enlaces a los portales del SAT y Banxico y sexto dígito del RFC. Se ven en
// modo lectura; «Actualizar» abre el formulario.
function SatSettings() {
  const toast = useToast();
  const settings = useBillingSettings();
  const saveSettings = useSaveBillingSettings();
  const [form, setForm] = useState<(Record<SatUrlKey, string> & { rfc_extra_days: number }) | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const data = settings.data;

  function startEditing() {
    setError(null);
    setForm({
      sat_invoice_url: data?.sat_invoice_url ?? "",
      sat_filing_url: data?.sat_filing_url ?? "",
      sat_payment_url: data?.sat_payment_url ?? "",
      banxico_fx_url: data?.banxico_fx_url ?? "",
      rfc_extra_days: data?.rfc_extra_days ?? 0,
    });
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setError(null);
    const urls = SAT_URLS.map(([key]) => form[key].trim());
    if (urls.some((u) => u && !u.toLowerCase().startsWith("https://")))
      return setError("Las URLs deben empezar con https://.");
    try {
      await saveSettings.mutateAsync({
        sat_invoice_url: form.sat_invoice_url.trim() || null,
        sat_filing_url: form.sat_filing_url.trim() || null,
        sat_payment_url: form.sat_payment_url.trim() || null,
        banxico_fx_url: form.banxico_fx_url.trim() || null,
        rfc_extra_days: form.rfc_extra_days,
      });
      setForm(null);
      toast.success("Configuración del SAT guardada.");
    } catch (err) {
      setError(errorText(err));
      toast.error(`No se guardó la configuración: ${errorText(err)}`);
    }
  }

  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-semibold">SAT y Banxico</h2>
          <p className="text-sm text-ink-muted">
            Enlaces a los portales que se abren desde Facturación y Declaraciones (Banxico, junto al
            tipo de cambio de cada cobro) y el sexto dígito de tu RFC, que suma días hábiles a la
            fecha límite de cada declaración.
          </p>
        </div>
        {!form && (
          <button type="button" className="btn-secondary" disabled={!data} onClick={startEditing}>
            <Icon name="pencil" className="size-3.5" />
            Actualizar URLs
          </button>
        )}
      </div>

      {!form ? (
        <dl className="divide-y divide-line rounded-lg border border-line text-sm">
          {SAT_URLS.map(([key, label]) => (
            <div key={key} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-0.5 px-3 py-2">
              <dt className="text-ink-muted">{label}</dt>
              <dd className="min-w-0 max-w-full">
                {data?.[key] ? (
                  <a
                    className="inline-flex max-w-full items-center gap-1 hover:underline"
                    href={data[key]}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <span className="truncate">{data[key]?.replace(/^https:\/\//, "")}</span>
                    <Icon name="externalLink" className="size-3.5" />
                  </a>
                ) : (
                  <span className="italic text-ink-subtle">Sin configurar</span>
                )}
              </dd>
            </div>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-0.5 px-3 py-2">
            <dt className="text-ink-muted">Sexto dígito del RFC</dt>
            <dd>{RFC_DIGIT_OPTIONS[data?.rfc_extra_days ?? 0]}</dd>
          </div>
        </dl>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-3">
          {SAT_URLS.map(([key, label]) => (
            <div key={key}>
              <label className="label" htmlFor={`url-${key}`}>{label}</label>
              <input
                id={`url-${key}`}
                type="url"
                className="input"
                placeholder="https://"
                maxLength={500}
                value={form[key]}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              />
            </div>
          ))}
          <div>
            <label className="label" htmlFor="rfc-digit">Sexto dígito de tu RFC</label>
            <select
              id="rfc-digit"
              className="input"
              value={form.rfc_extra_days}
              onChange={(e) => setForm({ ...form, rfc_extra_days: Number(e.target.value) })}
            >
              {RFC_DIGIT_OPTIONS.map((label, days) => (
                <option key={days} value={days}>
                  {label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-ink-muted">
              La fecha límite es el 17 del mes siguiente (o el siguiente día hábil) más estos días.
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <ErrorLine error={error} />
            <button type="button" className="btn-secondary" onClick={() => setForm(null)}>
              Cancelar
            </button>
            <button className="btn-primary" disabled={saveSettings.isPending}>
              {saveSettings.isPending && <Spinner className="size-4" />}
              Guardar
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

function SettingsTab({ clients }: { clients: BillingClientOut[] }) {
  const [clientModal, setClientModal] = useState<BillingClientOut | "new" | null>(null);

  return (
    <div className="space-y-4">
      <section className="card space-y-3 p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">Clientes</h2>
          <button className="btn-secondary" onClick={() => setClientModal("new")}>
            <Icon name="plus" />
            Nuevo cliente
          </button>
        </div>
        {clients.length === 0 ? (
          <p className="text-sm text-ink-muted">
            Da de alta a quien te paga (p. ej. Greenlight) con sus datos fiscales para armar la ficha de
            cada factura.
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {clients.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{c.name}</p>
                  <p className="truncate text-xs text-ink-muted">
                    {[c.tax_id, c.foreign_tax_id, c.country].filter(Boolean).join(" · ")}
                  </p>
                </div>
                <button className="btn-ghost px-2" aria-label="Editar" onClick={() => setClientModal(c)}>
                  <Icon name="pencil" className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <InvoiceableAccounts clients={clients} />
      <SatSettings />

      <Modal
        open={clientModal !== null}
        onClose={() => setClientModal(null)}
        title={clientModal === "new" ? "Nuevo cliente" : `Editar ${clientModal?.name ?? ""}`}
        size="xl"
      >
        {clientModal !== null && (
          <ClientForm
            key={clientModal === "new" ? "new" : clientModal.id}
            client={clientModal === "new" ? null : clientModal}
            onDone={() => setClientModal(null)}
          />
        )}
      </Modal>
    </div>
  );
}

// FAC-16: descarga el año elegido en un .zip.
function ExportButton() {
  const toast = useToast();
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="flex items-center gap-1">
      <select
        className="input w-auto"
        aria-label="Año a exportar"
        value={year}
        onChange={(e) => setYear(Number(e.target.value))}
      >
        {[0, 1, 2].map((back) => {
          const y = new Date().getFullYear() - back;
          return (
            <option key={y} value={y}>
              {y}
            </option>
          );
        })}
      </select>
      <button
        className="btn-secondary"
        disabled={busy}
        title={error ?? "Facturas, acuses y comprobantes del año, por mes, con resumen CSV"}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await downloadExport(year);
            toast.success(`Exportación ${year} descargada.`);
          } catch (err) {
            setError(errorText(err));
            toast.error(`No se pudo exportar ${year}: ${errorText(err)}`);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? <Spinner className="size-4" /> : <Icon name="upload" className="size-4 rotate-180" />}
        Exportar
      </button>
    </span>
  );
}

type Tab = "pending_invoice" | "declarations" | "all" | "settings";
const TABS: { id: Tab; label: string }[] = [
  { id: "pending_invoice", label: "Por facturar" },
  { id: "declarations", label: "Declaraciones" },
  { id: "all", label: "Todos los cobros" },
  { id: "settings", label: "Configuración" },
];

const isTab = (value: string | null): value is Tab => TABS.some((t) => t.id === value);

export default function BillingPage() {
  // La pestaña y el cobro abierto viven en la URL (?tab=…&cobro=…): el cobro se
  // ve en lugar de la lista de su pestaña y el botón atrás del navegador regresa.
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const tabParam = searchParams.get("tab");
  const tab: Tab = isTab(tabParam) ? tabParam : "pending_invoice";
  const openId = searchParams.get("cobro");
  const payments = useBillingPayments(tab === "pending_invoice" ? "pending_invoice" : undefined);
  const periods = useBillingPeriods();
  const summary = useBillingSummary();
  const clients = useBillingClients();
  const settings = useBillingSettings();
  const [oldPayment, setOldPayment] = useState(false);
  const clientNames = useMemo(
    () => new Map((clients.data ?? []).map((c) => [c.id, c.name])),
    [clients.data],
  );
  // El cobro abierto se relee de la lista para reflejar cada guardado.
  const allPayments = useBillingPayments();
  const opened = (allPayments.data ?? []).find((p) => p.id === openId) ?? null;

  const tabParams = (t: Tab): Record<string, string> => (t === "pending_invoice" ? {} : { tab: t });
  const selectTab = (t: Tab) => setSearchParams(tabParams(t));
  const openPayment = (p: PaymentOut) =>
    setSearchParams({ ...tabParams(tab), cobro: p.id }, { state: { fromList: true } });
  const closePayment = () => {
    if ((location.state as { fromList?: boolean } | null)?.fromList) navigate(-1);
    else setSearchParams(tabParams(tab), { replace: true });
  };
  const counts = summary.data?.counts;
  const pendingAmounts = Object.entries(summary.data?.pending_amounts ?? {});
  // FAC-12: el siguiente mes por declarar o pagar.
  const nextDue = (periods.data ?? [])
    .filter((p) => p.status === "to_declare" || p.status === "to_pay")
    .sort((a, b) => a.period.localeCompare(b.period))[0];
  const toAttend = (periods.data ?? []).filter(
    (p) => p.status === "to_declare" || p.status === "to_pay",
  ).length;

  return (
    <div className="page">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="page-title">Facturación</h1>
          <p className="page-subtitle">
            Cobros freelance por facturar (RESICO): cada pago que cae en la billetera lleva su factura.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SatLink url={settings.data?.sat_invoice_url ?? null}>Portal de facturación</SatLink>
          <ExportButton />
          <button className="btn-primary" onClick={() => setOldPayment(true)}>
            <Icon name="plus" />
            Pago anterior
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg border border-line bg-surface px-3 py-2.5">
          <p className="text-xs text-ink-muted">Por facturar</p>
          <p className="tabular mt-0.5 text-lg font-semibold">{counts?.pending_invoice ?? "—"}</p>
        </div>
        {pendingAmounts.map(([currency, total]) => (
          <div key={currency} className="rounded-lg border border-line bg-surface px-3 py-2.5">
            <p className="text-xs text-ink-muted">Sin facturar · {currency}</p>
            <p className="tabular mt-0.5 text-lg font-semibold">{formatMoney(total, currency)}</p>
          </div>
        ))}
        <div
          className={`rounded-lg border px-3 py-2.5 ${
            nextDue?.is_overdue ? "border-red-500/40 bg-red-500/10" : "border-line bg-surface"
          }`}
        >
          <p className="text-xs text-ink-muted">
            {nextDue
              ? `${nextDue.status === "to_pay" ? "Pagar" : "Declarar"} ${monthLabel(nextDue.period)}`
              : "Declaraciones"}
          </p>
          <p className="tabular mt-0.5 text-lg font-semibold">
            {nextDue
              ? `${nextDue.is_overdue ? "Venció " : "Antes del "}${formatDate(
                  nextDue.payment_deadline ?? nextDue.deadline,
                )}`
              : "Al corriente"}
          </p>
        </div>
      </div>

      <div role="tablist" className="flex flex-wrap gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${
              tab === t.id
                ? "border-accent font-medium text-ink"
                : "border-transparent text-ink-muted hover:text-ink"
            }`}
            onClick={() => selectTab(t.id)}
          >
            {t.label}
            {t.id === "pending_invoice" && counts && counts.pending_invoice > 0 && (
              <span className="ml-1.5 rounded-full bg-muted px-1.5 text-xs">{counts.pending_invoice}</span>
            )}
            {t.id === "declarations" && toAttend > 0 && (
              <span className="ml-1.5 rounded-full bg-muted px-1.5 text-xs">{toAttend}</span>
            )}
          </button>
        ))}
      </div>

      {openId !== null ? (
        opened ? (
          <PaymentDetail
            payment={opened}
            clientName={clientNames.get(opened.client_id) ?? "Cliente"}
            satInvoiceUrl={settings.data?.sat_invoice_url ?? null}
            banxicoUrl={settings.data?.banxico_fx_url ?? null}
            backLabel={TABS.find((t) => t.id === tab)?.label.toLowerCase() ?? "cobros"}
            onBack={closePayment}
          />
        ) : allPayments.isPending ? (
          <div className="card flex h-48 items-center justify-center">
            <Spinner className="size-7" />
          </div>
        ) : (
          <div className="grid place-items-center gap-3 rounded-xl border border-dashed border-line-strong p-10 text-center text-sm text-ink-muted">
            <span className="font-medium text-ink">Este cobro ya no existe</span>
            <button className="btn-secondary" onClick={closePayment}>
              <Icon name="arrowLeft" />
              Volver
            </button>
          </div>
        )
      ) : tab === "settings" ? (
        <SettingsTab clients={clients.data ?? []} />
      ) : tab === "declarations" ? (
        <DeclarationsTab payments={allPayments.data ?? []} onOpenPayment={openPayment} />
      ) : payments.isPending ? (
        <div className="card flex h-48 flex-col items-center justify-center gap-3 p-8 text-center text-sm text-ink-muted">
          <Spinner className="size-7" />
          Cargando cobros…
        </div>
      ) : payments.isError ? (
        <div className="card flex h-48 flex-col items-center justify-center gap-3 p-8 text-center text-sm text-ink-muted">
          No se pudieron cargar los cobros.
          <button className="btn-secondary" onClick={() => payments.refetch()}>
            Reintentar
          </button>
        </div>
      ) : payments.data.length === 0 ? (
        <div className="grid place-items-center gap-2 rounded-xl border border-dashed border-line-strong p-10 text-center text-sm text-ink-muted">
          <Icon name="receipt" className="size-6" />
          <span className="font-medium text-ink">
            {tab === "pending_invoice" ? "Nada por facturar" : "Sin cobros aquí"}
          </span>
          {tab === "pending_invoice" && (clients.data ?? []).length === 0 && (
            <span className="max-w-md">
              En Configuración da de alta a tu cliente y marca tu billetera (XTRM) como facturable: cada
              ingreso que registres ahí aparecerá aquí.
            </span>
          )}
        </div>
      ) : (
        <PaymentList payments={payments.data} clients={clientNames} onOpen={openPayment} />
      )}

      <Modal open={oldPayment} onClose={() => setOldPayment(false)} title="Pago anterior" size="xl">
        {oldPayment && (
          <OldPaymentForm clients={clients.data ?? []} onDone={() => setOldPayment(false)} />
        )}
      </Modal>
    </div>
  );
}
