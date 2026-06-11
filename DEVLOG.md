# DEVLOG — Bitácora de iteraciones

Registro de lo hecho en cada fase/iteración. Las fases vienen de `PLAN.md` §6;
las reglas, de `REGLAS_NEGOCIO.md`. Regla del bucle: **no se avanza de fase si
algún test (de esta fase o anteriores) falla.**

---

## Iteración 0 — Fase 0: Fundación (2026-06-10)

**Objetivo (PLAN §6 Fase 0):** login + espacio personal al registrarse, modelo
base con multimoneda desde la primera migración, CI básico.

### Backend

- **Modelos** (`app/models/`): `Profile`, `Space` (con `base_currency` FX-01 y
  `timezone` GLO-02), `SpaceMember` (roles ESP-03), `Category` y
  `PaymentMethod` (necesarios para el seed CAT-02; CRUD llega en Fase 1).
  Mixins de auditoría GLO-04 (`created_by/created_at/updated_at`).
- **Migración inicial** `alembic/versions/0001_initial.py` (escrita a mano —
  no hay Postgres local; se valida contra Supabase al configurar el proyecto).
- **Seguridad** (`core/security.py`): verificación de JWT de Supabase (HS256,
  audience `authenticated`). FastAPI no emite tokens.
- **Deps** (`core/deps.py`): `get_current_user` (provisioning perezoso ESP-01:
  el primer request autenticado crea perfil + espacio "Personal" + membresía
  owner + seed), `get_active_space` vía header `X-Space-Id` con **404 para
  no-miembros** (GLO-05), `require_role` (ESP-03).
- **Servicios**: `services/spaces.py` (provisioning idempotente, espacios
  compartidos), `services/catalogs.py` (seed CAT-02 con naturalezas CAT-03),
  `core/text.py` (normalización unaccent+lower portable para CAT-01).
- **API**: `GET /api/v1/me` (bootstrap), `GET/POST /api/v1/spaces`,
  `GET/PATCH /api/v1/spaces/{id}` (rename solo owner).

### Frontend

- Login (`features/auth/LoginPage.tsx`): Google OAuth + email/contraseña
  (alta y acceso), es-MX. Aviso claro si falta configurar Supabase en `.env`.
- `AuthProvider` (sesión Supabase) + rutas protegidas (`routes/index.tsx`).
- **Tema light/dark** (`lib/theme.tsx`): clase `dark` en `<html>`, persistido
  en localStorage, fallback a `prefers-color-scheme`; toggle en login y header.
- Shell de la app (`components/AppLayout.tsx`): sidebar, espacio activo,
  páginas placeholder para fases futuras.
- `api/client.ts` usa el proxy de Vite si no hay `VITE_API_URL`.

### Tests (8/8 ✅) — `backend/tests/test_spaces.py`

| Regla | Test |
|---|---|
| ESP-01 | provisioning crea perfil + espacio personal + owner + default_space_id |
| ESP-01/02 | provisioning idempotente; nunca un 2.º espacio personal |
| CAT-02/03 | seed exacto de categorías (con naturaleza) y métodos de pago |
| ESP-02 | crear espacio compartido (con seed) |
| GLO-05 (caso 8) | no-miembro recibe **404**, no 403, en GET y PATCH |
| ESP-03 | rename solo owner (editor → 403) |
| Auth | sin token / token inválido → 401 |

Calidad: `ruff check` ✅ · `ruff format` ✅ · `mypy app` (strict) ✅ ·
`npm run build` ✅ · CI en `.github/workflows/ci.yml`.

### Decisiones / notas

- **Tests con SQLite in-memory (aiosqlite)**: no hay Postgres/Docker local.
  Los modelos usan solo tipos portables; la unicidad CAT-01 se resuelve con
  columna `name_normalized` calculada en Python (equivalente a
  `unaccent+lower`) para comportamiento idéntico en ambos motores.
- **Provisioning perezoso**: Supabase es dueño del registro; el backend ve al
  usuario por primera vez en su primer request autenticado y ahí ejecuta
  ESP-01 (idempotente).
- `payment_methods.credit_card_id` queda como UUID sin FK hasta que exista
  `credit_cards` (Fase 2, CAT-07).
