# Reglas de negocio

Complemento de `PLAN.md` (v2). Cada regla tiene ID estable para referenciarla en código, tests y PRs (ej. `# implements TDC-04`). Convención: **DEBE** = obligatorio, **NO DEBE** = prohibido, **PUEDE** = opcional/configurable.

**Convenciones globales:**

- **GLO-01 · Dinero:** todo monto es `Decimal`/`NUMERIC(14,2)`, redondeo `ROUND_HALF_EVEN` salvo regla específica. Prohibido `float` en cualquier cálculo monetario.
- **GLO-02 · Fechas de negocio:** la lógica de ciclos, MSI, recurrentes y presupuestos opera con `date` (sin hora ni timezone). La conversión de "ahora" a `date` usa la timezone del espacio (`spaces.timezone`, default `America/Mexico_City`). Los `created_at`/`updated_at` sí son `timestamptz`.
- **GLO-03 · Soft-delete:** catálogos, tarjetas y cuentas de inversión nunca se borran físicamente si tienen registros asociados; se desactivan (`is_active=false`). Borrado físico solo si no tienen referencias.
- **GLO-04 · Auditoría:** toda entidad lleva `created_by`, `created_at`, `updated_at`. Las transacciones además `updated_by`.
- **GLO-05 · Aislamiento:** ninguna query de negocio cruza espacios. Toda tabla de dominio lleva `space_id` y RLS activa; FastAPI filtra siempre por el espacio activo de la sesión.

---

## 1. Usuarios y espacios (ESP) — R7, R8

- **ESP-01:** al completar el registro (cualquier proveedor) se crea automáticamente: `profile` + espacio `type=personal` llamado "Personal" + membresía `owner` + catálogos seed (CAT-02). El espacio personal NO DEBE poder eliminarse ni transferirse; es el fallback de `default_space_id`.
- **ESP-02:** un usuario PUEDE tener máximo 1 espacio personal y N espacios compartidos.
- **ESP-03 · Roles y permisos:**

| Acción | owner | editor | viewer |
|---|---|---|---|
| Ver todo el espacio | ✔ | ✔ | ✔ |
| Crear/editar/borrar transacciones | ✔ | ✔ | ✖ |
| Gestionar catálogos, tarjetas, inversiones | ✔ | ✔ | ✖ |
| Gestionar presupuestos y recurrentes | ✔ | ✔ | ✖ |
| Invitar/remover miembros, cambiar roles | ✔ | ✖ | ✖ |
| Renombrar/eliminar el espacio | ✔ | ✖ | ✖ |

- **ESP-04 · Invitaciones:** solo por email; token de un solo uso con expiración a 7 días. Si el email no tiene cuenta, la invitación se reclama al registrarse. Una invitación pendiente al mismo email reemplaza la anterior.
- **ESP-05:** un espacio compartido DEBE tener ≥1 owner en todo momento. El último owner no puede salir ni degradarse; primero transfiere ownership.
- **ESP-06:** eliminar un espacio compartido requiere confirmación explícita y borra en cascada todos sus datos. Los miembros reciben notificación. (Sin papelera en v1; el export previo es la mitigación, IMP-07.)
- **ESP-07:** al remover un miembro, sus transacciones creadas permanecen (con `created_by` intacto).

## 2. Catálogos (CAT) — R2

- **CAT-01 · Unicidad:** el nombre de categoría es único por espacio + `kind` (case/acentos-insensible, `unaccent + lower`). Igual para métodos de pago por espacio.
- **CAT-02 · Seed:** al crear cualquier espacio se siembran: categorías de gasto (Comida, Súper, Transporte, Vivienda, Servicios, Salud, Entretenimiento, Ropa, Educación, Regalos, Otros), de ingreso (Nómina, Freelance, Intereses, Otros) y métodos de pago (Efectivo, Débito, Transferencia). Todas editables y desactivables.
- **CAT-03 · Naturaleza del gasto:** cada categoría de gasto lleva `expense_nature` (`fixed | variable | discretionary`). Una transacción hereda la naturaleza de su categoría, pero PUEDE sobreescribirla (`transactions.expense_nature_override`). Los reportes usan `COALESCE(override, categoria)`.
- **CAT-04 · Desactivación:** una categoría/método inactivo no aparece en formularios de captura, pero las transacciones históricas lo conservan y los reportes lo siguen mostrando. Reactivable en cualquier momento.
- **CAT-05:** no se puede desactivar la última categoría activa de un `kind` ni el último método de pago activo.
- **CAT-06 · Subcategorías:** máximo 2 niveles (categoría → subcategoría). Una subcategoría hereda `kind` y `expense_nature` del padre salvo override. Los agregados por categoría suman las subcategorías al padre, con drill-down.
- **CAT-07:** un método de pago `type=credit_card` DEBE referenciar una tarjeta (`credit_card_id`). Al crear una tarjeta (TDC-01) se crea automáticamente su método de pago vinculado; al desactivar la tarjeta se desactiva el método.

