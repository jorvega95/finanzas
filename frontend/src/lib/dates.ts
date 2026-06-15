// GLO-02: las fechas de negocio son strings ISO `YYYY-MM-DD` (sin hora/tz).
// Parsear siempre como fecha local, nunca con `new Date("YYYY-MM-DD")` (UTC shift).
import { parse } from "date-fns";

export function parseBusinessDate(iso: string): Date {
  return parse(iso, "yyyy-MM-dd", new Date());
}

/**
 * Convierte un string ISO `YYYY-MM-DD` al formato de display `dd/MM/yyyy`.
 * Usa solo manipulación de string — sin parseo de fecha, sin desfase UTC.
 * Para inputs tipo date o llamadas a la API, siempre usar el ISO original.
 */
export function formatDate(iso: string): string {
  if (!iso || iso.length < 10) return iso ?? "";
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
}
