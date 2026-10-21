// Ajustes: miembros, catálogos (CAT-01..06) e importación. Las cuentas (antes
// "métodos de pago", CAT-07 derogada) viven en la página Cuentas y las reglas
// recurrentes en Suscripciones (REC-07).
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  useCategories,
  useCreateCategory,
  useDeleteCategory,
  useUpdateCategory,
  type CategoryOut,
} from "../../api/catalogs";
import { ApiError } from "../../api/client";
import CollapsibleCard from "../../components/ui/CollapsibleCard";
import Modal from "../../components/ui/Modal";
import ImportSection from "./ImportSection";
import MembersSection from "../spaces/MembersSection";

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
    <CollapsibleCard
      title="Categorías"
      description="Gastos e ingresos, con su naturaleza: fijo, variable o discrecional."
    >

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
            <h3 className="mb-2 text-sm font-medium text-ink-muted">
              {kind === "expense" ? "Gastos" : "Ingresos"}
            </h3>
            <ul className="space-y-1">
              {grouped[kind].map((c) => (
                <li
                  key={c.id}
                  className="flex items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-muted"
                >
                  <span className={c.is_active ? "" : "line-through opacity-50"}>
                    {c.name}
                    {c.expense_nature && (
                      <span className="ml-2 text-xs text-ink-muted">
                        {NATURE_LABELS[c.expense_nature as ExpenseNature]}
                      </span>
                    )}
                  </span>
                  <span className="flex items-center gap-1">
                    <button
                      aria-label="Editar categoría"
                      className="rounded p-1 text-ink-muted transition-colors hover:bg-muted hover:text-accent"
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
                      className="rounded p-1 text-ink-muted transition-colors hover:bg-red-500/10 hover:text-red-500 disabled:opacity-40 dark:hover:text-red-400"
                      onClick={() => setDeletingCategory(c)}
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="size-4">
                        <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clipRule="evenodd" />
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
            <p className="rounded-md border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs text-blue-700 dark:text-blue-300">
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
                className="btn-danger"
                disabled={deleteCategory.isPending || updateCategory.isPending}
                onClick={() => handleDelete(deletingCategory)}
              >
                Eliminar
              </button>
            </div>
          </div>
        )}
      </Modal>
    </CollapsibleCard>
  );
}

// REC-07: los recurrentes viven en su propio módulo.
function RecurringLink() {
  return (
    <section className="card flex flex-wrap items-center justify-between gap-3 p-4 sm:p-5">
      <div>
        <h2 className="text-base font-semibold tracking-tight">Pagos recurrentes</h2>
        <p className="text-sm text-ink-muted">
          Suscripciones, servicios, nómina y renta ahora viven en Suscripciones.
        </p>
      </div>
      <Link className="btn-secondary" to="/suscripciones">
        Ir a Suscripciones
      </Link>
    </section>
  );
}

export default function SettingsPage() {
  return (
    <div className="page">
      <div>
        <h1 className="page-title">Ajustes</h1>
        <p className="page-subtitle">Abre la sección que quieras configurar.</p>
      </div>
      <div className="space-y-3">
        <MembersSection />
        <CategoriesSection />
        <RecurringLink />
        <ImportSection />
      </div>
    </div>
  );
}
