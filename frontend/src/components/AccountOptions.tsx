// <option>s de cuentas agrupadas por tipo, como en la página de Cuentas.
// Se usa en Transacciones y Suscripciones.
import type { AccountBehavior, AccountOut } from "../api/accounts";

const ACCOUNT_GROUPS: { label: string; behaviors: AccountBehavior[] }[] = [
  { label: "Efectivo y cuentas", behaviors: ["cash", "debit", "prepaid"] },
  { label: "Ahorro", behaviors: ["savings"] },
  { label: "Tarjetas de crédito", behaviors: ["credit"] },
  { label: "Préstamos", behaviors: ["loan"] }, // TAR-11
];

export default function AccountOptions({
  accounts,
  exclude,
  baseCurrency,
}: {
  accounts: AccountOut[];
  exclude?: string;
  baseCurrency: string;
}) {
  return (
    <>
      {ACCOUNT_GROUPS.map((group) => {
        const items = accounts.filter(
          (a) => a.id !== exclude && a.behavior && group.behaviors.includes(a.behavior),
        );
        if (items.length === 0) return null;
        return (
          <optgroup key={group.label} label={group.label}>
            {items.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {a.currency !== baseCurrency ? ` (${a.currency})` : ""}
              </option>
            ))}
          </optgroup>
        );
      })}
    </>
  );
}
