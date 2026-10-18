// Tokens de color para las gráficas (recharts), sensibles al tema light/dark.
// Recharts pinta ejes, leyendas y tooltips con grises fijos pensados para fondo
// claro; sobre el fondo negro del dark mode quedan casi ilegibles. Aquí centralizamos los
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
  tick: "#4d4b46",
  axis: "#bfbbb1",
  grid: "#e2dfd8",
  legend: "#2e2d2a",
  tooltip: {
    contentStyle: {
      backgroundColor: "#fbfaf8",
      border: "1px solid #d8d5cd",
      borderRadius: "0.625rem",
      boxShadow: "0 8px 24px rgb(18 18 17 / 0.10)",
      fontSize: 12,
    },
    labelStyle: { color: "#121211", fontWeight: 600 },
    itemStyle: { color: "#2e2d2a" },
  },
  cursorFill: { fill: "rgb(18 18 17 / 0.06)" },
  cursorLine: { stroke: "#77746c", strokeWidth: 1 },
};

const DARK: ChartTheme = {
  tick: "#a8a8a5",
  axis: "#363636",
  grid: "#1f1f1f",
  legend: "#d6d6d3",
  tooltip: {
    contentStyle: {
      backgroundColor: "#161616",
      border: "1px solid #2e2e2e",
      borderRadius: "0.625rem",
      boxShadow: "0 8px 24px rgb(0 0 0 / 0.6)",
      fontSize: 12,
    },
    labelStyle: { color: "#f5f5f4", fontWeight: 600 },
    itemStyle: { color: "#d6d6d3" },
  },
  cursorFill: { fill: "rgb(255 255 255 / 0.05)" },
  cursorLine: { stroke: "#5a5a57", strokeWidth: 1 },
};

export function useChartTheme(): ChartTheme {
  return useTheme().theme === "dark" ? DARK : LIGHT;
}
