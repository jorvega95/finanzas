// Wizard de importación CSV (IMP-01..06) y export (IMP-07).
import { useRef, useState } from "react";
import { supabase } from "../../auth/supabase";
import { getActiveSpaceId } from "../../api/activeSpace";
import { usePaymentMethods } from "../../api/catalogs";
import {
  useConfirmImport,
  useImportBatches,
  usePreviewImport,
  useRollbackBatch,
  type MappingConfig,
  type PreviewResponse,
  type PreviewRow,
} from "../../api/imports";
import { formatMoney } from "../../lib/money";
import { formatDate } from "../../lib/dates";

const BATCH_STATUS: Record<string, string> = {
  confirmed: "Importado",
  rolled_back: "Revertido",
  partially_rolled_back: "Revertido (parcial)",
};

async function download(path: string, fileName: string) {
  // IMP-07: descarga autenticada vía fetch + blob.
  const session = supabase ? (await supabase.auth.getSession()).data.session : null;
  const spaceId = getActiveSpaceId();
  const res = await fetch(path, {
    headers: {
      ...(session ? { Authorization: `Bearer ${session.access_token}` } : {}),
      ...(spaceId ? { "X-Space-Id": spaceId } : {}),
    },
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

export default function ImportSection() {
  const fileInput = useRef<HTMLInputElement>(null);
  const methods = usePaymentMethods();
  const previewImport = usePreviewImport();
  const confirmImport = useConfirmImport();
  const batches = useImportBatches();
  const rollback = useRollbackBatch();

  const [fileName, setFileName] = useState("");
  const [content, setContent] = useState("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<MappingConfig>({
    date_column: "",
    amount_column: "",
    description_column: null,
    date_format: "%d/%m/%Y",
    decimal_separator: ".",
    delimiter: ",",
    negative_is_expense: true,
    currency: "MXN",
  });
  const [methodId, setMethodId] = useState("");
  const [preview, setPreview] = useState<PreviewResponse | null>(null);

  function handleFile(file: File) {
    setFileName(file.name);
    setPreview(null);
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? "");
      setContent(text);
      const firstLine = text.split(/\r?\n/, 1)[0] ?? "";
      setHeaders(firstLine.split(mapping.delimiter).map((h) => h.trim()));
    };
    // IMP-06: los bancos MX suelen exportar Latin-1; UTF-8 es el default.
    reader.readAsText(file, "UTF-8");
  }

  function toggleRow(index: number) {
    if (!preview) return;
    const rows = preview.rows.map((r, i) =>
      i === index ? { ...r, selected: !r.selected } : r,
    );
    setPreview({ ...preview, rows });
  }

  const selectedCount = preview?.rows.filter((r) => r.selected).length ?? 0;

  return (
    <section className="card p-5">
      <h2 className="mb-1 font-semibold">Importar estado de cuenta (CSV)</h2>
      <p className="mb-4 text-xs text-ink-muted dark:text-slate-400">
        Sube el CSV de tu banco, mapea las columnas y revisa antes de confirmar.
        Nada se guarda hasta que confirmes.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={fileInput}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
        />
        <button className="btn-secondary" onClick={() => fileInput.current?.click()}>
          📄 Elegir archivo
        </button>
        {fileName && <span className="text-sm text-ink-muted dark:text-slate-400">{fileName}</span>}
      </div>

      {headers.length > 0 && (
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          {(
            [
              ["date_column", "Columna de fecha"],
              ["amount_column", "Columna de monto"],
              ["description_column", "Columna de descripción"],
            ] as const
          ).map(([key, label]) => (
            <div key={key}>
              <label className="label">{label}</label>
              <select
                className="input"
                value={(mapping[key] as string) ?? ""}
                onChange={(e) =>
                  setMapping({ ...mapping, [key]: e.target.value || null })
                }
              >
                <option value="">—</option>
                {headers.map((h) => (
                  <option key={h} value={h}>{h}</option>
                ))}
              </select>
            </div>
          ))}
          <div>
            <label className="label">Formato de fecha</label>
            <select
              className="input"
              value={mapping.date_format}
              onChange={(e) => setMapping({ ...mapping, date_format: e.target.value })}
            >
              <option value="%d/%m/%Y">31/12/2026</option>
              <option value="%Y-%m-%d">2026-12-31</option>
              <option value="%d-%m-%Y">31-12-2026</option>
              <option value="%m/%d/%Y">12/31/2026</option>
            </select>
          </div>
          <div>
            <label className="label">Separador decimal</label>
            <select
              className="input"
              value={mapping.decimal_separator}
              onChange={(e) => setMapping({ ...mapping, decimal_separator: e.target.value })}
            >
              <option value=".">Punto (1234.56)</option>
              <option value=",">Coma (1.234,56)</option>
            </select>
          </div>
          <div>
            <label className="label">Método de pago destino</label>
            <select
              className="input"
              required
              value={methodId}
              onChange={(e) => setMethodId(e.target.value)}
            >
              <option value="">Selecciona…</option>
              {(methods.data ?? []).map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <button
              className="btn-primary w-full"
              disabled={!mapping.date_column || !mapping.amount_column || previewImport.isPending}
              onClick={() =>
                previewImport.mutate(
                  { content, mapping },
                  { onSuccess: setPreview },
                )
              }
            >
              Vista previa
            </button>
          </div>
        </div>
      )}
      {previewImport.error && (
        <p className="mt-2 text-sm text-red-600 dark:text-red-400">
          {previewImport.error.message}
        </p>
      )}

      {preview && (
        <div className="mt-4">
          <p className="mb-2 text-sm text-ink-muted dark:text-slate-400">
            {preview.total} filas · {preview.duplicates} posibles duplicados (des-seleccionados) ·{" "}
            {preview.invalid} con error
          </p>
          <div className="max-h-72 overflow-y-auto rounded-lg border border-line dark:border-slate-800">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-card dark:bg-slate-900">
                <tr className="text-left text-xs text-ink-muted dark:text-slate-400">
                  <th className="p-2">✓</th>
                  <th className="p-2">Fecha</th>
                  <th className="p-2">Descripción</th>
                  <th className="p-2">Tipo</th>
                  <th className="p-2">Monto</th>
                  <th className="p-2">Nota</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row: PreviewRow, index) => (
                  <tr
                    key={row.row}
                    className={`border-t border-line dark:border-slate-800 ${
                      row.error ? "opacity-50" : ""
                    }`}
                  >
                    <td className="p-2">
                      <input
                        type="checkbox"
                        checked={row.selected}
                        disabled={Boolean(row.error)}
                        onChange={() => toggleRow(index)}
                      />
                    </td>
                    <td className="p-2">{row.date ? formatDate(row.date) : "—"}</td>
                    <td className="max-w-48 truncate p-2">{row.description}</td>
                    <td className="p-2">{row.type === "income" ? "Ingreso" : row.type === "expense" ? "Gasto" : "—"}</td>
                    <td className="p-2">{row.amount ? formatMoney(row.amount, row.currency ?? "MXN") : "—"}</td>
                    <td className="p-2 text-xs">
                      {row.error ? (
                        <span className="text-red-600 dark:text-red-400">{row.error}</span>
                      ) : row.is_duplicate ? (
                        <span className="text-amber-600 dark:text-amber-400">Posible duplicado</span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <button
              className="btn-primary"
              disabled={!methodId || selectedCount === 0 || confirmImport.isPending}
              onClick={() =>
                confirmImport.mutate(
                  {
                    file_name: fileName,
                    source: "csv",
                    mapping,
                    rows: preview.rows,
                    payment_method_id: methodId,
                  },
                  { onSuccess: () => setPreview(null) },
                )
              }
            >
              Importar {selectedCount} seleccionadas
            </button>
            {confirmImport.error && (
              <p className="text-sm text-red-600 dark:text-red-400">
                {confirmImport.error.message}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Historial de batches con rollback (IMP-04) */}
      {(batches.data ?? []).length > 0 && (
        <div className="mt-5 border-t border-line pt-4 dark:border-slate-800">
          <h3 className="mb-2 text-sm font-medium">Importaciones</h3>
          <ul className="space-y-1 text-sm">
            {(batches.data ?? []).map((b) => (
              <li key={b.id} className="flex items-center justify-between">
                <span>
                  {b.file_name}{" "}
                  <span className="text-xs text-ink-muted dark:text-slate-400">
                    · {b.row_count} filas · {BATCH_STATUS[b.status]}
                  </span>
                </span>
                {b.status === "confirmed" && (
                  <button
                    className="text-xs text-red-600 hover:underline dark:text-red-400"
                    onClick={() => rollback.mutate(b.id)}
                  >
                    Revertir
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Export (IMP-07) */}
      <div className="mt-5 flex flex-wrap gap-2 border-t border-line pt-4 dark:border-slate-800">
        <span className="self-center text-sm text-ink-muted dark:text-slate-400">
          Exportar mis datos:
        </span>
        <button
          className="btn-secondary"
          onClick={() => void download("/api/v1/exports/transactions.csv", "transactions.csv")}
        >
          ⬇ CSV de transacciones
        </button>
        <button
          className="btn-secondary"
          onClick={() => void download("/api/v1/exports/full.json", "finanzas.json")}
        >
          ⬇ Respaldo completo (JSON)
        </button>
      </div>
    </section>
  );
}
