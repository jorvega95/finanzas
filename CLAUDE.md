# CLAUDE.md — Finanzas

App de finanzas personales multi-tenant. Monorepo: `backend/` (FastAPI + SQLAlchemy async + Supabase Postgres/Auth) y `frontend/` (React 18 + TypeScript + Vite + Tailwind v4 + TanStack Query).

## Documentos fuente de verdad (locales, gitignored — SÍ existen en disco)

- **`REGLAS_NEGOCIO.md`** — ~80 reglas de negocio con IDs estables (`TDC-05`, `MSI-02`, `GLO-01`...). **Léelo SIEMPRE antes de implementar cualquier feature**: busca el dominio (ESP, CAT, TXN, TDC, MSI, REC, FX, PRE, REM, INV, PAT, IMP, DSH) y cumple cada regla aplicable.
- **`PLAN.md`** — arquitectura, modelo de datos completo (§3), fases de implementación (§6) y riesgos.

Si una decisión no está cubierta por una regla, propónla al usuario y, si se aprueba, agrégala a `REGLAS_NEGOCIO.md` con ID nuevo antes de codificar.

## Flujo de trabajo por reglas

1. Lee las reglas del dominio en `REGLAS_NEGOCIO.md`.
2. Escribe los tests primero para lógica delicada (ciclos TDC, MSI, FX). Los 8 "casos de prueba obligatorios" al final de `REGLAS_NEGOCIO.md` son bloqueantes.
3. Referencia los IDs de regla en docstrings, tests y commits: `feat(tdc): motor de ciclos [TDC-02..TDC-05]`, `test: MSI-02 property-based`.
4. Una regla sin test que la cubra no está terminada.

## Convenciones NO negociables

- **Dinero**: `Decimal` / `NUMERIC(14,2)`, redondeo `ROUND_HALF_EVEN` salvo regla específica (MSI-02 usa `ROUND_FLOOR` + última cuota absorbe residuo). Prohibido `float` en cálculos monetarios, también en TS (GLO-01). Cantidades de crypto: `NUMERIC(28,10)` (INV-01).
- **Fechas de negocio**: `date` puro, nunca `datetime`, en ciclos/MSI/recurrentes/presupuestos (GLO-02). En el frontend, strings `YYYY-MM-DD` parseados como fecha local (ver `src/lib/dates.ts`).
- **Multi-tenancy**: toda tabla de dominio lleva `space_id`; toda query filtra por el espacio activo (GLO-05). Usuario sin membresía ⇒ **404, no 403**. Permisos por rol según matriz ESP-03.
- **Transfers nunca suman** en ingresos/gastos (TXN-02). **La transacción-madre MSI nunca suma** en agregados — solo sus cuotas (MSI-03). Violaciones aquí corrompen todos los números del dashboard.
- **Agregados en SQL**, no en Python/JS; predicados compartidos en un solo lugar (DSH-03).
- **Conversión de moneda solo en `services/fx.py`**: tasa congelada por transacción (FX-03), mark-to-market solo inversiones (FX-04).
- **API keys de precios solo en backend** (INV-03). Proveedor default CoinGecko vía interfaz `PriceProvider` (`services/prices.py`).
- **Seguridad TDC**: jamás almacenar/loggear PAN completo, CVV o expiración; solo `last4` (TDC-01).
- Código, identificadores y commits en **inglés**; textos de UI en **español** (es-MX).

## Arquitectura (resumen)

- El frontend usa Supabase **solo para auth** (`src/auth/supabase.ts`); todos los datos van por FastAPI con el JWT en `Authorization` (`src/api/client.ts`).
- FastAPI **verifica** JWTs de Supabase (`app/core/security.py`), no los emite.
- RLS en Postgres como segunda capa de defensa; FastAPI filtra primero.
- Jobs en APScheduler (`app/jobs/scheduler.py`): recurrentes, cierre de statements, FX, snapshots.
- Tipos del frontend generados del OpenAPI: `npm run generate:api` (no escribir tipos de API a mano).

## Comandos

```bash
# Backend (desde backend/; requiere uv)
uv sync                          # instalar deps
uv run uvicorn app.main:app --reload   # dev server :8000
uv run pytest                    # tests
uv run ruff check . && uv run ruff format .
uv run mypy app
uv run alembic revision --autogenerate -m "msg"
uv run alembic upgrade head

# Frontend (desde frontend/)
npm install
npm run dev                      # :5173, proxy /api -> :8000
npm run build                    # tsc + vite build
npm run generate:api             # regenerar tipos desde OpenAPI
```

## Testing

- `freezegun` para todo lo que dependa de "hoy" (ciclos, jobs). `hypothesis` para invariantes (MSI-02: `Σ cuotas == total` en miles de combinaciones).
- Edge cases obligatorios de ciclos: corte `last` en febrero (bisiesto y no), corte 28, compra exactamente el día de corte con ambas `cutoff_day_policy`.
- Tests de permisos por endpoint (viewer no muta; no-miembro recibe 404).
- Los jobs deben ser idempotentes: correrlos dos veces no duplica nada (REC-02).

## Estructura

```
backend/app/
  api/v1/        routers: spaces, catalogs, transactions, cards, installments, investments, dashboard
  core/          config (pydantic-settings), security (JWT), deps (current_user, active_space)
  db/            engine/session async, Base
  models/        SQLAlchemy por dominio — importar en models/__init__.py para Alembic
  schemas/       Pydantic request/response
  services/      LÓGICA DE NEGOCIO (un módulo por dominio de reglas, ya stubbed)
  jobs/          APScheduler
frontend/src/
  features/      vertical slices: transactions, catalogs, cards, msi, investments, dashboard, spaces, settings
  api/ auth/ lib/ routes/ components/ui/
```

## Estado actual

Scaffold de Fase 0 (ver PLAN.md §6). Nada implementado aún: los servicios son stubs con `NotImplementedError` y referencia a sus reglas. Siguiente: Supabase project + login + migración inicial (`profiles`, `spaces`, `space_members`) + seed ESP-01/CAT-02.
