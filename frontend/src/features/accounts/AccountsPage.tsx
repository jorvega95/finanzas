// Cuentas (TAR-01..11): tarjetas de crédito con ciclos/deuda (TDC), cuentas con
// saldo (débito, billeteras, vales, ahorro), efectivo con saldo ajustable
// (TAR-09) y préstamos personales (TAR-11). Alta con selector de tipo (CAT-08)
// y campos condicionales.
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
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
  hasBalance,
  isLoan,
  isPlastic,
  saveAccountLayoutRequest,
  DEFAULT_GROUP_ORDER,
  useAccountLayout,
  useAccounts,
  useAdjustCashBalance,
  useCloseCycles,
  useCreateAccount,
  useDeleteAccount,
  usePayCard,
  useSaveAccountLayout,
  useStatements,
  useUpdateAccount,
  type AccountBehavior,
  type AccountBody,
  type AccountGroupKey,
  type AccountOut,
  type AccountUpdateBody,
  type StatementOut,
} from "../../api/accounts";
import { useAccountTypes } from "../../api/catalogs";
import { formatMoney, isNegativeAmount, isPositiveAmount, subtractMoney, sumMoney } from "../../lib/money";
import { formatDate } from "../../lib/dates";
import Icon from "../../components/ui/Icon";
import Modal from "../../components/ui/Modal";
import Spinner from "../../components/ui/Spinner";
import AccountDesigner, { type AccountDesign } from "./AccountDesigner";
import AccountVisual, { defaultColorFor } from "./AccountVisual";

const STATUS_LABELS: Record<StatementOut["status"], string> = {
  open: "Abierto",
  closed: "Cerrado",
  paid: "Pagado",
  partially_paid: "Pago parcial",
};

const BEHAVIOR_LABELS: Record<AccountBehavior, string> = {
  cash: "Efectivo",
  debit: "Cuenta / billetera",
  prepaid: "Prepago / vales",
  savings: "Ahorro",
  credit: "Tarjeta de crédito",
  loan: "Préstamo personal",
};

// Secciones de la página (TAR-07): fijas por behavior; su orden y el de las
// cuentas dentro de cada una son preferencia de cada usuario.
type AccountGroup = {
  key: AccountGroupKey;
  title: string;
  hint: string;
  behaviors: AccountBehavior[];
};
const GROUPS: AccountGroup[] = [
  {
    key: "cash",
    title: "Efectivo y cuentas",
    hint: "Efectivo, débito, billeteras digitales y vales.",
    behaviors: ["cash", "debit", "prepaid"],
  },
  {
    key: "savings",
    title: "Ahorro",
    hint: "Dinero apartado; no cuenta como disponible.",
    behaviors: ["savings"],
  },
  {
    key: "credit",
    title: "Tarjetas de crédito",
    hint: "Ciclos de corte, pagos y deuda.",
    behaviors: ["credit"],
  },
  {
    key: "loan",
    title: "Préstamos",
    hint: "Dinero que debes a alguien o que te deben; no cuenta como disponible.",
    behaviors: ["loan"],
  },
];

const GROUP_BY_KEY = new Map(GROUPS.map((g) => [g.key, g]));

function groupKeyOf(behavior: AccountBehavior | null): AccountGroupKey | null {
  return GROUPS.find((g) => behavior && g.behaviors.includes(behavior))?.key ?? null;
}

const CURRENCIES = ["MXN", "USD"];

