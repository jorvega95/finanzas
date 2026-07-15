# Dashboard

Resumen de ingresos/gastos, tendencias, próximos compromisos y pronóstico de flujo (DSH-01..DSH-05, PRO-01..PRO-06).

El **dashboard** agrega transacciones del mes en resúmenes SQL puro (DSH-03). **Pronóstico** proyecta flujo futuro detectando sobregiro.

**Prefijo:** `/api/v1/dashboard`

---

## `GET /api/v1/dashboard/summary`

**Para qué sirve:** Resumen mensual completo: totales, desglose por categoría/naturaleza, tendencia, próximos compromisos (DSH-02/03/05). Agregados 100% en SQL.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:**
- `month` (string, `YYYY-MM`, optional) — mes a resumir; si no se especifica, mes actual.

**Request body:** ninguno

**Respuesta** `200` (`DashboardSummary`):
- `month` (string, `YYYY-MM`)
- `totals` (`Totals`):
  - `income` (Decimal) — ingresos totales (devengado).
  - `expenses` (Decimal) — gastos totales (devengado).
  - `net` (Decimal) — net = income − expenses.
- `by_category` (list[`CategoryBreakdownRow`]) — gasto por categoría:
  - `category_id` (uuid | null)
  - `category_name` (string)
  - `total` (Decimal)
- `by_nature` (dict[string, Decimal]) — gasto por naturaleza (food, transport, etc.).
- `trend` (list[`TrendPoint`]) — ingresos/gastos de cada mes (últimos 12 meses + actual):
  - `month` (string)
  - `income`, `expenses`, `net` (Decimal)
- `upcoming` (list[`UpcomingItem`]) — próximos compromisos sin pagar (DSH-05):
  - `kind` (string) — `payment_due`, `recurring_scheduled`, etc.
  - `date` (date)
  - `description` (string)
  - `amount` (Decimal)
  - `ref_id` (uuid) — ID de referencia (statement, regla, etc.).
  - `is_overdue` (bool)

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.
- `422` mes inválido.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/dashboard/summary?month=2026-07" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `GET /api/v1/dashboard/forecast`

**Para qué sirve:** Pronóstico de flujo a futuro (PRO-01..06). Detecta sobregiro y proyecta fechas críticas.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:**
- `horizon_months` (int, 1-24, opcional, default 6) — meses a proyectar.
- `cash_adjustment` (Decimal, opcional, default 0) — ajuste de caja inicial.

**Request body:** ninguno

**Respuesta** `200` (`ForecastSummary`):
- `horizon_months` (int) — meses proyectados.
- `generated_for` (date) — fecha de generación (hoy).
- `starting_cash` (Decimal) — caja inicial (PRO-02).
- `cash_adjustment` (Decimal) — ajuste aplicado.
- `ending_balance` (Decimal) — saldo al final del horizonte.
- `min_balance` (Decimal) — saldo mínimo dentro del horizonte.
- `min_balance_date` (date | null) — cuándo ocurre el mínimo.
- `first_overdraft_date` (date | null) — primera fecha con déficit (PRO-05).
- `total_shortfall` (Decimal) — déficit acumulado (PRO-05).
- `events` (list[`ForecastEvent`]) — eventos del flujo (PRO-03/04/05):
  - `date`, `kind` (payment, recurring, msi_charge, etc.)
  - `direction` (`in` | `out`)
  - `description`, `amount` (Decimal, magnitud positiva)
  - `currency` — moneda original
  - `is_estimate` (bool) — si es estimado.
  - `covered` (bool) — si hay caja para cubrirlo.
  - `shortfall` (Decimal) — déficit si no se cubre.
  - `balance_after` (Decimal) — saldo proyectado después.
- `alerts` (list[`ForecastAlert`]) — alertas de sobregiro (PRO-05):
  - `date`, `description`, `shortfall` (Decimal)

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.
- `422` horizon_months fuera de rango.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/dashboard/forecast?horizon_months=12&cash_adjustment=10000.00" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## Notas de implementación

- **Fase 0:** Endpoints esqueletados; servicios retornan `NotImplementedError`.
- **DSH-01:** Dashboard consolidado.
- **DSH-02/03:** Totales mensuales en SQL; transfers nunca suman (TXN-02); madre-MSI nunca suma (MSI-03).
- **DSH-04:** Desglose por naturaleza (food, transport, etc.).
- **DSH-05:** Próximos compromisos (pagos vencidos, recurrentes programadas, etc.).
- **PRO-01..06:** Pronóstico de flujo con detección de sobregiro.
- **GLO-01:** Montos como strings en JSON.
- **GLO-02:** Fechas como `date` puro.
