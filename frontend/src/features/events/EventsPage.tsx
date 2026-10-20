// Eventos (EVT-01..05): agrupan los movimientos de algo extraordinario (boda,
// mudanza, viaje) sin cambiar sus categorías. Cada evento muestra lo gastado,
// los regalos recibidos, el costo neto, el avance contra su presupuesto y los
// préstamos ligados (TAR-11). Los movimientos se ligan desde Transacciones.
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  useCreateEvent,
  useDeleteEvent,
  useEvents,
  useUpdateEvent,
  type EventBody,
  type EventOut,
  type EventSummary,
} from "../../api/events";
import { useSpace } from "../spaces/SpaceProvider";
import { formatMoney, isNegativeAmount, isPositiveAmount, subtractMoney } from "../../lib/money";
import { formatDate } from "../../lib/dates";
import Icon from "../../components/ui/Icon";
import Modal from "../../components/ui/Modal";
import Spinner from "../../components/ui/Spinner";

function EventForm({ event, onDone }: { event: EventOut | null; onDone: () => void }) {
  const create = useCreateEvent();
  const update = useUpdateEvent();
  const remove = useDeleteEvent();
  const [name, setName] = useState(event?.name ?? "");
  const [date, setDate] = useState(event?.date ?? "");
  const [budget, setBudget] = useState(event?.budget ?? "");
  const [notes, setNotes] = useState(event?.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const pending = create.isPending || update.isPending || remove.isPending;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (budget && !isPositiveAmount(budget)) {
      setError("El presupuesto debe ser mayor a 0, o déjalo vacío.");
      return;
    }
    const body: EventBody = {
      name: name.trim(),
      date: date || null,
      budget: budget || null,
      notes: notes.trim() || null,
    };
    try {
      if (event) await update.mutateAsync({ id: event.id, ...body });
      else await create.mutateAsync(body);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3">
      <div className="col-span-2">
        <label className="label" htmlFor="event-name">Nombre</label>
        <input
          id="event-name"
          className="input"
          required
          maxLength={80}
          placeholder="Boda, Luna de miel, Mudanza…"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="event-date">Fecha (opcional)</label>
        <input
          id="event-date"
          type="date"
          className="input"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="event-budget">Presupuesto (opcional)</label>
        <input
          id="event-budget"
          className="input"
          inputMode="decimal"
          pattern="^\d+(\.\d{1,2})?$"
          placeholder="0.00"
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
        />
      </div>
      <div className="col-span-2">
        <label className="label" htmlFor="event-notes">Notas</label>
        <textarea
          id="event-notes"
          className="input min-h-20"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>
      {error && <p className="col-span-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="col-span-2 flex flex-wrap items-center justify-between gap-2 pt-1">
        {event ? (
          <div className="flex gap-3">
            <button
              type="button"
              className="text-sm font-medium text-ink-muted hover:text-red-600 hover:underline dark:hover:text-red-400"
              disabled={pending}
              onClick={() => void run(() => remove.mutateAsync(event.id))}
              title="Solo si no tiene movimientos ligados"
            >
              Eliminar
            </button>
            <button
              type="button"
              className="text-sm font-medium text-ink-muted hover:text-ink hover:underline"
              disabled={pending}
              onClick={() =>
                void run(() => update.mutateAsync({ id: event.id, is_active: !event.is_active }))
              }
            >
              {event.is_active ? "Desactivar" : "Reactivar"}
            </button>
          </div>
        ) : (
          <span />
        )}
        <div className="flex gap-2">
          <button type="button" className="btn-secondary" onClick={onDone}>
            Cancelar
          </button>
          <button className="btn-primary" disabled={pending}>
            {event ? "Guardar cambios" : "Crear evento"}
          </button>
        </div>
      </div>
    </form>
  );
}

function Stat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2.5">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className={`tabular mt-0.5 text-base font-semibold ${tone}`}>{value}</p>
    </div>
  );
}

