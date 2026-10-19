// TAR-08: representación visual de una cuenta (proporción ISO/IEC 7810 ID-1,
// 85.6 × 53.98 mm) con el color o la imagen que eligió el usuario. Las tarjetas
// se pintan como plástico; efectivo, ahorro y billeteras como un tile con ícono.
// Solo se sobrepone `last4` — jamás PAN, CVV ni vencimiento (TDC-01).
import type { AccountBehavior } from "../../api/accounts";
import Icon, { type IconName } from "../../components/ui/Icon";

export const CARD_RATIO = 85.6 / 53.98;
export const DEFAULT_CARD_COLOR = "#1f1f1f";

// Color base por defecto para cuentas que no son plástico.
const TILE_DEFAULTS: Record<AccountBehavior, { color: string; icon: IconName; label: string }> = {
  cash: { color: "#1f6b47", icon: "banknote", label: "Efectivo" },
  savings: { color: "#0f4c75", icon: "piggy", label: "Ahorro" },
  debit: { color: "#33316b", icon: "wallet", label: "Billetera" },
  prepaid: { color: "#7a4b00", icon: "wallet", label: "Prepago" },
  credit: { color: DEFAULT_CARD_COLOR, icon: "card", label: "Crédito" },
};

/** TAR-02: se pinta como tarjeta si es crédito o trae datos de plástico. */
export function looksLikeCard(
  behavior: AccountBehavior | null | undefined,
  last4: string | null | undefined,
): boolean {
  return behavior === "credit" || !!last4;
}

export function defaultColorFor(
  behavior: AccountBehavior | null | undefined,
  last4: string | null | undefined,
): string {
  if (!behavior || looksLikeCard(behavior, last4)) return DEFAULT_CARD_COLOR;
  return TILE_DEFAULTS[behavior].color;
}

interface AccountVisualProps {
  name: string;
  bank?: string | null;
  network?: string | null;
  last4?: string | null;
  currency?: string;
  behavior?: AccountBehavior | null;
  color?: string | null;
  image?: string | null;
  inactive?: boolean;
  className?: string;
}

function parseHex(hex: string): [number, number, number] | null {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Mezcla hacia negro (amount<0) o blanco (amount>0). */
function shade(hex: string, amount: number): string {
  const rgb = parseHex(hex);
  if (!rgb) return hex;
  const target = amount < 0 ? 0 : 255;
  const t = Math.abs(amount);
  const mixed = rgb.map((c) => Math.round(c + (target - c) * t));
  return `rgb(${mixed[0]} ${mixed[1]} ${mixed[2]})`;
}

/** Luminancia relativa (WCAG) para decidir texto claro u oscuro. */
export function isLightColor(hex: string): boolean {
  const rgb = parseHex(hex);
  if (!rgb) return false;
  const [r, g, b] = rgb.map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45;
}

function NetworkMark({ network, light }: { network: string; light: boolean }) {
  const n = network.toLowerCase();
  if (n === "mastercard") {
    return (
      <svg viewBox="0 0 48 30" className="h-[22%] w-auto" aria-label="Mastercard">
        <circle cx="17" cy="15" r="13" fill="#eb001b" />
        <circle cx="31" cy="15" r="13" fill="#f79e1b" fillOpacity="0.9" />
        <path d="M24 4.2a13 13 0 0 1 0 21.6 13 13 0 0 1 0-21.6Z" fill="#ff5f00" />
      </svg>
    );
  }
  const label = n === "visa" ? "VISA" : n === "amex" ? "AMEX" : network.toUpperCase();
  return (
    <span
      className={`text-[clamp(0.8rem,4.2cqw,1.35rem)] font-bold tracking-tight ${
        n === "visa" ? "italic" : ""
      } ${light ? "text-black/80" : "text-white/95"}`}
    >
      {label}
    </span>
  );
}

function Chip() {
  return (
    <svg viewBox="0 0 40 30" className="h-full w-auto" aria-hidden>
      <defs>
        <linearGradient id="chip-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f3dfa2" />
          <stop offset="0.5" stopColor="#c9a959" />
          <stop offset="1" stopColor="#e8cf86" />
        </linearGradient>
      </defs>
      <rect x="0.5" y="0.5" width="39" height="29" rx="5" fill="url(#chip-g)" stroke="#a88a3d" strokeOpacity="0.5" />
      <path
        d="M0 10h12M0 20h12M28 10h12M28 20h12M12 0v30M28 0v30M12 15h16"
        stroke="#8a6f2c"
        strokeOpacity="0.45"
        strokeWidth="1"
        fill="none"
      />
    </svg>
  );
}

export default function AccountVisual({
  name,
  bank,
  network,
  last4,
  currency = "MXN",
  behavior,
  color,
  image,
  inactive = false,
  className = "",
}: AccountVisualProps) {
  const base = color && parseHex(color) ? color : defaultColorFor(behavior, last4);
  if (!looksLikeCard(behavior, last4)) {
    return (
      <AccountTile
        name={name}
        currency={currency}
        behavior={behavior ?? "debit"}
        base={base}
        image={image}
        inactive={inactive}
        className={className}
      />
    );
  }
  // Con imagen el texto va claro sobre un velo oscuro; con color, según luminancia.
  const light = !image && isLightColor(base);
  const text = light ? "text-black/85" : "text-white";
  const sub = light ? "text-black/55" : "text-white/70";

  return (
    <div
      className={`relative w-full select-none overflow-hidden rounded-[4.5%/7%] shadow-[0_10px_30px_-12px_rgb(0_0_0/0.55)] ring-1 ring-black/10 [container-type:inline-size] dark:ring-white/10 ${
        inactive ? "grayscale" : ""
      } ${className}`}
      style={{
        aspectRatio: CARD_RATIO,
        background: `radial-gradient(120% 90% at 0% 0%, ${shade(base, 0.18)} 0%, transparent 55%), linear-gradient(135deg, ${base} 0%, ${shade(base, -0.35)} 100%)`,
      }}
    >
      {image && (
        <>
          <img src={image} alt="" className="absolute inset-0 size-full object-cover" draggable={false} />
          <div className="absolute inset-0 bg-gradient-to-t from-black/55 via-black/5 to-black/35" />
        </>
      )}
      {/* Brillo sutil tipo plástico */}
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(115deg,transparent_35%,rgb(255_255_255/0.10)_48%,transparent_60%)]" />

      <div className="absolute inset-0 flex flex-col justify-between p-[6.5%]">
        <div className="flex items-start justify-between gap-2">
          <span className={`truncate text-[clamp(0.75rem,5cqw,1.25rem)] font-semibold tracking-tight ${text}`}>
            {bank || "Banco"}
          </span>
          <span className={`truncate text-right text-[clamp(0.6rem,3.4cqw,0.85rem)] font-medium ${sub}`}>
            {name}
          </span>
        </div>

        <div className="flex h-[17%] items-center gap-[3%]">
          <Chip />
          <svg viewBox="0 0 24 24" className={`h-[70%] w-auto ${sub}`} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
            <path d="M8.5 7.5a6 6 0 0 1 0 9" />
            <path d="M12 5a9.5 9.5 0 0 1 0 14" />
            <path d="M15.5 2.5a13 13 0 0 1 0 19" />
          </svg>
        </div>

        <div className="flex items-end justify-between gap-2">
          <span className={`font-mono text-[clamp(0.75rem,5.2cqw,1.3rem)] tracking-[0.18em] ${text}`}>
            •••• {last4 || "0000"}
          </span>
          {network && <NetworkMark network={network} light={light} />}
        </div>
      </div>

      {inactive && (
        <span className="absolute right-[6.5%] top-1/2 -translate-y-1/2 rounded-full bg-black/70 px-2.5 py-1 text-[11px] font-medium text-white">
          Inactiva
        </span>
      )}
    </div>
  );
}

