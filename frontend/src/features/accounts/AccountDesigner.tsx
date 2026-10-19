// TAR-08: editor del diseño de la cuenta — color base (paleta o libre) y/o una
// imagen del frente, con vista previa en vivo. La imagen se recorta a la
// proporción de tarjeta y se comprime en el navegador antes de enviarse.
import { useRef, useState, type ChangeEvent } from "react";
import Icon from "../../components/ui/Icon";
import type { AccountBehavior } from "../../api/accounts";
import AccountVisual, { CARD_RATIO, defaultColorFor, looksLikeCard } from "./AccountVisual";

export interface AccountDesign {
  color: string | null;
  image: string | null;
}

const PRESETS: { name: string; color: string }[] = [
  { name: "Grafito", color: "#1f1f1f" },
  { name: "Negro", color: "#050505" },
  { name: "Plata", color: "#a9abae" },
  { name: "Platino", color: "#d9d6cf" },
  { name: "Oro", color: "#b8975a" },
  { name: "Azul marino", color: "#072146" },
  { name: "Azul", color: "#1464f4" },
  { name: "Turquesa", color: "#0095a8" },
  { name: "Verde", color: "#00754a" },
  { name: "Morado", color: "#820ad1" },
  { name: "Rosa", color: "#e8457c" },
  { name: "Rojo", color: "#d4001a" },
  { name: "Vino", color: "#6e0f1f" },
  { name: "Naranja", color: "#ff6a13" },
];

// Máximo aceptado por el backend (TAR-08).
const MAX_DATA_URL = 1_000_000;
const OUT_WIDTH = 1000;

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("No se pudo leer la imagen"));
    };
    img.src = url;
  });
}

/** Recorte "cover" centrado a proporción de tarjeta + JPEG comprimido. */
async function toCardDataUrl(file: File): Promise<string> {
  const img = await loadImage(file);
  const outW = Math.min(OUT_WIDTH, img.naturalWidth);
  const outH = Math.round(outW / CARD_RATIO);
  const srcRatio = img.naturalWidth / img.naturalHeight;
  let sw = img.naturalWidth;
  let sh = img.naturalHeight;
  if (srcRatio > CARD_RATIO) sw = sh * CARD_RATIO;
  else sh = sw / CARD_RATIO;
  const sx = (img.naturalWidth - sw) / 2;
  const sy = (img.naturalHeight - sh) / 2;

  const canvas = document.createElement("canvas");
  canvas.width = outW;
  canvas.height = outH;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Tu navegador no permite procesar imágenes");
  ctx.drawImage(img, sx, sy, sw, sh, 0, 0, outW, outH);

  for (const quality of [0.86, 0.75, 0.6, 0.45]) {
    const url = canvas.toDataURL("image/jpeg", quality);
    if (url.length <= MAX_DATA_URL) return url;
  }
  throw new Error("La imagen es demasiado grande incluso comprimida");
}

interface AccountDesignerProps {
  value: AccountDesign;
  onChange: (next: AccountDesign) => void;
  preview: {
    name: string;
    bank: string;
    network: string;
    last4: string;
    currency: string;
    behavior: AccountBehavior | null;
  };
}

export default function AccountDesigner({ value, onChange, preview }: AccountDesignerProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const current = value.color ?? defaultColorFor(preview.behavior, preview.last4);
  const isCard = looksLikeCard(preview.behavior, preview.last4);

  async function handleFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("Elige un archivo de imagen (JPG, PNG o WebP).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onChange({ ...value, image: await toCardDataUrl(file) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo procesar la imagen");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-5 sm:grid-cols-[minmax(0,17rem)_1fr]">
      <div className="space-y-2">
        <AccountVisual {...preview} color={value.color} image={value.image} />
        <p className="text-center text-xs text-ink-subtle">Vista previa</p>
      </div>

      <div className="space-y-4">
        <div>
          <span className="label">Color</span>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => {
              const selected = !value.image && current.toLowerCase() === p.color.toLowerCase();
              return (
                <button
                  key={p.color}
                  type="button"
                  title={p.name}
                  aria-label={`Color ${p.name}`}
                  aria-pressed={selected}
                  onClick={() => onChange({ color: p.color, image: null })}
                  className={`size-7 rounded-full ring-1 ring-black/15 transition hover:scale-110 dark:ring-white/15 ${
                    selected ? "outline-2 outline-offset-2 outline-accent" : ""
                  }`}
                  style={{ background: p.color }}
                />
              );
            })}
            <label
              title="Color personalizado"
              className="relative grid size-7 cursor-pointer place-items-center rounded-full bg-[conic-gradient(#f43f5e,#f59e0b,#84cc16,#06b6d4,#6366f1,#d946ef,#f43f5e)] ring-1 ring-black/15 transition hover:scale-110"
            >
              <span className="sr-only">Color personalizado</span>
              <input
                type="color"
                className="absolute inset-0 size-full cursor-pointer opacity-0"
                value={current}
                onChange={(e) => onChange({ color: e.target.value, image: null })}
              />
            </label>
          </div>
          <p className="mt-1.5 font-mono text-xs text-ink-subtle">{current.toUpperCase()}</p>
        </div>

        <div>
          <span className="label">{isCard ? "Imagen del frente (opcional)" : "Imagen (opcional)"}</span>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn-secondary"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
            >
              <Icon name="image" />
              {busy ? "Procesando…" : value.image ? "Cambiar imagen" : "Subir imagen"}
            </button>
            {value.image && (
              <button
                type="button"
                className="btn-ghost text-red-600 dark:text-red-400"
                onClick={() => onChange({ ...value, image: null })}
              >
                Quitar
              </button>
            )}
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              onChange={handleFile}
            />
          </div>
          {/* TDC-01: la imagen nunca debe exponer datos sensibles. */}
          {isCard && (
          <p className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-900 dark:text-amber-200">
            Usa solo el diseño del frente: tapa o recorta el número completo, el CVV y la fecha
            de vencimiento. Solo mostramos los últimos 4 dígitos.
          </p>
          )}
          {error && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{error}</p>}
        </div>
      </div>
    </div>
  );
}
