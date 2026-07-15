# Catálogos (Catalogs)

Gestión de catálogos compartidos: categorías, métodos de pago y tipos de tarjeta (CAT-01..CAT-08).

Un catálogo pertenece a un espacio y es visible/editable por miembros con rol `editor` u `owner`. Los catálogos inactivos se ocultan por defecto en formularios de captura (CAT-04).

**Prefijo:** `/api/v1/catalogs`

---

## `GET /api/v1/catalogs/categories`

**Para qué sirve:** Lista categorías del espacio.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:**
- `kind` (enum, opcional) — filtrar por tipo: `expense`, `income` (si no se especifica, retorna todas).
- `include_inactive` (bool, opcional, default `false`) — incluir categorías inactivas.

**Request body:** ninguno

**Respuesta** `200` (list[`CategoryOut`]):
- `id` (uuid) — ID de la categoría.
- `name` (string) — nombre.
- `kind` (`CategoryKind`) — `expense` o `income`.
- `expense_nature` (`ExpenseNature` | null) — naturaleza del gasto (p. ej. `food`, `transport`).
- `parent_id` (uuid | null) — ID de categoría padre (jerarquía).
- `icon` (string | null) — emoji o nombre del ícono.
- `color` (string | null) — color hexadecimal.
- `is_active` (bool) — activa o inactiva.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/catalogs/categories?kind=expense" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/catalogs/categories`

**Para qué sirve:** Crea una categoría. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`CategoryCreate`):
- `name` (string, 1-60 chars) — nombre de la categoría.
- `kind` (`CategoryKind`, opcional, default `expense`) — `expense` o `income`.
- `expense_nature` (`ExpenseNature`, opcional) — naturaleza (ej. `food`, `transport`, etc.).
- `parent_id` (uuid, opcional) — ID de categoría padre (para subcategorías).
- `icon` (string, opcional, max 40 chars) — ícono.
- `color` (string, opcional, max 20 chars) — color hexadecimal.

**Respuesta** `201` (`CategoryOut`): categoría creada.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio o categoría padre no encontrada; no-miembro.
- `422` validación (nombre vacío, parent_id inválido).

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/catalogs/categories \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Restaurantes",
    "kind": "expense",
    "expense_nature": "food",
    "icon": "🍽️",
    "color": "#FF6B6B"
  }' | jq .
```

---

## `PATCH /api/v1/catalogs/categories/{category_id}`

**Para qué sirve:** Actualiza una categoría. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `category_id` (uuid) — ID de la categoría.

**Query params:** ninguno

**Request body** (`CategoryUpdate`):
- `name` (string, 1-60 chars, opcional) — nuevo nombre.
- `expense_nature` (`ExpenseNature`, opcional) — nueva naturaleza.
- `icon` (string, opcional, max 40 chars) — nuevo ícono.
- `color` (string, opcional, max 20 chars) — nuevo color.
- `is_active` (bool, opcional) — activar/desactivar.

**Respuesta** `200` (`CategoryOut`): categoría actualizada.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` categoría o espacio no encontrado; no-miembro.
- `422` validación.

**Ejemplo:**
```bash
curl -X PATCH http://localhost:8000/api/v1/catalogs/categories/$CATEGORY_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{"name": "Comidas", "is_active": false}' | jq .
```

---

## `DELETE /api/v1/catalogs/categories/{category_id}`

**Para qué sirve:** Elimina una categoría. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `category_id` (uuid) — ID de la categoría.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `204 No Content`: eliminada exitosamente.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` categoría o espacio no encontrado; no-miembro.

**Ejemplo:**
```bash
curl -X DELETE http://localhost:8000/api/v1/catalogs/categories/$CATEGORY_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID"
```

---

## `GET /api/v1/catalogs/payment-methods`

**Para qué sirve:** Lista métodos de pago del espacio.

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:**
- `include_inactive` (bool, opcional, default `false`) — incluir inactivos.

**Request body:** ninguno

**Respuesta** `200` (list[`PaymentMethodOut`]):
- `id` (uuid) — ID del método.
- `name` (string) — nombre.
- `type` (`PaymentMethodType`) — tipo (`cash`, `debit_card`, `credit_card`, `transfer`, etc.).
- `card_id` (uuid | null) — si es una tarjeta, su ID.
- `is_active` (bool) — activo o inactivo.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/catalogs/payment-methods" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/catalogs/payment-methods`

**Para qué sirve:** Crea un método de pago. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`PaymentMethodCreate`):
- `name` (string, 1-60 chars) — nombre del método.
- `type` (`PaymentMethodType`) — tipo.

**Respuesta** `201` (`PaymentMethodOut`): método creado.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio no encontrado; no-miembro.
- `422` validación.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/catalogs/payment-methods \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Billetera",
    "type": "cash"
  }' | jq .
