// MSI: vista por plan y proyección global mes × tarjeta (MSI-06),
// conversión de compras a MSI (MSI-01), registro por cuota en curso (MSI-10) y liquidación anticipada (MSI-07).
import { useMemo, useState } from "react";
import { useTransactions } from "../../api/transactions";
import { usePaymentMethods } from "../../api/catalogs";
import {
  useCreateMsiPlan,
  useCreateMsiBackfill,
  useMsiPlans,
  useMsiProjection,
  useSettleMsiPlan,
} from "../../api/msi";
import { useCards } from "../../api/cards";
import { useCategories } from "../../api/catalogs";
import { formatMoney } from "../../lib/money";
import { formatDate } from "../../lib/dates";

const STATUS_LABELS: Record<string, string> = {
  active: "Activo",
  completed: "Completado",
  settled_early: "Liquidado anticipado",
};

function ConvertSection() {
  const txns = useTransactions({ type: "expense", limit: 100 });
  const methods = usePaymentMethods();
  const create = useCreateMsiPlan();
  const [txnId, setTxnId] = useState("");
  const [months, setMonths] = useState("12");

  // MSI-01: solo compras con tarjeta de crédito son convertibles (TAR-02).
  const creditMethodIds = useMemo(
    () =>
      new Set(
        (methods.data ?? []).filter((m) => m.type === "credit_card").map((m) => m.id),
      ),
    [methods.data],
  );
  const candidates = (txns.data?.items ?? []).filter(
    (t) => t.payment_method_id !== null && creditMethodIds.has(t.payment_method_id),
  );

  return (
    <section className="card p-5">
      <h2 className="mb-1 font-semibold">Convertir compra a MSI</h2>
      <p className="mb-3 text-xs text-ink-muted dark:text-slate-400">
        Elige una compra ya registrada con tarjeta y el número de meses.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            { transaction_id: txnId, months: Number(months) },
            { onSuccess: () => setTxnId("") },
          );
        }}
        className="flex flex-wrap items-end gap-2"
      >
        <div className="min-w-64 flex-1">
          <label className="label">Compra</label>
          <select className="input" required value={txnId} onChange={(e) => setTxnId(e.target.value)}>
            <option value="">Selecciona…</option>
            {candidates.map((t) => (
              <option key={t.id} value={t.id}>
                {formatDate(t.date)} · {t.description || "Compra"} · {formatMoney(t.amount, t.currency)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Meses</label>
          <input
            className="input w-24"
            type="number"
            min={2}
            max={60}
            required
            value={months}
            onChange={(e) => setMonths(e.target.value)}
          />
        </div>
        <button className="btn-primary" disabled={create.isPending}>Crear plan</button>
      </form>
      {create.error && (
        <p className="mt-2 text-sm text-red-600 dark:text-red-400">{create.error.message}</p>
      )}
    </section>
  );
}

function BackfillSection() {
  const cards = useCards();
  const categories = useCategories();
  const create = useCreateMsiBackfill();

  const [form, setForm] = useState({
    description: "",
    monthly_amount: "",
    currency: "MXN",
    credit_card_id: "",
    current_number: "1",
    total_months: "12",
    category_id: "",
    current_is_charged: true,
  });

  const activeCards = (cards.data ?? []).filter((c) => c.is_active);
  const expenseCategories = (categories.data ?? []).filter(
    (c) => c.kind === "expense" && c.is_active,
  );

  function set(key: string, value: string | boolean) {
    setForm((prev) => {
      const next = { ...prev, [key]: value };
      if (key === "credit_card_id" && typeof value === "string") {
        const card = activeCards.find((c) => c.id === value);
        if (card) next.currency = card.currency;
      }
      return next;
    });
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      {
        description: form.description,
        monthly_amount: form.monthly_amount,
        currency: form.currency,
        credit_card_id: form.credit_card_id,
        current_number: Number(form.current_number),
        total_months: Number(form.total_months),
        category_id: form.category_id,
        current_is_charged: form.current_is_charged,
      },
      {
        onSuccess: () =>
          setForm({
            description: "",
            monthly_amount: "",
            currency: "MXN",
            credit_card_id: "",
            current_number: "1",
            total_months: "12",
            category_id: "",
            current_is_charged: true,
          }),
      },
    );
  }

  return (
    <section className="card p-5">
      <h2 className="mb-1 font-semibold">Registrar MSI existente</h2>
      <p className="mb-3 text-xs text-ink-muted dark:text-slate-400">
        Registra una compra a meses que ya tenías antes de usar el sistema. Ingresa el cobro que
        aparece en tu estado de cuenta actual (ej. "Pago 6 de 12 · $2,692").
      </p>
      <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label className="label">Descripción</label>
          <input
            className="input"
            type="text"
            maxLength={200}
            placeholder="Ej. TV, Refrigerador, Laptop…"
            required
            value={form.description}
            onChange={(e) => set("description", e.target.value)}
          />
        </div>
        <div>
          <label className="label">Tarjeta</label>
          <select
            className="input"
            required
            value={form.credit_card_id}
            onChange={(e) => set("credit_card_id", e.target.value)}
          >
            <option value="">Selecciona tarjeta…</option>
            {activeCards.map((c) => (
              <option key={c.id} value={c.id}>
                {c.alias} ({c.currency})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Monto de la cuota ({form.currency})</label>
          <input
            className="input"
            type="number"
            min="0.01"
            step="0.01"
            placeholder="0.00"
            required
            value={form.monthly_amount}
            onChange={(e) => set("monthly_amount", e.target.value)}
          />
        </div>
        <div>
          <label className="label">Cuota actual (N)</label>
          <input
            className="input"
            type="number"
            min={1}
            max={60}
            required
            value={form.current_number}
            onChange={(e) => set("current_number", e.target.value)}
          />
        </div>
        <div>
          <label className="label">Total de meses (M)</label>
          <input
            className="input"
            type="number"
            min={2}
            max={60}
            required
            value={form.total_months}
            onChange={(e) => set("total_months", e.target.value)}
          />
        </div>
        <div className="sm:col-span-2">
          <label className="label">Categoría</label>
          <select
            className="input"
            required
            value={form.category_id}
            onChange={(e) => set("category_id", e.target.value)}
          >
            <option value="">Selecciona categoría…</option>
            {expenseCategories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div className="sm:col-span-2">
          <div className="flex items-center gap-2">
            <input
              id="current-is-charged"
              type="checkbox"
              className="h-4 w-4 rounded border-line accent-accent"
              checked={form.current_is_charged}
              onChange={(e) => set("current_is_charged", e.target.checked)}
            />
            <label htmlFor="current-is-charged" className="text-sm font-medium">
              Esta cuota ya aparece en mi estado de cuenta anterior (ya cerrado)
            </label>
          </div>
          <p className="mt-1 pl-6 text-xs text-ink-muted dark:text-slate-400">
            {form.current_is_charged
              ? `La cuota ${form.current_number} se marcará como pagada (✅) — ya viene en tu Pago pendiente. La cuota ${Number(form.current_number) + 1} entrará al ciclo en curso (🧾).`
              : `La cuota ${form.current_number} entrará al ciclo en curso como cobrada (🧾); las anteriores como pagadas.`}
          </p>
        </div>
        <div className="sm:col-span-2">
          <button className="btn-primary" disabled={create.isPending}>
            Registrar MSI existente
          </button>
        </div>
      </form>
      {create.error && (
        <p className="mt-2 text-sm text-red-600 dark:text-red-400">{create.error.message}</p>
      )}
    </section>
  );
}

export default function MsiPage() {
  const plans = useMsiPlans();
  const projection = useMsiProjection();
  const settle = useSettleMsiPlan();

  const sortedPlans = useMemo(
    () =>
      [...(plans.data ?? [])].sort(
        (a, b) => (a.charged_count + a.pending_count) - (b.charged_count + b.pending_count),
      ),
    [plans.data],
  );

  const projectionByMonth = useMemo(() => {
    const months = [...new Set((projection.data ?? []).map((r) => r.month))].sort();
    const cards = [...new Set((projection.data ?? []).map((r) => r.card_alias))];
    return { months, cards };
  }, [projection.data]);

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="text-xl font-semibold">Meses sin intereses</h1>

      <ConvertSection />
      <BackfillSection />

      {sortedPlans.length === 0 ? (
        <div className="card grid h-40 place-items-center p-8 text-center text-sm text-ink-muted dark:text-slate-400">
          Sin planes MSI. Convierte una compra con tarjeta o registra un MSI existente.
        </div>
      ) : (
        sortedPlans.map((summary) => {
          const done = summary.paid_count + summary.charged_count;
          const total = summary.plan.months;
          return (
            <section key={summary.plan.id} className="card p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="font-semibold">{summary.description || "Compra MSI"}</h3>
                  <p className="text-xs text-ink-muted dark:text-slate-400">
                    {summary.card_alias} · {formatMoney(summary.plan.total_amount)} a{" "}
                    {summary.plan.months} meses · {STATUS_LABELS[summary.plan.status]}
                  </p>
                </div>
                {summary.plan.status === "active" && summary.pending_count > 0 && (
                  <button className="btn-secondary" onClick={() => settle.mutate(summary.plan.id)}>
                    Liquidar anticipado
                  </button>
                )}
              </div>
              <div className="mt-3">
                <div className="mb-1 flex justify-between text-xs text-ink-muted dark:text-slate-400">
                  <span>
                    {done} de {total} cuotas · restan{" "}
                    <span className="font-medium text-ink dark:text-white">
                      {formatMoney(summary.remaining_amount)}
                    </span>
                  </span>
                  <span>
                    último cobro: {formatDate(summary.projected_payoff)} · pago: {formatDate(summary.projected_payment_date)}
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                  <div
                    className="h-full rounded-full bg-accent transition-all"
                    style={{ width: `${total ? Math.round((done / total) * 100) : 0}%` }}
                  />
                </div>
              </div>
              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-accent">Ver cuotas</summary>
                <ul className="mt-2 grid grid-cols-2 gap-1 text-xs text-ink-muted dark:text-slate-400 md:grid-cols-3">
                  {summary.installments.map((i) => (
                    <li key={i.id}>
                      #{i.number} · {formatDate(i.estimated_charge_date)} · {formatMoney(i.amount)} ·{" "}
                      {i.status === "paid"
                        ? "✅"
                        : i.status === "charged"
                          ? "🧾"
                          : i.status === "canceled"
                            ? "✖"
                            : "⏳"}
                    </li>
                  ))}
                </ul>
              </details>
            </section>
          );
        })
      )}

      {(projection.data ?? []).length > 0 && (
        <section className="card p-5">
          <h2 className="mb-3 font-semibold">Comprometido por mes</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-ink-muted dark:text-slate-400">
                  <th className="py-1 pr-4">Tarjeta</th>
                  {projectionByMonth.months.map((m) => (
                    <th key={m} className="py-1 pr-4">{m}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {projectionByMonth.cards.map((alias) => (
                  <tr key={alias} className="border-t border-line dark:border-slate-800">
                    <td className="py-1.5 pr-4 font-medium">{alias}</td>
                    {projectionByMonth.months.map((month) => {
                      const row = (projection.data ?? []).find(
                        (r) => r.card_alias === alias && r.month === month,
                      );
                      return (
                        <td key={month} className="py-1.5 pr-4">
                          {row ? formatMoney(row.amount) : "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
