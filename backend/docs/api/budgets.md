# Presupuestos (Budgets)

Presupuestos por categoría mensual con seguimiento de consumo y alertas (PRE-01..PRE-04).

Un **presupuesto** limita el gasto en una categoría durante un mes. Puede generarse alertas automáticas cuando se alcanza un umbral de consumo. Presupuestos pueden copiarse de un mes a otro para reuso.

**Prefijo:** `/api/v1/budgets`

---

## `GET /api/v1/budgets`

**Para qué sirve:** Lista presupuestos de un mes con consumo actual (PRE-04). Presupuesto vs consumido por categoría.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:**
- `month` (string, `YYYY-MM`) — mes a consultar (REQUERIDO).

**Request body:** ninguno

**Respuesta** `200` (list[`BudgetProgressOut`]):
- `budget` (`BudgetOut`):
  - `id` (uuid)
  - `category_id` (uuid)
  - `month` (date, primer día del mes)
  - `amount` (Decimal) — presupuesto.
  - `alert_threshold` (Decimal, 0 < x ≤ 1) — umbral de alerta (default 0.80 = 80%).
- `category_name` (string)
- `consumed` (Decimal) — gasto actual en la categoría.
- `remaining` (Decimal) — amount − consumed.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.
- `422` mes inválido.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/budgets?month=2026-07" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/budgets`

**Para qué sirve:** Crea un presupuesto para una categoría en un mes. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`BudgetCreate`):
- `category_id` (uuid) — categoría.
- `month` (string, `YYYY-MM`) — mes.
- `amount` (Decimal, > 0) — presupuesto.
- `alert_threshold` (Decimal, 0 < x ≤ 1, opcional, default 0.80)

**Respuesta** `201` (`BudgetOut`): presupuesto creado.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` categoría o espacio no encontrado; no-miembro.
- `422` validación (amount ≤ 0, mes inválido).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/budgets \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "category_id": "'$CATEGORY_ID'",
    "month": "2026-07",
    "amount": "5000.00",
    "alert_threshold": 0.80
  }' | jq .
```

---

## `PATCH /api/v1/budgets/{budget_id}`

**Para qué sirve:** Actualiza un presupuesto. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `budget_id` (uuid) — ID del presupuesto.

**Query params:** ninguno

**Request body** (`BudgetUpdate`):
- `amount` (Decimal, > 0, optional)
- `alert_threshold` (Decimal, 0 < x ≤ 1, optional)

**Respuesta** `200` (`BudgetOut`): presupuesto actualizado.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` presupuesto o espacio no encontrado; no-miembro.
- `422` validación.

**Ejemplo:**
```bash
curl -X PATCH http://localhost:8000/api/v1/budgets/$BUDGET_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{"amount": "6000.00", "alert_threshold": 0.75}' | jq .
```

---

## `DELETE /api/v1/budgets/{budget_id}`

**Para qué sirve:** Elimina un presupuesto. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `budget_id` (uuid) — ID del presupuesto.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `204 No Content`: eliminado exitosamente.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` presupuesto o espacio no encontrado; no-miembro.

**Ejemplo:**
```bash
curl -X DELETE http://localhost:8000/api/v1/budgets/$BUDGET_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID"
```

---

## `POST /api/v1/budgets/copy`

**Para qué sirve:** Copia presupuestos del mes anterior a otro mes (PRE-01). Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`BudgetCopy`):
- `from_month` (string, `YYYY-MM`) — mes origen.
- `to_month` (string, `YYYY-MM`) — mes destino.

**Respuesta** `200` (dict):
- `copied` (int) — cantidad de presupuestos copiados.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio no encontrado; no-miembro.
- `422` validación (meses inválidos).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/budgets/copy \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "from_month": "2026-06",
    "to_month": "2026-07"
  }' | jq .
```

---

## `POST /api/v1/budgets/check-alerts`

**Para qué sirve:** Evalúa umbrales y crea alertas (PRE-03). Idempotente: ejecutar varias veces el mismo día no duplica alertas.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:**
- `month` (string, `YYYY-MM`) — mes a evaluar.

**Request body:** ninguno

**Respuesta** `200` (dict):
- `created` (int) — cantidad de alertas creadas.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio no encontrado; no-miembro.
- `422` mes inválido.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/budgets/check-alerts?month=2026-07 \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## Notas de implementación

- **Fase 0:** Endpoints esqueletados; servicios retornan `NotImplementedError`.
- **PRE-01:** Copia de presupuestos.
- **PRE-02:** (futuro: notificaciones de presupuesto).
- **PRE-03:** Alertas por umbral (default 80%).
- **PRE-04:** Presupuesto vs consumido.
- **GLO-01:** Montos como strings en JSON.
- **GLO-02:** Fechas como `date` puro.
