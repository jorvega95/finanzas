// Piezas compartidas del módulo de Facturación (FAC-10/11/14): archivos,
// copiar al portapapeles, enlaces al SAT y etiquetas de periodo.
import { useRef, useState, type ReactNode } from "react";
import { openFile, uploadFile, type PaymentOut, type PaymentStatus, type StoredFileOut } from "../../api/billing";
import ConfirmDialog from "../../components/ui/ConfirmDialog";
import Icon from "../../components/ui/Icon";
import Spinner from "../../components/ui/Spinner";
import { useToast } from "../../components/ui/Toast";

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
// GLO-10: reemplazar uno ya adjunto se confirma y cada subida se avisa; el
// archivo queda ligado hasta que se guarda el formulario.
export function FilePicker({
  label,
  accept,
  file,
  onUploaded,
}: {
  label: string;
  accept: string;
  file: StoredFileOut | null;
  onUploaded: (file: StoredFileOut) => void | Promise<void>;
}) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [confirmingReplace, setConfirmingReplace] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="space-y-1.5">
      <span className="label">{label}</span>
      <div className="flex flex-wrap items-center gap-2">
        {file && <FileChip file={file} />}
        <button
          type="button"
          className="btn-secondary"
          disabled={busy}
          onClick={() => (file ? setConfirmingReplace(true) : input.current?.click())}
        >
          {busy ? <Spinner className="size-4" /> : <Icon name="upload" />}
          {busy ? "Subiendo…" : file ? "Reemplazar" : "Subir archivo"}
        </button>
        <input
          ref={input}
          type="file"
          className="sr-only"
          tabIndex={-1}
          aria-label={label}
          accept={accept}
          disabled={busy}
          onChange={async (e) => {
            const picked = e.target.files?.[0];
            e.target.value = "";
            if (!picked) return;
            setError(null);
            setBusy(true);
            try {
              await onUploaded(await uploadFile(picked));
              toast.success(`«${picked.name}» cargado. Guarda para conservarlo.`);
            } catch (err) {
              setError(errorText(err));
              toast.error(`No se pudo subir «${picked.name}»: ${errorText(err)}`);
            } finally {
              setBusy(false);
            }
          }}
        />
      </div>
      <ErrorLine error={error} />
      {file && (
        <ConfirmDialog
          open={confirmingReplace}
          title="Reemplazar archivo"
          confirmLabel="Elegir otro archivo"
          tone="primary"
          onClose={() => setConfirmingReplace(false)}
          onConfirm={() => {
            setConfirmingReplace(false);
            input.current?.click();
          }}
        >
          <p>
            Ya hay un archivo adjunto: <strong className="break-all">{file.original_name}</strong>.
          </p>
          <p>
            Si eliges otro, sustituirá a este en cuanto guardes. Mientras no guardes, el actual se
            conserva.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}

// FAC-06/14: abre la página de Banxico guardada en Configuración para consultar
// el tipo de cambio para solventar obligaciones. Sin URL queda deshabilitado.
export function BanxicoButton({ url }: { url: string | null }) {
  if (!url)
    return (
      <button
        type="button"
        className="btn-secondary shrink-0"
        disabled
        title="Guarda la URL de Banxico en Facturación › Configuración"
      >
        <Icon name="externalLink" />
        Banxico
      </button>
    );
  return (
    <a
      className="btn-secondary shrink-0"
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title="Consultar el tipo de cambio en Banxico"
    >
      <Icon name="externalLink" />
      Banxico
    </a>
  );
}

// FAC-11: un campo del formulario "Genera tu factura" del portal, con la
// misma etiqueta y su botón de copiar. Sin valor muestra la indicación.
export function PortalField({
  label,
  value,
  hint,
}: {
  label: string;
  value?: string | null;
  hint?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="min-w-0">
      <p className="mb-1 text-xs font-medium text-ink-muted">{label}</p>
      <div
        className={`flex min-h-9 items-start justify-between gap-2 rounded-md border px-2.5 py-1.5 ${
          value ? "border-line bg-surface" : "border-dashed border-line bg-transparent"
        }`}
      >
        <p className={`min-w-0 break-words text-sm ${value ? "" : "italic text-ink-subtle"}`}>
          {value || hint || "Dejar vacío"}
        </p>
        {value && (
          <button
            type="button"
            className="-mr-1 shrink-0 rounded p-1 text-ink-subtle transition hover:bg-muted hover:text-ink"
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
        )}
      </div>
      {value && hint && <p className="mt-0.5 text-xs text-ink-subtle">{hint}</p>}
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

