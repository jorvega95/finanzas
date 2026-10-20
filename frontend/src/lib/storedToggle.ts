// Preferencias booleanas de vista (EVT-04, PRO-08) recordadas por usuario en
// este navegador. Si el almacenamiento falla, vale el default y dura la visita.
import { useEffect, useState } from "react";

export function useStoredToggle(key: string, fallback = false): [boolean, (value: boolean) => void] {
  const [value, setValue] = useState(() => {
    try {
      const stored = localStorage.getItem(key);
      return stored === null ? fallback : stored === "1";
    } catch {
      return fallback;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, value ? "1" : "0");
    } catch {
      // Sin almacenamiento la preferencia dura solo esta visita.
    }
  }, [key, value]);
  return [value, setValue];
}
