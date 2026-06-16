// Ajustes: catálogos (CAT-01..05) y reglas recurrentes (REC-01..04).
import { useState, type FormEvent } from "react";
import {
  useCategories,
  useCreateCategory,
  useCreatePaymentMethod,
  useDeleteCategory,
  useDeletePaymentMethod,
  usePaymentMethods,
  useUpdateCategory,
  useUpdatePaymentMethod,
  type CategoryOut,
  type PaymentMethodOut,
} from "../../api/catalogs";
import { ApiError } from "../../api/client";
import Modal from "../../components/ui/Modal";
import {
  useCreateRecurringRule,
  useDeleteRecurringRule,
  useRecurringRules,
  useUpdateRecurringRule,
  type RecurringRuleOut,
} from "../../api/recurring";
import ImportSection from "./ImportSection";
import MembersSection from "../spaces/MembersSection";
import { useSpace } from "../spaces/SpaceProvider";
import { formatMoney } from "../../lib/money";
import { formatDate } from "../../lib/dates";

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
  const [deletingCategory, setDeletingCategory] = useState<CategoryOut | null>(null);
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
      onSuccess: () => setDeletingCategory(null),
      onError: (err) => {
        if (err instanceof ApiError && err.status === 409) {
          updateCategory.mutate(
            { id: c.id, is_active: false },
            {
              onSuccess: () => {
                setDeletingCategory(null);
                setDeleteMessage("Tiene registros asociados — fue desactivada en su lugar.");
              },
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
                      onClick={() => setDeletingCategory(c)}
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
          {editName !== editingCategory?.name && editName.trim() !== "" && (
            <p className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300">
              Todas las transacciones asignadas a esta categoría reflejarán el nuevo nombre.
            </p>
          )}
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

      {/* Modal de confirmación de eliminación */}
      <Modal
        open={deletingCategory !== null}
        onClose={() => setDeletingCategory(null)}
        title="Eliminar categoría"
      >
        {deletingCategory && (
          <div className="space-y-4">
            <p className="text-sm">
              ¿Eliminar <strong>{deletingCategory.name}</strong>? Si tiene transacciones
              asociadas, se desactivará en su lugar.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setDeletingCategory(null)}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-50"
                disabled={deleteCategory.isPending || updateCategory.isPending}
                onClick={() => handleDelete(deletingCategory)}
              >
                Eliminar
              </button>
            </div>
          </div>
        )}
      </Modal>
    </section>
  );
}

function PaymentMethodsSection() {
  const methods = usePaymentMethods(true);
  const createMethod = useCreatePaymentMethod();
  const updateMethod = useUpdatePaymentMethod();
  const deleteMethod = useDeletePaymentMethod();

  const [name, setName] = useState("");
  const [type, setType] = useState<"cash" | "debit" | "transfer" | "other">("debit");

  const [editingMethod, setEditingMethod] = useState<PaymentMethodOut | null>(null);
  const [editName, setEditName] = useState("");
  const [deletingMethod, setDeletingMethod] = useState<PaymentMethodOut | null>(null);
  const [deleteMessage, setDeleteMessage] = useState<string | null>(null);

  const nonCardMethods = (methods.data ?? []).filter((m) => m.card_id === null);

  function openEditModal(m: PaymentMethodOut) {
    setEditingMethod(m);
    setEditName(m.name);
  }

  function closeEditModal() {
    setEditingMethod(null);
  }

  function handleSaveEdit(e: FormEvent) {
    e.preventDefault();
    if (!editingMethod) return;
    updateMethod.mutate(
      { id: editingMethod.id, ...(editName !== editingMethod.name && { name: editName }) },
      { onSuccess: closeEditModal },
    );
  }

  function handleDelete(m: PaymentMethodOut) {
    setDeleteMessage(null);
    deleteMethod.mutate(m.id, {
      onSuccess: () => setDeletingMethod(null),
      onError: (err) => {
        if (err instanceof ApiError && err.status === 409) {
          updateMethod.mutate(
            { id: m.id, is_active: false },
            {
              onSuccess: () => {
                setDeletingMethod(null);
                setDeleteMessage("Tiene registros asociados — fue desactivado en su lugar.");
              },
            },
          );
        }
      },
    });
  }

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
      <ErrorText error={createMethod.error ?? deleteMethod.error} />
      {deleteMessage && (
        <p className="mb-2 text-sm text-amber-600 dark:text-amber-400">{deleteMessage}</p>
      )}
      <ul className="space-y-1">
        {nonCardMethods.map((m) => (
          <li
            key={m.id}
            className="flex items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
          >
            <span className={m.is_active ? "" : "line-through opacity-50"}>{m.name}</span>
            <span className="flex items-center gap-1">
              <button
                aria-label="Editar método de pago"
                className="rounded p-1 text-ink-muted transition-colors hover:bg-slate-100 hover:text-accent dark:hover:bg-slate-700"
                onClick={() => openEditModal(m)}
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                  <path d="M13.586 3.586a2 2 0 1 1 2.828 2.828l-.793.793-2.828-2.828.793-.793ZM11.379 5.793 3 14.172V17h2.828l8.38-8.379-2.83-2.828Z" />
                </svg>
              </button>
              {!m.is_active && (
                <button
                  className="text-xs text-accent hover:underline"
                  onClick={() => updateMethod.mutate({ id: m.id, is_active: true })}
                >
                  Reactivar
                </button>
              )}
              <button
                aria-label="Eliminar método de pago"
                className="rounded p-1 text-ink-muted transition-colors hover:bg-red-50 hover:text-red-500 disabled:opacity-40 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                onClick={() => setDeletingMethod(m)}
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                  <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clipRule="evenodd" />
                </svg>
              </button>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-ink-muted dark:text-slate-500">
        Los métodos de tarjeta de crédito y las tarjetas registradas se gestionan en la
        sección de Tarjetas.
      </p>

      <Modal open={editingMethod !== null} onClose={closeEditModal} title="Editar método de pago">
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
          {editName !== editingMethod?.name && editName.trim() !== "" && (
            <p className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300">
              Todas las transacciones asignadas a este método reflejarán el nuevo nombre.
            </p>
          )}
          <ErrorText error={updateMethod.error} />
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn-secondary" onClick={closeEditModal}>
              Cancelar
            </button>
            <button type="submit" className="btn-primary" disabled={updateMethod.isPending}>
              Guardar
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal de confirmación de eliminación */}
      <Modal
        open={deletingMethod !== null}
        onClose={() => setDeletingMethod(null)}
        title="Eliminar método de pago"
      >
        {deletingMethod && (
          <div className="space-y-4">
            <p className="text-sm">
              ¿Eliminar <strong>{deletingMethod.name}</strong>? Si tiene transacciones
              asociadas, se desactivará en su lugar.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setDeletingMethod(null)}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-50"
                disabled={deleteMethod.isPending || updateMethod.isPending}
                onClick={() => handleDelete(deletingMethod)}
              >
                Eliminar
              </button>
            </div>
          </div>
        )}
      </Modal>
    </section>
  );
}

interface RuleListProps {
  rules: RecurringRuleOut[];
  onEdit: (rule: RecurringRuleOut) => void;
  onToggle: (rule: RecurringRuleOut) => void;
  onDelete: (rule: RecurringRuleOut) => void;
}

function RuleList({ rules, onEdit, onToggle, onDelete }: RuleListProps) {
  return (
    <ul className="divide-y divide-line dark:divide-slate-800">
      {rules.map((r) => (
        <li key={r.id} className="flex items-center justify-between gap-3 py-2">
          <div className="min-w-0">
            <p className={`truncate text-sm font-medium ${r.is_active ? "" : "opacity-50"}`}>
              {r.description}
            </p>
            <p className="text-xs text-ink-muted dark:text-slate-400">
              {FREQ_LABELS[r.frequency]} · {formatMoney(r.amount, r.currency)} · desde{" "}
              {formatDate(r.start_date)}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              aria-label="Editar"
              className="rounded p-1 text-ink-muted transition-colors hover:bg-slate-100 hover:text-accent dark:hover:bg-slate-700"
              onClick={() => onEdit(r)}
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                <path d="M13.586 3.586a2 2 0 1 1 2.828 2.828l-.793.793-2.828-2.828.793-.793ZM11.379 5.793 3 14.172V17h2.828l8.38-8.379-2.83-2.828Z" />
              </svg>
            </button>
            <button
              type="button"
              className="text-xs text-accent hover:underline"
              onClick={() => onToggle(r)}
            >
              {r.is_active ? "Pausar" : "Reanudar"}
            </button>
            <button
              type="button"
              aria-label="Eliminar"
              className="rounded p-1 text-ink-muted transition-colors hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20 dark:hover:text-red-400"
              onClick={() => onDelete(r)}
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.498-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.498-.06l-.3 7.5a.75.75 0 1 0 1.498.06l.3-7.5Z" clipRule="evenodd" />
              </svg>
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

function RecurringSection() {
  const { activeSpace } = useSpace();
  const rules = useRecurringRules(true);
  const categories = useCategories();
  const methods = usePaymentMethods();
  const createRule = useCreateRecurringRule();
  const updateRule = useUpdateRecurringRule();
  const deleteRule = useDeleteRecurringRule();

  // Create — gasto
  const [expDesc, setExpDesc] = useState("");
  const [expAmount, setExpAmount] = useState("");
  const [expFreq, setExpFreq] = useState("monthly");
  const [expStart, setExpStart] = useState("");
  const [expCatId, setExpCatId] = useState("");
  const [expMethodId, setExpMethodId] = useState("");

  // Create — ingreso
  const [incDesc, setIncDesc] = useState("");
  const [incAmount, setIncAmount] = useState("");
  const [incFreq, setIncFreq] = useState("monthly");
  const [incStart, setIncStart] = useState("");
  const [incCatId, setIncCatId] = useState("");
  const [incMethodId, setIncMethodId] = useState("");

  // Modal de edición
  const [editingRule, setEditingRule] = useState<RecurringRuleOut | null>(null);
  const [editAmount, setEditAmount] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editCategoryId, setEditCategoryId] = useState("");
  const [editMethodId, setEditMethodId] = useState("");
  const [editEndDate, setEditEndDate] = useState("");

  // Modal de eliminación
  const [deletingRule, setDeletingRule] = useState<RecurringRuleOut | null>(null);

  const expenseRules = (rules.data ?? []).filter((r) => r.type === "expense");
  const incomeRules = (rules.data ?? []).filter((r) => r.type === "income");
  const expenseCats = (categories.data ?? []).filter((c) => c.kind === "expense");
  const incomeCats = (categories.data ?? []).filter((c) => c.kind === "income");
  const allMethods = methods.data ?? [];
  const editCategories = editingRule
    ? (categories.data ?? []).filter((c) => c.kind === editingRule.type)
    : [];

  function handleCreateExpense(e: FormEvent) {
    e.preventDefault();
    createRule.mutate(
      {
        type: "expense",
        description: expDesc,
        amount: expAmount,
        currency: activeSpace.base_currency,
        frequency: expFreq,
        start_date: expStart,
        category_id: expCatId || null,
        payment_method_id: expMethodId || null,
      },
      { onSuccess: () => { setExpDesc(""); setExpAmount(""); } },
    );
  }

  function handleCreateIncome(e: FormEvent) {
    e.preventDefault();
    createRule.mutate(
      {
        type: "income",
        description: incDesc,
        amount: incAmount,
        currency: activeSpace.base_currency,
        frequency: incFreq,
        start_date: incStart,
        category_id: incCatId || null,
        payment_method_id: incMethodId || null,
      },
      { onSuccess: () => { setIncDesc(""); setIncAmount(""); } },
    );
  }

  function openEdit(rule: RecurringRuleOut) {
    setEditingRule(rule);
    setEditAmount(rule.amount);
    setEditDescription(rule.description);
    setEditCategoryId(rule.category_id ?? "");
    setEditMethodId(rule.payment_method_id ?? "");
    setEditEndDate(rule.end_date ?? "");
  }

  function handleEditSubmit(e: FormEvent) {
    e.preventDefault();
    if (!editingRule) return;
    updateRule.mutate(
      {
        id: editingRule.id,
        amount: editAmount,
        description: editDescription,
        category_id: editCategoryId || null,
        payment_method_id: editMethodId || null,
        end_date: editEndDate || null,
      },
      { onSuccess: () => setEditingRule(null) },
    );
  }

  function handleToggle(rule: RecurringRuleOut) {
    updateRule.mutate({ id: rule.id, is_active: !rule.is_active });
  }

  function handleDelete() {
    if (!deletingRule) return;
    deleteRule.mutate(deletingRule.id, { onSuccess: () => setDeletingRule(null) });
  }

  return (
    <>
      {/* Gastos recurrentes */}
      <section className="card p-5">
        <h2 className="mb-1 font-semibold">Gastos recurrentes</h2>
        <p className="mb-4 text-xs text-ink-muted dark:text-slate-400">
          Suscripciones, renta, servicios. Se generan solos y aparecen en
          &ldquo;Por confirmar&rdquo;.
        </p>
        <form onSubmit={handleCreateExpense} className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-6">
          <input
            className="input col-span-2"
            placeholder="Descripción (p. ej. Spotify)"
            required
            value={expDesc}
            onChange={(e) => setExpDesc(e.target.value)}
          />
          <input
            className="input"
            placeholder="Monto"
            inputMode="decimal"
            pattern="^\d+(\.\d{1,2})?$"
            required
            value={expAmount}
            onChange={(e) => setExpAmount(e.target.value)}
          />
          <select className="input" value={expFreq} onChange={(e) => setExpFreq(e.target.value)}>
            {Object.entries(FREQ_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <input
            type="date"
            className="input"
            required
            value={expStart}
            onChange={(e) => setExpStart(e.target.value)}
          />
          <button className="btn-primary" disabled={createRule.isPending}>Crear</button>
          <select
            className="input col-span-2"
            required
            value={expCatId}
            onChange={(e) => setExpCatId(e.target.value)}
          >
            <option value="">Categoría…</option>
            {expenseCats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select
            className="input col-span-2"
            required
            value={expMethodId}
            onChange={(e) => setExpMethodId(e.target.value)}
          >
            <option value="">Método de pago…</option>
            {allMethods.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </form>
        <ErrorText error={createRule.error} />
        <RuleList
          rules={expenseRules}
          onEdit={openEdit}
          onToggle={handleToggle}
          onDelete={setDeletingRule}
        />
      </section>

      {/* Ingresos recurrentes */}
      <section className="card p-5">
        <h2 className="mb-1 font-semibold">Ingresos recurrentes</h2>
        <p className="mb-4 text-xs text-ink-muted dark:text-slate-400">
          Nómina, freelance, rentas cobradas. Se generan solos y aparecen en
          &ldquo;Por confirmar&rdquo;.
        </p>
        <form onSubmit={handleCreateIncome} className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-6">
          <input
            className="input col-span-2"
            placeholder="Descripción (p. ej. Nómina)"
            required
            value={incDesc}
            onChange={(e) => setIncDesc(e.target.value)}
          />
          <input
            className="input"
            placeholder="Monto"
            inputMode="decimal"
            pattern="^\d+(\.\d{1,2})?$"
            required
            value={incAmount}
            onChange={(e) => setIncAmount(e.target.value)}
          />
          <select className="input" value={incFreq} onChange={(e) => setIncFreq(e.target.value)}>
            {Object.entries(FREQ_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <input
            type="date"
            className="input"
            required
            value={incStart}
            onChange={(e) => setIncStart(e.target.value)}
          />
          <button className="btn-primary" disabled={createRule.isPending}>Crear</button>
          <select
            className="input col-span-2"
            required
            value={incCatId}
            onChange={(e) => setIncCatId(e.target.value)}
          >
            <option value="">Categoría…</option>
            {incomeCats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select
            className="input col-span-2"
            required
            value={incMethodId}
            onChange={(e) => setIncMethodId(e.target.value)}
          >
            <option value="">Método de pago…</option>
            {allMethods.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </form>
        <ErrorText error={createRule.error} />
        <RuleList
          rules={incomeRules}
          onEdit={openEdit}
          onToggle={handleToggle}
          onDelete={setDeletingRule}
        />
      </section>

      {/* Modal: editar regla recurrente */}
      <Modal
        open={editingRule !== null}
        onClose={() => setEditingRule(null)}
        title="Editar recurrente"
        size="lg"
      >
        <form onSubmit={handleEditSubmit} className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <span className="inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300">
              {editingRule?.type === "expense" ? "Gasto" : "Ingreso"}
            </span>
            <span className="inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300">
              {editingRule ? FREQ_LABELS[editingRule.frequency] : ""}
            </span>
            <span className="inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300">
              Desde {editingRule ? formatDate(editingRule.start_date) : ""}
            </span>
          </div>
          <p className="text-xs text-ink-muted dark:text-slate-400">
            Los cambios solo aplican a los próximos pagos.
          </p>
          <div className="grid grid-cols-4 gap-3">
            <div>
              <label className="label">Monto</label>
              <input
                className="input"
                inputMode="decimal"
                pattern="^\d+(\.\d{1,2})?$"
                required
                value={editAmount}
                onChange={(e) => setEditAmount(e.target.value)}
              />
            </div>
            <div>
              <label className="label">Fecha fin</label>
              <input
                type="date"
                className="input"
                value={editEndDate}
                onChange={(e) => setEditEndDate(e.target.value)}
              />
            </div>
            <div>
              <label className="label">Categoría</label>
              <select
                className="input"
                value={editCategoryId}
                onChange={(e) => setEditCategoryId(e.target.value)}
              >
                <option value="">Sin categoría</option>
                {editCategories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Método de pago</label>
              <select
                className="input"
                value={editMethodId}
                onChange={(e) => setEditMethodId(e.target.value)}
              >
                <option value="">Sin método</option>
                {allMethods.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-4 gap-3">
            <div className="col-span-4">
              <label className="label">Descripción</label>
              <input
                className="input"
                required
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
              />
            </div>
          </div>
          <ErrorText error={updateRule.error} />
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn-secondary" onClick={() => setEditingRule(null)}>
              Cancelar
            </button>
            <button type="submit" className="btn-primary" disabled={updateRule.isPending}>
              Guardar
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: confirmar eliminación */}
      <Modal
        open={deletingRule !== null}
        onClose={() => setDeletingRule(null)}
        title="Eliminar recurrente"
      >
        {deletingRule && (
          <div className="space-y-4">
            <p className="text-sm">
              ¿Eliminar <strong>{deletingRule.description}</strong>? Los pagos ya confirmados
              se conservan en tu historial.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setDeletingRule(null)}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-50"
                disabled={deleteRule.isPending}
                onClick={handleDelete}
              >
                Eliminar
              </button>
            </div>
          </div>
        )}
      </Modal>
    </>
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
