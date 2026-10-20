// Inversiones (R5/R15): portafolio con P&L, movimientos (INV-02), precios
// manuales (INV-04), snapshots (INV-05) y patrimonio neto (PAT-01/02).
import { useState, type FormEvent } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  useCreateInvestmentAccount,
  useInvestmentAccounts,
  useNetWorth,
  usePortfolio,
  usePortfolioSnapshots,
  useRegisterMovement,
  useSetManualPrice,
  useTakeSnapshots,
} from "../../api/investments";
import { formatMoney } from "../../lib/money";
import { formatDate } from "../../lib/dates";
import { useChartTheme } from "../../lib/chartTheme";
import { useSpace } from "../spaces/SpaceProvider";

const KIND_LABELS: Record<string, string> = {
  crypto: "Crypto",
  stocks: "Acciones",
  fixed_income: "Renta fija",
  other: "Otro",
};

function MovementForm() {
  const accounts = useInvestmentAccounts();
  const register = useRegisterMovement();
  const [accountId, setAccountId] = useState("");
  const [type, setType] = useState("buy");
  const [symbol, setSymbol] = useState("");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [currency, setCurrency] = useState("USD");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const today = new Date();
    const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    register.mutate(
      {
        accountId,
        type,
        asset_symbol: symbol.trim().toLowerCase(),
        quantity,
        price: price || null,
        currency,
        date: iso,
      },
      { onSuccess: () => { setQuantity(""); setPrice(""); } },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 items-end gap-3 md:grid-cols-3 xl:grid-cols-7">
      <div>
        <label className="label">Cuenta</label>
        <select className="input" required value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">Cuenta…</option>
          {(accounts.data ?? []).map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
      </div>
      <div>
        <label className="label">Operación</label>
        <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="buy">Compra</option>
          <option value="sell">Venta</option>
          <option value="deposit">Depósito</option>
          <option value="withdraw">Retiro</option>
        </select>
      </div>
      <div>
        <label className="label">Activo</label>
        <input
          className="input"
          placeholder="bitcoin"
          title="Crypto: id de CoinGecko (bitcoin, ethereum…). Otros: tu ticker."
          required
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
        />
      </div>
      <div>
        <label className="label">Cantidad</label>
        <input
          className="input"
          inputMode="decimal"
          pattern="^\d+(\.\d{1,10})?$"
          required
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
        />
      </div>
      <div>
        <label className="label">Precio unitario</label>
        <input
          className="input"
          inputMode="decimal"
          pattern="^\d+(\.\d{1,8})?$"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
        />
      </div>
      <div>
        <label className="label">Moneda</label>
        <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
          <option>USD</option>
          <option>MXN</option>
        </select>
      </div>
      <button className="btn-primary w-full" disabled={register.isPending}>Registrar</button>
      {register.error && (
        <p className="col-span-full text-sm text-red-600 dark:text-red-400">{register.error.message}</p>
      )}
    </form>
  );
}

export default function InvestmentsPage() {
  const { activeSpace } = useSpace();
  const portfolio = usePortfolio();
  const snapshots = usePortfolioSnapshots();
  const netWorth = useNetWorth();
  const createAccount = useCreateInvestmentAccount();
  const takeSnapshots = useTakeSnapshots();
  const setManualPrice = useSetManualPrice();
  const [accountName, setAccountName] = useState("");
  const [accountKind, setAccountKind] = useState("crypto");

  const currency = activeSpace.base_currency;
  const chart = useChartTheme();
  const data = portfolio.data;
  const lastNetWorth = (netWorth.data ?? []).at(-1);

  return (
    <div className="page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Inversiones</h1>
        <button className="btn-secondary" onClick={() => takeSnapshots.mutate()}>
          Tomar snapshot de hoy
        </button>
      </div>

      {/* Totales (INV-06) */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          ["Valor del portafolio", data?.total_value],
          ["P&L no realizado", data?.total_unrealized_pnl],
          ["P&L realizado", data?.total_realized_pnl],
          ["Patrimonio neto", lastNetWorth?.net_worth],
        ].map(([label, value]) => (
          <div key={label as string} className="card p-4">
            <p className="text-xs text-ink-muted">{label}</p>
            <p
              className={`text-lg font-semibold ${
                value && Number(value) < 0 ? "text-red-600 dark:text-red-400" : ""
              }`}
            >
              {value !== undefined && value !== null ? formatMoney(value, currency) : "—"}
            </p>
          </div>
        ))}
      </div>
      <p className="text-xs text-ink-muted">
        Patrimonio = inversiones + saldos de cuentas (efectivo, débito, billeteras, ahorro) −
        deuda de tarjetas. Los saldos en dólares se valúan al tipo de cambio del día, así que
        es un aproximado.
      </p>

      {/* Cuentas + movimientos */}
      <section className="card space-y-5 p-5">
        <h2 className="text-base font-semibold tracking-tight">Cuentas de inversión y movimientos</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createAccount.mutate(
              { name: accountName, kind: accountKind },
              { onSuccess: () => setAccountName("") },
            );
          }}
          className="grid grid-cols-2 items-end gap-3 md:grid-cols-3 xl:grid-cols-7"
        >
          <div className="col-span-2 md:col-span-1 xl:col-span-2">
            <label className="label" htmlFor="inv-account-name">Nueva cuenta</label>
            <input
              id="inv-account-name"
              className="input"
              placeholder="Binance, GBM…"
              required
              value={accountName}
              onChange={(e) => setAccountName(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="inv-account-kind">Tipo</label>
            <select
              id="inv-account-kind"
              className="input"
              value={accountKind}
              onChange={(e) => setAccountKind(e.target.value)}
            >
              {Object.entries(KIND_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
          <button className="btn-secondary w-full" disabled={createAccount.isPending}>
            Crear cuenta
          </button>
        </form>
        <div className="border-t border-line pt-5">
          <MovementForm />
        </div>
      </section>

      {/* Holdings (INV-06) */}
      <section className="card p-5">
        <h2 className="mb-3 text-base font-semibold tracking-tight">Portafolio</h2>
        {(data?.holdings ?? []).length === 0 ? (
          <p className="text-sm text-ink-muted">
            Sin posiciones. Registra tu primera compra arriba.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="tabular w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs font-medium uppercase tracking-wide text-ink-subtle">
                  <th className="py-1 pr-3">Activo</th>
                  <th className="py-1 pr-3">Cuenta</th>
                  <th className="py-1 pr-3">Cantidad</th>
                  <th className="py-1 pr-3">Costo prom.</th>
                  <th className="py-1 pr-3">Precio</th>
                  <th className="py-1 pr-3">Valor</th>
                  <th className="py-1 pr-3">P&L no real.</th>
                  <th className="py-1">P&L real.</th>
                </tr>
              </thead>
              <tbody>
                {(data?.holdings ?? []).map((h) => (
                  <tr key={h.holding_id} className="border-t border-line">
                    <td className="py-2 pr-3 font-medium">{h.asset_name}</td>
                    <td className="py-2 pr-3 text-ink-muted">
                      {h.account_name}
                    </td>
                    <td className="py-2 pr-3">{h.quantity}</td>
                    <td className="py-2 pr-3">{h.avg_cost} {h.currency}</td>
                    <td className="py-2 pr-3">
                      {h.price ?? "—"}
                      {h.price_source === "manual" && (
                        <span className="ml-1 text-xs text-ink-muted" title="Precio capturado manualmente">✎</span>
                      )}
                    </td>
                    <td className="py-2 pr-3 font-medium">
                      {h.value_base ? formatMoney(h.value_base, currency) : "—"}
                    </td>
                    <td
                      className={`py-2 pr-3 ${
                        h.unrealized_pnl && Number(h.unrealized_pnl) < 0
                          ? "text-red-600 dark:text-red-400"
                          : "text-emerald-600 dark:text-emerald-400"
                      }`}
                    >
                      {h.unrealized_pnl ? formatMoney(h.unrealized_pnl, currency) : "—"}
                    </td>
                    <td className="py-2">{formatMoney(h.realized_pnl, currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {/* INV-04: precio manual rápido */}
        <form
          className="mt-4 flex flex-wrap items-end gap-2 border-t border-line pt-4"
          onSubmit={(e) => {
            e.preventDefault();
            const form = e.target as HTMLFormElement;
            const fd = new FormData(form);
            setManualPrice.mutate({
              symbol: String(fd.get("symbol")),
              price: String(fd.get("price")),
              currency: String(fd.get("currency")),
            });
            form.reset();
          }}
        >
          <span className="text-xs text-ink-muted">
            Precio manual (CETES, fondos, acciones):
          </span>
          <input name="symbol" className="input w-32" placeholder="símbolo" required />
          <input
            name="price"
            className="input w-28"
            placeholder="precio"
            inputMode="decimal"
            pattern="^\d+(\.\d{1,8})?$"
            required
          />
          <select name="currency" className="input w-24" defaultValue="MXN">
            <option>MXN</option>
            <option>USD</option>
          </select>
          <button className="btn-secondary">Actualizar</button>
        </form>
      </section>

      {/* Historia (INV-05 + PAT-01) */}
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card p-5">
          <h2 className="mb-3 text-base font-semibold tracking-tight">Evolución del portafolio</h2>
          {(snapshots.data ?? []).length < 2 ? (
            <p className="text-sm text-ink-muted">
              Los snapshots diarios van dibujando esta gráfica.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={(snapshots.data ?? []).map((s) => ({ ...s, value: Number(s.total_value) }))}>
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
                  cursor={chart.cursorLine}
                  {...chart.tooltip}
                />
                <Line type="monotone" dataKey="value" name="Valor" stroke="#10b981" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </section>
        <section className="card p-5">
          <h2 className="mb-3 text-base font-semibold tracking-tight">Patrimonio neto</h2>
          {(netWorth.data ?? []).length < 2 ? (
            <p className="text-sm text-ink-muted">
              {lastNetWorth
                ? `Hoy: ${formatMoney(lastNetWorth.net_worth, currency)} (activos ${formatMoney(lastNetWorth.assets, currency)} − deuda ${formatMoney(lastNetWorth.liabilities, currency)})`
                : "Toma el primer snapshot para empezar la historia."}
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={(netWorth.data ?? []).map((s) => ({ ...s, value: Number(s.net_worth) }))}>
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
                  cursor={chart.cursorLine}
                  {...chart.tooltip}
                />
                <Line type="monotone" dataKey="value" name="Patrimonio" stroke="#6366f1" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </section>
      </div>
    </div>
  );
}