function MoneyInput({
  value,
  onChange,
  placeholder = "0.00",
  required = false,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <input
      className="input"
      inputMode="decimal"
      pattern="^\d+(\.\d{1,2})?$"
      placeholder={placeholder}
      required={required}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

// TAR-02: banco, red y últimos 4 son opcionales; solo aplican a tarjetas.
function PlasticFields({
  bank,
  setBank,
  network,
  setNetwork,
  last4,
  setLast4,
}: {
  bank: string;
  setBank: (v: string) => void;
  network: string;
  setNetwork: (v: string) => void;
  last4: string;
  setLast4: (v: string) => void;
}) {
  return (
    <>
      <div>
        <label className="label">Banco (opcional)</label>
        <input className="input" value={bank} onChange={(e) => setBank(e.target.value)} />
      </div>
      <div>
        <label className="label">Red</label>
        <select className="input" value={network} onChange={(e) => setNetwork(e.target.value)}>
          <option value="">Sin tarjeta</option>
          <option>Visa</option>
          <option>Mastercard</option>
          <option>Amex</option>
          <option>Otra</option>
        </select>
      </div>
      <div>
        <label className="label">Últimos 4 (opcional)</label>
        <input
          className="input"
          pattern="\d{4}"
          maxLength={4}
          value={last4}
          onChange={(e) => setLast4(e.target.value)}
        />
      </div>
    </>
  );
}

// TAR-11: el saldo de un préstamo se captura como monto positivo + dirección y
// se guarda con signo (negativo = debes, positivo = te deben).
type LoanDirection = "owe" | "owed";

function splitLoanBalance(balance: string | null): { direction: LoanDirection; amount: string } {
  const value = balance ?? "0";
  return isNegativeAmount(value)
    ? { direction: "owe", amount: subtractMoney("0", value) }
    : { direction: "owed", amount: isPositiveAmount(value) ? value : "" };
}

function signedLoanBalance(direction: LoanDirection, amount: string): string {
  if (!amount) return "0";
  return direction === "owe" ? subtractMoney("0", amount) : amount;
}

function LoanBalanceFields({
  direction,
  setDirection,
  amount,
  setAmount,
}: {
  direction: LoanDirection;
  setDirection: (v: LoanDirection) => void;
  amount: string;
  setAmount: (v: string) => void;
}) {
  return (
    <>
      <div>
        <label className="label">¿Quién debe?</label>
        <select
          className="input"
          value={direction}
          onChange={(e) => setDirection(e.target.value as LoanDirection)}
        >
          <option value="owe">Yo debo</option>
          <option value="owed">Me deben</option>
        </select>
      </div>
      <div>
        <label className="label">Monto pendiente hoy</label>
        <MoneyInput value={amount} onChange={setAmount} placeholder="0.00" />
      </div>
      <p className="col-span-2 self-end text-xs text-ink-muted md:col-span-2">
        Si te van a prestar después, déjalo en 0 y registra una transferencia desde el préstamo
        cuando recibas el dinero.
      </p>
    </>
  );
}

function NewAccountForm({
  initialBehavior,
  onDone,
}: {
  initialBehavior: AccountBehavior | null;
  onDone: () => void;
}) {
  const create = useCreateAccount();
  const accountTypes = useAccountTypes();
  const types = accountTypes.data ?? [];
  const [typeId, setTypeId] = useState("");
  const selected = types.find((t) => t.id === typeId) ?? null;
  const behavior = selected?.behavior ?? null;
  const isCredit = behavior === "credit";

  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("MXN");
  const [bank, setBank] = useState("");
  const [network, setNetwork] = useState("");
  const [last4, setLast4] = useState("");
  const [statementDay, setStatementDay] = useState("15");
  const [dueDays, setDueDays] = useState("20");
  const [limit, setLimit] = useState("");
  const [openingBalance, setOpeningBalance] = useState("");
  const [initialBalance, setInitialBalance] = useState("");
  const [allowOverdraft, setAllowOverdraft] = useState(false);
  const [loanDirection, setLoanDirection] = useState<LoanDirection>("owe"); // TAR-11
  const [design, setDesign] = useState<AccountDesign>({ color: null, image: null }); // TAR-08

  // Tipo inicial: el de la sección desde la que se abrió; si no, débito.
  useEffect(() => {
    if (typeId || types.length === 0) return;
    const wanted = initialBehavior ?? "debit";
    const preferred = types.find((t) => t.behavior === wanted);
    setTypeId((preferred ?? types[0]).id);
  }, [types, typeId, initialBehavior]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const body: AccountBody = {
      account_type_id: typeId,
      name,
      currency,
      color: design.color,
      image: design.image,
    };
    if (isPlastic(behavior)) {
      body.bank = bank || null;
      body.network = network || null;
      body.last4 = last4 || null;
    }
    if (isCredit) {
      // TDC-15: campos de ciclo opcionales (se pueden completar luego).
      if (statementDay) body.statement_day = statementDay === "last" ? "last" : Number(statementDay);
      if (dueDays) body.payment_due_days = Number(dueDays);
      if (limit) body.credit_limit = limit;
      if (openingBalance) body.opening_balance = openingBalance; // TDC-14
    } else if (isLoan(behavior)) {
      // TAR-11: sobregiro siempre permitido; el saldo lleva signo.
      body.initial_balance = signedLoanBalance(loanDirection, initialBalance);
    } else {
      body.initial_balance = initialBalance || "0";
      if (behavior !== "cash") body.allow_overdraft = allowOverdraft; // TAR-09: cash siempre
    }
    create.mutate(body, { onSuccess: onDone });
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div>
        <label className="label">Tipo</label>
        <select className="input" value={typeId} onChange={(e) => setTypeId(e.target.value)}>
          {(["cash", "debit", "prepaid", "savings", "credit", "loan"] as AccountBehavior[]).map((b) => {
            const group = types.filter((t) => t.behavior === b);
            if (group.length === 0) return null;
            return (
              <optgroup key={b} label={BEHAVIOR_LABELS[b]}>
                {group.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </optgroup>
            );
          })}
        </select>
      </div>
      <div className="col-span-2 md:col-span-2">
        <label className="label">Nombre</label>
        <input
          className="input"
          required
          placeholder={
            isCredit
              ? "BBVA Azul"
              : behavior === "cash"
                ? "Efectivo"
                : isLoan(behavior)
                  ? "Préstamo papás"
                  : "XTRM, Mercado Pago…"
          }
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div>
        <label className="label">Moneda</label>
        <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
          {CURRENCIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </div>

      {isPlastic(behavior) && (
        <>
          <p className="col-span-2 -mb-1 text-xs text-ink-muted md:col-span-4">
            Solo guardamos banco y últimos 4 dígitos — nunca el número completo.
          </p>
          <PlasticFields
            bank={bank}
            setBank={setBank}
            network={network}
            setNetwork={setNetwork}
            last4={last4}
            setLast4={setLast4}
          />
        </>
      )}

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
            <MoneyInput value={limit} onChange={setLimit} placeholder="" />
          </div>
          <div>
            <label className="label">Pago pendiente (deuda del corte anterior)</label>
            <MoneyInput value={openingBalance} onChange={setOpeningBalance} placeholder="opcional" />
          </div>
        </>
      ) : isLoan(behavior) ? (
        <LoanBalanceFields
          direction={loanDirection}
          setDirection={setLoanDirection}
          amount={initialBalance}
          setAmount={setInitialBalance}
        />
      ) : (
        <>
          <div className="col-span-2">
            <label className="label">
              {behavior === "cash" ? "¿Cuánto efectivo tienes hoy?" : "Saldo inicial"}
            </label>
            <MoneyInput value={initialBalance} onChange={setInitialBalance} />
          </div>
          {behavior !== "cash" && (
            <label className="flex items-end gap-2 pb-2 text-sm">
              <input
                type="checkbox"
                checked={allowOverdraft}
                onChange={(e) => setAllowOverdraft(e.target.checked)}
              />
              Permitir sobregiro
            </label>
          )}
        </>
      )}

      <fieldset className="col-span-2 mt-2 border-t border-line pt-4 md:col-span-4">
        <legend className="sr-only">Diseño</legend>
        <h3 className="mb-3 text-sm font-medium">Diseño</h3>
        <AccountDesigner
          value={design}
          onChange={setDesign}
          preview={{ name, bank, network, last4, currency, behavior }}
        />
      </fieldset>

      <div className="col-span-2 mt-2 flex items-end justify-end gap-2 md:col-span-4">
        <button type="button" className="btn-secondary" onClick={onDone}>
          Cancelar
        </button>
        <button className="btn-primary" disabled={create.isPending || !typeId}>
          Guardar cuenta
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

function PayForm({
  card,
  statements,
  sources,
}: {
  card: AccountOut;
  statements: StatementOut[];
  sources: AccountOut[];
}) {
  const pay = usePayCard();
  const [amount, setAmount] = useState("");
  const [fromId, setFromId] = useState("");
  const [statementId, setStatementId] = useState("");
  const payable = statements.filter((s) => s.status !== "paid");
  // TAR-10: el pago sale en la moneda de la tarjeta; entre monedas se usa una
  // transferencia con monto recibido (TXN-13) desde Transacciones.
  const sameCurrency = sources.filter((a) => a.currency === card.currency);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const today = new Date();
    const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    pay.mutate(
      {
        accountId: card.id,
        amount,
        from_account_id: fromId,
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
        <select className="input w-40" required value={fromId} onChange={(e) => setFromId(e.target.value)}>
          <option value="">Cuenta…</option>
          {sameCurrency.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
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
      <button className="btn-primary" disabled={pay.isPending}>
        Registrar pago
      </button>
      {pay.error && <p className="text-sm text-red-600 dark:text-red-400">{pay.error.message}</p>}
    </form>
  );
}

function EditAccountForm({ account, onDone }: { account: AccountOut; onDone: () => void }) {
  const update = useUpdateAccount();
  const remove = useDeleteAccount();
  const behavior = account.behavior;
  const isCredit = behavior === "credit";
  // TDC-12: baja/reactivación lógica; GLO-03: borrado físico solo sin movimientos.
  const [confirming, setConfirming] = useState<"toggle" | "delete" | null>(null);

  function toggleActive() {
    update.mutate(
      { accountId: account.id, is_active: !account.is_active },
      {
        onSuccess: () => {
          setConfirming(null);
          onDone();
        },
      },
    );
  }

  function deleteAccount() {
    remove.mutate(account.id, {
      onSuccess: () => {
        setConfirming(null);
        onDone();
      },
    });
  }

  const [name, setName] = useState(account.name);
  const [currency, setCurrency] = useState(account.currency);
  const [bank, setBank] = useState(account.bank ?? "");
  const [network, setNetwork] = useState(account.network ?? "");
  const [last4, setLast4] = useState(account.last4 ?? "");
  const [statementDay, setStatementDay] = useState(
    account.statement_day_is_last
      ? "last"
      : account.statement_day != null
        ? String(account.statement_day)
        : "",
  );
  const [payMode, setPayMode] = useState<"due_days" | "payment_day">(
    account.payment_day != null || account.payment_day_is_last ? "payment_day" : "due_days",
  );
  const [dueDays, setDueDays] = useState(
    account.payment_due_days != null ? String(account.payment_due_days) : "",
  );
  const [payDay, setPayDay] = useState(
    account.payment_day_is_last ? "last" : account.payment_day != null ? String(account.payment_day) : "",
  );
  const [limit, setLimit] = useState(account.credit_limit ?? "");
  const [openingBalance, setOpeningBalance] = useState(account.opening_balance ?? "");
  const [initialBalance, setInitialBalance] = useState(account.initial_balance ?? "0");
  const [allowOverdraft, setAllowOverdraft] = useState(account.allow_overdraft);
  // TAR-11: el saldo inicial del préstamo se edita como monto + dirección.
  const initialLoan = splitLoanBalance(account.initial_balance);
  const [loanDirection, setLoanDirection] = useState<LoanDirection>(initialLoan.direction);
  const [loanAmount, setLoanAmount] = useState(initialLoan.amount);
  const [design, setDesign] = useState<AccountDesign>({ color: account.color, image: account.image });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const body: AccountUpdateBody = { name };
    if (currency !== account.currency) body.currency = currency; // TAR-10: 409 si ya tiene movimientos
    if (isPlastic(behavior)) {
      body.bank = bank || null;
      body.network = network || null;
      body.last4 = last4 || null;
    }
    // TAR-08: solo enviamos el diseño si cambió (la imagen puede pesar ~200 KB).
    if (design.color !== account.color) body.color = design.color;
    if (design.image !== account.image) body.image = design.image;
    if (isCredit) {
      body.statement_day = statementDay ? (statementDay === "last" ? "last" : Number(statementDay)) : null;
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
    } else if (isLoan(behavior)) {
      body.initial_balance = signedLoanBalance(loanDirection, loanAmount); // TAR-11
    } else if (behavior !== "cash") {
      // TAR-09: el efectivo se ajusta con "Ajustar saldo", no con el saldo inicial.
      body.initial_balance = initialBalance || "0";
      body.allow_overdraft = allowOverdraft;
    }
    update.mutate({ accountId: account.id, ...body }, { onSuccess: onDone });
  }

  const noun = isCredit ? "tarjeta" : "cuenta";

  return (
    <>
      <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="col-span-2 md:col-span-3">
          <label className="label">Nombre</label>
          <input className="input" required value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label className="label">Moneda</label>
          <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {CURRENCIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>

        {isPlastic(behavior) && (
          <PlasticFields
            bank={bank}
            setBank={setBank}
            network={network}
            setNetwork={setNetwork}
            last4={last4}
            setLast4={setLast4}
          />
        )}

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
              <MoneyInput value={limit} onChange={setLimit} placeholder="opcional" />
            </div>
            <div className="col-span-2">
              <label className="label">Saldo pendiente del corte anterior</label>
              <MoneyInput
                value={openingBalance}
                onChange={setOpeningBalance}
                placeholder="déjalo vacío si no aplica"
              />
              <p className="mt-1 text-xs text-ink-muted">
                Lo que ya debías del estado de cuenta anterior; se agrega como pago próximo.
              </p>
            </div>
          </>
        ) : behavior === "cash" ? (
          <p className="col-span-2 self-end text-xs text-ink-muted md:col-span-4">
            El saldo del efectivo se corrige con <strong>Ajustar saldo</strong> en la lista de
            cuentas. Puede quedar en negativo si registras más gastos de los que tenías.
          </p>
        ) : isLoan(behavior) ? (
          <>
            <LoanBalanceFields
              direction={loanDirection}
              setDirection={setLoanDirection}
              amount={loanAmount}
              setAmount={setLoanAmount}
            />
            <p className="col-span-2 -mt-1 text-xs text-ink-muted md:col-span-4">
              Es lo que se debía al empezar a registrar el préstamo; préstamos nuevos, abonos y
              condonaciones se registran como movimientos.
            </p>
          </>
        ) : (
          <>
            <div className="col-span-2">
              <label className="label">Saldo inicial</label>
              <MoneyInput value={initialBalance} onChange={setInitialBalance} />
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
          <h3 className="mb-3 text-sm font-medium">Diseño</h3>
          <AccountDesigner
            value={design}
            onChange={setDesign}
            preview={{ name, bank, network, last4, currency, behavior }}
          />
        </fieldset>

        <div className="col-span-2 mt-2 flex items-end justify-end gap-2 md:col-span-4">
          <button type="button" className="btn-secondary" onClick={onDone}>
            Cancelar
          </button>
          <button className="btn-primary" disabled={update.isPending}>
            Guardar cambios
          </button>
        </div>
        {update.error && !confirming && (
          <p className="col-span-2 text-sm text-red-600 dark:text-red-400 md:col-span-4">
            {update.error.message}
          </p>
        )}

        <div className="col-span-2 mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-4 md:col-span-4">
          <p className="text-xs text-ink-muted">
            {account.is_active
              ? `Desactivar impide nuevos movimientos; podrás reactivarla luego.`
              : `Esta ${noun} está desactivada.`}
          </p>
          <div className="flex gap-3">
            <button
              type="button"
              className="text-sm font-medium text-ink-muted hover:text-red-600 hover:underline dark:hover:text-red-400"
              onClick={() => setConfirming("delete")}
            >
              Eliminar
            </button>
            <button
              type="button"
              className={
                account.is_active
                  ? "text-sm font-medium text-red-600 hover:underline dark:text-red-400"
                  : "text-sm font-medium text-accent hover:underline"
              }
              onClick={() => setConfirming("toggle")}
            >
              {account.is_active ? `Desactivar ${noun}` : `Reactivar ${noun}`}
            </button>
          </div>
        </div>
      </form>

      <Modal
        open={confirming === "toggle"}
        onClose={() => setConfirming(null)}
        title={account.is_active ? `Desactivar ${noun}` : `Reactivar ${noun}`}
      >
        <div className="space-y-4">
          <p className="text-sm">
            {account.is_active ? (
              <>
                Vas a desactivar <strong>{account.name}</strong>. No podrás registrar nuevos{" "}
                {isCredit ? "cargos" : "movimientos"} en ella.{" "}
                {isCredit
                  ? "Sus ciclos seguirán cerrando hasta liquidar la deuda pendiente."
                  : "Su saldo actual se conserva."}{" "}
                Podrás reactivarla cuando quieras.
              </>
            ) : (
              <>
                Vas a reactivar <strong>{account.name}</strong>. Volverás a poder registrar{" "}
                {isCredit ? "cargos" : "movimientos"} en ella.
              </>
            )}
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => setConfirming(null)}>
              Cancelar
            </button>
            <button
              type="button"
              className={account.is_active ? "btn-danger" : "btn-primary"}
              disabled={update.isPending}
              onClick={toggleActive}
            >
              {account.is_active ? "Desactivar" : "Reactivar"}
            </button>
          </div>
          {update.error && (
            <p className="text-sm text-red-600 dark:text-red-400">{update.error.message}</p>
          )}
        </div>
      </Modal>

      <Modal open={confirming === "delete"} onClose={() => setConfirming(null)} title={`Eliminar ${noun}`}>
        <div className="space-y-4">
          <p className="text-sm">
            Vas a eliminar <strong>{account.name}</strong> de forma permanente. Solo es posible si
            nunca tuvo movimientos; si ya los tiene, desactívala en su lugar.
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => setConfirming(null)}>
              Cancelar
            </button>
            <button
              type="button"
              className="btn-danger"
              disabled={remove.isPending}
              onClick={deleteAccount}
            >
              Eliminar
            </button>
          </div>
          {remove.error && (
            <p className="text-sm text-red-600 dark:text-red-400">{remove.error.message}</p>
          )}
        </div>
      </Modal>
    </>
  );
}

// TAR-09: "mi efectivo real es $X". Sin transacciones: solo se corrige el saldo.
function AdjustCashModal({ account, onClose }: { account: AccountOut; onClose: () => void }) {
  const adjust = useAdjustCashBalance();
  const [balance, setBalance] = useState("");

  function submit(value: string) {
    adjust.mutate({ accountId: account.id, balance: value }, { onSuccess: onClose });
  }

  return (
    <Modal open onClose={onClose} title={`Ajustar ${account.name}`}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          submit(balance);
        }}
      >
        <p className="text-sm text-ink-muted">
          Saldo calculado:{" "}
          <strong className={isNegativeAmount(account.balance ?? "0") ? "text-red-600 dark:text-red-400" : "text-ink"}>
            {formatMoney(account.balance ?? "0", account.currency)}
          </strong>
          . Si no cuadra con lo que traes (perdiste dinero u olvidaste registrar algo), captura el
          monto real. No se crea ningún gasto ni ingreso.
        </p>
        <div>
          <label className="label">¿Cuánto efectivo tienes ahora?</label>
          <MoneyInput value={balance} onChange={setBalance} required />
        </div>
        <div className="flex flex-wrap justify-between gap-2">
          <button
            type="button"
            className="btn-secondary"
            disabled={adjust.isPending}
            onClick={() => submit("0")}
          >
            Poner en $0
          </button>
          <div className="flex gap-2">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancelar
            </button>
            <button className="btn-primary" disabled={adjust.isPending}>
              Guardar saldo
            </button>
          </div>
        </div>
        {adjust.error && <p className="text-sm text-red-600 dark:text-red-400">{adjust.error.message}</p>}
      </form>
    </Modal>
  );
}

function StatementsDetail({ card, sources }: { card: AccountOut; sources: AccountOut[] }) {
  const statements = useStatements(card.id);
  return (
    <div className="mt-4 border-t border-line pt-4">
      <h4 className="mb-2 text-sm font-medium">Statements</h4>
      <ul className="divide-y divide-line text-sm">
        {(statements.data ?? []).map((s) => (
          <li key={s.id} className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 py-1.5">
            <span className="text-xs text-ink-muted sm:text-sm">
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
      <PayForm card={card} statements={statements.data ?? []} sources={sources} />
    </div>
  );
}

// TAR-07: lo que se muestra a la derecha de una fila compacta del modo ordenar.
function compactAmount(account: AccountOut): string | null {
  if (account.behavior === "credit") {
    return account.debt ? `debe ${formatMoney(account.debt.total_debt, account.currency)}` : null;
  }
  return account.balance !== null ? formatMoney(account.balance, account.currency) : null;
}

// TAR-07: fila compacta y arrastrable, solo dentro de su sección.
function SortableAccountRow({ account }: { account: AccountOut }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: account.id,
  });
  // Solo traslación: Transform incluye el scale con que dnd-kit iguala alturas
  // distintas, y estiraba la fila/sección al pasar sobre otra más grande.
  const style = { transform: CSS.Translate.toString(transform), transition };
  const color = account.color ?? defaultColorFor(account.behavior, account.last4);
  const amount = compactAmount(account);
  return (
    <li
      ref={setNodeRef}
      style={style}
      className={`flex items-center gap-2.5 rounded-lg border border-line bg-surface px-2 py-1.5 ${
        isDragging ? "relative z-10 shadow-lg ring-2 ring-accent" : ""
      } ${account.is_active ? "" : "opacity-60"}`}
    >
      <button
        type="button"
        className="cursor-grab touch-none rounded p-1 text-ink-subtle hover:bg-muted hover:text-ink"
        aria-label={`Arrastrar ${account.name}`}
        {...attributes}
        {...listeners}
      >
        <Icon name="grip" className="size-3.5" />
      </button>
      <span
        aria-hidden
        className="size-3 shrink-0 rounded-full ring-1 ring-black/10 dark:ring-white/15"
        style={{ backgroundColor: color }}
      />
      <span className="min-w-0 flex-1 truncate text-sm font-medium">{account.name}</span>
      {account.last4 && <span className="hidden text-xs text-ink-subtle sm:inline">····{account.last4}</span>}
      {amount && <span className="tabular shrink-0 text-xs text-ink-muted">{amount}</span>}
    </li>
  );
}

// TAR-07: sección arrastrable (desde su encabezado) con sus cuentas, que se
// reordenan en su propio contexto: una cuenta no puede cambiar de sección.
function SortableGroup({
  group,
  items,
  sensors,
  onReorder,
}: {
  group: AccountGroup;
  items: AccountOut[];
  sensors: ReturnType<typeof useSensors>;
  onReorder: (items: AccountOut[]) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: `group:${group.key}`,
  });
  // Solo traslación: Transform incluye el scale con que dnd-kit iguala alturas
  // distintas, y estiraba la fila/sección al pasar sobre otra más grande.
  const style = { transform: CSS.Translate.toString(transform), transition };

  function handleDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const from = items.findIndex((a) => a.id === active.id);
    const to = items.findIndex((a) => a.id === over.id);
    if (from >= 0 && to >= 0) onReorder(arrayMove(items, from, to));
  }

  return (
    <li
      ref={setNodeRef}
      style={style}
      className={`card p-3 ${isDragging ? "relative z-20 shadow-xl ring-2 ring-accent" : ""}`}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="cursor-grab touch-none rounded-md p-1 text-ink-subtle hover:bg-muted hover:text-ink"
          aria-label={`Arrastrar la sección ${group.title}`}
          {...attributes}
          {...listeners}
        >
          <Icon name="grip" />
        </button>
        <h3 className="text-sm font-semibold tracking-tight">{group.title}</h3>
        <span className="text-xs text-ink-muted">
          {items.length} {items.length === 1 ? "cuenta" : "cuentas"}
        </span>
      </div>
      {items.length > 0 ? (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={items.map((a) => a.id)} strategy={verticalListSortingStrategy}>
            <ul className="mt-2 space-y-1 pl-8">
              {items.map((account) => (
                <SortableAccountRow key={account.id} account={account} />
              ))}
            </ul>
          </SortableContext>
        </DndContext>
      ) : (
        <p className="mt-1 pl-9 text-xs text-ink-subtle">Sin cuentas en esta sección.</p>
      )}
    </li>
  );
}

// TAR-11: saldo del préstamo en lenguaje de deuda.
function LoanBalance({ account }: { account: AccountOut }) {
  const balance = account.balance ?? "0";
  const owe = isNegativeAmount(balance);
  const owed = isPositiveAmount(balance);
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-xs text-ink-muted">{owe ? "Debes" : owed ? "Te deben" : "Préstamo"}</p>
      <p
        className={`tabular text-2xl font-semibold tracking-tight ${
          owe ? "text-amber-700 dark:text-amber-300" : owed ? "text-emerald-700 dark:text-emerald-300" : ""
        }`}
      >
        {owe || owed ? formatMoney(owe ? subtractMoney("0", balance) : balance, account.currency) : "Saldado"}
      </p>
      <p className="mt-1 text-xs text-ink-muted">
        Recibir lo prestado o abonar: transferencia. Si te lo pagan directo a un tercero: gasto con
        esta cuenta. Si te perdonan una parte: ingreso «Regalos recibidos».
      </p>
    </div>
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

function accountSummary(account: AccountOut): string {
  const plastic = [account.bank, account.last4 ? `····${account.last4}` : null]
    .filter(Boolean)
    .join(" ");
  if (account.behavior !== "credit") {
    const label = account.behavior ? BEHAVIOR_LABELS[account.behavior] : "Cuenta";
    return [label, account.currency, plastic].filter(Boolean).join(" · ");
  }
  if (account.statement_day == null && !account.statement_day_is_last) return "Crédito · corte sin definir";
  const cut = account.statement_day_is_last ? "último día" : `día ${account.statement_day}`;
  const pay = account.payment_due_days
    ? ` · ${account.payment_due_days} días para pagar`
    : account.payment_day_is_last
      ? " · paga el último día"
      : account.payment_day
        ? ` · paga el día ${account.payment_day}`
        : "";
  return `Crédito · corte ${cut}${pay}`;
}

/** Σ por moneda (GLO-01: suma exacta con BigInt, nunca float). */
function totalsByCurrency(items: { currency: string; amount: string | null }[]): [string, string][] {
  const groups = new Map<string, string[]>();
  for (const { currency, amount } of items) {
    if (amount == null) continue;
    groups.set(currency, [...(groups.get(currency) ?? []), amount]);
  }
  return [...groups.entries()].map(([currency, amounts]) => [currency, sumMoney(amounts)]);
}

function AccountItem({
  account,
  expanded,
  onToggleExpand,
  onEdit,
  onAdjust,
  sources,
}: {
  account: AccountOut;
  expanded: boolean;
  onToggleExpand: () => void;
  onEdit: () => void;
  onAdjust: () => void;
  sources: AccountOut[];
}) {
  const isCredit = account.behavior === "credit";
  const isCash = account.behavior === "cash";
  const negative = account.balance !== null && isNegativeAmount(account.balance);
  // Solo proporción visual de la barra (no aritmética de dinero, GLO-01).
  const usage =
    isCredit && account.debt && account.credit_limit && Number(account.credit_limit) > 0
      ? Math.min(100, (Number(account.debt.total_debt) / Number(account.credit_limit)) * 100)
      : null;

  return (
    <section
      className={`card @container p-4 ${expanded ? "col-span-full" : ""} ${account.is_active ? "" : "opacity-70"}`}
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-start gap-4">
          <div className="w-32 shrink-0 @md:w-40">
            <AccountVisual {...account} inactive={!account.is_active} />
          </div>
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <div className="min-w-0">
              <h3 className="truncate text-base font-semibold tracking-tight">{account.name}</h3>
              <p className="text-xs text-ink-muted">{accountSummary(account)}</p>
            </div>
            <div className="flex flex-wrap gap-1.5 [&>button]:h-8 [&>button]:px-2.5 @md:[&>button]:h-9 @md:[&>button]:px-3.5">
              {isCash && (
                <button className="btn-secondary" onClick={onAdjust}>
                  Ajustar saldo
                </button>
              )}
              <button className="btn-secondary" onClick={onEdit}>
                <Icon name="pencil" className="size-3.5" />
                Editar
              </button>
              {isCredit && (
                <button className="btn-secondary" aria-expanded={expanded} onClick={onToggleExpand}>
                  {expanded ? "Ocultar" : "Detalle"}
                  <Icon name="chevronDown" className={`size-3.5 transition ${expanded ? "rotate-180" : ""}`} />
                </button>
              )}
            </div>
          </div>
        </div>

        {isCredit && account.next_payment && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm">
            <span className="text-amber-900 dark:text-amber-200">
              Próximo pago · vence {formatDate(account.next_payment.due_date)}
            </span>
            <span className="tabular font-semibold">
              {formatMoney(account.next_payment.amount, account.currency)}
            </span>
          </div>
        )}

        {isCredit && account.debt && (
          <div className="grid grid-cols-2 gap-2 @xl:grid-cols-4">
            <Stat label="Saldo al corte" value={formatMoney(account.debt.statement_balance, account.currency)} />
            <Stat label="Ciclo en curso" value={formatMoney(account.debt.current_cycle_spend, account.currency)} />
            <Stat label="MSI por venir" value={formatMoney(account.debt.committed_msi, account.currency)} />
            <Stat label="Deuda total" value={formatMoney(account.debt.total_debt, account.currency)} strong />
          </div>
        )}

        {usage !== null && account.credit_limit && (
          <div>
            <div className="mb-1 flex justify-between text-xs text-ink-muted">
              <span>Uso de la línea</span>
              <span className="tabular">
                {usage.toFixed(0)}% de {formatMoney(account.credit_limit, account.currency)}
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

        {isLoan(account.behavior) && account.balance !== null && <LoanBalance account={account} />}

        {hasBalance(account.behavior) && !isLoan(account.behavior) && account.balance !== null && (
          <div className="rounded-lg border border-line bg-surface px-4 py-3">
            <p className="text-xs text-ink-muted">Saldo actual</p>
            <p
              className={`tabular text-2xl font-semibold tracking-tight ${
                negative ? "text-red-600 dark:text-red-400" : ""
              }`}
            >
              {formatMoney(account.balance, account.currency)}
            </p>
          </div>
        )}

        {/* TAR-09: el efectivo puede quedar negativo; se sugiere ajustarlo. */}
        {isCash && negative && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-200">
            <span className="flex items-center gap-2">
              <Icon name="alert" />
              Registraste más gastos en efectivo de los que tenías.
            </span>
            <button className="font-medium underline-offset-2 hover:underline" onClick={onAdjust}>
              Ajustar saldo
            </button>
          </div>
        )}
      </div>

      {isCredit && expanded && <StatementsDetail card={account} sources={sources} />}
    </section>
  );
}

export default function AccountsPage() {
  // TDC-07: al entrar, cierra ciclos vencidos en segundo plano para que
  // "Saldo al corte" y "Próximo pago" reflejen el estado actual sin depender del
  // job horario. Fire-and-forget: useCloseCycles invalida ["accounts"] al
  // terminar. NO bloqueamos la query en este callback: gatearla en el resultado
  // de una mutación puede dejarla deshabilitada para siempre (spinner infinito)
  // si el callback queda huérfano (StrictMode/desmontaje).
  const closeCycles = useCloseCycles();
  const autoClosed = useRef(false);
  useEffect(() => {
    if (autoClosed.current) return;
    autoClosed.current = true;
    closeCycles.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [showInactive, setShowInactive] = useState(false);
  const accounts = useAccounts(true, showInactive);
  const [creating, setCreating] = useState<{ behavior: AccountBehavior | null } | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [adjusting, setAdjusting] = useState<string | null>(null);

  const list = useMemo(() => accounts.data ?? [], [accounts.data]);
  const editingAccount = list.find((a) => a.id === editing) ?? null;
  const adjustingAccount = list.find((a) => a.id === adjusting) ?? null;
  // Cuentas desde las que se puede pagar una tarjeta (TDC-10).
  const paySources = list.filter((a) => a.is_active && hasBalance(a.behavior));

  const balances = totalsByCurrency(
    list
      .filter((a) => hasBalance(a.behavior) && !isLoan(a.behavior))
      .map((a) => ({ currency: a.currency, amount: a.balance })),
  );
  // TAR-11: lo que debes en préstamos (solo saldos negativos, en positivo).
  const loanDebts = totalsByCurrency(
    list
      .filter((a) => isLoan(a.behavior) && a.balance !== null && isNegativeAmount(a.balance))
      .map((a) => ({ currency: a.currency, amount: subtractMoney("0", a.balance ?? "0") })),
  );
  const debts = totalsByCurrency(
    list
      .filter((a) => a.behavior === "credit")
      .map((a) => ({ currency: a.currency, amount: a.debt?.total_debt ?? null })),
  );

  // TAR-07: reorder mode. Gated by a button; drag is active only inside it.
  // Sections and the accounts inside each one are ordered independently.
  const qc = useQueryClient();
  const layout = useAccountLayout();
  const groupOrder = layout.data?.group_order ?? DEFAULT_GROUP_ORDER;
  const orderedGroups = groupOrder
    .map((key) => GROUP_BY_KEY.get(key))
    .filter((g): g is AccountGroup => g !== undefined);
  const saveLayout = useSaveAccountLayout();
  const [reordering, setReordering] = useState(false);
  const [draftGroups, setDraftGroups] = useState<AccountGroupKey[]>([]);
  const [draftItems, setDraftItems] = useState<Record<AccountGroupKey, AccountOut[]>>({
    cash: [],
    savings: [],
    credit: [],
    loan: [],
  });
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  function groupItems(source: AccountOut[]): Record<AccountGroupKey, AccountOut[]> {
    const items: Record<AccountGroupKey, AccountOut[]> = { cash: [], savings: [], credit: [], loan: [] };
    for (const account of source) {
      const key = groupKeyOf(account.behavior);
      if (key) items[key].push(account);
    }
    return items;
  }

  function startReorder() {
    setExpanded(null);
    setEditing(null);
    setDraftGroups(groupOrder);
    setDraftItems(groupItems(list));
    setReordering(true);
  }

  function handleGroupDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    setDraftGroups((groups) => {
      const from = groups.indexOf(String(active.id).replace("group:", "") as AccountGroupKey);
      const to = groups.indexOf(String(over.id).replace("group:", "") as AccountGroupKey);
      return from >= 0 && to >= 0 ? arrayMove(groups, from, to) : groups;
    });
  }

  function draftAccountIds(groups: AccountGroupKey[], items: Record<AccountGroupKey, AccountOut[]>) {
    return groups.flatMap((key) => items[key].map((a) => a.id));
  }

  function saveReorder() {
    const groups = draftGroups;
    const ordered = groups.flatMap((key) => draftItems[key]);
    setReordering(false);
    // Reflect the new order in the cache right away; the mutation's
    // invalidation refetches in the background to confirm.
    qc.setQueryData<AccountOut[]>(["accounts", { includeInactive: showInactive }], ordered);
    qc.setQueryData(["accounts", "layout"], {
      account_ids: ordered.map((a) => a.id),
      group_order: groups,
    });
    saveLayout.mutate({ accountIds: ordered.map((a) => a.id), groupOrder: groups });
  }

  function cancelReorder() {
    setReordering(false);
  }

  // Auto-save on leaving the module with unsaved order (TAR-07). A ref holds the
  // latest state so the unmount cleanup can fire a raw request even though the
  // component (and its mutation hook) is gone.
  const autoSaveRef = useRef<{
    active: boolean;
    ids: string[];
    groups: AccountGroupKey[];
    baseline: string;
  }>({ active: false, ids: [], groups: [], baseline: "" });
  autoSaveRef.current = {
    active: reordering,
    ids: draftAccountIds(draftGroups, draftItems),
    groups: draftGroups,
    baseline: JSON.stringify([list.map((a) => a.id), groupOrder]),
  };
  useEffect(() => {
    return () => {
      const { active, ids, groups, baseline } = autoSaveRef.current;
      if (active && groups.length > 0 && JSON.stringify([ids, groups]) !== baseline) {
        void saveAccountLayoutRequest(ids, groups)
          .then(() => qc.invalidateQueries({ queryKey: ["accounts"] }))
          .catch(() => {});
      }
    };
  }, [qc]);

  return (
    <div className="page">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="page-title">Cuentas</h1>
          <p className="page-subtitle">Efectivo, débito, billeteras, ahorro, tarjetas de crédito y préstamos.</p>
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
          {!reordering && list.length > 1 && (
            <button className="btn-secondary" onClick={startReorder}>
              <Icon name="arrowUpDown" />
              Ordenar
            </button>
          )}
          {!reordering && (
            <>
              <button className="btn-secondary" onClick={() => closeCycles.mutate()} title="Cerrar ciclos vencidos">
                <Icon name="refresh" />
                <span className="hidden sm:inline">Cerrar ciclos</span>
              </button>
              <button className="btn-primary" onClick={() => setCreating({ behavior: null })}>
                <Icon name="plus" />
                Nueva cuenta
              </button>
            </>
          )}
        </div>
      </div>

      {!reordering && list.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {balances.map(([currency, total]) => (
            <Stat key={`b-${currency}`} label={`Saldo en cuentas · ${currency}`} value={formatMoney(total, currency)} strong />
          ))}
          {debts.map(([currency, total]) => (
            <Stat key={`d-${currency}`} label={`Deuda de tarjetas · ${currency}`} value={formatMoney(total, currency)} strong />
          ))}
          {loanDebts.map(([currency, total]) => (
            <Stat key={`l-${currency}`} label={`Debes en préstamos · ${currency}`} value={formatMoney(total, currency)} strong />
          ))}
        </div>
      )}

      {/* Los recordatorios viven en la campana del header (REM-04, OPP-01). */}

      <Modal open={creating !== null} onClose={() => setCreating(null)} title="Nueva cuenta" size="xl">
        {creating && <NewAccountForm initialBehavior={creating.behavior} onDone={() => setCreating(null)} />}
      </Modal>

      {editingAccount && (
        <Modal open onClose={() => setEditing(null)} title={`Editar ${editingAccount.name}`} size="xl">
          <EditAccountForm account={editingAccount} onDone={() => setEditing(null)} />
        </Modal>
      )}

      {adjustingAccount && <AdjustCashModal account={adjustingAccount} onClose={() => setAdjusting(null)} />}

      {reordering ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-ink-muted">
              Arrastra las secciones desde su encabezado y las cuentas dentro de cada una. Este
              orden es solo tuyo; si sales sin guardar, también se conserva.
            </p>
            <div className="flex gap-2">
              <button className="btn-secondary" onClick={cancelReorder}>
                Cancelar
              </button>
              <button className="btn-primary" disabled={saveLayout.isPending} onClick={saveReorder}>
                Guardar orden
              </button>
            </div>
          </div>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleGroupDragEnd}>
            <SortableContext
              items={draftGroups.map((key) => `group:${key}`)}
              strategy={verticalListSortingStrategy}
            >
              <ul className="space-y-2">
                {draftGroups.map((key) => {
                  const group = GROUP_BY_KEY.get(key);
                  if (!group) return null;
                  return (
                    <SortableGroup
                      key={key}
                      group={group}
                      items={draftItems[key]}
                      sensors={sensors}
                      onReorder={(items) => setDraftItems((all) => ({ ...all, [key]: items }))}
                    />
                  );
                })}
              </ul>
            </SortableContext>
          </DndContext>
        </div>
      ) : accounts.isPending ? (
        <div className="card flex h-48 flex-col items-center justify-center gap-3 p-8 text-center text-sm text-ink-muted">
          <Spinner className="size-7" />
          Cargando tus cuentas…
        </div>
      ) : accounts.isError ? (
        <div className="card flex h-48 flex-col items-center justify-center gap-3 p-8 text-center text-sm text-ink-muted">
          No se pudieron cargar tus cuentas.
          <button className="btn-secondary" onClick={() => accounts.refetch()}>
            Reintentar
          </button>
        </div>
      ) : (
        <div className="space-y-8">
          {orderedGroups.map((group) => {
            const items = list.filter((a) => a.behavior && group.behaviors.includes(a.behavior));
            return (
              <div key={group.title} className="space-y-3">
                <div className="flex items-end justify-between gap-3">
                  <div>
                    <h2 className="text-base font-semibold tracking-tight">{group.title}</h2>
                    <p className="text-xs text-ink-muted">{group.hint}</p>
                  </div>
                  <button
                    className="btn-ghost text-sm"
                    onClick={() => setCreating({ behavior: group.behaviors[group.behaviors.length > 1 ? 1 : 0] })}
                  >
                    <Icon name="plus" className="size-3.5" />
                    Agregar
                  </button>
                </div>
                {items.length === 0 ? (
                  <button
                    type="button"
                    onClick={() => setCreating({ behavior: group.behaviors[group.behaviors.length > 1 ? 1 : 0] })}
                    className="grid h-24 w-full place-items-center rounded-xl border border-dashed border-line-strong text-sm text-ink-muted transition hover:bg-card hover:text-ink"
                  >
                    <span className="flex items-center gap-2">
                      <Icon name="plus" className="size-4" />
                      Agregar a {group.title.toLowerCase()}
                    </span>
                  </button>
                ) : (
                  // items-stretch: todas las tarjetas de una fila miden lo mismo.
                  <div className="card-grid items-stretch">
                    {items.map((account) => (
                      <AccountItem
                        key={account.id}
                        account={account}
                        expanded={expanded === account.id}
                        onToggleExpand={() => setExpanded(expanded === account.id ? null : account.id)}
                        onEdit={() => setEditing(account.id)}
                        onAdjust={() => setAdjusting(account.id)}
                        sources={paySources}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
