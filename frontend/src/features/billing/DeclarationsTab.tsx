// Declaraciones mensuales RESICO (FAC-06/07/08/12/13): una tarjeta por mes
// fiscal con lo que se declara, la estimación del ISR, el aviso de precarga
// del SAT, el acuse y su pago (que puede crear el gasto "Impuestos").
import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { hasBalance, useAccounts } from "../../api/accounts";
import {
  useBillingPeriods,
  useBillingSettings,
  useDeleteFiling,
  useRemoveFilingPayment,
  useSaveFiling,
  useSetFilingPayment,
  type FilingKind,
  type FilingOut,
  type PaymentOut,
  type PeriodOut,
  type PeriodStatus,
  type PrefillItem,
  type StoredFileOut,
} from "../../api/billing";
import Icon from "../../components/ui/Icon";
import Modal from "../../components/ui/Modal";
import ConfirmDialog from "../../components/ui/ConfirmDialog";
import Spinner from "../../components/ui/Spinner";
import { formatDate, parseBusinessDate, todayISO } from "../../lib/dates";
import { formatMoney, isPositiveAmount, sanitizeDecimal } from "../../lib/money";
import {
  CopyRow,
  ErrorLine,
  FileChip,
  FilePicker,
  SatLink,
  StatusBadge,
  errorText,
  monthLabel,
} from "./shared";

const PERIOD_STYLES: Record<PeriodStatus, string> = {
  open: "bg-muted text-ink-muted",
  to_declare: "bg-amber-500/15 text-amber-800 dark:text-amber-200",
  to_pay: "bg-violet-500/15 text-violet-800 dark:text-violet-200",
  paid: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
};
const PERIOD_LABELS: Record<PeriodStatus, string> = {
  open: "Mes en curso",
  to_declare: "Por declarar",
  to_pay: "Por pagar",
  paid: "Pagado",
};
const KIND_LABELS: Record<FilingKind, string> = {
  normal: "Normal",
  complementary: "Complementaria",
};

/** Días naturales de hoy a `iso` (fechas locales, GLO-02). */
function daysUntil(iso: string): number {
  const ms = parseBusinessDate(iso).getTime() - parseBusinessDate(todayISO()).getTime();
  return Math.round(ms / 86_400_000);
}

function dueText(iso: string): string {
  const days = daysUntil(iso);
  if (days < 0) return `venció el ${formatDate(iso)}`;
  if (days === 0) return "vence hoy";
  return `${formatDate(iso)} · faltan ${days} ${days === 1 ? "día" : "días"}`;
}

/** "0.0100" → "1.0%" sin float (GLO-01: solo presentación de una tasa). */
function percent(rate: string): string {
  const [int = "0", dec = ""] = rate.split(".");
  const basis = Number(int) * 10000 + Number(dec.padEnd(4, "0").slice(0, 4));
  return `${(basis / 100).toFixed(1)}%`;
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-line bg-surface px-3 py-2.5">
      <p className="truncate text-xs text-ink-muted">{label}</p>
      <p className="tabular mt-0.5 text-base font-semibold">{value}</p>
      {hint && <p className="truncate text-xs text-ink-muted">{hint}</p>}
    </div>
  );
}

function PrefillList({ items, verb }: { items: PrefillItem[]; verb: string }) {
  return (
    <ul className="mt-1 list-disc space-y-0.5 pl-5">
      {items.map((i) => (
        <li key={i.payment_id}>
          {verb} el cobro del {formatDate(i.payment_date)}
          {i.mxn ? ` (${formatMoney(i.mxn, "MXN")})` : ""}, facturado el {formatDate(i.issue_date)}.
        </li>
      ))}
    </ul>
  );
}

// FAC-08: lo que el portal precarga contra lo que se debe declarar.
function PrefillNotice({ period }: { period: PeriodOut }) {
  if (period.status === "paid") return null; // ya declarado: el aviso no ayuda
  const differs =
    period.sat_prefill !== period.to_declare ||
    period.exclude_from_prefill.length > 0 ||
    period.add_to_prefill.length > 0;
  if (!differs) return null;
  return (
    <div className="rounded-lg bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-100">
      <p>
        El portal precargará {formatMoney(period.sat_prefill, "MXN")} (facturas emitidas en el mes),
        pero debes declarar {formatMoney(period.to_declare, "MXN")} (cobros del mes).
      </p>
      {period.exclude_from_prefill.length > 0 && (
        <PrefillList items={period.exclude_from_prefill} verb="Excluye" />
      )}
      {period.add_to_prefill.length > 0 && (
        <PrefillList items={period.add_to_prefill} verb="Agrega como ingreso adicional" />
      )}
    </div>
  );
}

