# Plan: Plataforma de Finanzas Personales

**Stack:** FastAPI + Supabase (Postgres + Auth) + React/TypeScript · **Alcance:** producto multi-tenant desde el inicio · **Fecha:** 2026-06-10 · **v2** (áreas de oportunidad integradas como requerimientos)

> Reglas de negocio detalladas (IDs referenciables, fórmulas, edge cases y casos de prueba): ver [`REGLAS_NEGOCIO.md`](REGLAS_NEGOCIO.md).

## Requerimientos consolidados

Originales: **R1** registro de gastos diarios · **R2** catálogos editables (categorías, métodos de pago) · **R3** TDC con ciclos, pagos y deuda · **R4** vista MSI restante · **R5** inversiones + crypto (CoinGecko) · **R6** dashboard entradas/salidas · **R7** login multi-proveedor (Google, email, teléfono) · **R8** espacios personales y compartidos.

Incorporados del análisis: **R9** transacciones recurrentes (suscripciones, renta) · **R10** presupuestos por categoría con alertas · **R11** multimoneda (MXN/USD mínimo) · **R12** patrimonio neto (activos − deudas) · **R13** importación CSV de estados de cuenta · **R14** recordatorios de fecha de pago TDC · **R15** inversiones no-crypto (CETES, fondos, acciones). Backlog sin fase: categorización automática por reglas.

---

## 1. Análisis de requerimientos y áreas de oportunidad

Tus 8 requerimientos están bien encaminados. Esto es lo que detecté al analizarlos:

### 1.1 El concepto clave que falta: "Espacios" (Spaces)

Tu requerimiento #8 (finanzas personales + finanzas con pareja) es en realidad un patrón de **workspaces multi-tenant**, no una funcionalidad de "familia" especial. Si lo modelas como espacios desde el día 1:

- Tu cuenta personal es un espacio con 1 miembro.
- "Familia" es un espacio con 2+ miembros y roles (owner/editor/viewer).
- **Todo** (transacciones, catálogos, tarjetas, inversiones) pertenece a un espacio, no a un usuario.
- Escala gratis a tu objetivo de producto: equipos, roomies, pequeños negocios.

Esto evita la migración dolorosa más común en apps de finanzas: pasar de `user_id` a `space_id` en todas las tablas cuando ya hay datos.

### 1.2 Transacciones unificadas (no "gastos" y "entradas" separados)

Tu req. #1 habla de compras y el #6 de entradas/salidas. Conviene **una sola tabla `transactions`** con `type: expense | income | transfer`. El tipo `transfer` (mover dinero entre cuentas propias, p. ej. pagar la TDC desde débito) es crítico para que el dashboard no cuente doble.

### 1.3 MSI: es un plan de pagos, no una compra

Una compra a MSI genera N mensualidades futuras. Cada mensualidad cae en un **ciclo de facturación** distinto según la fecha de corte. Modelo correcto: la compra (`transactions`) + un plan (`installment_plans`) + N cuotas generadas (`installments`) con fecha estimada de cargo. Así obtienes gratis:

