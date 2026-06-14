# Plan: App Mobile (Android + iOS)

**Stack:** React Native + Expo (SDK actual al arranque) · **Alcance v1:** companion app → paridad gradual · **Repo:** mismo monorepo · **Distribución:** uso personal primero · **Fecha:** 2026-06-11 · **v1**

> Complementa `PLAN.md` (v2) y `REGLAS_NEGOCIO.md`. Las reglas existentes aplican íntegras a mobile; este plan propone además reglas nuevas `MOB-*` (§7) que deben agregarse a `REGLAS_NEGOCIO.md` al aprobarse.

## Decisiones tomadas (2026-06-11)

| Decisión | Elección | Racional |
|---|---|---|
| Alcance v1 | **Companion app** | Captura rápida, bandeja de revisión, push TDC, dashboard ligero. La web sigue siendo la app completa. El caso de uso mobile real es "registrar el gasto en 10 segundos y que me recuerde pagar la tarjeta". |
| Código | **Mismo monorepo** | Compartir tipos OpenAPI, lógica de dominio y hooks de datos sin publicar paquetes npm. Expo soporta monorepos nativamente (Metro auto-configurado vía `expo/metro-config`). |
| Distribución | **Uso personal primero** | Android: APK/internal track. iOS: dev build o TestFlight (Apple Developer $99/año). Sin review de tiendas hasta que el producto madure. |
| Timing | **Tras Fase 2-3 web** | Mobile consume la API; arrancar antes de que transacciones + TDC + dashboard existan y estén testeados es construir contra arena movediza. La **reestructura del monorepo sí se hace antes** (Fase M0, barata hoy, cara después). |

---

## 1. Principio rector: compartir lógica, no UI

Con backend API-first, **toda la lógica de negocio ya vive en FastAPI** (ciclos TDC, MSI, agregados). Lo que el frontend duplica entre web y mobile es: tipos del API, cliente HTTP, hooks de datos, validaciones de formularios y utilidades de dinero/fechas. Eso es lo que se extrae a `packages/`.

La **UI no se comparte**. Alternativas evaluadas:

- **Universal UI (Tamagui + Solito, o react-strict-dom):** un solo árbol de componentes para web y native. Potente, pero acopla ambas apps al mismo framework de UI, obliga a migrar la web existente (shadcn/ui + Tailwind) y añade un compilador más a depurar. Para una companion app con ~6 pantallas, el costo supera al beneficio.
- **UI por plataforma (elegida):** web sigue con shadcn/ui + Tailwind v4; mobile usa **NativeWind v4** (sintaxis Tailwind sobre React Native → cero curva de aprendizaje extra, design tokens compartibles vía preset de Tailwind en `packages/config`). Si en el futuro se busca paridad total, migrar a universal UI es una decisión reversible porque la lógica ya estará extraída.

## 2. Estructura del monorepo (post Fase M0)

```
finanzas/
├── backend/                      # sin cambios
├── apps/
│   ├── web/                      # el frontend/ actual, movido
│   └── mobile/                   # Expo app (Expo Router)
│       ├── app/                  # rutas file-based: (auth)/, (tabs)/
│       ├── src/features/         # mismos vertical slices que web
│       ├── app.config.ts
│       └── eas.json
├── packages/
│   ├── api/                      # tipos generados del OpenAPI (npm run generate:api
│   │                             #   se mueve aquí) + cliente fetch con inyección de JWT
│   ├── domain/                   # dinero (formato, validación sin float — GLO-01),
│   │                             #   fechas YYYY-MM-DD locales (GLO-02, hoy en
│   │                             #   apps/web/src/lib/dates.ts), schemas zod de formularios,
│   │                             #   constantes (monedas, roles ESP-03, frecuencias REC-01)
│   ├── queries/                  # hooks TanStack Query compartidos (query keys únicos,
│   │                             #   invalidaciones consistentes web/mobile)
│   └── config/                   # tsconfig base, eslint, preset Tailwind (tokens de
│                                 #   color/espaciado consumidos por web y NativeWind)
├── package.json                  # pnpm workspaces
├── turbo.json                    # opcional: cache de build/lint/test
└── pnpm-workspace.yaml
```

**Reglas del monorepo:**

- **pnpm workspaces** (migrar de npm); dependencias internas con `workspace:*`.
- **Una sola versión de React y React Native** en todo el repo (duplicados rompen Metro de formas opacas).
- `packages/*` son TypeScript puro **sin imports de react-dom ni react-native** (salvo `queries`, que importa solo `@tanstack/react-query`, agnóstico de plataforma). Lint rule que lo haga cumplir.
- Supabase auth: `@supabase/supabase-js` funciona en ambos; el **storage del token es por plataforma** (localStorage en web, `expo-secure-store` en mobile — MOB-04). El wrapper de auth queda en cada app; `packages/api` solo recibe un `getToken()`.
- CI: GitHub Actions corre lint + tests de `packages/*` y ambas apps; EAS Build solo para releases mobile (free tier: 15 builds Android + 15 iOS/mes, suficiente para uso personal).

