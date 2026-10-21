// Registro de gastos (R1): captura rápida <10 s, bandeja "Por confirmar"
// (REC-03) y lista con filtros (TXN-01..03). TXN-08/TXN-09: validaciones y avisos.
// TXN-11: aviso de posible duplicado + confirmación visual del alta.
// TXN-12: búsqueda por descripción y periodo por mes o rango libre.
// TAR-03/10: se paga con una cuenta y en su moneda. TXN-13/14: transferencias
// entre monedas (monto recibido) y con comisión. EVT-02/05: evento opcional
// por movimiento y filtro por evento. CXP-03: abonos a compromisos (filtro,
// etiqueta y vínculo en la edición).
import { useEffect, useMemo, useState, type FormEvent, type KeyboardEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useCategories } from "../../api/catalogs";
import {
  hasBalance,
  isLoan,
  useAccounts,
  type AccountBehavior,
  type AccountOut,
} from "../../api/accounts";
import {
  fetchPossibleDuplicates,
  useConfirmTransaction,
  useCreateTransaction,
  useDeleteTransaction,
  useUpdateTransaction,
  useTransactions,
  type TransactionBody,
  type TransactionOut,
} from "../../api/transactions";
import { useEvents, useSetTransactionEvent } from "../../api/events";
import { useCommitments } from "../../api/commitments";
import {
  useRecurringRules,
  useUpdateRecurringRule,
  type RecurringRuleOut,
} from "../../api/recurring";
import { useSpace } from "../spaces/SpaceProvider";
import { convertWithRate, formatMoney, impliedRate, isPositiveAmount, sanitizeDecimal } from "../../lib/money";
import { formatDate } from "../../lib/dates";
import Modal from "../../components/ui/Modal";
import Icon from "../../components/ui/Icon";

type TxnType = "expense" | "income" | "transfer";

const TYPE_LABELS: Record<TxnType, string> = {
  expense: "Gasto",
  income: "Ingreso",
  transfer: "Transferencia",
};

