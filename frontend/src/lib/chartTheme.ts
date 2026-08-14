// Tokens de color para las gráficas (recharts), sensibles al tema light/dark.
// Recharts pinta ejes, leyendas y tooltips con grises fijos pensados para fondo
// claro; sobre `dark:bg-slate-900` quedan casi ilegibles. Aquí centralizamos los
// colores para que todas las gráficas de la app usen los mismos tokens de texto
// (el texto nunca hereda el color de la serie: la identidad la da la marca).
import type { CSSProperties } from "react";
import { useTheme } from "./theme";

export interface ChartTheme {
  /** Texto de ticks de ejes y etiquetas de datos. */
  tick: string;
  /** Línea del eje y de las marcas de tick. */
  axis: string;
  /** Rejilla de fondo. */
  grid: string;
  /** Texto de la leyenda. */
  legend: string;
  /** Estilos del tooltip. */
  tooltip: {
    contentStyle: CSSProperties;
    labelStyle: CSSProperties;
    itemStyle: CSSProperties;
  };
  /** Cursor del tooltip en gráficas de barras (rectángulo resaltado). */
  cursorFill: { fill: string };
  /** Cursor del tooltip en gráficas de línea/área. */
  cursorLine: { stroke: string; strokeWidth: number };
}

const LIGHT: ChartTheme = {
  tick: "#475569", // slate-600
  axis: "#cbd5e1", // slate-300
  grid: "#e2e8f0", // slate-200
  legend: "#334155", // slate-700
  tooltip: {
    contentStyle: {
      backgroundColor: "#ffffff",
      border: "1px solid #cbd5e1",
      borderRadius: "0.5rem",
      boxShadow: "0 4px 12px rgb(15 23 42 / 0.08)",
      fontSize: 12,
    },
    labelStyle: { color: "#0f172a", fontWeight: 600 },
    itemStyle: { color: "#334155" },
  },
  cursorFill: { fill: "rgb(100 116 139 / 0.12)" },
  cursorLine: { stroke: "#94a3b8", strokeWidth: 1 },
};

const DARK: ChartTheme = {
  tick: "#cbd5e1", // slate-300
  axis: "#475569", // slate-600
  grid: "#334155", // slate-700
  legend: "#e2e8f0", // slate-200
  tooltip: {
    contentStyle: {
      backgroundColor: "#1e293b", // slate-800
      border: "1px solid #475569",
      borderRadius: "0.5rem",
      boxShadow: "0 4px 12px rgb(0 0 0 / 0.4)",
      fontSize: 12,
    },
    labelStyle: { color: "#f1f5f9", fontWeight: 600 },
    itemStyle: { color: "#cbd5e1" },
  },
  cursorFill: { fill: "rgb(148 163 184 / 0.15)" },
  cursorLine: { stroke: "#64748b", strokeWidth: 1 },
};

export function useChartTheme(): ChartTheme {
  return useTheme().theme === "dark" ? DARK : LIGHT;
}
