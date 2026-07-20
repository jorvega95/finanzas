// Campana del centro de notificaciones in-app (REM-04..REM-07, OPP-01).
// Badge de no leídos + panel con los avisos del espacio activo.
import { useEffect, useRef, useState } from "react";
import {
  useDismissNotification,
  useMarkAllRead,
  useNotifications,
  useUnreadCount,
  type NotificationOut,
} from "../api/notifications";
import { formatDate } from "../lib/dates";

const KIND_ICON: Record<NotificationOut["kind"], string> = {
  card_due: "💳",
  budget_alert: "🎯",
  custom: "🔔",
};

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const notifications = useNotifications();
  const unread = useUnreadCount();
  const markAllRead = useMarkAllRead();
  const dismiss = useDismissNotification();

  const items = notifications.data ?? [];
  const unreadCount = unread.data?.unread ?? 0;

  // Cerrar al hacer clic fuera o con Escape.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  // REM-07: abrir el panel es "ver" los avisos ⇒ el badge se limpia, pero
  // siguen en la lista hasta que el usuario los descarte (REM-05).
  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && unreadCount > 0 && !markAllRead.isPending) markAllRead.mutate();
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={toggle}
        className="btn-secondary relative"
        aria-label={
          unreadCount > 0 ? `Notificaciones (${unreadCount} sin leer)` : "Notificaciones"
        }
        aria-expanded={open}
      >
        🔔
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="card absolute right-0 z-20 mt-2 max-h-96 w-80 overflow-y-auto p-0 shadow-lg sm:w-96">
          <div className="flex items-center justify-between border-b border-line px-4 py-2 dark:border-slate-800">
            <h2 className="text-sm font-semibold">Notificaciones</h2>
            <span className="text-xs text-ink-muted dark:text-slate-500">
              {items.length > 0 ? `${items.length}` : ""}
            </span>
          </div>

          {notifications.isPending ? (
            <p className="px-4 py-6 text-center text-sm text-ink-muted dark:text-slate-400">
              Cargando…
            </p>
          ) : items.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-ink-muted dark:text-slate-400">
              Sin notificaciones pendientes.
            </p>
          ) : (
            <ul className="divide-y divide-line dark:divide-slate-800">
              {items.map((n) => (
                <li
                  key={n.id}
                  className={`flex items-start gap-2 px-4 py-3 text-sm ${
                    n.read_at === null ? "bg-accent/5" : ""
                  }`}
                >
                  <span aria-hidden className="mt-0.5">
                    {KIND_ICON[n.kind]}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="break-words">{n.message}</p>
                    <p className="mt-0.5 text-xs text-ink-muted dark:text-slate-500">
                      {formatDate(n.fire_at)}
                    </p>
                  </div>
                  <button
                    className="shrink-0 rounded p-1 text-ink-muted hover:bg-surface hover:text-red-500 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-red-400"
                    title="Descartar notificación"
                    aria-label="Descartar notificación"
                    disabled={dismiss.isPending}
                    onClick={() => dismiss.mutate(n.id)}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
