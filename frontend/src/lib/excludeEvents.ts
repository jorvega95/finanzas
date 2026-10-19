// EVT-04: preferencia "excluir eventos" del dashboard y presupuestos, recordada
// por usuario en este navegador. Si el almacenamiento falla, vale `false`.
import { useEffect, useState } from "react";

const STORAGE_KEY = "finanzas.excludeEvents";

function read(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function useExcludeEvents(): [boolean, (value: boolean) => void] {
  const [value, setValue] = useState(read);
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
    } catch {
      // Sin almacenamiento la preferencia dura solo esta visita.
    }
  }, [value]);
  return [value, setValue];
}
