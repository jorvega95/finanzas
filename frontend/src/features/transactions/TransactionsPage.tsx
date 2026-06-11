// Registro de gastos (R1): captura rápida <10 s, bandeja "Por confirmar"
// (REC-03) y lista con filtros (TXN-01..03).
import { useMemo, useState, type FormEvent } from "react";
import { useCategories, usePaymentMethods } from "../../api/catalogs";
import {
  useConfirmTransaction,
  useCreateTransaction,
  useDeleteTransaction,
  useTransactions,
  type TransactionOut,
} from "../../api/transactions";
import { useSpace } from "../spaces/SpaceProvider";
import { formatMoney } from "../../lib/money";

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

export default function TransactionsPage() {
  const { activeSpace } = useSpace();
  const categories = useCategories();
  const methods = usePaymentMethods();

  const [type, setType] = useState<TxnType>("expense");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(todayISO);
  const [categoryId, setCategoryId] = useState("");
  const [methodId, setMethodId] = useState("");
  const [methodToId, setMethodToId] = useState("");
  const [description, setDescription] = useState("");
  const [currency, setCurrency] = useState(activeSpace.base_currency);
  const [formError, setFormError] = useState<string | null>(null);

  const [filterMonth, setFilterMonth] = useState(todayISO().slice(0, 7));
  const [filterType, setFilterType] = useState("");

  const create = useCreateTransaction();
  const confirm = useConfirmTransaction();
  const remove = useDeleteTransaction();

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
  const byId = useMemo(() => {
    const cats = new Map((categories.data ?? []).map((c) => [c.id, c.name]));
    const pms = new Map((methods.data ?? []).map((m) => [m.id, m.name]));
    return { cats, pms };
  }, [categories.data, methods.data]);

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
      });
      setAmount("");
      setDescription("");
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
              onChange={(e) => setDate(e.target.value)}
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
              onChange={(e) => setMethodId(e.target.value)}
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
                <div className="flex shrink-0 gap-2">
                  <button
                    className="btn-primary px-3 py-1.5"
                    onClick={() => confirm.mutate({ id: t.id })}
                  >
                    Confirmar
                  </button>
                  <button
                    className="btn-secondary px-3 py-1.5"
                    onClick={() => remove.mutate(t.id)}
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
                <div className="flex shrink-0 items-center gap-3">
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
                    aria-label="Eliminar"
                    className="text-xs text-ink-muted hover:text-red-600 dark:text-slate-500"
                    onClick={() => remove.mutate(t.id)}
                  >
                    ✕
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