// FAC-12/13: pago de la línea de captura; con cuenta, crea el gasto "Impuestos".
function PaymentFields({
  amount,
  setAmount,
  date,
  setDate,
  accountId,
  setAccountId,
  receipt,
  setReceipt,
}: {
  amount: string;
  setAmount: (v: string) => void;
  date: string;
  setDate: (v: string) => void;
  accountId: string;
  setAccountId: (v: string) => void;
  receipt: StoredFileOut | null;
  setReceipt: (f: StoredFileOut) => void;
}) {
  const accounts = useAccounts();
  const mxnAccounts = (accounts.data ?? []).filter(
    (a) => a.is_active && a.currency === "MXN" && a.behavior !== null,
  );
  return (
    <>
      <div>
        <label className="label" htmlFor="pay-date">Fecha de pago</label>
        <input
          id="pay-date"
          type="date"
          className="input"
          required
          max={todayISO()}
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="pay-amount">Importe pagado</label>
        <input
          id="pay-amount"
          className="input"
          inputMode="decimal"
          required
          value={amount}
          onChange={(e) => setAmount(sanitizeDecimal(e.target.value))}
        />
      </div>
      <div className="col-span-2">
        <label className="label" htmlFor="pay-account">Registrar el gasto "Impuestos" en</label>
        <select
          id="pay-account"
          className="input"
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
        >
          <option value="">No registrar gasto</option>
          {mxnAccounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
              {hasBalance(a.behavior) ? "" : " (crédito)"}
            </option>
          ))}
        </select>
      </div>
      <div className="col-span-2 md:col-span-4">
        <FilePicker
          label="Comprobante de pago (.jpg, .png o .pdf)"
          accept="image/jpeg,image/png,.pdf"
          file={receipt}
          onUploaded={setReceipt}
        />
      </div>
    </>
  );
}

function useDefaultTaxAccount(): string {
  const accounts = useAccounts();
  return (
    (accounts.data ?? []).find((a) => a.is_active && a.currency === "MXN" && a.behavior === "debit")
      ?.id ?? ""
  );
}

