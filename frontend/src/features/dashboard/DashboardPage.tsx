// Dashboard (R6): resumen mensual con doble vista devengado/flujo (DSH-04),
// desgloses (DSH-03), tendencia 6 meses y próximos compromisos (DSH-05).
// Presupuestos con barra de avance (PRE-04, R10).
import { useState, type FormEvent } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useCategories } from "../../api/catalogs";
import {
  useBudgets,
  useCopyBudgets,
  useCreateBudget,
  useDashboard,
  useDeleteBudget,
} from "../../api/dashboard";
import { formatMoney } from "../../lib/money";
import { formatDate } from "../../lib/dates";
import { useSpace } from "../spaces/SpaceProvider";

const COLORS = ["#0d9488", "#f59e0b", "#6366f1", "#ef4444", "#10b981", "#8b5cf6", "#f97316", "#06b6d4"];
const NATURE_LABELS: Record<string, string> = {
  fixed: "Fijo",
  variable: "Variable",
  discretionary: "Discrecional",
};
const KIND_ICONS: Record<string, string> = {
  card_due: "💳",
  msi_quota: "📅",
  recurring: "🔁",
};

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function prevMonth(month: string): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 2, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function BudgetsSection({ month }: { month: string }) {
  const budgets = useBudgets(month);
  const categories = useCategories();
  const createBudget = useCreateBudget();
  const deleteBudget = useDeleteBudget();
  const copyBudgets = useCopyBudgets();
  const [categoryId, setCategoryId] = useState("");
  const [amount, setAmount] = useState("");

  const usedCategories = new Set((budgets.data ?? []).map((b) => b.budget.category_id));
  const available = (categories.data ?? []).filter(
    (c) => c.kind === "expense" && !c.parent_id && !usedCategories.has(c.id),
  );

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    createBudget.mutate(
      { category_id: categoryId, month, amount },
      { onSuccess: () => { setCategoryId(""); setAmount(""); } },
    );
  }

  return (
    <section className="card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold">Presupuestos</h2>
        <button
          className="btn-secondary text-xs"
          onClick={() => copyBudgets.mutate({ from_month: prevMonth(month), to_month: month })}
        >
          Repetir mes anterior
        </button>
      </div>

      <form onSubmit={handleCreate} className="mb-4 flex flex-wrap gap-2">
        <select
          className="input w-44"
          required
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
        >
          <option value="">Categoría…</option>
          {available.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <input
          className="input w-32"
          inputMode="decimal"
          pattern="^\d+(\.\d{1,2})?$"
          placeholder="Monto"
          required
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
        <button className="btn-primary" disabled={createBudget.isPending}>Agregar</button>
      </form>
      {createBudget.error && (
        <p className="mb-2 text-sm text-red-600 dark:text-red-400">{createBudget.error.message}</p>
      )}

      {(budgets.data ?? []).length === 0 ? (
        <p className="text-sm text-ink-muted dark:text-slate-400">
          Sin presupuestos este mes.
        </p>
      ) : (
        <ul className="space-y-3">
          {(budgets.data ?? []).map((row) => {
            const consumed = Number(row.consumed);
            const total = Number(row.budget.amount);
            const ratio = total > 0 ? Math.min(consumed / total, 1) : 0;
            const over = Number(row.remaining) < 0;
            return (
              <li key={row.budget.id}>
                <div className="mb-1 flex items-center justify-between text-sm">
                  <span className="font-medium">{row.category_name}</span>
                  <span className={over ? "text-red-600 dark:text-red-400" : "text-ink-muted dark:text-slate-400"}>
                    {formatMoney(row.consumed)} / {formatMoney(row.budget.amount)}
                    <button
                      aria-label="Eliminar presupuesto"
                      className="ml-2 text-xs text-ink-muted hover:text-red-600"
                      onClick={() => deleteBudget.mutate(row.budget.id)}
                    >
                      ✕
                    </button>
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                  <div
                    className={`h-full rounded-full transition-all ${
                      over ? "bg-red-500" : ratio >= 0.8 ? "bg-amber-500" : "bg-accent"
                    }`}
                    style={{ width: `${Math.round(ratio * 100)}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default function DashboardPage() {
  const { activeSpace } = useSpace();
  const [month, setMonth] = useState(currentMonth);
  const [view, setView] = useState<"accrual" | "cash_flow">("accrual");
  const dashboard = useDashboard(month);
  const data = dashboard.data;
  const totals = data?.[view];
  const currency = activeSpace.base_currency;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <div className="flex items-center gap-2">
          <div
            className="flex rounded-lg border border-line p-0.5 dark:border-slate-700"
            title="Devengado: cuándo compraste. Flujo: cuándo pagaste (la confusión #1 con TDC)."
          >
            {(["accrual", "cash_flow"] as const).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`rounded-md px-3 py-1 text-xs font-medium transition ${
                  view === v
                    ? "bg-accent text-white"
                    : "text-ink-muted hover:text-ink dark:text-slate-400"
                }`}
              >
                {v === "accrual" ? "Devengado" : "Flujo de caja"}
              </button>
            ))}
          </div>
          <input
            type="month"
            className="input w-auto"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
          />
        </div>
      </div>

      {/* Totales del mes (DSH-02) */}
      <div className="grid grid-cols-3 gap-3">
        {[
          ["Ingresos", totals?.income, "text-emerald-600 dark:text-emerald-400"],
          ["Gastos", totals?.expenses, "text-red-600 dark:text-red-400"],
          ["Neto", totals?.net, ""],
        ].map(([label, value, color]) => (
          <div key={label as string} className="card p-4">
            <p className="text-xs text-ink-muted dark:text-slate-400">{label}</p>
            <p className={`text-xl font-semibold ${color}`}>
              {value !== undefined ? formatMoney(value as string, currency) : "…"}
            </p>
          </div>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Tendencia 6 meses (DSH-03) */}
        <section className="card p-5">
          <h2 className="mb-3 font-semibold">Tendencia 6 meses</h2>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data?.trend ?? []}>
              <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
              <XAxis dataKey="month" fontSize={11} />
              <YAxis fontSize={11} />
              <Tooltip formatter={(v) => formatMoney(String(v), currency)} />
              <Legend />
              <Line type="monotone" dataKey="income" name="Ingresos" stroke="#10b981" dot={false} />
              <Line type="monotone" dataKey="expenses" name="Gastos" stroke="#ef4444" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </section>

        {/* Por categoría (DSH-03) */}
        <section className="card p-5">
          <h2 className="mb-3 font-semibold">Gasto por categoría</h2>
          {(data?.by_category ?? []).length === 0 ? (
            <p className="text-sm text-ink-muted dark:text-slate-400">Sin gastos este mes.</p>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart
                data={(data?.by_category ?? []).map((r) => ({ ...r, value: Number(r.total) }))}
                layout="vertical"
              >
                <XAxis type="number" fontSize={11} />
                <YAxis type="category" dataKey="category_name" width={110} fontSize={11} />
                <Tooltip formatter={(v) => formatMoney(String(v), currency)} />
                <Bar dataKey="value" name="Gasto" radius={[0, 4, 4, 0]}>
                  {(data?.by_category ?? []).map((_, index) => (
                    <Cell key={index} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </section>

        {/* Por naturaleza (CAT-03/DSH-03) */}
        <section className="card p-5">
          <h2 className="mb-3 font-semibold">Por naturaleza</h2>
          {Object.keys(data?.by_nature ?? {}).length === 0 ? (
            <p className="text-sm text-ink-muted dark:text-slate-400">Sin gastos este mes.</p>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={Object.entries(data?.by_nature ?? {}).map(([key, value]) => ({
                    name: NATURE_LABELS[key] ?? key,
                    value: Number(value),
                  }))}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={50}
                  label={(entry) => entry.name}
                >
                  {Object.keys(data?.by_nature ?? {}).map((_, index) => (
                    <Cell key={index} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v) => formatMoney(String(v), currency)} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </section>

        {/* Próximos compromisos (DSH-05) */}
        <section className="card p-5">
          <h2 className="mb-3 font-semibold">Próximos compromisos</h2>
          {(data?.upcoming ?? []).length === 0 ? (
            <p className="text-sm text-ink-muted dark:text-slate-400">Nada pendiente. 🎉</p>
          ) : (
            <ul className="divide-y divide-line dark:divide-slate-800">
              {(data?.upcoming ?? []).map((item) => (
                <li key={`${item.kind}-${item.ref_id}`} className="flex items-center justify-between py-2 text-sm">
                  <span className="flex items-center gap-2">
                    <span aria-hidden>{KIND_ICONS[item.kind]}</span>
                    <span>
                      {item.description}
                      {item.is_overdue && (
                        <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">
                          Vencido
                        </span>
                      )}
                    </span>
                  </span>
                  <span className="text-right">
                    <span className="font-medium">{formatMoney(item.amount, currency)}</span>
                    <span className="ml-2 text-xs text-ink-muted dark:text-slate-400">{formatDate(item.date)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <BudgetsSection month={month} />
    </div>
  );
}
