// Suscripciones y pagos recurrentes (REC-01..14): suscripciones de precio fijo
// (en MXN o USD, REC-08), pruebas gratuitas (REC-10), servicios de monto
// variable que se capturan cada periodo (REC-11) y otros recurrentes (nómina,
// renta). Los avisos previos al cobro se programan solos (REC-12).
import { useMemo, useState, type FormEvent } from "react";
import { addDays, format } from "date-fns";
import { useAccounts, type AccountOut } from "../../api/accounts";
import { useCategories } from "../../api/catalogs";
import {
  useCaptureBill,
  useCreateRecurringRule,
  useDeleteRecurringRule,
  usePendingBills,
  useRecurringRules,
  useSetRuleCanceled,
  useSkipBill,
  useSubscriptionSummary,
  useUpdateRecurringRule,
  type PendingBillOut,
  type RecurringFrequency,
  type RecurringKind,
  type RecurringRuleBody,
  type RecurringRuleOut,
  type RuleStatus,
} from "../../api/recurring";
import AccountOptions from "../../components/AccountOptions";
import Icon from "../../components/ui/Icon";
import Modal from "../../components/ui/Modal";
import Spinner from "../../components/ui/Spinner";
import { formatDate, parseBusinessDate, todayISO } from "../../lib/dates";
import { formatMoney, isPositiveAmount, sanitizeDecimal } from "../../lib/money";
import { useSpace } from "../spaces/SpaceProvider";

const CURRENCIES = ["MXN", "USD"];

const FREQ_LABELS: Record<RecurringFrequency, string> = {
  weekly: "Semanal",
  biweekly: "Catorcena (cada 14 días)",
  semimonthly: "Quincenal (15 y fin de mes)",
  monthly: "Mensual",
  bimonthly: "Bimestral",
  yearly: "Anual",
};

const FREQ_SHORT: Record<RecurringFrequency, string> = {
  weekly: "semana",
  biweekly: "14 días",
  semimonthly: "quincena",
  monthly: "mes",
  bimonthly: "bimestre",
  yearly: "año",
};

const STATUS_LABELS: Record<RuleStatus, string> = {
  active: "Activa",
  trial: "En prueba",
  paused: "Pausada",
  canceled: "Cancelada",
};

const STATUS_STYLES: Record<RuleStatus, string> = {
  active: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  trial: "bg-amber-500/15 text-amber-800 dark:text-amber-200",
  paused: "bg-muted text-ink-muted",
  canceled: "bg-muted text-ink-muted",
};

const TABS: { kind: RecurringKind; label: string; short?: string; empty: string }[] = [
  {
    kind: "subscription",
    label: "Suscripciones",
    empty: "Agrega Spotify, Netflix, Claude… Te aviso unos días antes de cada cobro.",
  },
  {
    kind: "bill",
    label: "Servicios",
    empty: "Luz, agua, gas, internet: cada periodo te recuerdo capturar el monto del recibo.",
  },
  {
    kind: "generic",
    label: "Otros recurrentes",
    short: "Otros",
    empty: "Nómina, renta y demás pagos fijos que se registran solos en «Por confirmar».",
  },
];

// Colores como en el dashboard: ingresos verde, gastos rojo.
const GENERIC_GROUPS = [
  {
    type: "expense",
    label: "Gastos",
    empty: "Sin gastos recurrentes.",
    border: "border-red-500/25",
    header: "border-red-500/25 bg-red-500/10 text-red-700 dark:text-red-300",
    dot: "bg-red-500",
    pill: "bg-red-500/15 text-red-700 dark:text-red-300",
  },
  {
    type: "income",
    label: "Ingresos",
    empty: "Sin ingresos recurrentes.",
    border: "border-emerald-500/25",
    header: "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
    dot: "bg-emerald-500",
    pill: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  },
] as const;

// REC-12: opciones de aviso (días antes del cobro).
const REMINDER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Sin aviso" },
  { value: "0", label: "El mismo día" },
  { value: "1", label: "1 día antes" },
  { value: "2", label: "2 días antes" },
  { value: "3", label: "3 días antes" },
  { value: "5", label: "5 días antes" },
  { value: "7", label: "7 días antes" },
];