function FilingForm({
  period,
  filing,
  onDone,
}: {
  period: PeriodOut;
  filing: FilingOut | null;
  onDone: () => void;
}) {
  const save = useSaveFiling();
  const remove = useDeleteFiling();
  // GLO-09: borrar la declaración se confirma.
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const defaultAccount = useDefaultTaxAccount();
  const hasNormal = period.filings.some((f) => f.kind === "normal" && f.id !== filing?.id);
  const [kind, setKind] = useState<FilingKind>(filing?.kind ?? (hasNormal ? "complementary" : "normal"));
  const [filedDate, setFiledDate] = useState(filing?.filed_date ?? todayISO());
  const [operation, setOperation] = useState(filing?.operation_number ?? "");
  const [captureLine, setCaptureLine] = useState(filing?.capture_line ?? "");
  const [income, setIncome] = useState(filing?.declared_income ?? `${period.to_declare}.00`);
  const [isr, setIsr] = useState(filing?.isr_amount ?? `${period.isr_estimate}.00`);
  const [iva, setIva] = useState(filing?.iva_amount ?? "0.00");
  const [due, setDue] = useState(filing?.amount_due ?? `${period.isr_estimate}.00`);
  const [validUntil, setValidUntil] = useState(filing?.valid_until ?? "");
  const [ack, setAck] = useState<StoredFileOut | null>(filing?.ack_file ?? null);
  const [alreadyPaid, setAlreadyPaid] = useState(false);
  const [paidDate, setPaidDate] = useState(todayISO());
  const [paidAmount, setPaidAmount] = useState("");
  const [accountId, setAccountId] = useState("");
  const [receipt, setReceipt] = useState<StoredFileOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isrDiffers = !filing && isr !== `${period.isr_estimate}.00`;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    for (const [value, label] of [
      [isr, "El ISR"],
      [iva, "El IVA"],
      [due, "El total a pagar"],
    ] as const) {
      if (!/^\d+(\.\d{1,2})?$/.test(value)) return setError(`${label} debe ser un monto válido.`);
    }
    if (filedDate > todayISO()) return setError("La fecha de presentación no puede ser futura.");
    if (alreadyPaid && !isPositiveAmount(paidAmount || due))
      return setError("El importe pagado debe ser mayor a 0.");
    try {
      await save.mutateAsync({
        id: filing?.id,
        ...(filing ? {} : { period: period.period }),
        kind,
        filed_date: filedDate,
        operation_number: operation.trim() || null,
        capture_line: captureLine.replace(/\s+/g, "") || null,
        declared_income: income || null,
        isr_amount: isr,
        iva_amount: iva,
        amount_due: due,
        valid_until: validUntil || null,
        ack_file_id: ack?.id ?? null,
        ...(!filing && alreadyPaid
          ? {
              payment: {
                paid_date: paidDate,
                paid_amount: paidAmount || due,
                receipt_file_id: receipt?.id ?? null,
                account_id: accountId || null,
              },
            }
          : {}),
      });
      onDone();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div className="col-span-2 md:col-span-4">
        <FilePicker label="Acuse de la declaración (.pdf)" accept=".pdf,image/*" file={ack} onUploaded={setAck} />
      </div>
      <div>
        <label className="label" htmlFor="f-kind">Tipo</label>
        <select
          id="f-kind"
          className="input"
          value={kind}
          onChange={(e) => setKind(e.target.value as FilingKind)}
        >
          <option value="normal" disabled={hasNormal}>
            Normal
          </option>
          <option value="complementary">Complementaria</option>
        </select>
      </div>
      <div>
        <label className="label" htmlFor="f-date">Presentada el</label>
        <input
          id="f-date"
          type="date"
          className="input"
          required
          max={todayISO()}
          value={filedDate}
          onChange={(e) => setFiledDate(e.target.value)}
        />
      </div>
      <div className="col-span-2">
        <label className="label" htmlFor="f-op">Número de operación</label>
        <input
          id="f-op"
          className="input"
          maxLength={40}
          value={operation}
          onChange={(e) => setOperation(e.target.value)}
        />
      </div>
      <div className="col-span-2">
        <label className="label" htmlFor="f-line">Línea de captura</label>
        <input
          id="f-line"
          className="input font-mono text-xs"
          maxLength={60}
          value={captureLine}
          onChange={(e) => setCaptureLine(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="f-valid">Vigente hasta</label>
        <input
          id="f-valid"
          type="date"
          className="input"
          value={validUntil}
          onChange={(e) => setValidUntil(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="f-income">Ingresos declarados</label>
        <input
          id="f-income"
          className="input"
          inputMode="decimal"
          value={income}
          onChange={(e) => setIncome(sanitizeDecimal(e.target.value))}
        />
      </div>
      <div>
        <label className="label" htmlFor="f-isr">ISR</label>
        <input
          id="f-isr"
          className="input"
          inputMode="decimal"
          value={isr}
          onChange={(e) => setIsr(sanitizeDecimal(e.target.value))}
        />
      </div>
      <div>
        <label className="label" htmlFor="f-iva">IVA</label>
        <input
          id="f-iva"
          className="input"
          inputMode="decimal"
          value={iva}
          onChange={(e) => setIva(sanitizeDecimal(e.target.value))}
        />
      </div>
      <div>
        <label className="label" htmlFor="f-due">Total a pagar</label>
        <input
          id="f-due"
          className="input"
          inputMode="decimal"
          value={due}
          onChange={(e) => setDue(sanitizeDecimal(e.target.value))}
        />
      </div>
      {isrDiffers && (
        <p className="col-span-2 text-xs text-amber-800 md:col-span-4 dark:text-amber-200">
          El ISR difiere de la estimación ({formatMoney(period.isr_estimate, "MXN")}); manda lo que
          dice el acuse (FAC-07).
        </p>
      )}
      {!filing && (
        <>
          <label className="col-span-2 flex items-center gap-2 text-sm md:col-span-4">
            <input
              type="checkbox"
              checked={alreadyPaid}
              onChange={(e) => {
                setAlreadyPaid(e.target.checked);
                if (e.target.checked && !accountId) setAccountId(defaultAccount);
              }}
            />
            Ya está pagada
          </label>
          {alreadyPaid && (
            <PaymentFields
              amount={paidAmount || due}
              setAmount={setPaidAmount}
              date={paidDate}
              setDate={setPaidDate}
              accountId={accountId}
              setAccountId={setAccountId}
              receipt={receipt}
              setReceipt={setReceipt}
            />
          )}
        </>
      )}
      <div className="col-span-2 flex flex-wrap items-center justify-end gap-2 md:col-span-4">
        <ErrorLine error={error} />
        {filing && !filing.paid_date && (
          <button
            type="button"
            className="btn-danger"
            disabled={remove.isPending}
            onClick={() => setConfirmingDelete(true)}
          >
            Borrar declaración
          </button>
        )}
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cancelar
        </button>
        <button className="btn-primary" disabled={save.isPending}>
          Guardar declaración
        </button>
      </div>

      {filing && (
        <ConfirmDialog
          open={confirmingDelete}
          title="Borrar declaración"
          confirmLabel="Eliminar"
          pending={remove.isPending}
          onClose={() => setConfirmingDelete(false)}
          onConfirm={() => {
            setConfirmingDelete(false);
            void remove
              .mutateAsync(filing.id)
              .then(onDone)
              .catch((err) => setError(errorText(err)));
          }}
        >
          <p>
            ¿Borrar la declaración de {monthLabel(period.period)}? Se elimina de forma permanente
            junto con sus datos capturados.
          </p>
        </ConfirmDialog>
      )}
    </form>
  );
}

function FilingPaymentForm({ filing, onDone }: { filing: FilingOut; onDone: () => void }) {
  const pay = useSetFilingPayment();
  const defaultAccount = useDefaultTaxAccount();
  const [date, setDate] = useState(todayISO());
  const [amount, setAmount] = useState(filing.amount_due);
  const [accountId, setAccountId] = useState(defaultAccount);
  const [receipt, setReceipt] = useState<StoredFileOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!isPositiveAmount(amount)) return setError("El importe pagado debe ser mayor a 0.");
    if (date < filing.filed_date)
      return setError("El pago no puede ser anterior a la presentación de la declaración.");
    try {
      await pay.mutateAsync({
        filingId: filing.id,
        paid_date: date,
        paid_amount: amount,
        receipt_file_id: receipt?.id ?? null,
        account_id: accountId || null,
      });
      onDone();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {filing.capture_line && (
        <div className="col-span-2 rounded-lg border border-line bg-surface px-3 md:col-span-4">
          <CopyRow label="Línea de captura (sin espacios)" value={filing.capture_line} />
          <CopyRow label="Importe exacto" value={filing.amount_due} />
        </div>
      )}
      <PaymentFields
        amount={amount}
        setAmount={setAmount}
        date={date}
        setDate={setDate}
        accountId={accountId}
        setAccountId={setAccountId}
        receipt={receipt}
        setReceipt={setReceipt}
      />
      <div className="col-span-2 flex flex-wrap items-center justify-end gap-2 md:col-span-4">
        <ErrorLine error={error} />
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cancelar
        </button>
        <button className="btn-primary" disabled={pay.isPending}>
          Registrar pago
        </button>
      </div>
    </form>
  );
}

function FilingRow({
  filing,
  onEdit,
  onPay,
}: {
  filing: FilingOut;
  onEdit: () => void;
  onPay: () => void;
}) {
  const removePayment = useRemoveFilingPayment();
  const [error, setError] = useState<string | null>(null);
  // GLO-09: quitar el pago borra también su gasto; se confirma.
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const needsPayment = filing.paid_date === null && filing.amount_due !== "0.00";
  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 text-sm">
          <p className="font-medium">
            {KIND_LABELS[filing.kind]} · presentada el {formatDate(filing.filed_date)}
          </p>
          <p className="text-xs text-ink-muted">
            {[
              filing.operation_number ? `Operación ${filing.operation_number}` : null,
              `ISR ${formatMoney(filing.isr_amount, "MXN")}`,
              `IVA ${formatMoney(filing.iva_amount, "MXN")}`,
              `a pagar ${formatMoney(filing.amount_due, "MXN")}`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {filing.paid_date ? (
            <p className="text-xs text-emerald-700 dark:text-emerald-300">
              Pagada el {formatDate(filing.paid_date)} ·{" "}
              {formatMoney(filing.paid_amount ?? "0", "MXN")}
              {filing.expense_transaction_id && " · gasto registrado en Impuestos"}
            </p>
          ) : (
            filing.amount_due === "0.00" && (
              <p className="text-xs text-ink-muted">Sin importe a pagar.</p>
            )
          )}
        </div>
        <div className="flex flex-wrap gap-1.5 [&>*]:h-8 [&>*]:px-2.5">
          {needsPayment && (
            <button className="btn-primary" onClick={onPay}>
              Registrar pago
            </button>
          )}
          {filing.paid_date && (
            <button
              className="btn-secondary"
              disabled={removePayment.isPending}
              title="Borra también su gasto de Impuestos"
              onClick={() => setConfirmingRemove(true)}
            >
              Quitar pago
            </button>
          )}
          {filing.expense_transaction_id && (
            <Link className="btn-secondary" to="/transacciones">
              Ver gasto
            </Link>
          )}
          <button className="btn-secondary px-2.5" onClick={onEdit} aria-label="Editar declaración">
            <Icon name="pencil" className="size-3.5" />
          </button>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {filing.ack_file && <FileChip file={filing.ack_file} />}
        {filing.receipt_file && <FileChip file={filing.receipt_file} />}
      </div>
      {needsPayment && filing.capture_line && (
        <div className="rounded-lg border border-line bg-surface px-3">
          <CopyRow label="Línea de captura" value={filing.capture_line} />
        </div>
      )}
      <ConfirmDialog
        open={confirmingRemove}
        title="Quitar pago"
        confirmLabel="Sí, quitar"
        pending={removePayment.isPending}
        onClose={() => setConfirmingRemove(false)}
        onConfirm={() => {
          setConfirmingRemove(false);
          void removePayment.mutateAsync(filing.id).catch((err) => setError(errorText(err)));
        }}
      >
        <p>
          ¿Quitar el pago de esta declaración? Se borra también su gasto de Impuestos y la
          declaración vuelve a quedar pendiente de pago.
        </p>
      </ConfirmDialog>
      <ErrorLine error={error} />
    </li>
  );
}

function PeriodCard({
  period,
  payments,
  urls,
  onFile,
  onEditFiling,
  onPay,
  onOpenPayment,
}: {
  period: PeriodOut;
  payments: PaymentOut[];
  urls: { filing: string | null; payment: string | null };
  onFile: () => void;
  onEditFiling: (f: FilingOut) => void;
  onPay: (f: FilingOut) => void;
  onOpenPayment: (p: PaymentOut) => void;
}) {
  const p = period;
  const declarable = p.status !== "open";
  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex flex-wrap items-center gap-2 text-lg font-semibold tracking-tight">
            {monthLabel(p.period)}
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${PERIOD_STYLES[p.status]}`}>
              {PERIOD_LABELS[p.status]}
            </span>
            {p.is_overdue && (
              <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-700 dark:text-red-300">
                Vencido
              </span>
            )}
          </h2>
          <p className="text-sm text-ink-muted">
            {p.status === "open" && `Se declara del 1 al ${formatDate(p.deadline)}`}
            {p.status === "to_declare" && `Declarar antes del ${dueText(p.deadline)}`}
            {p.status === "to_pay" && `Pagar antes del ${dueText(p.payment_deadline ?? p.deadline)}`}
            {p.status === "paid" && "Declarado y pagado"}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {declarable && p.status !== "paid" && <SatLink url={urls.filing}>Portal de declaraciones</SatLink>}
          {p.status === "to_pay" && <SatLink url={urls.payment}>Portal de pago</SatLink>}
          {declarable && (
            <button className={p.filings.length ? "btn-secondary" : "btn-primary"} onClick={onFile}>
              <Icon name="plus" />
              {p.filings.length ? "Complementaria" : "Registrar declaración"}
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile label="Ingresos a declarar" value={formatMoney(p.to_declare, "MXN")} hint="pesos sin centavos" />
        <Tile
          label="ISR estimado"
          value={formatMoney(p.isr_estimate, "MXN")}
          hint={`tasa RESICO ${percent(p.isr_rate)}`}
        />
        <Tile label="IVA" value={formatMoney("0", "MXN")} hint="exportación, tasa 0%" />
        <Tile label="Cobros" value={String(payments.length)} />
      </div>

      {(p.missing_rates > 0 || p.pending_invoice > 0) && (
        <p className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-800 dark:text-red-200">
          {[
            p.pending_invoice > 0 &&
              `${p.pending_invoice} ${p.pending_invoice === 1 ? "cobro sin factura" : "cobros sin factura"}`,
            p.missing_rates > 0 &&
              `${p.missing_rates} ${p.missing_rates === 1 ? "cobro sin tipo de cambio" : "cobros sin tipo de cambio"} (no suman al total)`,
          ]
            .filter(Boolean)
            .join(" · ")}
          .
        </p>
      )}
      <PrefillNotice period={p} />

      {payments.length > 0 && (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {payments.map((pay) => (
            <li key={pay.id}>
              <button
                type="button"
                className="flex w-full flex-wrap items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-muted/60"
                onClick={() => onOpenPayment(pay)}
              >
                <span>
                  {formatDate(pay.payment_date)} · {formatMoney(pay.amount, pay.currency)}
                </span>
                <span className="flex items-center gap-2">
                  <StatusBadge payment={pay} />
                  <span className="tabular text-xs text-ink-muted">
                    {pay.mxn ? formatMoney(pay.mxn, "MXN") : "sin TC"}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {p.filings.length > 0 && (
        <ul className="divide-y divide-line border-t border-line">
          {p.filings.map((f) => (
            <FilingRow key={f.id} filing={f} onEdit={() => onEditFiling(f)} onPay={() => onPay(f)} />
          ))}
        </ul>
      )}
    </section>
  );
}

export default function DeclarationsTab({
  payments,
  onOpenPayment,
}: {
  payments: PaymentOut[];
  onOpenPayment: (p: PaymentOut) => void;
}) {
  const periods = useBillingPeriods();
  const settings = useBillingSettings();
  const [modal, setModal] = useState<
    | { kind: "file"; period: PeriodOut; filing: FilingOut | null }
    | { kind: "pay"; period: PeriodOut; filing: FilingOut }
    | null
  >(null);
  const byId = useMemo(() => new Map(payments.map((p) => [p.id, p])), [payments]);
  const urls = {
    filing: settings.data?.sat_filing_url ?? null,
    payment: settings.data?.sat_payment_url ?? null,
  };

  if (periods.isPending)
    return (
      <div className="card flex h-48 items-center justify-center">
        <Spinner className="size-7" />
      </div>
    );
  if (periods.isError) return <ErrorLine error={errorText(periods.error)} />;
  if (periods.data.length === 0)
    return (
      <div className="grid place-items-center gap-2 rounded-xl border border-dashed border-line-strong p-10 text-center text-sm text-ink-muted">
        <Icon name="receipt" className="size-6" />
        Sin meses que declarar todavía.
      </div>
    );

  const title =
    modal?.kind === "pay"
      ? `Pago · ${monthLabel(modal.period.period)}`
      : modal
        ? `${modal.filing ? "Editar declaración" : "Declaración"} · ${monthLabel(modal.period.period)}`
        : "";

  return (
    <div className="space-y-4">
      {periods.data.map((period) => (
        <PeriodCard
          key={period.period}
          period={period}
          payments={period.payment_ids.map((id) => byId.get(id)).filter((p): p is PaymentOut => !!p)}
          urls={urls}
          onFile={() => setModal({ kind: "file", period, filing: null })}
          onEditFiling={(filing) => setModal({ kind: "file", period, filing })}
          onPay={(filing) => setModal({ kind: "pay", period, filing })}
          onOpenPayment={onOpenPayment}
        />
      ))}
      <Modal open={modal !== null} onClose={() => setModal(null)} title={title} size="xl">
        {modal?.kind === "file" && (
          <FilingForm
            key={modal.filing?.id ?? "new"}
            period={modal.period}
            filing={modal.filing}
            onDone={() => setModal(null)}
          />
        )}
        {modal?.kind === "pay" && (
          <FilingPaymentForm filing={modal.filing} onDone={() => setModal(null)} />
        )}
      </Modal>
    </div>
  );
}
