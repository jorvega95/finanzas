// GLO-10: avisos breves del resultado de una acción (guardar, subir un
// archivo, registrar un pago). Se apilan abajo a la derecha y se cierran solos.
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import Icon from "./Icon";

type Tone = "success" | "error";

interface ToastItem {
  id: number;
  tone: Tone;
  message: string;
}

interface ToastApi {
  success: (message: string) => void;
  error: (message: string) => void;
}

const DURATION_MS = { success: 3500, error: 6000 };

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((all) => all.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (tone: Tone, message: string) => {
      const id = nextId.current++;
      setItems((all) => [...all.slice(-3), { id, tone, message }]);
      setTimeout(() => dismiss(id), DURATION_MS[tone]);
    },
    [dismiss],
  );

  const [api] = useState<ToastApi>(() => ({
    success: (m) => push("success", m),
    error: (m) => push("error", m),
  }));

  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(
        <div
          aria-live="polite"
          className="pointer-events-none fixed inset-x-4 bottom-4 z-[60] flex flex-col items-end gap-2 sm:left-auto sm:w-96"
        >
          {items.map((t) => (
            <div
              key={t.id}
              role={t.tone === "error" ? "alert" : "status"}
              className={`pointer-events-auto flex w-full items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm shadow-lg ${
                t.tone === "success"
                  ? "border-emerald-500/30 bg-surface text-ink"
                  : "border-red-500/40 bg-surface text-ink"
              }`}
            >
              <Icon
                name={t.tone === "success" ? "check" : "alert"}
                className={`mt-0.5 size-4 ${
                  t.tone === "success"
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-red-600 dark:text-red-400"
                }`}
              />
              <p className="min-w-0 flex-1 break-words">{t.message}</p>
              <button
                aria-label="Cerrar aviso"
                className="-mr-1 rounded p-0.5 text-ink-subtle hover:bg-muted hover:text-ink"
                onClick={() => dismiss(t.id)}
              >
                <Icon name="x" className="size-3.5" />
              </button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast requiere <ToastProvider>");
  return ctx;
}
