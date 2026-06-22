// Throbber reutilizable. Tamaño vía `className` (p. ej. "size-7").
export default function Spinner({ className = "size-5" }: { className?: string }) {
  return (
    <svg
      className={`animate-spin text-accent ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      role="status"
      aria-label="Cargando"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}
