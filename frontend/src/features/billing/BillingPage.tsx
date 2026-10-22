// Facturación de ingresos freelance (RESICO, FAC-01..FAC-14). Cada ingreso en
// una cuenta facturable (XTRM) aparece aquí como cobro por facturar (FAC-01);
// la ficha arma lo que se captura en el portal del SAT (FAC-11) y la factura
// (.zip) se sube al cobro (FAC-03/10). Los pagos que ya no están en la
// billetera se capturan a mano como "pagos anteriores" (FAC-01b).
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { hasBalance, useAccounts } from "../../api/accounts";
import {
  checkCfdi,
  downloadExport,
  useBillingClients,
  useBillingPayments,
  useBillingPeriods,
  useBillingSettings,
  useBillingSummary,
  useCreateOldPayment,
  useDeleteBillingClient,
  useDeleteInvoice,
  useDeletePayment,
  useInvoiceSheet,
  useSaveBillingClient,
  useSaveBillingSettings,
  useSaveInvoice,
  useSetInvoiceableAccount,
  useUpdatePayment,
  type BillingClientOut,
  type CfdiWarning,
  type InvoiceBody,
  type PaymentOut,
  type StoredFileOut,
} from "../../api/billing";
import Icon from "../../components/ui/Icon";
import Modal from "../../components/ui/Modal";
import ConfirmDialog from "../../components/ui/ConfirmDialog";
import Spinner from "../../components/ui/Spinner";
import { formatDate, todayISO } from "../../lib/dates";
import { formatMoney, isPositiveAmount, sanitizeDecimal } from "../../lib/money";
import DeclarationsTab from "./DeclarationsTab";
import {
  CopyRow,
  ErrorLine,
  FilePicker,
  SatLink,
  StatusBadge,
  errorText,
  monthLabel,
} from "./shared";

const CURRENCIES = ["USD", "MXN"];
const RATE_PATTERN = /^\d+(\.\d{1,4})?$/;
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


// FAC-11: lo que se captura en "Genera tu factura", con botones de copiar.
function InvoiceSheet({ paymentId }: { paymentId: string }) {
  const sheet = useInvoiceSheet(paymentId);
  if (sheet.isPending) return <Spinner className="size-5" />;
  if (sheet.isError) return <ErrorLine error={errorText(sheet.error)} />;
  const { payment: p, client: c, description, missing } = sheet.data;
  return (
    <div className="space-y-3">
      {missing.length > 0 && (
        <p className="rounded-lg bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-100">
          Falta capturar{" "}
          {missing
            .map((m) => (m === "work_period" ? "el periodo trabajado" : "el tipo de cambio de Banxico"))
            .join(" y ")}{" "}
          en los datos del cobro.
        </p>
      )}
      <div className="grid gap-x-6 sm:grid-cols-2">
        <div className="divide-y divide-line">
          <CopyRow label="Valor unitario" value={p.amount} />
          <CopyRow label="Moneda" value={p.currency === "USD" ? "Dólar americano" : "Peso mexicano"} />
          <CopyRow label="Tipo de cambio (para solventar obligaciones)" value={p.fiscal_fx_rate} />
          <CopyRow label="Producto o servicio" value={c.product_code} />
          <CopyRow label="Unidad de medida" value={c.unit_code} />
        </div>
        <div className="divide-y divide-line">
          <CopyRow label="RFC del cliente" value={c.tax_id} />
          <CopyRow label="Nombre o razón social" value={c.name} />
          <CopyRow label="Identificación fiscal extranjera" value={c.foreign_tax_id} />
          <CopyRow label="País de residencia fiscal" value={c.country} />
          <CopyRow label="Régimen fiscal" value={c.fiscal_regime} />
          <CopyRow label="Uso de la factura" value={c.cfdi_use} />
          <CopyRow label="Código postal" value={c.postal_code} />
        </div>
      </div>
      <div className="rounded-lg border border-line bg-surface px-3">
        <CopyRow label="Descripción del concepto" value={description} />
      </div>
      <details className="text-sm text-ink-muted">
        <summary className="cursor-pointer">Revisión antes de sellar</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>Forma de pago: transferencia electrónica de fondos; método: una sola exhibición.</li>
          <li>IVA: Tasa 0% (nunca 16% ni Exento); sin retenciones.</li>
          <li>Subtotal = total = {formatMoney(p.amount, p.currency)}; impuestos trasladados 0.00.</li>
          <li>Tipo de cambio y fecha de la descripción correctos en la vista previa.</li>
        </ul>
      </details>
      <SatLink url={sheet.data.sat_invoice_url}>Abrir portal de facturación</SatLink>
    </div>
  );
}

