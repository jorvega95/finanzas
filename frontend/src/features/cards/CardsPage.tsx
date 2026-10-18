// Tarjetas (TAR-01..05): crédito con ciclos/deuda (TDC) y débito/prepaid con
// saldo (TAR-05). Alta con selector de tipo (CAT-08) y campos condicionales.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  saveCardLayoutRequest,
  useCards,
  useCardStatements,
  useCloseCycles,
  useCreateCard,
  usePayCard,
  useSaveCardLayout,
  useUpdateCard,
  type CardBody,
  type CardOut,
  type CardUpdateBody,
  type StatementOut,
} from "../../api/cards";
import { useCardTypes, usePaymentMethods } from "../../api/catalogs";
import { formatMoney } from "../../lib/money";
import { formatDate } from "../../lib/dates";
import Icon from "../../components/ui/Icon";
import Modal from "../../components/ui/Modal";
import Spinner from "../../components/ui/Spinner";
import CardDesigner, { type CardDesign } from "./CardDesigner";
import CardVisual from "./CardVisual";

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
  const [design, setDesign] = useState<CardDesign>({ color: null, image: null }); // TAR-08

  // Default to the first (credit) seeded type once loaded.
  useEffect(() => {
    if (!cardTypeId && types.length > 0) setCardTypeId(types[0].id);
  }, [types, cardTypeId]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const body: CardBody = {
      card_type_id: cardTypeId,
      alias,
      bank,
      network,
      last4,
      color: design.color,
      image: design.image,
    };
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
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <p className="col-span-2 -mt-2 text-xs text-ink-muted md:col-span-4">
        Solo guardamos alias, banco y últimos 4 dígitos — nunca el número completo.
      </p>
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

      <fieldset className="col-span-2 mt-2 border-t border-line pt-4 md:col-span-4">
        <legend className="sr-only">Diseño</legend>
        <h3 className="mb-3 text-sm font-medium">Diseño de la tarjeta</h3>
        <CardDesigner value={design} onChange={setDesign} preview={{ alias, bank, network, last4 }} />
      </fieldset>

      <div className="col-span-2 mt-2 flex items-end justify-end gap-2 md:col-span-4">
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cancelar
        </button>
        <button className="btn-primary" disabled={create.isPending || !cardTypeId}>
          Guardar tarjeta
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
              Corte {formatDate(s.period_end)}
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
  // TDC-12: baja/reactivación lógica de la tarjeta (y su método vinculado, CAT-07).
  const [confirmingToggle, setConfirmingToggle] = useState(false);

  function toggleActive() {
    update.mutate(
      { cardId: card.id, is_active: !card.is_active },
      {
        onSuccess: () => {
          setConfirmingToggle(false);
          onDone();
        },
      },
    );
  }
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
  const [openingBalance, setOpeningBalance] = useState(card.opening_balance ?? "");
  const [initialBalance, setInitialBalance] = useState(card.initial_balance ?? "0");
  const [allowOverdraft, setAllowOverdraft] = useState(card.allow_overdraft);
  const [design, setDesign] = useState<CardDesign>({ color: card.color, image: card.image }); // TAR-08

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const body: CardUpdateBody = { alias, bank, network, last4 };
    // TAR-08: solo enviamos el diseño si cambió (la imagen puede pesar ~200 KB).
    if (design.color !== card.color) body.color = design.color;
    if (design.image !== card.image) body.image = design.image;
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
      body.initial_balance = initialBalance || "0";
      body.allow_overdraft = allowOverdraft;
    }
    update.mutate({ cardId: card.id, ...body }, { onSuccess: onDone });
  }

  return (
    <>
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
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
            <p className="mt-1 text-xs text-ink-muted">
              Lo que ya debías del estado de cuenta anterior; se agrega como pago próximo.
            </p>
          </div>
        </>
      ) : (
        <>
          <div className="col-span-2">
            <label className="label">Saldo inicial</label>
            <input
              className="input"
              inputMode="decimal"
              pattern="^\d+(\.\d{1,2})?$"
              placeholder="0.00"
              value={initialBalance}
              onChange={(e) => setInitialBalance(e.target.value)}
            />
            <p className="mt-1 text-xs text-ink-muted">
              Modificar el saldo inicial recalcula el saldo disponible actual.
            </p>
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

      <fieldset className="col-span-2 mt-2 border-t border-line pt-4 md:col-span-4">
        <legend className="sr-only">Diseño</legend>
        <h3 className="mb-3 text-sm font-medium">Diseño de la tarjeta</h3>
        <CardDesigner value={design} onChange={setDesign} preview={{ alias, bank, network, last4 }} />
      </fieldset>

      <div className="col-span-2 mt-2 flex items-end justify-end gap-2 md:col-span-4">
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cancelar
        </button>
        <button className="btn-primary" disabled={update.isPending}>
          Guardar cambios
        </button>
      </div>
      {update.error && (
        <p className="col-span-2 text-sm text-red-600 dark:text-red-400 md:col-span-4">
          {update.error.message}
        </p>
      )}

      {/* TDC-12: baja/reactivación lógica desde el propio formulario de edición. */}
      <div className="col-span-2 mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-4 md:col-span-4">
        <p className="text-xs text-ink-muted">
          {card.is_active
            ? "Desactivar impide nuevos cargos; podrás reactivarla luego."
            : "Esta tarjeta está desactivada."}
        </p>
        <button
          type="button"
          className={
            card.is_active
              ? "text-sm font-medium text-red-600 hover:underline dark:text-red-400"
              : "text-sm font-medium text-accent hover:underline"
          }
          onClick={() => setConfirmingToggle(true)}
        >
          {card.is_active ? "Desactivar tarjeta" : "Reactivar tarjeta"}
        </button>
      </div>
    </form>

    <Modal
      open={confirmingToggle}
      onClose={() => setConfirmingToggle(false)}
      title={card.is_active ? "Desactivar tarjeta" : "Reactivar tarjeta"}
    >
      <div className="space-y-4">
        <p className="text-sm">
          {card.is_active ? (
            <>
              Vas a desactivar <strong>{card.alias}</strong>. No podrás registrar nuevos{" "}
              {isCredit ? "cargos" : "movimientos"} con esta tarjeta ni con su método de pago
              vinculado.{" "}
              {isCredit
                ? "Sus ciclos seguirán cerrando hasta liquidar la deuda pendiente."
                : "Su saldo actual se conserva."}{" "}
              Podrás reactivarla cuando quieras.
            </>
          ) : (
            <>
              Vas a reactivar <strong>{card.alias}</strong>. Volverás a poder registrar{" "}
              {isCredit ? "cargos" : "movimientos"} con esta tarjeta y con su método de pago
              vinculado.
            </>
          )}
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setConfirmingToggle(false)}
          >
            Cancelar
          </button>
          <button
            type="button"
            className={
              card.is_active
                ? "btn-danger"
                : "btn-primary"
            }
            disabled={update.isPending}
            onClick={toggleActive}
          >
            {card.is_active ? "Desactivar" : "Reactivar"}
          </button>
        </div>
        {update.error && (
          <p className="text-sm text-red-600 dark:text-red-400">{update.error.message}</p>
        )}
      </div>
    </Modal>
    </>
  );
}

