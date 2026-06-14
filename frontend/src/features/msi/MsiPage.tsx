// MSI: vista por plan y proyección global mes × tarjeta (MSI-06),
// conversión de compras a MSI (MSI-01) y liquidación anticipada (MSI-07).
import { useMemo, useState } from "react";
import { useTransactions } from "../../api/transactions";
import { usePaymentMethods } from "../../api/catalogs";
import {
  useCreateMsiPlan,
  useMsiPlans,
  useMsiProjection,
  useSettleMsiPlan,
} from "../../api/msi";
import { formatMoney } from "../../lib/money";

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
        Elige una compra hecha con tarjeta y el número de meses.
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
                {t.date} · {t.description || "Compra"} · {formatMoney(t.amount, t.currency)}
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

export default function MsiPage() {
  const plans = useMsiPlans();
  const projection = useMsiProjection();
  const settle = useSettleMsiPlan();

  const projectionByMonth = useMemo(() => {
    const months = [...new Set((projection.data ?? []).map((r) => r.month))].sort();
    const cards = [...new Set((projection.data ?? []).map((r) => r.card_alias))];
    return { months, cards };
  }, [projection.data]);

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="text-xl font-semibold">Meses sin intereses</h1>

      <ConvertSection />

      {(plans.data ?? []).length === 0 ? (
        <div className="card grid h-40 place-items-center p-8 text-center text-sm text-ink-muted dark:text-slate-400">
          Sin planes MSI. Convierte una compra con tarjeta arriba.
        </div>
      ) : (
        (plans.data ?? []).map((summary) => {
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
                    {done} de {total} cuotas · restan {formatMoney(summary.remaining_amount)}
                  </span>
                  <span>liquidas el {summary.projected_payoff}</span>
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
                      #{i.number} · {i.estimated_charge_date} · {formatMoney(i.amount)} ·{" "}
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
