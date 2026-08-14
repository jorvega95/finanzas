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
