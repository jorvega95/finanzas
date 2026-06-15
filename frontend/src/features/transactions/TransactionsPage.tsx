// Registro de gastos (R1): captura rápida <10 s, bandeja "Por confirmar"
// (REC-03) y lista con filtros (TXN-01..03).
import { useMemo, useState, type FormEvent } from "react";
import { useCategories, usePaymentMethods, type PaymentMethodOut } from "../../api/catalogs";
import { useCards, type CardOut } from "../../api/cards";
import {
  useConfirmTransaction,
  useCreateTransaction,
  useDeleteTransaction,
  useUpdateTransaction,
  useTransactions,
  type TransactionOut,
} from "../../api/transactions";
import { useSpace } from "../spaces/SpaceProvider";
import { formatMoney } from "../../lib/money";
import Modal from "../../components/ui/Modal";

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

function detectCutoffCollision(
  txnDate: string,
  methodId: string,
  cardsData: CardOut[],
  methodsData: PaymentMethodOut[],
): { defaultHint: "current" | "next" } | null {
  if (!txnDate || !methodId) return null;
  const method = methodsData.find((m) => m.id === methodId);
  if (!method?.card_id) return null;
  const card = cardsData.find((c) => c.id === method.card_id);
  if (!card || card.behavior !== "credit" || !card.statement_day) return null;
  const [year, month, day] = txnDate.split("-").map(Number);
  const cutoffDay = card.statement_day_is_last
    ? new Date(year, month, 0).getDate()
    : card.statement_day;
  if (day !== cutoffDay) return null;
  return { defaultHint: card.cutoff_day_policy === "next_cycle" ? "next" : "current" };
}