## 3. Transacciones (TXN) — R1, R11

- **TXN-01 · Tipos:** `expense`, `income`, `transfer`. Campos mínimos obligatorios: `date`, `amount > 0`, `currency`, `type`; expense/income además `category_id` (de `kind` acorde) y `payment_method_id`.
- **TXN-02 · Transfer:** requiere `payment_method_from` y `payment_method_to` distintos. Las transferencias NO DEBEN contarse en ingresos ni gastos de ningún agregado. Caso principal: pago de TDC (TDC-10).
- **TXN-03 · Fechas:** `date` PUEDE ser pasada o presente; futura solo hasta +1 año (para programados manuales). Las transacciones con fecha futura se excluyen de agregados del mes actual hasta que llegue su fecha.
- **TXN-04 · Moneda:** `currency` ∈ ISO-4217 soportadas (v1: MXN, USD; crypto se maneja en inversiones, no en transacciones). Al crear/editar, se persiste `fx_rate_to_base` según FX-03 — el agregado nunca re-consulta tasas históricas.
- **TXN-05 · Edición/borrado:** editable por cualquier editor/owner del espacio. Si la transacción tiene plan MSI asociado, ver MSI-08. Si proviene de regla recurrente o import, editarla la desvincula de regeneraciones futuras (mantiene `recurring_rule_id`/`import_batch_id` para trazabilidad).
- **TXN-06 · TDC:** una transacción con método de pago de tipo `credit_card` se asigna a un ciclo de facturación según TDC-05 y NO cuenta como flujo de salida hasta que se paga el statement (el gasto sí cuenta en reportes por categoría en su fecha; el flujo de caja lo refleja el pago — ver DSH-04).
- **TXN-07 · Adjuntos (v2+):** preparar `attachment_url` (ticket/factura, Supabase Storage). No bloqueante para v1.

## 4. Tarjetas de crédito y ciclos (TDC) — R3

