// DSH-08: la tendencia de DSH-03 en grande, por mes o por semana.
import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  useTrendDetail,
  type TrendGranularity,
  type TrendRangePoint,
} from "../../api/dashboard";
import { useChartTheme } from "../../lib/chartTheme";
import { formatMoney } from "../../lib/money";
import { parseBusinessDate } from "../../lib/dates";
import Modal from "../../components/ui/Modal";
import Spinner from "../../components/ui/Spinner";

const MONTHS_ES = [
  "ene",
  "feb",
  "mar",
  "abr",
  "may",
  "jun",
  "jul",
  "ago",
  "sep",
  "oct",
  "nov",
  "dic",
];

function shortDay(iso: string): string {
  const d = parseBusinessDate(iso);
  return `${d.getDate()} ${MONTHS_ES[d.getMonth()]}`;
}

function periodLabel(
  p: TrendRangePoint,
  granularity: TrendGranularity,
): string {
  if (granularity === "month") {
    const d = parseBusinessDate(p.start);
    return `${MONTHS_ES[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`;
  }
  return shortDay(p.start);
}

function tooltipTitle(
  p: TrendRangePoint,
  granularity: TrendGranularity,
): string {
  return granularity === "month"
    ? periodLabel(p, "month")
    : `${shortDay(p.start)} – ${shortDay(p.end)}`;
}

const compact = new Intl.NumberFormat("es-MX", {
  notation: "compact",
  maximumFractionDigits: 1,
});

function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex rounded-lg border border-line p-0.5"
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1 text-xs font-medium transition ${
            o.value === value
              ? "bg-accent text-white"
              : "text-ink-muted hover:text-ink"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

interface Props {
  open: boolean;
  onClose: () => void;
  month: string;
  currency: string;
  excludeEvents: boolean;
}

export default function TrendModal({
  open,
  onClose,
  month,
  currency,
  excludeEvents,
}: Props) {
  const chart = useChartTheme();
  const [granularity, setGranularity] = useState<TrendGranularity>("week");
  const [months, setMonths] = useState(6);
  const query = useTrendDetail(month, granularity, months, excludeEvents, open);
  const points = query.data ?? [];
  const rows = points.map((p) => ({
    ...p,
    label: periodLabel(p, granularity),
    income: Number(p.income),
    expenses: Number(p.expenses),
    net: Number(p.net),
  }));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Tendencia de ingresos y gastos"
      size="2xl"
    >
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented
          label="Agrupar por"
          value={granularity}
          onChange={setGranularity}
          options={[
            { value: "week", label: "Semanal" },
            { value: "month", label: "Mensual" },
          ]}
        />
        <Segmented
          label="Periodo"
          value={months}
          onChange={setMonths}
          options={[
            { value: 3, label: "3 meses" },
            { value: 6, label: "6 meses" },
            { value: 12, label: "12 meses" },
          ]}
        />
      </div>
      {query.isLoading ? (
        <div className="flex h-[55dvh] items-center justify-center">
          <Spinner />
        </div>
      ) : (
        <div className="h-[55dvh] min-h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows}>
              <CartesianGrid vertical={false} stroke={chart.grid} />
              <XAxis
                dataKey="label"
                fontSize={11}
                tick={{ fill: chart.tick }}
                stroke={chart.axis}
                interval="preserveStartEnd"
                minTickGap={18}
              />
              <YAxis
                fontSize={11}
                width={52}
                tick={{ fill: chart.tick }}
                stroke={chart.axis}
                tickFormatter={(v) => compact.format(Number(v))}
              />
              <Tooltip
                cursor={chart.cursorLine}
                {...chart.tooltip}
                labelFormatter={(_, payload) => {
                  const p = payload?.[0]?.payload as
                    TrendRangePoint | undefined;
                  return p ? tooltipTitle(p, granularity) : "";
                }}
                formatter={(v) => formatMoney(String(v), currency)}
                itemSorter={() => 0}
              />
              <Legend
                formatter={(value) => (
                  <span style={{ color: chart.legend }}>{value}</span>
                )}
              />
              <Line
                type="monotone"
                dataKey="income"
                name="Ingresos"
                stroke="#10b981"
                strokeWidth={2}
                dot={rows.length <= 14}
              />
              <Line
                type="monotone"
                dataKey="expenses"
                name="Gastos"
                stroke="#ef4444"
                strokeWidth={2}
                dot={rows.length <= 14}
              />
              <Line
                type="monotone"
                dataKey="net"
                name="Neto"
                stroke={chart.tick}
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-3 text-xs text-ink-muted">
        {granularity === "week"
          ? "Semanas de lunes a domingo; la primera y la última pueden ser parciales (recortadas al periodo)."
          : "Mes calendario."}{" "}
        Gasto devengado; las transferencias no cuentan.
      </p>
    </Modal>
  );
}
