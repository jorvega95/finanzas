import { useEffect, useId, type ReactNode } from "react";
import { createPortal } from "react-dom";
import Icon from "./Icon";

// Modales abiertos, el último arriba: con modales anidados (p. ej. una
// confirmación sobre un formulario, GLO-09) Escape cierra solo el de arriba.
const openStack: string[] = [];

const SIZE_CLASSES = {
  sm: "max-w-sm",
  lg: "max-w-2xl",
  xl: "max-w-3xl",
};

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  size?: keyof typeof SIZE_CLASSES;
}

export default function Modal({ open, onClose, title, children, size = "sm" }: ModalProps) {
  const id = useId();
  const titleId = `${id}-title`;

  useEffect(() => {
    if (!open) return;
    openStack.push(id);
    return () => {
      openStack.splice(openStack.lastIndexOf(id), 1);
    };
  }, [open, id]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && openStack.at(-1) === id) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, id]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-3 backdrop-blur-sm sm:px-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`card max-h-[90dvh] w-full overflow-y-auto ${SIZE_CLASSES[size]} p-4 shadow-2xl sm:p-6`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <h2 id={titleId} className="text-base font-semibold tracking-tight">
            {title}
          </h2>
          <button
            aria-label="Cerrar"
            className="-mr-2 -mt-1 rounded-lg p-1.5 text-ink-subtle transition hover:bg-muted hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            onClick={onClose}
          >
            <Icon name="x" />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