- **TDC-01 · Alta:** campos obligatorios: alias, banco, red, `last4` (4 dígitos), `statement_day` (1-28 o `last`), y exactamente uno de: `payment_due_days` (1-30, típico 20) o `payment_day` (1-28 o `last`). Opcionales: `credit_limit`, color/ícono. NO DEBE almacenarse PAN completo, CVV ni fecha de expiración.
- **TDC-02 · Día de corte:** si `statement_day=d`, el corte del mes M es `min(d, último_día(M))`. `statement_day=last` ⇒ último día del mes. Se permite 29/30 capturándolo como `last` o ajustando; la UI ofrece 1-28 y `last` para evitar ambigüedad.
- **TDC-03 · Ciclo:** el ciclo que cierra en el corte C abarca `[corte_anterior + 1 día, C]`. Cada ciclo genera un `card_statement` con `period_start`, `period_end=C`, `due_date`.
- **TDC-04 · Fecha límite:** `due_date = period_end + payment_due_days`; con `payment_day`: el primer `payment_day` estrictamente posterior a `period_end` (ajustado por TDC-02 si el mes es corto). Si `due_date` cae en fin de semana NO se ajusta en v1 (los bancos MX difieren; el usuario ve la fecha exacta que configuró).
- **TDC-05 · Asignación de compra a ciclo:** una compra con fecha `t` se asigna al statement cuyo `period_end` sea el primer corte `≥ t`. Excepción: si `t == period_end`, el comportamiento depende de `card.cutoff_day_policy` (`include` default | `next_cycle`), configurable por tarjeta porque los bancos difieren.
- **TDC-06 · Reasignación manual:** el usuario PUEDE mover cualquier cargo al ciclo anterior/siguiente (un paso). La reasignación recalcula totales de ambos statements y queda auditada.
- **TDC-07 · Cierre de statement:** un statement pasa a `closed` automáticamente cuando `hoy > period_end` (job diario). Al cerrar: `computed_total = Σ cargos del ciclo + Σ cuotas MSI con cargo en ese ciclo (MSI-04) − Σ pagos/abonos asignados al ciclo`, y se programa el recordatorio (REM-01).
- **TDC-08 · Estados de statement:** `open → closed → paid | partially_paid | overdue`. `paid` cuando `paid_amount ≥ computed_total`; `overdue` si `hoy > due_date` y no está pagado; `partially_paid` si `0 < paid_amount < computed_total` (puede coexistir con overdue: flag, no estado excluyente — `status` + `is_overdue` booleano).
- **TDC-09 · Deuda:** por tarjeta se reportan tres números, sin mezclarlos: **(a) saldo al corte** = `computed_total − paid_amount` de statements cerrados no pagados; **(b) gasto del ciclo en curso** = Σ cargos del statement `open`; **(c) comprometido futuro** = Σ cuotas MSI `pending` aún no cargadas. Deuda total = a + b + c.
- **TDC-10 · Pago de tarjeta:** se registra como `transfer` (TXN-02) hacia el método de la tarjeta, con asignación a un statement. Abona a `paid_amount`. Si excede el `computed_total`, el excedente queda como saldo a favor que se aplica al siguiente statement al cerrarlo.
- **TDC-11 · Backfill:** al dar de alta una tarjeta se generan statements desde la fecha de la transacción más antigua que la use (o desde hoy si no hay), nunca a futuro: el statement `open` se materializa al vuelo y los futuros no existen hasta que abren.
- **TDC-12 · Desactivación:** una tarjeta con MSI pendientes o statements no pagados PUEDE desactivarse (no acepta cargos nuevos) pero sus ciclos siguen cerrando y sus cuotas siguen cargándose hasta liquidar.
- **TDC-13:** no se calculan intereses ni comisiones en v1 (se asume totalero). El usuario PUEDE capturar intereses/comisiones como cargos manuales con categoría "Comisiones e intereses" (seed al crear la primera tarjeta).

## 5. Meses sin intereses (MSI) — R4

- **MSI-01 · Alta:** una compra MSI se captura como transacción expense normal (monto total, fecha, categoría) + plan: `months ∈ [2, 60]`, `credit_card_id` obligatorio (MSI solo existe en TDC).
- **MSI-02 · Cuotas:** `monthly_amount = round(total / months, 2)` con `ROUND_FLOOR`; la **última cuota absorbe el residuo**: `last = total − monthly_amount × (months − 1)`. Invariante (test obligatorio): `Σ cuotas == total` exacto.
- **MSI-03 · Doble contabilidad evitada:** la transacción de compra MSI NO entra a agregados de gasto mensual ni al `computed_total` de ningún statement por su monto total; lo que entra son sus **cuotas** (cada una en su ciclo). En reportes por categoría, cada cuota hereda la categoría y naturaleza de la compra original.
- **MSI-04 · Calendario de cuotas:** la cuota 1 se carga en el statement al que TDC-05 asigne la fecha de compra; la cuota n en el n-ésimo corte siguiente. `estimated_charge_date = period_end` del statement correspondiente. Si los statements futuros no existen aún (TDC-11), la fecha se calcula proyectando cortes con TDC-02 y se reconcilia cuando el statement abre.
- **MSI-05 · Estados de cuota:** `pending` (futura) → `charged` (su statement cerró; entra al `computed_total`) → `paid` (su statement quedó pagado). El job de cierre (TDC-07) hace la transición.
- **MSI-06 · Vista MSI (R4):** por plan: cuotas pagadas/cargadas/restantes, monto restante = Σ cuotas no-`paid`, fecha de liquidación proyectada. Global: tabla mes × tarjeta con el total comprometido por mes futuro (suma de cuotas `pending` por `estimated_charge_date`).
- **MSI-07 · Liquidación anticipada:** el usuario PUEDE marcar un plan como liquidado: las cuotas `pending` se cancelan y se genera un cargo único por su suma en el statement abierto de la tarjeta. Queda auditado (`status=settled_early`).
- **MSI-08 · Edición:** editar el monto/meses de un plan solo si ninguna cuota está `charged`; después, solo MSI-07 o ajustes manuales cuota por cuota. Borrar la transacción de compra borra el plan completo solo si todas las cuotas están `pending`; si no, se bloquea con mensaje.
- **MSI-09:** compras MSI en moneda ≠ moneda de la tarjeta no se soportan en v1 (validación al alta).

