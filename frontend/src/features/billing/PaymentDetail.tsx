// Vista de un cobro (FAC-01..FAC-15): reemplaza la lista de su pestaña y
// sigue el orden del trabajo: 1) datos del cobro (tipo de cambio fiscal,
// periodo trabajado, recibo), 2) ficha para "Genera tu factura" acomodada
// como el portal del SAT (FAC-11) y 3) la factura (FAC-03/15).
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useBlocker } from "react-router-dom";
import {
  checkCfdi,
  useDeleteInvoice,
  useDeletePayment,
  useInvoiceSheet,
  useSaveInvoice,
  useUpdatePayment,
  type CfdiWarning,
  type InvoiceBody,
  type PaymentOut,
  type StoredFileOut,
} from "../../api/billing";
import ConfirmDialog from "../../components/ui/ConfirmDialog";
import Icon from "../../components/ui/Icon";
import Spinner from "../../components/ui/Spinner";
import { useToast } from "../../components/ui/Toast";
import { formatDate } from "../../lib/dates";
import { formatMoney, isPositiveAmount, sanitizeDecimal } from "../../lib/money";
import {
  BanxicoButton,
  ErrorLine,
  FilePicker,
  PortalField,
  SatLink,
  StatusBadge,
  errorText,
  monthLabel,
} from "./shared";

const CURRENCIES = ["USD", "MXN"];
const RATE_PATTERN = /^\d+(\.\d{1,4})?$/;
const CFDI_UUID_PATTERN =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const CURRENCY_NAMES: Record<string, string> = { USD: "Dólar americano", MXN: "Peso mexicano" };

function PortalBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-line p-3 sm:p-4">
      <h4 className="mb-3 text-sm font-semibold">{title}</h4>
      {children}
    </div>
  );
}