export default function TransactionsPage() {
  const { activeSpace } = useSpace();
  const categories = useCategories();
  const methods = usePaymentMethods();
  const cards = useCards();

  const [type, setType] = useState<TxnType>("expense");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(todayISO);
  const [categoryId, setCategoryId] = useState("");
  const [methodId, setMethodId] = useState("");
  const [methodToId, setMethodToId] = useState("");
  const [description, setDescription] = useState("");
  const [currency, setCurrency] = useState(activeSpace.base_currency);
  const [formError, setFormError] = useState<string | null>(null);
  const [cycleHint, setCycleHint] = useState<"current" | "next" | null>(null);

  const [filterMonth, setFilterMonth] = useState(todayISO().slice(0, 7));
  const [filterType, setFilterType] = useState("");

  const create = useCreateTransaction();
  const update = useUpdateTransaction();
  const confirm = useConfirmTransaction();
  const remove = useDeleteTransaction();

  const [deletingTxn, setDeletingTxn] = useState<TransactionOut | null>(null);
  const [editingTxn, setEditingTxn] = useState<TransactionOut | null>(null);
  const [editType, setEditType] = useState<TxnType>("expense");
  const [editAmount, setEditAmount] = useState("");
  const [editDate, setEditDate] = useState("");
  const [editCategoryId, setEditCategoryId] = useState("");
  const [editMethodId, setEditMethodId] = useState("");
  const [editMethodToId, setEditMethodToId] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editCurrency, setEditCurrency] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [editCycleHint, setEditCycleHint] = useState<"current" | "next" | null>(null);

  function openEditModal(txn: TransactionOut) {
    setEditingTxn(txn);
    setEditType(txn.type as TxnType);
    setEditAmount(txn.amount);
    setEditDate(txn.date);
    setEditCategoryId(txn.category_id ?? "");
    setEditMethodId(txn.payment_method_id ?? "");
    setEditMethodToId(txn.payment_method_to_id ?? "");
    setEditDescription(txn.description);
    setEditCurrency(txn.currency);
    setEditError(null);
    setEditCycleHint(null);
  }

  async function handleUpdate(e: FormEvent) {
    e.preventDefault();
    if (!editingTxn) return;
    setEditError(null);
    try {
      await update.mutateAsync({
        id: editingTxn.id,
        type: editType,
        date: editDate,
        amount: editAmount,
        currency: editCurrency,
        description: editDescription,
        category_id: editType === "transfer" ? null : editCategoryId || null,
        payment_method_id: editMethodId || null,
        payment_method_to_id: editType === "transfer" ? editMethodToId || null : null,
        cycle_hint: editCollision ? (editCycleHint ?? editCollision.defaultHint) : undefined,
      });
      setEditingTxn(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  const monthFilters = useMemo(() => {
    const [year, month] = filterMonth.split("-").map(Number);
    const lastDay = new Date(year, month, 0).getDate();
    return {
      date_from: `${filterMonth}-01`,
      date_to: `${filterMonth}-${String(lastDay).padStart(2, "0")}`,
    };
  }, [filterMonth]);

  const list = useTransactions({ ...monthFilters, type: filterType || undefined });
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
    const pms = new Map((methods.data ?? []).map((m) => [m.id, m.name]));
    return { cats, pms };
  }, [categories.data, methods.data]);

  const collision = useMemo(
    () => detectCutoffCollision(date, methodId, cards.data ?? [], methods.data ?? []),
    [date, methodId, cards.data, methods.data],
  );
  const editCollision = useMemo(
    () => detectCutoffCollision(editDate, editMethodId, cards.data ?? [], methods.data ?? []),
    [editDate, editMethodId, cards.data, methods.data],
  );

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    try {
      await create.mutateAsync({
        type,
        date,
        amount,
        currency,
        description,
        category_id: type === "transfer" ? null : categoryId || null,
        payment_method_id: methodId || null,
        payment_method_to_id: type === "transfer" ? methodToId || null : null,
        cycle_hint: collision ? (cycleHint ?? collision.defaultHint) : undefined,
      });
      setAmount("");
      setDescription("");
      setCycleHint(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* Captura rápida */}
      <form onSubmit={handleSubmit} className="card space-y-4 p-5">
        <div className="flex flex-wrap items-center gap-2">
          {(Object.keys(TYPE_LABELS) as TxnType[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setType(t)}
              className={
                type === t
                  ? "btn-primary px-3 py-1.5"
                  : "btn-secondary px-3 py-1.5"
              }
            >
              {TYPE_LABELS[t]}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div>
            <label className="label" htmlFor="amount">Monto</label>
            <input
              id="amount"
              className="input"
              inputMode="decimal"
              pattern="^\d+(\.\d{1,2})?$"
              placeholder="0.00"
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
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
            <label className="label" htmlFor="method">
              {type === "transfer" ? "Desde" : "Método de pago"}
            </label>
            <select
              id="method"
              className="input"
              required
              value={methodId}
              onChange={(e) => { setMethodId(e.target.value); setCycleHint(null); }}
            >
              <option value="">Selecciona…</option>
              {(methods.data ?? []).map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </div>
          {type === "transfer" && (
            <div>
              <label className="label" htmlFor="methodTo">Hacia</label>
              <select
                id="methodTo"
                className="input"
                required
                value={methodToId}
                onChange={(e) => setMethodToId(e.target.value)}
              >
                <option value="">Selecciona…</option>
                {(methods.data ?? [])
                  .filter((m) => m.id !== methodId)
                  .map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
              </select>
            </div>
          )}
          <div className="col-span-2">
            <label className="label" htmlFor="description">Descripción</label>
            <input
              id="description"
              className="input"
              placeholder="¿En qué fue?"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="currency">Moneda</label>
            <select
              id="currency"
              className="input"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
            >
              <option value="MXN">MXN</option>
              <option value="USD">USD</option>
            </select>
          </div>
          <div className="flex items-end">
            <button type="submit" className="btn-primary w-full" disabled={create.isPending}>
              Agregar
            </button>
          </div>
        </div>
        {collision && (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-700 dark:bg-amber-900/20">
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
        {formError && <p className="text-sm text-red-600 dark:text-red-400">{formError}</p>}
      </form>

      {/* Bandeja por confirmar (REC-03) */}
      {(tray.data?.total ?? 0) > 0 && (
        <section className="card p-5">
          <h2 className="mb-3 font-semibold">
            Por confirmar
            <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800 dark:bg-amber-900 dark:text-amber-200">
              {tray.data!.total}
            </span>
          </h2>
          <ul className="divide-y divide-line dark:divide-slate-800">
            {tray.data!.items.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{t.description || "Recurrente"}</p>
                  <p className="text-xs text-ink-muted dark:text-slate-400">
                    {t.date} · {formatMoney(t.amount, t.currency)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    aria-label="Editar transacción"
                    className="rounded p-1 text-ink-muted transition-colors hover:bg-slate-100 hover:text-accent dark:hover:bg-slate-700"
                    onClick={() => openEditModal(t)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                      <path d="M13.586 3.586a2 2 0 1 1 2.828 2.828l-.793.793-2.828-2.828.793-.793ZM11.379 5.793 3 14.172V17h2.828l8.38-8.379-2.83-2.828Z" />
                    </svg>
                  </button>
                  <button
                    className="btn-primary px-3 py-1.5"
                    onClick={() => confirm.mutate({ id: t.id })}
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
      <section className="card p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-semibold">Movimientos</h2>
          <div className="flex gap-2">
            <input
              type="month"
              className="input w-auto"
              value={filterMonth}
              onChange={(e) => setFilterMonth(e.target.value)}
            />
            <select
              className="input w-auto"
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
            >
              <option value="">Todos</option>
              <option value="expense">Gastos</option>
              <option value="income">Ingresos</option>
              <option value="transfer">Transferencias</option>
            </select>
          </div>
        </div>
        {list.isLoading ? (
          <p className="text-sm text-ink-muted">Cargando…</p>
        ) : (list.data?.items.length ?? 0) === 0 ? (
          <p className="text-sm text-ink-muted dark:text-slate-400">
            Sin movimientos este mes. Registra el primero arriba ☝️
          </p>
        ) : (
          <ul className="divide-y divide-line dark:divide-slate-800">
            {list.data!.items.map((t: TransactionOut) => (
              <li key={t.id} className="flex items-center justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {t.description ||
                      (t.type === "transfer"
                        ? "Transferencia"
                        : (t.category_id && byId.cats.get(t.category_id)) || "—")}
                  </p>
                  <p className="text-xs text-ink-muted dark:text-slate-400">
                    {t.date}
                    {t.category_id ? ` · ${byId.cats.get(t.category_id) ?? ""}` : ""}
                    {t.payment_method_id
                      ? ` · ${byId.pms.get(t.payment_method_id) ?? ""}`
                      : ""}
                    {t.type === "transfer" && t.payment_method_to_id
                      ? ` → ${byId.pms.get(t.payment_method_to_id) ?? ""}`
                      : ""}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span
                    className={
                      t.type === "income"
                        ? "text-sm font-semibold text-emerald-600 dark:text-emerald-400"
                        : t.type === "transfer"
                          ? "text-sm font-semibold text-ink-muted dark:text-slate-400"
                          : "text-sm font-semibold"
                    }
                  >
                    {t.type === "income" ? "+" : t.type === "expense" ? "−" : ""}
                    {formatMoney(t.amount, t.currency)}
                  </span>
                  <button
                    aria-label="Editar transacción"
                    className="rounded p-1 text-ink-muted transition-colors hover:bg-slate-100 hover:text-accent dark:hover:bg-slate-700"
                    onClick={() => openEditModal(t)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                      <path d="M13.586 3.586a2 2 0 1 1 2.828 2.828l-.793.793-2.828-2.828.793-.793ZM11.379 5.793 3 14.172V17h2.828l8.38-8.379-2.83-2.828Z" />
                    </svg>
                  </button>
                  <button
                    aria-label="Eliminar transacción"
                    className="rounded p-1 text-ink-muted transition-colors hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                    onClick={() => setDeletingTxn(t)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                      <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clip-rule="evenodd" />
                    </svg>
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      {/* Modal de confirmación de eliminación */}
      <Modal
        open={deletingTxn !== null}
        onClose={() => setDeletingTxn(null)}
        title="Eliminar transacción"
      >
        {deletingTxn && (
          <div className="space-y-4">
            <p className="text-sm text-ink-muted dark:text-slate-400">
              Estás a punto de eliminar esta transacción:
            </p>
            <div className="rounded-lg border border-line bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-800">
              <p className="font-medium">
                {deletingTxn.description ||
                  (deletingTxn.type === "transfer"
                    ? "Transferencia"
                    : (deletingTxn.category_id && byId.cats.get(deletingTxn.category_id)) || "—")}
              </p>
              <p className="mt-1 text-ink-muted dark:text-slate-400">
                {TYPE_LABELS[deletingTxn.type as TxnType]} · {deletingTxn.date} ·{" "}
                <span className="font-semibold text-ink dark:text-slate-200">
                  {deletingTxn.type === "income" ? "+" : deletingTxn.type === "expense" ? "−" : ""}
                  {formatMoney(deletingTxn.amount, deletingTxn.currency)}
                </span>
              </p>
              {deletingTxn.category_id && (
                <p className="mt-0.5 text-xs text-ink-muted dark:text-slate-500">
                  {byId.cats.get(deletingTxn.category_id)}
                  {deletingTxn.payment_method_id
                    ? ` · ${byId.pms.get(deletingTxn.payment_method_id)}`
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
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-50"
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
        <form onSubmit={handleUpdate} className="space-y-4">
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
          <div className="grid grid-cols-4 gap-3">
            <div>
              <label className="label">Monto</label>
              <input
                className="input"
                inputMode="decimal"
                pattern="^\d+(\.\d{1,2})?$"
                required
                value={editAmount}
                onChange={(e) => setEditAmount(e.target.value)}
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
                    value={editMethodId}
                    onChange={(e) => { setEditMethodId(e.target.value); setEditCycleHint(null); }}
                  >
                    <option value="">Selecciona…</option>
                    {(methods.data ?? []).map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">Hacia</label>
                  <select
                    className="input"
                    required
                    value={editMethodToId}
                    onChange={(e) => setEditMethodToId(e.target.value)}
                  >
                    <option value="">Selecciona…</option>
                    {(methods.data ?? [])
                      .filter((m) => m.id !== editMethodId)
                      .map((m) => (
                        <option key={m.id} value={m.id}>{m.name}</option>
                      ))}
                  </select>
                </div>
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
                  <label className="label">Método de pago</label>
                  <select
                    className="input"
                    required
                    value={editMethodId}
                    onChange={(e) => { setEditMethodId(e.target.value); setEditCycleHint(null); }}
                  >
                    <option value="">Selecciona…</option>
                    {(methods.data ?? []).map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </select>
                </div>
              </>
            )}
          </div>

          {editCollision && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-700 dark:bg-amber-900/20">
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

          {/* Fila 3 — Descripción · Moneda */}
          <div className="grid grid-cols-4 gap-3">
            <div className="col-span-3">
              <label className="label">Descripción</label>
              <input
                className="input"
                placeholder="¿En qué fue?"
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
              />
            </div>
            <div>
              <label className="label">Moneda</label>
              <select
                className="input"
                value={editCurrency}
                onChange={(e) => setEditCurrency(e.target.value)}
              >
                <option value="MXN">MXN</option>
                <option value="USD">USD</option>
              </select>
            </div>
          </div>

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
      </Modal>
    </div>
  );
}
