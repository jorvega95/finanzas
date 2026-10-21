// Dashboard (R6): resumen mensual de gasto devengado (DSH-02/04),
// desgloses (DSH-03), tendencia 6 meses y próximos compromisos (DSH-05).
// Presupuestos con barra de avance (PRE-04, R10). Toggle "excluir eventos"
// (EVT-04) para ver el mes sin gastos extraordinarios.
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
import { useNetWorth } from "../../api/investments";
import { useExcludeEvents } from "../../lib/excludeEvents";
import { formatMoney } from "../../lib/money";
import { formatDate } from "../../lib/dates";
import { useChartTheme } from "../../lib/chartTheme";
import { useSpace } from "../spaces/SpaceProvider";
import Icon, { type IconName } from "../../components/ui/Icon";
import NatureDetailModal from "./NatureDetailModal";
import { CHART_COLORS as COLORS, NATURE_LABELS } from "./nature";

const KIND_ICONS: Record<string, IconName> = {
  card_due: "card",
  msi_quota: "calendar",
  recurring: "refresh",
  commitment: "party", // CXP-08: pago a proveedor
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

function BudgetsSection({ month, excludeEvents }: { month: string; excludeEvents: boolean }) {
  const budgets = useBudgets(month, excludeEvents);
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
    <section className="card p-4 sm:p-5 xl:col-span-3">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Presupuestos</h2>
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
        <p className="text-sm text-ink-muted">
          Sin presupuestos este mes.
        </p>
      ) : (
        <ul className="grid gap-x-8 gap-y-3 xl:grid-cols-3">
          {(budgets.data ?? []).map((row) => {
            const consumed = Number(row.consumed);
            const total = Number(row.budget.amount);
            const ratio = total > 0 ? Math.min(consumed / total, 1) : 0;
            const over = Number(row.remaining) < 0;
            return (
              <li key={row.budget.id}>
                <div className="mb-1 flex items-center justify-between text-sm">
                  <span className="font-medium">{row.category_name}</span>
                  <span className={over ? "text-red-600 dark:text-red-400" : "text-ink-muted"}>
                    {formatMoney(row.consumed)} / {formatMoney(row.budget.amount)}
                    <button
                      aria-label="Eliminar presupuesto"
                      className="ml-2 text-xs text-ink-muted hover:text-red-600"
                      onClick={() => deleteBudget.mutate(row.budget.id)}
                    >
                      <Icon name="x" className="inline size-3.5 align-[-2px]" />
                    </button>
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-muted">
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
  const [natureDetail, setNatureDetail] = useState<string | null>(null);
  const [excludeEvents, setExcludeEvents] = useExcludeEvents(); // EVT-04
  const dashboard = useDashboard(month, excludeEvents);
  const data = dashboard.data;
  const totals = data?.totals;
  const currency = activeSpace.base_currency;
  const chart = useChartTheme();
  const lastNetWorth = (useNetWorth().data ?? []).at(-1); // DSH-07

  // DSH-06: cada rebanada es navegable; `key` conserva el valor de dominio.
  const natureData = Object.entries(data?.by_nature ?? {}).map(([key, value]) => ({
    key,
    name: NATURE_LABELS[key] ?? key,
    value: Number(value),
    amount: value,
  }));
  const natureTotal = natureData.reduce((sum, row) => sum + row.value, 0);

  return (
    <div className="page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Gasto devengado del mes y lo que viene.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label
            className="flex items-center gap-1.5 text-sm text-ink-muted"
            title="Oculta los gastos e ingresos ligados a eventos (boda, viaje…) en totales, gráficas y presupuestos"
          >
            <input
              type="checkbox"
              checked={excludeEvents}
              onChange={(e) => setExcludeEvents(e.target.checked)}
            />
            Excluir eventos
          </label>
          <input
            type="month"
            className="input w-auto"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
          />
        </div>
      </div>

      {/* Totales del mes (DSH-02) + patrimonio neto actual (DSH-07) */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          ["Ingresos", totals?.income, "text-emerald-600 dark:text-emerald-400"],
          ["Gastos", totals?.expenses, "text-red-600 dark:text-red-400"],
          ["Neto", totals?.net, ""],
        ].map(([label, value, color]) => (
          <div key={label as string} className="card p-4 sm:p-5">
            <p className="text-sm text-ink-muted">{label}</p>
            <p className={`tabular mt-2 text-xl font-semibold tracking-tight sm:text-2xl ${color}`}>
              {value !== undefined ? formatMoney(value as string, currency) : "…"}
            </p>
          </div>
        ))}
        <div
          className="card p-4 sm:p-5"
          title="Situación actual: activos − pasivos al último snapshot, sin importar el mes elegido"
        >
          <p className="text-sm text-ink-muted">Patrimonio neto (hoy)</p>
          <p
            className={`tabular mt-2 text-xl font-semibold tracking-tight sm:text-2xl ${
              lastNetWorth && Number(lastNetWorth.net_worth) < 0
                ? "text-red-600 dark:text-red-400"
                : ""
            }`}
          >
            {lastNetWorth ? formatMoney(lastNetWorth.net_worth, currency) : "…"}
          </p>
          {lastNetWorth && (
            <p className="tabular mt-1 text-xs text-ink-muted">
              Activos {formatMoney(lastNetWorth.assets, currency)} · Pasivos{" "}
              {formatMoney(lastNetWorth.liabilities, currency)}
            </p>
          )}
        </div>
      </div>

      {/* xl: tendencia, categoría y naturaleza en 2/3; próximos compromisos ocupa
          el tercio derecho en dos filas; presupuestos a lo ancho. */}
      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {/* Tendencia 6 meses (DSH-03) */}
        <section className="card p-4 sm:p-5 lg:col-span-2">
          <h2 className="mb-4 text-sm font-semibold">Tendencia 6 meses</h2>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data?.trend ?? []}>
              <CartesianGrid vertical={false} stroke={chart.grid} />
              <XAxis dataKey="month" fontSize={11} tick={{ fill: chart.tick }} stroke={chart.axis} />
              <YAxis fontSize={11} tick={{ fill: chart.tick }} stroke={chart.axis} />
              <Tooltip
                formatter={(v) => formatMoney(String(v), currency)}
                cursor={chart.cursorLine}
                {...chart.tooltip}
              />
              <Legend
                formatter={(value) => <span style={{ color: chart.legend }}>{value}</span>}
              />
              <Line type="monotone" dataKey="income" name="Ingresos" stroke="#10b981" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="expenses" name="Gastos" stroke="#ef4444" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </section>

        {/* Próximos compromisos (DSH-05) */}
        <section className="card p-4 sm:p-5 xl:row-span-2">
          <h2 className="mb-4 text-sm font-semibold">Próximos compromisos</h2>
          {(data?.upcoming ?? []).length === 0 ? (
            <p className="text-sm text-ink-muted">Nada pendiente.</p>
          ) : (
            <ul className="divide-y divide-line">
              {(data?.upcoming ?? []).map((item) => (
                <li key={`${item.kind}-${item.ref_id}`} className="flex items-center justify-between py-2 text-sm">
                  <span className="flex items-center gap-2">
                    <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-muted text-ink-muted">
                      <Icon name={KIND_ICONS[item.kind] ?? "calendar"} className="size-3.5" />
                    </span>
                    <span>
                      {item.description}
                      {item.is_overdue && (
                        <span className="ml-2 rounded-full bg-red-500/15 px-2 py-0.5 text-xs text-red-700 dark:text-red-300">
                          Vencido
                        </span>
                      )}
                    </span>
                  </span>
                  <span className="text-right">
                    <span className="tabular font-medium">{formatMoney(item.amount, currency)}</span>
                    <span className="ml-2 text-xs text-ink-muted">{formatDate(item.date)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Por categoría (DSH-03) */}
        <section className="card p-4 sm:p-5">
          <h2 className="mb-4 text-sm font-semibold">Gasto por categoría</h2>
          {(data?.by_category ?? []).length === 0 ? (
            <p className="text-sm text-ink-muted">Sin gastos este mes.</p>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart
                data={(data?.by_category ?? []).map((r) => ({ ...r, value: Number(r.total) }))}
                layout="vertical"
              >
                <XAxis type="number" fontSize={11} tick={{ fill: chart.tick }} stroke={chart.axis} />
                <YAxis
                  type="category"
                  dataKey="category_name"
                  width={110}
                  fontSize={11}
                  tick={{ fill: chart.tick }}
                  stroke={chart.axis}
                />
                <Tooltip
                  formatter={(v) => formatMoney(String(v), currency)}
                  cursor={chart.cursorFill}
                  {...chart.tooltip}
                />
                <Bar dataKey="value" name="Gasto" radius={[0, 4, 4, 0]}>
                  {(data?.by_category ?? []).map((_, index) => (
                    <Cell key={index} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </section>

        {/* Por naturaleza (CAT-03/DSH-03), con drill-down (DSH-06) */}
        <section className="card p-4 sm:p-5">
          <h2 className="mb-4 text-sm font-semibold">Por naturaleza</h2>
          {natureData.length === 0 ? (
            <p className="text-sm text-ink-muted">Sin gastos este mes.</p>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie
                    data={natureData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={50}
                    cursor="pointer"
                    onClick={(_, index) => setNatureDetail(natureData[index].key)}
                    label={({ name, x, y, textAnchor }) => (
                      <text
                        x={x}
                        y={y}
                        textAnchor={textAnchor}
                        dominantBaseline="central"
                        fill={chart.tick}
                        fontSize={12}
                      >
                        {name}
                      </text>
                    )}
                    labelLine={{ stroke: chart.axis }}
                  >
                    {natureData.map((_, index) => (
                      <Cell key={index} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v) => formatMoney(String(v), currency)} {...chart.tooltip} />
                </PieChart>
              </ResponsiveContainer>
              {/* Misma acción que la rebanada, accesible por teclado. */}
              <ul className="mt-3 space-y-1">
                {natureData.map((row, index) => (
                  <li key={row.key}>
                    <button
                      className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-sm transition hover:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      onClick={() => setNatureDetail(row.key)}
                    >
                      <span
                        aria-hidden
                        className="size-2.5 shrink-0 rounded-full"
                        style={{ backgroundColor: COLORS[index % COLORS.length] }}
                      />
                      <span className="flex-1 text-left">Ver detalle de {row.name.toLowerCase()}</span>
                      <span className="tabular-nums">{formatMoney(row.amount, currency)}</span>
                      <span className="w-10 text-right text-xs tabular-nums text-ink-muted">
                        {natureTotal > 0 ? Math.round((row.value / natureTotal) * 100) : 0}%
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <BudgetsSection month={month} excludeEvents={excludeEvents} />
      </div>

      <NatureDetailModal
        month={month}
        excludeEvents={excludeEvents}
        nature={natureDetail}
        currency={currency}
        onClose={() => setNatureDetail(null)}
      />
    </div>
  );
}
