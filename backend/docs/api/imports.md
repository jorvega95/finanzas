# Importación y Exportación (Imports)

CSV import wizard, detección de duplicados, confirma transacciones y export (IMP-01..IMP-07).

Un **import** procesa un archivo CSV: preview (validación sin insertar), marcado de duplicados (IMP-02), confirmación e inserción en batch. Export permite migración de datos (mitigación ESP-06).

**Endpoints base:** sin prefijo específico (rutas en raíz `/api/v1/`)

---

## `POST /api/v1/imports/preview`

**Para qué sirve:** Parsea y valida un CSV SIN insertar (IMP-01). Marca duplicados (IMP-02). Retorna preview de filas parsificadas.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`PreviewRequest`):
- `content` (string) — contenido CSV en bruto.
- `mapping` (`MappingConfig`) — cómo interpretar el CSV:
  - `date_column` (string) — nombre de la columna de fecha (REQUERIDO).
  - `amount_column` (string) — nombre de la columna de monto (REQUERIDO).
  - `description_column` (string | null, optional) — columna de descripción.
  - `date_format` (string, opcional, default `%Y-%m-%d`) — formato de fecha (Python strftime).
  - `decimal_separator` (char, opcional, default `.`) — `.` o `,`.
  - `delimiter` (char, opcional, default `,`) — delimitador CSV (`,` o `;`).
  - `negative_is_expense` (bool, opcional, default `true`) — si negativo = gasto.
  - `currency` (string, opcional, default `MXN`) — moneda de las transacciones.

**Respuesta** `200` (`PreviewResponse`):
- `rows` (list[`PreviewRow`]) — filas procesadas:
  - `row` (int) — número de línea.
  - `date` (date | null) — fecha parseada.
  - `type` (string | null) — tipo inferido (`income`, `expense`).
  - `amount` (string | null) — monto parseado.
  - `currency` (string | null)
  - `description` (string)
  - `error` (string | null) — mensaje de error si falla.
  - `is_duplicate` (bool) — si ya existe en el espacio (IMP-02).
  - `selected` (bool) — si será importado (default `true` si no hay error).
- `total` (int) — cantidad de filas.
- `duplicates` (int) — cantidad de duplicados detectados.
- `invalid` (int) — cantidad de filas con error.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio no encontrado; no-miembro.
- `422` CSV malformado, encoding inválido.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/imports/preview \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "fecha,monto,descripcion\n2026-07-14,1500.00,Almuerzo\n2026-07-15,-2000.00,Compra\n",
    "mapping": {
      "date_column": "fecha",
      "amount_column": "monto",
      "description_column": "descripcion",
      "date_format": "%Y-%m-%d",
      "decimal_separator": ".",
      "delimiter": ",",
      "negative_is_expense": true,
      "currency": "MXN"
    }
  }' | jq .
```

---

## `POST /api/v1/imports/confirm`

**Para qué sirve:** Confirma e inserta transacciones de preview como batch (IMP-01). Crea registro de ImportBatch para trazabilidad.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`ConfirmRequest`):
- `file_name` (string, 1-255 chars) — nombre del archivo (trazabilidad).
- `source` (string, max 60 chars, opcional, default `csv`) — origen (banco, app, etc.).
- `mapping` (`MappingConfig`) — mismo que preview.
- `rows` (list[`PreviewRow`]) — filas a importar (con `selected=true`).
- `payment_method_id` (uuid) — método de pago por defecto.
- `category_id` (uuid | null, optional) — categoría por defecto.

**Respuesta** `201` (`BatchOut`):
- `id` (uuid) — ID del batch de importación.
- `source` (string)
- `file_name` (string)
- `row_count` (int) — filas insertadas.
- `status` (`ImportStatus`) — `pending`, `completed`, etc.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio, método de pago o categoría no encontrado; no-miembro.
- `422` validación (method/category no pertenecen al espacio, filas inválidas).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/imports/confirm \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "file_name": "banco_julio_2026.csv",
    "source": "csv",
    "mapping": {...},
    "rows": [
      {"row": 1, "date": "2026-07-14", "type": "expense", "amount": "1500.00", "currency": "MXN", "description": "Almuerzo", "error": null, "is_duplicate": false, "selected": true}
    ],
    "payment_method_id": "'$METHOD_ID'",
    "category_id": "'$CATEGORY_ID'"
  }' | jq .
```

---

## `GET /api/v1/imports`

**Para qué sirve:** Lista batches de importación del espacio (historial).

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (list[`BatchOut`]):
- `id` (uuid)
- `source` (string)
- `file_name` (string)
- `row_count` (int)
- `status` (`ImportStatus`)

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/imports" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/imports/{batch_id}/rollback`

**Para qué sirve:** Revierte un batch de importación (IMP-04). Transacciones editadas a mano se conservan; solo se borran las del batch.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `batch_id` (uuid) — ID del batch a revertir.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (dict):
- `deleted` (int) — cantidad de transacciones borradas.
- `preserved` (int) — cantidad de transacciones editadas (conservadas).

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` batch o espacio no encontrado; no-miembro.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/imports/$BATCH_ID/rollback \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `GET /api/v1/exports/transactions.csv`

**Para qué sirve:** Exporta todas las transacciones del espacio como CSV (IMP-07). Columnas: date, description, amount, currency, category, payment_method, etc.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (text/csv):
- Content-Type: `text/csv; charset=utf-8`
- Content-Disposition: `attachment; filename="transactions.csv"`
- Body: CSV con todas las transacciones.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/exports/transactions.csv" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  > transactions.csv
```

---

## `GET /api/v1/exports/full.json`

**Para qué sirve:** Exporta datos completos del espacio como JSON (IMP-07). Mitigación de ESP-06 (privacy: facilita descarga total antes de borrar). Incluye transacciones, tarjetas, presupuestos, planes MSI, etc.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (application/json):
- Content-Type: `application/json; charset=utf-8`
- Content-Disposition: `attachment; filename="finanzas.json"`
- Body: JSON con datos completos del espacio.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/exports/full.json" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  > finanzas.json
```

---

## Modelos auxiliares

### MappingConfig
Mapeo de columnas CSV a campos de transacción. Ver request body de `/preview`.

### PreviewRow
Resultado del parsing de una línea CSV. Incluye error si falla, is_duplicate si coincide con existentes.

### PreviewResponse
Respuesta de preview: lista de filas, totales, duplicados, inválidos.

### ConfirmRequest
Solicitud de confirmación: archivo, mapping, filas seleccionadas, método y categoría.

### BatchOut
Resumen de un batch importado: ID, origen, nombre, cantidad de filas, status.

---

## Notas de implementación

- **Fase 0:** Endpoints esqueletados; servicios retornan `NotImplementedError`.
- **IMP-01:** Parser con validación de fecha, monto, tipo.
- **IMP-02:** Detección de duplicados: misma fecha + monto + descripción.
- **IMP-03:** (futuro: match automático de transacciones pendientes).
- **IMP-04:** Rollback: solo borra transacciones no editadas del batch.
- **IMP-05:** Cargos de TDC pueden convertirse a MSI después de importar.
- **IMP-06:** Templates de bancos comunes (BBVA, Santander, etc.) con mappings preconfigurados.
- **IMP-07:** Exportación CSV y JSON completa.
- **ESP-06:** Export permite descarga antes de borrar espacio.
- **GLO-01:** Montos como strings en JSON.
