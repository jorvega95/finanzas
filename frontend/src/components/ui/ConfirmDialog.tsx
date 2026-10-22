import type { ReactNode } from "react";
import Modal from "./Modal";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** Qué se afecta y qué pasa al confirmar. */
  children: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onClose: () => void;
  pending?: boolean;
  error?: string | null;
  /** `danger` (default) para acciones destructivas; `primary` para las reversibles. */
  tone?: "danger" | "primary";
}

/** GLO-09: confirmación previa a una acción delicada de un solo clic. */
export default function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  onConfirm,
  onClose,
  pending = false,
  error,
  tone = "danger",
}: ConfirmDialogProps) {
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div className="space-y-4">
        <div className="space-y-2 text-sm">{children}</div>
        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Volver
          </button>
          <button
            type="button"
            className={tone === "danger" ? "btn-danger" : "btn-primary"}
            disabled={pending}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}
