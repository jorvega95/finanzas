// Ajustes: catálogos (CAT-01..05) y reglas recurrentes (REC-01..04).
import { useState, type FormEvent } from "react";
import {
  useCategories,
  useCreateCategory,
  useCreatePaymentMethod,
  usePaymentMethods,
  useUpdateCategory,
  useUpdatePaymentMethod,
} from "../../api/catalogs";
import {
  useCreateRecurringRule,
  useRecurringRules,
  useUpdateRecurringRule,
} from "../../api/recurring";
import ImportSection from "./ImportSection";
import MembersSection from "../spaces/MembersSection";
import { useSpace } from "../spaces/SpaceProvider";
import { formatMoney } from "../../lib/money";

const FREQ_LABELS: Record<string, string> = {
  weekly: "Semanal",
  biweekly: "Quincenal",
  monthly: "Mensual",
  yearly: "Anual",
};

function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p className="mt-2 text-sm text-red-600 dark:text-red-400">
      {error instanceof Error ? error.message : "Error"}
    </p>
  );
}

function CategoriesSection() {
  const categories = useCategories(true);
  const createCategory = useCreateCategory();
  const updateCategory = useUpdateCategory();
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState<"expense" | "income">("expense");

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    createCategory.mutate(
      { name: newName, kind: newKind },
      { onSuccess: () => setNewName("") },
    );
  }

  const grouped = {
    expense: (categories.data ?? []).filter((c) => c.kind === "expense"),
    income: (categories.data ?? []).filter((c) => c.kind === "income"),
  };

  return (
    <section className="card p-5">
      <h2 className="mb-4 font-semibold">Categorías</h2>
      <form onSubmit={handleCreate} className="mb-4 flex flex-wrap gap-2">
        <input
          className="input w-48"
          placeholder="Nueva categoría"
          required
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <select
          className="input w-36"
          value={newKind}
          onChange={(e) => setNewKind(e.target.value as "expense" | "income")}
        >
          <option value="expense">Gasto</option>
          <option value="income">Ingreso</option>
        </select>
        <button className="btn-primary" disabled={createCategory.isPending}>
          Agregar
        </button>
      </form>
      <ErrorText error={createCategory.error ?? updateCategory.error} />
      <div className="grid gap-6 md:grid-cols-2">
        {(["expense", "income"] as const).map((kind) => (
          <div key={kind}>
            <h3 className="mb-2 text-sm font-medium text-ink-muted dark:text-slate-400">
              {kind === "expense" ? "Gastos" : "Ingresos"}
            </h3>
            <ul className="space-y-1">
              {grouped[kind].map((c) => (
                <li
                  key={c.id}
                  className="flex items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
                >
                  <span className={c.is_active ? "" : "line-through opacity-50"}>
                    {c.name}
                    {c.expense_nature && (
                      <span className="ml-2 text-xs text-ink-muted dark:text-slate-500">
                        {c.expense_nature === "fixed"
                          ? "fijo"
                          : c.expense_nature === "variable"
                            ? "variable"
                            : "discrecional"}
                      </span>
                    )}
                  </span>
                  <button
                    className="text-xs text-accent hover:underline"
                    onClick={() =>
                      updateCategory.mutate({ id: c.id, is_active: !c.is_active })
                    }
                  >
                    {c.is_active ? "Desactivar" : "Reactivar"}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

function PaymentMethodsSection() {
  const methods = usePaymentMethods(true);
  const createMethod = useCreatePaymentMethod();
  const updateMethod = useUpdatePaymentMethod();
  const [name, setName] = useState("");
  const [type, setType] = useState<"cash" | "debit" | "transfer" | "other">("debit");

  return (
    <section className="card p-5">
      <h2 className="mb-4 font-semibold">Métodos de pago</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          createMethod.mutate({ name, type }, { onSuccess: () => setName("") });
        }}
        className="mb-4 flex flex-wrap gap-2"
      >
        <input
          className="input w-48"
          placeholder="Nuevo método"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <select
          className="input w-36"
          value={type}
          onChange={(e) => setType(e.target.value as typeof type)}
        >
          <option value="cash">Efectivo</option>
          <option value="debit">Débito</option>
          <option value="transfer">Transferencia</option>
          <option value="other">Otro</option>
        </select>
        <button className="btn-primary" disabled={createMethod.isPending}>
          Agregar
        </button>
      </form>
      <ErrorText error={createMethod.error ?? updateMethod.error} />
      <ul className="space-y-1">
        {(methods.data ?? []).map((m) => (
          <li
            key={m.id}
            className="flex items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
          >
            <span className={m.is_active ? "" : "line-through opacity-50"}>{m.name}</span>
            <button
              className="text-xs text-accent hover:underline"
              onClick={() => updateMethod.mutate({ id: m.id, is_active: !m.is_active })}
            >
              {m.is_active ? "Desactivar" : "Reactivar"}
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-ink-muted dark:text-slate-500">
        Los métodos de tarjeta de crédito se crean automáticamente al dar de alta una
        tarjeta.
      </p>
    </section>
  );
}

function RecurringSection() {
  const { activeSpace } = useSpace();
  const rules = useRecurringRules(true);
  const categories = useCategories();
  const methods = usePaymentMethods();
  const createRule = useCreateRecurringRule();
  const updateRule = useUpdateRecurringRule();

  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [frequency, setFrequency] = useState("monthly");
  const [startDate, setStartDate] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [methodId, setMethodId] = useState("");

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    createRule.mutate(
      {
        type: "expense",
        description,
        amount,
        currency: activeSpace.base_currency,
        frequency,
        start_date: startDate,
        category_id: categoryId || null,
        payment_method_id: methodId || null,
      },
      {
        onSuccess: () => {
          setDescription("");
          setAmount("");
        },
      },
    );
  }

  return (
    <section className="card p-5">
      <h2 className="mb-1 font-semibold">Gastos recurrentes</h2>
      <p className="mb-4 text-xs text-ink-muted dark:text-slate-400">
        Suscripciones, renta, servicios. Se generan solos y aparecen en
        &ldquo;Por confirmar&rdquo;.
      </p>
      <form onSubmit={handleCreate} className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-6">
        <input
          className="input col-span-2"
          placeholder="Descripción (p. ej. Spotify)"
          required
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <input
          className="input"
          placeholder="Monto"
          inputMode="decimal"
          pattern="^\d+(\.\d{1,2})?$"
          required
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
        <select
          className="input"
          value={frequency}
          onChange={(e) => setFrequency(e.target.value)}
        >
          {Object.entries(FREQ_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <input
          type="date"
          className="input"
          required
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
        />
        <button className="btn-primary" disabled={createRule.isPending}>
          Crear
        </button>
        <select
          className="input col-span-2"
          required
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
        >
          <option value="">Categoría…</option>
          {(categories.data ?? [])
            .filter((c) => c.kind === "expense")
            .map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
        </select>
        <select
          className="input col-span-2"
          required
          value={methodId}
          onChange={(e) => setMethodId(e.target.value)}
        >
          <option value="">Método de pago…</option>
          {(methods.data ?? []).map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
      </form>
      <ErrorText error={createRule.error} />
      <ul className="divide-y divide-line dark:divide-slate-800">
        {(rules.data ?? []).map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-3 py-2">
            <div>
              <p className={`text-sm font-medium ${r.is_active ? "" : "opacity-50"}`}>
                {r.description}
              </p>
              <p className="text-xs text-ink-muted dark:text-slate-400">
                {FREQ_LABELS[r.frequency]} · {formatMoney(r.amount, r.currency)} · desde{" "}
                {r.start_date}
              </p>
            </div>
            <button
              className="text-xs text-accent hover:underline"
              onClick={() => updateRule.mutate({ id: r.id, is_active: !r.is_active })}
            >
              {r.is_active ? "Pausar" : "Reanudar"}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <MembersSection />
      <CategoriesSection />
      <PaymentMethodsSection />
      <RecurringSection />
      <ImportSection />
    </div>
  );
}
