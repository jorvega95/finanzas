# Reglas Recurrentes (Recurring)

Creación y gestión de reglas para generación automática de transacciones (REC-01..REC-05).

Una **regla recurrente** define un patrón de transacción: cantidad, frecuencia, categoría, método de pago. El job diario genera instancias según la regla. Las ediciones solo afectan futuras instancias; confirmadas se preservan (REC-04).

**Prefijo:** `/api/v1/recurring-rules`

---

## `GET /api/v1/recurring-rules`

**Para qué sirve:** Lista reglas recurrentes del espacio.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:**
- `include_inactive` (bool, opcional, default `false`) — incluir reglas inactivas.

**Request body:** ninguno

**Respuesta** `200` (list[`RecurringRuleOut`]):
- `id` (uuid)
- `type` (`TransactionType`) — `income` o `expense`.
- `amount` (string, Decimal)
- `amount_is_estimate` (bool) — si el monto es aproximado (REC-01).
- `currency` (string) — moneda.
- `description` (string) — descripción de la regla.
- `category_id` (uuid | null)
- `payment_method_id` (uuid | null)
- `frequency` (`RecurringFrequency`) — `daily`, `weekly`, `monthly`, `annual`.
- `start_date` (date) — inicio del patrón.
- `end_date` (date | null) — fin opcional.
- `max_occurrences` (int | null) — cantidad máxima de instancias.
- `month_day` (int | null) — día del mes (1-31, para frecuencia monthly).
- `use_last_day` (bool) — usar último día del mes.
- `is_active` (bool)

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/recurring-rules" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/recurring-rules`

**Para qué sirve:** Crea una regla recurrente. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`RecurringRuleCreate`):
- `type` (`TransactionType`) — `income` o `expense`.
- `amount` (string, Decimal, > 0)
- `amount_is_estimate` (bool, opcional, default `false`)
- `currency` (string) — moneda.
- `description` (string, 1-200 chars)
- `category_id` (uuid | null) — categoría plantilla.
- `payment_method_id` (uuid | null) — método plantilla.
- `frequency` (`RecurringFrequency`) — `daily`, `weekly`, `monthly`, `annual`.
- `start_date` (date)
- `end_date` (date | null)
- `max_occurrences` (int | null, ≥ 1)
- `month_day` (int | null, 1-31) — para monthly.
- `use_last_day` (bool, opcional, default `false`)

**Respuesta** `201` (`RecurringRuleOut`): regla creada.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio, categoría o método no encontrado; no-miembro.
- `422` validación (currency no soportada, fecha/frecuencia inválida, etc.).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/recurring-rules \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "expense",
    "amount": "500.00",
    "currency": "MXN",
    "description": "Pago de renta",
    "category_id": "'$CATEGORY_ID'",
    "payment_method_id": "'$METHOD_ID'",
    "frequency": "monthly",
    "start_date": "2026-08-01",
    "month_day": 1
  }' | jq .
```

---

## `PATCH /api/v1/recurring-rules/{rule_id}`

**Para qué sirve:** Actualiza una regla recurrente (REC-04). Ediciones afectan solo futuras instancias; confirmadas se preservan.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `rule_id` (uuid) — ID de la regla.

**Query params:** ninguno

**Request body** (`RecurringRuleUpdate`):
- `amount` (string, Decimal, optional)
- `amount_is_estimate` (bool, optional)
- `description` (string, 1-200 chars, optional)
- `category_id` (uuid | null, optional)
- `payment_method_id` (uuid | null, optional)
- `end_date` (date | null, optional)
- `max_occurrences` (int | null, optional)
- `month_day` (int | null, optional)
- `use_last_day` (bool, optional)
- `is_active` (bool, optional)

**Respuesta** `200` (`RecurringRuleOut`): regla actualizada.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` regla o espacio no encontrado; no-miembro.
- `422` validación.

**Ejemplo:**
```bash
curl -X PATCH http://localhost:8000/api/v1/recurring-rules/$RULE_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{"amount": "550.00"}' | jq .
```

---

## `DELETE /api/v1/recurring-rules/{rule_id}`

**Para qué sirve:** Elimina una regla recurrente. Transacciones confirmadas se preservan con `recurring_rule_id=NULL` (FK SET NULL). Tombstones se borran en cascada.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `rule_id` (uuid) — ID de la regla.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `204 No Content`: eliminada exitosamente.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` regla o espacio no encontrado; no-miembro.

**Ejemplo:**
```bash
curl -X DELETE http://localhost:8000/api/v1/recurring-rules/$RULE_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID"
```

---

## `POST /api/v1/recurring-rules/generate`

**Para qué sirve:** Trigger manual del job diario de generación para el espacio activo (REC-02, REC-05). Idempotente: ejecutar múltiples veces no duplica instancias.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (dict):
- `created` (int) — cantidad de instancias generadas.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/recurring-rules/generate \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## Notas de implementación

- **Fase 0:** Endpoints esqueletados; servicios retornan `NotImplementedError`.
- **REC-01:** Reglas pueden marcar estimados (`amount_is_estimate`).
- **REC-02/05:** Jobs diarios son idempotentes; múltiples ejecuciones no crean duplicados.
- **REC-03:** Instancias generadas pueden requerir confirmación manual (`needs_review`).
- **REC-04:** Ediciones solo afectan futuras instancias; las confirmadas persisten.
- **Currencies:** Solo se aceptan monedas soportadas (lista en `SUPPORTED_CURRENCIES`).
