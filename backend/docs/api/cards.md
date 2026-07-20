# Tarjetas (Cards)

Gestión de tarjetas de crédito y débito, estados de cuenta, pagos y ciclos de facturación (TDC-01..TDC-16, TAR-01..TAR-07, REM-01, REM-01b).

Una **tarjeta** puede ser de crédito (revolvente) o débito/prepago. Las tarjetas de crédito generan **ciclos de facturación** (statements) automáticamente según reglas TDC-02..TDC-04. Los recordatorios (REM-01) disparan notificaciones cercanas a la fecha de vencimiento.

**Prefijo:** `/api/v1/cards`

---

## `GET /api/v1/cards`

**Para qué sirve:** Lista tarjetas del espacio con deuda y saldo.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:**
- `include_inactive` (bool, opcional, default `false`) — incluir tarjetas inactivas.

**Request body:** ninguno

**Respuesta** `200` (list[`CardWithDebtOut`]):

Cada tarjeta retorna:
- `id`, `alias`, `bank`, `network`, `last4`, `currency` (TDC-01: nunca PAN completo, CVV, expiración)
- `credit_limit` (Decimal | null) — límite de crédito.
- `statement_day`, `cutoff_day_policy`, `payment_due_days`, `payment_day` — ciclos TDC-02..TDC-04.
- `reminder_days` (list[int]) — días antes del vencimiento para recordar (REM-01).
- `initial_balance` (Decimal | null) — balance inicial (débito/prepago).
- `allow_overdraft` (bool) — permitir sobregiro.
- `color` (string | null)
- `payment_method_id` (uuid | null)
- `is_active` (bool)
- `behavior` (`CardBehavior`) — `credit` o `debit`.
- `debt` (`DebtSummary`, solo crédito) — TDC-09:
  - `statement_balance` — saldo en statements cerrados.
  - `current_cycle_spend` — gasto del ciclo actual.
  - `committed_msi` — comprometido en MSI.
  - `total_debt` — suma de los anteriores.
- `balance` (Decimal | null, solo débito) — TAR-05.
- `signed_balance` (Decimal | null) — TAR-06 para PAT-01.
- `next_payment` (`NextPaymentOut` | null, solo crédito) — TDC-14:
  - `amount` — monto a pagar.
  - `due_date` — cuándo.
- `opening_balance` (Decimal | null, solo crédito) — TDC-14: deuda del corte anterior.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/cards" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `PUT /api/v1/cards/layout`

**Para qué sirve:** Guarda el ordenamiento personal del usuario para tarjetas en el espacio (TAR-07). Preferencia UI personal, no datos compartidos.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404. Cualquier rol puede guardar su preferencia.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`CardLayoutUpdate`):
- `card_ids` (list[uuid]) — IDs ordenadas. IDs no pertenecientes al espacio se ignoran; tarjetas faltantes mantienen orden de alias.

**Respuesta** `204 No Content`: guardado exitoso.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -X PUT http://localhost:8000/api/v1/cards/layout \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{"card_ids": ["'$CARD_ID_1'", "'$CARD_ID_2'"]}' 
```

---

## `POST /api/v1/cards`

**Para qué sirve:** Crea una tarjeta. Requiere rol editor+. TDC-15: todos los campos opcionales, rellenables después.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`CardCreate`):
- `card_type_id` (uuid) — tipo de tarjeta (CAT-08).
- `alias` (string, 1-60 chars) — nombre amigable.
- `bank` (string, 1-60 chars) — banco emisor.
- `network` (string, 1-20 chars) — red (Visa, Mastercard, etc.).
- `last4` (string, exacto 4 dígitos) — últimos 4 dígitos (TDC-01).
- `currency` (string, opcional, default `MXN`)
- `color` (string | null, optional, max 20 chars)
- **Crédito (TAR-02):**
  - `statement_day` (int 1-28 | `"last"` | null, optional) — día del mes de corte.
  - `cutoff_day_policy` (`CutoffDayPolicy`, opcional, default `include`) — TDC-05a: `include` o `exclude`.
  - `payment_due_days` (int 1-30 | null, optional) — días para pagar.
  - `payment_day` (int 1-28 | `"last"` | null, optional) — día de pago.
  - `credit_limit` (Decimal | null, optional)
  - `reminder_days` (list[int] | null, optional, default [3, 1]) — REM-01.
  - `opening_balance` (Decimal ≥ 0 | null, optional) — TDC-14: deuda previa.
- **Débito/Prepago (TAR-05):**
  - `initial_balance` (Decimal ≥ 0 | null, optional) — saldo inicial.
  - `allow_overdraft` (bool, optional, default `false`)

**Respuesta** `201` (`CardOut`): tarjeta creada.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio o tipo de tarjeta no encontrado; no-miembro.
- `422` validación (last4 inválido, tipo no existe, etc.).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/cards \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "card_type_id": "'$CARD_TYPE_ID'",
    "alias": "Visa Crédito",
    "bank": "BBVA",
    "network": "Visa",
    "last4": "1234",
    "currency": "MXN",
    "statement_day": 15,
    "cutoff_day_policy": "include",
    "payment_due_days": 20,
    "payment_day": 5,
    "credit_limit": "50000.00"
  }' | jq .
```

---

## `GET /api/v1/cards/{card_id}`