function CardDetail({ card }: { card: CardOut }) {
  const statements = useCardStatements(card.id);
  return (
    <div className="mt-4 border-t border-line pt-4">
      <h4 className="mb-2 text-sm font-medium">Statements</h4>
      <ul className="space-y-1 text-sm">
        {(statements.data ?? []).map((s) => (
          <li key={s.id} className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-ink-muted">
              {formatDate(s.period_start)} → {formatDate(s.period_end)} · vence {formatDate(s.due_date)}
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
                    ? "bg-red-500/15 text-red-700 dark:text-red-300"
                    : s.status === "paid"
                      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                      : s.status === "open"
                        ? "bg-sky-500/15 text-sky-700 dark:text-sky-300"
                        : "bg-amber-500/15 text-amber-800 dark:text-amber-200"
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

// TAR-07: a draggable row used only inside the reorder mode.
function SortableCardRow({ card }: { card: CardOut }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: card.id,
  });
  const style = { transform: CSS.Transform.toString(transform), transition };
  return (
    <li
      ref={setNodeRef}
      style={style}
      className={`card flex items-center gap-4 p-3 ${isDragging ? "z-10 ring-2 ring-accent" : ""}`}
    >
      <button
        type="button"
        className="cursor-grab touch-none rounded-md p-1 text-ink-subtle hover:bg-muted hover:text-ink"
        aria-label="Arrastrar para reordenar"
        {...attributes}
        {...listeners}
      >
        <Icon name="grip" />
      </button>
      <CardVisual {...card} inactive={!card.is_active} className="w-24 shrink-0" />
      <div className="min-w-0">
        <p className="truncate font-medium">{card.alias}</p>
        <p className="truncate text-xs text-ink-muted">
          {card.bank} · {card.network} ····{card.last4}
        </p>
      </div>
    </li>
  );
}

function Stat({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2.5">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className={`tabular mt-0.5 font-semibold ${strong ? "text-lg" : "text-base"}`}>{value}</p>
    </div>
  );
}

function cycleSummary(card: CardOut): string {
  if (card.behavior === "debit") return "Débito · saldo disponible";
  if (card.behavior === "prepaid") return "Prepago · saldo disponible";
  if (card.statement_day == null && !card.statement_day_is_last) return "Crédito · corte sin definir";
  const cut = card.statement_day_is_last ? "último día" : `día ${card.statement_day}`;
  const pay = card.payment_due_days
    ? ` · ${card.payment_due_days} días para pagar`
    : card.payment_day_is_last
      ? " · paga el último día"
      : card.payment_day
        ? ` · paga el día ${card.payment_day}`
        : "";
  return `Crédito · corte ${cut}${pay}`;
}

export default function CardsPage() {
  // TDC-07: al entrar, cierra ciclos vencidos en segundo plano para que
  // "Saldo al corte" y "Próximo pago" reflejen el estado actual sin depender del
  // job horario. No bloquea la carga de tarjetas (ver efecto abajo).
  const closeCycles = useCloseCycles();
  const autoClosed = useRef(false);
  useEffect(() => {
    if (autoClosed.current) return;
    autoClosed.current = true;
    // TDC-07: cierra ciclos vencidos al entrar. Fire-and-forget: useCloseCycles
    // invalida ["cards"] al terminar, así "Saldo al corte"/"Próximo pago" se
    // refrescan en cuanto cierra. NO bloqueamos la query de tarjetas en este
    // callback: gatearla en el resultado de una mutación puede dejarla
    // deshabilitada para siempre (spinner infinito) si el callback queda
    // huérfano (StrictMode/desmontaje). Las tarjetas cargan de inmediato.
    closeCycles.mutate();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [showInactive, setShowInactive] = useState(false);
  const cards = useCards(true, showInactive);
  const [showForm, setShowForm] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);

  const cardList = cards.data ?? [];
  const editingCard = cardList.find((c) => c.id === editing) ?? null;

  // TAR-07: reorder mode. Gated by a button; drag is active only inside it.
  const qc = useQueryClient();
  const saveLayout = useSaveCardLayout();
  const [reordering, setReordering] = useState(false);
  const [draftOrder, setDraftOrder] = useState<CardOut[]>([]);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  function startReorder() {
    setExpanded(null);
    setEditing(null);
    setDraftOrder(cardList);
    setReordering(true);
  }

  function handleDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (over && active.id !== over.id) {
      setDraftOrder((items) => {
        const from = items.findIndex((c) => c.id === active.id);
        const to = items.findIndex((c) => c.id === over.id);
        return arrayMove(items, from, to);
      });
    }
  }

  function saveReorder() {
    const ordered = draftOrder;
    setReordering(false);
    // Reflect the new order in the cache right away so the list updates on
    // return; the mutation's invalidation refetches in the background to confirm
    // (no need to wait on it visually).
    qc.setQueryData<CardOut[]>(["cards", { includeInactive: showInactive }], ordered);
    saveLayout.mutate(ordered.map((c) => c.id));
  }

  function cancelReorder() {
    setReordering(false);
    setDraftOrder([]);
  }

  // Auto-save on leaving the module with unsaved order (TAR-07). A ref holds the
  // latest state so the unmount cleanup can fire a raw request even though the
  // component (and its mutation hook) is gone.
  const autoSaveRef = useRef<{ active: boolean; ids: string[]; baseline: string[] }>({
    active: false,
    ids: [],
    baseline: [],
  });
  autoSaveRef.current = {
    active: reordering,
    ids: draftOrder.map((c) => c.id),
    baseline: cardList.map((c) => c.id),
  };
  useEffect(() => {
    return () => {
      const { active, ids, baseline } = autoSaveRef.current;
      if (active && ids.length > 0 && JSON.stringify(ids) !== JSON.stringify(baseline)) {
        void saveCardLayoutRequest(ids)
          .then(() => qc.invalidateQueries({ queryKey: ["cards"] }))
          .catch(() => {});
      }
    };
  }, [qc]);

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="page-title">Tarjetas</h1>
          <p className="page-subtitle">Crédito, débito, vales y tarjetas de regalo.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="mr-1 flex items-center gap-1.5 text-sm text-ink-muted">
            <input
              type="checkbox"
              checked={showInactive}
              disabled={reordering}
              onChange={(e) => setShowInactive(e.target.checked)}
            />
            Mostrar inactivas
          </label>
          {!reordering && cardList.length > 1 && (
            <button className="btn-secondary" onClick={startReorder}>
              <Icon name="arrowUpDown" />
              Ordenar
            </button>
          )}
          {!reordering && (
            <>
              <button
                className="btn-secondary"
                onClick={() => closeCycles.mutate()}
                title="Cerrar ciclos vencidos"
              >
                <Icon name="refresh" />
                <span className="hidden sm:inline">Cerrar ciclos</span>
              </button>
              <button className="btn-primary" onClick={() => setShowForm(true)}>
                <Icon name="plus" />
                Nueva tarjeta
              </button>
            </>
          )}
        </div>
      </div>

      {/* Los recordatorios viven en la campana del header (REM-04, OPP-01). */}

      <Modal open={showForm} onClose={() => setShowForm(false)} title="Nueva tarjeta" size="xl">
        {showForm && <NewCardForm onDone={() => setShowForm(false)} />}
      </Modal>

      {editingCard && (
        <Modal open onClose={() => setEditing(null)} title={`Editar ${editingCard.alias}`} size="xl">
          <EditCardForm card={editingCard} onDone={() => setEditing(null)} />
        </Modal>
      )}

      {reordering ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-ink-muted">
              Arrastra para reordenar. Este orden es solo tuyo; si sales sin guardar, también se
              conserva.
            </p>
            <div className="flex gap-2">
              <button className="btn-secondary" onClick={cancelReorder}>
                Cancelar
              </button>
              <button
                className="btn-primary"
                disabled={saveLayout.isPending}
                onClick={saveReorder}
              >
                Guardar orden
              </button>
            </div>
          </div>
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={draftOrder.map((c) => c.id)}
              strategy={verticalListSortingStrategy}
            >
              <ul className="space-y-2">
                {draftOrder.map((card) => (
                  <SortableCardRow key={card.id} card={card} />
                ))}
              </ul>
            </SortableContext>
          </DndContext>
        </div>
      ) : cards.isPending ? (
        <div className="card flex h-48 flex-col items-center justify-center gap-3 p-8 text-center text-sm text-ink-muted">
          <Spinner className="size-7" />
          Cargando tus tarjetas…
        </div>
      ) : cards.isError ? (
        <div className="card flex h-48 flex-col items-center justify-center gap-3 p-8 text-center text-sm text-ink-muted">
          No se pudieron cargar tus tarjetas.
          <button className="btn-secondary" onClick={() => cards.refetch()}>
            Reintentar
          </button>
        </div>
      ) : cardList.length === 0 ? (
        <button
          type="button"
          onClick={() => setShowForm(true)}
          className="grid h-56 w-full place-items-center rounded-xl border border-dashed border-line-strong text-sm text-ink-muted transition hover:bg-card hover:text-ink"
        >
          <span className="flex flex-col items-center gap-2">
            <Icon name="plus" className="size-5" />
            Da de alta tu primera tarjeta
          </span>
        </button>
      ) : (
        <div className="space-y-4">
          {cardList.map((card) => {
            const isCredit = card.behavior === "credit";
            // Solo proporción visual de la barra (no aritmética de dinero, GLO-01).
            const usage =
              isCredit && card.debt && card.credit_limit && Number(card.credit_limit) > 0
                ? Math.min(100, (Number(card.debt.total_debt) / Number(card.credit_limit)) * 100)
                : null;
            return (
              <section
                key={card.id}
                className={`card p-4 sm:p-5 ${card.is_active ? "" : "opacity-70"}`}
              >
                <div className="flex flex-col gap-5 sm:flex-row">
                  <div className="w-full shrink-0 sm:w-72">
                    <CardVisual {...card} inactive={!card.is_active} />
                  </div>

                  <div className="flex min-w-0 flex-1 flex-col gap-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="truncate text-lg font-semibold tracking-tight">
                          {card.alias}
                        </h3>
                        <p className="text-sm text-ink-muted">{cycleSummary(card)}</p>
                      </div>
                      <div className="flex gap-1.5">
                        <button className="btn-secondary" onClick={() => setEditing(card.id)}>
                          <Icon name="pencil" className="size-3.5" />
                          Editar
                        </button>
                        {isCredit && (
                          <button
                            className="btn-secondary"
                            aria-expanded={expanded === card.id}
                            onClick={() => setExpanded(expanded === card.id ? null : card.id)}
                          >
                            {expanded === card.id ? "Ocultar" : "Detalle"}
                            <Icon
                              name="chevronDown"
                              className={`size-3.5 transition ${expanded === card.id ? "rotate-180" : ""}`}
                            />
                          </button>
                        )}
                      </div>
                    </div>

                    {isCredit && card.next_payment && (
                      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm">
                        <span className="text-amber-900 dark:text-amber-200">
                          Próximo pago · vence {formatDate(card.next_payment.due_date)}
                        </span>
                        <span className="tabular font-semibold">
                          {formatMoney(card.next_payment.amount, card.currency)}
                        </span>
                      </div>
                    )}

                    {isCredit && card.debt && (
                      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                        <Stat label="Saldo al corte" value={formatMoney(card.debt.statement_balance, card.currency)} />
                        <Stat label="Ciclo en curso" value={formatMoney(card.debt.current_cycle_spend, card.currency)} />
                        <Stat label="MSI por venir" value={formatMoney(card.debt.committed_msi, card.currency)} />
                        <Stat label="Deuda total" value={formatMoney(card.debt.total_debt, card.currency)} strong />
                      </div>
                    )}

                    {usage !== null && card.credit_limit && (
                      <div>
                        <div className="mb-1 flex justify-between text-xs text-ink-muted">
                          <span>Uso de la línea</span>
                          <span className="tabular">
                            {usage.toFixed(0)}% de {formatMoney(card.credit_limit, card.currency)}
                          </span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                          <div
                            className={`h-full rounded-full ${
                              usage > 80 ? "bg-red-500" : usage > 50 ? "bg-amber-500" : "bg-accent"
                            }`}
                            style={{ width: `${usage}%` }}
                          />
                        </div>
                      </div>
                    )}

                    {!isCredit && card.balance !== null && (
                      <div className="rounded-lg border border-line bg-surface px-4 py-3">
                        <p className="text-xs text-ink-muted">Saldo actual</p>
                        <p className="tabular text-2xl font-semibold tracking-tight">
                          {formatMoney(card.balance, card.currency)}
                        </p>
                      </div>
                    )}
                  </div>
                </div>

                {isCredit && expanded === card.id && <CardDetail card={card} />}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
