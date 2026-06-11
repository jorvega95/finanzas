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