const DEFAULT_REMINDER: Record<RecurringKind, string> = {
  subscription: "3",
  bill: "0",
  generic: "",
};

function plusDaysISO(days: number): string {
  return format(addDays(parseBusinessDate(todayISO()), days), "yyyy-MM-dd");
}

function MoneyInput({
  id,
  value,
  onChange,
  required = false,
  placeholder = "0.00",
}: {
  id?: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  placeholder?: string;
}) {
  return (
    <input
      id={id}
      className="input"
      inputMode="decimal"
      placeholder={placeholder}
      required={required}
      value={value}
      onChange={(e) => onChange(sanitizeDecimal(e.target.value))}
    />
  );
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : "Error al guardar";
}

// Alta y edición de una regla. En edición, tipo, frecuencia e inicio quedan
// fijos (REC-04: los cambios solo afectan cobros futuros).
function RuleForm({
  kind,
  rule,
  accounts,
  onDone,
}: {
  kind: RecurringKind;
  rule: RecurringRuleOut | null;
  accounts: AccountOut[];
  onDone: () => void;
}) {
  const { activeSpace } = useSpace();
  const categories = useCategories();
  const create = useCreateRecurringRule();
  const update = useUpdateRecurringRule();

  const [type, setType] = useState<"expense" | "income">(rule?.type ?? "expense");
  const [description, setDescription] = useState(rule?.description ?? "");
  const [amount, setAmount] = useState(rule?.amount ?? "");
  const [currency, setCurrency] = useState(rule?.currency ?? activeSpace.base_currency);
  const [accountId, setAccountId] = useState(rule?.account_id ?? "");
  const [categoryId, setCategoryId] = useState(rule?.category_id ?? "");
  const [frequency, setFrequency] = useState<RecurringFrequency>(rule?.frequency ?? "monthly");
  const [startDate, setStartDate] = useState(rule?.start_date ?? "");
  const [useLastDay, setUseLastDay] = useState(rule?.use_last_day ?? false);
  const [isTrial, setIsTrial] = useState(rule?.is_trial ?? false);
  const [reminder, setReminder] = useState(
    rule ? (rule.reminder_days[0]?.toString() ?? "") : DEFAULT_REMINDER[kind],
  );
  const [endDate, setEndDate] = useState(rule?.end_date ?? "");
  const [cancelUrl, setCancelUrl] = useState(rule?.cancel_url ?? "");
  const [notes, setNotes] = useState(rule?.notes ?? "");
  const [error, setError] = useState<string | null>(null);

  const isBill = kind === "bill";
  const account = accounts.find((a) => a.id === accountId);
  // REC-08: solo un gasto que no es servicio puede tener precio en otra moneda.
  const freeCurrency = type === "expense" && !isBill;
  const effectiveCurrency = freeCurrency ? currency : (account?.currency ?? currency);
  const byMonth = frequency === "monthly" || frequency === "bimonthly";
  const categoryKind = type === "expense" ? "expense" : "income";
  const categoryOptions = (categories.data ?? []).filter(
    (c) => c.kind === categoryKind && (c.is_active || c.id === categoryId),
  );
  const pending = create.isPending || update.isPending;

  const startLabel =
    kind === "bill"
      ? "Fecha del recibo"
      : isTrial
        ? "Termina la prueba (primer cobro)"
        : rule
          ? "Desde"
          : "Próximo cobro";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const hasAmount = amount.trim() !== "";
    if ((!isBill || hasAmount) && !isPositiveAmount(amount)) {
      setError(
        isBill
          ? "El estimado debe ser mayor a 0, o déjalo vacío."
          : "El monto debe ser mayor a 0. Si ya no aplica, pausa o cancela la regla.",
      );
      return;
    }
    // REC-12: los recurrentes genéricos no avisan.
    const reminderDays = reminder === "" || kind === "generic" ? [] : [Number(reminder)];
    try {
      if (rule) {
        await update.mutateAsync({
          id: rule.id,
          description: description.trim(),
          amount: hasAmount ? amount : null,
          currency: effectiveCurrency,
          account_id: accountId,
          category_id: categoryId || null,
          end_date: endDate || null,
          ...(byMonth && { use_last_day: useLastDay }),
          reminder_days: reminderDays,
          cancel_url: cancelUrl.trim() || null,
          notes: notes.trim() || null,
        });
      } else {
        const body: RecurringRuleBody = {
          kind,
          type,
          description: description.trim(),
          amount: hasAmount ? amount : null,
          amount_is_estimate: isBill,
          currency: effectiveCurrency,
          account_id: accountId,
          category_id: categoryId || null,
          frequency,
          start_date: startDate,
          use_last_day: byMonth && useLastDay,
          is_trial: kind === "subscription" && isTrial,
          reminder_days: reminderDays,
          cancel_url: cancelUrl.trim() || null,
          notes: notes.trim() || null,
        };
        await create.mutateAsync(body);
      }
      onDone();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {kind === "generic" && !rule && (
        <div className="col-span-2 md:col-span-4">
          <div className="inline-flex rounded-lg border border-line p-0.5" role="group" aria-label="Tipo">
            {(["expense", "income"] as const).map((t) => (
              <button
                key={t}
                type="button"
                aria-pressed={type === t}
                onClick={() => {
                  setType(t);
                  setCategoryId("");
                }}
                className={`rounded-md px-3 py-1 text-sm transition ${
                  type === t ? "bg-muted font-medium text-ink" : "text-ink-muted hover:text-ink"
                }`}
              >
                {t === "expense" ? "Gasto" : "Ingreso"}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="col-span-2">
        <label className="label" htmlFor="r-desc">
          {kind === "bill" ? "Servicio" : "Nombre"}
        </label>
        <input
          id="r-desc"
          className="input"
          required
          maxLength={200}
          placeholder={
            kind === "subscription" ? "Spotify, Claude…" : kind === "bill" ? "Luz, Agua…" : "Nómina, Renta…"
          }
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="r-amount">
          {isBill ? "Estimado (opcional)" : kind === "subscription" ? "Precio" : "Monto"}
        </label>
        <MoneyInput
          id="r-amount"
          value={amount}
          onChange={setAmount}
          required={!isBill}
          placeholder={isBill ? "Opcional" : "0.00"}
        />
      </div>
      <div>
        <label className="label" htmlFor="r-currency">Moneda</label>
        <select
          id="r-currency"
          className="input"
          disabled={!freeCurrency}
          value={effectiveCurrency}
          onChange={(e) => setCurrency(e.target.value)}
        >
          {CURRENCIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </div>

      <div className="col-span-2">
        <label className="label" htmlFor="r-account">
          {type === "income" ? "Se deposita en" : "Se cobra a"}
        </label>
        <select
          id="r-account"
          className="input"
          required
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
        >
          <option value="">Selecciona…</option>
          <AccountOptions
            accounts={accounts.filter((a) => a.is_active || a.id === accountId)}
            baseCurrency={activeSpace.base_currency}
          />
        </select>
      </div>
      <div className="col-span-2">
        <label className="label" htmlFor="r-category">Categoría</label>
        <select
          id="r-category"
          className="input"
          required
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
        >
          <option value="">Selecciona…</option>
          {categoryOptions.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>
      {freeCurrency && account && effectiveCurrency !== account.currency && (
        <p className="col-span-2 -mt-1 text-xs text-ink-muted md:col-span-4">
          El día del cobro se registra en {account.currency} con el tipo de cambio de ese día; si
          tu banco cobró otra cantidad, la ajustas al confirmar.
        </p>
      )}

      <div>
        <label className="label" htmlFor="r-freq">Frecuencia</label>
        <select
          id="r-freq"
          className="input"
          disabled={rule !== null}
          value={frequency}
          onChange={(e) => setFrequency(e.target.value as RecurringFrequency)}
        >
          {(Object.keys(FREQ_LABELS) as RecurringFrequency[]).map((f) => (
            <option key={f} value={f}>
              {FREQ_LABELS[f]}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="label" htmlFor="r-start">{startLabel}</label>
        <input
          id="r-start"
          type="date"
          className="input"
          required
          disabled={rule !== null}
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
        />
      </div>
      <div className={kind === "generic" ? "hidden" : ""}>
        <label className="label" htmlFor="r-reminder">Avisarme</label>
        <select
          id="r-reminder"
          className="input"
          value={reminder}
          onChange={(e) => setReminder(e.target.value)}
        >
          {REMINDER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="label" htmlFor="r-end">Fecha fin (opcional)</label>
        <input
          id="r-end"
          type="date"
          className="input"
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
        />
      </div>

      <div className="col-span-2 flex flex-wrap items-center gap-x-5 gap-y-2 md:col-span-4">
        {byMonth && (
          <label className="flex items-center gap-1.5 text-sm text-ink-muted">
            <input
              type="checkbox"
              checked={useLastDay}
              onChange={(e) => setUseLastDay(e.target.checked)}
            />
            Último día del mes
          </label>
        )}
        {kind === "subscription" && !rule && (
          <label className="flex items-center gap-1.5 text-sm text-ink-muted">
            <input
              type="checkbox"
              checked={isTrial}
              onChange={(e) => setIsTrial(e.target.checked)}
            />
            Es una prueba gratuita
          </label>
        )}
        {isTrial && !rule && (
          <span className="flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
            Dura:
            {[7, 14, 30].map((days) => (
              <button
                key={days}
                type="button"
                className="rounded-md border border-line px-2 py-0.5 hover:bg-muted"
                onClick={() => setStartDate(plusDaysISO(days))}
              >
                {days} días
              </button>
            ))}
          </span>
        )}
      </div>
      {isTrial && (
        <p className="col-span-2 -mt-1 text-xs text-ink-muted md:col-span-4">
          Te aviso un día antes de que termine. Si no la cancelas, se vuelve suscripción y el
          primer cobro cae en esa fecha.
        </p>
      )}

      {kind !== "generic" && (
        <div className="col-span-2 md:col-span-4">
          <label className="label" htmlFor="r-url">
            {kind === "bill" ? "Liga para pagar o consultar (opcional)" : "Liga para cancelar (opcional)"}
          </label>
          <input
            id="r-url"
            type="url"
            className="input"
            maxLength={500}
            placeholder="https://"
            value={cancelUrl}
            onChange={(e) => setCancelUrl(e.target.value)}
          />
        </div>
      )}
      <div className="col-span-2 md:col-span-4">
        <label className="label" htmlFor="r-notes">Notas</label>
        <textarea
          id="r-notes"
          className="input min-h-16"
          maxLength={2000}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>

      {error && (
        <p className="col-span-2 text-sm text-red-600 dark:text-red-400 md:col-span-4">{error}</p>
      )}
      <div className="col-span-2 flex justify-end gap-2 pt-1 md:col-span-4">
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cerrar
        </button>
        <button className="btn-primary" disabled={pending}>
          {rule ? "Guardar cambios" : "Crear"}
        </button>
      </div>
    </form>
  );
}

// REC-11: un recibo pendiente de capturar.
function PendingBillRow({ bill, accountName }: { bill: PendingBillOut; accountName: string }) {
  const capture = useCaptureBill();
  const skip = useSkipBill();
  // Sin prellenar con el estimado: el registro debe llevar el monto real.
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(bill.scheduled_date);
  const [error, setError] = useState<string | null>(null);

  async function handleCapture(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!isPositiveAmount(amount)) {
      setError("El monto debe ser mayor a 0. Si este recibo no aplica, usa «Omitir».");
      return;
    }
    try {
      await capture.mutateAsync({
        ruleId: bill.rule_id,
        scheduled_date: bill.scheduled_date,
        amount,
        date,
      });
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <li className="py-3">
      <form onSubmit={handleCapture} className="flex flex-wrap items-end gap-2">
        <div className="min-w-40 flex-1">
          <p className="text-sm font-medium">{bill.description}</p>
          <p className="text-xs text-ink-muted">
            Recibo del {formatDate(bill.scheduled_date)}
            {accountName && ` · ${accountName}`}
            {bill.estimate && ` · aprox. ${formatMoney(bill.estimate, bill.currency)}`}
          </p>
        </div>
        <div className="w-32">
          <label className="sr-only" htmlFor={`b-amount-${bill.rule_id}-${bill.scheduled_date}`}>
            Monto
          </label>
          <MoneyInput
            id={`b-amount-${bill.rule_id}-${bill.scheduled_date}`}
            value={amount}
            onChange={setAmount}
            required
            placeholder={bill.estimate ?? "Monto"}
          />
        </div>
        <input
          type="date"
          aria-label="Fecha del pago"
          className="input w-auto"
          required
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
        <button className="btn-primary" disabled={capture.isPending}>
          Registrar
        </button>
        <button
          type="button"
          className="btn-secondary"
          disabled={skip.isPending}
          onClick={() =>
            skip.mutate({ ruleId: bill.rule_id, scheduled_date: bill.scheduled_date })
          }
        >
          Omitir
        </button>
      </form>
      {error && <p className="mt-1 text-sm text-red-600 dark:text-red-400">{error}</p>}
    </li>
  );
}

type ConfirmAction = "pause" | "cancel";

function RuleRow({
  rule,
  accountName,
  onEdit,
  onDelete,
  onConfirm,
}: {
  rule: RecurringRuleOut;
  accountName: string;
  onEdit: () => void;
  onDelete: () => void;
  // Pausar y cancelar piden confirmación (evita un clic accidental).
  onConfirm: (action: ConfirmAction) => void;
}) {
  const setCanceled = useSetRuleCanceled();
  const update = useUpdateRecurringRule();
  const busy = setCanceled.isPending || update.isPending;
  const inactive = rule.status === "paused" || rule.status === "canceled";
  const showStatus = rule.kind !== "generic" || inactive;

  const price =
    rule.amount === null
      ? "Monto variable"
      : `${rule.kind === "bill" ? "aprox. " : ""}${formatMoney(rule.amount, rule.currency)}`;

  return (
    <li className={`flex flex-wrap items-center justify-between gap-3 py-3 ${inactive ? "opacity-70" : ""}`}>
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
          <span className="truncate">{rule.description}</span>
          {showStatus && (
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[rule.status]}`}>
              {STATUS_LABELS[rule.status]}
            </span>
          )}
        </p>
        <p className="text-xs text-ink-muted">
          <span className="tabular">{price}</span> / {FREQ_SHORT[rule.frequency]}
          {rule.account_amount_today && rule.account_currency && (
            <> (≈ {formatMoney(rule.account_amount_today, rule.account_currency)} hoy)</>
          )}
          {accountName && ` · ${accountName}`}
        </p>
        <p className="text-xs text-ink-muted">
          {rule.status === "canceled" && rule.canceled_at
            ? `Cancelada el ${formatDate(rule.canceled_at)}`
            : rule.status === "paused"
              ? "Sin cobros mientras esté pausada"
              : rule.next_date
                ? rule.status === "trial"
                  ? `La prueba termina el ${formatDate(rule.next_date)}`
                  : `${rule.kind === "bill" ? "Próximo recibo" : rule.type === "income" ? "Próximo depósito" : "Próximo cobro"}: ${formatDate(rule.next_date)}`
                : "Sin cobros próximos"}
          {rule.status === "trial" && " · aviso un día antes de que termine"}
          {rule.reminder_days.length > 0 &&
            !inactive &&
            rule.status !== "trial" &&
            ` · aviso ${rule.reminder_days[0] === 0 ? "el mismo día" : `${rule.reminder_days[0]} ${rule.reminder_days[0] === 1 ? "día" : "días"} antes`}`}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 [&>*]:h-8 [&>*]:px-2.5">
        {rule.cancel_url && /^https?:\/\//i.test(rule.cancel_url) && (
          <a
            className="btn-secondary"
            href={rule.cancel_url}
            target="_blank"
            rel="noopener noreferrer"
            title={rule.kind === "bill" ? "Abrir liga" : "Abrir la página para cancelar"}
          >
            {rule.kind === "bill" ? "Abrir" : "Ir a cancelar"}
          </a>
        )}
        {rule.status === "canceled" ? (
          <button
            className="btn-secondary"
            disabled={busy}
            onClick={() => setCanceled.mutate({ id: rule.id, canceled: false })}
          >
            Reactivar
          </button>
        ) : (
          <>
            <button
              className="btn-secondary"
              disabled={busy}
              onClick={() =>
                rule.status === "paused"
                  ? update.mutate({ id: rule.id, is_active: true })
                  : onConfirm("pause")
              }
            >
              {rule.status === "paused" ? "Reanudar" : "Pausar"}
            </button>
            {rule.kind !== "generic" && (
              <button
                className="btn-secondary"
                disabled={busy}
                onClick={() => onConfirm("cancel")}
              >
                Cancelar
              </button>
            )}
          </>
        )}
        <button className="btn-secondary" onClick={onEdit} aria-label="Editar" title="Editar">
          <Icon name="pencil" className="size-3.5" />
        </button>
        <button
          className="btn-secondary hover:text-red-600 dark:hover:text-red-400"
          onClick={onDelete}
          aria-label="Eliminar"
          title="Eliminar"
        >
          <Icon name="x" className="size-3.5" />
        </button>
      </div>
    </li>
  );
}

export default function SubscriptionsPage() {
  const [tab, setTab] = useState<RecurringKind>("subscription");
  const [showInactive, setShowInactive] = useState(false);
  const rules = useRecurringRules(true);
  const pendingBills = usePendingBills();
  const summary = useSubscriptionSummary();
  const accounts = useAccounts();
  const remove = useDeleteRecurringRule();
  const [modal, setModal] = useState<{ rule: RecurringRuleOut | null; kind: RecurringKind } | null>(
    null,
  );
  const [deleting, setDeleting] = useState<RecurringRuleOut | null>(null);
  const [confirming, setConfirming] = useState<{
    rule: RecurringRuleOut;
    action: ConfirmAction;
  } | null>(null);
  const pauseRule = useUpdateRecurringRule();
  const cancelRule = useSetRuleCanceled();
  const confirmPending = pauseRule.isPending || cancelRule.isPending;

  function runConfirmed() {
    if (!confirming) return;
    const done = { onSuccess: () => setConfirming(null) };
    if (confirming.action === "pause") {
      pauseRule.mutate({ id: confirming.rule.id, is_active: false }, done);
    } else {
      cancelRule.mutate({ id: confirming.rule.id, canceled: true }, done);
    }
  }

  const accountList = accounts.data ?? [];
  const accountNames = useMemo(
    () => new Map(accountList.map((a) => [a.id, a.name])),
    [accountList],
  );
  const all = rules.data ?? [];
  const counts = useMemo(() => {
    const result: Record<RecurringKind, number> = { subscription: 0, bill: 0, generic: 0 };
    for (const r of all) if (r.status !== "canceled") result[r.kind] += 1;
    return result;
  }, [all]);
  const visible = all.filter(
    (r) => r.kind === tab && (showInactive || (r.status !== "canceled" && r.status !== "paused")),
  );
  const hiddenCount = all.filter(
    (r) => r.kind === tab && (r.status === "canceled" || r.status === "paused"),
  ).length;
  const bills = pendingBills.data ?? [];
  const current = TABS.find((t) => t.kind === tab)!;
  const s = summary.data;

  function ruleList(group: RecurringRuleOut[]) {
    return (
      <ul className="divide-y divide-line">
        {group.map((r) => (
          <RuleRow
            key={r.id}
            rule={r}
            accountName={accountNames.get(r.account_id) ?? ""}
            onEdit={() => setModal({ rule: r, kind: r.kind })}
            onDelete={() => setDeleting(r)}
            onConfirm={(action) => setConfirming({ rule: r, action })}
          />
        ))}
      </ul>
    );
  }

  // "Otros recurrentes" se divide en gastos e ingresos (2 columnas en
  // desktop, 1 en móvil); las demás pestañas solo tienen gastos (REC-07).
  function renderRules() {
    if (tab !== "generic") return ruleList(visible);
    return (
      <div className="grid gap-4 md:grid-cols-2">
        {GENERIC_GROUPS.map((g) => {
          const group = visible.filter((r) => r.type === g.type);
          return (
            <section key={g.type} className={`card min-w-0 overflow-hidden p-0 ${g.border}`}>
              <header
                className={`flex items-center justify-between gap-2 border-b px-4 py-2.5 ${g.header}`}
              >
                <h3 className="flex items-center gap-2 text-sm font-semibold">
                  <span className={`size-2.5 rounded-full ${g.dot}`} aria-hidden />
                  {g.label}
                </h3>
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${g.pill}`}>
                  {group.length}
                </span>
              </header>
              <div className="px-4">
                {group.length > 0 ? (
                  ruleList(group)
                ) : (
                  <p className="py-6 text-center text-sm text-ink-muted">{g.empty}</p>
                )}
              </div>
            </section>
          );
        })}
      </div>
    );
  }

  return (
    <div className="page">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="page-title">Suscripciones</h1>
          <p className="page-subtitle">
            Suscripciones, pruebas, servicios y demás pagos recurrentes, con aviso antes de cada
            cobro.
          </p>
        </div>
        <button className="btn-primary" onClick={() => setModal({ rule: null, kind: tab })}>
          <Icon name="plus" />
          Nuevo
        </button>
      </div>

      {/* REC-13: costo mensual equivalente */}
      {s && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          <div className="card p-4">
            <p className="text-xs text-ink-muted">Suscripciones al mes</p>
            <p className="tabular mt-1 text-xl font-semibold">
              {s.is_approximate && "≈ "}
              {formatMoney(s.monthly_total, s.currency)}
            </p>
          </div>
          <div className="card p-4">
            <p className="text-xs text-ink-muted">Al año</p>
            <p className="tabular mt-1 text-xl font-semibold">
              {s.is_approximate && "≈ "}
              {formatMoney(s.yearly_total, s.currency)}
            </p>
          </div>
          <div className="card col-span-2 p-4 md:col-span-1">
            <p className="text-xs text-ink-muted">Activas</p>
            <p className="mt-1 text-xl font-semibold">
              {s.active_count}
              {s.trial_count > 0 && (
                <span className="ml-2 text-sm font-normal text-amber-700 dark:text-amber-300">
                  + {s.trial_count} en prueba
                </span>
              )}
            </p>
          </div>
          {s.missing_rate && (
            <p className="col-span-2 text-xs text-amber-700 dark:text-amber-300 md:col-span-3">
              Sin tipo de cambio de hoy: las suscripciones en otra moneda no se incluyen en el
              total.
            </p>
          )}
        </div>
      )}

      {/* REC-11: recibos por capturar */}
      {bills.length > 0 && (
        <section className="card p-4 sm:p-5">
          <h2 className="text-base font-semibold tracking-tight">
            Por capturar
            <span className="ml-2 rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-800 dark:text-amber-200">
              {bills.length}
            </span>
          </h2>
          <p className="text-sm text-ink-muted">
            Escribe el monto del recibo para registrarlo como gasto.
          </p>
          <ul className="divide-y divide-line">
            {bills.map((b) => (
              <PendingBillRow
                key={`${b.rule_id}-${b.scheduled_date}`}
                bill={b}
                accountName={accountNames.get(b.account_id) ?? ""}
              />
            ))}
          </ul>
        </section>
      )}

      {/* Pestañas fuera de la tarjeta: alineadas con el resto de la página y,
          en móvil, tres botones iguales en una sola fila. */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div
          className="grid grid-cols-3 rounded-lg border border-line bg-card p-0.5 sm:inline-grid sm:w-auto"
          role="group"
          aria-label="Tipo"
        >
          {TABS.map((t) => (
            <button
              key={t.kind}
              type="button"
              aria-pressed={tab === t.kind}
              onClick={() => setTab(t.kind)}
              className={`flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1.5 text-sm transition sm:px-4 ${
                tab === t.kind ? "bg-muted font-medium text-ink" : "text-ink-muted hover:text-ink"
              }`}
            >
              {t.short ? (
                <>
                  <span className="sm:hidden">{t.short}</span>
                  <span className="hidden sm:inline">{t.label}</span>
                </>
              ) : (
                t.label
              )}
              {counts[t.kind] > 0 && (
                <span className="text-xs text-ink-subtle">{counts[t.kind]}</span>
              )}
            </button>
          ))}
        </div>
        {hiddenCount > 0 && (
          <label className="flex items-center gap-1.5 text-sm text-ink-muted">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(e) => setShowInactive(e.target.checked)}
            />
            Mostrar pausadas y canceladas ({hiddenCount})
          </label>
        )}
      </div>

      {rules.isPending ? (
        <div className="card grid place-items-center py-10">
          <Spinner />
        </div>
      ) : visible.length === 0 ? (
        <p className="card px-4 py-8 text-center text-sm text-ink-muted">{current.empty}</p>
      ) : tab === "generic" ? (
        renderRules()
      ) : (
        <section className="card px-4 sm:px-5">{renderRules()}</section>
      )}

      <Modal
        open={modal !== null}
        onClose={() => setModal(null)}
        title={
          modal?.rule
            ? `Editar ${modal.rule.description}`
            : modal?.kind === "subscription"
              ? "Nueva suscripción"
              : modal?.kind === "bill"
                ? "Nuevo servicio"
                : "Nuevo recurrente"
        }
        size="xl"
      >
        {modal && (
          <RuleForm
            key={modal.rule?.id ?? `new-${modal.kind}`}
            kind={modal.kind}
            rule={modal.rule}
            accounts={accountList}
            onDone={() => setModal(null)}
          />
        )}
      </Modal>

      <Modal open={deleting !== null} onClose={() => setDeleting(null)} title="Eliminar">
        {deleting && (
          <div className="space-y-4">
            <p className="text-sm">
              ¿Eliminar <strong>{deleting.description}</strong>? Los cobros ya registrados se
              conservan en tu historial.
              {deleting.kind !== "generic" &&
                " Si solo dejaste de pagarla, mejor cancélala: así conservas la regla y su historial."}
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setDeleting(null)}>
                Volver
              </button>
              <button
                type="button"
                className="btn-danger"
                disabled={remove.isPending}
                onClick={() => remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
              >
                Eliminar
              </button>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        title={
          confirming?.action === "pause"
            ? "Pausar"
            : confirming?.rule.kind === "bill"
              ? "Cancelar servicio"
              : "Cancelar suscripción"
        }
      >
        {confirming && (
          <div className="space-y-4">
            {confirming.action === "pause" ? (
              <p className="text-sm">
                ¿Pausar <strong>{confirming.rule.description}</strong>? Mientras esté pausada no se
                registran cobros ni recibes avisos. Puedes reanudarla cuando quieras.
              </p>
            ) : (
              <>
                <p className="text-sm">
                  ¿Cancelar <strong>{confirming.rule.description}</strong>? Ya no se registrarán
                  cobros y sus avisos pendientes se eliminan. El historial se conserva y puedes
                  reactivarla después.
                </p>
                <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
                  Esto solo la cancela en Finanzas: recuerda cancelarla también con el proveedor.
                  {confirming.rule.cancel_url && /^https?:\/\//i.test(confirming.rule.cancel_url) && (
                    <>
                      {" "}
                      <a
                        className="font-medium underline"
                        href={confirming.rule.cancel_url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Ir a cancelar
                      </a>
                    </>
                  )}
                </p>
              </>
            )}
            {(pauseRule.error ?? cancelRule.error) && (
              <p className="text-sm text-red-600 dark:text-red-400">
                {errorText(pauseRule.error ?? cancelRule.error)}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setConfirming(null)}>
                Volver
              </button>
              <button
                type="button"
                className={confirming.action === "pause" ? "btn-primary" : "btn-danger"}
                disabled={confirmPending}
                onClick={runConfirmed}
              >
                {confirming.action === "pause" ? "Pausar" : "Sí, cancelar"}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
