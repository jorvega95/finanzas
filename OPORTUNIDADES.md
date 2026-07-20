# OPORTUNIDADES.md — Roadmap de áreas de oportunidad

Backlog priorizado de mejoras detectadas tras auditar la funcionalidad actual (backend + frontend). Pensado para **desarrollar una feature a la vez mientras se prueba en uso real**.

- Cada oportunidad tiene un **ID estable** (`OPP-01`…) para referenciarlo en commits, tests y nuevas reglas, igual que los IDs de `REGLAS_NEGOCIO.md`.
- Antes de implementar cualquiera: leer las reglas del dominio en `REGLAS_NEGOCIO.md` (columna *Reglas*). Si la feature necesita reglas nuevas (marcadas **regla nueva**), **proponerlas y agregarlas con ID antes de codificar** (flujo de `CLAUDE.md`).
- "Estado" describe qué existe **hoy** en el código, para no reimplementar lo ya hecho.
- Orden sugerido = de arriba hacia abajo. No es rígido: cada bloque es independiente.

Leyenda de esfuerzo: 🟢 bajo · 🟡 medio · 🔴 alto.

---

## Estado base (lo que ya funciona — no tocar salvo para extender)

Transacciones (expense/income/transfer) · catálogos con soft-delete · TDC con motor de ciclos · MSI (plan + cuotas) · recurrentes (job idempotente) · multimoneda (FX Banxico) · presupuestos con alertas · inversiones crypto/no-crypto + patrimonio neto · importación/exportación CSV · pronóstico de flujo a futuro · esqueleto de espacios compartidos con invitaciones.

---

## Bloque 1 — Terminar lo que ya está construido a medias (máximo ROI)

El modelo y la lógica ya existen; falta la "última milla". Empezar aquí.

### OPP-01 · Centro de notificaciones in-app 🟡 ✅ [COMPLETADO 2026-07-20]
**Qué:** campana con badge + inbox para ver y descartar recordatorios dentro de la app.
**Por qué:** el feature que más retiene en apps de finanzas (PLAN §1.4). Antes se generaban recordatorios que nadie veía.
**Entregado:** reglas nuevas **REM-06** (semántica del inbox: solo `sent`, no descartados; `/history` para auditoría) y **REM-07** (`read_at`: leído ≠ descartado, badge, `read-all`). Migración `0013` (`reminders.read_at`). Router `api/v1/notifications.py` con `GET /notifications`, `/unread-count`, `/history`, `POST /read-all`, `POST /{id}/read`, `DELETE /{id}` — los endpoints previos bajo `/cards/notifications/*` se retiraron. Frontend: `api/notifications.ts` + `components/NotificationBell.tsx` en el header (abrir el panel marca leído); se eliminó el banner duplicado de `CardsPage`. 8 tests nuevos en `test_reminders.py` (14 en total).
**Reglas:** REM-01b, REM-04, REM-05, **REM-06**, **REM-07**, GLO-05.
**Pendiente relacionado:** el estado leído/descartado es **por espacio, no por miembro** (simplificación documentada en REM-07); revisar cuando existan preferencias de notificación por usuario.

### OPP-02 · Envío real de email (Resend) 🟢
**Qué:** que los recordatorios de pago TDC y alertas de presupuesto lleguen por correo.
**Por qué:** sin esto, ningún aviso te alcanza con la app cerrada.
**Estado:** `services/reminders.py` hoy solo hace `logger.info("email reminder: ...")`. La regla REM-02 ya define reintentos (3 con backoff → `failed`).
**Falta:** integrar Resend (API key en backend, `core/config.py`); plantilla de correo (REM-03: alias, monto, fecha; nunca `last4` completo); marcar `sent`/`failed`.
**Reglas:** REM-02, REM-03, REM-04.
**Hecho cuando:** un recordatorio `due` se envía una sola vez por (statement, offset, canal) y queda `sent`; un fallo reintenta y termina `failed` visible en UI.

### OPP-03 · PWA instalable + push 🟡
**Qué:** completar la PWA (service worker) y notificaciones push.
**Por qué:** puente barato a móvil (PLAN §Móvil) y hace útil el recordatorio con la app cerrada. Habilita el canal `push` que REM-04 deja para esta fase.
**Estado:** ya existe `frontend/public/manifest.webmanifest`; **no hay** service worker ni suscripción push.
**Falta:** service worker (vite-plugin-pwa), prompt de instalación, suscripción Web Push + envío desde el backend al disparar recordatorios.
**Reglas:** REM-04 (canal push).
**Hecho cuando:** la app se instala en móvil/desktop y un recordatorio llega como push.

---

## Bloque 2 — Espacios compartidos: de "soportado" a "valioso"

El modelo multi-tenant ya está; estas features lo convierten en finanzas en pareja/familia de verdad. Probar primero el flujo de invitación actual antes de empezar.

### OPP-04 · Atribución y feed de actividad 🟢
**Qué:** mostrar quién registró cada transacción + filtro por miembro y un feed de actividad reciente del espacio.
**Por qué:** en un espacio compartido, "¿quién gastó/registró esto?" es información básica que hoy se guarda pero no se muestra.
**Estado:** `transactions.created_by` **ya se persiste**; la UI no lo expone ni filtra.
**Falta:** incluir `created_by` (display_name/avatar) en el response de transacciones; columna/etiqueta en la lista; filtro por miembro; opcional: vista "actividad del espacio".
**Reglas:** ESP-03 (roles), GLO-05.
**Hecho cuando:** cada transacción muestra su autor y puedo filtrar la lista por miembro.

