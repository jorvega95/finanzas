# Notificaciones (Notifications)

Centro de notificaciones in-app: inbox, badge de no leídos y descarte (REM-04..REM-07).

Los recordatorios los **genera** el sistema (cierre de statement TDC-07 → REM-01; alertas de presupuesto PRE-03) y los **dispara** el job diario (`fire_due_reminders`), que pasa un recordatorio de `pending` a `sent` cuando llega su `fire_at`. Este router solo los consume: no crea recordatorios.

Estados relevantes:

| Estado | Significado | ¿Aparece en el inbox? |
|---|---|---|
| `pending` | Programado a futuro, aún no disparado | No |
| `sent` | Disparado — es una notificación real | **Sí** |
| `canceled` | El statement se pagó (REM-01b) | No |
| `dismissed` | El usuario lo descartó (REM-05) | No |
| `failed` | Falló el envío tras 3 intentos (REM-02) | No |

`read_at` (REM-07) es **independiente** del descarte: leer solo apaga el badge; el aviso sigue en el inbox hasta descartarse o cancelarse. En v1 ambos son **por espacio, no por miembro**.

**Prefijo:** `/api/v1/notifications`

---

## `GET /api/v1/notifications`

**Para qué sirve:** Inbox del centro de notificaciones (REM-06). Devuelve solo los avisos del canal `in_app` del espacio activo ya disparados (`status = sent`) y no descartados. Máximo 50, ordenados por `fire_at` desc y luego `created_at` desc.

**Auth:** requiere JWT + membresía (cualquier rol, incluido `viewer`). No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (`list[NotificationOut]`):
- `id` (uuid)
- `kind` (string) — `card_due` | `budget_alert` | `custom`.
- `ref_id` (uuid) — statement (card_due) o presupuesto (budget_alert).
- `fire_at` (date) — cuándo debía dispararse.
- `channel` (string) — siempre `in_app` en este endpoint.
- `message` (string) — alias + monto + fecha límite; **nunca `last4`** (REM-03).
- `status` (string) — siempre `sent` en este endpoint.
- `sent_at` (datetime | null)
- `read_at` (datetime | null) — nulo = no leído (REM-07).
- `created_at` (datetime)

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro (GLO-05).

**Ejemplo:**
```bash
curl -s http://localhost:8000/api/v1/notifications \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `GET /api/v1/notifications/unread-count`

**Para qué sirve:** Badge de la campana (REM-07): cuántos avisos del inbox tienen `read_at IS NULL`.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params / query params / body:** ninguno

**Respuesta** `200` (`UnreadCountOut`):
- `unread` (int)

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s http://localhost:8000/api/v1/notifications/unread-count \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
# => { "unread": 2 }
```

---

## `GET /api/v1/notifications/history`

**Para qué sirve:** Auditoría (REM-06): **todos** los recordatorios del espacio activo, sin filtrar por estado ni canal — incluye `pending` (programados a futuro), `canceled`, `dismissed`, `failed` y los del canal `email`. Máximo 100, mismo orden que el inbox.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params / query params / body:** ninguno

**Respuesta** `200` (`list[NotificationOut]`) — mismo shape que el inbox, pero `status` y `channel` pueden tomar cualquier valor.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s http://localhost:8000/api/v1/notifications/history \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq '[.[] | select(.channel == "in_app")]'
```

---

## `POST /api/v1/notifications/read-all`

**Para qué sirve:** Marca leído todo el inbox (REM-07). Idempotente: la segunda llamada devuelve `marked: 0`. **No** altera `status`, así que los avisos siguen visibles.

**Auth:** requiere JWT + membresía (no requiere rol editor). No-miembro ⇒ 404.

**Path params / query params / body:** ninguno

**Respuesta** `200` (`MarkedReadOut`):
- `marked` (int) — cuántos pasaron de no leído a leído.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/notifications/read-all \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
# => { "marked": 2 }
```

---

## `POST /api/v1/notifications/{reminder_id}/read`

**Para qué sirve:** Marca leído un aviso concreto (REM-07). Idempotente; no cambia `status`.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:**
- `reminder_id` (uuid) — debe pertenecer al espacio activo.

**Query params / body:** ninguno

**Respuesta** `200` (`NotificationOut`) — el recordatorio con `read_at` ya poblado.

**Errores:**
- `401` JWT inválido o expirado.
- `404` recordatorio inexistente o de otro espacio (GLO-05).

**Ejemplo:**
```bash
curl -X POST "http://localhost:8000/api/v1/notifications/$REMINDER_ID/read" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `DELETE /api/v1/notifications/{reminder_id}`

**Para qué sirve:** Descartar un aviso (REM-05). Soft-delete: pasa a `dismissed`, desaparece del inbox y se conserva en `/history` para auditoría. **No** afecta el estado del statement ni los otros canales.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:**
- `reminder_id` (uuid) — debe pertenecer al espacio activo.

**Query params / body:** ninguno

**Respuesta** `204` — sin cuerpo.

**Errores:**
- `401` JWT inválido o expirado.
- `404` recordatorio inexistente o de otro espacio (GLO-05).

**Ejemplo:**
```bash
curl -X DELETE "http://localhost:8000/api/v1/notifications/$REMINDER_ID" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" -i
```
