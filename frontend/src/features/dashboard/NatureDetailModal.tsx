// DSH-06: drill-down de una naturaleza del pie "Por naturaleza".
// Read-only: total del mes, reparto por categoría raíz (CAT-06) y los
// movimientos que lo componen (gastos directos + cuotas MSI, MSI-03).
import { useNatureDetail } from "../../api/dashboard";
import Modal from "../../components/ui/Modal";
import Spinner from "../../components/ui/Spinner";
import { formatDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import { CHART_COLORS, NATURE_LABELS, formatMonth } from "./nature";

interface Props {
  month: string;
  /** `null` cierra el modal. */
  nature: string | null;
  currency: string;
  onClose: () => void;
}

export default function NatureDetailModal({ month, nature, currency, onClose }: Props) {
  const detail = useNatureDetail(month, nature);
  const data = detail.data;
  const total = Number(data?.total ?? 0);

  return (
    <Modal
      open={nature !== null}
      onClose={onClose}
      size="lg"
      title={`Gasto ${NATURE_LABELS[nature ?? ""] ?? nature ?? ""} · ${formatMonth(month)}`}
    >
      {detail.isPending ? (
        <div className="flex justify-center py-10">
          <Spinner className="size-7" />
        </div>
      ) : detail.error ? (
        <p className="py-6 text-sm text-red-600 dark:text-red-400">{detail.error.message}</p>
      ) : !data || data.items.length === 0 ? (
        <p className="py-6 text-sm text-ink-muted dark:text-slate-400">
          Sin gastos de esta naturaleza en el mes.
        </p>
      ) : (
        <div className="max-h-[70vh] space-y-6 overflow-y-auto pr-1">
          <div className="flex items-baseline justify-between">
            <p className="text-2xl font-semibold">{formatMoney(data.total, currency)}</p>
            <p className="text-xs text-ink-muted dark:text-slate-400">
              {data.items.length} {data.items.length === 1 ? "movimiento" : "movimientos"}
            </p>
          </div>

          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted dark:text-slate-400">
              Por categoría
            </h3>
            <ul className="space-y-2">
              {data.by_category.map((row, index) => {
                const share = total > 0 ? Number(row.total) / total : 0;
                return (
                  <li key={row.category_id ?? "none"}>
                    <div className="mb-1 flex items-center justify-between text-sm">
                      <span className="font-medium">{row.category_name}</span>
                      <span className="text-ink-muted dark:text-slate-400">
                        {formatMoney(row.total, currency)}
                        <span className="ml-2 tabular-nums">{Math.round(share * 100)}%</span>
                      </span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.round(share * 100)}%`,
                          backgroundColor: CHART_COLORS[index % CHART_COLORS.length],
                        }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>

          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted dark:text-slate-400">
              Movimientos
            </h3>
            <ul className="divide-y divide-line dark:divide-slate-800">
              {data.items.map((item) => (
                <li key={`${item.kind}-${item.id}`} className="flex items-start gap-3 py-2 text-sm">
                  <span className="w-16 shrink-0 text-xs text-ink-muted dark:text-slate-400">
                    {formatDate(item.date)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">
                      {item.kind === "msi_quota" && (
                        <span
                          className="mr-1.5 rounded-full bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                          title="Cuota de meses sin intereses"
                        >
                          MSI {item.installment_number}/{item.installment_total}
                        </span>
                      )}
                      {item.description || item.category_name}
                    </span>
                    <span className="block truncate text-xs text-ink-muted dark:text-slate-400">
                      {item.category_name}
                      {item.payment_method_name && ` · ${item.payment_method_name}`}
                    </span>
                  </span>
                  <span className="shrink-0 text-right">
                    <span className="block font-medium tabular-nums">
                      {formatMoney(item.amount, currency)}
                    </span>
                    {item.original_amount && (
                      <span className="block text-xs text-ink-muted dark:text-slate-400">
                        {formatMoney(item.original_amount, item.currency)}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </Modal>
  );
}
