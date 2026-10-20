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
import { useStoredToggle } from "../../lib/storedToggle";
import { formatMoney } from "../../lib/money";
import { useChartTheme } from "../../lib/chartTheme";
import { useSpace } from "../spaces/SpaceProvider";
import Icon, { type IconName } from "../../components/ui/Icon";

const HORIZONS = [3, 6, 12];

const KIND_LABEL: Record<ForecastEvent["kind"], string> = {
  income: "Ingreso",
  recurring_income: "Nómina/recurrente",
  card_due: "Pago de tarjeta",
  recurring_expense: "Domiciliado",
  manual_expense: "Gasto programado",
  loan_in: "Préstamo recibido",
  loan_out: "Abono a préstamo",
  savings_in: "Retiro de ahorro",
  savings_out: "Apartado a ahorro",
  commitment: "Pago a proveedor",
};

const KIND_ICON: Record<ForecastEvent["kind"], IconName> = {
  income: "investments",
  recurring_income: "refresh",
  card_due: "card",
  recurring_expense: "refresh",
  manual_expense: "transactions",
  loan_in: "handshake",
  loan_out: "handshake",
  savings_in: "piggy",
  savings_out: "piggy",
  commitment: "party",
};

export default function ForecastPage() {
  const { activeSpace } = useSpace();
  const currency = activeSpace.base_currency;
  const chart = useChartTheme();
  const [horizon, setHorizon] = useState(6);
  const [adjustmentInput, setAdjustmentInput] = useState("0");
  const [adjustment, setAdjustment] = useState("0");

  // PRO-08: el ahorro entra completo (saldo + flujos) o no entra.
  const [includeSavings, setIncludeSavings] = useStoredToggle("finanzas.forecastIncludeSavings");
  const forecast = useForecast(horizon, adjustment, includeSavings);
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
    <div className="page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="page-title">Pronóstico de flujo</h1>
          <p className="page-subtitle">
            Proyección de ingresos y pagos a futuro; te avisa si una deuda no será pagable.
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-lg bg-muted p-1">
          {HORIZONS.map((h) => (
            <button
              key={h}
              onClick={() => setHorizon(h)}
              className={`rounded-md px-3 py-1 text-sm transition ${
                horizon === h
                  ? "bg-card font-medium text-ink shadow-sm"
                  : "text-ink-muted"
              }`}
            >
              {h} meses
            </button>
          ))}
        </div>
      </div>

      {/* PRO-02/07: caja inicial = saldos del perímetro de liquidez + ajuste manual */}
      <section className="card flex flex-wrap items-end gap-4 p-5">
        <div>
          <label className="mb-1 block text-xs text-ink-muted">
            Ajuste de caja inicial (dinero no registrado en Cuentas)
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
            <p className="text-xs text-ink-muted">Caja inicial estimada</p>
            <p className="text-lg font-semibold">{formatMoney(data.starting_cash, currency)}</p>
            {data.include_savings && (
              <p className="text-xs text-ink-muted">
                incluye {formatMoney(data.savings_included, currency)} de ahorro
              </p>
            )}
          </div>
        )}
        <label
          className="ml-auto flex items-center gap-1.5 self-center text-sm text-ink-muted"
          title="Cuenta el saldo y los movimientos de tus cuentas de ahorro como dinero disponible"
        >
          <input
            type="checkbox"
            checked={includeSavings}
            onChange={(e) => setIncludeSavings(e.target.checked)}
          />
          Incluir ahorros
        </label>
        <p className="w-full text-xs text-ink-muted">
          {includeSavings
            ? "Con ahorros: ¿me alcanza si uso lo que tengo ahorrado? Mover dinero entre tus cuentas y el ahorro no cuenta."
            : "Sin ahorros: ¿me alcanza sin tocarlos? Lo que pasa dentro de tus cuentas de ahorro y préstamos no cuenta; apartar o retirar del ahorro sí."}
        </p>
      </section>

      {forecast.isLoading && (
        <p className="text-sm text-ink-muted">Calculando pronóstico…</p>
      )}
      {forecast.error && (
        <p className="text-sm text-red-600 dark:text-red-400">{forecast.error.message}</p>
      )}

      {data && (
        <>
          {/* PRO-05: alerta de sobregiro */}
          {hasOverdraft ? (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4">
              <p className="font-semibold text-red-700 dark:text-red-300">
                Sobregiro proyectado el {formatDate(data.first_overdraft_date!)}
              </p>
              <p className="mt-1 text-sm text-red-700 dark:text-red-300">
                Con tus ingresos proyectados no alcanzarás a cubrir todos los pagos. Faltante
                acumulado en el horizonte: <strong>{formatMoney(data.total_shortfall, currency)}</strong>.
              </p>
            </div>
          ) : (
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4">
              <p className="font-semibold text-emerald-700 dark:text-emerald-300">
                Sin sobregiros en los próximos {horizon} meses
              </p>
              <p className="mt-1 text-sm text-emerald-700 dark:text-emerald-300">
                Saldo mínimo proyectado: {formatMoney(data.min_balance, currency)}
                {data.min_balance_date ? ` (${formatDate(data.min_balance_date)})` : ""}.
              </p>
            </div>
          )}

          {/* Saldo líquido proyectado */}
          <section className="card p-5">
            <h2 className="mb-3 text-base font-semibold tracking-tight">Saldo líquido proyectado</h2>
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="bal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
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
                  stroke="#10b981"
                  fill="url(#bal)"
                  name="Saldo"
                />
              </AreaChart>
            </ResponsiveContainer>
          </section>

          {/* Timeline de eventos */}
          <section className="card p-5">
            <h2 className="mb-3 text-base font-semibold tracking-tight">Línea de tiempo</h2>
            {data.events.length === 0 ? (
              <p className="text-sm text-ink-muted">
                Sin movimientos proyectados en el horizonte.
              </p>
            ) : (
              <ul className="divide-y divide-line">
                {data.events.map((ev, i) => {
                  const isIn = ev.direction === "in";
                  const balNeg = Number(ev.balance_after) < 0;
                  return (
                    <li
                      key={`${ev.kind}-${ev.date}-${i}`}
                      className="flex items-center justify-between gap-3 py-2 text-sm"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-muted text-ink-muted">
                          <Icon name={KIND_ICON[ev.kind]} className="size-3.5" />
                        </span>
                        <span className="min-w-0">
                          <span className="truncate">{ev.description}</span>
                          <span className="ml-2 text-xs text-ink-muted">
                            {KIND_LABEL[ev.kind]}
                            {ev.is_estimate ? " · estimado" : ""}
                          </span>
                          {!ev.covered && (
                            <span className="ml-2 rounded-full bg-red-500/15 px-2 py-0.5 text-xs text-red-700 dark:text-red-300">
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
                              : "text-ink-muted"
                          }`}
                        >
                          {formatMoney(ev.balance_after, currency)}
                        </span>
                        <span className="w-20 text-xs text-ink-muted">
                          {formatDate(ev.date)}
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
            {/* CXP-07: lo pendiente sin fecha no entra a la serie; se avisa aparte. */}
            {data.undated_commitments.length > 0 && (
              <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-900 dark:text-amber-200">
                <p className="font-medium">Pendientes con proveedores sin fecha (no están en la proyección):</p>
                <ul className="mt-1 space-y-0.5">
                  {data.undated_commitments.map((c, i) => (
                    <li key={`${c.description}-${i}`} className="flex justify-between gap-3">
                      <span>{c.description}</span>
                      <span className="tabular font-medium">{formatMoney(c.amount, currency)}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-1 text-xs">
                  Ponles fecha o calendario en <strong>Compromisos</strong> para incluirlos.
                </p>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