function todayISO(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

const CREATED_LABELS: Record<TxnType, string> = {
  expense: "Gasto registrado",
  income: "Ingreso registrado",
  transfer: "Transferencia registrada",
};

const PAGE_SIZE = 100;
const RANGE_PRESETS = [2, 3, 6] as const;

function monthBounds(ym: string): { from: string; to: string } {
  const [year, month] = ym.split("-").map(Number);
  const lastDay = new Date(year, month, 0).getDate();
  return { from: `${ym}-01`, to: `${ym}-${String(lastDay).padStart(2, "0")}` };
}

function shiftMonth(ym: string, delta: number): string {
  const [year, month] = ym.split("-").map(Number);
  const d = new Date(year, month - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** TXN-12: del día 1 de hace N−1 meses al último día del mes actual. */
function lastMonthsRange(n: number): { from: string; to: string } {
  const current = todayISO().slice(0, 7);
  return { from: monthBounds(shiftMonth(current, -(n - 1))).from, to: monthBounds(current).to };
}

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

function detectCutoffCollision(
  txnDate: string,
  card: AccountOut | undefined,
): { defaultHint: "current" | "next" } | null {
  if (!txnDate || !card || card.behavior !== "credit" || !card.statement_day) return null;
  const [year, month, day] = txnDate.split("-").map(Number);
  const cutoffDay = card.statement_day_is_last
    ? new Date(year, month, 0).getDate()
    : card.statement_day;
  if (day !== cutoffDay) return null;
  return { defaultHint: card.cutoff_day_policy === "next_cycle" ? "next" : "current" };
}

// Selector de cuentas agrupado como en la página de Cuentas.
const ACCOUNT_GROUPS: { label: string; behaviors: AccountBehavior[] }[] = [
  { label: "Efectivo y cuentas", behaviors: ["cash", "debit", "prepaid"] },
  { label: "Ahorro", behaviors: ["savings"] },
  { label: "Tarjetas de crédito", behaviors: ["credit"] },
  { label: "Préstamos", behaviors: ["loan"] }, // TAR-11
];

function AccountOptions({
  accounts,
  exclude,
  baseCurrency,
}: {
  accounts: AccountOut[];
  exclude?: string;
  baseCurrency: string;
}) {
  return (
    <>
      {ACCOUNT_GROUPS.map((group) => {
        const items = accounts.filter(
          (a) => a.id !== exclude && a.behavior && group.behaviors.includes(a.behavior),
        );
        if (items.length === 0) return null;
        return (
          <optgroup key={group.label} label={group.label}>
            {items.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {a.currency !== baseCurrency ? ` (${a.currency})` : ""}
              </option>
            ))}
          </optgroup>
        );
      })}
    </>
  );
}

// Enter dentro de un campo no guarda por accidente: solo el botón envía.
function blockEnterSubmit(e: KeyboardEvent<HTMLFormElement>) {
  if (e.key === "Enter" && e.target instanceof HTMLInputElement) e.preventDefault();
}

// TXN-14: comisión en la moneda de la cuenta origen.
function FeeField({
  source,
  fee,
  setFee,
  className,
  placeholder = "0.00",
}: {
  source: AccountOut | undefined;
  fee: string;
  setFee: (v: string) => void;
  className?: string;
  placeholder?: string;
}) {
  return (
    <div className={className}>
      <label className="label">Comisión{source ? ` (${source.currency})` : ""}</label>
      <input
        className="input"
        inputMode="decimal"
        pattern="^\d+(\.\d{1,2})?$"
        placeholder={placeholder}
        value={fee}
        onChange={(e) => setFee(sanitizeDecimal(e.target.value))}
      />
    </div>
  );
}

// TXN-13/14: monto recibido cuando las monedas difieren y comisión opcional.
function TransferExtras({
  source,
  target,
  amount,
  amountTo,
  setAmountTo,
  fee,
  setFee,
  showFee = true,
}: {
  source: AccountOut | undefined;
  target: AccountOut | undefined;
  amount: string;
  amountTo: string;
  setAmountTo: (v: string) => void;
  fee: string;
  setFee: (v: string) => void;
  showFee?: boolean;
}) {
  const crossCurrency = !!source && !!target && source.currency !== target.currency;
  // Tipo de cambio editable (p. ej. el de ARQ): al escribirlo calcula "Recibe";
  // al escribir "Recibe" se muestra el implícito. No se persiste (TXN-13).
  const [rateText, setRateText] = useState<string | null>(null);
  const implied = crossCurrency ? impliedRate(amountTo, amount) : null;
  useEffect(() => {
    if (rateText === null) return;
    const converted = convertWithRate(amount, rateText);
    if (converted !== null && converted !== amountTo) setAmountTo(converted);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [amount]);
  useEffect(() => {
    if (!crossCurrency) setRateText(null);
  }, [crossCurrency]);
  return (
    <>
      {crossCurrency && (
        <>
          <div>
            <label className="label">Recibe ({target.currency})</label>
            <input
              className="input"
              inputMode="decimal"
              pattern="^\d+(\.\d{1,2})?$"
              placeholder="0.00"
              required
              value={amountTo}
              onChange={(e) => {
                setRateText(null);
                setAmountTo(sanitizeDecimal(e.target.value));
              }}
            />
          </div>
          <div>
            <label className="label">Tipo de cambio</label>
            <input
              className="input"
              inputMode="decimal"
              placeholder="opcional"
              value={rateText ?? implied ?? ""}
              onChange={(e) => {
                const v = sanitizeDecimal(e.target.value, 6);
                setRateText(v);
                const converted = convertWithRate(amount, v);
                if (converted !== null) setAmountTo(converted);
              }}
            />
          </div>
        </>
      )}
      {showFee && <FeeField source={source} fee={fee} setFee={setFee} placeholder="opcional" />}
    </>
  );
}

// EVT-02: selector de evento (solo activos; conserva el actual si ya está inactivo).
function EventSelect({
  id,
  value,
  onChange,
  events,
}: {
  id?: string;
  value: string;
  onChange: (v: string) => void;
  events: { id: string; name: string; is_active: boolean }[];
}) {
  return (
    <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Sin evento</option>
      {events
        .filter((ev) => ev.is_active || ev.id === value)
        .map((ev) => (
          <option key={ev.id} value={ev.id}>
            {ev.name}
            {ev.is_active ? "" : " (inactivo)"}
          </option>
        ))}
    </select>
  );
}

export default function TransactionsPage() {
  const { activeSpace } = useSpace();
  const categories = useCategories();
  const accounts = useAccounts();
  const accountList = useMemo(() => accounts.data ?? [], [accounts.data]);
  const accountById = useMemo(
    () => new Map(accountList.map((a) => [a.id, a])),
    [accountList],
  );

  const [type, setType] = useState<TxnType>("expense");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(todayISO);
  const [categoryId, setCategoryId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [accountToId, setAccountToId] = useState("");
  const [description, setDescription] = useState("");
  const [amountTo, setAmountTo] = useState(""); // TXN-13
  const [feeAmount, setFeeAmount] = useState(""); // TXN-14
  const [formError, setFormError] = useState<string | null>(null);
  const [cycleHint, setCycleHint] = useState<"current" | "next" | null>(null);
  // EVT-02: se conserva entre altas para capturar varios gastos del mismo evento.
  const [eventId, setEventId] = useState("");
  const [withFee, setWithFee] = useState(false); // toggle de comisión (TXN-14)
  const [withEvent, setWithEvent] = useState(false); // toggle de evento (EVT-02)
  const eventsQuery = useEvents(true);
  const eventList = useMemo(
    () => (eventsQuery.data ?? []).map((e) => e.event),
    [eventsQuery.data],
  );
  const eventById = useMemo(() => new Map(eventList.map((e) => [e.id, e])), [eventList]);
  const hasActiveEvents = eventList.some((e) => e.is_active);
  const setTxnEvent = useSetTransactionEvent();
  const commitmentsQuery = useCommitments(true);
  const commitmentList = useMemo(() => commitmentsQuery.data ?? [], [commitmentsQuery.data]);
  const commitmentById = useMemo(
    () => new Map(commitmentList.map((c) => [c.id, c])),
    [commitmentList],
  );

  const [filterMode, setFilterMode] = useState<"month" | "range">("month");
  const [filterMonth, setFilterMonth] = useState(todayISO().slice(0, 7));
  const [rangeFrom, setRangeFrom] = useState(() => monthBounds(todayISO().slice(0, 7)).from);
  const [rangeTo, setRangeTo] = useState(() => monthBounds(todayISO().slice(0, 7)).to);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounced(search.trim(), 300);
  const [listLimit, setListLimit] = useState(PAGE_SIZE);

  // TXN-11: alta pendiente de confirmar por posible duplicado.
  const [pendingCreate, setPendingCreate] = useState<{
    body: TransactionBody;
    matches: TransactionOut[];
  } | null>(null);
  const [checkingDuplicates, setCheckingDuplicates] = useState(false);
  const [created, setCreated] = useState<TransactionOut | null>(null);

  useEffect(() => {
    if (!created) return;
    const id = window.setTimeout(() => setCreated(null), 4000);
    return () => window.clearTimeout(id);
  }, [created]);
  const [filterType, setFilterType] = useState("");
  const [filterCategoryId, setFilterCategoryId] = useState("");
  const [filterAccountId, setFilterAccountId] = useState("");
  // EVT-05: `?evento=<id>` (desde la página de Eventos) abre el listado filtrado.
  const [searchParams] = useSearchParams();
  const [filterEventId, setFilterEventId] = useState(() => searchParams.get("evento") ?? "");
  // CXP-03: `?compromiso=<id>` lista los abonos de un compromiso.
  const [filterCommitmentId, setFilterCommitmentId] = useState(
    () => searchParams.get("compromiso") ?? "",
  );

  const create = useCreateTransaction();
  const update = useUpdateTransaction();
  const confirm = useConfirmTransaction();
  const remove = useDeleteTransaction();
  // REC-14: al confirmar una suscripción con otro monto, ofrecer actualizar
  // su precio (solo si la regla está en la moneda de la cuenta).
  const recurringRules = useRecurringRules(true);
  const updateRule = useUpdateRecurringRule();
  const [priceChange, setPriceChange] = useState<{ rule: RecurringRuleOut; amount: string } | null>(
    null,
  );

  function confirmInstance(t: TransactionOut) {
    confirm.mutate(
      { id: t.id },
      {
        onSuccess: () => {
          const rule = recurringRules.data?.find((r) => r.id === t.recurring_rule_id);
          if (
            rule &&
            rule.kind === "subscription" &&
            rule.currency === t.currency &&
            rule.amount !== null &&
            rule.amount !== t.amount
          ) {
            setPriceChange({ rule, amount: t.amount });
          }
        },
      },
    );
  }

  const [deletingTxn, setDeletingTxn] = useState<TransactionOut | null>(null);
  const [editingTxn, setEditingTxn] = useState<TransactionOut | null>(null);
  const [editType, setEditType] = useState<TxnType>("expense");
  const [editAmount, setEditAmount] = useState("");
  const [editDate, setEditDate] = useState("");
  const [editCategoryId, setEditCategoryId] = useState("");
  const [editAccountId, setEditAccountId] = useState("");
  const [editAccountToId, setEditAccountToId] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editAmountTo, setEditAmountTo] = useState("");
  const [editFeeAmount, setEditFeeAmount] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [editCycleHint, setEditCycleHint] = useState<"current" | "next" | null>(null);
  const [editEventId, setEditEventId] = useState("");
  const [editCommitmentId, setEditCommitmentId] = useState(""); // CXP-03
  // MSI-08: una compra MSI no se edita aquí; solo se le puede cambiar el evento.
  const editingMsiParent = !!editingTxn?.installment_plan_id;

  function openEditModal(txn: TransactionOut) {
    setEditingTxn(txn);
    setEditType(txn.type as TxnType);
    setEditAmount(txn.amount);
    setEditDate(txn.date);
    setEditCategoryId(txn.category_id ?? "");
    setEditAccountId(txn.account_id);
    setEditAccountToId(txn.account_to_id ?? "");
    setEditDescription(txn.description);
    setEditAmountTo(txn.amount_to ?? "");
    setEditFeeAmount(txn.fee_amount ?? "");
    setEditError(null);
    setEditCycleHint(null);
    setEditEventId(txn.event_id ?? "");
    setEditCommitmentId(txn.commitment_id ?? "");
  }

  async function handleUpdate(e: FormEvent) {
    e.preventDefault();
    if (!editingTxn) return;
    setEditError(null);
    if (editingMsiParent) {
      try {
        await setTxnEvent.mutateAsync({ id: editingTxn.id, event_id: editEventId || null });
        setEditingTxn(null);
      } catch (err) {
        setEditError(err instanceof Error ? err.message : "Error al guardar");
      }
      return;
    }
    if (!isPositiveAmount(editAmount)) {
      setEditError(
        editingTxn.needs_review
          ? "El monto debe ser mayor a 0. Si este mes no aplica, usa «Descartar» en la bandeja Por confirmar."
          : "El monto debe ser mayor a 0.",
      );
      return;
    }
    try {
      await update.mutateAsync({
        id: editingTxn.id,
        type: editType,
        date: editDate,
        amount: editAmount,
        currency: editCurrency,
        description: editDescription,
        category_id: editType === "transfer" ? null : editCategoryId || null,
        account_id: editAccountId,
        account_to_id: editType === "transfer" ? editAccountToId || null : null,
        amount_to: editType === "transfer" && editCrossCurrency ? editAmountTo || null : null,
        fee_amount: editType === "transfer" && editFeeAmount ? editFeeAmount : null,
        cycle_hint: editCollision ? (editCycleHint ?? editCollision.defaultHint) : undefined,
        event_id: editEventId || null, // EVT-02
        // CXP-03: solo un gasto puede ser abono; el vínculo se conserva al editar.
        commitment_id: editType === "expense" ? editCommitmentId || null : null,
      });
      setEditingTxn(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  const periodFilters = useMemo(() => {
    if (filterMode === "month") {
      const { from, to } = monthBounds(filterMonth);
      return { date_from: from, date_to: to };
    }
    return { date_from: rangeFrom || undefined, date_to: rangeTo || undefined };
  }, [filterMode, filterMonth, rangeFrom, rangeTo]);
  // TXN-12: un rango invertido no se consulta.
  const invalidRange =
    filterMode === "range" && !!rangeFrom && !!rangeTo && rangeFrom > rangeTo;

  const filterCategories = useMemo(
    () =>
      (categories.data ?? []).filter((c) =>
        filterType === "expense"
          ? c.kind === "expense"
          : filterType === "income"
            ? c.kind === "income"
            : filterType === "transfer"
              ? false
              : true,
      ),
    [categories.data, filterType],
  );

  useEffect(() => {
    setListLimit(PAGE_SIZE);
  }, [
    periodFilters,
    filterType,
    filterCategoryId,
    filterAccountId,
    filterEventId,
    filterCommitmentId,
    debouncedSearch,
  ]);
  // EVT-05/CXP-03: un evento o un compromiso abarca varios meses.
  const spansPeriods = !!filterEventId || !!filterCommitmentId;

  const list = useTransactions(
    {
      // EVT-05: un evento abarca varios meses; con el filtro de evento se
      // listan todos sus movimientos, sin importar el periodo.
      ...(spansPeriods ? {} : periodFilters),
      type: filterType || undefined,
      category_id: filterCategoryId || undefined,
      account_id: filterAccountId || undefined,
      event_id: filterEventId || undefined,
      commitment_id: filterCommitmentId || undefined,
      q: debouncedSearch || undefined,
      limit: listLimit,
    },
    { enabled: !invalidRange || spansPeriods },
  );
  const activePreset = useMemo(() => {
    if (filterMode !== "range") return null;
    return (
      RANGE_PRESETS.find((n) => {
        const r = lastMonthsRange(n);
        return r.from === rangeFrom && r.to === rangeTo;
      }) ?? null
    );
  }, [filterMode, rangeFrom, rangeTo]);
  const tray = useTransactions({ needs_review: true });

  const visibleCategories = (categories.data ?? []).filter(
    (c) => c.kind === (type === "income" ? "income" : "expense"),
  );
  const visibleEditCategories = useMemo(
    () =>
      (categories.data ?? []).filter(
        (c) => c.kind === (editType === "income" ? "income" : "expense"),
      ),
    [categories.data, editType],
  );
  const byId = useMemo(() => {
    const cats = new Map((categories.data ?? []).map((c) => [c.id, c.name]));
    const accounts = new Map(accountList.map((a) => [a.id, a.name]));
    return { cats, accounts };
  }, [categories.data, accountList]);

  // TAR-10: la moneda la define la cuenta elegida.
  const account = accountById.get(accountId);
  const accountTo = accountById.get(accountToId);
  const currency = account?.currency ?? activeSpace.base_currency;
  const crossCurrency = type === "transfer" && !!account && !!accountTo && account.currency !== accountTo.currency;
  const editAccount = accountById.get(editAccountId);
  const editAccountTo = accountById.get(editAccountToId);
  const editCurrency = editAccount?.currency ?? editingTxn?.currency ?? activeSpace.base_currency;
  const editCrossCurrency =
    editType === "transfer" && !!editAccount && !!editAccountTo && editAccount.currency !== editAccountTo.currency;

  const collision = useMemo(() => detectCutoffCollision(date, account), [date, account]);
  const editCollision = useMemo(
    () => detectCutoffCollision(editDate, editAccount),
    [editDate, editAccount],
  );

  // TXN-08: saldo disponible del origen (cuentas con saldo, TAR-05). Un
  // préstamo no tiene "disponible" (TAR-11).
  const showsAvailable = (a: AccountOut | undefined) => !!a && hasBalance(a.behavior) && !isLoan(a.behavior);
  const transferFromBalance = account && showsAvailable(account) ? account.balance : null;
  const editTransferFromBalance = editAccount && showsAvailable(editAccount) ? editAccount.balance : null;

  // TDC-16: un ingreso a una tarjeta de crédito es un abono/devolución.
  const showIncomeWarning = type === "income" && account?.behavior === "credit";
  const showEditIncomeWarning = editType === "income" && editAccount?.behavior === "credit";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!isPositiveAmount(amount)) {
      setFormError("El monto debe ser mayor a 0.");
      return;
    }
    const body: TransactionBody = {
      type,
      date,
      amount,
      currency,
      description,
      category_id: type === "transfer" ? null : categoryId || null,
      account_id: accountId,
      account_to_id: type === "transfer" ? accountToId || null : null,
      amount_to: crossCurrency ? amountTo || null : null,
      fee_amount: type === "transfer" && withFee && feeAmount ? feeAmount : null,
      cycle_hint: collision ? (cycleHint ?? collision.defaultHint) : undefined,
      event_id: withEvent && eventId ? eventId : null, // EVT-02
    };
    // TXN-11: mismo tipo, fecha, monto, moneda, categoría y descripción
    // (la cuenta se ignora) ⇒ pedir confirmación antes de registrar.
    setCheckingDuplicates(true);
    let matches: TransactionOut[] = [];
    try {
      matches = await fetchPossibleDuplicates({
        type: body.type,
        date: body.date,
        amount: body.amount,
        currency: body.currency,
        description: body.description,
        category_id: body.category_id,
      });
    } catch {
      // El aviso es auxiliar: si la verificación falla, no bloquea el alta.
    } finally {
      setCheckingDuplicates(false);
    }
    if (matches.length > 0) {
      setPendingCreate({ body, matches });
      return;
    }
    await submitCreate(body);
  }

  async function submitCreate(body: TransactionBody) {
    setFormError(null);
    try {
      const txn = await create.mutateAsync(body);
      setAmount("");
      setDescription("");
      setAmountTo("");
      setFeeAmount("");
      setWithFee(false);
      setCycleHint(null);
      setPendingCreate(null);
      setCreated(txn);
    } catch (err) {
      setPendingCreate(null);
      setFormError(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  function txnTitle(t: TransactionOut): string {
    return (
      t.description ||
      (t.type === "transfer"
        ? "Transferencia"
        : (t.category_id && byId.cats.get(t.category_id)) || "—")
    );
  }

  function txnAccounts(t: TransactionOut): string {
    const from = t.account_id ? (byId.accounts.get(t.account_id) ?? "") : "";
    const to =
      t.type === "transfer" && t.account_to_id
        ? ` → ${byId.accounts.get(t.account_to_id) ?? ""}`
        : "";
    return `${from}${to}`;
  }

  return (
    <div className="page">
      {/* Captura rápida */}
      <form onSubmit={handleSubmit} onKeyDown={blockEnterSubmit} className="card @container space-y-4 p-4 sm:p-5">
        {/* Si no caben los 5 botones: tipos a todo el ancho y extras centrados debajo. */}
        <div className="flex flex-wrap items-center gap-2 @xl:flex-nowrap">
          <div className="flex w-full gap-2 @xl:w-auto">
          {(Object.keys(TYPE_LABELS) as TxnType[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setType(t)}
              className={`flex-1 @xl:flex-none ${
                type === t ? "btn-primary px-3 py-1.5" : "btn-secondary px-3 py-1.5"
              }`}
            >
              {TYPE_LABELS[t]}
            </button>
          ))}
          </div>
          {(type === "transfer" || hasActiveEvents || eventId) && (
          <div className="flex w-full justify-center gap-2 @xl:ml-auto @xl:w-auto">
          {type === "transfer" && (
            <button
              type="button"
              aria-pressed={withFee}
              onClick={() => {
                setWithFee((v) => !v);
                setFeeAmount("");
              }}
              className={withFee ? "btn-primary px-3 py-1.5" : "btn-secondary px-3 py-1.5"}
            >
              {withFee ? "✓ " : "+ "}Comisión
            </button>
          )}
          {(hasActiveEvents || eventId) && (
            <button
              type="button"
              aria-pressed={withEvent}
              onClick={() => {
                setWithEvent((v) => !v);
                setEventId("");
              }}
              className={withEvent ? "btn-primary px-3 py-1.5" : "btn-secondary px-3 py-1.5"}
            >
              {withEvent ? "✓ " : "+ "}Evento
            </button>
          )}
          </div>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div>
            <label className="label" htmlFor="amount">
              Monto{account ? ` (${currency})` : ""}
            </label>
            <input
              id="amount"
              className="input"
              inputMode="decimal"
              pattern="^\d+(\.\d{1,2})?$"
              placeholder="0.00"
              required
              value={amount}
              onChange={(e) => setAmount(sanitizeDecimal(e.target.value))}
            />
          </div>
          <div>
            <label className="label" htmlFor="date">Fecha</label>
            <input
              id="date"
              type="date"
              className="input"
              required
              value={date}
              onChange={(e) => { setDate(e.target.value); setCycleHint(null); }}
            />
          </div>
          {type !== "transfer" && (
            <div>
              <label className="label" htmlFor="category">Categoría</label>
              <select
                id="category"
                className="input"
                required
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
              >
                <option value="">Selecciona…</option>
                {visibleCategories.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label className="label" htmlFor="account">
              {type === "transfer" ? "Desde" : "Cuenta"}
            </label>
            <select
              id="account"
              className="input"
              required
              value={accountId}
              onChange={(e) => { setAccountId(e.target.value); setCycleHint(null); }}
            >
              <option value="">Selecciona…</option>
              <AccountOptions accounts={accountList} baseCurrency={activeSpace.base_currency} />
            </select>
            {transferFromBalance !== null && account && (
              <p className="mt-1 text-xs text-ink-muted">
                Disponible: {formatMoney(transferFromBalance, account.currency)}
              </p>
            )}
          </div>
          {type === "transfer" && (
            <div>
              <label className="label" htmlFor="accountTo">Hacia</label>
              <select
                id="accountTo"
                className="input"
                required
                value={accountToId}
                onChange={(e) => setAccountToId(e.target.value)}
              >
                <option value="">Selecciona…</option>
                <AccountOptions
                  accounts={accountList}
                  exclude={accountId}
                  baseCurrency={activeSpace.base_currency}
                />
              </select>
            </div>
          )}
          {type === "transfer" && (
            <TransferExtras
              source={account}
              target={accountTo}
              amount={amount}
              amountTo={amountTo}
              setAmountTo={setAmountTo}
              fee={feeAmount}
              setFee={setFeeAmount}
              showFee={false}
            />
          )}
          <div className="contents md:col-span-full md:flex md:items-end md:gap-3">
          {type === "transfer" && withFee && (
            <FeeField source={account} fee={feeAmount} setFee={setFeeAmount} className="md:w-36 md:shrink-0" />
          )}
          {withEvent && (
            <div className="md:w-48 md:shrink-0">
              <label className="label" htmlFor="event">Evento</label>
              <EventSelect id="event" value={eventId} onChange={setEventId} events={eventList} />
            </div>
          )}
          <div className="col-span-2 md:min-w-0 md:flex-1">
            <label className="label" htmlFor="description">Descripción</label>
            <input
              id="description"
              className="input"
              placeholder="¿En qué fue?"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="flex items-end md:w-40 md:shrink-0">
            <button
              type="submit"
              className="btn-primary w-full"
              disabled={create.isPending || checkingDuplicates}
            >
              {create.isPending || checkingDuplicates ? "Guardando…" : "Agregar"}
            </button>
          </div>
          </div>
        </div>
        {collision && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
            <p className="mb-2 font-medium text-amber-800 dark:text-amber-300">
              Este cargo cae el día de corte. ¿A qué ciclo pertenece?
            </p>
            <div className="flex gap-2">
              {(["current", "next"] as const).map((val) => {
                const effective = cycleHint ?? collision.defaultHint;
                return (
                  <button
                    key={val}
                    type="button"
                    onClick={() => setCycleHint(val)}
                    className={effective === val ? "btn-primary px-3 py-1.5" : "btn-secondary px-3 py-1.5"}
                  >
                    {val === "current" ? "Ciclo actual (cierra hoy)" : "Siguiente ciclo"}
                  </button>
                );
              })}
            </div>
          </div>
        )}
        {showIncomeWarning && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
            <p className="text-amber-800 dark:text-amber-300">
              Este ingreso se registrará como <strong>devolución/abono</strong> en el ciclo activo de la tarjeta y reducirá el total a pagar.
            </p>
          </div>
        )}
        {formError && <p className="text-sm text-red-600 dark:text-red-400">{formError}</p>}
      </form>

      {/* Bandeja por confirmar (REC-03) */}
      {(tray.data?.total ?? 0) > 0 && (
        <section className="card p-4 sm:p-5">
          <h2 className="mb-3 text-base font-semibold tracking-tight">
            Por confirmar
            <span className="ml-2 rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-800 dark:text-amber-200">
              {tray.data!.total}
            </span>
          </h2>
          <ul className="divide-y divide-line">
            {tray.data!.items.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{t.description || "Recurrente"}</p>
                  <p className="text-xs text-ink-muted">
                    {formatDate(t.date)} · {formatMoney(t.amount, t.currency)}
                    {t.original_amount && t.original_currency && (
                      <> (precio {formatMoney(t.original_amount, t.original_currency)})</>
                    )}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    aria-label="Editar transacción"
                    className="rounded p-1 text-ink-muted transition-colors hover:bg-muted hover:text-accent"
                    onClick={() => openEditModal(t)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                      <path d="M13.586 3.586a2 2 0 1 1 2.828 2.828l-.793.793-2.828-2.828.793-.793ZM11.379 5.793 3 14.172V17h2.828l8.38-8.379-2.83-2.828Z" />
                    </svg>
                  </button>
                  <button
                    className="btn-primary px-3 py-1.5"
                    onClick={() => confirmInstance(t)}
                  >
                    Confirmar
                  </button>
                  <button
                    className="btn-secondary px-3 py-1.5"
                    onClick={() => setDeletingTxn(t)}
                  >
                    Descartar
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Lista con filtros */}
      <section className="card p-4 sm:p-5">
        <div className="mb-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold tracking-tight">
              Movimientos
              {list.data && (!invalidRange || spansPeriods) && (
                <span className="ml-2 text-xs font-normal text-ink-muted">
                  {list.data.total} {list.data.total === 1 ? "movimiento" : "movimientos"}
                </span>
              )}
            </h2>
            <div className="relative w-full sm:w-72">
              <Icon
                name="search"
                className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-subtle"
              />
              <input
                type="search"
                aria-label="Buscar por descripción"
                className="input pl-9"
                placeholder="Buscar por descripción…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-lg border border-line p-0.5" role="group" aria-label="Periodo">
              {(["month", "range"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  aria-pressed={filterMode === mode}
                  onClick={() => {
                    if (mode === "range" && filterMode === "month") {
                      const { from, to } = monthBounds(filterMonth);
                      setRangeFrom(from);
                      setRangeTo(to);
                    }
                    setFilterMode(mode);
                  }}
                  className={`rounded-md px-3 py-1 text-sm transition ${
                    filterMode === mode
                      ? "bg-muted font-medium text-ink"
                      : "text-ink-muted hover:text-ink"
                  }`}
                >
                  {mode === "month" ? "Mes" : "Rango"}
                </button>
              ))}
            </div>
            {filterMode === "month" ? (
              <div className="flex flex-1 items-center gap-1 sm:flex-none">
                <button
                  type="button"
                  aria-label="Mes anterior"
                  className="rounded-lg p-2 text-ink-muted transition hover:bg-muted hover:text-ink"
                  onClick={() => setFilterMonth((m) => shiftMonth(m, -1))}
                >
                  <Icon name="chevron-left" />
                </button>
                <input
                  type="month"
                  aria-label="Mes"
                  className="input min-w-0 flex-1 sm:w-auto sm:flex-none"
                  value={filterMonth}
                  onChange={(e) => e.target.value && setFilterMonth(e.target.value)}
                />
                <button
                  type="button"
                  aria-label="Mes siguiente"
                  className="rounded-lg p-2 text-ink-muted transition hover:bg-muted hover:text-ink"
                  onClick={() => setFilterMonth((m) => shiftMonth(m, 1))}
                >
                  <Icon name="chevron-right" />
                </button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="date"
                  aria-label="Desde"
                  className="input w-auto"
                  value={rangeFrom}
                  onChange={(e) => setRangeFrom(e.target.value)}
                />
                <span className="text-sm text-ink-muted">a</span>
                <input
                  type="date"
                  aria-label="Hasta"
                  className="input w-auto"
                  value={rangeTo}
                  onChange={(e) => setRangeTo(e.target.value)}
                />
                {RANGE_PRESETS.map((n) => (
                  <button
                    key={n}
                    type="button"
                    className={activePreset === n ? "btn-primary px-3 py-1.5" : "btn-secondary px-3 py-1.5"}
                    onClick={() => {
                      const r = lastMonthsRange(n);
                      setRangeFrom(r.from);
                      setRangeTo(r.to);
                    }}
                  >
                    Últimos {n} meses
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap [&>select]:min-w-0 sm:[&>select]:w-auto">
            <select
              className="input"
              aria-label="Tipo"
              value={filterType}
              onChange={(e) => {
                setFilterType(e.target.value);
                setFilterCategoryId("");
              }}
            >
              <option value="">Todos</option>
              <option value="expense">Gastos</option>
              <option value="income">Ingresos</option>
              <option value="transfer">Transferencias</option>
            </select>
            {filterType !== "transfer" && (
              <select
                className="input"
                aria-label="Categoría"
                value={filterCategoryId}
                onChange={(e) => setFilterCategoryId(e.target.value)}
              >
                <option value="">Categoría</option>
                {filterType === "" ? (
                  <>
                    <optgroup label="Gastos">
                      {filterCategories.filter((c) => c.kind === "expense").map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </optgroup>
                    <optgroup label="Ingresos">
                      {filterCategories.filter((c) => c.kind === "income").map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </optgroup>
                  </>
                ) : (
                  filterCategories.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))
                )}
              </select>
            )}
            <select
              className="input"
              aria-label="Cuenta"
              value={filterAccountId}
              onChange={(e) => setFilterAccountId(e.target.value)}
            >
              <option value="">Cuenta</option>
              <AccountOptions accounts={accountList} baseCurrency={activeSpace.base_currency} />
            </select>
            {eventList.length > 0 && (
              <select
                className="input"
                aria-label="Evento"
                value={filterEventId}
                onChange={(e) => setFilterEventId(e.target.value)}
              >
                <option value="">Evento</option>
                {eventList.map((ev) => (
                  <option key={ev.id} value={ev.id}>
                    {ev.name}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>
        {spansPeriods && (
          <p className="mb-3 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
            {filterCommitmentId ? (
              <>
                Mostrando los abonos a{" "}
                <strong className="text-ink">
                  {commitmentById.get(filterCommitmentId)?.name ?? "el compromiso"}
                </strong>
              </>
            ) : (
              <>
                Mostrando todos los movimientos de{" "}
                <strong className="text-ink">{eventById.get(filterEventId)?.name ?? "el evento"}</strong>
              </>
            )}
            , sin importar el periodo.
            <button
              type="button"
              className="font-medium text-accent hover:underline"
              onClick={() => {
                setFilterEventId("");
                setFilterCommitmentId("");
              }}
            >
              Quitar filtro
            </button>
          </p>
        )}
        {invalidRange && !spansPeriods ? (
          <p className="text-sm text-amber-700 dark:text-amber-300">
            La fecha inicial es posterior a la final. Ajusta el rango.
          </p>
        ) : list.isLoading ? (
          <p className="text-sm text-ink-muted">Cargando…</p>
        ) : (list.data?.items.length ?? 0) === 0 ? (
          <p className="text-sm text-ink-muted">
            {debouncedSearch
              ? `Sin movimientos que coincidan con «${debouncedSearch}» en este periodo.`
              : filterMode === "month"
                ? "Sin movimientos este mes. Registra el primero arriba."
                : "Sin movimientos en este rango."}
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {list.data!.items.map((t: TransactionOut) => (
              <li
                key={t.id}
                className={`-mx-2 flex items-center justify-between gap-3 rounded-lg px-2 py-2.5 transition-colors duration-700 ${
                  created?.id === t.id ? "bg-emerald-500/10" : ""
                }`}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span
                    aria-hidden
                    className={`grid size-9 shrink-0 place-items-center rounded-full text-xs font-semibold ${
                      t.type === "income"
                        ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                        : t.type === "transfer"
                          ? "bg-muted text-ink-muted"
                          : "bg-muted text-ink"
                    }`}
                  >
                    {t.type === "transfer" ? (
                      <Icon name="transactions" className="size-4" />
                    ) : (
                      ((t.category_id && byId.cats.get(t.category_id)) || t.description || "?")
                        .trim()
                        .charAt(0)
                        .toUpperCase()
                    )}
                  </span>
                  <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {t.description ||
                      (t.type === "transfer"
                        ? "Transferencia"
                        : (t.category_id && byId.cats.get(t.category_id)) || "—")}
                  </p>
                  <p className="text-xs text-ink-muted">
                    {formatDate(t.date)}
                    {t.category_id ? ` · ${byId.cats.get(t.category_id) ?? ""}` : ""}
                    {t.account_id
                      ? ` · ${byId.accounts.get(t.account_id) ?? ""}`
                      : ""}
                    {t.type === "transfer" && t.account_to_id
                      ? ` → ${byId.accounts.get(t.account_to_id) ?? ""}`
                      : ""}
                    {t.fee_for_id ? " · comisión de transferencia" : ""}
                    {t.commitment_id && commitmentById.get(t.commitment_id) && (
                      <span className="ml-1.5 inline-flex items-center rounded-full bg-sky-500/15 px-1.5 py-px text-[11px] font-medium text-sky-800 dark:text-sky-200">
                        Abono · {commitmentById.get(t.commitment_id)!.name}
                      </span>
                    )}
                    {t.event_id && eventById.get(t.event_id) && (
                      <span className="ml-1.5 inline-flex items-center rounded-full bg-violet-500/15 px-1.5 py-px text-[11px] font-medium text-violet-800 dark:text-violet-200">
                        {eventById.get(t.event_id)!.name}
                      </span>
                    )}
                  </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span
                    className={
                      t.type === "income"
                        ? "tabular text-sm font-semibold text-emerald-600 dark:text-emerald-400"
                        : t.type === "transfer"
                          ? "tabular text-sm font-semibold text-ink-muted"
                          : "tabular text-sm font-semibold"
                    }
                  >
                    {t.type === "income" ? "+" : t.type === "expense" ? "−" : ""}
                    {formatMoney(t.amount, t.currency)}
                    {/* TXN-13/14: lo recibido en otra moneda y la comisión aparte. */}
                    {t.amount_to && t.account_to_id && (
                      <span className="block text-right text-xs font-normal text-ink-muted">
                        recibe{" "}
                        {formatMoney(t.amount_to, accountById.get(t.account_to_id)?.currency ?? t.currency)}
                      </span>
                    )}
                    {t.fee_amount && (
                      <span className="block text-right text-xs font-normal text-ink-muted">
                        + {formatMoney(t.fee_amount, t.currency)} comisión
                      </span>
                    )}
                  </span>
                  {t.fee_for_id ? (
                    // TXN-14: la comisión se edita o borra desde su transferencia.
                    <span className="w-14 text-right text-[11px] text-ink-subtle" title="Se edita desde su transferencia">
                      auto
                    </span>
                  ) : (
                  <>
                  <button
                    aria-label="Editar transacción"
                    className="rounded p-1 text-ink-muted transition-colors hover:bg-muted hover:text-accent"
                    onClick={() => openEditModal(t)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                      <path d="M13.586 3.586a2 2 0 1 1 2.828 2.828l-.793.793-2.828-2.828.793-.793ZM11.379 5.793 3 14.172V17h2.828l8.38-8.379-2.83-2.828Z" />
                    </svg>
                  </button>
                  <button
                    aria-label="Eliminar transacción"
                    className="rounded p-1 text-ink-muted transition-colors hover:bg-red-500/10 hover:text-red-500 dark:hover:text-red-400"
                    onClick={() => setDeletingTxn(t)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                      <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clipRule="evenodd" />
                    </svg>
                  </button>
                  </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        {(!invalidRange || spansPeriods) && list.data && list.data.items.length < list.data.total && (
          <div className="mt-4 flex justify-center">
            <button
              type="button"
              className="btn-secondary"
              disabled={list.isFetching}
              onClick={() => setListLimit((l) => l + PAGE_SIZE)}
            >
              {list.isFetching
                ? "Cargando…"
                : `Mostrar más (${list.data.items.length} de ${list.data.total})`}
            </button>
          </div>
        )}
      </section>

      {/* TXN-11: aviso de posible duplicado */}
      <Modal
        open={pendingCreate !== null}
        onClose={() => setPendingCreate(null)}
        title="¿Registro duplicado?"
      >
        {pendingCreate && (
          <div className="space-y-4">
            <div className="flex gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-300">
              <Icon name="alert" className="mt-0.5 size-4" />
              <p>
                Ya {pendingCreate.matches.length === 1 ? "existe un movimiento" : `existen ${pendingCreate.matches.length} movimientos`}{" "}
                con la misma descripción, tipo, categoría y monto el{" "}
                <strong>{formatDate(pendingCreate.body.date)}</strong> (sin importar la cuenta):
              </p>
            </div>
            <ul className="divide-y divide-line rounded-lg border border-line bg-muted text-sm">
              {pendingCreate.matches.map((m) => (
                <li key={m.id} className="flex items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{txnTitle(m)}</p>
                    <p className="text-xs text-ink-muted">
                      {TYPE_LABELS[m.type as TxnType]} · {txnAccounts(m) || "Sin cuenta"}
                    </p>
                  </div>
                  <span className="tabular shrink-0 font-semibold">
                    {formatMoney(m.amount, m.currency)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-sm">
              Lo que vas a registrar sería en{" "}
              <strong>
                {(pendingCreate.body.account_id &&
                  byId.accounts.get(pendingCreate.body.account_id)) ||
                  "—"}
              </strong>
              . ¿Seguro que no es el mismo gasto y deseas continuar?
            </p>
            <div className="flex justify-end gap-2 pt-1">
              <button type="button" className="btn-secondary" onClick={() => setPendingCreate(null)}>
                Cancelar
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={create.isPending}
                onClick={() => void submitCreate(pendingCreate.body)}
              >
                Registrar de todos modos
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* TXN-11: confirmación visual del alta */}
      {created && (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-6 left-1/2 z-50 w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 sm:left-auto sm:right-6 sm:translate-x-0"
        >
          <div className="card flex items-start gap-3 p-4 shadow-2xl">
            <span className="grid size-8 shrink-0 place-items-center rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
              <Icon name="check" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">{CREATED_LABELS[created.type as TxnType]}</p>
              <p className="truncate text-sm">{txnTitle(created)}</p>
              <p className="text-xs text-ink-muted">
                {formatMoney(created.amount, created.currency)} · {formatDate(created.date)}
                {txnAccounts(created) ? ` · ${txnAccounts(created)}` : ""}
              </p>
            </div>
            <button
              aria-label="Cerrar aviso"
              className="-mr-1 -mt-1 rounded-lg p-1 text-ink-subtle transition hover:bg-muted hover:text-ink"
              onClick={() => setCreated(null)}
            >
              <Icon name="x" />
            </button>
          </div>
        </div>
      )}

      {/* REC-14: actualizar el precio de la suscripción */}
      <Modal
        open={priceChange !== null}
        onClose={() => setPriceChange(null)}
        title="¿Cambió el precio?"
      >
        {priceChange && (
          <div className="space-y-4">
            <p className="text-sm">
              Confirmaste <strong>{priceChange.rule.description}</strong> por{" "}
              {formatMoney(priceChange.amount, priceChange.rule.currency)}, pero la suscripción
              dice {formatMoney(priceChange.rule.amount ?? "0", priceChange.rule.currency)}.
              ¿Actualizo el precio para los próximos cobros?
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setPriceChange(null)}>
                Solo este mes
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={updateRule.isPending}
                onClick={() =>
                  updateRule.mutate(
                    { id: priceChange.rule.id, amount: priceChange.amount },
                    { onSuccess: () => setPriceChange(null) },
                  )
                }
              >
                Actualizar precio
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* Modal de confirmación de eliminación */}
      <Modal
        open={deletingTxn !== null}
        onClose={() => setDeletingTxn(null)}
        title="Eliminar transacción"
      >
        {deletingTxn && (
          <div className="space-y-4">
            <p className="text-sm text-ink-muted">
              Estás a punto de eliminar esta transacción:
            </p>
            <div className="rounded-lg border border-line bg-muted p-3 text-sm">
              <p className="font-medium">
                {deletingTxn.description ||
                  (deletingTxn.type === "transfer"
                    ? "Transferencia"
                    : (deletingTxn.category_id && byId.cats.get(deletingTxn.category_id)) || "—")}
              </p>
              <p className="mt-1 text-ink-muted">
                {TYPE_LABELS[deletingTxn.type as TxnType]} · {formatDate(deletingTxn.date)} ·{" "}
                <span className="font-semibold text-ink">
                  {deletingTxn.type === "income" ? "+" : deletingTxn.type === "expense" ? "−" : ""}
                  {formatMoney(deletingTxn.amount, deletingTxn.currency)}
                </span>
              </p>
              {deletingTxn.category_id && (
                <p className="mt-0.5 text-xs text-ink-muted">
                  {byId.cats.get(deletingTxn.category_id)}
                  {deletingTxn.account_id
                    ? ` · ${byId.accounts.get(deletingTxn.account_id)}`
                    : ""}
                </p>
              )}
            </div>
            <p className="text-sm font-medium">¿Estás seguro que deseas continuar?</p>
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setDeletingTxn(null)}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="btn-danger"
                disabled={remove.isPending}
                onClick={() => {
                  remove.mutate(deletingTxn.id, { onSuccess: () => setDeletingTxn(null) });
                }}
              >
                Eliminar
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* Modal de edición */}
      <Modal
        open={editingTxn !== null}
        onClose={() => setEditingTxn(null)}
        title="Editar transacción"
        size="lg"
      >
        {editingMsiParent ? (
          <form onSubmit={handleUpdate} onKeyDown={blockEnterSubmit} className="space-y-4">
            <p className="text-sm text-ink-muted">
              Es una compra a meses sin intereses: su monto y cuotas se ajustan desde{" "}
              <strong>MSI</strong>. Aquí solo puedes ligarla a un evento.
            </p>
            <div>
              <label className="label">Evento</label>
              <EventSelect value={editEventId} onChange={setEditEventId} events={eventList} />
            </div>
            {editError && <p className="text-sm text-red-600 dark:text-red-400">{editError}</p>}
            <div className="flex justify-end gap-2 pt-1">
              <button type="button" className="btn-secondary" onClick={() => setEditingTxn(null)}>
                Cancelar
              </button>
              <button type="submit" className="btn-primary" disabled={setTxnEvent.isPending}>
                Guardar
              </button>
            </div>
          </form>
        ) : (
        <form onSubmit={handleUpdate} onKeyDown={blockEnterSubmit} className="space-y-4">
          {/* Fila 1 — tipo */}
          <div className="flex flex-wrap gap-2">
            {(Object.keys(TYPE_LABELS) as TxnType[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setEditType(t)}
                className={editType === t ? "btn-primary px-3 py-1.5" : "btn-secondary px-3 py-1.5"}
              >
                {TYPE_LABELS[t]}
              </button>
            ))}
          </div>

          {/* Fila 2 — Monto · Fecha · Categoría/Desde · Método/Hacia */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div>
              <label className="label">Monto ({editCurrency})</label>
              <input
                className="input"
                inputMode="decimal"
                pattern="^\d+(\.\d{1,2})?$"
                required
                value={editAmount}
                onChange={(e) => setEditAmount(sanitizeDecimal(e.target.value))}
              />
            </div>
            <div>
              <label className="label">Fecha</label>
              <input
                type="date"
                className="input"
                required
                value={editDate}
                onChange={(e) => { setEditDate(e.target.value); setEditCycleHint(null); }}
              />
            </div>
            {editType === "transfer" ? (
              <>
                <div>
                  <label className="label">Desde</label>
                  <select
                    className="input"
                    required
                    value={editAccountId}
                    onChange={(e) => { setEditAccountId(e.target.value); setEditCycleHint(null); }}
                  >
                    <option value="">Selecciona…</option>
                    <AccountOptions accounts={accountList} baseCurrency={activeSpace.base_currency} />
                  </select>
                  {editTransferFromBalance !== null && editAccount && (
                    <p className="mt-1 text-xs text-ink-muted">
                      Disponible: {formatMoney(editTransferFromBalance, editAccount.currency)}
                    </p>
                  )}
                </div>
                <div>
                  <label className="label">Hacia</label>
                  <select
                    className="input"
                    required
                    value={editAccountToId}
                    onChange={(e) => setEditAccountToId(e.target.value)}
                  >
                    <option value="">Selecciona…</option>
                    <AccountOptions
                      accounts={accountList}
                      exclude={editAccountId}
                      baseCurrency={activeSpace.base_currency}
                    />
                  </select>
                </div>
                <TransferExtras
                  source={editAccount}
                  target={editAccountTo}
                  amount={editAmount}
                  amountTo={editAmountTo}
                  setAmountTo={setEditAmountTo}
                  fee={editFeeAmount}
                  setFee={setEditFeeAmount}
                />
              </>
            ) : (
              <>
                <div>
                  <label className="label">Categoría</label>
                  <select
                    className="input"
                    required
                    value={editCategoryId}
                    onChange={(e) => setEditCategoryId(e.target.value)}
                  >
                    <option value="">Selecciona…</option>
                    {visibleEditCategories.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">Cuenta</label>
                  <select
                    className="input"
                    required
                    value={editAccountId}
                    onChange={(e) => { setEditAccountId(e.target.value); setEditCycleHint(null); }}
                  >
                    <option value="">Selecciona…</option>
                    <AccountOptions accounts={accountList} baseCurrency={activeSpace.base_currency} />
                  </select>
                </div>
              </>
            )}
          </div>

          {editCollision && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
              <p className="mb-2 font-medium text-amber-800 dark:text-amber-300">
                Este cargo cae el día de corte. ¿A qué ciclo pertenece?
              </p>
              <div className="flex gap-2">
                {(["current", "next"] as const).map((val) => {
                  const effective = editCycleHint ?? editCollision.defaultHint;
                  return (
                    <button
                      key={val}
                      type="button"
                      onClick={() => setEditCycleHint(val)}
                      className={effective === val ? "btn-primary px-3 py-1.5" : "btn-secondary px-3 py-1.5"}
                    >
                      {val === "current" ? "Ciclo actual (cierra hoy)" : "Siguiente ciclo"}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          {showEditIncomeWarning && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
              <p className="text-amber-800 dark:text-amber-300">
                Este ingreso se registrará como <strong>devolución/abono</strong> en el ciclo activo de la tarjeta y reducirá el total a pagar.
              </p>
            </div>
          )}

          {/* Fila 3 — Descripción (la moneda la define la cuenta, TAR-10) y evento (EVT-02) */}
          <div className="grid grid-cols-3 gap-3">
            <div className={eventList.length > 0 ? "col-span-3 sm:col-span-2" : "col-span-3"}>
              <label className="label">Descripción</label>
              <input
                className="input"
                placeholder="¿En qué fue?"
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
              />
            </div>
            {eventList.length > 0 && (
              <div className="col-span-3 sm:col-span-1">
                <label className="label">Evento</label>
                <EventSelect value={editEventId} onChange={setEditEventId} events={eventList} />
              </div>
            )}
          </div>
          {editType === "expense" && (commitmentList.some((c) => c.status === "pending") || editCommitmentId) && (
            <div>
              <label className="label">Abono a compromiso</label>
              <select
                className="input"
                value={editCommitmentId}
                onChange={(e) => {
                  setEditCommitmentId(e.target.value);
                  // CXP-03: el abono toma el evento de su compromiso.
                  const c = commitmentById.get(e.target.value);
                  if (c?.event_id) setEditEventId(c.event_id);
                }}
              >
                <option value="">No es abono</option>
                {commitmentList
                  .filter((c) => c.status === "pending" || c.id === editCommitmentId)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} · pendiente {formatMoney(c.pending, c.currency)}
                    </option>
                  ))}
              </select>
            </div>
          )}

          {editError && <p className="text-sm text-red-600 dark:text-red-400">{editError}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn-secondary" onClick={() => setEditingTxn(null)}>
              Cancelar
            </button>
            <button type="submit" className="btn-primary" disabled={update.isPending}>
              Guardar
            </button>
          </div>
        </form>
        )}
      </Modal>
    </div>
  );
}
