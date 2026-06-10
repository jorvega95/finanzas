// GLO-01: montos como enteros (centavos) o strings decimales del backend.
// Nunca aritmética float sobre dinero. Formateo:
export function formatMoney(amount: string | number, currency = "MXN"): string {
  return new Intl.NumberFormat("es-MX", { style: "currency", currency }).format(
    Number(amount),
  );
}
