// Tarjeta desplegable: el encabezado (título + descripción) siempre visible y el
// contenido se muestra al expandir. Usa <details>, así el estado interno de los
// formularios se conserva aunque se cierre.
import type { ReactNode } from "react";
import Icon from "./Icon";

interface CollapsibleCardProps {
  title: ReactNode;
  description?: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  children: ReactNode;
}

export default function CollapsibleCard({
  title,
  description,
  defaultOpen = false,
  className = "",
  children,
}: CollapsibleCardProps) {
  return (
    <details className={`card group ${className}`} open={defaultOpen}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-xl p-5 transition hover:bg-muted/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent [&::-webkit-details-marker]:hidden">
        <div className="min-w-0">
          <h2 className="text-base font-semibold tracking-tight">{title}</h2>
          {description && <p className="mt-0.5 text-xs text-ink-muted">{description}</p>}
        </div>
        <Icon
          name="chevronDown"
          className="size-4 shrink-0 text-ink-subtle transition group-open:rotate-180"
        />
      </summary>
      <div className="border-t border-line p-5">{children}</div>
    </details>
  );
}