### OPP-05 · Reparto y liquidación de gastos compartidos ("quién le debe a quién") 🔴
**Qué:** marcar un gasto como compartido (50/50 u otro split) y un resumen de saldos entre miembros, estilo Splitwise.
**Por qué:** *la* razón de usar un espacio compartido en vez de dos apps personales. Mayor salto de valor de producto del backlog.
**Estado:** no existe. La arquitectura multi-tenant lo habilita, pero requiere modelo y reglas nuevas.
**Falta:** **regla nueva** (dominio sugerido `SPL`): tabla de splits por transacción (miembro, proporción/monto), servicio de liquidación (saldos netos entre miembros), endpoints y UI de "saldos del espacio" + registrar pago de liquidación.
**Reglas:** **regla nueva (SPL-xx)** — proponer antes de codificar; reusa ESP-03, FX-03.
**Hecho cuando:** un gasto puede dividirse entre miembros y existe una vista "X te debe $Y" con opción de saldar.

---

## Bloque 3 — Reducir fricción de captura (causa #1 de abandono)

### OPP-06 · Categorización automática por reglas 🟡
**Qué:** reglas keyword→categoría que sugieren categoría al capturar y al importar CSV.
**Por qué:** la captura/clasificación manual mata la adherencia (PLAN §7).
**Estado:** ya está en backlog explícito (IMP-03). Hoy las filas sin categoría caen en "Sin categoría".
**Falta:** **regla nueva** para el motor de reglas (CRUD de reglas: si descripción contiene X → categoría Y); aplicarlas en alta de transacción y en preview de importación.
**Reglas:** IMP-03, REC-03; **regla nueva** para el motor de reglas.
**Hecho cuando:** importar un CSV pre-categoriza por mis reglas y al teclear una descripción conocida se sugiere la categoría.

### OPP-07 · Captura desde foto de ticket (OCR) 🔴
**Qué:** foto del recibo → extraer monto, fecha y comercio → prellenar el formulario.
**Por qué:** elimina el tecleo, el tipo de "magia" que diferencia el producto.
**Estado:** no existe.
**Falta:** endpoint backend que recibe la imagen y usa visión (Claude API, `claude-opus-4-8` u otro modelo de la familia 4.x) para extraer campos; UI de captura por foto; revisión antes de guardar. La API key vive solo en backend (análogo a INV-03).
**Reglas:** **regla nueva** (extensión de TXN); reusar la bandeja de revisión (REC-03).
**Hecho cuando:** subo una foto y obtengo una transacción prellenada y editable.

---

## Bloque 4 — Inteligencia financiera (valor analítico nuevo)

### OPP-08 · Insights mensuales automáticos 🟡
**Qué:** "gastaste 22% más en restaurantes que el mes pasado", "Spotify subió de $115 a $129", detección de suscripciones olvidadas.
**Por qué:** ya tienes los datos; falta convertirlos en conclusiones.
**Estado:** no existe. Se apoya en agregados que ya calcula el dashboard (DSH-03) y en recurrentes (REC).
**Falta:** servicio de comparativa mes vs mes y detección de variaciones de recurrentes; widget de insights en el dashboard.
**Reglas:** DSH-03; **regla nueva** para definir umbrales de "insight".
**Hecho cuando:** el dashboard muestra 2-3 observaciones automáticas relevantes del mes.

### OPP-09 · Metas de ahorro 🟡
**Qué:** apartar dinero hacia un objetivo y ver avance (distinto de presupuesto = límite de gasto).
**Por qué:** complementa patrimonio neto; control activo en positivo, no solo de gasto.
**Estado:** no existe.
**Falta:** **regla nueva** (dominio sugerido `GOL`): modelo de meta (nombre, monto objetivo, fecha, aportaciones), UI de avance.
**Reglas:** **regla nueva (GOL-xx)**; relación con PAT.
**Hecho cuando:** creo una meta, registro aportaciones y veo el % de avance.

### OPP-10 · Flujo de caja histórico ("cuándo pagaste") 🟡
**Qué:** vista de caja real pasada, complemento del gasto devengado (dashboard) y la proyección futura (pronóstico).
**Por qué:** cierra el triángulo devengado / futuro / caja real. Backlog explícito.
**Estado:** backlog declarado en DSH-04. El pronóstico (PRO-01…06) ya resuelve el lado *futuro* del flujo de caja.
**Falta:** servicio que agregue salidas reales por fecha de pago (liquidación de statements, cargos cash/débito); vista en dashboard o sección propia.
**Reglas:** DSH-04 (backlog), TDC-09.
**Hecho cuando:** puedo ver cuánto dinero salió realmente cada mes, no cuándo se devengó el gasto.

---

## Cómo trabajar este backlog

1. Elegir el siguiente `OPP-xx` (recomendado: en orden).
2. Leer sus reglas en `REGLAS_NEGOCIO.md`. Si dice **regla nueva**, proponerla y agregarla con ID antes de codificar.
3. Tests primero para lógica delicada (splits, liquidación, motor de reglas).
4. Implementar backend → tipos OpenAPI → frontend.
5. Verificar CI completo (ruff format + mypy + pytest + build) antes de commit.
6. Commit referenciando el ID: `feat(notifications): centro de avisos in-app [OPP-01, REM-04..05]`.
7. Probarlo en uso real antes de pasar al siguiente.

---

*Creado tras auditoría de funcionalidad (2026-06-27). Mantener vivo: al completar un OPP, marcarlo o moverlo a un historial; al detectar nuevas oportunidades, agregarlas con el siguiente ID.*