- RLS en Supabase se escribe/verifica en Fase 5 según PLAN §6.
- **Pendiente de configuración del usuario**: crear el proyecto Supabase y
  llenar `backend/.env` (`SUPABASE_JWT_SECRET`, `DATABASE_URL`) y
  `frontend/.env` (URL + anon key); luego `uv run alembic upgrade head`.

---

## Iteración 1 — Fase 1: Transacciones + catálogos + recurrentes + FX (2026-06-10)

**Objetivo (PLAN §6 Fase 1):** registrar el día a día, catálogos editables,
suscripciones que se capturan solas, multimoneda.

### Backend

- **Modelos**: `Transaction` (TXN-01..06: tipos expense/income/transfer,
  `fx_rate_to_base` congelada FX-03, `needs_review`, constraint único
  `(recurring_rule_id, scheduled_date)` para REC-02), `RecurringRule` +
  `RecurringTombstone` (REC-01/03), `ExchangeRate` (FX-02). Migración `0002`.
- **`services/transactions.py`**: validaciones TXN-01 (categoría de kind
  acorde, método activo), TXN-02 (transfer: origen≠destino, sin categoría),
  TXN-03 (fecha futura máx. +1 año, hoy en tz del espacio), TXN-04 (MXN/USD),
  TXN-05 (editar mantiene trazabilidad y no regenera), FX-03 (tasa congelada:
  solo cambia si cambia fecha/moneda u override manual). Borrar instancia
  recurrente ⇒ tombstone (REC-03).
- **`services/recurring.py`**: generador puro de ocurrencias (weekly/biweekly/
  monthly con día N ajustado o último día/yearly), job idempotente con
  catch-up (REC-02/05), auto-pausa si categoría/método inactivo (REC-04).
- **`services/fx.py`**: `get_rate` (tasa de la fecha o previa más cercana,
  fallback inverso), `sync_usd_mxn_rate` con Banxico FIX y carry-forward en
  inhábiles (FX-02), upsert idempotente.
- **`services/catalogs.py` CRUD**: CAT-01 (unicidad unaccent+lower), CAT-04
  (desactivar/reactivar), CAT-05 (última activa protegida), CAT-06 (2 niveles,
  herencia), CAT-07 (método credit_card solo vía tarjeta), GLO-03 (delete
  físico solo sin referencias).
- **Routers**: `/catalogs/*`, `/transactions` (filtros + paginación + confirm),
  `/recurring-rules` (+`/generate` manual). Mutaciones requieren editor+
  (ESP-03); lecturas cualquier miembro; no-miembro 404.
- **Scheduler** (`jobs/scheduler.py`): job horario de recurrentes (idempotente
  ⇒ seguro multi-tz) y job diario FX. Activable con `SCHEDULER_ENABLED=true`.
- Fix notable: la columna `date` de `Transaction` sombreaba el tipo
  `datetime.date` en el cuerpo de la clase y rompía la nulabilidad de
  `scheduled_date` ⇒ se usa `dt.date`.

### Frontend

- `SpaceProvider`: carga `/me`, fija `X-Space-Id` global (GLO-05) y expone el
  espacio activo.
- **Transacciones** (`features/transactions/`): captura rápida (tipo, monto,
  fecha, categoría, método, transfer con desde/hacia, moneda MXN/USD),
  bandeja "Por confirmar" (REC-03: confirmar 1 tap / descartar) y lista del
  mes con filtros. Montos siempre strings (GLO-01).
- **Ajustes** (`features/settings/`): CRUD de categorías (con naturaleza
  visible) y métodos de pago (desactivar/reactivar), y gestión de gastos
  recurrentes (crear, pausar/reanudar).

### Tests (30/30 ✅, incluye los 8 de Fase 0)

| Regla | Test |
|---|---|
| CAT-01 | unicidad case/acentos-insensible (cat y métodos) |
| CAT-04/05 | desactivación oculta de formularios, reactivable; última activa protegida |
| CAT-06 | herencia kind/naturaleza; tercer nivel rechazado |
| CAT-07 | método credit_card manual rechazado |
| GLO-03 | delete físico solo sin referencias (409 si hay) |
| TXN-01 | campos obligatorios, kind acorde, monto > 0 |
| TXN-02 | transfer: origen≠destino, sin categoría |
| TXN-03 | fecha futura cap +1 año (freezegun) |
| TXN-04 | EUR rechazada |
| FX-03 (caso 6) | tasa congelada al editar; re-resuelve al cambiar fecha; override manual |
| FX-02 | carry-forward en domingo + idempotencia del job |
| REC-02/05 (caso 5) | 2 corridas ⇒ 0 duplicados; catch-up enero→junio = 5 instancias |
| REC-01 | día 31 ajustado a feb 28; weekly con end_date |
| REC-03 | descartar ⇒ tombstone (no regenera); confirmar con ajuste de monto |
| REC-04 | editar regla no toca generadas; auto-pausa con categoría inactiva |
| ESP-03/GLO-05 | viewer no muta catálogos (403); cross-space 404 |

