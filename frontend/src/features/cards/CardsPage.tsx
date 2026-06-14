// Tarjetas (TAR-01..05): crédito con ciclos/deuda (TDC) y débito/prepaid con
// saldo (TAR-05). Alta con selector de tipo (CAT-08) y campos condicionales.
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  useCards,
  useCardStatements,
  useCloseCycles,
  useCreateCard,
  useNotifications,
  usePayCard,
  useUpdateCard,
  type CardBody,
  type CardOut,
  type CardUpdateBody,
  type StatementOut,
} from "../../api/cards";
import { useCardTypes, usePaymentMethods } from "../../api/catalogs";
import { formatMoney } from "../../lib/money";

const STATUS_LABELS: Record<StatementOut["status"], string> = {
  open: "Abierto",
  closed: "Cerrado",
  paid: "Pagado",
  partially_paid: "Pago parcial",
};

function NewCardForm({ onDone }: { onDone: () => void }) {
  const create = useCreateCard();
  const cardTypes = useCardTypes();
  const types = cardTypes.data ?? [];
  const [cardTypeId, setCardTypeId] = useState("");
  const selected = types.find((t) => t.id === cardTypeId) ?? null;
  const behavior = selected?.behavior ?? null;
  const isCredit = behavior === "credit";

  const [alias, setAlias] = useState("");
  const [bank, setBank] = useState("");
  const [network, setNetwork] = useState("Visa");
  const [last4, setLast4] = useState("");
  const [statementDay, setStatementDay] = useState("15");
  const [dueDays, setDueDays] = useState("20");
  const [limit, setLimit] = useState("");
  const [openingBalance, setOpeningBalance] = useState("");
  const [initialBalance, setInitialBalance] = useState("");
  const [allowOverdraft, setAllowOverdraft] = useState(false);

  // Default to the first (credit) seeded type once loaded.
  useEffect(() => {
    if (!cardTypeId && types.length > 0) setCardTypeId(types[0].id);
  }, [types, cardTypeId]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const body: CardBody = { card_type_id: cardTypeId, alias, bank, network, last4 };
    if (isCredit) {
      // TDC-15: campos de ciclo opcionales (se pueden completar luego).
      if (statementDay) body.statement_day = statementDay === "last" ? "last" : Number(statementDay);
      if (dueDays) body.payment_due_days = Number(dueDays);
      if (limit) body.credit_limit = limit;
      if (openingBalance) body.opening_balance = openingBalance; // TDC-14
    } else {
      body.initial_balance = initialBalance || "0";
      body.allow_overdraft = allowOverdraft;
    }
    create.mutate(body, { onSuccess: onDone });
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
        <label className="label">Tipo</label>
        <select className="input" value={cardTypeId} onChange={(e) => setCardTypeId(e.target.value)}>
          {types.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
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
          <option>Otra</option>
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

      {isCredit ? (
        <>
          <div>
            <label className="label">Día de corte</label>
            <select
              className="input"
              value={statementDay}
              onChange={(e) => setStatementDay(e.target.value)}
            >
              <option value="">Sin definir aún</option>
              {Array.from({ length: 28 }, (_, i) => String(i + 1)).map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
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
              placeholder="opcional"
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
          <div>
            <label className="label">Pago pendiente (deuda del corte anterior)</label>
            <input
              className="input"
              inputMode="decimal"
              pattern="^\d+(\.\d{1,2})?$"
              placeholder="opcional"
              value={openingBalance}
              onChange={(e) => setOpeningBalance(e.target.value)}
            />
          </div>
        </>
      ) : (
        <>
          <div>
            <label className="label">Saldo inicial</label>
            <input
              className="input"
              inputMode="decimal"
              pattern="^\d+(\.\d{1,2})?$"
              placeholder="0.00"
              value={initialBalance}
              onChange={(e) => setInitialBalance(e.target.value)}
            />
          </div>
          <label className="flex items-end gap-2 pb-2 text-sm">
            <input
              type="checkbox"
              checked={allowOverdraft}
              onChange={(e) => setAllowOverdraft(e.target.checked)}
            />
            Permitir sobregiro
          </label>
        </>
      )}

      <div className="col-span-2 flex items-end gap-2 md:col-span-4">
        <button className="btn-primary flex-1" disabled={create.isPending || !cardTypeId}>
          Guardar
        </button>
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cancelar
        </button>
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

function EditCardForm({ card, onDone }: { card: CardOut; onDone: () => void }) {
  const update = useUpdateCard();
  const isCredit = card.behavior === "credit";
  const [alias, setAlias] = useState(card.alias);
  const [bank, setBank] = useState(card.bank);
  const [network, setNetwork] = useState(card.network);
  const [last4, setLast4] = useState(card.last4);
  const [statementDay, setStatementDay] = useState(
    card.statement_day_is_last ? "last" : card.statement_day != null ? String(card.statement_day) : "",
  );
  const [payMode, setPayMode] = useState<"due_days" | "payment_day">(
    card.payment_day != null || card.payment_day_is_last ? "payment_day" : "due_days",
  );
  const [dueDays, setDueDays] = useState(
    card.payment_due_days != null ? String(card.payment_due_days) : "",
  );
  const [payDay, setPayDay] = useState(
    card.payment_day_is_last ? "last" : card.payment_day != null ? String(card.payment_day) : "",
  );
  const [limit, setLimit] = useState(card.credit_limit ?? "");
  const [openingBalance, setOpeningBalance] = useState("");
  const [allowOverdraft, setAllowOverdraft] = useState(card.allow_overdraft);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const body: CardUpdateBody = { alias, bank, network, last4 };
    if (isCredit) {
      body.statement_day = statementDay
        ? statementDay === "last"
          ? "last"
          : Number(statementDay)
        : null;
      // Send both payment fields consistently so editing never leaves both set.
      if (payMode === "due_days") {
        body.payment_due_days = dueDays ? Number(dueDays) : null;
        body.payment_day = null;
      } else {
        body.payment_day = payDay ? (payDay === "last" ? "last" : Number(payDay)) : null;
        body.payment_due_days = null;
      }
      body.credit_limit = limit || null;
      if (openingBalance) body.opening_balance = openingBalance; // TDC-14
    } else {
      body.allow_overdraft = allowOverdraft;
    }
    update.mutate({ cardId: card.id, ...body }, { onSuccess: onDone });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mt-4 grid grid-cols-2 gap-3 border-t border-line pt-4 dark:border-slate-800 md:grid-cols-4"
    >
      <div className="col-span-2 md:col-span-4">
        <h4 className="text-sm font-medium">Editar tarjeta</h4>
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
          <option>Otra</option>
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

      {isCredit ? (
        <>
          <div>
            <label className="label">Día de corte</label>
            <select className="input" value={statementDay} onChange={(e) => setStatementDay(e.target.value)}>
              <option value="">Sin definir</option>
              {Array.from({ length: 28 }, (_, i) => String(i + 1)).map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
              <option value="last">Último día del mes</option>
            </select>
          </div>
          <div>
            <label className="label">Términos de pago</label>
            <select
              className="input"
              value={payMode}
              onChange={(e) => setPayMode(e.target.value as "due_days" | "payment_day")}
            >
              <option value="due_days">Días para pagar</option>
              <option value="payment_day">Día fijo de pago</option>
            </select>
          </div>
          {payMode === "due_days" ? (
            <div>
              <label className="label">Días para pagar</label>
              <input
                className="input"
                type="number"
                min={1}
                max={30}
                placeholder="opcional"
                value={dueDays}
                onChange={(e) => setDueDays(e.target.value)}
              />
            </div>
          ) : (
            <div>
              <label className="label">Día de pago</label>
              <select className="input" value={payDay} onChange={(e) => setPayDay(e.target.value)}>
                <option value="">Sin definir</option>
                {Array.from({ length: 28 }, (_, i) => String(i + 1)).map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
                <option value="last">Último día del mes</option>
              </select>
            </div>
          )}
          <div>
            <label className="label">Límite</label>
            <input
              className="input"
              inputMode="decimal"
              pattern="^\d+(\.\d{1,2})?$"
              placeholder="opcional"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
            />
          </div>
          <div className="col-span-2">
            <label className="label">Saldo pendiente del corte anterior</label>
            <input
              className="input"
              inputMode="decimal"
              pattern="^\d+(\.\d{1,2})?$"
              placeholder="déjalo vacío si no aplica"
              value={openingBalance}
              onChange={(e) => setOpeningBalance(e.target.value)}
            />
            <p className="mt-1 text-xs text-ink-muted dark:text-slate-400">
              Lo que ya debías del estado de cuenta anterior; se agrega como pago próximo.
            </p>
          </div>
        </>
      ) : (
        <label className="flex items-end gap-2 pb-2 text-sm">
          <input
            type="checkbox"
            checked={allowOverdraft}
            onChange={(e) => setAllowOverdraft(e.target.checked)}
          />
          Permitir sobregiro
        </label>
      )}

      <div className="col-span-2 flex items-end gap-2 md:col-span-4">
        <button className="btn-primary flex-1" disabled={update.isPending}>
          Guardar cambios
        </button>
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cancelar
        </button>
      </div>
      {update.error && (
        <p className="col-span-2 text-sm text-red-600 dark:text-red-400 md:col-span-4">
          {update.error.message}
        </p>
      )}
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
  const [editing, setEditing] = useState<string | null>(null);

  // Al entrar al módulo, cierra ciclos vencidos (TDC-07) para que "Saldo al
  // corte" y "Próximo pago" estén al día sin depender del job horario. Es
  // idempotente; se ignora el 403 de un viewer (no puede mutar, ESP-03).
  const autoClosed = useRef(false);
  useEffect(() => {
    if (autoClosed.current) return;
    autoClosed.current = true;
    closeCycles.mutate(undefined, { onError: () => {} });
  }, [closeCycles]);

  const pendingNotifs = (notifications.data ?? []).filter((n) => n.status === "sent");

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Tarjetas</h1>
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
          Sin tarjetas aún. Da de alta la primera: crédito, débito, vales o tarjeta de regalo.
        </div>
      ) : (
        (cards.data ?? []).map((card) => {
          const isCredit = card.behavior === "credit";
          return (
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
                    {isCredit
                      ? `Corte: ${card.statement_day_is_last ? "último día" : `día ${card.statement_day}`}${
                          card.payment_due_days ? ` · ${card.payment_due_days} días para pagar` : ""
                        }`
                      : card.behavior === "debit"
                        ? "Débito · saldo disponible"
                        : "Prepago · saldo disponible"}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    className="btn-secondary"
                    onClick={() => setEditing(editing === card.id ? null : card.id)}
                  >
                    {editing === card.id ? "Cerrar" : "Editar"}
                  </button>
                  {isCredit && (
                    <button
                      className="btn-secondary"
                      onClick={() => setExpanded(expanded === card.id ? null : card.id)}
                    >
                      {expanded === card.id ? "Ocultar" : "Detalle"}
                    </button>
                  )}
                </div>
              </div>

              {editing === card.id && (
                <EditCardForm card={card} onDone={() => setEditing(null)} />
              )}

              {isCredit && card.next_payment && (
                <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm dark:bg-amber-950/40">
                  <span className="text-amber-800 dark:text-amber-200">
                    Próximo pago · vence {card.next_payment.due_date}
                  </span>
                  <span className="font-semibold">
                    {formatMoney(card.next_payment.amount, card.currency)}
                  </span>
                </div>
              )}

              {isCredit && card.debt && (
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

              {!isCredit && card.balance !== null && (
                <div className="mt-4 rounded-lg bg-surface p-3 dark:bg-slate-800/50">
                  <p className="text-xs text-ink-muted dark:text-slate-400">Saldo actual</p>
                  <p className="text-2xl font-semibold">{formatMoney(card.balance, card.currency)}</p>
                </div>
              )}

              {isCredit && expanded === card.id && <CardDetail card={card} />}
            </section>
          );
        })
      )}
    </div>
  );
}
