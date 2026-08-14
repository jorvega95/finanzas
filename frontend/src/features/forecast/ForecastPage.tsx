// Pronóstico de flujo a futuro (PRO-01..06, R17): proyecta ingresos y
// obligaciones (pagos de TDC con MSI/domiciliados, gastos no-crédito) sobre un
// horizonte y detecta sobregiros (cuándo el saldo líquido se vuelve negativo).
import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useForecast, type ForecastEvent } from "../../api/forecast";
import { formatDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import { useChartTheme } from "../../lib/chartTheme";
import { useSpace } from "../spaces/SpaceProvider";

const HORIZONS = [3, 6, 12];

const KIND_LABEL: Record<ForecastEvent["kind"], string> = {
  income: "Ingreso",
  recurring_income: "Nómina/recurrente",
  card_due: "Pago de tarjeta",
  recurring_expense: "Domiciliado",
  manual_expense: "Gasto programado",
};

const KIND_ICON: Record<ForecastEvent["kind"], string> = {
  income: "💰",
  recurring_income: "💵",
  card_due: "💳",
  recurring_expense: "🔁",
  manual_expense: "🧾",
};

export default function ForecastPage() {
  const { activeSpace } = useSpace();
  const currency = activeSpace.base_currency;
  const chart = useChartTheme();
  const [horizon, setHorizon] = useState(6);
  const [adjustmentInput, setAdjustmentInput] = useState("0");
  const [adjustment, setAdjustment] = useState("0");

  const forecast = useForecast(horizon, adjustment);
  const data = forecast.data;

  const chartData = useMemo(() => {
    if (!data) return [];
    const points = [{ date: data.generated_for, balance: Number(data.starting_cash) }];
    for (const ev of data.events) {
      points.push({ date: ev.date, balance: Number(ev.balance_after) });
    }
    return points;
  }, [data]);

  const hasOverdraft = !!data?.first_overdraft_date;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Pronóstico de flujo</h1>
          <p className="text-sm text-ink-muted dark:text-slate-400">
            Proyección de ingresos y pagos a futuro; te avisa si una deuda no será pagable.
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
          {HORIZONS.map((h) => (
            <button
              key={h}
              onClick={() => setHorizon(h)}
              className={`rounded-md px-3 py-1 text-sm transition ${
                horizon === h
                  ? "bg-card font-medium text-accent-strong shadow-sm dark:bg-slate-900 dark:text-teal-300"
                  : "text-ink-muted dark:text-slate-400"
              }`}
            >
              {h} meses
            </button>
          ))}
        </div>
      </div>

      {/* PRO-02: caja inicial = saldos débito/prepago + ajuste manual */}
      <section className="card flex flex-wrap items-end gap-4 p-5">
        <div>
          <label className="mb-1 block text-xs text-ink-muted dark:text-slate-400">
            Ajuste de caja inicial (efectivo/banco no registrado)
          </label>
          <div className="flex gap-2">
            <input
              className="input w-40"
              inputMode="decimal"
              pattern="^-?\d+(\.\d{1,2})?$"
              value={adjustmentInput}
              onChange={(e) => setAdjustmentInput(e.target.value)}
            />
            <button className="btn-secondary" onClick={() => setAdjustment(adjustmentInput || "0")}>
              Aplicar
            </button>
          </div>
        </div>
        {data && (
          <div className="text-sm">
            <p className="text-xs text-ink-muted dark:text-slate-400">Caja inicial estimada</p>
            <p className="text-lg font-semibold">{formatMoney(data.starting_cash, currency)}</p>
          </div>
        )}
      </section>

      {forecast.isLoading && (
        <p className="text-sm text-ink-muted dark:text-slate-400">Calculando pronóstico…</p>
      )}
      {forecast.error && (
        <p className="text-sm text-red-600 dark:text-red-400">{forecast.error.message}</p>
      )}

      {data && (
        <>
          {/* PRO-05: alerta de sobregiro */}
          {hasOverdraft ? (
            <div className="rounded-xl border border-red-300 bg-red-50 p-4 dark:border-red-900 dark:bg-red-950/40">
              <p className="font-semibold text-red-700 dark:text-red-300">
                ⚠️ Sobregiro proyectado el {formatDate(data.first_overdraft_date!)}
              </p>
              <p className="mt-1 text-sm text-red-700 dark:text-red-300">
                Con tus ingresos proyectados no alcanzarás a cubrir todos los pagos. Faltante
                acumulado en el horizonte: <strong>{formatMoney(data.total_shortfall, currency)}</strong>.
              </p>
            </div>
          ) : (
            <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950/40">
              <p className="font-semibold text-emerald-700 dark:text-emerald-300">
                ✅ Sin sobregiros en los próximos {horizon} meses
              </p>
              <p className="mt-1 text-sm text-emerald-700 dark:text-emerald-300">
                Saldo mínimo proyectado: {formatMoney(data.min_balance, currency)}
                {data.min_balance_date ? ` (${formatDate(data.min_balance_date)})` : ""}.
              </p>
            </div>
          )}

          {/* Saldo líquido proyectado */}
          <section className="card p-5">
            <h2 className="mb-3 font-semibold">Saldo líquido proyectado</h2>
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="bal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0d9488" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#0d9488" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
                <XAxis
                  dataKey="date"
                  fontSize={11}
                  tickFormatter={formatDate}
                  tick={{ fill: chart.tick }}
                  stroke={chart.axis}
                />
                <YAxis fontSize={11} tick={{ fill: chart.tick }} stroke={chart.axis} />
                <Tooltip
                  formatter={(v) => formatMoney(String(v), currency)}
                  labelFormatter={(l) => formatDate(String(l))}
                  cursor={chart.cursorLine}
                  {...chart.tooltip}
                />
                <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="4 4" />
                <Area
                  type="stepAfter"
                  dataKey="balance"
                  stroke="#0d9488"
                  fill="url(#bal)"
                  name="Saldo"
                />
              </AreaChart>
            </ResponsiveContainer>
          </section>

          {/* Timeline de eventos */}
          <section className="card p-5">
            <h2 className="mb-3 font-semibold">Línea de tiempo</h2>
            {data.events.length === 0 ? (
              <p className="text-sm text-ink-muted dark:text-slate-400">
                Sin movimientos proyectados en el horizonte.
              </p>
            ) : (
              <ul className="divide-y divide-line dark:divide-slate-800">
                {data.events.map((ev, i) => {
                  const isIn = ev.direction === "in";
                  const balNeg = Number(ev.balance_after) < 0;
                  return (
                    <li
                      key={`${ev.kind}-${ev.date}-${i}`}
                      className="flex items-center justify-between gap-3 py-2 text-sm"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <span aria-hidden>{KIND_ICON[ev.kind]}</span>
                        <span className="min-w-0">
                          <span className="truncate">{ev.description}</span>
                          <span className="ml-2 text-xs text-ink-muted dark:text-slate-500">
                            {KIND_LABEL[ev.kind]}
                            {ev.is_estimate ? " · estimado" : ""}
                          </span>
                          {!ev.covered && (
                            <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">
                              Faltan {formatMoney(ev.shortfall, currency)}
                            </span>
                          )}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-3 text-right">
                        <span
                          className={
                            isIn
                              ? "font-medium text-emerald-600 dark:text-emerald-400"
                              : "font-medium text-red-600 dark:text-red-400"
                          }
                        >
                          {isIn ? "+" : "−"}
                          {formatMoney(ev.amount, currency)}
                        </span>
                        <span
                          className={`w-28 text-xs ${
                            balNeg
                              ? "text-red-600 dark:text-red-400"
                              : "text-ink-muted dark:text-slate-400"
                          }`}
                        >
                          {formatMoney(ev.balance_after, currency)}
                        </span>
                        <span className="w-20 text-xs text-ink-muted dark:text-slate-500">
                          {formatDate(ev.date)}
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
