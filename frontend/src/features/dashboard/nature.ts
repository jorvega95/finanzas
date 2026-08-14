// Tokens compartidos por los widgets del dashboard (CAT-03, DSH-03/06).
export const CHART_COLORS = [
  "#0d9488",
  "#f59e0b",
  "#6366f1",
  "#ef4444",
  "#10b981",
  "#8b5cf6",
  "#f97316",
  "#06b6d4",
];

export const NATURE_LABELS: Record<string, string> = {
  fixed: "Fijo",
  variable: "Variable",
  discretionary: "Discrecional",
};

/** "2026-07" → "julio 2026". */
export function formatMonth(month: string): string {
  const [year, monthNumber] = month.split("-").map(Number);
  return new Intl.DateTimeFormat("es-MX", { month: "long", year: "numeric" }).format(
    new Date(year, monthNumber - 1, 1),
  );
}