## 6. Recurrentes (REC) — R9

- **REC-01 · Regla:** plantilla de transacción (tipo, monto, moneda, categoría, método, descripción) + `frequency` (`weekly | biweekly | monthly | yearly`), `start_date`, `end_date?` o `max_occurrences?`, `day_rule` para mensual (`día N` con ajuste a último día si el mes es corto, o `último día`).
- **REC-02 · Generación:** job diario (00:30 tz del espacio) genera las instancias con `scheduled_date ≤ hoy`. Idempotencia: constraint único `(recurring_rule_id, scheduled_date)` — re-ejecutar el job nunca duplica.
- **REC-03 · Revisión:** toda instancia generada nace con `needs_review=true` y aparece en una bandeja "Por confirmar". El usuario confirma (1 tap), ajusta monto (caso luz/agua con monto variable: la regla PUEDE marcarse `amount_is_estimate`) o descarta (se crea tombstone para que REC-02 no la regenere).
- **REC-04 · Cambios a la regla:** editar una regla afecta solo instancias futuras; las generadas no se tocan. Pausar (`is_active=false`) detiene generación sin borrar historial. Si la regla apunta a categoría/método desactivado, se pausa automáticamente y se notifica.
- **REC-05 · Catch-up:** si el job no corrió N días (downtime), genera todas las instancias faltantes hasta hoy, en orden.

## 7. Multimoneda (FX) — R11

- **FX-01:** cada espacio tiene `base_currency` (default MXN), inmutable después de que exista la primera transacción (v1; migración de base es feature futura).
- **FX-02 · Fuente:** job diario obtiene USD/MXN de Banxico SIE (serie FIX) y la persiste en `exchange_rates(base, quote, rate, date)`. Días inhábiles: se persiste la última tasa publicada con la fecha del día (flag `is_carry_forward`).
- **FX-03 · Tasa congelada:** al crear/editar una transacción en moneda ≠ base, se resuelve y **persiste** `fx_rate_to_base` con la tasa de `transactions.date` (o la previa más cercana). Los agregados usan siempre la tasa persistida; nunca re-convertir histórico con tasas nuevas. El usuario PUEDE sobreescribir la tasa manualmente (caso: tasa real de su banco).
- **FX-04:** valuación de inversiones (INV) usa la tasa **del día de la valuación**, no congelada — el portafolio es mark-to-market.
- **FX-05:** montos se muestran en su moneda original con el equivalente en base; agregados y presupuestos siempre en `base_currency`.

## 8. Presupuestos (PRE) — R10

- **PRE-01:** presupuesto = (categoría raíz, mes, monto en `base_currency`, `alert_threshold` default 0.8). Único por categoría+mes. PUEDE copiarse del mes anterior en bloque ("repetir presupuestos").
- **PRE-02 · Consumo:** Σ de gastos del mes de esa categoría y sus subcategorías, convertidos a base (FX-03), **incluyendo** cuotas MSI cargadas ese mes (MSI-03) y **excluyendo** transfers y la transacción-madre MSI.
- **PRE-03 · Alertas:** una sola alerta al cruzar el umbral y una al cruzar 100%, por presupuesto-mes (no spam por cada transacción). Canal según REM-04.
- **PRE-04:** sin rollover en v1 (lo no gastado no se acumula). El reporte muestra variación vs presupuesto por mes.

## 9. Recordatorios (REM) — R14

