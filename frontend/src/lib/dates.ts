// GLO-02: las fechas de negocio son strings ISO `YYYY-MM-DD` (sin hora/tz).
// Parsear siempre como fecha local, nunca con `new Date("YYYY-MM-DD")` (UTC shift).
import { parse } from "date-fns";

export function parseBusinessDate(iso: string): Date {
  return parse(iso, "yyyy-MM-dd", new Date());
}
