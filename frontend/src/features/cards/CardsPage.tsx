// Tarjetas: alta (TDC-01), deuda en 3 números (TDC-09), statements (TDC-07/08)
// y pagos (TDC-10). Recordatorios visibles en la bandeja (REM-04).
import { useState, type FormEvent } from "react";
import {
  useCards,
  useCardStatements,
  useCloseCycles,
  useCreateCard,
  useNotifications,
  usePayCard,
  type CardOut,
  type StatementOut,
} from "../../api/cards";
import { usePaymentMethods } from "../../api/catalogs";
import { formatMoney } from "../../lib/money";

const STATUS_LABELS: Record<StatementOut["status"], string> = {
  open: "Abierto",
  closed: "Cerrado",
  paid: "Pagado",
  partially_paid: "Pago parcial",
};

function NewCardForm({ onDone }: { onDone: () => void }) {
  const create = useCreateCard();
  const [alias, setAlias] = useState("");
  const [bank, setBank] = useState("");
  const [network, setNetwork] = useState("Visa");
  const [last4, setLast4] = useState("");
  const [statementDay, setStatementDay] = useState("15");
  const [dueDays, setDueDays] = useState("20");
  const [limit, setLimit] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    create.mutate(
      {
        alias,
        bank,
        network,
        last4,
        statement_day: statementDay === "last" ? "last" : Number(statementDay),
        payment_due_days: Number(dueDays),
        credit_limit: limit || null,
      },
      { onSuccess: onDone },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="card grid grid-cols-2 gap-3 p-5 md:grid-cols-4">
      <div className="col-span-2 md:col-span-4">
        <h2 className="font-semibold">Nueva tarjeta</h2>
        <p className="text-xs text-ink-muted dark:text-slate-400">
          Solo guardamos alias, banco y últimos 4 dígitos — nunca el número completo.
        </p>
      </div>
      <div>
        <label className="label">Alias</label>
        <input className="input" required value={alias} onChange={(e) => setAlias(e.target.value)} />
      </div>
      <div>
        <label className="label">Banco</label>
        <input className="input" required value={bank} onChange={(e) => setBank(e.target.value)} />
      </div>
      <div>
        <label className="label">Red</label>
        <select className="input" value={network} onChange={(e) => setNetwork(e.target.value)}>
          <option>Visa</option>
          <option>Mastercard</option>
          <option>Amex</option>
        </select>
      </div>
      <div>
        <label className="label">Últimos 4</label>
        <input
          className="input"
          required
          pattern="\d{4}"
          maxLength={4}
          value={last4}
          onChange={(e) => setLast4(e.target.value)}
        />
      </div>
      <div>
        <label className="label">Día de corte</label>
        <select className="input" value={statementDay} onChange={(e) => setStatementDay(e.target.value)}>
          {Array.from({ length: 28 }, (_, i) => String(i + 1)).map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
          <option value="last">Último día del mes</option>
        </select>
      </div>
      <div>
        <label className="label">Días para pagar</label>
        <input
          className="input"
          type="number"
          min={1}
          max={30}
          required
          value={dueDays}
          onChange={(e) => setDueDays(e.target.value)}
        />
      </div>
      <div>
        <label className="label">Límite (opcional)</label>
        <input
          className="input"
          inputMode="decimal"
          pattern="^\d+(\.\d{1,2})?$"
          value={limit}
          onChange={(e) => setLimit(e.target.value)}
        />
      </div>
      <div className="flex items-end gap-2">
        <button className="btn-primary flex-1" disabled={create.isPending}>Guardar</button>
        <button type="button" className="btn-secondary" onClick={onDone}>Cancelar</button>
      </div>
      {create.error && (
        <p className="col-span-2 text-sm text-red-600 dark:text-red-400 md:col-span-4">
          {create.error.message}
        </p>
      )}
    </form>
  );
}

function PayForm({ card, statements }: { card: CardOut; statements: StatementOut[] }) {
  const pay = usePayCard();
  const methods = usePaymentMethods();
  const [amount, setAmount] = useState("");
  const [fromId, setFromId] = useState("");
  const payable = statements.filter((s) => s.status !== "paid");

  const [statementId, setStatementId] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const today = new Date();
    const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    pay.mutate(
      {
        cardId: card.id,
        amount,
        from_payment_method_id: fromId,
        date: iso,
        statement_id: statementId || null,
      },
      { onSuccess: () => setAmount("") },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 flex flex-wrap items-end gap-2">
      <div>
        <label className="label">Pagar</label>
        <input
          className="input w-28"
          inputMode="decimal"
          pattern="^\d+(\.\d{1,2})?$"
          placeholder="0.00"
          required
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </div>
      <div>
        <label className="label">Desde</label>
        <select className="input w-36" required value={fromId} onChange={(e) => setFromId(e.target.value)}>
          <option value="">Método…</option>
          {(methods.data ?? [])
            .filter((m) => m.type !== "credit_card")
            .map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
        </select>
      </div>
      <div>
        <label className="label">Statement</label>
        <select className="input w-44" value={statementId} onChange={(e) => setStatementId(e.target.value)}>
          <option value="">Más antiguo sin pagar</option>
          {payable.map((s) => (
            <option key={s.id} value={s.id}>
              Corte {s.period_end}
            </option>
          ))}
        </select>
      </div>
      <button className="btn-primary" disabled={pay.isPending}>Registrar pago</button>
      {pay.error && <p className="text-sm text-red-600 dark:text-red-400">{pay.error.message}</p>}
    </form>
  );
}

function CardDetail({ card }: { card: CardOut }) {
  const statements = useCardStatements(card.id);
  return (
    <div className="mt-4 border-t border-line pt-4 dark:border-slate-800">
      <h4 className="mb-2 text-sm font-medium">Statements</h4>
      <ul className="space-y-1 text-sm">
        {(statements.data ?? []).map((s) => (
          <li key={s.id} className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-ink-muted dark:text-slate-400">
              {s.period_start} → {s.period_end} · vence {s.due_date}
            </span>
            <span className="flex items-center gap-2">
              {formatMoney(s.computed_total, card.currency)}
              {s.paid_amount !== "0.00" && (
                <span className="text-xs text-emerald-600 dark:text-emerald-400">
                  pagado {formatMoney(s.paid_amount, card.currency)}
                </span>
              )}
              <span
                className={`rounded-full px-2 py-0.5 text-xs ${
                  s.is_overdue
                    ? "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300"
                    : s.status === "paid"
                      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                      : s.status === "open"
                        ? "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300"
                        : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200"
                }`}
              >
                {s.is_overdue ? "Vencido" : STATUS_LABELS[s.status]}
              </span>
            </span>
          </li>
        ))}
      </ul>
      <PayForm card={card} statements={statements.data ?? []} />
    </div>
  );
}

export default function CardsPage() {
  const cards = useCards();
  const notifications = useNotifications();
  const closeCycles = useCloseCycles();
  const [showForm, setShowForm] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const pendingNotifs = (notifications.data ?? []).filter((n) => n.status === "sent");

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Tarjetas de crédito</h1>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={() => closeCycles.mutate()}>
            Cerrar ciclos vencidos
          </button>
          <button className="btn-primary" onClick={() => setShowForm(true)}>
            + Nueva tarjeta
          </button>
        </div>
      </div>

      {pendingNotifs.length > 0 && (
        <section className="card p-4">
          <h2 className="mb-2 text-sm font-semibold">🔔 Recordatorios</h2>
          <ul className="space-y-1 text-sm text-ink-muted dark:text-slate-400">
            {pendingNotifs.slice(0, 5).map((n) => (
              <li key={n.id}>{n.message}</li>
            ))}
          </ul>
        </section>
      )}

      {showForm && <NewCardForm onDone={() => setShowForm(false)} />}

      {(cards.data ?? []).length === 0 && !showForm ? (
        <div className="card grid h-48 place-items-center p-8 text-center text-sm text-ink-muted dark:text-slate-400">
          Sin tarjetas aún. Da de alta la primera para registrar ciclos, MSI y pagos.
        </div>
      ) : (
        (cards.data ?? []).map((card) => (
          <section key={card.id} className="card p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold">
                  {card.alias}{" "}
                  <span className="text-sm font-normal text-ink-muted dark:text-slate-400">
                    {card.bank} · {card.network} ····{card.last4}
                  </span>
                </h3>
                <p className="text-xs text-ink-muted dark:text-slate-400">
                  Corte: {card.statement_day_is_last ? "último día" : `día ${card.statement_day}`}
                  {card.payment_due_days ? ` · ${card.payment_due_days} días para pagar` : ""}
                </p>
              </div>
              <button
                className="btn-secondary"
                onClick={() => setExpanded(expanded === card.id ? null : card.id)}
              >
                {expanded === card.id ? "Ocultar" : "Detalle"}
              </button>
            </div>

            {card.debt && (
              <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                {[
                  ["Saldo al corte", card.debt.statement_balance],
                  ["Ciclo en curso", card.debt.current_cycle_spend],
                  ["MSI por venir", card.debt.committed_msi],
                  ["Deuda total", card.debt.total_debt],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-lg bg-surface p-3 dark:bg-slate-800/50">
                    <p className="text-xs text-ink-muted dark:text-slate-400">{label}</p>
                    <p className="text-lg font-semibold">{formatMoney(value, card.currency)}</p>
                  </div>
                ))}
              </div>
            )}

            {expanded === card.id && <CardDetail card={card} />}
          </section>
        ))
      )}
    </div>
  );
}