- Saldo restante de MSI (req. #4).
- Pago mensual proyectado por tarjeta (req. #3).
- **Proyección de flujo de efectivo futuro** — sabes cuánto tienes ya comprometido en agosto, septiembre, etc. (oportunidad que no pediste pero es el mayor valor de capturar MSI).

### 1.4 Ciclos de TDC: más sutil de lo que parece

Con fecha de corte y fecha límite de pago puedes calcular el ciclo, pero ojo:

- Cortes el día 29/30/31 no existen en todos los meses → regla de "último día del mes".
- La fecha límite suele ser N días después del corte (típico 20), no un día fijo → guarda ambas representaciones y deja al usuario elegir.
- Una compra del día del corte puede caer en el ciclo actual o el siguiente según el banco → el usuario debe poder reasignar ciclo manualmente.
- Oportunidad: **recordatorios de pago** (push/email) días antes de la fecha límite. Es la feature que más retiene en este tipo de apps.

### 1.5 Seguridad de datos de tarjetas

No guardes el PAN completo ni CVV (te metería en territorio PCI-DSS). Guarda: alias, banco, red (Visa/MC/Amex), **últimos 4 dígitos**, límite de crédito, fecha de corte y días para pago. Es todo lo que necesitas para los cálculos.

### 1.6 API de precios crypto: CoinGecko (default)

- **CoinGecko Demo (gratis): 10,000 llamadas/mes con crédito plano** — 1 llamada = 1 crédito aunque pidas 250 monedas en batch — e **históricos de 1 año** incluidos. CMC en cambio cobra por data points y no da históricos en free tier; queda como proveedor alterno.
- Nota: la API pública de CMC **no expone el portafolio del usuario** — aunque uses CMC para ver tu wallet, los holdings se capturan manualmente con cualquier proveedor.
- La API key **nunca** debe vivir en el frontend → proxy en FastAPI con caché (1 batch cada 10 min ≈ 4,300 llamadas/mes, holgado).
- Históricos de CoinGecko sirven para **rellenar gráficas hacia atrás** al dar de alta un holding; hacia adelante mandan los snapshots propios (cron diario), que también resuelven el histórico de patrimonio neto.
- Proveedor abstraído tras interfaz `PriceProvider` (implementaciones: `CoinGeckoProvider` default, `CoinMarketCapProvider` alterno) — cambiar es una clase, no una refactorización.
- Backlog: APIs de exchanges (Binance, Bitso) para sincronizar holdings automáticamente y eliminar la captura manual.

### 1.7 Oportunidades incorporadas al plan

Ya son requerimientos (R9-R15); aquí el racional y dónde caen:

| Requerimiento | Por qué | Fase |
|---|---|---|
| **R9 Recurrentes** (suscripciones, renta) | El 30-50% de gastos típicos son fijos; auto-registrarlos elimina la fricción #1 | 1 |
| **R10 Presupuestos** por categoría con alertas | Convierte el registro pasivo en control activo | 3 |
| **R11 Multimoneda** (MXN/USD) | Crypto ya te obliga; barato el día 1, carísimo después | 0-1 (modelo) |
| **R12 Patrimonio neto** (activos − deudas) | Con deuda TDC + inversiones el cálculo es casi gratis | 4 |
| **R13 Importación CSV** | Capturar a mano mata la adherencia; los bancos MX exportan CSV/XLS | 6 |
| **R14 Recordatorios de pago TDC** | La feature que más retiene en apps de finanzas | 2 |
| **R15 Inversiones no-crypto** | El modelo `holdings` genérico lo permite sin costo extra | 4 |
| Categorización automática (reglas → ML) | Calidad de vida; empieza con reglas por descripción | Backlog |

### 1.8 Decisiones de diseño importantes

- **Dinero como enteros (centavos)**, nunca float. En Postgres `BIGINT` o `NUMERIC(14,2)`; en Python `Decimal`; en TS, enteros + formateo.
- **Soft-delete en catálogos** (req. #2): si eliminas la categoría "Comida" con 500 transacciones, se desactiva (`is_active=false`), no se borra. Las transacciones históricas conservan su categoría.
- **Catálogos por espacio con plantilla**: al crear un espacio se siembran categorías/métodos de pago predeterminados que el usuario edita.
- **Tipo de gasto** (fijo/variable/discrecional): mejor como atributo de la categoría (con override por transacción) que capturarlo en cada compra — menos fricción.

---

## 2. Arquitectura

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  React + TS     │     │  FastAPI (Python)     │     │  Supabase        │
│  (Vite, SPA)    │────▶│  - API REST /api/v1   │────▶│  - Postgres      │
│                 │     │  - Lógica de negocio  │     │  - Auth (JWT)    │
│  Móvil futuro:  │     │  - Verifica JWT       │     │  - Storage       │
│  React Native/  │     │    de Supabase        │     └─────────────────┘
│  Expo (mismo TS)│     │  - Proxy precios+caché│────▶ CoinGecko API (CMC alterno)
└─────────────────┘     │  - Jobs (APScheduler) │
                        └──────────────────────┘
```

**Por qué así:**

- **Supabase Auth** resuelve req. #7 completo (Google OAuth, email magic link/password, SMS) sin escribir código de seguridad. El frontend habla con Supabase para login; FastAPI solo **verifica el JWT** (JWKS) — stateless y simple.
- **FastAPI como única API de negocio** (no usar el cliente Supabase directo desde React para datos): la lógica de ciclos de TDC, MSI y agregaciones del dashboard vive en Python, testeada, y la app móvil la reutiliza tal cual. API-first = req. móvil futuro resuelto.
- **RLS de Supabase como segunda capa**: políticas Row-Level Security por `space_id` como defensa en profundidad, aunque FastAPI ya filtre.
- **Jobs**: APScheduler dentro de FastAPI basta al inicio (snapshot diario de precios, generación de transacciones recurrentes, recordatorios). Si crece → Celery/arq.

---

## 3. Modelo de datos (Postgres)

```
users  (gestionada por Supabase Auth: auth.users)
profiles              id (=auth uid), display_name, default_space_id, locale, ...

spaces                id, name, type(personal|shared), base_currency, created_by
space_members         space_id, user_id, role(owner|editor|viewer), joined_at
space_invites         space_id, email, role, token, expires_at

categories            id, space_id, name, icon, color, kind(expense|income),
                      expense_nature(fixed|variable|discretionary|null),
                      parent_id (subcategorías), is_active
payment_methods       id, space_id, name, type(cash|debit|credit_card|transfer|other),
                      credit_card_id (nullable), is_active

credit_cards          id, space_id, alias, bank, network, last4,
                      credit_limit, statement_day (1-28 o 'last'),
                      cutoff_day_policy(include|next_cycle),
                      payment_due_days (o payment_day), is_active
card_statements      id, credit_card_id, period_start, period_end,
                      due_date, computed_total, paid_amount, status

transactions          id, space_id, type(expense|income|transfer),
                      date, description, amount, currency,
                      category_id, payment_method_id, credit_card_id?,
                      installment_plan_id?, recurring_rule_id?,
                      notes, created_by, created_at
recurring_rules       id, space_id, template(jsonb), frequency, next_run,
                      end_date?, is_active                              (R9)
exchange_rates        base, quote, rate, date            (R11; fuente: Banxico/API FX)

installment_plans     id, space_id, credit_card_id, transaction_id,
                      total_amount, months, monthly_amount, start_date, status
installments          id, plan_id, number, amount, estimated_charge_date,
                      statement_id?, status(pending|charged|paid)

investment_accounts   id, space_id, name, kind(crypto|stocks|fixed_income|other)
holdings              id, account_id, asset_symbol, asset_name, quantity,
                      avg_cost, currency
asset_prices          symbol, price_usd, fetched_at, source (caché CoinGecko/CMC)
portfolio_snapshots   id, space_id, date, total_value, breakdown(jsonb)

budgets               id, space_id, category_id, month, amount,
                      alert_threshold (ej. 0.8)                          (R10)
reminders             id, space_id, kind(card_due|budget_alert|custom),
                      ref_id, fire_at, channel(email|push|in_app),
                      sent_at?, status                                   (R14)
import_batches        id, space_id, source(bank), file_name, row_count,
                      mapping(jsonb), status, created_at                 (R13)
                      → transactions.import_batch_id? (dedupe y rollback)
net_worth_snapshots   id, space_id, date, assets, liabilities,
                      net_worth, breakdown(jsonb)                        (R12)
```

Notas: montos en `NUMERIC(14,2)`; cada monto lleva `currency` y el espacio una `base_currency` — los agregados convierten con `exchange_rates` del día (R11); índices por `(space_id, date)` en transactions; RLS en todas las tablas con `space_id`. R15 no requiere tablas nuevas: `investment_accounts.kind` ya admite `stocks|fixed_income|other` con captura manual de precios.

---

## 4. Estructura del proyecto

Monorepo (un solo repo, deploy independiente):

```
finanzas/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app factory
│   │   ├── core/                    # config, seguridad (verificación JWT), deps
│   │   ├── db/                      # sesión SQLAlchemy, base
│   │   ├── models/                  # modelos SQLAlchemy (1 archivo por dominio)
│   │   ├── schemas/                 # Pydantic (request/response)
│   │   ├── api/v1/                  # routers: spaces, catalogs, transactions,
│   │   │                            #   cards, installments, investments, dashboard
│   │   ├── services/                # lógica: billing_cycles, msi, dashboard,
│   │   │                            #   prices (PriceProvider → CoinGecko|CMC), fx (R11),
│   │   │                            #   recurring (R9), budgets (R10),
│   │   │                            #   reminders (R14), imports (R13)
│   │   └── jobs/                    # APScheduler: snapshots precio/patrimonio,
│   │                                #   recurrentes, recordatorios, tipos de cambio
│   ├── alembic/                     # migraciones
│   ├── tests/                       # pytest (ciclos TDC y MSI: cobertura exhaustiva)
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/                     # cliente generado desde OpenAPI + TanStack Query
│   │   ├── auth/                    # supabase-js, AuthProvider, guards
│   │   ├── features/                # transactions/, catalogs/, cards/, msi/,
│   │   │                            #   investments/, dashboard/, spaces/, settings/
│   │   ├── components/ui/           # shadcn/ui
│   │   ├── lib/                     # formato de moneda, fechas
│   │   └── routes/                  # TanStack Router o React Router
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml               # dev local (opcional: supabase local)
└── PLAN.md
```

Organización del frontend por **features** (vertical), no por tipo de archivo — facilita extraer lógica compartida para la app móvil después.

---

## 5. Dependencias

**Backend (Python 3.12+):**

| Paquete | Uso |
|---|---|
| fastapi + uvicorn | API |
| sqlalchemy 2.x + alembic | ORM y migraciones |
| asyncpg | driver Postgres async |
| pydantic v2 + pydantic-settings | validación y config |
| pyjwt[crypto] | verificación de JWT de Supabase (JWKS) |
| httpx | cliente CoinGecko (y CMC alterno) |
| apscheduler | jobs |
| python-dateutil | aritmética de fechas (ciclos, MSI) |
| pytest + pytest-asyncio + freezegun | tests (freezegun es clave para probar ciclos de corte) |
| resend (o SMTP Supabase) | emails de recordatorio (R14) |
| API Banxico SIE (httpx) | tipo de cambio MXN/USD oficial (R11), gratuita |

**Frontend:**

| Paquete | Uso |
|---|---|
| react 18 + typescript + vite | base |
| @supabase/supabase-js | auth |
| @tanstack/react-query | estado de servidor, caché |
| react-router (o TanStack Router) | rutas |
| react-hook-form + zod | formularios (captura rápida de gastos) |
| tailwindcss + shadcn/ui | UI (accesible, rápida de construir) |
| recharts | gráficas del dashboard |
| openapi-typescript / orval | tipos TS generados del OpenAPI de FastAPI → contrato único |
| date-fns | fechas |
| dinero.js (opcional) | manejo seguro de montos |

**Infra sugerida:** Supabase (DB+Auth, free tier) · backend en Railway/Render/Fly.io · frontend en Vercel/Cloudflare Pages. Costo inicial: ~$0-5/mes.

---

## 6. Plan de implementación

Cada fase termina en algo usable. Estimaciones para tiempo parcial.

### Fase 0 — Fundación (1 semana) → R7, base de R8 y R11
Monorepo, Supabase project, FastAPI esqueleto + verificación JWT, Vite + login (Google + email; teléfono/SMS al final, requiere Twilio), CI básico (lint, tests), Alembic con `profiles`, `spaces`, `space_members`. Seed de espacio personal al registrarse. `base_currency` en el espacio y `currency` en los modelos desde la primera migración (R11).
**Sale:** puedes hacer login y existe tu espacio personal.

### Fase 1 — Registro de gastos + catálogos + recurrentes (2 semanas) → R1, R2, R9, R11
CRUD de categorías y métodos de pago (seed por defecto, soft-delete). CRUD de transacciones (expense/income) con formulario optimizado para captura en <10 segundos. Lista con filtros (fecha, categoría, tipo). Reglas recurrentes (R9): plantilla + frecuencia, job diario que genera las transacciones y las marca para revisión. Job de tipos de cambio (R11) y conversión a `base_currency` en listados.
**Sale:** registras tu día a día y las suscripciones se capturan solas. **Empieza a usarla tú mismo desde aquí.**

### Fase 2 — TDC, MSI y recordatorios (2-3 semanas) → R3, R4, R14
CRUD de tarjetas. Motor de ciclos de facturación (`billing_cycles.py` — el código más delicado del proyecto, tests primero). Compras a MSI → plan + cuotas. Vista por tarjeta: ciclo actual, pago proyectado, deuda total, MSI restantes. Vista MSI global con proyección de meses futuros. Recordatorios (R14): job que crea avisos N días antes de la fecha límite, canal in-app + email (Resend/SMTP de Supabase); push queda para la PWA.
**Sale:** sabes cuánto y cuándo pagar cada tarjeta, y la app te lo recuerda.

### Fase 3 — Dashboard + presupuestos (2 semanas) → R6, R10
Resumen mensual: ingresos vs gastos, por categoría, por naturaleza (fijo/variable/discrecional), tendencia 6 meses, próximos pagos de TDC. Presupuestos por categoría (R10): barra de avance en el dashboard y alerta al cruzar el umbral (reusa el canal de R14). Endpoints de agregación en SQL (no agregues en JS).
**Sale:** la vista que abres cada mañana, con control activo del gasto.

### Fase 4 — Inversiones + patrimonio neto (2 semanas) → R5, R12, R15
Cuentas de inversión y holdings. Crypto (R5): proxy CoinGecko en FastAPI con caché (TTL 10 min) + snapshot diario; backfill de gráficas con históricos del free tier. No-crypto (R15): CETES/fondos/acciones con precio de captura manual, mismo modelo. Vista de portafolio: valor actual, P&L vs costo promedio, evolución con snapshots. Patrimonio neto (R12): job diario que persiste activos − deuda TDC en `net_worth_snapshots` y gráfica histórica.
**Sale:** portafolio completo + patrimonio neto con historia.

### Fase 5 — Espacios compartidos (1 semana) → R8
Invitaciones por email, roles, switcher de espacio en la UI, RLS verificada con tests. (El modelo existe desde Fase 0; aquí solo se expone.)
**Sale:** espacio compartido con tu pareja.

### Fase 6 — Importación y pulido (continuo) → R13
Importación CSV (R13): wizard de mapeo de columnas por banco, dedupe contra existentes, `import_batches` con rollback. PWA instalable (puente barato antes de React Native). Login por teléfono si aún pendiente. Exportación de datos. Backlog: categorización automática por reglas.

### Móvil (futuro)
Con la API ya completa: **React Native + Expo** reutilizando tipos TS, cliente API y supabase-js. Antes de eso, la PWA de la Fase 6 cubre el 80% del caso de uso móvil (capturar gastos al vuelo) y habilita push para R14.

---

## 7. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Lógica de ciclos TDC con bugs (meses cortos, zona horaria) | Tests exhaustivos con freezegun; fechas siempre `date` (no datetime) en lógica de ciclos; permitir reasignación manual de ciclo |
| Free tier CoinGecko insuficiente | Caché server-side; 1 batch c/10 min ≈ 4,300 de 10,000 llamadas/mes (crédito plano por llamada); fallback a CMC vía `PriceProvider` |
| Fricción de captura manual → abandono | Formulario ultra-rápido, recurrentes, importación CSV en Fase 6 |
| Errores de redondeo en dinero | `Decimal`/`NUMERIC` siempre; tests de suma de cuotas MSI = total exacto (la última cuota absorbe el residuo) |
| Lock-in Supabase | Es Postgres estándar + JWT estándar; SQLAlchemy y Alembic hacen la DB portable |
| Recurrentes generan transacciones erróneas (R9) | Se crean con flag "por revisar"; idempotencia por (rule_id, fecha) |
| Conversión FX inconsistente en agregados (R11) | Tasa del día de la transacción persistida en `exchange_rates`; un solo servicio `fx` para toda conversión |
| Importación CSV duplica transacciones (R13) | Hash por (fecha, monto, descripción normalizada) + revisión manual de colisiones; rollback por batch |

---

## Próximo paso sugerido

Fase 0: crear el monorepo con el esqueleto funcionando (login incluido). Dime cuándo y lo construimos.

---

*Historial: v1 (2026-06-10) plan inicial · v2 (2026-06-10) R9-R15 integrados al modelo de datos y fases · v2.1 (2026-06-10) reglas de negocio detalladas en REGLAS_NEGOCIO.md · v2.2 (2026-06-10) CoinGecko como proveedor de precios default, CMC alterno.*
