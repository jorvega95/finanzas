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
