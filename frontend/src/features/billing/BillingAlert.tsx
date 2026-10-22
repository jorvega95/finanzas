// FAC-09: aviso del Dashboard con los cobros por facturar y el siguiente mes
// por declarar o pagar. No se muestra si no hay nada pendiente.
import { Link } from "react-router-dom";
import { useBillingPeriods, useBillingSummary } from "../../api/billing";
import Icon from "../../components/ui/Icon";
import { formatDate } from "../../lib/dates";
import { monthLabel } from "./shared";

export default function BillingAlert() {
  const summary = useBillingSummary();
  const periods = useBillingPeriods();
  const pending = summary.data?.counts.pending_invoice ?? 0;
  const next = (periods.data ?? [])
    .filter((p) => p.status === "to_declare" || p.status === "to_pay")
    .sort((a, b) => a.period.localeCompare(b.period))[0];
  if (pending === 0 && !next) return null;

  const parts = [
    pending > 0 && `${pending} ${pending === 1 ? "cobro por facturar" : "cobros por facturar"}`,
    next &&
      `${next.status === "to_pay" ? "pagar" : "declarar"} ${monthLabel(next.period)} ${
        next.is_overdue ? "venció el" : "antes del"
      } ${formatDate(next.payment_deadline ?? next.deadline)}`,
  ].filter(Boolean);

  return (
    <Link
      to="/facturacion"
      className={`card flex items-center gap-3 p-4 text-sm transition hover:bg-muted/60 ${
        next?.is_overdue ? "border-red-500/40" : ""
      }`}
    >
      <span
        className={`grid size-8 shrink-0 place-items-center rounded-lg ${
          next?.is_overdue ? "bg-red-500/15 text-red-700 dark:text-red-300" : "bg-muted text-ink-muted"
        }`}
      >
        <Icon name="receipt" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="font-medium">Facturación: </span>
        {parts.join(" · ")}
      </span>
      <Icon name="externalLink" className="size-3.5 text-ink-subtle" />
    </Link>
  );
}
