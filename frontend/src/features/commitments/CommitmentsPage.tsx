// Compromisos con proveedores (CXP-01..08): servicios contratados con saldo por
// liquidar (salón, fotógrafo, banda). Cada abono es un gasto normal ligado al
// compromiso (CXP-03); "Pagado por un tercero" registra el regalo y el abono a
// la vez (CXP-04). El calendario de pagos se cubre en orden de fecha (CXP-02).
import { useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { hasBalance, useAccounts, type AccountOut } from "../../api/accounts";
import { useCategories } from "../../api/catalogs";
import {
  useCommitments,
  useCreateCommitment,
  useDeleteCommitment,
  usePayByThirdParty,
  useUpdateCommitment,
  type CommitmentBody,
  type CommitmentOut,
} from "../../api/commitments";
import { useEvents } from "../../api/events";
import { useCreateTransaction } from "../../api/transactions";
import { formatMoney, isPositiveAmount, subtractMoney, sumMoney } from "../../lib/money";
import { formatDate, todayISO } from "../../lib/dates";
import Icon from "../../components/ui/Icon";
import Modal from "../../components/ui/Modal";
import Spinner from "../../components/ui/Spinner";

const CURRENCIES = ["MXN", "USD"];

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
      pattern="^\d+(\.\d{1,2})?$"
      placeholder={placeholder}
      required={required}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function useExpenseCategories() {
  const categories = useCategories();
  return useMemo(
    () => (categories.data ?? []).filter((c) => c.kind === "expense"),
    [categories.data],
  );
}

type ScheduleDraft = { due_date: string; amount: string };

// CXP-01/02: alta y edición, con calendario opcional.
function CommitmentForm({
  commitment,
  defaultEventId,
  onDone,
}: {
  commitment: CommitmentOut | null;
  defaultEventId: string;
  onDone: () => void;
}) {
  const create = useCreateCommitment();
  const update = useUpdateCommitment();
  const remove = useDeleteCommitment();
  const events = useEvents(true);
  const categories = useExpenseCategories();
  const [name, setName] = useState(commitment?.name ?? "");
  const [total, setTotal] = useState(commitment?.total_amount ?? "");
  const [currency, setCurrency] = useState(commitment?.currency ?? "MXN");
  const [eventId, setEventId] = useState(commitment?.event_id ?? defaultEventId);
  const [categoryId, setCategoryId] = useState(commitment?.category_id ?? "");
  const [paidBefore, setPaidBefore] = useState(
    commitment && commitment.paid_before_tracking !== "0.00" ? commitment.paid_before_tracking : "",
  );
  const [dueDate, setDueDate] = useState(commitment?.due_date ?? "");
  const [notes, setNotes] = useState(commitment?.notes ?? "");
  const [schedule, setSchedule] = useState<ScheduleDraft[]>(
    (commitment?.schedule ?? []).map((r) => ({ due_date: r.due_date, amount: r.amount })),
  );
  const [error, setError] = useState<string | null>(null);
  const pending = create.isPending || update.isPending || remove.isPending;
  const locked = (commitment?.abonos ?? 0) > 0; // CXP-06: moneda y evento fijos

  const remaining =
    total && isPositiveAmount(total) ? subtractMoney(total, paidBefore || "0") : null;
  const scheduled = sumMoney(schedule.filter((r) => isPositiveAmount(r.amount)).map((r) => r.amount));

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!isPositiveAmount(total)) {
      setError("El total pactado debe ser mayor a 0.");
      return;
    }
    if (schedule.some((r) => !r.due_date || !isPositiveAmount(r.amount))) {
      setError("Cada pago del calendario necesita fecha y un monto mayor a 0.");
      return;
    }
    const body: CommitmentBody = {
      name: name.trim(),
      total_amount: total,
      paid_before_tracking: paidBefore || "0",
      category_id: categoryId || null,
      due_date: dueDate || null,
      notes: notes.trim() || null,
      schedule,
    };
    if (!locked) {
      body.currency = currency;
      body.event_id = eventId || null;
    }
    try {
      if (commitment) await update.mutateAsync({ id: commitment.id, ...body });
      else await create.mutateAsync(body);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div className="col-span-2">
        <label className="label" htmlFor="c-name">Proveedor o concepto</label>
        <input
          id="c-name"
          className="input"
          required
          maxLength={120}
          placeholder="Salón, Fotógrafo, Banda…"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="c-total">Total pactado</label>
        <MoneyInput id="c-total" value={total} onChange={setTotal} required />
      </div>
      <div>
        <label className="label" htmlFor="c-currency">Moneda</label>
        <select
          id="c-currency"
          className="input"
          disabled={locked}
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
        >
          {CURRENCIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </div>
      <div>
        <label className="label" htmlFor="c-event">Evento</label>
        <select
          id="c-event"
          className="input"
          disabled={locked}
          value={eventId}
          onChange={(e) => setEventId(e.target.value)}
        >
          <option value="">Sin evento</option>
          {(events.data ?? [])
            .filter((s) => s.event.is_active || s.event.id === eventId)
            .map((s) => (
              <option key={s.event.id} value={s.event.id}>
                {s.event.name}
              </option>
            ))}
        </select>
      </div>
      <div>
        <label className="label" htmlFor="c-category">Categoría de los abonos</label>
        <select
          id="c-category"
          className="input"
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
        >
          <option value="">Elegir al abonar</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="label" htmlFor="c-before">Abonado antes de la app</label>
        <MoneyInput id="c-before" value={paidBefore} onChange={setPaidBefore} placeholder="0.00" />
      </div>
      <div>
        <label className="label" htmlFor="c-due">Fecha de liquidación</label>
        <input
          id="c-due"
          type="date"
          className="input"
          value={dueDate}
          onChange={(e) => setDueDate(e.target.value)}
        />
      </div>
      {locked && (
        <p className="col-span-2 -mt-1 text-xs text-ink-muted md:col-span-4">
          Ya tiene abonos: la moneda y el evento quedan fijos.
        </p>
      )}

      <fieldset className="col-span-2 space-y-2 border-t border-line pt-3 md:col-span-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <legend className="text-sm font-medium">Calendario de pagos (opcional)</legend>
          {remaining !== null && (
            <span className="text-xs text-ink-muted">
              Calendarizado {formatMoney(scheduled, currency)} de {formatMoney(remaining, currency)} por
              pagar
            </span>
          )}
        </div>
        {schedule.map((row, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <input
              type="date"
              aria-label="Fecha del pago"
              className="input w-auto"
              value={row.due_date}
              onChange={(e) =>
                setSchedule(schedule.map((r, j) => (j === i ? { ...r, due_date: e.target.value } : r)))
              }
            />
            <div className="w-36">
              <MoneyInput
                value={row.amount}
                onChange={(v) => setSchedule(schedule.map((r, j) => (j === i ? { ...r, amount: v } : r)))}
              />
            </div>
            <button
              type="button"
              aria-label="Quitar pago"
              className="rounded p-1.5 text-ink-muted hover:bg-muted hover:text-red-500"
              onClick={() => setSchedule(schedule.filter((_, j) => j !== i))}
            >
              <Icon name="x" className="size-4" />
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn-ghost text-sm"
          onClick={() => setSchedule([...schedule, { due_date: "", amount: "" }])}
        >
          <Icon name="plus" className="size-3.5" />
          Agregar pago
        </button>
      </fieldset>

      <div className="col-span-2 md:col-span-4">
        <label className="label" htmlFor="c-notes">Notas</label>
        <textarea
          id="c-notes"
          className="input min-h-16"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>

      {error && <p className="col-span-2 text-sm text-red-600 dark:text-red-400 md:col-span-4">{error}</p>}
      <div className="col-span-2 flex flex-wrap items-center justify-between gap-2 pt-1 md:col-span-4">
        {commitment ? (
          <div className="flex gap-3">
            <button
              type="button"
              className="text-sm font-medium text-ink-muted hover:text-red-600 hover:underline dark:hover:text-red-400"
              disabled={pending}
              title="Solo si no tiene abonos"
              onClick={() => void run(() => remove.mutateAsync(commitment.id))}
            >
              Eliminar
            </button>
            <button
              type="button"
              className="text-sm font-medium text-ink-muted hover:text-ink hover:underline"
              disabled={pending}
              onClick={() =>
                void run(() =>
                  update.mutateAsync({ id: commitment.id, is_canceled: !commitment.is_canceled }),
                )
              }
            >
              {commitment.is_canceled ? "Reactivar" : "Cancelar compromiso"}
            </button>
          </div>
        ) : (
          <span />
        )}
        <div className="flex gap-2">
          <button type="button" className="btn-secondary" onClick={onDone}>
            Cerrar
          </button>
          <button className="btn-primary" disabled={pending}>
            {commitment ? "Guardar cambios" : "Crear compromiso"}
          </button>
        </div>
      </div>
    </form>
  );
}

// CXP-03: un abono es un gasto normal ligado al compromiso.
function AbonoForm({
  commitment,
  accounts,
  onDone,
}: {
  commitment: CommitmentOut;
  accounts: AccountOut[];
  onDone: () => void;
}) {
  const create = useCreateTransaction();
  const categories = useExpenseCategories();
  const sameCurrency = accounts.filter((a) => a.is_active && a.currency === commitment.currency);
  const [amount, setAmount] = useState(commitment.pending);
  const [date, setDate] = useState(todayISO);
  const [accountId, setAccountId] = useState("");
  const [categoryId, setCategoryId] = useState(commitment.category_id ?? "");
  const [description, setDescription] = useState(`Abono: ${commitment.name}`);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!isPositiveAmount(amount)) {
      setError("El monto debe ser mayor a 0.");
      return;
    }
    try {
      await create.mutateAsync({
        type: "expense",
        date,
        amount,
        currency: commitment.currency,
        description,
        category_id: categoryId,
        account_id: accountId,
        commitment_id: commitment.id,
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3">
      <p className="col-span-2 text-sm text-ink-muted">
        Pendiente: <strong className="text-ink">{formatMoney(commitment.pending, commitment.currency)}</strong>.
        El abono cuenta como gasto en su fecha.
      </p>
      <div>
        <label className="label" htmlFor="a-amount">Monto ({commitment.currency})</label>
        <MoneyInput id="a-amount" value={amount} onChange={setAmount} required />
      </div>
      <div>
        <label className="label" htmlFor="a-date">Fecha</label>
        <input
          id="a-date"
          type="date"
          className="input"
          required
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="a-account">Pagado con</label>
        <select
          id="a-account"
          className="input"
          required
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
        >
          <option value="">Selecciona…</option>
          {sameCurrency.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="label" htmlFor="a-category">Categoría</label>
        <select
          id="a-category"
          className="input"
          required
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
        >
          <option value="">Selecciona…</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>
      <div className="col-span-2">
        <label className="label" htmlFor="a-desc">Descripción</label>
        <input
          id="a-desc"
          className="input"
          maxLength={200}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <p className="col-span-2 text-xs text-ink-muted">
        Si tus papás u otro acreedor lo pagaron directo, elige la cuenta de ese préstamo: la deuda
        crece y el gasto queda registrado.
      </p>
      {error && <p className="col-span-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="col-span-2 flex justify-end gap-2">
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cancelar
        </button>
        <button className="btn-primary" disabled={create.isPending}>
          Registrar abono
        </button>
      </div>
    </form>
  );
}

// CXP-04: alguien le pagó directo al proveedor como regalo.
function ThirdPartyForm({
  commitment,
  accounts,
  onDone,
}: {
  commitment: CommitmentOut;
  accounts: AccountOut[];
  onDone: () => void;
}) {
  const pay = usePayByThirdParty();
  const categories = useExpenseCategories();
  // TAR-01: cuentas con saldo (no TDC) en la moneda del compromiso.
  const eligible = accounts.filter(
    (a) => a.is_active && hasBalance(a.behavior) && a.currency === commitment.currency,
  );
  const [amount, setAmount] = useState(commitment.pending);
  const [date, setDate] = useState(todayISO);
  const [accountId, setAccountId] = useState(
    () => (eligible.find((a) => a.behavior === "cash") ?? eligible[0])?.id ?? "",
  );
  const [categoryId, setCategoryId] = useState(commitment.category_id ?? "");
  const [who, setWho] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!isPositiveAmount(amount)) {
      setError("El monto debe ser mayor a 0.");
      return;
    }
    try {
      await pay.mutateAsync({
        id: commitment.id,
        amount,
        date,
        account_id: accountId,
        category_id: categoryId || null,
        description: who ? `${commitment.name} (pagado por ${who})` : "",
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3">
      <p className="col-span-2 text-sm text-ink-muted">
        Se registran a la vez un <strong className="text-ink">ingreso «Regalos recibidos»</strong> y
        el <strong className="text-ink">abono</strong>, por el mismo monto: el evento refleja el gasto
        y el regalo, y el saldo de la cuenta no cambia.
      </p>
      <div className="col-span-2">
        <label className="label" htmlFor="t-who">¿Quién pagó? (opcional)</label>
        <input
          id="t-who"
          className="input"
          maxLength={80}
          placeholder="Tío Juan"
          value={who}
          onChange={(e) => setWho(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="t-amount">Monto ({commitment.currency})</label>
        <MoneyInput id="t-amount" value={amount} onChange={setAmount} required />
      </div>
      <div>
        <label className="label" htmlFor="t-date">Fecha</label>
        <input
          id="t-date"
          type="date"
          className="input"
          required
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="t-account">Registrar en</label>
        <select
          id="t-account"
          className="input"
          required
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
        >
          <option value="">Selecciona…</option>
          {eligible.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="label" htmlFor="t-category">Categoría del gasto</label>
        <select
          id="t-category"
          className="input"
          required
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
        >
          <option value="">Selecciona…</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>
      {error && <p className="col-span-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="col-span-2 flex justify-end gap-2">
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cancelar
        </button>
        <button className="btn-primary" disabled={pay.isPending}>
          Registrar regalo y abono
        </button>
      </div>
    </form>
  );
}

const STATUS_STYLES: Record<CommitmentOut["status"], string> = {
  pending: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  paid: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  canceled: "bg-muted text-ink-muted",
};
const STATUS_LABELS: Record<CommitmentOut["status"], string> = {
  pending: "Pendiente",
  paid: "Liquidado",
  canceled: "Cancelado",
};

function CommitmentCard({
  commitment,
  eventName,
  onEdit,
  onAbono,
  onThirdParty,
}: {
  commitment: CommitmentOut;
  eventName: string | null;
  onEdit: () => void;
  onAbono: () => void;
  onThirdParty: () => void;
}) {
  const c = commitment;
  // Solo proporción visual de la barra (no aritmética de dinero, GLO-01).
  const progress = Math.min(100, (Number(c.paid) / Number(c.total_amount)) * 100);
  const open = c.status === "pending";

  return (
    <section className={`card p-4 sm:p-5 ${c.status === "canceled" ? "opacity-70" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex flex-wrap items-center gap-2 text-lg font-semibold tracking-tight">
            <span className="truncate">{c.name}</span>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                c.is_overdue ? "bg-red-500/15 text-red-700 dark:text-red-300" : STATUS_STYLES[c.status]
              }`}
            >
              {c.is_overdue ? "Vencido" : STATUS_LABELS[c.status]}
            </span>
            {eventName && (
              <span className="rounded-full bg-violet-500/15 px-2 py-0.5 text-xs font-medium text-violet-800 dark:text-violet-200">
                {eventName}
              </span>
            )}
          </h2>
          <p className="text-sm text-ink-muted">
            {[
              `${c.abonos} ${c.abonos === 1 ? "abono" : "abonos"}`,
              c.due_date ? `liquidar antes del ${formatDate(c.due_date)}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5 [&>*]:h-8 [&>*]:px-2.5">
          {open && (
            <>
              <button className="btn-primary" onClick={onAbono}>
                Abonar
              </button>
              <button className="btn-secondary" onClick={onThirdParty} title="Alguien le pagó directo al proveedor">
                Pagado por un tercero
              </button>
            </>
          )}
          <Link className="btn-secondary" to={`/transacciones?compromiso=${c.id}`}>
            Abonos
          </Link>
          <button className="btn-secondary px-2.5" onClick={onEdit} aria-label="Editar" title="Editar">
            <Icon name="pencil" className="size-3.5" />
          </button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2">
        {[
          ["Total pactado", c.total_amount],
          ["Pagado", c.paid],
          ["Pendiente", c.pending],
        ].map(([label, value]) => (
          <div key={label} className="min-w-0 rounded-lg border border-line bg-surface px-2.5 py-2.5 sm:px-3">
            <p className="truncate text-xs text-ink-muted">{label}</p>
            <p className="tabular mt-0.5 text-sm font-semibold sm:text-base">
              {formatMoney(value, c.currency)}
            </p>
          </div>
        ))}
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-accent" style={{ width: `${progress}%` }} />
      </div>
      {c.paid_before_tracking !== "0.00" && (
        <p className="mt-1 text-xs text-ink-muted">
          Incluye {formatMoney(c.paid_before_tracking, c.currency)} abonados antes de usar la app.
        </p>
      )}

      {c.schedule.length > 0 && (
        <ul className="mt-3 divide-y divide-line text-sm">
          {c.schedule.map((row) => (
            <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
              <span className="text-ink-muted">{formatDate(row.due_date)}</span>
              <span className="flex items-center gap-2">
                <span className="tabular">{formatMoney(row.amount, c.currency)}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs ${
                    row.is_covered
                      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                      : row.is_overdue
                        ? "bg-red-500/15 text-red-700 dark:text-red-300"
                        : row.covered !== "0.00"
                          ? "bg-amber-500/15 text-amber-800 dark:text-amber-200"
                          : "bg-muted text-ink-muted"
                  }`}
                >
                  {row.is_covered
                    ? "Cubierto"
                    : row.is_overdue
                      ? `Vencido · faltan ${formatMoney(row.uncovered, c.currency)}`
                      : row.covered !== "0.00"
                        ? `Faltan ${formatMoney(row.uncovered, c.currency)}`
                        : "Por pagar"}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {open && c.unscheduled_pending !== "0.00" && (
        <p className="mt-2 text-xs text-ink-muted">
          {formatMoney(c.unscheduled_pending, c.currency)} sin calendarizar
          {c.due_date ? ` (se esperan para el ${formatDate(c.due_date)})` : " y sin fecha: no entran al pronóstico"}.
        </p>
      )}
      {c.notes && <p className="mt-2 whitespace-pre-line text-sm text-ink-muted">{c.notes}</p>}
    </section>
  );
}

export default function CommitmentsPage() {
  // EVT: `?evento=<id>` (desde la página de Eventos) filtra por evento.
  const [searchParams] = useSearchParams();
  const [eventFilter, setEventFilter] = useState(() => searchParams.get("evento") ?? "");
  const [showClosed, setShowClosed] = useState(false);
  const commitments = useCommitments(showClosed);
  const events = useEvents(true);
  const accounts = useAccounts();
  const eventNames = useMemo(
    () => new Map((events.data ?? []).map((s) => [s.event.id, s.event.name])),
    [events.data],
  );
  const [modal, setModal] = useState<
    | { kind: "new" }
    | { kind: "edit" | "abono" | "third"; commitment: CommitmentOut }
    | null
  >(null);

  const list = (commitments.data ?? []).filter((c) => !eventFilter || c.event_id === eventFilter);
  const pendingByCurrency = useMemo(() => {
    const groups = new Map<string, string[]>();
    for (const c of list) {
      if (c.status !== "pending") continue;
      groups.set(c.currency, [...(groups.get(c.currency) ?? []), c.pending]);
    }
    return [...groups.entries()].map(([currency, values]) => [currency, sumMoney(values)] as const);
  }, [list]);

  const accountList = accounts.data ?? [];
  const title =
    modal?.kind === "new"
      ? "Nuevo compromiso"
      : modal?.kind === "edit"
        ? `Editar ${modal.commitment.name}`
        : modal?.kind === "abono"
          ? `Abonar a ${modal.commitment.name}`
          : modal?.kind === "third"
            ? `${modal.commitment.name}: pagado por un tercero`
            : "";

  return (
    <div className="page">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="page-title">Compromisos</h1>
          <p className="page-subtitle">
            Servicios contratados con saldo por liquidar: anticipos, abonos y fechas de pago.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(events.data ?? []).length > 0 && (
            <select
              className="input w-auto"
              aria-label="Evento"
              value={eventFilter}
              onChange={(e) => setEventFilter(e.target.value)}
            >
              <option value="">Todos los eventos</option>
              {(events.data ?? []).map((s) => (
                <option key={s.event.id} value={s.event.id}>
                  {s.event.name}
                </option>
              ))}
            </select>
          )}
          <label className="mr-1 flex items-center gap-1.5 text-sm text-ink-muted">
            <input
              type="checkbox"
              checked={showClosed}
              onChange={(e) => setShowClosed(e.target.checked)}
            />
            Mostrar liquidados
          </label>
          <button className="btn-primary" onClick={() => setModal({ kind: "new" })}>
            <Icon name="plus" />
            Nuevo compromiso
          </button>
        </div>
      </div>

      {pendingByCurrency.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {pendingByCurrency.map(([currency, total]) => (
            <div key={currency} className="rounded-lg border border-line bg-surface px-3 py-2.5">
              <p className="text-xs text-ink-muted">Por pagar · {currency}</p>
              <p className="tabular mt-0.5 text-lg font-semibold">{formatMoney(total, currency)}</p>
            </div>
          ))}
        </div>
      )}

      <Modal open={modal !== null} onClose={() => setModal(null)} title={title} size={modal?.kind === "new" || modal?.kind === "edit" ? "xl" : "lg"}>
        {modal?.kind === "new" && (
          <CommitmentForm commitment={null} defaultEventId={eventFilter} onDone={() => setModal(null)} />
        )}
        {modal?.kind === "edit" && (
          <CommitmentForm
            key={modal.commitment.id}
            commitment={modal.commitment}
            defaultEventId=""
            onDone={() => setModal(null)}
          />
        )}
        {modal?.kind === "abono" && (
          <AbonoForm commitment={modal.commitment} accounts={accountList} onDone={() => setModal(null)} />
        )}
        {modal?.kind === "third" && (
          <ThirdPartyForm commitment={modal.commitment} accounts={accountList} onDone={() => setModal(null)} />
        )}
      </Modal>

      {commitments.isPending ? (
        <div className="card flex h-48 flex-col items-center justify-center gap-3 p-8 text-center text-sm text-ink-muted">
          <Spinner className="size-7" />
          Cargando compromisos…
        </div>
      ) : commitments.isError ? (
        <div className="card flex h-48 flex-col items-center justify-center gap-3 p-8 text-center text-sm text-ink-muted">
          No se pudieron cargar los compromisos.
          <button className="btn-secondary" onClick={() => commitments.refetch()}>
            Reintentar
          </button>
        </div>
      ) : list.length === 0 ? (
        <button
          type="button"
          onClick={() => setModal({ kind: "new" })}
          className="grid w-full place-items-center gap-2 rounded-xl border border-dashed border-line-strong p-10 text-center text-sm text-ink-muted transition hover:bg-card hover:text-ink"
        >
          <Icon name="target" className="size-6" />
          <span className="font-medium text-ink">
            {showClosed || eventFilter ? "Sin compromisos aquí" : "Sin compromisos pendientes"}
          </span>
          <span className="max-w-md">
            Registra lo que pactaste con un proveedor y lo que ya abonaste; cada abono que registres
            aquí cuenta como gasto en su fecha.
          </span>
        </button>
      ) : (
        <div className="card-grid">
          {list.map((c) => (
            <CommitmentCard
              key={c.id}
              commitment={c}
              eventName={c.event_id ? (eventNames.get(c.event_id) ?? null) : null}
              onEdit={() => setModal({ kind: "edit", commitment: c })}
              onAbono={() => setModal({ kind: "abono", commitment: c })}
              onThirdParty={() => setModal({ kind: "third", commitment: c })}
            />
          ))}
        </div>
      )}
    </div>
  );
}