- **REM-01 · TDC:** al cerrar un statement (TDC-07) se programan recordatorios a `due_date − N días` con N = `card.reminder_days` (default `[3, 1]`). Si el statement se paga antes, los pendientes se cancelan.
- **REM-02:** un recordatorio se envía una sola vez por (statement, offset, canal). Reintentos ante fallo de envío: 3 con backoff, luego `failed` visible en UI.
- **REM-03 · Contenido:** alias de tarjeta, monto a pagar (`computed_total − paid_amount`), fecha límite. Nunca incluir `last4` completo en notificaciones push (privacidad en lockscreen): solo alias.
- **REM-04 · Canales:** v1: in-app (centro de notificaciones) + email (Resend). Push llega con la PWA (Fase 6). Preferencias por usuario y por tipo (TDC, presupuesto) en settings.

## 10. Inversiones (INV) — R5, R15

- **INV-01:** `investment_account` (kind: `crypto | stocks | fixed_income | other`) contiene `holdings` (símbolo, cantidad, costo promedio, moneda de costo). Cantidad con `NUMERIC(28,10)` (crypto necesita decimales finos; GLO-01 aplica solo a montos monetarios).
- **INV-02 · Movimientos:** alta por operaciones `buy | sell | deposit | withdraw`, no edición directa de cantidades. `buy`: nuevo costo promedio ponderado = `(qty_old × avg_old + qty_in × precio) / qty_new`. `sell`: la cantidad baja, el costo promedio NO cambia; P&L realizado = `qty × (precio_venta − avg_cost)`, registrado en el movimiento. `sell` con qty > posición se rechaza.
- **INV-03 · Precios crypto:** proxy FastAPI → interfaz `PriceProvider` con `CoinGeckoProvider` default (`CoinMarketCapProvider` alterno), caché TTL 10 min, sin exponer la key. Si el proveedor falla, se sirve el último precio cacheado con su `fetched_at` visible ("precio de hace 2 h"). Presupuesto de llamadas: 1 batch (`/simple/price` con todos los símbolos del sistema) por refresh, no por usuario — CoinGecko cobra 1 crédito por llamada sin importar el batch (~4,300 de 10,000/mes).
- **INV-03b · Backfill histórico:** al dar de alta un holding crypto, se PUEDE rellenar la gráfica con históricos de CoinGecko (hasta 1 año, free tier). Los puntos backfilled se marcan `source=backfill` y nunca sobreescriben snapshots propios (INV-05).
- **INV-04 · Precios no-crypto:** captura manual de precio por símbolo (v1). El usuario actualiza cuando quiera; la UI muestra la fecha del último precio.
- **INV-05 · Snapshot:** job diario (23:50 tz espacio) persiste `portfolio_snapshots` con valor total y desglose por holding (precio usado, FX usado). Es la fuente de las gráficas históricas — nunca se reconstruyen con precios actuales.
- **INV-06 · P&L:** no realizado por holding = `qty × precio_actual − qty × avg_cost` (convertido a base con FX-04). La vista separa P&L realizado (de ventas) y no realizado.

## 11. Patrimonio neto (PAT) — R12

- **PAT-01:** `activos = Σ valor de portafolios (INV-05)`; `pasivos = Σ deuda total TDC (TDC-09: a+b+c)`. `patrimonio = activos − pasivos`. Job diario lo persiste en `net_worth_snapshots` (mismo horario que INV-05, después de él).
- **PAT-02:** v1 no modela cuentas de efectivo/débito como activos (no hay saldos de cuentas bancarias). La UI lo declara explícitamente ("patrimonio = inversiones − deuda TDC") para no inducir a error. Modelar saldos de cuentas es candidato a R16 futuro.

## 12. Importación CSV (IMP) — R13

- **IMP-01 · Flujo:** subir archivo → detectar/elegir plantilla de banco (mapping de columnas persistido en `import_batches.mapping`) → preview con validaciones → confirmar → insertar. Nada se inserta antes de confirmar.
- **IMP-02 · Dedupe:** hash = `sha256(space_id | date | amount | currency | descripcion_normalizada)` (trim, lower, colapsar espacios). Colisión contra transacciones existentes ⇒ la fila se marca "posible duplicado" y queda des-seleccionada por default en el preview; el usuario decide.
- **IMP-03 · Categorización:** filas sin categoría inferible quedan en "Sin categoría" (seed oculta) y en la bandeja de revisión (REC-03 reutilizada). Reglas simples por keyword en descripción PUEDEN sugerir categoría (backlog).
- **IMP-04 · Rollback:** un batch puede revertirse completo mientras ninguna de sus transacciones haya sido editada manualmente; si alguna lo fue, el rollback excluye esas y lo informa.
- **IMP-05:** cargos de TDC importados se asignan a ciclos con TDC-05 normalmente. Compras MSI no son detectables desde CSV: se importan como cargo normal y el usuario las convierte a plan MSI manualmente (acción "convertir a MSI" que aplica MSI-03 retroactivamente).
- **IMP-06:** límite 5,000 filas por archivo; encoding UTF-8/Latin-1 auto-detectado; formatos de fecha y separador decimal configurables por plantilla de banco.
- **IMP-07 · Export:** todo espacio puede exportar sus transacciones a CSV (mismo esquema que import) y un JSON completo. Es también la mitigación de ESP-06.