// FAC-11: lo que se captura en "Genera tu factura", con las etiquetas y el
// acomodo del portal (Datos generales → Datos del cliente → Producto y Servicio).
function InvoiceSheet({ paymentId }: { paymentId: string }) {
  const sheet = useInvoiceSheet(paymentId);
  if (sheet.isPending) return <Spinner className="size-5" />;
  if (sheet.isError) return <ErrorLine error={errorText(sheet.error)} />;
  const { payment: p, client: c, description, missing } = sheet.data;
  const isUsd = p.currency !== "MXN";
  return (
    <div className="space-y-3">
      {missing.length > 0 && (
        <p className="rounded-lg bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-100">
          Falta capturar{" "}
          {missing
            .map((m) => (m === "work_period" ? "el periodo trabajado" : "el tipo de cambio de Banxico"))
            .join(" y ")}{" "}
          en el paso 1.
        </p>
      )}
      <PortalBlock title="Datos generales">
        <div className="grid gap-3 sm:grid-cols-3">
          <PortalField label="Moneda*" value={CURRENCY_NAMES[p.currency] ?? p.currency} />
          <PortalField
            label="Tipo de Cambio"
            value={isUsd ? p.fiscal_fx_rate : null}
            hint={
              !isUsd ? "No aplica en pesos" : p.fiscal_fx_rate ? undefined : "Falta el tipo de cambio de Banxico (paso 1)"
            }
          />
        </div>
      </PortalBlock>
      <PortalBlock title="Datos del cliente">
        {/* Tres columnas como en el portal; en móvil se apilan en ese orden. */}
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-3">
            <PortalField label="Cliente Frecuente*" value={c.tax_id} hint="RFC genérico del extranjero" />
            <PortalField label="País de Residencia Fiscal" value={c.country} />
          </div>
          <div className="space-y-3">
            <PortalField label="Nombre o Razón Social*" value={c.name} />
            <PortalField label="Código Postal*" value={c.postal_code} />
            <PortalField label="Régimen Fiscal*" value={c.fiscal_regime} />
            <PortalField label="Clave de Identidad Fiscal*" value={c.foreign_tax_id} />
          </div>
          <div className="space-y-3">
            <PortalField label="Uso de la Factura*" value={c.cfdi_use} />
          </div>
        </div>
      </PortalBlock>
      <PortalBlock title="Producto y Servicio">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <PortalField label="Descripción Detallada*" value={description} />
          <PortalField label="Producto o Servicio*" value={c.product_code} />
          <PortalField label="Unidad de Medida*" value={c.unit_code} />
          <div className="hidden lg:block" />
          <PortalField label="Cantidad*" value="1" />
          <PortalField label="Valor Unitario*" value={p.amount} />
          <PortalField label="Importe*" value={p.amount} hint="Lo calcula el portal" />
          <PortalField label="Descuento" />
          <PortalField
            label="Objeto de Impuesto*"
            value="Sí objeto de impuesto"
            hint="Luego agrega el traslado de IVA a tasa 0%"
          />
          <PortalField label="Número de Identificación" />
        </div>
      </PortalBlock>
      <details className="text-sm text-ink-muted">
        <summary className="cursor-pointer">Revisión antes de sellar</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>Forma de pago: transferencia electrónica de fondos; método: una sola exhibición.</li>
          <li>IVA: Tasa 0% (nunca 16% ni Exento); sin retenciones.</li>
          <li>Subtotal = total = {formatMoney(p.amount, p.currency)}; impuestos trasladados 0.00.</li>
          <li>Tipo de cambio y fecha de la descripción correctos en la vista previa.</li>
        </ul>
      </details>
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

/** GLO-10: avisa al padre si el formulario tiene cambios sin guardar. */
function useReportDirty(dirty: boolean, onDirtyChange: (dirty: boolean) => void) {
  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(
    () => () => {
      onDirtyChange(false);
    },
    [onDirtyChange],
  );
}

// FAC-03: alta o reemplazo de la factura de un cobro.
function InvoiceForm({
  payment,
  onDirtyChange,
}: {
  payment: PaymentOut;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const toast = useToast();
  const save = useSaveInvoice();
  const remove = useDeleteInvoice();
  const inv = payment.invoice;
  const initial = {
    fileId: inv?.file?.id ?? null,
    cfdiUuid: inv?.cfdi_uuid ?? "",
    issueDate: inv?.issue_date ?? payment.payment_date,
    total: inv?.total ?? payment.amount,
    currency: inv?.currency ?? payment.currency,
    fxRate: inv?.fx_rate ?? payment.fiscal_fx_rate ?? "",
  };
  // GLO-09: quitar la factura se confirma.
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  // GLO-10: guardar con diferencias del CFDI se confirma.
  const [confirmingWarnings, setConfirmingWarnings] = useState(false);
  const [file, setFile] = useState<StoredFileOut | null>(inv?.file ?? null);
  const [cfdiUuid, setCfdiUuid] = useState(initial.cfdiUuid);
  const [issueDate, setIssueDate] = useState(initial.issueDate);
  const [total, setTotal] = useState(initial.total);
  const [currency, setCurrency] = useState(initial.currency);
  const [fxRate, setFxRate] = useState(initial.fxRate);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<CfdiWarning[]>([]);
  const [cfdiNote, setCfdiNote] = useState<string | null>(null);

  useReportDirty(
    (file?.id ?? null) !== initial.fileId ||
      cfdiUuid !== initial.cfdiUuid ||
      issueDate !== initial.issueDate ||
      total !== initial.total ||
      currency !== initial.currency ||
      fxRate !== initial.fxRate,
    onDirtyChange,
  );

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

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!isPositiveAmount(total)) return setError("El total de la factura debe ser mayor a 0.");
    if (cfdiUuid && !CFDI_UUID_PATTERN.test(cfdiUuid.trim()))
      return setError("El folio fiscal tiene el formato XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX.");
    if (currency !== "MXN" && fxRate && !RATE_PATTERN.test(fxRate))
      return setError("El tipo de cambio admite hasta 4 decimales.");
    if (warnings.length > 0) return setConfirmingWarnings(true);
    void submit();
  }

  async function submit() {
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
      setWarnings([]);
      setCfdiNote(null);
      toast.success(inv ? "Factura actualizada." : "Factura guardada: el cobro quedó como facturado.");
    } catch (err) {
      setError(errorText(err));
      toast.error(`No se guardó la factura: ${errorText(err)}`);
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
          {save.isPending && <Spinner className="size-4" />}
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
            .then(() => toast.success("Factura quitada: el cobro vuelve a estar por facturar."))
            .catch((err) => setError(errorText(err)));
        }}
      >
        <p>
          ¿Quitar la factura de este cobro? Se borran sus datos (UUID, fecha y total) y el cobro
          vuelve a quedar pendiente de facturar.
        </p>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirmingWarnings}
        title="La factura no coincide con el cobro"
        confirmLabel="Guardar de todos modos"
        tone="primary"
        pending={save.isPending}
        onClose={() => setConfirmingWarnings(false)}
        onConfirm={() => {
          setConfirmingWarnings(false);
          void submit();
        }}
      >
        <p>Al leer el CFDI se encontraron estas diferencias:</p>
        <ul className="list-disc space-y-0.5 pl-5">
          {warnings.map((w) => (
            <li key={w}>{CFDI_WARNINGS[w]}</li>
          ))}
        </ul>
        <p>Si la factura está mal, cancélala en el portal y sube la correcta en lugar de guardarla.</p>
      </ConfirmDialog>
    </form>
  );
}