Calidad: ruff ✅ · mypy strict ✅ · `npm run build` ✅.

### Decisiones / notas

- Plantilla de regla recurrente con columnas explícitas (no jsonb) para
  paridad SQLite/Postgres en tests.
- El job de recurrentes corre **cada hora** y es idempotente — así cada
  espacio genera poco después de su medianoche local sin un scheduler por tz.
- `fx_rate_to_base` es NULL cuando la moneda es la base (tasa 1 implícita).
- Agregados (DSH-02: transfers fuera, etc.) se prueban en Fase 3 con los
  endpoints de dashboard — los predicados vivirán en un solo lugar (DSH-03).

---

## Iteración 2 — Fase 2: TDC, MSI y recordatorios (2026-06-11)

**Objetivo (PLAN §6 Fase 2):** saber cuánto y cuándo pagar cada tarjeta, MSI
como plan de pagos, y que la app lo recuerde. Tests primero para el código
más delicado.

### Backend

- **`services/billing_cycles.py`** (funciones puras, tests ANTES de
  implementar): `statement_cutoff` (TDC-02: 1-28 o `last`, min con fin de
  mes), `cycle_for_purchase` (TDC-03/05 con `cutoff_day_policy`
  include/next_cycle), `due_date_for` (TDC-04: `payment_due_days` o primer
  `payment_day` posterior), `next_cutoff` (proyección MSI-04).
- **Modelos**: `CreditCard` (TDC-01: solo last4, jamás PAN/CVV; constraint
  "exactamente uno" entre due_days/payment_day), `CardStatement` (único por
  tarjeta+corte, `applied_credit` para TDC-10), `InstallmentPlan` +
  `Installment` (MSI-01..05), `Reminder` (único por statement+offset+canal,
  REM-02). `transactions.statement_id` nuevo. Migración `0003`.
- **`services/cards.py`**: alta con método de pago auto (CAT-07) y seed
  "Comisiones e intereses" (TDC-13); statements materializados on-demand
  (TDC-11); asignación de cargos al ciclo (TDC-05/TXN-06) al crear/editar
  transacciones; **cierre** (TDC-07): cuotas MSI del ciclo pasan a `charged`,
  saldo a favor del statement anterior se aplica como `applied_credit`
  (TDC-10), recordatorios programados (REM-01); estados TDC-08 con
  `is_overdue` como flag; pagos como transfer asignado a statement con
  excedente que viaja al siguiente cierre; deuda en 3 números (TDC-09);
  reasignación de ciclo ±1 con recálculo de ambos statements (TDC-06);
  desactivación que sigue cerrando ciclos (TDC-12).
- **`services/msi.py`**: `split_installments` (MSI-02: ROUND_FLOOR + última
  cuota absorbe residuo), calendario de cuotas proyectado con el motor de
  ciclos (MSI-04), conversión compra→plan con MSI-09 (moneda tarjeta),
  exclusión de la madre en totales (MSI-03), liquidación anticipada con cargo
  único en el ciclo abierto (MSI-07), borrado bloqueado con cuotas cargadas
  (MSI-08), vista por plan y proyección mes×tarjeta (MSI-06).
- **`services/reminders.py`**: programación a due_date−N por canal
  (REM-01/04), unicidad y reintentos (REM-02), mensaje con alias sin last4
  (REM-03), cancelación al pagar.
- **API**: `/cards` (CRUD + deuda TDC-09 + statements + pagos + cierre manual
  + bandeja de notificaciones), `/installment-plans` (crear desde compra,
  resumen, proyección, liquidar), `/transactions/{id}/move-cycle` (TDC-06).
- **Scheduler**: job horario de cierre de statements + disparo de
  recordatorios (idempotente, multi-tz).

### Frontend

