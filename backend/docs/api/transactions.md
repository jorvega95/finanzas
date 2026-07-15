# Transacciones (Transactions)

Alta, edición y consulta de transacciones: ingresos, gastos, transferencias (TXN-01..TXN-06, REC-03).

Una **transacción** representa un movimiento de dinero entre métodos de pago o categorías. Puede ser de ingreso, gasto o transferencia. Transfers nunca suman en ingresos/gastos (TXN-02).

**Prefijo:** `/api/v1/transactions`

---

## `GET /api/v1/transactions`

**Para qué sirve:** Lista transacciones del espacio con filtros y paginación.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:**
- `date_from` (date, opcional) — rango desde (YYYY-MM-DD).
- `date_to` (date, opcional) — rango hasta (YYYY-MM-DD).
- `type` (`TransactionType`, opcional) — filtrar por tipo: `income`, `expense`, `transfer`.
- `category_id` (uuid, opcional) — filtrar por categoría.
- `payment_method_id` (uuid, opcional) — filtrar por método de pago.
- `needs_review` (bool, opcional) — mostrar solo transacciones pendientes de revisión.
- `limit` (int, opcional, default 50, max 200) — cantidad de resultados.
- `offset` (int, opcional, default 0) — salto de paginación.

**Request body:** ninguno

**Respuesta** `200` (`TransactionListOut`):
- `items` (list[`TransactionOut`]) — transacciones.
- `total` (int) — total de transacciones sin pagination.

Cada `TransactionOut` contiene:
- `id` (uuid)
- `type` (`TransactionType`)
- `date` (date)
- `amount` (string, Decimal)
- `currency` (string)
- `fx_rate_to_base` (string, Decimal | null) — tasa aplicada al convertir.
- `description` (string)
- `notes` (string | null)
- `category_id` (uuid | null)
- `payment_method_id` (uuid | null)
- `payment_method_to_id` (uuid | null) — si es transfer, el destino.
- `card_id` (uuid | null) — si es de tarjeta de crédito.
- `statement_id` (uuid | null) — si es pago de TDC, a qué statement (TXN-09).
- `expense_nature_override` (`ExpenseNature` | null) — naturaleza manual.
- `recurring_rule_id` (uuid | null) — si fue generada por regla recurrente.
- `needs_review` (bool) — si requiere confirmación manual (REC-03).

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/transactions?date_from=2026-07-01&date_to=2026-07-31&limit=20" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/transactions`

**Para qué sirve:** Crea una transacción. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`TransactionCreate`):
- `type` (`TransactionType`) — `income`, `expense` o `transfer`.
- `date` (date) — fecha (YYYY-MM-DD).
- `amount` (string, Decimal, > 0) — monto (sin signo).
- `currency` (string) — moneda (ej. `MXN`, `USD`).
- `description` (string, optional, max 200) — descripción.
- `notes` (string | null) — notas internas.
- `category_id` (uuid | null) — categoría (requerida para income/expense).
- `payment_method_id` (uuid | null) — método de origen.
- `payment_method_to_id` (uuid | null) — para transfers, método destino.
- `expense_nature_override` (`ExpenseNature` | null) — naturaleza manual (override).
- `fx_rate_override` (string, Decimal | null) — tasa de cambio manual (FX-03).
- `cycle_hint` (`current` | `next` | null) — para TDC, hint de ciclo si cae en corte (TDC-05a).
- `target_statement_id` (uuid | null) — para pagos TDC, a qué statement (TXN-09).

**Respuesta** `201` (`TransactionOut`): transacción creada.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio, categoría o método no encontrado; no-miembro.
- `422` validación (amount ≤ 0, categoría/método no pertenecen al espacio, etc.).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/transactions \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "expense",
    "date": "2026-07-14",
    "amount": "150.50",
    "currency": "MXN",
    "description": "Almuerzo",
    "category_id": "'$CATEGORY_ID'",
    "payment_method_id": "'$METHOD_ID'"
  }' | jq .
```

---

## `GET /api/v1/transactions/{txn_id}`

**Para qué sirve:** Obtiene detalles de una transacción específica.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:**
- `txn_id` (uuid) — ID de la transacción.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (`TransactionOut`): detalles de la transacción.

**Errores:**
- `401` JWT inválido o expirado.
- `404` transacción o espacio no encontrado; no-miembro.

**Ejemplo:**
```bash
curl -s http://localhost:8000/api/v1/transactions/$TXN_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `PUT /api/v1/transactions/{txn_id}`

**Para qué sirve:** Actualiza una transacción completamente. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `txn_id` (uuid) — ID de la transacción.

**Query params:** ninguno

**Request body** (`TransactionUpdate`): mismos campos que `TransactionCreate`.

**Respuesta** `200` (`TransactionOut`): transacción actualizada.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` transacción, espacio, categoría o método no encontrado; no-miembro.
- `422` validación.

**Ejemplo:**
```bash
curl -X PUT http://localhost:8000/api/v1/transactions/$TXN_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "expense",
    "date": "2026-07-14",
    "amount": "200.00",
    "currency": "MXN",
    "description": "Almuerzo actualizado",
    "category_id": "'$CATEGORY_ID'",
    "payment_method_id": "'$METHOD_ID'"
  }' | jq .
```

---

## `DELETE /api/v1/transactions/{txn_id}`

**Para qué sirve:** Elimina una transacción. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `txn_id` (uuid) — ID de la transacción.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `204 No Content`: eliminada exitosamente.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` transacción o espacio no encontrado; no-miembro.

**Ejemplo:**
```bash
curl -X DELETE http://localhost:8000/api/v1/transactions/$TXN_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID"
```

---

## `POST /api/v1/transactions/{txn_id}/confirm`

**Para qué sirve:** Confirma una transacción de la bandeja de revisión (REC-03). Opcional: ajustar el monto.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `txn_id` (uuid) — ID de la transacción.

**Query params:** ninguno

**Request body** (`TransactionConfirm`):
- `amount` (string, Decimal, optional) — nuevo monto si se ajusta (si no se envía, se mantiene el original).

**Respuesta** `200` (`TransactionOut`): transacción confirmada.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` transacción o espacio no encontrado; no-miembro.
- `422` validación (amount inválido).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/transactions/$TXN_ID/confirm \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{"amount": "175.00"}' | jq .
```

---

## `POST /api/v1/transactions/{txn_id}/move-cycle`

**Para qué sirve:** Mueve una compra de tarjeta de crédito al ciclo anterior o siguiente (TDC-06).

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `txn_id` (uuid) — ID de la transacción (debe ser cargo de TDC).

**Query params:** ninguno

**Request body** (`MoveCycle`):
- `direction` (string) — `previous` o `next`.

**Respuesta** `200` (`TransactionOut`): transacción con nuevo ciclo.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` transacción o espacio no encontrado; no-miembro.
- `422` transacción no es cargo de TDC o ciclo no válido.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/transactions/$TXN_ID/move-cycle \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{"direction": "next"}' | jq .
```

---

## Notas de implementación

- **Fase 0:** Endpoints esqueletados; servicios retornan `NotImplementedError`.
- **GLO-01:** Montos viajan como strings en JSON (Decimal-safe).
- **GLO-02:** Fechas son `date` puro, no `datetime`.
- **TXN-02:** Transfers nunca suman en ingresos/gastos agregados.
- **TXN-09:** Pagos de TDC incluyen `statement_id` para asociación explícita.
- **REC-03:** Transacciones generadas por reglas recurrentes pueden requerir confirmación manual (`needs_review=true`).
- **Reglas:** TXN-01..TXN-06.
