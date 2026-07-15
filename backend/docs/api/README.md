# Documentación de API — Finanzas

Documentación completa de los endpoints de la API REST de Finanzas. Todos los endpoints requieren un JWT de Supabase válido en el header `Authorization: Bearer <token>` (excepto los de meta).

**Prefijo base:** `/api/v1`

## Índice de dominios

1. **[Espacios (Spaces)](./spaces.md)** — Gestión de espacios compartidos, perfiles, membresías e invitaciones (ESP-01..ESP-07, GLO-05).
2. **[Catálogos (Catalogs)](./catalogs.md)** — Categorías, métodos de pago y tipos de tarjeta (CAT-01..CAT-08).
3. **[Transacciones (Transactions)](./transactions.md)** — Alta, edición y consulta de transacciones (TXN-01..TXN-06, REC-03).
4. **[Reglas Recurrentes (Recurring)](./recurring.md)** — Creación y gestión de reglas de generación automática (REC-01..REC-05).
5. **[Tarjetas (Cards)](./cards.md)** — Tarjetas de crédito y débito, estados de cuenta, pagos, ciclos y recordatorios (TDC-01..TDC-16, TAR-01..TAR-07, REM-01..REM-05).
6. **[Cuotas/MSI (Installments)](./installments.md)** — Planes de compra en cuotas (MSI-01..MSI-10).
7. **[Inversiones (Investments)](./investments.md)** — Cuentas de inversión, portafolio, snapshots de patrimonio (INV-01..INV-06, PAT-01..PAT-02).
8. **[Dashboard (Dashboard)](./dashboard.md)** — Resumen de ingresos/gastos, tendencias, próximos compromisos y pronóstico de flujo (DSH-01..DSH-05, PRO-01..PRO-06).
9. **[Presupuestos (Budgets)](./budgets.md)** — Presupuestos por categoría mensual, seguimiento de consumo y alertas (PRE-01..PRE-04).
10. **[Importación/Exportación (Imports)](./imports.md)** — CSV preview, confirmación, rollback y exportación de datos (IMP-01..IMP-07).

## Notas generales

### Autenticación y autorización

- **JWT requerido:** Todo endpoint excepto `/health` requiere un `Authorization: Bearer <token>` válido.
- **Espacio activo:** Se especifica con el header `X-Space-Id`; si no se envía, se usa el espacio por defecto del usuario.
- **Roles:** La autorización depende del rol en el espacio (ESP-03):
  - `viewer` — solo lectura.
  - `editor` — lectura y escritura de datos de dominio.
  - `owner` — todas las permisos + gestión de espacio y miembros.
- **No-miembro retorna 404:** Si un usuario no es miembro del espacio solicitado, la API retorna `404` (no `403`) para no revelar la existencia (GLO-05, regla de test 8).

### Request/Response

- **Moneda:** Todos los montos viajan como strings en JSON para evitar pérdida de precisión decimal (GLO-01). Tipados como `Decimal` en Python.
- **Fechas:** `date` puro (YYYY-MM-DD), nunca `datetime`, en transacciones, ciclos, reglas recurrentes y presupuestos (GLO-02).
- **Formato de error:** Errores HTTP estándar (400, 401, 403, 404, 422, etc.) con `detail` descriptivo.

### Patrones comunes

#### Dependencias de auth
- `CurrentUser` — requiere JWT válido; provee el perfil del usuario.
- `ActiveSpace` — requiere JWT + membresía en el espacio (cualquier rol); retorna (space, member).
- `EditorSpace` — requiere JWT + rol `editor` u `owner`; para mutaciones.
- `OwnerSpace` — requiere JWT + rol `owner`; para administración.

#### Listados con filtros
Muchos endpoints soportan `limit`, `offset` y filtros opcionales (ej: `date_from`, `date_to`, `category_id`). Responden con paginación.

#### Idempotencia
Ciertos endpoints (jobs manuales como `/close-cycles`, `/generate`, `/check-alerts`, snapshots) son idempotentes: ejecutarlos múltiples veces no crea duplicados.

## Ejemplo: flujo completo

```bash
# 1. Bootstrap: obtener sesión y espacios del usuario
curl -s http://localhost:8000/api/v1/me \
  -H "Authorization: Bearer $JWT" | jq .

# 2. Listar tarjetas del espacio activo
curl -s "http://localhost:8000/api/v1/cards" \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" | jq .

# 3. Crear una transacción
curl -X POST http://localhost:8000/api/v1/transactions \
  -H "Authorization: Bearer $JWT" \
  -H "X-Space-Id: $SPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "expense",
    "date": "2026-07-14",
    "amount": "150.50",
    "currency": "MXN",
    "description": "Almuerzo",
    "category_id": "'$CATEGORY_ID'",
    "payment_method_id": "'$METHOD_ID'"
  }' | jq .
```

## Estado de implementación

Fase 0 del proyecto (PLAN.md §6). Todos los endpoints están esqueletados; servicios retornan `NotImplementedError` y referencian reglas de negocio en `REGLAS_NEGOCIO.md` para implementación posterior.
