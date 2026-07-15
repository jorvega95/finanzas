# Espacios (Spaces)

Gestión de espacios compartidos, perfiles de usuario, membresías e invitaciones (ESP-01..ESP-07, GLO-05).

Un **espacio** es un área compartida donde múltiples usuarios colaboran. El primer espacio (personal) se crea automáticamente en la primera solicitud autenticada (ESP-01). Espacios adicionales son compartidos entre miembros con roles (ESP-03).

---

## `GET /api/v1/me`

**Para qué sirve:** Bootstrap de sesión. Retorna el perfil del usuario y sus espacios.

**Auth:** requiere JWT. Rol: ninguno (solo usuario autenticado).

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (`MeOut`):
- `profile` (`ProfileOut`):
  - `id` (uuid) — ID del usuario.
  - `display_name` (string) — nombre a mostrar.
  - `email` (string | null) — email de Supabase.
  - `default_space_id` (uuid | null) — espacio por defecto del usuario.
  - `locale` (string) — idioma preferido.
- `spaces` (list[`SpaceOut`]) — espacios donde es miembro.

**Errores:**
- `401` JWT inválido o expirado.

**Ejemplo:**
```bash
curl -s http://localhost:8000/api/v1/me \
  -H "Authorization: Bearer $JWT" | jq .
```

---

## `GET /api/v1/spaces`

**Para qué sirve:** Lista todos los espacios donde el usuario es miembro.

**Auth:** requiere JWT. Rol: ninguno.

**Path params:** ninguno

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (list[`SpaceOut`]):
- `id` (uuid) — ID del espacio.
- `name` (string) — nombre del espacio.
- `type` (`SpaceType`) — `personal` o `shared`.
- `base_currency` (string) — moneda base (p. ej. `MXN`).
- `timezone` (string) — zona horaria (p. ej. `America/Mexico_City`).
- `role` (`SpaceRole`) — rol del usuario en este espacio (`viewer`, `editor`, `owner`).

**Errores:**
- `401` JWT inválido o expirado.

**Ejemplo:**
```bash
curl -s http://localhost:8000/api/v1/spaces \
  -H "Authorization: Bearer $JWT" | jq .
```

---

## `POST /api/v1/spaces`

**Para qué sirve:** Crea un nuevo espacio compartido (ESP-02). El usuario pasa a ser owner.

**Auth:** requiere JWT. Rol: ninguno (cualquier usuario puede crear espacios).

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`SpaceCreate`):
- `name` (string, 1-80 chars) — nombre del espacio.
- `base_currency` (string, opcional, default `MXN`) — moneda base.
- `timezone` (string, opcional, default `America/Mexico_City`) — zona horaria.

**Respuesta** `201` (`SpaceOut`): el espacio creado.

**Errores:**
- `401` JWT inválido o expirado.
- `422` validación (p. ej. nombre vacío).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/spaces \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Familia García",
    "base_currency": "MXN",
    "timezone": "America/Mexico_City"
  }' | jq .
```

---

## `GET /api/v1/spaces/{space_id}`

**Para qué sirve:** Obtiene los detalles de un espacio específico.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:**
- `space_id` (uuid) — ID del espacio.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (`SpaceOut`): detalles del espacio.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio inexistente o usuario no es miembro.

**Ejemplo:**
```bash
curl -s http://localhost:8000/api/v1/spaces/$SPACE_ID \
  -H "Authorization: Bearer $JWT" | jq .
```

---

## `PATCH /api/v1/spaces/{space_id}`

**Para qué sirve:** Renombra el espacio (ESP-03). Solo owner.

**Auth:** requiere JWT + rol `owner`. No-miembro ⇒ 404; miembro sin permisos ⇒ 403.

**Path params:**
- `space_id` (uuid) — ID del espacio.

**Query params:** ninguno

**Request body** (`SpaceUpdate`):
- `name` (string, 1-80 chars) — nuevo nombre.

**Respuesta** `200` (`SpaceOut`): espacio actualizado.

**Errores:**
- `401` JWT inválido o expirado.
- `403` no es owner.
- `404` espacio no encontrado o no-miembro.
- `422` validación (nombre vacío).

**Ejemplo:**
```bash
curl -X PATCH http://localhost:8000/api/v1/spaces/$SPACE_ID \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name": "Familia García 2024"}' | jq .
```

---

## `DELETE /api/v1/spaces/{space_id}`

**Para qué sirve:** Elimina un espacio compartido completamente (ESP-06). Requiere confirmación del nombre exacto. Solo owner.

**Auth:** requiere JWT + rol `owner`. No-miembro ⇒ 404; miembro sin permisos ⇒ 403.

**Path params:**
- `space_id` (uuid) — ID del espacio a borrar.

**Query params:** ninguno

**Request body** (`SpaceDelete`):
- `confirm_name` (string) — nombre exacto del espacio (confirmación).

**Respuesta** `204 No Content`: borrado exitoso.

**Errores:**
- `401` JWT inválido o expirado.
- `403` no es owner.
- `404` espacio no encontrado o no-miembro.
- `422` nombre de confirmación no coincide.

**Ejemplo:**
```bash
curl -X DELETE http://localhost:8000/api/v1/spaces/$SPACE_ID \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"confirm_name": "Familia García"}' 
```

---

## `GET /api/v1/spaces/{space_id}/members`

**Para qué sirve:** Lista todos los miembros del espacio.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:**
- `space_id` (uuid) — ID del espacio.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (list[`MemberOut`]):
- `user_id` (uuid) — ID del usuario.
- `display_name` (string) — nombre a mostrar.
- `email` (string | null) — email.
- `role` (`SpaceRole`) — rol en el espacio.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s http://localhost:8000/api/v1/spaces/$SPACE_ID/members \
  -H "Authorization: Bearer $JWT" | jq .
```