function EventCard({
  summary,
  currency,
  onEdit,
}: {
  summary: EventSummary;
  currency: string;
  onEdit: () => void;
}) {
  const { event } = summary;
  const [open, setOpen] = useState(false);
  // Solo proporción visual de la barra (no aritmética de dinero, GLO-01).
  const usage =
    event.budget && Number(event.budget) > 0
      ? Math.min(100, (Number(summary.spent) / Number(event.budget)) * 100)
      : null;
  const overBudget = summary.budget_remaining !== null && isNegativeAmount(summary.budget_remaining);

  return (
    <section className={`card @container p-4 sm:p-5 ${event.is_active ? "" : "opacity-70"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold tracking-tight">
            {event.name}
            {!event.is_active && (
              <span className="ml-2 rounded-full bg-muted px-2 py-0.5 align-middle text-xs font-normal text-ink-muted">
                Inactivo
              </span>
            )}
          </h2>
          <p className="text-sm text-ink-muted">
            {[event.date ? formatDate(event.date) : null, `${summary.movements} movimientos`]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <div className="flex gap-1.5">
          <Link className="btn-secondary" to={`/transacciones?evento=${event.id}`}>
            Ver movimientos
          </Link>
          <button className="btn-secondary" onClick={onEdit}>
            <Icon name="pencil" className="size-3.5" />
            Editar
          </button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 @xl:grid-cols-4">
        <Stat label="Gastado" value={formatMoney(summary.spent, currency)} />
        <Stat
          label="Regalos recibidos"
          value={formatMoney(summary.received, currency)}
          tone="text-emerald-600 dark:text-emerald-400"
        />
        <Stat label="Costo neto" value={formatMoney(summary.net, currency)} />
        {summary.budget_remaining !== null ? (
          <Stat
            label={overBudget ? "Excedido" : "Por gastar"}
            value={formatMoney(
              overBudget ? subtractMoney("0", summary.budget_remaining) : summary.budget_remaining,
              currency,
            )}
            tone={overBudget ? "text-red-600 dark:text-red-400" : ""}
          />
        ) : (
          <Stat label="Presupuesto" value="Sin definir" />
        )}
      </div>

      {isPositiveAmount(summary.spent_before_tracking) && (
        <p className="mt-2 text-xs text-ink-muted">
          Lo gastado incluye {formatMoney(summary.spent_before_tracking, currency)} abonados a
          proveedores antes de usar la app.
        </p>
      )}

      {usage !== null && event.budget && (
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-xs text-ink-muted">
            <span>Avance del presupuesto</span>
            <span className="tabular">
              {usage.toFixed(0)}% de {formatMoney(event.budget, currency)}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className={`h-full rounded-full ${
                usage >= 100 ? "bg-red-500" : usage > 80 ? "bg-amber-500" : "bg-accent"
              }`}
              style={{ width: `${usage}%` }}
            />
          </div>
        </div>
      )}

      {/* CXP-03: lo que aún se debe a los proveedores del evento. */}
      {isPositiveAmount(summary.pending_commitments) && (
        <Link
          to={`/compromisos?evento=${event.id}`}
          className="mt-3 flex items-center justify-between gap-2 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm hover:bg-sky-500/15"
        >
          <span className="flex items-center gap-2 text-sky-900 dark:text-sky-200">
            <Icon name="target" className="size-4" />
            Por pagar a proveedores
          </span>
          <span className="tabular font-semibold">
            {formatMoney(summary.pending_commitments, currency)}
          </span>
        </Link>
      )}

      {/* TAR-11: préstamos usados para el evento, con su saldo actual. */}
      {summary.loans.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {summary.loans.map((loan) => {
            const owe = isNegativeAmount(loan.balance);
            const owed = isPositiveAmount(loan.balance);
            return (
              <li
                key={loan.account_id}
                className="flex items-center justify-between gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm"
              >
                <span className="flex items-center gap-2 text-amber-900 dark:text-amber-200">
                  <Icon name="handshake" className="size-4" />
                  {loan.name}
                </span>
                <span className="tabular font-semibold">
                  {owe
                    ? `Debes ${formatMoney(subtractMoney("0", loan.balance), loan.currency)}`
                    : owed
                      ? `Te deben ${formatMoney(loan.balance, loan.currency)}`
                      : "Saldado"}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {summary.by_category.length > 0 && (
        <div className="mt-3">
          <button
            type="button"
            className="flex items-center gap-1 text-sm text-ink-muted hover:text-ink"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            <Icon name="chevronDown" className={`size-3.5 transition ${open ? "rotate-180" : ""}`} />
            Por categoría
          </button>
          {open && (
            <ul className="mt-2 divide-y divide-line text-sm">
              {summary.by_category.map((row) => (
                <li key={row.category_id ?? "none"} className="flex justify-between py-1.5">
                  <span>{row.category_name}</span>
                  <span className="tabular">{formatMoney(row.total, currency)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

export default function EventsPage() {
  const { activeSpace } = useSpace();
  const currency = activeSpace.base_currency;
  const [showInactive, setShowInactive] = useState(false);
  const events = useEvents(showInactive);
  const [editing, setEditing] = useState<EventOut | "new" | null>(null);
  const list = events.data ?? [];

  return (
    <div className="page">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="page-title">Eventos</h1>
          <p className="page-subtitle">
            Agrupa los gastos y regalos de algo extraordinario: una boda, un viaje, una mudanza.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="mr-1 flex items-center gap-1.5 text-sm text-ink-muted">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(e) => setShowInactive(e.target.checked)}
            />
            Mostrar inactivos
          </label>
          <button className="btn-primary" onClick={() => setEditing("new")}>
            <Icon name="plus" />
            Nuevo evento
          </button>
        </div>
      </div>

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? "Nuevo evento" : `Editar ${editing?.name ?? ""}`}
        size="lg"
      >
        {editing !== null && (
          <EventForm
            key={editing === "new" ? "new" : editing.id}
            event={editing === "new" ? null : editing}
            onDone={() => setEditing(null)}
          />
        )}
      </Modal>

      {events.isPending ? (
        <div className="card flex h-48 flex-col items-center justify-center gap-3 p-8 text-center text-sm text-ink-muted">
          <Spinner className="size-7" />
          Cargando eventos…
        </div>
      ) : events.isError ? (
        <div className="card flex h-48 flex-col items-center justify-center gap-3 p-8 text-center text-sm text-ink-muted">
          No se pudieron cargar los eventos.
          <button className="btn-secondary" onClick={() => events.refetch()}>
            Reintentar
          </button>
        </div>
      ) : list.length === 0 ? (
        <button
          type="button"
          onClick={() => setEditing("new")}
          className="grid w-full place-items-center gap-2 rounded-xl border border-dashed border-line-strong p-10 text-center text-sm text-ink-muted transition hover:bg-card hover:text-ink"
        >
          <Icon name="party" className="size-6" />
          <span className="font-medium text-ink">Crea tu primer evento</span>
          <span className="max-w-md">
            Luego, al registrar un gasto o un regalo, elige el evento para ver cuánto te costó en
            total. Las categorías no cambian: la banda sigue siendo «Entretenimiento».
          </span>
        </button>
      ) : (
        <div className="space-y-4">
          {list.map((summary) => (
            <EventCard
              key={summary.event.id}
              summary={summary}
              currency={currency}
              onEdit={() => setEditing(summary.event)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