## 3. Stack mobile

| Capa | Elección | Notas |
|---|---|---|
| Framework | **Expo (managed) + dev builds** | Acceso a módulos nativos sin eyectar; `expo-dev-client` desde el día 1 |
| Navegación | **Expo Router** | File-based, deep links gratis (necesarios para push → statement) |
| UI | **NativeWind v4** | Sintaxis Tailwind; tokens compartidos vía preset |
| Datos | **TanStack Query** (de `packages/queries`) | Mismos hooks que web |
| Formularios | react-hook-form + zod (schemas de `packages/domain`) | Igual que web |
| Auth | supabase-js + expo-secure-store; Google OAuth nativo vía `expo-auth-session` | El backend no cambia: mismo JWT |
| Push | **expo-notifications** + Expo Push Service | Ver §5 |
| Gráficas | victory-native o react-native-svg + d3 ligero | Solo dashboard ligero; decidir en M2 |
| Builds | **EAS Build + EAS Submit** | eas.json con perfiles `development`, `preview` (APK/TestFlight), `production` |

## 4. Alcance funcional v1 (companion)

Pantallas (≈6, en tabs):

1. **Captura** (pantalla default al abrir): formulario <10 s — monto, categoría (grid de íconos), método de pago, fecha=hoy. Cumple TXN-01..06; MSI se captura con toggle "a MSI" solo si el método es TDC (MSI-01).
2. **Movimientos**: lista del mes con filtros básicos; editar/borrar (TXN-05, permisos ESP-03 — viewer solo lee).
3. **Por confirmar**: bandeja REC-03 (confirmar 1 tap / ajustar monto / descartar). Caso de uso mobile perfecto.
4. **Tarjetas**: por tarjeta los tres números de TDC-09 (saldo al corte, ciclo en curso, comprometido MSI), próxima fecha límite, estado del statement. Solo lectura + registrar pago (TDC-10 como transfer).
5. **Dashboard ligero**: ingresos vs gastos del mes (DSH-02), top categorías, próximos compromisos (DSH-05). Sin tendencias ni drill-down (eso es web).
6. **Ajustes**: switcher de espacio (GLO-05), preferencias de notificaciones (REM-04), sesión.

**Explícitamente fuera de v1 mobile:** alta/edición de catálogos, tarjetas, recurrentes, presupuestos, inversiones, importación CSV, gestión de espacios/invitaciones. Todo eso es web (la PWA de Fase 6 web da acceso de emergencia desde el teléfono).

## 5. Push notifications (completa REM-04)

La web planeaba push vía PWA; mobile lo hace nativo y mejor:

- Backend: tabla `device_push_tokens (id, user_id, expo_push_token, platform, last_seen_at, is_active)`. Endpoint de registro al login; prune de tokens inválidos según receipts de Expo.
- El job de recordatorios (REM-01/REM-02) gana el canal `push`: envía vía Expo Push API (httpx desde FastAPI, sin SDK extra).
- Contenido cumple REM-03: alias de tarjeta, monto, fecha límite — **nunca `last4`** (lockscreen).
- Deep link: tocar la notificación abre la pantalla de la tarjeta/statement (Expo Router).
- Presupuestos (PRE-03) reutiliza el mismo canal.

## 6. Captura offline (la feature que justifica mobile)

Registrar un gasto en el súper sin señal debe funcionar:

- Cola local de mutaciones de creación de transacción (TanStack Query `onlineManager` + persistencia en AsyncStorage/SQLite). Al recuperar red, se reenvían en orden.
- Idempotencia: cada transacción creada en mobile lleva `client_generated_id` (UUID v4 generado en el dispositivo); el backend lo persiste con constraint único por espacio — reintentos nunca duplican (espíritu de REC-02).
- Lectura: caché persistida de TanStack Query (último estado conocido, marcado como "sin conexión"). **No** se intenta sync bidireccional completo (no CRDTs, no replicación): solo cola de salida + caché de lectura. v1 honesto.

## 7. Reglas nuevas propuestas (agregar a REGLAS_NEGOCIO.md al aprobar)

- **MOB-01 · Push tokens:** cada dispositivo registra su Expo push token al iniciar sesión (`device_push_tokens`). Un token pertenece a un usuario, no a un espacio. Tokens con receipt de error `DeviceNotRegistered` se desactivan automáticamente.
- **MOB-02 · Idempotencia de captura:** las transacciones creadas desde mobile DEBEN llevar `client_generated_id` (UUID) único por espacio. El backend ante un duplicado responde 200 con la transacción existente (no 409): el cliente no distingue reintento de éxito.
- **MOB-03 · Offline:** mobile encola creaciones offline y las reenvía en orden al reconectar. Ediciones y borrados offline NO se soportan en v1 (requieren resolución de conflictos); la UI los deshabilita sin red.
- **MOB-04 · Sesión:** el refresh token vive en `expo-secure-store` (Keychain/Keystore), nunca en AsyncStorage. Bloqueo biométrico opcional para abrir la app: backlog.
- **MOB-05 · Permisos:** la app respeta ESP-03 igual que la web; un viewer ve captura deshabilitada, no oculta (descubribilidad). Usuario sin membresía: mismo 404 (GLO-05).

