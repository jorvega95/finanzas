// GLO-01: montos como enteros (centavos) o strings decimales del backend.
// Nunca aritmética float sobre dinero. Formateo:
export function formatMoney(amount: string | number, currency = "MXN"): string {
  return new Intl.NumberFormat("es-MX", { style: "currency", currency }).format(
    Number(amount),
  );
}

// GLO-01: sin aritmética float. Un monto es positivo si es decimal bien formado
// y tiene al menos un dígito significativo (descarta "0", "0.00", "", "-5").
export function isPositiveAmount(value: string): boolean {
  const trimmed = value.trim();
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return false;
  return /[1-9]/.test(trimmed);
}

// GLO-01: "−123.45" ⇄ centavos en BigInt (exacto, sin float).
function toCents(value: string): bigint {
  const m = /^(-)?(\d+)(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!m) return 0n;
  const cents = BigInt(m[2]) * 100n + BigInt((m[3] ?? "").padEnd(2, "0"));
  return m[1] ? -cents : cents;
}

function fromCents(cents: bigint): string {
  const sign = cents < 0n ? "-" : "";
  const abs = cents < 0n ? -cents : cents;
  return `${sign}${abs / 100n}.${String(abs % 100n).padStart(2, "0")}`;
}

/** Suma exacta de montos decimales (strings del backend). */
export function sumMoney(values: string[]): string {
  return fromCents(values.reduce((acc, v) => acc + toCents(v), 0n));
}

/** Diferencia exacta `a − b`. */
export function subtractMoney(a: string, b: string): string {
  return fromCents(toCents(a) - toCents(b));
}

export function isNegativeAmount(value: string): boolean {
  return toCents(value) < 0n;
}

/** TXN-13: tasa implícita `received / sent` con 4 decimales, solo para mostrar. */
export function impliedRate(received: string, sent: string): string | null {
  const s = toCents(sent);
  if (s <= 0n || !isPositiveAmount(received)) return null;
  const scaled = (toCents(received) * 10000n) / s;
  return `${scaled / 10000n}.${String(scaled % 10000n).padStart(4, "0")}`;
}