const CFDI_WARNINGS: Record<CfdiWarning, string> = {
  total: "El total del CFDI no coincide con el monto del cobro.",
  currency: "La moneda del CFDI no coincide con la del cobro.",
  fx_rate: "El tipo de cambio del CFDI no coincide con el de Banxico capturado en el cobro.",
  issue_month: "Se emitió en otro mes que el cobro: el SAT la precargará en ese otro mes.",
  iva: "El IVA no está a tasa 0%: una exportación de servicios va al 0%.",
  receiver: "El RFC del receptor no coincide con el del cliente.",
};

// FAC-03: alta o reemplazo de la factura de un cobro.
function InvoiceForm({ payment }: { payment: PaymentOut }) {
  const save = useSaveInvoice();
  const remove = useDeleteInvoice();
  const inv = payment.invoice;
  // GLO-09: quitar la factura se confirma.
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [file, setFile] = useState<StoredFileOut | null>(inv?.file ?? null);
  const [cfdiUuid, setCfdiUuid] = useState(inv?.cfdi_uuid ?? "");
  const [issueDate, setIssueDate] = useState(inv?.issue_date ?? payment.payment_date);
  const [total, setTotal] = useState(inv?.total ?? payment.amount);
  const [currency, setCurrency] = useState(inv?.currency ?? payment.currency);
  const [fxRate, setFxRate] = useState(inv?.fx_rate ?? payment.fiscal_fx_rate ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [warnings, setWarnings] = useState<CfdiWarning[]>([]);
  const [cfdiNote, setCfdiNote] = useState<string | null>(null);

  // FAC-15: al subir el .zip/XML se lee el CFDI y se precarga la factura.
  async function handleUploaded(uploaded: StoredFileOut) {
    setFile(uploaded);
    setWarnings([]);
    setCfdiNote(null);
    if (uploaded.mime !== "application/zip" && uploaded.mime !== "application/xml") return;
    try {
      const cfdi = await checkCfdi(payment.id, uploaded.id);
      if (cfdi.uuid) setCfdiUuid(cfdi.uuid);
      if (cfdi.issue_date) setIssueDate(cfdi.issue_date);
      if (cfdi.total) setTotal(cfdi.total);
      if (cfdi.currency === "USD" || cfdi.currency === "MXN") setCurrency(cfdi.currency);
      if (cfdi.fx_rate) setFxRate(cfdi.fx_rate);
      setWarnings(cfdi.warnings);
      setCfdiNote("Datos leídos del CFDI; revísalos y guarda.");
    } catch (err) {
      setCfdiNote(errorText(err));
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    if (!isPositiveAmount(total)) return setError("El total de la factura debe ser mayor a 0.");
    if (cfdiUuid && !CFDI_UUID_PATTERN.test(cfdiUuid.trim()))
      return setError("El folio fiscal tiene el formato XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX.");
    if (currency !== "MXN" && fxRate && !RATE_PATTERN.test(fxRate))
      return setError("El tipo de cambio admite hasta 4 decimales.");
    const body: InvoiceBody = {
      cfdi_uuid: cfdiUuid.trim() || null,
      issue_date: issueDate,
      total,
      currency,
      fx_rate: currency === "MXN" ? null : fxRate || null,
      file_id: file?.id ?? null,
    };
    try {
      await save.mutateAsync({ paymentId: payment.id, ...body });
      setSaved(true);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div className="col-span-2 md:col-span-4">
        <FilePicker
          label="Factura (.zip con XML y PDF, o el XML/PDF)"
          accept=".zip,.xml,.pdf"
          file={file}
          onUploaded={handleUploaded}
        />
        {cfdiNote && <p className="mt-1 text-xs text-ink-muted">{cfdiNote}</p>}
        {warnings.length > 0 && (
          <ul className="mt-2 list-disc space-y-0.5 rounded-lg bg-red-500/10 py-2 pl-7 pr-3 text-sm text-red-800 dark:text-red-200">
            {warnings.map((w) => (
              <li key={w}>{CFDI_WARNINGS[w]}</li>
            ))}
          </ul>
        )}
      </div>
      <div className="col-span-2">
        <label className="label" htmlFor="inv-uuid">Folio fiscal (UUID)</label>
        <input
          id="inv-uuid"
          className="input font-mono text-xs"
          placeholder="Opcional"
          value={cfdiUuid}
          onChange={(e) => setCfdiUuid(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="inv-date">Fecha de emisión</label>
        <input
          id="inv-date"
          type="date"
          className="input"
          required
          value={issueDate}
          onChange={(e) => setIssueDate(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="inv-total">Total</label>
        <input
          id="inv-total"
          className="input"
          inputMode="decimal"
          required
          value={total}
          onChange={(e) => setTotal(sanitizeDecimal(e.target.value))}
        />
      </div>
      <div>
        <label className="label" htmlFor="inv-currency">Moneda</label>
        <select
          id="inv-currency"
          className="input"
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
        >
          {CURRENCIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </div>
      {currency !== "MXN" && (
        <div>
          <label className="label" htmlFor="inv-rate">Tipo de cambio</label>
          <input
            id="inv-rate"
            className="input"
            inputMode="decimal"
            placeholder="0.0000"
            value={fxRate}
            onChange={(e) => setFxRate(sanitizeDecimal(e.target.value, 4))}
          />
        </div>
      )}
      {issueDate.slice(0, 7) !== payment.payment_date.slice(0, 7) && (
        <p className="col-span-2 text-xs text-amber-800 md:col-span-4 dark:text-amber-200">
          Emitida en otro mes que el cobro: el SAT la precargará en {monthLabel(`${issueDate.slice(0, 7)}-01`)},
          pero se declara en {monthLabel(payment.period)} (FAC-02).
        </p>
      )}
      <div className="col-span-2 flex flex-wrap items-center justify-end gap-2 md:col-span-4">
        <ErrorLine error={error} />
        {saved && <span className="text-sm text-emerald-700 dark:text-emerald-300">Factura guardada</span>}
        {inv && (
          <button
            type="button"
            className="btn-danger"
            disabled={remove.isPending}
            onClick={() => setConfirmingRemove(true)}
          >
            Quitar factura
          </button>
        )}
        <button className="btn-primary" disabled={save.isPending}>
          {inv ? "Guardar factura" : "Marcar como facturado"}
        </button>
      </div>
      <ConfirmDialog
        open={confirmingRemove}
        title="Quitar factura"
        confirmLabel="Sí, quitar"
        pending={remove.isPending}
        onClose={() => setConfirmingRemove(false)}
        onConfirm={() => {
          setConfirmingRemove(false);
          void remove
            .mutateAsync(payment.id)
            .then(() => setSaved(false))
            .catch((err) => setError(errorText(err)));
        }}
      >
        <p>
          ¿Quitar la factura de este cobro? Se borran sus datos (UUID, fecha y total) y el cobro
          vuelve a quedar pendiente de facturar.
        </p>
      </ConfirmDialog>
    </form>
  );
}

// Datos del cobro: tipo de cambio fiscal (FAC-06), periodo trabajado (FAC-11),
// captura del wallet y exclusión (FAC-04/05).
function PaymentDataForm({ payment, onDeleted }: { payment: PaymentOut; onDeleted: () => void }) {
  const update = useUpdatePayment();
  const remove = useDeletePayment();
  // GLO-09: borrar un pago anterior se confirma.
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [rate, setRate] = useState(payment.fiscal_fx_rate ?? "");
  const [workStart, setWorkStart] = useState(payment.work_period_start ?? "");
  const [workEnd, setWorkEnd] = useState(payment.work_period_end ?? "");
  const [notes, setNotes] = useState(payment.notes ?? "");
  const [capture, setCapture] = useState<StoredFileOut | null>(payment.capture_file);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const isUsd = payment.currency !== "MXN";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    if (isUsd && rate && !RATE_PATTERN.test(rate))
      return setError("El tipo de cambio admite hasta 4 decimales.");
    if (Boolean(workStart) !== Boolean(workEnd))
      return setError("Captura el inicio y el fin del periodo trabajado.");
    if (workStart && workEnd && workStart > workEnd)
      return setError("El periodo trabajado empieza después de terminar.");
    try {
      await update.mutateAsync({
        id: payment.id,
        fiscal_fx_rate: isUsd ? rate || null : null,
        work_period_start: workStart || null,
        work_period_end: workEnd || null,
        notes: notes.trim() || null,
        capture_file_id: capture?.id ?? null,
      });
      setSaved(true);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {isUsd && (
        <div className="col-span-2">
          <label className="label" htmlFor="p-rate">
            Tipo de cambio Banxico del {formatDate(payment.payment_date)}
          </label>
          <input
            id="p-rate"
            className="input"
            inputMode="decimal"
            placeholder="Para solventar obligaciones, p. ej. 18.0692"
            value={rate}
            onChange={(e) => setRate(sanitizeDecimal(e.target.value, 4))}
          />
          {payment.mxn && (
            <p className="mt-1 text-xs text-ink-muted">≈ {formatMoney(payment.mxn, "MXN")} a declarar</p>
          )}
        </div>
      )}
      <div>
        <label className="label" htmlFor="p-ws">Periodo trabajado: inicio</label>
        <input
          id="p-ws"
          type="date"
          className="input"
          value={workStart}
          onChange={(e) => setWorkStart(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="p-we">Fin</label>
        <input
          id="p-we"
          type="date"
          className="input"
          value={workEnd}
          onChange={(e) => setWorkEnd(e.target.value)}
        />
      </div>
      <div className="col-span-2 md:col-span-4">
        <FilePicker
          label="Captura del movimiento en el wallet (opcional)"
          accept="image/png,image/jpeg,.pdf"
          file={capture}
          onUploaded={setCapture}
        />
      </div>
      <div className="col-span-2 md:col-span-4">
        <label className="label" htmlFor="p-notes">Notas</label>
        <textarea
          id="p-notes"
          className="input"
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>
      <div className="col-span-2 flex flex-wrap items-center justify-end gap-2 md:col-span-4">
        <ErrorLine error={error} />
        {saved && <span className="text-sm text-emerald-700 dark:text-emerald-300">Guardado</span>}
        {payment.transaction_id === null && payment.invoice === null && (
          <button
            type="button"
            className="btn-danger"
            disabled={remove.isPending}
            onClick={() => setConfirmingDelete(true)}
          >
            Borrar pago anterior
          </button>
        )}
        {payment.transaction_id !== null && payment.invoice === null && (
          <button
            type="button"
            className="btn-secondary"
            disabled={update.isPending}
            title="Un ingreso que no se factura (p. ej. un reembolso)"
            onClick={() =>
              update
                .mutateAsync({ id: payment.id, is_excluded: !payment.is_excluded })
                .catch((err) => setError(errorText(err)))
            }
          >
            {payment.is_excluded ? "Volver a facturable" : "Marcar no facturable"}
          </button>
        )}
        <button className="btn-primary" disabled={update.isPending}>
          Guardar datos
        </button>
      </div>

      <ConfirmDialog
        open={confirmingDelete}
        title="Borrar pago anterior"
        confirmLabel="Eliminar"
        pending={remove.isPending}
        onClose={() => setConfirmingDelete(false)}
        onConfirm={() => {
          setConfirmingDelete(false);
          void remove
            .mutateAsync(payment.id)
            .then(onDeleted)
            .catch((err) => setError(errorText(err)));
        }}
      >
        <p>
          ¿Borrar este pago anterior de {formatMoney(payment.amount, payment.currency)}? Se elimina
          de forma permanente.
        </p>
      </ConfirmDialog>
    </form>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3 border-t border-line pt-4 first:border-t-0 first:pt-0">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function PaymentDialog({ payment, onClose }: { payment: PaymentOut; onClose: () => void }) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="tabular text-xl font-semibold">{formatMoney(payment.amount, payment.currency)}</p>
          <p className="text-sm text-ink-muted">
            Cobrado el {formatDate(payment.payment_date)} · se declara en {monthLabel(payment.period)}
            {payment.transaction_id === null && " · pago anterior"}
          </p>
        </div>
        <StatusBadge payment={payment} />
      </div>
      {payment.status !== "excluded" && (
        <Section title="Ficha para el portal del SAT">
          <InvoiceSheet paymentId={payment.id} />
        </Section>
      )}
      <Section title="Datos del cobro">
        <PaymentDataForm key={payment.id} payment={payment} onDeleted={onClose} />
      </Section>
      {payment.status !== "excluded" && (
        <Section title="Factura">
          {/* Sin factura, la tasa recién guardada en "Datos del cobro" se vuelve a precargar. */}
          <InvoiceForm
            key={`${payment.id}-${payment.invoice?.id ?? `new-${payment.fiscal_fx_rate ?? ""}`}`}
            payment={payment}
          />

        </Section>
      )}
    </div>
  );
}

// FAC-01b: un cobro que ya no está en la billetera; puede venir ya facturado.
function OldPaymentForm({ clients, onDone }: { clients: BillingClientOut[]; onDone: () => void }) {
  const create = useCreateOldPayment();
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
      onDone();
    } catch (err) {
      setError(errorText(err));
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
          <input
            id="o-rate"
            className="input"
            inputMode="decimal"
            placeholder="Para solventar obligaciones"
            value={rate}
            onChange={(e) => setRate(sanitizeDecimal(e.target.value, 4))}
          />
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
                    <div className="text-right">
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
  const save = useSaveBillingClient();
  const remove = useDeleteBillingClient();
  // GLO-09: borrar el cliente se confirma.
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const initial = client ?? { name: "", foreign_tax_id: "", country: "", postal_code: "", ...CLIENT_DEFAULTS };
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
  });
  const [error, setError] = useState<string | null>(null);
  const field = (key: keyof typeof form, label: string, wide = false, maxLength = 60) => (
    <div className={wide ? "col-span-2" : ""}>
      <label className="label" htmlFor={`cl-${key}`}>{label}</label>
      <input
        id={`cl-${key}`}
        className="input"
        maxLength={maxLength}
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
      />
    </div>
  );

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.name.trim()) return setError("El nombre del cliente es obligatorio.");
    const body = Object.fromEntries(
      Object.entries(form).map(([k, v]) => [k, v.trim() || null]),
    ) as Record<keyof typeof form, string | null>;
    try {
      await save.mutateAsync({ id: client?.id, ...body, name: form.name.trim() });
      onDone();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {field("name", "Nombre o razón social", true, 120)}
      {field("tax_id", "RFC", false, 13)}
      {field("foreign_tax_id", "ID fiscal extranjero", false, 40)}
      {field("country", "País de residencia fiscal")}
      {field("fiscal_regime", "Régimen fiscal")}
      {field("cfdi_use", "Uso de la factura")}
      {field("postal_code", "Código postal", false, 10)}
      {field("product_code", "Producto o servicio")}
      {field("unit_code", "Unidad de medida")}
      <div className="col-span-2 md:col-span-4">
        <label className="label" htmlFor="cl-template">Plantilla de la descripción</label>
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
          <code>{"{fecha_pago}"}</code> = "2 de octubre de 2026"
        </p>
      </div>
      <div className="col-span-2 flex flex-wrap items-center justify-end gap-2 md:col-span-4">
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
              .then(onDone)
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

function SettingsTab({ clients }: { clients: BillingClientOut[] }) {
  const settings = useBillingSettings();
  const saveSettings = useSaveBillingSettings();
  const accounts = useAccounts();
  const setInvoiceable = useSetInvoiceableAccount();
  const [urls, setUrls] = useState<Record<string, string> | null>(null);
  const [extraDays, setExtraDays] = useState<number | null>(null);
  const [clientModal, setClientModal] = useState<BillingClientOut | "new" | null>(null);
  const [importSince, setImportSince] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const current = urls ?? {
    sat_invoice_url: settings.data?.sat_invoice_url ?? "",
    sat_filing_url: settings.data?.sat_filing_url ?? "",
    sat_payment_url: settings.data?.sat_payment_url ?? "",
  };
  const balanceAccounts = (accounts.data ?? []).filter((a) => a.is_active && hasBalance(a.behavior));

  async function saveUrls(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    if (Object.values(current).some((u) => u && !u.toLowerCase().startsWith("https://")))
      return setError("Las URLs del SAT deben empezar con https://.");
    try {
      await saveSettings.mutateAsync({
        ...current,
        rfc_extra_days: extraDays ?? settings.data?.rfc_extra_days ?? 0,
      });
      setUrls(null);
      setExtraDays(null);
      setMessage("Configuración del SAT guardada.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function changeAccount(accountId: string, clientId: string) {
    setError(null);
    setMessage(null);
    try {
      const res = await setInvoiceable.mutateAsync({
        accountId,
        client_id: clientId || null,
        import_since: clientId ? importSince[accountId] || null : null,
      });
      if (res.imported > 0) setMessage(`Se importaron ${res.imported} ingresos como cobros por facturar.`);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <div className="space-y-4">
      {(message || error) && (
        <p className={`text-sm ${error ? "text-red-600 dark:text-red-400" : "text-emerald-700 dark:text-emerald-300"}`}>
          {error ?? message}
        </p>
      )}
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

      <section className="card space-y-3 p-4 sm:p-5">
        <div>
          <h2 className="font-semibold">Cuentas facturables</h2>
          <p className="text-sm text-ink-muted">
            Cada ingreso que registres en una cuenta facturable aparece como cobro por facturar. Para
            traer ingresos ya registrados, elige la fecha desde la que se importan antes de asignar el
            cliente.
          </p>
        </div>
        <ul className="divide-y divide-line">
          {balanceAccounts.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span className="text-sm font-medium">
                {a.name} <span className="text-xs text-ink-muted">{a.currency}</span>
              </span>
              <span className="flex flex-wrap items-center gap-2">
                {!a.invoice_client_id && (
                  <input
                    type="date"
                    className="input w-auto"
                    aria-label={`Importar ingresos de ${a.name} desde`}
                    title="Importar ingresos existentes desde (opcional)"
                    value={importSince[a.id] ?? ""}
                    onChange={(e) => setImportSince({ ...importSince, [a.id]: e.target.value })}
                  />
                )}
                <select
                  className="input w-auto"
                  aria-label={`Cliente de ${a.name}`}
                  value={a.invoice_client_id ?? ""}
                  disabled={setInvoiceable.isPending}
                  onChange={(e) => changeAccount(a.id, e.target.value)}
                >
                  <option value="">No facturable</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>
                      Facturable · {c.name}
                    </option>
                  ))}
                </select>
              </span>
            </li>
          ))}
        </ul>
      </section>

      <form onSubmit={saveUrls} className="card space-y-3 p-4 sm:p-5">
        <h2 className="font-semibold">SAT</h2>
        <div>
          <label className="label" htmlFor="rfc-digit">Sexto dígito de tu RFC</label>
          <select
            id="rfc-digit"
            className="input"
            value={extraDays ?? settings.data?.rfc_extra_days ?? 0}
            onChange={(e) => setExtraDays(Number(e.target.value))}
          >
            <option value={0}>Sin días extra (vence el 17)</option>
            <option value={1}>1 o 2 · un día hábil extra</option>
            <option value={2}>3 o 4 · dos días hábiles extra</option>
            <option value={3}>5 o 6 · tres días hábiles extra</option>
            <option value={4}>7 o 8 · cuatro días hábiles extra</option>
            <option value={5}>9 o 0 · cinco días hábiles extra</option>
          </select>
          <p className="mt-1 text-xs text-ink-muted">
            La fecha límite es el 17 del mes siguiente (o el siguiente día hábil) más estos días.
          </p>
        </div>
        {(
          [
            ["sat_invoice_url", "Factura electrónica (Genera tu factura)"],
            ["sat_filing_url", "Declaración provisional mensual"],
            ["sat_payment_url", "Pago (línea de captura)"],
          ] as const
        ).map(([key, label]) => (
          <div key={key}>
            <label className="label" htmlFor={`url-${key}`}>{label}</label>
            <input
              id={`url-${key}`}
              type="url"
              className="input"
              placeholder="https://"
              maxLength={500}
              value={current[key]}
              onChange={(e) => setUrls({ ...current, [key]: e.target.value })}
            />
          </div>
        ))}
        <div className="flex justify-end">
          <button className="btn-primary" disabled={saveSettings.isPending}>
            Guardar
          </button>
        </div>
      </form>

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
          } catch (err) {
            setError(errorText(err));
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

export default function BillingPage() {
  const [tab, setTab] = useState<Tab>("pending_invoice");
  const payments = useBillingPayments(tab === "pending_invoice" ? "pending_invoice" : undefined);
  const periods = useBillingPeriods();
  const summary = useBillingSummary();
  const clients = useBillingClients();
  const settings = useBillingSettings();
  const [openId, setOpenId] = useState<string | null>(null);
  const [oldPayment, setOldPayment] = useState(false);
  const clientNames = useMemo(
    () => new Map((clients.data ?? []).map((c) => [c.id, c.name])),
    [clients.data],
  );
  // El cobro abierto se relee de la lista para reflejar cada guardado.
  const allPayments = useBillingPayments();
  const opened = (allPayments.data ?? []).find((p) => p.id === openId) ?? null;
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
            onClick={() => setTab(t.id)}
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

      {tab === "settings" ? (
        <SettingsTab clients={clients.data ?? []} />
      ) : tab === "declarations" ? (
        <DeclarationsTab payments={allPayments.data ?? []} onOpenPayment={(p) => setOpenId(p.id)} />
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
        <PaymentList payments={payments.data} clients={clientNames} onOpen={(p) => setOpenId(p.id)} />
      )}

      <Modal open={opened !== null} onClose={() => setOpenId(null)} title="Cobro" size="xl">
        {opened && <PaymentDialog payment={opened} onClose={() => setOpenId(null)} />}
      </Modal>
      <Modal open={oldPayment} onClose={() => setOldPayment(false)} title="Pago anterior" size="xl">
        {oldPayment && (
          <OldPaymentForm clients={clients.data ?? []} onDone={() => setOldPayment(false)} />
        )}
      </Modal>
    </div>
  );
}