// Datos del cobro: tipo de cambio fiscal (FAC-06), periodo trabajado (FAC-11),
// recibo/captura del wallet y exclusión (FAC-04/05).
function PaymentDataForm({
  payment,
  banxicoUrl,
  onDeleted,
  onDirtyChange,
}: {
  payment: PaymentOut;
  banxicoUrl: string | null;
  onDeleted: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const toast = useToast();
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
  const isUsd = payment.currency !== "MXN";

  useReportDirty(
    rate !== (payment.fiscal_fx_rate ?? "") ||
      workStart !== (payment.work_period_start ?? "") ||
      workEnd !== (payment.work_period_end ?? "") ||
      notes.trim() !== (payment.notes ?? "") ||
      (capture?.id ?? null) !== (payment.capture_file?.id ?? null),
    onDirtyChange,
  );

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
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
      toast.success("Datos del cobro guardados.");
    } catch (err) {
      setError(errorText(err));
      toast.error(`No se guardaron los datos del cobro: ${errorText(err)}`);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {isUsd && (
        <div className="col-span-2">
          <label className="label" htmlFor="p-rate">
            Tipo de cambio Banxico del {formatDate(payment.payment_date)}
          </label>
          <div className="flex gap-2">
            <input
              id="p-rate"
              className="input"
              inputMode="decimal"
              placeholder="Para solventar obligaciones, p. ej. 18.0692"
              value={rate}
              onChange={(e) => setRate(sanitizeDecimal(e.target.value, 4))}
            />
            <BanxicoButton url={banxicoUrl} />
          </div>
          <p className="mt-1 text-xs text-ink-muted">
            Es el «Tipo de Cambio» de la factura.
            {payment.mxn && ` ≈ ${formatMoney(payment.mxn, "MXN")} a declarar.`}
          </p>
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
          label="Recibo de pago o captura del movimiento en el wallet (opcional)"
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
                .then(() =>
                  toast.success(
                    payment.is_excluded
                      ? "El cobro vuelve a ser facturable."
                      : "Cobro marcado como no facturable.",
                  ),
                )
                .catch((err) => setError(errorText(err)))
            }
          >
            {payment.is_excluded ? "Volver a facturable" : "Marcar no facturable"}
          </button>
        )}
        <button className="btn-primary" disabled={update.isPending}>
          {update.isPending && <Spinner className="size-4" />}
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
            .then(() => {
              toast.success("Pago anterior eliminado.");
              onDeleted();
            })
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

function Step({
  n,
  title,
  subtitle,
  done,
  action,
  children,
}: {
  n: number;
  title: string;
  subtitle: string;
  done: boolean;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className={`grid size-7 shrink-0 place-items-center rounded-full text-sm font-semibold ${
              done ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" : "bg-muted text-ink"
            }`}
            aria-label={done ? "Completo" : `Paso ${n}`}
          >
            {done ? <Icon name="check" className="size-4" /> : n}
          </span>
          <div className="min-w-0">
            <h3 className="font-semibold">{title}</h3>
            <p className="text-sm text-ink-muted">{subtitle}</p>
          </div>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

const SECTION_NAMES = { data: "Datos del cobro", invoice: "Factura" } as const;
type Section = keyof typeof SECTION_NAMES;

export default function PaymentDetail({
  payment,
  clientName,
  satInvoiceUrl,
  banxicoUrl,
  backLabel,
  onBack,
}: {
  payment: PaymentOut;
  clientName: string;
  satInvoiceUrl: string | null;
  banxicoUrl: string | null;
  backLabel: string;
  onBack: () => void;
}) {
  const [dirty, setDirty] = useState<Record<Section, boolean>>({ data: false, invoice: false });
  const setDataDirty = useCallback((d: boolean) => setDirty((s) => ({ ...s, data: d })), []);
  const setInvoiceDirty = useCallback((d: boolean) => setDirty((s) => ({ ...s, invoice: d })), []);
  const dirtySections = (Object.keys(dirty) as Section[]).filter((k) => dirty[k]);
  const isDirty = dirtySections.length > 0;

  // GLO-10: salir con cambios sin guardar (Volver, otra pestaña, el menú o el
  // botón atrás del navegador) se confirma; cerrar la pestaña lo avisa el navegador.
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      isDirty &&
      (currentLocation.pathname !== nextLocation.pathname ||
        currentLocation.search !== nextLocation.search),
  );
  useEffect(() => {
    if (!isDirty) return;
    const onUnload = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, [isDirty]);

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [payment.id]);

  const isUsd = payment.currency !== "MXN";
  const dataDone =
    (!isUsd || payment.fiscal_fx_rate !== null) &&
    payment.work_period_start !== null &&
    payment.work_period_end !== null;
  const excluded = payment.status === "excluded";

  return (
    <div className="space-y-4">
      <button type="button" className="btn-ghost -ml-2" onClick={onBack}>
        <Icon name="arrowLeft" />
        Volver a {backLabel}
      </button>

      <section className="card flex flex-wrap items-start justify-between gap-4 p-4 sm:p-5">
        <div className="min-w-0 space-y-1">
          <p className="text-sm text-ink-muted">{clientName}</p>
          <p className="tabular text-2xl font-semibold tracking-tight">
            {formatMoney(payment.amount, payment.currency)}
            {payment.mxn && isUsd && (
              <span className="ml-2 text-base font-normal text-ink-muted">
                ≈ {formatMoney(payment.mxn, "MXN")}
              </span>
            )}
          </p>
          <p className="text-sm text-ink-muted">
            Cobrado el {formatDate(payment.payment_date)} · se declara en {monthLabel(payment.period)}
            {payment.transaction_id === null ? " · pago anterior" : payment.description ? ` · ${payment.description}` : ""}
          </p>
        </div>
        <StatusBadge payment={payment} />
      </section>

      <Step
        n={1}
        title="Datos del cobro"
        subtitle="Tipo de cambio de Banxico, periodo trabajado y recibo del pago."
        done={dataDone}
      >
        <PaymentDataForm
          key={payment.id}
          payment={payment}
          banxicoUrl={banxicoUrl}
          onDeleted={onBack}
          onDirtyChange={setDataDirty}
        />
      </Step>

      {excluded ? (
        <p className="rounded-lg border border-dashed border-line-strong p-4 text-center text-sm text-ink-muted">
          Este cobro está marcado como no facturable: no lleva factura ni se declara.
        </p>
      ) : (
        <>
          <Step
            n={2}
            title="Captura en el portal del SAT"
            subtitle="Copia cada campo en el mismo lugar de «Genera tu factura»."
            done={payment.invoice !== null}
            action={<SatLink url={satInvoiceUrl}>Abrir portal de facturación</SatLink>}
          >
            <InvoiceSheet paymentId={payment.id} />
          </Step>
          <Step
            n={3}
            title="Factura"
            subtitle="Sube el .zip que descargaste del portal: se leen sus datos para revisarlos antes de guardar."
            done={payment.invoice !== null}
          >
            {/* Sin factura, la tasa recién guardada en el paso 1 se vuelve a precargar. */}
            <InvoiceForm
              key={`${payment.id}-${payment.invoice?.id ?? `new-${payment.fiscal_fx_rate ?? ""}`}`}
              payment={payment}
              onDirtyChange={setInvoiceDirty}
            />
          </Step>
        </>
      )}

      <ConfirmDialog
        open={blocker.state === "blocked"}
        title="Cambios sin guardar"
        confirmLabel="Salir sin guardar"
        onClose={() => blocker.reset?.()}
        onConfirm={() => blocker.proceed?.()}
      >
        <p>
          Tienes cambios sin guardar en{" "}
          <strong>{dirtySections.map((s) => SECTION_NAMES[s]).join(" y ")}</strong>. Si sales ahora se
          pierden, incluidos los archivos que subiste y no guardaste.
        </p>
      </ConfirmDialog>
    </div>
  );
}
