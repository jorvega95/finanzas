# Inversiones (Investments)

Gestión de cuentas de inversión, portafolio, precios y patrimonio neto (INV-01..INV-06, PAT-01..PAT-02).

Una **inversión** es un activo (acciones, criptos, fondos) en una cuenta. El portafolio se valúa diariamente con precios en tiempo real (CoinGecko para crypto). Snapshots históricos permiten análisis de rendimiento. Patrimonio neto = activos − deuda TDC (PAT-01).

**Prefijo:** `/api/v1/investments`

---

## `GET /api/v1/investments/accounts`

**Para qué sirve:** Lista cuentas de inversión del espacio.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (list[`AccountOut`]):
- `id` (uuid)
- `name` (string)
- `kind` (`AccountKind`) — `brokerage`, `crypto_wallet`, `retirement`, etc.
- `is_active` (bool)

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/investments/accounts" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/investments/accounts`

**Para qué sirve:** Crea una cuenta de inversión. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`AccountCreate`):
- `name` (string, 1-80 chars)
- `kind` (`AccountKind`) — tipo de cuenta.

**Respuesta** `201` (`AccountOut`): cuenta creada.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio no encontrado; no-miembro.
- `422` validación (nombre vacío).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/investments/accounts \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Mi Broker",
    "kind": "brokerage"
  }' | jq .
```

---

## `POST /api/v1/investments/accounts/{account_id}/movements`

**Para qué sirve:** Registra operación (compra/venta) en la cuenta; retorna portafolio actualizado (INV-02).

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `account_id` (uuid) — ID de la cuenta.

**Query params:** ninguno

**Request body** (`MovementCreate`):
- `type` (`MovementType`) — `buy` o `sell`.
- `asset_symbol` (string, 1-60 chars) — símbolo (ej. `AAPL`, `BTC`).
- `asset_name` (string, optional, max 80 chars) — nombre descriptivo.
- `quantity` (Decimal, > 0) — cantidad (INV-01: hasta 10 decimales para crypto).
- `price` (Decimal, > 0, optional) — precio unitario. Si no se envía, se busca en proveedor.
- `currency` (string, opcional, default `USD`) — moneda del precio.
- `date` (date) — fecha de la operación.

**Respuesta** `201` (`PortfolioOut`): portafolio actualizado con:
- `total_value` (Decimal)
- `total_unrealized_pnl` (Decimal) — P&L no realizado mark-to-market hoy (FX-04).
- `total_realized_pnl` (Decimal) — P&L realizado acumulado.
- `holdings` (list[`HoldingValuation`]) — cada posición con:
  - `holding_id`, `account_id`, `account_name`, `kind`
  - `asset_symbol`, `asset_name`
  - `quantity`, `avg_cost`, `currency`
  - `price`, `price_fetched_at`, `price_source` (INV-03)
  - `value_base` (Decimal | null) — valuación en moneda base
  - `unrealized_pnl`, `realized_pnl`

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` cuenta o espacio no encontrado; no-miembro.
- `422` validación (quantity ≤ 0, asset_symbol vacío).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/investments/accounts/$ACCOUNT_ID/movements \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "buy",
    "asset_symbol": "AAPL",
    "asset_name": "Apple Inc.",
    "quantity": "10",
    "price": "150.00",
    "currency": "USD",
    "date": "2026-07-14"
  }' | jq .
```

---

## `GET /api/v1/investments/portfolio`

**Para qué sirve:** Valuación actual del portafolio completo (INV-06). P&L realizado y no realizado con FX-04 hoy.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (`PortfolioOut`): valuación completa.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/investments/portfolio" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/investments/prices`

**Para qué sirve:** Captura manual de precio para activos no-crypto (INV-04). Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`ManualPrice`):
- `symbol` (string, 1-60 chars) — símbolo del activo.
- `price` (Decimal, > 0)
- `currency` (string, opcional, default `MXN`)

**Respuesta** `200` (dict):
- `symbol` (string)
- `price` (string, Decimal)
- `currency` (string)

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio no encontrado; no-miembro.
- `422` validación (precio ≤ 0).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/investments/prices \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "CASA",
    "price": "2500000.00",
    "currency": "MXN"
  }' | jq .
```

---

## `POST /api/v1/investments/snapshot`

**Para qué sirve:** Snapshot manual del portafolio (INV-05). Job diario hace lo mismo automáticamente. Idempotente: mismo día → mismo snapshot.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (`SnapshotOut`):
- `date` (date) — fecha del snapshot.
- `total_value` (Decimal) — valor total del portafolio.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio no encontrado; no-miembro.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/investments/snapshot \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `GET /api/v1/investments/snapshots`

**Para qué sirve:** Historial de snapshots (últimos 90 por defecto).

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:**
- `limit` (int, opcional, default 90, max 365) — cantidad de días atrás.

**Request body:** ninguno

**Respuesta** `200` (list[`SnapshotOut`]): snapshots ordenados cronológicamente ascendente.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/investments/snapshots?limit=30" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/investments/net-worth/snapshot`

**Para qué sirve:** Snapshot de patrimonio neto (PAT-01). Activos (portafolio + otros) − deuda TDC del día. Idempotente.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (`NetWorthOut`):
- `date` (date)
- `assets` (Decimal) — valor total de activos.
- `liabilities` (Decimal) — deuda TDC.
- `net_worth` (Decimal) — assets − liabilities.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio no encontrado; no-miembro.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/investments/net-worth/snapshot \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `GET /api/v1/investments/net-worth`

**Para qué sirve:** Historial de patrimonio neto (últimos 90 días por defecto).

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:**
- `limit` (int, opcional, default 90, max 365)

**Request body:** ninguno

**Respuesta** `200` (list[`NetWorthOut`]): snapshots ordenados cronológicamente ascendente.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/investments/net-worth?limit=30" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## Notas de implementación

- **Fase 0:** Endpoints esqueletados; servicios retornan `NotImplementedError`.
- **INV-01:** Crypto quantities hasta 10 decimales (NUMERIC 28,10).
- **INV-02:** Operaciones (buy/sell) y cálculo de P&L realizado.
- **INV-03:** Precios de CoinGecko (default) o manual (INV-04). Interfaz `PriceProvider`.
- **INV-04:** Captura manual para no-crypto.
- **INV-05:** Snapshots diarios automáticos + manual.
- **INV-06:** Mark-to-market (FX-04) para P&L no realizado hoy.
- **PAT-01:** Patrimonio neto = activos − deuda TDC.
- **PAT-02:** Signed_balance para crédito/débito (TAR-06).
- **FX-03:** Tasa congelada por transacción.
- **FX-04:** Mark-to-market solo inversiones hoy.
- **GLO-01:** Montos y cantidades como strings en JSON.