- **Tarjetas** (`features/cards/`): alta segura (aviso de que solo se guarda
  last4), deuda en 3 números + total por tarjeta, statements con estados y
  flag vencido, pago con método origen y statement destino, botón de cierre
  manual de ciclos, recordatorios visibles.
- **MSI** (`features/msi/`): convertir compra con tarjeta a plan, barra de
  progreso de cuotas, detalle por cuota, liquidación anticipada, tabla de
  comprometido por mes × tarjeta.

### Tests (58/58 ✅ — Fases 0+1+2 juntas)

| Caso | Test |
|---|---|
| Obligatorio 1 (TDC-02/04) | corte `last` feb bisiesto/no + corte 28 los 12 meses + due `last`+20 |
| Obligatorio 2 (TDC-05) | compra el día del corte con `include` y `next_cycle` |
| Obligatorio 3 (MSI-02) | 1000/3 ⇒ 333.33+333.33+333.34; Σ==total en 1000 casos (hypothesis) |
| Obligatorio 4 (MSI-03) | compra 12,000 a 12 MSI ⇒ statement refleja 1,000, nunca 13,000 |
| Obligatorio 7 (TDC-10) | pago de 800 sobre 500 ⇒ 300 a favor; siguiente cierre 300−300=0 ⇒ paid |
| TDC-01/CAT-07/TDC-13 | validaciones de alta; método auto; categoría comisiones |
| TDC-07/08/11 | cierre idempotente, due_date, statement abierto materializado |
| TDC-06 | mover cargo a ciclo anterior y recálculo |
| TDC-12 | tarjeta inactiva no acepta cargos pero cierra ciclos |
| MSI-05/06/07/08/09 | ciclo de vida de cuotas, proyección, liquidación, borrado, moneda |
| REM-01/02/03 | programación, no-duplicación, cancelación al pagar, sin last4 |
| GLO-05 | tarjetas cross-space ⇒ 404 |

Calidad: ruff ✅ · mypy strict ✅ · `npm run build` ✅.

### Decisiones / notas

- `computed_total` puede ser negativo (crédito que sigue viajando): la
  fórmula `saldo_a_favor = max(paid − computed_total, 0)` hace que el
  excedente se arrastre solo entre cierres consecutivos.
- Pagos (transfers) abonan a `paid_amount` del statement asignado; los
  income en tarjeta se tratan como devoluciones que restan del total del
  ciclo.
- El statement_day de la UI se limita a 1-28 o `last` (TDC-02), y eso mismo
  valida el alta de tarjeta reutilizando el motor de ciclos.

---

## Iteración 3 — Fase 3: Dashboard y presupuestos (2026-06-11)

**Objetivo (PLAN §6 Fase 3):** la vista que abres cada mañana, con control
activo del gasto.

### Backend

- **`services/dashboard.py`** — EL único dueño de los predicados de
  gasto/ingreso (DSH-03): `expense_predicates` excluye transfers (TXN-02),
  madres MSI (MSI-03) y fechas futuras (TXN-03); cuotas MSI cargadas entran
  con categoría/naturaleza/tasa de la compra original. Conversión a base en
  SQL con tasa congelada (`amount × COALESCE(fx_rate_to_base, 1)`, FX-05) y
  cuantización ROUND_HALF_EVEN (GLO-01).
  - DSH-02: ingresos/gastos/neto del mes.
  - DSH-04 doble vista: devengado vs flujo (gastos sin TDC + pagos de
    tarjeta detectados como transfers a métodos credit_card).
  - DSH-03: por categoría raíz (roll-up CAT-06), por naturaleza
    (COALESCE(override, categoría), CAT-03), tendencia 6 meses con los mismos
    predicados.
  - DSH-05: próximos compromisos (statements por vencer con flag overdue,
    cuotas MSI ≤45 días, próxima ocurrencia de cada recurrente) ordenados.
- **`services/budgets.py`** (PRE-01..04): presupuesto único por categoría
  raíz+mes, consumo reutilizando los predicados de dashboard restringidos a
  la categoría y sus hijas, copia en bloque del mes anterior, alertas únicas
  por nivel (umbral y 100%) vía reminders (PRE-03) integradas al job horario.
- **API**: `GET /dashboard/summary?month=` (un payload con todo),
  `/budgets` CRUD + `/copy` + `/check-alerts`. Migración `0004` (budgets).

### Frontend