function background(base: string): string {
  return `radial-gradient(120% 90% at 0% 0%, ${shade(base, 0.18)} 0%, transparent 55%), linear-gradient(135deg, ${base} 0%, ${shade(base, -0.35)} 100%)`;
}

/** Cuenta sin plástico (efectivo, ahorro, billetera): ícono, nombre y moneda. */
function AccountTile({
  name,
  currency,
  behavior,
  base,
  image,
  inactive,
  className,
}: {
  name: string;
  currency: string;
  behavior: AccountBehavior;
  base: string;
  image?: string | null;
  inactive: boolean;
  className: string;
}) {
  const light = !image && isLightColor(base);
  const text = light ? "text-black/85" : "text-white";
  const sub = light ? "text-black/55" : "text-white/70";
  const meta = TILE_DEFAULTS[behavior];
  return (
    <div
      className={`relative w-full select-none overflow-hidden rounded-[4.5%/7%] shadow-[0_10px_30px_-12px_rgb(0_0_0/0.55)] ring-1 ring-black/10 [container-type:inline-size] dark:ring-white/10 ${
        inactive ? "grayscale" : ""
      } ${className}`}
      style={{ aspectRatio: CARD_RATIO, background: background(base) }}
    >
      {image && (
        <>
          <img src={image} alt="" className="absolute inset-0 size-full object-cover" draggable={false} />
          <div className="absolute inset-0 bg-gradient-to-t from-black/55 via-black/5 to-black/35" />
        </>
      )}
      <div className="absolute inset-0 flex flex-col justify-between p-[6.5%]">
        <div className="flex items-start justify-between gap-2">
          <span
            className={`grid size-[18cqw] place-items-center rounded-[22%] ${
              light ? "bg-black/10" : "bg-white/15"
            } ${text}`}
          >
            <Icon name={meta.icon} className="size-[55%]" />
          </span>
          <span
            className={`rounded-full px-[3cqw] py-[0.8cqw] font-mono text-[clamp(0.6rem,3.4cqw,0.85rem)] font-semibold ${
              light ? "bg-black/10" : "bg-white/15"
            } ${text}`}
          >
            {currency}
          </span>
        </div>
        <div className="min-w-0">
          <p className={`text-[clamp(0.6rem,3.4cqw,0.85rem)] font-medium uppercase tracking-wider ${sub}`}>
            {meta.label}
          </p>
          <p className={`truncate text-[clamp(0.85rem,6.5cqw,1.6rem)] font-semibold tracking-tight ${text}`}>
            {name}
          </p>
        </div>
      </div>
      {inactive && (
        <span className="absolute right-[6.5%] top-1/2 -translate-y-1/2 rounded-full bg-black/70 px-2.5 py-1 text-[11px] font-medium text-white">
          Inactiva
        </span>
      )}
    </div>
  );
}