**Para qué sirve:** Obtiene detalles completos de una tarjeta con deuda/saldo.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:**
- `card_id` (uuid) — ID de la tarjeta.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (`CardWithDebtOut`): detalles completos.

**Errores:**
- `401` JWT inválido o expirado.
- `404` tarjeta o espacio no encontrado; no-miembro.

**Ejemplo:**
```bash
curl -s http://localhost:8000/api/v1/cards/$CARD_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `PATCH /api/v1/cards/{card_id}`

**Para qué sirve:** Actualiza una tarjeta completamente (TDC-15). Solo campos enviados se aplican. Tipo de tarjeta es inmutable.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `card_id` (uuid) — ID de la tarjeta.

**Query params:** ninguno

**Request body** (`CardUpdate`): campos a actualizar (todos opcionales):
- `alias`, `bank`, `network`, `last4`, `currency`, `color`
- `statement_day`, `cutoff_day_policy`, `payment_due_days`, `payment_day` (crédito)
- `credit_limit`, `reminder_days`, `opening_balance` (crédito)
- `initial_balance`, `allow_overdraft` (débito/prepago)
- `is_active` (bool, optional) — TDC-12.

**Respuesta** `200` (`CardWithDebtOut`): tarjeta actualizada.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` tarjeta o espacio no encontrado; no-miembro.
- `422` validación.

**Ejemplo:**
```bash
curl -X PATCH http://localhost:8000/api/v1/cards/$CARD_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{"alias": "Visa Plata", "credit_limit": "60000.00"}' | jq .
```

---

## `GET /api/v1/cards/{card_id}/statements`

**Para qué sirve:** Lista estados de cuenta (ciclos) de la tarjeta (TDC-02..TDC-08).

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:**
- `card_id` (uuid) — ID de la tarjeta.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (list[`StatementOut`]):
- `id` (uuid)
- `credit_card_id` (uuid)
- `period_start`, `period_end`, `due_date` (date)
- `computed_total` (Decimal) — total de cargos.
- `applied_credit` (Decimal) — crédito aplicado.
- `paid_amount` (Decimal) — monto pagado (TDC-10).
- `status` (`StatementStatus`) — `pending`, `closed`, `partially_paid`, `paid`.
- `is_overdue` (bool, computed) — TDC-08: flag contra hoy, no status.

**Errores:**
- `401` JWT inválido o expirado.
- `404` tarjeta o espacio no encontrado; no-miembro.

**Ejemplo:**
```bash
curl -s http://localhost:8000/api/v1/cards/$CARD_ID/statements \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/cards/{card_id}/payments`

**Para qué sirve:** Registra un pago de tarjeta de crédito como transferencia hacia el método de la tarjeta (TDC-10, REM-04).

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `card_id` (uuid) — ID de la tarjeta.

**Query params:** ninguno

**Request body** (`PaymentCreate`):
- `amount` (Decimal, > 0) — monto del pago.
- `from_payment_method_id` (uuid) — método de origen del pago.
- `date` (date) — fecha del pago.
- `statement_id` (uuid | null, optional) — statement específico a abonar. Si no se especifica, se abona al más antiguo sin pagar completamente.

**Respuesta** `201` (`TransactionOut`): transacción de pago creada.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` tarjeta, espacio o método no encontrado; no-miembro.
- `422` validación (amount ≤ 0).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/cards/$CARD_ID/payments \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "5000.00",
    "from_payment_method_id": "'$ORIGIN_METHOD_ID'",
    "date": "2026-07-20"
  }' | jq .
```

---

## `POST /api/v1/cards/close-cycles`

**Para qué sirve:** Trigger manual del job diario de cierre de ciclos (TDC-07) para el espacio. Idempotente. Dispara recordatorios (REM-04).

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (list[`StatementOut`]): ciclos cerrados hoy.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/cards/close-cycles \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## Notificaciones

El centro de notificaciones in-app (inbox, badge de no leídos y descarte) vive en su propio router: ver **[notifications.md](./notifications.md)** (REM-04..REM-07). Las tarjetas solo *generan* los recordatorios al cerrar un statement (REM-01) y los cancelan al pagarlo (REM-01b).

---

## Notas de implementación

- **Fase 0:** Endpoints esqueletados; servicios retornan `NotImplementedError`.
- **TDC-01:** PAN, CVV y expiración jamás se almacenan ni loggean; solo `last4`.
- **TDC-02..TDC-04:** Ciclos generados según `statement_day`, `cutoff_day_policy`, `payment_due_days`.
- **TDC-05a:** `cycle_hint` resuelve ambigüedad de compras en día de corte.
- **TDC-07:** Job diario cierra ciclos vencidos automáticamente.
- **TDC-08:** `is_overdue` es flag computado contra hoy, no status de DB.
- **TDC-09:** `debt_summary` nunca mezcla números; transfers nunca suman (TXN-02).
- **TDC-10:** Pagos son transferencias hacia el método de pago de la tarjeta.
- **TDC-14:** `next_payment` y `opening_balance` sintetizados desde statements.
- **TDC-15:** Actualización completa; todos los campos opcionales.
- **TAR-05/TAR-06:** Débito/prepago con balance y signed_balance para PAT-01.
- **TAR-07:** Ordenamiento personal, no compartido.
- **REM-01/REM-04/REM-05:** Recordatorios y centro de notificaciones.
