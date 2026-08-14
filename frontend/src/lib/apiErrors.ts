// GLO-06: los 422 de FastAPI llegan como lista de errores de Pydantic en inglés
// (`detail: [{loc, msg, type, ctx}]`). La UI es es-MX: se traducen a una frase
// accionable por campo. Fallback: `msg` original.
interface ValidationError {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
  ctx?: Record<string, unknown>;
}

// Etiquetas con artículo incluido: se concatenan con el predicado.
const FIELD_LABELS: Record<string, string> = {
  amount: "El monto",
  amount_paid: "El monto pagado",
  paid_amount: "El monto pagado",
  price: "El precio",
  unit_cost: "El costo unitario",
  quantity: "La cantidad",
  description: "La descripción",
  name: "El nombre",
  date: "La fecha",
  start_date: "La fecha de inicio",
  end_date: "La fecha de fin",
  due_date: "La fecha límite",
  currency: "La moneda",
  category_id: "La categoría",
  payment_method_id: "El método de pago",
  payment_method_to_id: "El método destino",
  months: "El número de meses",
  month_day: "El día del mes",
  max_occurrences: "El número de ocurrencias",
  alert_threshold: "El umbral de alerta",
  statement_day: "El día de corte",
  due_day: "El día de pago",
  last4: "Los últimos 4 dígitos",
  symbol: "El símbolo",
  email: "El correo",
  role: "El rol",
  frequency: "La frecuencia",
  type: "El tipo",
};

function fieldLabel(loc: ValidationError["loc"]): string {
  const segments = (loc ?? []).filter(
    (s): s is string => typeof s === "string" && !["body", "query", "path", "header"].includes(s),
  );
  const field = segments[segments.length - 1];
  if (!field) return "El dato";
  return FIELD_LABELS[field] ?? `El campo "${field}"`;
}

function num(value: unknown): string {
  return typeof value === "number" || typeof value === "string" ? String(value) : "";
}

function describe(error: ValidationError): string {
  const label = fieldLabel(error.loc);
  const ctx = error.ctx ?? {};
  switch (error.type) {
    case "missing":
      return `${label} es obligatorio.`;
    case "greater_than":
      return `${label} debe ser mayor a ${num(ctx.gt)}.`;
    case "greater_than_equal":
      return `${label} no puede ser menor a ${num(ctx.ge)}.`;
    case "less_than":
      return `${label} debe ser menor a ${num(ctx.lt)}.`;
    case "less_than_equal":
      return `${label} no puede ser mayor a ${num(ctx.le)}.`;
    case "string_too_short":
      return ctx.min_length === 1
        ? `${label} no puede estar vacío.`
        : `${label} debe tener al menos ${num(ctx.min_length)} caracteres.`;
    case "string_too_long":
      return `${label} no puede exceder ${num(ctx.max_length)} caracteres.`;
    case "string_pattern_mismatch":
      return `${label} tiene un formato inválido.`;
    case "decimal_max_places":
      return `${label} admite máximo ${num(ctx.decimal_places)} decimales.`;
    case "decimal_max_digits":
    case "decimal_whole_digits":
      return `${label} excede el máximo permitido.`;
    case "enum":
      return `${label} no es una opción válida.`;
    case "value_error":
      // Los `ValueError` de los validadores propios ya vienen en español.
      return (error.msg ?? "").replace(/^Value error,\s*/, "") || `${label} no es válido.`;
    default:
      return `${label} no es válido.`;
  }
}

/** Traduce el `detail` de un 422; `null` si no tiene esa forma. */
export function translateValidationErrors(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) return null;
  const messages = detail
    .filter((e): e is ValidationError => typeof e === "object" && e !== null)
    .map(describe);
  if (messages.length === 0) return null;
  return [...new Set(messages)].join(" ");
}
