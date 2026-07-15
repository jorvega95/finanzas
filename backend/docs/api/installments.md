# Cuotas/MSI (Installments)

Gestión de planes de compra en cuotas (Mensualidades Sin Intereses / MSI) (MSI-01..MSI-10).

Una **MSI** convierte una compra única en tarjeta de crédito en un plan de múltiples cuotas mensuales. Cada cuota es una transacción independiente que se carga en su ciclo correspondiente. Proyecciones calculadas 100% en SQL sin duplicar agregados (MSI-03, DSH-03).

**Prefijo:** `/api/v1/installment-plans`

---

## `POST /api/v1/installment-plans`

**Para qué sirve:** Convierte una compra de tarjeta de crédito en plan MSI (MSI-01, IMP-05). Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`PlanCreate`):
- `transaction_id` (uuid) — ID de la transacción a convertir (debe ser cargo de TDC).
- `months` (int, 2-60) — cantidad de cuotas.

**Respuesta** `201` (`PlanOut`):
- `id` (uuid) — ID del plan.
- `credit_card_id` (uuid) — tarjeta.
- `transaction_id` (uuid) — transacción origen.
- `total_amount` (Decimal) — monto total.
- `months` (int) — cantidad de cuotas.
- `monthly_amount` (Decimal) — monto por cuota (MSI-02: redondeo ROUND_FLOOR, última absorbe residuo).
- `start_date` (date) — fecha de inicio.
- `status` (`PlanStatus`) — `active`, `settled`, etc.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` transacción o espacio no encontrado; no-miembro.
- `422` transacción no es cargo de TDC, months inválidos, etc.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/installment-plans \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "'$TXN_ID'",
    "months": 12
  }' | jq .
```

---

## `GET /api/v1/installment-plans`

**Para qué sirve:** Lista resumen de planes MSI con proyecciones (MSI-06).

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (list[`PlanSummaryOut`]):

Cada plan incluye:
- `plan` (`PlanOut`) — detalles base.
- `description` (string) — descripción de la compra.
- `card_alias` (string) — alias de la tarjeta.
- `paid_count` (int) — cuotas pagadas.
- `charged_count` (int) — cuotas cargadas (pendientes de pago).
- `pending_count` (int) — cuotas futuras.
- `remaining_amount` (Decimal) — monto sin pagar.
- `projected_payoff` (date) — fecha proyectada de liquidación (último corte).
- `projected_payment_date` (date) — fecha proyectada de pago (due_date del último statement, TDC-04).
- `installments` (list[`InstallmentOut`]) — cuotas con:
  - `number` (int), `amount` (Decimal)
  - `estimated_charge_date` (date)
  - `statement_id` (uuid | null)
  - `status` (`InstallmentStatus`) — `pending`, `charged`, `paid`

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/installment-plans" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/installment-plans/backfill`

**Para qué sirve:** Registra una cuota en curso para compras MSI anteriores al sistema (MSI-10).

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`PlanCurrentInstallmentCreate`):
- `description` (string, optional, max 200 chars) — descripción de la compra.
- `monthly_amount` (Decimal, > 0) — monto por cuota.
- `currency` (string, opcional, default `MXN`)
- `credit_card_id` (uuid) — tarjeta donde se cargará.
- `current_number` (int, 1-60) — número de la cuota actual.
- `total_months` (int, 2-60) — total de cuotas del plan.
- `category_id` (uuid) — categoría de la compra.
- `current_is_charged` (bool, optional, default `true`) — si la cuota actual ya fue cargada.

**Respuesta** `201` (`PlanOut`): plan creado.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` tarjeta, categoría o espacio no encontrado; no-miembro.
- `422` validación (monto ≤ 0, números inválidos).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/installment-plans/backfill \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Laptop comprada hace 3 meses",
    "monthly_amount": "500.00",
    "currency": "MXN",
    "credit_card_id": "'$CARD_ID'",
    "current_number": 4,
    "total_months": 12,
    "category_id": "'$CATEGORY_ID'",
    "current_is_charged": true
  }' | jq .
```

---

## `GET /api/v1/installment-plans/projection`

**Para qué sirve:** Proyección global por mes futuro × tarjeta (MSI-06). Cuánto está comprometido en MSI por mes.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (list[`ProjectionRow`]):
- `credit_card_id` (uuid)
- `card_alias` (string)
- `month` (string, `YYYY-MM`)
- `amount` (Decimal) — monto comprometido en ese mes.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/installment-plans/projection" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/installment-plans/{plan_id}/settle`

**Para qué sirve:** Liquidación anticipada de un plan (MSI-07). Crea crédito en el siguiente statement.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `plan_id` (uuid) — ID del plan MSI.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (`PlanOut`): plan con status actualizado a `settled`.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` plan o espacio no encontrado; no-miembro.
- `422` plan ya está liquidado o no hay cuotas pendientes.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/installment-plans/$PLAN_ID/settle \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## Notas de implementación

- **Fase 0:** Endpoints esqueletados; servicios retornan `NotImplementedError`.
- **MSI-01:** Convierte compras TDC en planes de cuotas.
- **MSI-02:** Redondeo ROUND_FLOOR + última cuota absorbe residuo. Σ cuotas == total (tested).
- **MSI-03:** Cuota-madre nunca suma en agregados; solo cuotas (TXN-02).
- **MSI-06:** Proyecciones de comprometido por mes × tarjeta.
- **MSI-07:** Liquidación anticipada con crédito en siguiente statement.
- **MSI-10:** Backfill para compras MSI anteriores al sistema.
- **GLO-01:** Montos como strings en JSON.
- **DSH-03:** Agregados 100% en SQL sin duplicar (madre-cuotas).