## 8. Fases mobile

Prerequisito: web Fases 0-2 completas (API de auth, transacciones, catálogos, TDC/MSI funcionando y testeada). La Fase M0 puede y debe hacerse antes, en cuanto termine la Fase 0 web.

### Fase M0 — Reestructura del monorepo (2-4 días) · *hacer temprano*
Migrar a pnpm workspaces; mover `frontend/` → `apps/web`; crear `packages/api` (mover ahí `generate:api` y el cliente), `packages/domain` (mover `lib/dates.ts`, formato de dinero, schemas zod), `packages/config`. La web debe quedar **idéntica en comportamiento** (mismo build, mismos tests) — es solo mudanza. Actualizar CLAUDE.md y CI.
**Sale:** monorepo listo; el desarrollo web continúa sin fricción y todo lo nuevo compartible nace en `packages/`.

### Fase M1 — Esqueleto + auth (1 semana)
App Expo con Expo Router, NativeWind, dev build en tu(s) dispositivo(s). Login Supabase (Google + email) con secure store (MOB-04). Switcher de espacio. Pantalla de movimientos en solo-lectura consumiendo `packages/queries`.
**Sale:** haces login en tu teléfono y ves tus datos reales.

### Fase M2 — Captura + bandeja (1-2 semanas)
Formulario de captura <10 s (TXN), toggle MSI, edición/borrado, bandeja "Por confirmar" (REC-03). Cola offline + `client_generated_id` (MOB-02/03, incluye endpoint backend).
**Sale:** registras gastos desde el teléfono, incluso sin señal. **Dejas de necesitar la web para el día a día.**

### Fase M3 — Push + TDC (1-2 semanas)
`device_push_tokens` + canal push en el job de recordatorios (MOB-01, REM-01..04). Pantalla de tarjetas (TDC-09) con registro de pago (TDC-10). Deep links.
**Sale:** el teléfono te avisa cuándo y cuánto pagar — la feature de retención #1.

### Fase M4 — Dashboard ligero + pulido (1 semana)
Resumen del mes (DSH-02/05), top categorías, presupuestos en modo lectura con barras (PRE). Estados vacíos, splash, ícono, EAS perfiles `preview`/`production`, TestFlight/APK para uso diario.
**Sale:** companion app v1 completa instalada en tus dispositivos.

### Backlog mobile (hacia paridad)
Presupuestos e inversiones editables, vista MSI completa, gestión de espacios, widgets de home screen (gasto del mes), biometría, captura por voz/foto de ticket (TXN-07), publicación en tiendas (privacy policy, screenshots, review).

## 9. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Reestructura del monorepo rompe el dev web | M0 es mudanza pura con criterio de aceptación "build y tests idénticos"; hacerla cuando la web aún es chica (post Fase 0) |
| Versiones duplicadas de React/RN rompen Metro | pnpm + una sola versión declarada en el root; `expo-doctor` en CI |
| `packages/*` se contamina de código de plataforma | Lint rule de imports prohibidos (react-dom/react-native) en packages |
| Float se cuela en cálculos de UI mobile (GLO-01) | El formato/parse de dinero vive solo en `packages/domain`, testeado; PRs que tocan montos referencian GLO-01 |
| Cola offline duplica transacciones | MOB-02: idempotencia por `client_generated_id` con test obligatorio (reenviar la cola 2 veces ⇒ cero duplicados) |
| iOS sin cuenta de pago: builds expiran a los 7 días | Asumir Apple Developer ($99/año) en cuanto el uso sea diario; mientras, desarrollo en simulador + Android físico |
| Free tier EAS insuficiente | 15+15 builds/mes sobra para uso personal; builds locales (`eas build --local`) como escape |
| La API cambia y rompe mobile | Tipos generados del OpenAPI fallan el build en CI ante breaking changes — el contrato es el compilador |

## 10. Relación con el plan web

- La **PWA de Fase 6 web baja de prioridad**: mobile nativo la sustituye para captura y push. Se conserva como acceso de emergencia (instalable barata) o se descarta — decidir al llegar.
- `npm run generate:api` pasa a ser `pnpm --filter @finanzas/api generate` (actualizar CLAUDE.md en M0).
- Nada del backend cambia salvo: endpoint de push tokens (M3) y `client_generated_id` en transacciones (M2) — ambos aditivos.

---

*Historial: v1 (2026-06-11) plan inicial — companion app, monorepo pnpm, Expo, distribución personal.*