```

---

## `PATCH /api/v1/catalogs/payment-methods/{method_id}`

**Para qué sirve:** Actualiza un método de pago. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `method_id` (uuid) — ID del método.

**Query params:** ninguno

**Request body** (`PaymentMethodUpdate`):
- `name` (string, 1-60 chars, opcional) — nuevo nombre.
- `is_active` (bool, opcional) — activar/desactivar.

**Respuesta** `200` (`PaymentMethodOut`): método actualizado.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` método o espacio no encontrado; no-miembro.
- `422` validación.

**Ejemplo:**
```bash
curl -X PATCH http://localhost:8000/api/v1/catalogs/payment-methods/$METHOD_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{"name": "Billetera 2"}' | jq .
```

---

## `DELETE /api/v1/catalogs/payment-methods/{method_id}`

**Para qué sirve:** Elimina un método de pago. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `method_id` (uuid) — ID del método.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `204 No Content`: eliminado exitosamente.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` método o espacio no encontrado; no-miembro.

**Ejemplo:**
```bash
curl -X DELETE http://localhost:8000/api/v1/catalogs/payment-methods/$METHOD_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID"
```

---

## `GET /api/v1/catalogs/card-types`

**Para qué sirve:** Lista tipos de tarjeta del espacio (CAT-08).

**Auth:** requiere JWT + membresía. No-miembro ⇒ 404.

**Path params:** ninguno

**Query params:**
- `include_inactive` (bool, opcional, default `false`) — incluir inactivos.

**Request body:** ninguno

**Respuesta** `200` (list[`CardTypeOut`]):
- `id` (uuid) — ID del tipo.
- `name` (string) — nombre.
- `behavior` (`CardBehavior`) — `credit` o `debit`.
- `icon` (string | null) — ícono.
- `color` (string | null) — color.
- `is_system` (bool) — si es del sistema (no editable).
- `is_active` (bool) — activo o inactivo.

**Errores:**
- `401` JWT inválido o expirado.
- `404` espacio no encontrado o no-miembro.

**Ejemplo:**
```bash
curl -s "http://localhost:8000/api/v1/catalogs/card-types" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .
```

---

## `POST /api/v1/catalogs/card-types`

**Para qué sirve:** Crea un tipo de tarjeta. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:** ninguno

**Query params:** ninguno

**Request body** (`CardTypeCreate`):
- `name` (string, 1-60 chars) — nombre del tipo.
- `behavior` (`CardBehavior`) — `credit` o `debit`.
- `icon` (string, opcional, max 40 chars) — ícono.
- `color` (string, opcional, max 20 chars) — color.

**Respuesta** `201` (`CardTypeOut`): tipo creado.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` espacio no encontrado; no-miembro.
- `422` validación.

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/v1/catalogs/card-types \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Visa Crédito",
    "behavior": "credit",
    "icon": "💳",
    "color": "#1434CB"
  }' | jq .
```

---

## `PATCH /api/v1/catalogs/card-types/{card_type_id}`

**Para qué sirve:** Actualiza un tipo de tarjeta. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `card_type_id` (uuid) — ID del tipo.

**Query params:** ninguno

**Request body** (`CardTypeUpdate`):
- `name` (string, 1-60 chars, opcional) — nuevo nombre.
- `icon` (string, opcional, max 40 chars) — nuevo ícono.
- `color` (string, opcional, max 20 chars) — nuevo color.
- `is_active` (bool, opcional) — activar/desactivar.

**Respuesta** `200` (`CardTypeOut`): tipo actualizado.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` tipo o espacio no encontrado; no-miembro.
- `422` validación.

**Ejemplo:**
```bash
curl -X PATCH http://localhost:8000/api/v1/catalogs/card-types/$CARD_TYPE_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{"name": "Visa Débito"}' | jq .
```

---

## `DELETE /api/v1/catalogs/card-types/{card_type_id}`

**Para qué sirve:** Elimina un tipo de tarjeta. Requiere rol editor+.

**Auth:** requiere JWT + rol `editor`/`owner`. No-miembro ⇒ 404; viewer ⇒ 403.

**Path params:**
- `card_type_id` (uuid) — ID del tipo.

**Query params:** ninguno

**Request body:** ninguno

**Respuesta** `204 No Content`: eliminado exitosamente.

**Errores:**
- `401` JWT inválido o expirado.
- `403` rol insuficiente (viewer).
- `404` tipo o espacio no encontrado; no-miembro.

**Ejemplo:**
```bash
curl -X DELETE http://localhost:8000/api/v1/catalogs/card-types/$CARD_TYPE_ID \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID"
```

---

## Notas de implementación

- **Fase 0:** Endpoints esqueletados; servicios retornan `NotImplementedError`.
- **Reglas:** CAT-01 (categorías por espacio), CAT-02 (seeding), CAT-04 (inactividad), CAT-08 (tipos de tarjeta).
- **Monedas:** Los montos en endpoints relacionados usan formato de string (GLO-01).