- **Dashboard** (`features/dashboard/`): toggle Devengado/Flujo con tooltip
  explicativo (DSH-04), tarjetas de totales, tendencia 6 meses (línea),
  gasto por categoría (barras), naturaleza (dona), próximos compromisos con
  chip "Vencido", y sección de presupuestos con barras de avance
  (verde→ámbar≥80%→rojo si excedido), alta y "repetir mes anterior".

### Tests (67/67 ✅ — Fases 0..3)

| Regla | Test |
|---|---|
| DSH-02 + TXN-02/03 | transfers nunca suman; gasto futuro excluido hasta su fecha |
| Caso obligatorio 4 | MSI 12,000×12 ⇒ mes = 1,000 en totales, categoría y naturaleza |
| DSH-04 | compra TDC: devengado sí, flujo no; al pagar: flujo sí, devengado igual |
| DSH-03 + CAT-06 + FX-05 | subcategoría suma al padre; USD con tasa congelada |
| DSH-03 | tendencia == resumen (mismos predicados) |
| DSH-05 | card_due + msi_quota + recurring ordenados por fecha |
| PRE-01 | único por categoría+mes (409); solo raíz de gasto; copy idempotente |
| PRE-02 | consumo con subcategorías, sin transfers, variación PRE-04 |
| PRE-03 | alerta una vez por nivel (80% y 100%), cero spam |

Calidad: ruff ✅ · mypy strict ✅ · `npm run build` ✅.

### Decisiones / notas

- Los pagos de TDC se identifican en flujo de caja como transfers cuyo
  método destino es `type=credit_card` — sin marcar nada extra.
- Las alertas de presupuesto reutilizan la tabla/canales de reminders
  (REM-04) con `offset_days` como nivel (80/100) para la unicidad.
- `to_money()` cuantiza todo resultado agregado a 2 decimales
  ROUND_HALF_EVEN (GLO-01) tras el producto monto×tasa.

---

## Iteración 4 — Fase 4: Inversiones + patrimonio neto (2026-06-11)

**Objetivo (PLAN §6 Fase 4):** portafolio completo (crypto + no-crypto) y
patrimonio neto con historia.

### Backend

- **Modelos** (`models/investments.py`): `InvestmentAccount` (kinds crypto/
  stocks/fixed_income/other — R15 sin tablas extra), `Holding` con
  `NUMERIC(28,10)` para cantidades (INV-01) y `realized_pnl` acumulado,
  `InvestmentMovement` (INV-02: nunca edición directa), `AssetPrice` (caché +
  manuales), `PortfolioSnapshot` y `NetWorthSnapshot` (únicos por
  espacio+día). Migración `0005`.
- **`services/prices.py`**: interfaz `PriceProvider` con `CoinGeckoProvider`
  default (1 batch `/simple/price` por refresh — crédito plano) y
  `CoinMarketCapProvider` alterno. Caché server-side TTL 10 min en
  `asset_prices`; si el proveedor falla se sirve el último precio con su
  `fetched_at` visible (INV-03). Precios manuales `source=manual` que el
  refresh nunca pisa (INV-04). API key solo backend.
- **`services/investments.py`**: movimientos INV-02 (buy: promedio
  ponderado; sell: qty baja, avg intacto, P&L realizado registrado; deposit
  con precio re-pondera, withdraw solo resta; venta > posición ⇒ 422).
  Valuación INV-06/FX-04 con tasa DEL DÍA (mark-to-market) separando P&L
  realizado/no realizado. Snapshots INV-05 idempotentes por día — el
  histórico jamás se reconstruye con precios actuales. PAT-01: patrimonio =
  snapshot de portafolio − Σ deuda TDC (TDC-09 a+b+c), job tras INV-05.
- **API**: `/investments/accounts(+movements)`, `/portfolio`, `/prices`
  (manual), `/snapshot(s)`, `/net-worth(+snapshot)`. Job diario 23:50 MX.

### Frontend

- **Inversiones** (`features/investments/`): tarjetas de totales (valor,
  P&L no realizado/realizado, patrimonio), alta de cuentas y movimientos,
  tabla de holdings con precio (✎ si es manual), formulario de precio manual,
  gráficas de evolución del portafolio y patrimonio neto, y la nota PAT-02
  ("patrimonio = inversiones − deuda TDC") visible.

### Tests (73/73 ✅ — Fases 0..4)

