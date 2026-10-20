// EVT-04: preferencia "excluir eventos" del dashboard y presupuestos, recordada
// por usuario en este navegador. Si el almacenamiento falla, vale `false`.
import { useStoredToggle } from "./storedToggle";

export function useExcludeEvents(): [boolean, (value: boolean) => void] {
  return useStoredToggle("finanzas.excludeEvents");
}
