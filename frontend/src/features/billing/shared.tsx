// Piezas compartidas del módulo de Facturación (FAC-10/11/14): archivos,
// copiar al portapapeles, enlaces al SAT y etiquetas de periodo.
import { useState, type ReactNode } from "react";
import { openFile, uploadFile, type PaymentOut, type PaymentStatus, type StoredFileOut } from "../../api/billing";
import Icon from "../../components/ui/Icon";
import Spinner from "../../components/ui/Spinner";

export const MONTHS = [
  "Enero",
  "Febrero",
  "Marzo",
  "Abril",
  "Mayo",
  "Junio",
  "Julio",
  "Agosto",
  "Septiembre",
  "Octubre",
  "Noviembre",
  "Diciembre",
];

export const STATUS_STYLES: Record<PaymentStatus, string> = {
  pending_invoice: "bg-amber-500/15 text-amber-800 dark:text-amber-200",
  invoiced: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  declared: "bg-violet-500/15 text-violet-800 dark:text-violet-200",
  paid: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  excluded: "bg-muted text-ink-muted",
};
export const STATUS_LABELS: Record<PaymentStatus, string> = {
  pending_invoice: "Por facturar",
  invoiced: "Facturado",
  declared: "Declarado",
  paid: "Pagado",
  excluded: "No facturable",
};

export function monthLabel(period: string): string {
  return `${MONTHS[Number(period.slice(5, 7)) - 1]} ${period.slice(0, 4)}`;
}

export function errorText(err: unknown): string {
  return err instanceof Error ? err.message : "Error al guardar";
}

export function ErrorLine({ error }: { error: string | null }) {
  return error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null;
}

export function StatusBadge({ payment }: { payment: PaymentOut }) {
  return (
    <span className="flex flex-wrap gap-1">
      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[payment.status]}`}>
        {STATUS_LABELS[payment.status]}
      </span>
      {payment.invoice_mismatch && (
        <span
          className="rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-700 dark:text-red-300"
          title="El total o la moneda de la factura no coinciden con el cobro"
        >
          No coincide con la factura
        </span>
      )}
    </span>
  );
}

// FAC-14: los portales del SAT se abren en otra pestaña, sin opener.
export function SatLink({ url, children }: { url: string | null; children: ReactNode }) {
  if (!url) return null;
  return (
    <a className="btn-secondary" href={url} target="_blank" rel="noopener noreferrer">
      <Icon name="externalLink" />
      {children}
    </a>
  );
}

export function FileChip({ file }: { file: StoredFileOut }) {
  const [error, setError] = useState<string | null>(null);
  const previewable = file.mime === "application/pdf" || file.mime.startsWith("image/");
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-sm">
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 hover:bg-muted"
        onClick={() => openFile(file, previewable).catch((e) => setError(errorText(e)))}
        title={previewable ? "Ver" : "Descargar"}
      >
        <Icon name="receipt" className="size-3.5" />
        <span className="max-w-48 truncate">{file.original_name}</span>
      </button>
      {error && <span className="text-xs text-red-600 dark:text-red-400">{error}</span>}
    </span>
  );
}

// FAC-10: sube el archivo en cuanto se elige y devuelve su id al formulario.
export function FilePicker({
  label,
  accept,
  file,
  onUploaded,
}: {
  label: string;
  accept: string;
  file: StoredFileOut | null;
  onUploaded: (file: StoredFileOut) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="space-y-1.5">
      <span className="label">{label}</span>
      <div className="flex flex-wrap items-center gap-2">
        {file && <FileChip file={file} />}
        <label className="btn-secondary cursor-pointer">
          {busy ? <Spinner className="size-4" /> : <Icon name="upload" />}
          {file ? "Reemplazar" : "Subir archivo"}
          <input
            type="file"
            className="sr-only"
            accept={accept}
            disabled={busy}
            onChange={async (e) => {
              const picked = e.target.files?.[0];
              e.target.value = "";
              if (!picked) return;
              setError(null);
              setBusy(true);
              try {
                onUploaded(await uploadFile(picked));
              } catch (err) {
                setError(errorText(err));
              } finally {
                setBusy(false);
              }
            }}
          />
        </label>
      </div>
      <ErrorLine error={error} />
    </div>
  );
}

export function CopyRow({ label, value }: { label: string; value: string | null | undefined }) {
  const [copied, setCopied] = useState(false);
  if (!value) return null;
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <div className="min-w-0">
        <p className="text-xs text-ink-muted">{label}</p>
        <p className="break-words text-sm">{value}</p>
      </div>
      <button
        type="button"
        className="btn-ghost shrink-0 px-2"
        aria-label={`Copiar ${label}`}
        title="Copiar"
        onClick={async () => {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        <Icon name={copied ? "check" : "copy"} className="size-3.5" />
      </button>
    </div>
  );
}

