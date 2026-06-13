// Ajustes: catálogos (CAT-01..05) y reglas recurrentes (REC-01..04).
import { useState, type FormEvent } from "react";
import {
  useCategories,
  useCreateCategory,
  useCreatePaymentMethod,
  useDeleteCategory,
  usePaymentMethods,
  useUpdateCategory,
  useUpdatePaymentMethod,
  type CategoryOut,
} from "../../api/catalogs";
import { ApiError } from "../../api/client";
import Modal from "../../components/ui/Modal";
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

type ExpenseNature = "fixed" | "variable" | "discretionary";

const NATURE_LABELS: Record<ExpenseNature, string> = {
  variable: "Variable",
  fixed: "Fijo",
  discretionary: "Discrecional",
};

function CategoriesSection() {
  const categories = useCategories(true);
  const createCategory = useCreateCategory();
  const updateCategory = useUpdateCategory();
  const deleteCategory = useDeleteCategory();

  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState<"expense" | "income">("expense");
  const [newNature, setNewNature] = useState<ExpenseNature>("variable");

  const [editingCategory, setEditingCategory] = useState<CategoryOut | null>(null);
  const [editName, setEditName] = useState("");
  const [editNature, setEditNature] = useState<ExpenseNature>("variable");
  const [deleteMessage, setDeleteMessage] = useState<string | null>(null);

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    createCategory.mutate(
      {
        name: newName,
        kind: newKind,
        ...(newKind === "expense" && { expense_nature: newNature }),
      },
      { onSuccess: () => setNewName("") },
    );
  }

  function openEditModal(c: CategoryOut) {
    setEditingCategory(c);
    setEditName(c.name);
    setEditNature((c.expense_nature ?? "variable") as ExpenseNature);
  }

  function closeEditModal() {
    setEditingCategory(null);
  }

  function handleSaveEdit(e: FormEvent) {
    e.preventDefault();
    if (!editingCategory) return;
    updateCategory.mutate(
      {
        id: editingCategory.id,
        ...(editName !== editingCategory.name && { name: editName }),
        ...(editingCategory.kind === "expense" &&
          editNature !== editingCategory.expense_nature && { expense_nature: editNature }),
      },
      { onSuccess: closeEditModal },
    );
  }

  function handleDelete(c: CategoryOut) {
    setDeleteMessage(null);
    deleteCategory.mutate(c.id, {
      onError: (err) => {
        if (err instanceof ApiError && err.status === 409) {
          updateCategory.mutate(
            { id: c.id, is_active: false },
            {
              onSuccess: () =>
                setDeleteMessage("Tiene registros asociados — fue desactivada en su lugar."),
            },
          );
        }
      },
    });
  }

  const grouped = {
    expense: (categories.data ?? []).filter((c) => c.kind === "expense"),
    income: (categories.data ?? []).filter((c) => c.kind === "income"),
  };

  return (
    <section className="card p-5">
      <h2 className="mb-4 font-semibold">Categorías</h2>

      {/* Formulario de creación */}
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
        {newKind === "expense" && (
          <select
            className="input w-40"
            value={newNature}
            onChange={(e) => setNewNature(e.target.value as ExpenseNature)}
          >
            {(Object.keys(NATURE_LABELS) as ExpenseNature[]).map((n) => (
              <option key={n} value={n}>
                {NATURE_LABELS[n]}
              </option>
            ))}
          </select>
        )}
        <button className="btn-primary" disabled={createCategory.isPending}>
          Agregar
        </button>
      </form>

      <ErrorText error={createCategory.error ?? deleteCategory.error} />
      {deleteMessage && (
        <p className="mb-2 text-sm text-amber-600 dark:text-amber-400">{deleteMessage}</p>
      )}

      {/* Listado agrupado */}
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
                        {NATURE_LABELS[c.expense_nature as ExpenseNature]}
                      </span>
                    )}
                  </span>
                  <span className="flex items-center gap-1">
                    <button
                      aria-label="Editar categoría"
                      className="rounded p-1 text-ink-muted transition-colors hover:bg-slate-100 hover:text-accent dark:hover:bg-slate-700"
                      onClick={() => openEditModal(c)}
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                        <path d="M13.586 3.586a2 2 0 1 1 2.828 2.828l-.793.793-2.828-2.828.793-.793ZM11.379 5.793 3 14.172V17h2.828l8.38-8.379-2.83-2.828Z" />
                      </svg>
                    </button>
                    {!c.is_active && (
                      <button
                        className="text-xs text-accent hover:underline"
                        onClick={() => updateCategory.mutate({ id: c.id, is_active: true })}
                      >
                        Reactivar
                      </button>
                    )}
                    <button
                      aria-label="Eliminar categoría"
                      className="rounded p-1 text-ink-muted transition-colors hover:bg-red-50 hover:text-red-500 disabled:opacity-40 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                      onClick={() => handleDelete(c)}
                      disabled={deleteCategory.isPending}
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                        <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clip-rule="evenodd" />
                      </svg>
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Modal de edición */}
      <Modal
        open={editingCategory !== null}
        onClose={closeEditModal}
        title="Editar categoría"
      >
        <form onSubmit={handleSaveEdit} className="space-y-4">
          <div>
            <label className="label">Nombre</label>
            <input
              className="input"
              value={editName}
              required
              onChange={(e) => setEditName(e.target.value)}
            />
          </div>
          {editingCategory?.kind === "expense" && (
            <div>
              <label className="label">Tipo de gasto</label>
              <select
                className="input"
                value={editNature}
                onChange={(e) => setEditNature(e.target.value as ExpenseNature)}
              >
                {(Object.keys(NATURE_LABELS) as ExpenseNature[]).map((n) => (
                  <option key={n} value={n}>
                    {NATURE_LABELS[n]}
                  </option>
                ))}
              </select>
            </div>
          )}
          <ErrorText error={updateCategory.error} />
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn-secondary" onClick={closeEditModal}>
              Cancelar
            </button>
            <button type="submit" className="btn-primary" disabled={updateCategory.isPending}>
              Guardar
            </button>
          </div>
        </form>
      </Modal>
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