## 13. Dashboard y agregados (DSH) — R6

- **DSH-01 · Mes financiero:** los agregados son por mes calendario en tz del espacio. (Mes personalizado tipo "quincena a quincena" es backlog.)
- **DSH-02 · Ingresos/gastos del mes:** ingresos = Σ income; gastos = Σ expense excluyendo transacciones-madre MSI (MSI-03) e incluyendo cuotas MSI cargadas en el mes; transfers excluidos siempre (TXN-02). Todo en base currency con tasas congeladas (FX-03).
- **DSH-03 · Desgloses:** por categoría (raíz, con drill-down CAT-06), por naturaleza (CAT-03), por método de pago, tendencia 6 meses. Todos calculados en SQL con los mismos predicados de DSH-02 — un solo lugar (vista SQL o CTE compartido) para que ningún número difiera entre widgets.
- **DSH-04 · Doble vista TDC:** el dashboard distingue **gasto devengado** (cuándo compraste — categorías, presupuestos) de **flujo de caja** (cuándo pagaste — pagos de statements). Default: devengado; toggle a flujo. Ambos documentados en la UI con tooltip, porque es la confusión #1 en apps de finanzas con TDC.
- **DSH-05 · Próximos compromisos:** widget con statements por vencer (TDC-08), cuotas MSI del próximo mes (MSI-06) y recurrentes próximas (REC), ordenados por fecha.

---

## Matriz requerimiento → reglas

| Req | Reglas |
|---|---|
| R1 gastos | TXN-01…07, GLO-01/02 |
| R2 catálogos | CAT-01…07 |
| R3 TDC | TDC-01…13 |
| R4 MSI | MSI-01…09 |
| R5 crypto | INV-01/02/03/03b/05/06 |
| R6 dashboard | DSH-01…05 |
| R7 login | ESP-01/02 |
| R8 espacios | ESP-01…07, GLO-05 |
| R9 recurrentes | REC-01…05 |
| R10 presupuestos | PRE-01…04 |
| R11 multimoneda | FX-01…05 |
| R12 patrimonio | PAT-01/02 |
| R13 import | IMP-01…07 |
| R14 recordatorios | REM-01…04 |
| R15 no-crypto | INV-01/02/04/05/06 |

## Casos de prueba obligatorios (mínimos)

1. **TDC-02/04:** tarjeta con corte `last` y `payment_due_days=20` en febrero bisiesto y no bisiesto; corte 28 en todos los meses.
2. **TDC-05:** compra exactamente el día de corte con ambas políticas (`include`/`next_cycle`).
3. **MSI-02:** `1000.00 / 3` ⇒ cuotas `333.33, 333.33, 333.34`; `Σ == total` para 1000 combinaciones aleatorias (property-based, hypothesis).
4. **MSI-03/DSH-02:** compra MSI de 12,000 a 12 meses ⇒ el gasto del mes de compra refleja 1,000, no 12,000, y ningún agregado suma 13,000.
5. **REC-02:** ejecutar el job 2 veces el mismo día ⇒ cero duplicados; REC-05 con 10 días de downtime ⇒ 10 instancias correctas.
6. **FX-03:** editar una transacción vieja no cambia su tasa persistida; un gasto USD del 2026-01-15 usa la tasa de esa fecha aunque hoy sea otra.
7. **TDC-10:** pago mayor al statement ⇒ saldo a favor aplicado al siguiente cierre.
8. **GLO-05/ESP-03:** un viewer no puede mutar nada (test de permisos por endpoint); un usuario sin membresía recibe 404 (no 403, para no filtrar existencia).