| Regla | Test |
|---|---|
| INV-02 | avg ponderado (100+200⇒150); sell: qty↓, avg intacto, P&L=15; venta>posición 422; deposit/withdraw |
| INV-01 | cantidad con 10 decimales intacta |
| INV-03 | TTL: 2.ª consulta sin llamadas; proveedor caído ⇒ caché con fetched_at |
| INV-04 | precio manual CETES en MXN, `source=manual` |
| INV-06/FX-04 | valuación con tasa de HOY (20), no la histórica (17) |
| INV-05 | snapshot idempotente; histórico congelado aunque el precio cambie |
| PAT-01 | patrimonio = 300 activos − 700 deuda TDC = −400; idempotente |

Calidad: ruff ✅ · mypy strict ✅ · `npm run build` ✅.

### Decisiones / notas

- Crypto usa el **id de CoinGecko** como `asset_symbol` (bitcoin, ethereum) —
  documentado en el placeholder de la UI.
- La caché de precios commitea dentro de `get_prices` para sobrevivir a
  requests de solo lectura.
- INV-03b (backfill histórico) es opcional ("PUEDE") y queda en backlog; el
  modelo ya trae `source=backfill` reservado.

---

## Iteración 5 — Fase 5: Espacios compartidos (2026-06-11)

**Objetivo (PLAN §6 Fase 5):** invitaciones, roles, switcher de espacio y RLS.
(El modelo multi-tenant existe desde Fase 0; aquí se expone.)

### Backend

- **`SpaceInvite`** (ESP-04): token urlsafe de un solo uso, expiración 7
  días, re-invitar al mismo email reemplaza la pendiente. **Claim** por dos
  vías: automático al registrarse (en el provisioning ESP-01, por email) y
  endpoint `POST /invites/claim` con verificación de email (fallos siempre
  404, sin filtrar — GLO-05).
- **Miembros**: `GET /spaces/{id}/members`, `PATCH .../members/{uid}` (rol),
  `DELETE .../members/{uid}` (remover/salirse). ESP-05: el último owner no
  puede degradarse ni salir — primero transfiere. ESP-07: las transacciones
  del removido permanecen con su `created_by`.
- **ESP-06**: `DELETE /spaces/{id}` exige el nombre exacto, borra en cascada
  y deja notificación in-app a cada miembro (en su espacio personal, que
  sobrevive al cascade); `default_space_id` de los afectados regresa a su
  personal (fallback ESP-01). El espacio personal jamás se elimina.
- **Migración `0006`**: tabla `space_invites` + **RLS** para Postgres/
  Supabase: función `is_space_member(uuid)` (SECURITY DEFINER sobre
  `auth.uid()`) y políticas por `space_id` en las 13 tablas de dominio, más
  políticas especiales (profiles=self, installments vía plan, holdings vía
  cuenta). En SQLite (tests) la sección RLS se omite — FastAPI filtra primero.

### Frontend

- **Switcher de espacio** en el header (👥 marca los compartidos); al cambiar
  se invalida TODO el caché de queries (otro tenant).
- **Ajustes → Espacio**: miembros con rol editable (owner), invitar por email
  con rol, lista de invitaciones pendientes con "copiar token", reclamar
  token, crear espacio compartido, salir del espacio y eliminar espacio con
  confirmación de nombre exacto.

### Tests (79/79 ✅ — Fases 0..5)

| Regla | Test |
|---|---|
| ESP-04 | re-invitar reemplaza; token viejo 404; email ajeno 404; claim ok con rol; 2.º claim 404 |
| ESP-04 | invitación expirada 404; auto-claim al registrarse |
| ESP-03 | editor no invita/lista/cambia roles (403); no-miembro 404 |
| ESP-05 | único owner no se degrada ni sale (422); transferir y luego sí |
| ESP-07 | transacciones del removido persisten con created_by; removido ve 404; salirse OK |
| ESP-06 | personal nunca; nombre incorrecto 422; cascada + 2 notificaciones |

Calidad: ruff ✅ · mypy strict ✅ · `npm run build` ✅.

### Decisiones / notas

- El email de la invitación se envía en Fase 6 (Resend); mientras, el owner
  comparte el token (visible solo para owners).
- La notificación de ESP-06 se guarda en el espacio **personal** de cada
  miembro porque las del espacio borrado morirían con el cascade.
- RLS usa una función `SECURITY DEFINER` para evitar recursión de políticas
  sobre `space_members`.

---