---

## `PATCH /api/v1/spaces/{space_id}/members/{member_id}`

**Para qué sirve:** Cambia el rol de un miembro (ESP-03, ESP-05). Solo owner. El último owner no puede bajar de rol.

**Auth:** requiere JWT + rol `owner`. No-miembro ⇒ 404; miembro sin permisos ⇒ 403.

**Path params:**
- `space_id` (uuid) — ID del espacio.
- `member_id` (uuid) — ID del miembro a cambiar.

**Query params:** ninguno

**Request body** (`MemberRoleUpdate`):
- `role` (`SpaceRole`) — nuevo rol (`viewer`, `editor`, `owner`).

**Respuesta** `200` (`MemberOut`): miembro actualizado.

**Errores:**
- `401` JWT inválido o expirado.
- `403` no es owner.
- `404` espacio o miembro no encontrado; no-miembro del espacio.
- `422` intento de bajar el último owner.

**Ejemplo:**
```bash
curl -X PATCH http://localhost:8000/api/v1/spaces/$SPACE_ID/members/$MEMBER_ID \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"role": "editor"}' | jq .
```

---

## `DELETE /api/v1/spaces/{space_id}/members/{member_id}`

**Para qué sirve:** Remueve un miembro del espacio (ESP-05, ESP-07). Un usuario puede salirse a sí mismo. El owner puede remover a cualquiera. Las transacciones del removido permanecen.

**Auth:** requiere JWT + membresía. Para remover a otro, se necesita rol `owner`. No-miembro ⇒ 404.

**Path params:**
- `space_id` (uuid) — ID del espacio.
- `member_id` (uuid) — ID del miembro a remover.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `204 No Content`: removido exitoso.

**Errores:**
- `401` JWT inválido o expirado.
- `403` no es owner e intenta remover a otro.
- `404` espacio o miembro no encontrado; no-miembro del espacio.

**Ejemplo:**
```bash
curl -X DELETE http://localhost:8000/api/v1/spaces/$SPACE_ID/members/$MEMBER_ID \
  -H "Authorization: Bearer $JWT"
```

---

## `GET /api/v1/spaces/{space_id}/invites`

**Para qué sirve:** Lista invitaciones pendientes del espacio (no reclamadas). Solo owner.

**Auth:** requiere JWT + rol `owner`. No-miembro ⇒ 404; miembro sin permisos ⇒ 403.

**Path params:**
- `space_id` (uuid) — ID del espacio.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `200` (list[`InviteOut`]):
- `id` (uuid) — ID de la invitación.
- `email` (string) — email invitado.
- `role` (`SpaceRole`) — rol que tendrá al aceptar.
- `token` (string) — token único de un solo uso.
- `expires_at` (datetime) — expiración (7 días, ESP-04).
- `claimed_at` (datetime | null) — cuándo se reclamó (null si pendiente).

**Errores:**
- `401` JWT inválido o expirado.
- `403` no es owner.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s http://localhost:8000/api/v1/spaces/$SPACE_ID/invites \
  -H "Authorization: Bearer $JWT" | jq .
```

---

## `POST /api/v1/spaces/{space_id}/invites`

**Para qué sirve:** Crea una invitación por email (ESP-04). Token de un solo uso, válido por 7 días.

**Auth:** requiere JWT + rol `owner`. No-miembro ⇒ 404; miembro sin permisos ⇒ 403.

**Path params:**
- `space_id` (uuid) — ID del espacio.

**Query params:** ninguno

**Request body** (`InviteCreate`):
- `email` (string) — email a invitar.
- `role` (`SpaceRole`, opcional, default `editor`) — rol al aceptar.

**Respuesta** `201` (`InviteOut`): invitación creada.

**Errores:**
- `401` JWT inválido o expirado.
- `403` no es owner.
- `404` espacio no encontrado o no-miembro.
- `422` email inválido.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/spaces/$SPACE_ID/invites \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "juan@example.com",
    "role": "editor"
  }' | jq .
```

---

## `POST /api/v1/invites/claim`

**Para qué sirve:** Reclama una invitación con el token (ESP-04). El email del usuario debe coincidir con el de la invitación. Agrega al usuario como miembro del espacio.

**Auth:** requiere JWT. Rol: ninguno (cualquier usuario autenticado).

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`InviteClaim`):
- `token` (string, 10-64 chars) — token de la invitación.

**Respuesta** `200` (`SpaceOut`): espacio al que se unió.

**Errores:**
- `401` JWT inválido o expirado.
- `404` token inválido o expirado.
- `422` email no coincide con el de la invitación.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/invites/claim \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"token": "abc123def456"}' | jq .
```

---

## Notas de implementación

- **Fase 0:** Endpoints esqueletados; servicios aún retornan `NotImplementedError`.
- **Reglas de negocio:** ESP-01 (provisionamiento automático), ESP-02 (espacios compartidos), ESP-03 (matriz de roles), ESP-04 (invitaciones), ESP-05/07 (remoción), ESP-06 (borrado seguro).
- **GLO-05:** No-miembro retorna 404 para no revelar existencia; verificación en `get_active_space` en `deps.py`.
