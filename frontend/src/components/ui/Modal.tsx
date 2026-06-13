import { useEffect, type ReactNode } from "react";

const SIZE_CLASSES = {
  sm: "max-w-sm",
  lg: "max-w-2xl",
};

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  size?: keyof typeof SIZE_CLASSES;
}

export default function Modal({ open, onClose, title, children, size = "sm" }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        className={`card w-full ${SIZE_CLASSES[size]} p-6 shadow-xl`}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="modal-title" className="mb-5 font-semibold">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}
