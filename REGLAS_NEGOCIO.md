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
- **CAT-02 · Seed:** al crear cualquier espacio se siembran: categorías de gasto (Comida, Súper, Transporte, Vivienda, Servicios, Salud, Entretenimiento, Ropa, Educación, Regalos, Otros), de ingreso (Nómina, Freelance, Intereses, Otros), métodos de pago (Efectivo, Débito, Transferencia) y tipos de tarjeta (CAT-08). Todas editables y desactivables.
- **CAT-03 · Naturaleza del gasto:** cada categoría de gasto lleva `expense_nature` (`fixed | variable | discretionary`). Una transacción hereda la naturaleza de su categoría, pero PUEDE sobreescribirla (`transactions.expense_nature_override`). Los reportes usan `COALESCE(override, categoria)`.
- **CAT-04 · Desactivación:** una categoría/método inactivo no aparece en formularios de captura, pero las transacciones históricas lo conservan y los reportes lo siguen mostrando. Reactivable en cualquier momento.
- **CAT-05:** no se puede desactivar la última categoría activa de un `kind` ni el último método de pago activo.
- **CAT-06 · Subcategorías:** máximo 2 niveles (categoría → subcategoría). Una subcategoría hereda `kind` y `expense_nature` del padre salvo override. Los agregados por categoría suman las subcategorías al padre, con drill-down.
- **CAT-07:** un método de pago vinculado a una tarjeta DEBE referenciarla (`card_id`). Toda tarjeta (cualquier tipo, TAR-03) crea automáticamente su método de pago al alta y lo desactiva al desactivarse. El `type` del método refleja el `behavior` del tipo: `credit_card` (crédito), `debit` (débito), `prepaid` (vales/regalo y demás prepago).
- **CAT-08 · Tipos de tarjeta:** catálogo `card_types` por espacio (seed CAT-02). Cada tipo lleva un `behavior` de sistema **no editable** (`credit | debit | prepaid`) que determina el comportamiento del motor (TAR-01); el nombre es libre y editable. Seed: "Crédito" (`credit`), "Débito" (`debit`), "Vales de despensa" (`prepaid`), "Tarjeta de regalo" (`prepaid`). Unicidad de nombre por espacio (estilo CAT-01). NO DEBE borrarse ni desactivarse un tipo con tarjetas asociadas (GLO-03); reactivable en cualquier momento.

## 3. Transacciones (TXN) — R1, R11

- **TXN-01 · Tipos:** `expense`, `income`, `transfer`. Campos mínimos obligatorios: `date`, `amount > 0`, `currency`, `type`; expense/income además `category_id` (de `kind` acorde) y `payment_method_id`.
- **TXN-02 · Transfer:** requiere `payment_method_from` y `payment_method_to` distintos. Las transferencias NO DEBEN contarse en ingresos ni gastos de ningún agregado. Caso principal: pago de TDC (TDC-10).
- **TXN-03 · Fechas:** `date` PUEDE ser pasada o presente; futura solo hasta +1 año (para programados manuales). Las transacciones con fecha futura se excluyen de agregados del mes actual hasta que llegue su fecha.
- **TXN-04 · Moneda:** `currency` ∈ ISO-4217 soportadas (v1: MXN, USD; crypto se maneja en inversiones, no en transacciones). Al crear/editar, se persiste `fx_rate_to_base` según FX-03 — el agregado nunca re-consulta tasas históricas.
- **TXN-05 · Edición/borrado:** editable por cualquier editor/owner del espacio. Si la transacción tiene plan MSI asociado, ver MSI-08. Si proviene de regla recurrente o import, editarla la desvincula de regeneraciones futuras (mantiene `recurring_rule_id`/`import_batch_id` para trazabilidad).
- **TXN-06 · TDC:** una transacción con método de pago de tipo `credit_card` se asigna a un ciclo de facturación según TDC-05 (salvo TDC-16 para ingresos) (el gasto cuenta en los agregados devengados —totales, reportes por categoría y presupuestos— en su fecha de compra, DSH-04; su liquidación se refleja en la deuda de la tarjeta, TDC-09, no en los agregados de gasto).
- **TXN-07 · Adjuntos (v2+):** preparar `attachment_url` (ticket/factura, Supabase Storage). No bloqueante para v1.
- **TXN-08 · Balance en transferencias:** una transferencia cuyo `payment_method_id` (origen) pertenece a una tarjeta de behavior `debit`/`prepaid` se rechaza (422) si `amount > saldo_disponible`, salvo `allow_overdraft=true` en esa tarjeta. No aplica cuando el origen es efectivo, transferencia bancaria u otro método sin tarjeta vinculada (sin `card_id`).
- **TXN-09 · Transferencia a TDC como pago:** si `payment_method_to_id` pertenece a una tarjeta de behavior `credit`, `create_transaction` enruta internamente como pago: abona `amount` a `paid_amount` del statement cerrado más antiguo con saldo pendiente; si no existe ninguno, abona al statement abierto del ciclo actual. El campo opcional `target_statement_id` en el request permite elegir el statement exacto. La transacción se crea siempre como `type=transfer` para trazabilidad (TXN-02). Aplica también al editar (update).
- **TXN-10 · Filtro por método de pago:** el listado de transacciones filtrado por `payment_method_id` DEBE incluir las transferencias en las que el método sea origen **o** destino (`payment_method_to_id`). El filtro representa "movimientos que tocan el método", no solo egresos desde él; sin esto un pago de TDC (TDC-10, TXN-09) queda invisible al filtrar por la tarjeta pagada. No altera agregados: los transfers siguen excluidos de ingresos/gastos (TXN-02, DSH-02).

## 4. Tarjetas (TAR) y ciclos de crédito (TDC) — R3

Toda tarjeta tiene un tipo (CAT-08) cuyo `behavior` define su modelo. Las reglas TAR aplican a cualquier tarjeta; las TDC, MSI y REM solo al behavior `credit`.

- **TAR-01 · Tipo:** toda tarjeta DEBE tener un `card_type` (CAT-08). Su `behavior` define el modelo: `credit` (deuda, ciclos, statements, MSI — ver TDC) o `debit`/`prepaid` (saldo de valor almacenado, sin ciclos).
- **TAR-02 · Campos por behavior:** solo `credit` lleva `statement_day`, política de corte, `payment_due_days`/`payment_day`, `credit_limit` y `reminder_days`, y genera statements, ciclos y MSI. `debit`/`prepaid` NO DEBEN llevar esos campos; en su lugar llevan `initial_balance` y `allow_overdraft`.
- **TAR-03 · Método vinculado:** al alta, toda tarjeta crea automáticamente su `payment_method` vinculado (`card_id`), con `type` acorde al behavior (CAT-07). Desactivar la tarjeta desactiva su método (generaliza TDC-12).
- **TAR-04 · Cargo no-crédito:** un gasto con tarjeta `debit`/`prepaid` es **salida de caja inmediata** en su fecha (como efectivo); NO DEBE asignarse a ningún statement ni ciclo (contrasta con TXN-06/TDC-05). Un ingreso o transferencia hacia su método entra igualmente en su fecha.
- **TAR-05 · Saldo:** para `debit`/`prepaid`, `saldo = initial_balance + Σ ingresos + Σ transferencias entrantes − Σ gastos − Σ transferencias salientes` del método de la tarjeta, **calculado en SQL** (DSH-03), nunca un campo mutable. Un gasto que deje el saldo negativo se rechaza (422) salvo `allow_overdraft=true`. El saldo se reporta en la moneda de la tarjeta. `credit` no lleva saldo (su contraparte es la deuda, TDC-09).
- **TAR-06 · Saldo con signo (`signed_balance`):** campo calculado en `CardOut` que expone el balance neto desde la perspectiva de activos del patrimonio: `debit`/`prepaid` → `+card_balance()` (asset positivo); `credit` → `−(TDC-09: a+b+c)` (pasivo, número negativo representando la deuda total). Devuelve `null` si la TDC no tiene `statement_day` configurado (no es cycle-ready). Este campo es el único que DEBEN usar PAT-01 y el dashboard para cálculos de patrimonio; nunca mezclar con `computed_total` interno.
- **TAR-07 · Orden de tarjetas (por usuario):** el orden en que se listan las tarjetas es una **preferencia personal de cada usuario**, no del espacio: se persiste en `card_layouts` (una fila por `user_id`+`space_id`) como lista ordenada de `card_id`. `GET /cards` aplica ese orden sobre la línea base alfabética por `alias`; las tarjetas sin posición explícita (p. ej. recién creadas) van al final en orden de `alias`, y los ids que ya no existen en el espacio se ignoran. El reordenamiento es un **simple ordenamiento de lista**, no un agregado, por lo que no aplica DSH-03. Guardar el layout es accesible a **cualquier rol** (incluido `viewer`) porque no muta datos de dominio compartido (`ActiveSpace`, no `EditorSpace`); RLS lo restringe a su dueño (`user_id = auth.uid()`). No-miembro ⇒ 404 (GLO-05).

- **TDC-01 · Alta (tipo `credit`):** además de los campos comunes de tarjeta (TAR-01/03: alias, banco, red, `last4`), una tarjeta de crédito define su ciclo con `statement_day` (1-28 o `last`) y **a lo más uno** de: `payment_due_days` (1-30, típico 20) o `payment_day` (1-28 o `last`). Estos campos de ciclo son **opcionales al alta** (TDC-15): pueden completarse después por edición. Opcionales: `credit_limit`, color/ícono. NO DEBE almacenarse PAN completo, CVV ni fecha de expiración; solo `last4` (4 dígitos).
- **TDC-02 · Día de corte:** si `statement_day=d`, el corte del mes M es `min(d, último_día(M))`. `statement_day=last` ⇒ último día del mes. Se permite 29/30 capturándolo como `last` o ajustando; la UI ofrece 1-28 y `last` para evitar ambigüedad.
- **TDC-03 · Ciclo:** el ciclo que cierra en el corte C abarca `[corte_anterior + 1 día, C]`. Cada ciclo genera un `card_statement` con `period_start`, `period_end=C`, `due_date`.
- **TDC-04 · Fecha límite:** `due_date = period_end + payment_due_days`; con `payment_day`: el primer `payment_day` estrictamente posterior a `period_end` (ajustado por TDC-02 si el mes es corto). Si `due_date` cae en fin de semana NO se ajusta en v1 (los bancos MX difieren; el usuario ve la fecha exacta que configuró).
- **TDC-05 · Asignación de compra a ciclo:** una compra con fecha `t` se asigna al statement cuyo `period_end` sea el primer corte `≥ t`. Excepción: si `t == period_end`, el comportamiento depende de `card.cutoff_day_policy` (`include` default | `next_cycle`), configurable por tarjeta porque los bancos difieren.
- **TDC-05a · cycle_hint:** cuando la API recibe `cycle_hint: "current" | "next"` en un request de creación o edición de cargo de TDC, y la fecha del cargo coincide exactamente con el día de corte de la tarjeta, `cycle_hint` anula `cutoff_day_policy` para esa transacción. `"current"` fuerza el ciclo que cierra ese día; `"next"` abre el siguiente. Si la fecha no es día de corte, `cycle_hint` se ignora silenciosamente. No se persiste en la transacción; solo se usa durante la asignación a `statement_id`.
- **TDC-06 · Reasignación manual:** el usuario PUEDE mover cualquier cargo al ciclo anterior/siguiente (un paso). La reasignación recalcula totales de ambos statements y queda auditada.
- **TDC-07 · Cierre de statement:** un statement pasa a `closed` automáticamente cuando `hoy > period_end` (job diario). Al cerrar: `computed_total = Σ cargos del ciclo + Σ cuotas MSI con cargo en ese ciclo (MSI-04) − Σ pagos/abonos asignados al ciclo`, y se programa el recordatorio (REM-01).
- **TDC-08 · Estados de statement:** `open → closed → paid | partially_paid | overdue`. `paid` cuando `paid_amount ≥ computed_total`; `overdue` si `hoy > due_date` y no está pagado; `partially_paid` si `0 < paid_amount < computed_total` (puede coexistir con overdue: flag, no estado excluyente — `status` + `is_overdue` booleano).
- **TDC-09 · Deuda:** por tarjeta se reportan tres números, sin mezclarlos: **(a) saldo al corte** = `computed_total − paid_amount` de statements cerrados no pagados; **(b) gasto del ciclo en curso** = Σ cargos del statement `open`; **(c) comprometido futuro** = Σ cuotas MSI `pending` aún no cargadas. Deuda total = a + b + c.
- **TDC-10 · Pago de tarjeta:** se registra como `transfer` (TXN-02) hacia el método de la tarjeta, con asignación a un statement. Abona a `paid_amount`. Si excede el `computed_total`, el excedente queda como saldo a favor que se aplica al siguiente statement al cerrarlo.
- **TDC-11 · Backfill:** al dar de alta una tarjeta se generan statements desde la fecha de la transacción más antigua que la use (o desde hoy si no hay), nunca a futuro: el statement `open` se materializa al vuelo y los futuros no existen hasta que abren.
- **TDC-12 · Desactivación:** una tarjeta con MSI pendientes o statements no pagados PUEDE desactivarse (no acepta cargos nuevos) pero sus ciclos siguen cerrando y sus cuotas siguen cargándose hasta liquidar.
- **TDC-13:** no se calculan intereses ni comisiones en v1 (se asume totalero). El usuario PUEDE capturar intereses/comisiones como cargos manuales con categoría "Comisiones e intereses" (seed al crear la primera tarjeta).
- **TDC-14 · Deuda del corte anterior:** el usuario PUEDE capturar un `opening_balance` (lo que ya debe del estado de cuenta anterior) **tanto al alta como al editar** una TDC existente. Se materializa como un `card_statement` **cerrado** con `computed_total = opening_balance`, `period_end` en el corte inmediato anterior a hoy y `due_date` por TDC-04; entra a TDC-09 (a) y se liquida con un pago normal (TDC-10). Es **un solo corte** (el anterior): al re-capturar se reemplaza el monto del mismo statement (no se duplica). Requiere `statement_day` y términos de pago configurados (si no, 422). Si ese corte **ya tiene cargos itemizados** no se sobrepone un monto manual (409). Su `computed_total` NO se recalcula. El API expone además `next_payment` (monto + `due_date` del corte cerrado más próximo) para mostrar "qué pagar y cuándo".
- **TDC-15 · Captura parcial y edición:** una TDC PUEDE guardarse sin todos los datos del ciclo (`statement_day`/términos opcionales) y completarse después. Toda tarjeta es **editable** (alias, banco, red, `last4`, moneda, color y, según behavior, los campos de ciclo/límite o saldo/sobregiro); el tipo (CAT-08) y su behavior son inmutables. Mientras una TDC no tenga `statement_day`, NO es "cycle-ready": sus cargos NO se asignan a ningún ciclo, el cierre la omite y no acepta pagos sin statement explícito. Al editar el alias se renombra su método de pago vinculado (CAT-07).
- **TDC-16 · Reembolso posterior al corte (abono a pago pendiente):** un `income` con método de pago de una TDC NO sigue TDC-05 cuando su fecha cae en la ventana `(period_end, due_date]` de un statement `closed`/`partially_paid` con saldo pendiente (`computed_total > paid_amount`): en ese caso se asigna a ese statement (el más antiguo que cumpla la condición) y reduce su `computed_total` de inmediato (recálculo igual que TDC-06, no espera al siguiente cierre) — funciona como abono real al pago que está por vencer, replicando el comportamiento real de las TDC (una devolución/reembolso posterior al corte pero anterior a la fecha límite se aplica al estado de cuenta ya emitido). Si ningún statement pendiente cumple la ventana (no hay statement cerrado sin liquidar, o la fecha es posterior a todos los `due_date` pendientes), se aplica TDC-05 normal (se asigna al ciclo cuyo corte sea el primero ≥ la fecha).

## 5. Meses sin intereses (MSI) — R4

- **MSI-01 · Alta:** una compra MSI se captura como transacción expense normal (monto total, fecha, categoría) + plan: `months ∈ [2, 60]`, `credit_card_id` obligatorio (MSI solo existe en tarjetas de behavior `credit`; se rechaza en `debit`/`prepaid`).
- **MSI-02 · Cuotas:** `monthly_amount = round(total / months, 2)` con `ROUND_FLOOR`; la **última cuota absorbe el residuo**: `last = total − monthly_amount × (months − 1)`. Invariante (test obligatorio): `Σ cuotas == total` exacto.
- **MSI-03 · Doble contabilidad evitada:** la transacción de compra MSI NO entra a agregados de gasto mensual ni al `computed_total` de ningún statement por su monto total; lo que entra son sus **cuotas** (cada una en su ciclo). En reportes por categoría, cada cuota hereda la categoría y naturaleza de la compra original.
- **MSI-04 · Calendario de cuotas:** la cuota 1 se carga en el statement al que TDC-05 asigne la fecha de compra; la cuota n en el n-ésimo corte siguiente. `estimated_charge_date = period_end` (día de corte) del ciclo de cada cuota: los bancos imprimen el cargo en el estado de cuenta en el último día del período, que es el día de corte. Si los statements futuros no existen aún (TDC-11), la fecha se calcula proyectando cortes con TDC-02 y se reconcilia cuando el statement abre.
- **MSI-05 · Estados de cuota:** `pending` (futura) → `charged` (su statement cerró; entra al `computed_total`) → `paid` (su statement quedó pagado). El job de cierre (TDC-07) hace la transición.
- **MSI-06 · Vista MSI (R4):** por plan: cuotas pagadas/cargadas/restantes, monto restante = Σ cuotas no-`paid`, fecha del último corte proyectado (`projected_payoff` = `period_end` del statement de la última cuota), fecha de pago proyectada (`projected_payment_date` = `due_date` de ese statement, calculada con TDC-04). Global: tabla mes × tarjeta con el total comprometido por mes futuro (suma de cuotas `pending` por `estimated_charge_date`).
- **MSI-07 · Liquidación anticipada:** el usuario PUEDE marcar un plan como liquidado: las cuotas `pending` se cancelan y se genera un cargo único por su suma en el statement abierto de la tarjeta. Queda auditado (`status=settled_early`).
- **MSI-08 · Edición:** editar el monto/meses de un plan solo si ninguna cuota está `charged`; después, solo MSI-07 o ajustes manuales cuota por cuota. Borrar la transacción de compra borra el plan completo solo si todas las cuotas están `pending`; si no, se bloquea con mensaje.
- **MSI-09:** compras MSI en moneda ≠ moneda de la tarjeta no se soportan en v1 (validación al alta).
- **MSI-10 · Registro por cuota en curso:** permite registrar compras MSI anteriores al sistema aportando solo la información visible en el estado de cuenta. Campos requeridos: `description`, `credit_card_id`, `category_id`, `current_number` (N, ej. 6), `total_months` (M, ej. 12), `monthly_amount` (monto de la cuota, ej. 2692.00), `currency`, `current_is_charged` (si la cuota N ya aparece en el **último estado de cuenta cerrado**). El sistema: (1) crea la transacción-madre excluida de agregados (MSI-03), con `date` = fecha estimada de la primera cuota; (2) `total_amount = monthly_amount × total_months` (aproximado, última cuota absorbe residuo — MSI-02); (3) genera el calendario completo proyectando desde la cuota N con el corte *vigente* de la tarjeta; (4) asigna statuses según `current_is_charged`: **`true`** → cuotas 1..N `paid` (N ya viene contabilizada en el `opening_balance` / Pago pendiente, no se suma de nuevo); cuota N+1 `charged` asignada al statement abierto del ciclo en curso → entra a Ciclo en curso; cuotas N+2..M `pending`; caso borde N==M: todas `paid`, plan `completed` al crearse. **`false`** → cuotas 1..N-1 `paid`; cuota N `charged` asignada al statement abierto → entra a Ciclo en curso; cuotas N+1..M `pending`. Aplican MSI-02, MSI-03, MSI-09. Restricción: 1 ≤ N ≤ M ≤ 60. **Semántica del ancla:** `current_is_charged=true` → ancla en el corte más recientemente cerrado (`period_end ≤ hoy`); `current_is_charged=false` → ancla en el corte que cierra el ciclo actualmente abierto (el próximo corte futuro cuando hoy no es día de corte, o el siguiente si hoy sí lo es).

## 6. Recurrentes (REC) — R9

- **REC-01 · Regla:** plantilla de transacción (tipo, monto, moneda, categoría, método, descripción) + `frequency` (`weekly | biweekly | monthly | yearly`), `start_date`, `end_date?` o `max_occurrences?`, `day_rule` para mensual (`día N` con ajuste a último día si el mes es corto, o `último día`).
- **REC-02 · Generación:** job diario (00:30 tz del espacio) genera las instancias con `scheduled_date ≤ hoy`. Idempotencia: constraint único `(recurring_rule_id, scheduled_date)` — re-ejecutar el job nunca duplica.
- **REC-03 · Revisión:** toda instancia generada nace con `needs_review=true` y aparece en una bandeja "Por confirmar". El usuario confirma (1 tap), ajusta monto (caso luz/agua con monto variable: la regla PUEDE marcarse `amount_is_estimate`) o descarta (se crea tombstone para que REC-02 no la regenere).
- **REC-04 · Cambios a la regla:** editar una regla afecta solo instancias futuras; las generadas no se tocan. Pausar (`is_active=false`) detiene generación sin borrar historial. Eliminar físicamente la regla es válido; las instancias ya confirmadas se conservan con `recurring_rule_id=NULL` (trazabilidad del historial sin la regla). Los tombstones se borran en cascada. Si la regla apunta a categoría/método desactivado, se pausa automáticamente y se notifica.
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

- **REM-01 · TDC:** al cerrar un statement (TDC-07) se programan recordatorios a `due_date − N días` con N = `card.reminder_days` (default `[3, 1]`). **Solo se crean recordatorios con `fire_at ≥ hoy`**: si el corte ya venció al momento de cerrarse (p. ej. backfill de gastos históricos), no se generan notificaciones de cortes pasados. Aplica igualmente al registrar `opening_balance` (TDC-14): el statement sintético del corte anterior también programa sus recordatorios futuros en el mismo momento de crearse, con el mismo filtro de fecha.
- **REM-01b · Cancelación al pagar:** cuando un statement queda totalmente pagado, se cancelan sus recordatorios en estado `pending` **y** `sent`. Esto garantiza que las notificaciones ya enviadas desaparezcan del inbox en cuanto se registra el pago.
- **REM-02:** un recordatorio se envía una sola vez por (statement, offset, canal). Reintentos ante fallo de envío: 3 con backoff, luego `failed` visible en UI.
- **REM-03 · Contenido:** alias de tarjeta, monto a pagar (`computed_total − paid_amount`), fecha límite. Nunca incluir `last4` completo en notificaciones push (privacidad en lockscreen): solo alias.
- **REM-04 · Canales:** v1: in-app (centro de notificaciones) + email (Resend). Push llega con la PWA (Fase 6). Preferencias por usuario y por tipo (TDC, presupuesto) en settings.
- **REM-05 · Descarte:** el usuario PUEDE descartar cualquier recordatorio in-app (`DELETE /notifications/{id}`). El registro pasa a `dismissed` (soft-delete): se oculta del inbox pero se conserva para auditoría. Solo se puede descartar recordatorios del propio espacio activo (GLO-05). No afecta el estado del statement ni otros canales.
- **REM-06 · Inbox in-app:** `GET /notifications` devuelve el centro de notificaciones del **espacio activo** (GLO-05): canal `in_app`, únicamente los ya disparados (`status = sent`) y no descartados. Los `pending` (programados a futuro), `canceled` (REM-01b) y `dismissed` (REM-05) **no** aparecen; para auditoría existe `GET /notifications/history`, que devuelve todos los estados. Orden: `fire_at` descendente, luego `created_at` descendente.
- **REM-07 · Leído vs. descartado:** son estados independientes. `read_at` (timestamp, nulo = no leído) marca que el usuario **vio** el aviso; el descarte (REM-05) lo **quita** del inbox. `GET /notifications/unread-count` alimenta el badge de la campana contando los del inbox (REM-06) con `read_at IS NULL`. `POST /notifications/read-all` (y `POST /notifications/{id}/read`) marcan leído: es idempotente y **no** altera `status`, por lo que un aviso leído sigue visible hasta que se descarte o se cancele al pagar (REM-01b). Marcar leído no requiere rol editor: cualquier miembro del espacio puede hacerlo. **v1: `read_at` y el descarte son por espacio, no por usuario** — el recordatorio pertenece al espacio (no hay tabla por miembro), así que si un miembro lo lee o lo descarta, deja de estar no-leído para todos. Se acepta la simplificación; el estado por miembro queda para cuando exista preferencia de notificaciones por usuario (REM-04).

## 10. Inversiones (INV) — R5, R15

- **INV-01:** `investment_account` (kind: `crypto | stocks | fixed_income | other`) contiene `holdings` (símbolo, cantidad, costo promedio, moneda de costo). Cantidad con `NUMERIC(28,10)` (crypto necesita decimales finos; GLO-01 aplica solo a montos monetarios).
- **INV-02 · Movimientos:** alta por operaciones `buy | sell | deposit | withdraw`, no edición directa de cantidades. `buy`: nuevo costo promedio ponderado = `(qty_old × avg_old + qty_in × precio) / qty_new`. `sell`: la cantidad baja, el costo promedio NO cambia; P&L realizado = `qty × (precio_venta − avg_cost)`, registrado en el movimiento. `sell` con qty > posición se rechaza.
- **INV-03 · Precios crypto:** proxy FastAPI → interfaz `PriceProvider` con `CoinGeckoProvider` default (`CoinMarketCapProvider` alterno), caché TTL 10 min, sin exponer la key. Si el proveedor falla, se sirve el último precio cacheado con su `fetched_at` visible ("precio de hace 2 h"). Presupuesto de llamadas: 1 batch (`/simple/price` con todos los símbolos del sistema) por refresh, no por usuario — CoinGecko cobra 1 crédito por llamada sin importar el batch (~4,300 de 10,000/mes).
- **INV-03b · Backfill histórico:** al dar de alta un holding crypto, se PUEDE rellenar la gráfica con históricos de CoinGecko (hasta 1 año, free tier). Los puntos backfilled se marcan `source=backfill` y nunca sobreescriben snapshots propios (INV-05).
- **INV-04 · Precios no-crypto:** captura manual de precio por símbolo (v1), **por espacio** (GLO-05): el precio manual vive en `manual_asset_prices (space_id, symbol)` y solo lo ven los holdings de ese espacio. El usuario actualiza cuando quiera; la UI muestra la fecha del último precio. Solo se acepta capturar símbolos que el espacio efectivamente posee (algún holding con `quantity > 0`).
- **INV-04b · Precedencia y aislamiento de precios:** al valuar un holding, el precio manual **del espacio activo** (INV-04) gana sobre la caché del proveedor (INV-03); si no hay manual, se usa la caché global. Un precio manual **nunca** escribe en la caché compartida ni la invalida: dos espacios pueden tener precios distintos para el mismo símbolo, y capturar uno a mano no altera la valuación de ningún otro espacio ni detiene el refresco del proveedor para ese símbolo. La moneda del precio manual (para FX-04) es la del espacio que lo capturó.
- **INV-05 · Snapshot:** job diario (23:50 tz espacio) persiste `portfolio_snapshots` con valor total y desglose por holding (precio usado, FX usado). Es la fuente de las gráficas históricas — nunca se reconstruyen con precios actuales.
- **INV-06 · P&L:** no realizado por holding = `qty × precio_actual − qty × avg_cost` (convertido a base con FX-04). La vista separa P&L realizado (de ventas) y no realizado.

## 11. Patrimonio neto (PAT) — R12

- **PAT-01:** `activos = Σ valor de portafolios (INV-05) + Σ saldo de tarjetas no-crédito (TAR-05)`; `pasivos = Σ deuda de tarjetas de crédito (TDC-09: a+b+c)`. `patrimonio = activos − pasivos`. Job diario lo persiste en `net_worth_snapshots` (mismo horario que INV-05, después de él); el `breakdown` separa inversiones, efectivo en tarjetas y deuda.
- **PAT-02:** v1 modela como activo el saldo de tarjetas `debit`/`prepaid` (TAR-05) además de las inversiones. NO modela efectivo suelto ni cuentas bancarias sin una tarjeta registrada en la app. La UI lo declara explícitamente ("patrimonio = inversiones + saldos de tarjetas − deuda de crédito") para no inducir a error. Modelar saldos de efectivo/cuentas sin tarjeta es candidato a R16 futuro.

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
- **DSH-04 · Gasto devengado:** el dashboard reporta **gasto devengado** — cuándo compraste, no cuándo pagaste. Una compra con TDC cuenta en su fecha de compra (totales, categorías, presupuestos), no cuando se liquida el statement. v1 NO ofrece vista de flujo de caja; el pago del statement se refleja en la deuda de la tarjeta (TDC-09) y en próximos compromisos (DSH-05), nunca en los agregados de gasto. (Vista de flujo de caja "cuándo pagaste" es backlog.)
- **DSH-05 · Próximos compromisos:** widget con statements por vencer (TDC-08), cuotas MSI del próximo mes (MSI-06) y recurrentes próximas (REC), ordenados por fecha.

## 14. Pronóstico de flujo (PRO) — R17

El pronóstico responde "¿con mis ingresos futuros podré pagar lo que se viene?". Es la versión **a futuro** del flujo de caja; el flujo de caja *histórico* ("cuándo pagaste") sigue en backlog (DSH-04).

- **PRO-01 · Naturaleza:** el pronóstico es una proyección de flujo de caja **read-only** sobre un horizonte configurable (default 6 meses; opciones 3/6/12). Se calcula al vuelo: NO persiste nada, NO materializa statements ni cuotas (respeta TDC-11/MSI-04) y NO escribe en BD. Es lo opuesto al gasto devengado del dashboard (DSH-04): aquí importa **cuándo sale/entra el dinero**, no cuándo se compró. Todo en `date` puro (GLO-02) y `Decimal` (GLO-01).
- **PRO-02 · Caja inicial:** la liquidez de arranque = Σ `card_balance()` (TAR-05) de tarjetas activas de behavior `debit`/`prepaid` **+** un `cash_adjustment` opcional capturado por el usuario para efectivo/cuentas bancarias no modeladas en la app (PAT-02). Las inversiones (INV) NO son líquidas y NO entran. El `cash_adjustment` no se persiste; viaja en el request.
- **PRO-03 · Salidas proyectadas:** sobre `(hoy, hoy + horizonte]`:
  - **Pagos de TDC** (behavior `credit`, cycle-ready TDC-15): por cada ciclo del horizonte se proyecta el monto del statement = cargos ya asignados al statement abierto + cuotas MSI `pending` cuya `estimated_charge_date` cae en el ciclo (MSI-04) + ocurrencias de recurrentes-gasto (REC) cuyo método de pago pertenece a esa tarjeta, asignadas al ciclo por TDC-05; menos el saldo a favor conocido. El egreso se fecha en el `due_date` proyectado (TDC-04). Los statements ya existentes cerrados/parciales no pagados entran con su saldo real (TDC-09a) en su `due_date`.
  - **Gastos no-crédito recurrentes** (efectivo/débito/prepago, método sin tarjeta de crédito): egreso inmediato en la fecha de ocurrencia (TAR-04).
  - **Transacciones futuras manuales** (TXN-03, `date > hoy`): si son cargo de crédito alimentan el statement proyectado de su tarjeta; si son cash/débito o ingreso, entran directo en su fecha.
- **PRO-04 · Entradas proyectadas:** ocurrencias de recurrentes-ingreso (nómina, REC) en su fecha + ingresos futuros manuales (TXN-03). Los montos marcados `amount_is_estimate` (REC-03) se usan y se reportan como aproximados.
- **PRO-05 · Detección de sobregiro:** recorriendo los eventos ordenados por fecha, `saldo(t) = caja_inicial + Σ entradas(≤t) − Σ salidas(≤t)`. Si tras aplicar una salida `saldo(t) < 0`, esa obligación queda **no cubierta**: se reporta su fecha, el faltante (`−saldo(t)`, acotado al monto de la obligación) y se marca el **primer punto de sobregiro** global del horizonte. El pronóstico devuelve la serie de saldo por evento, la lista de obligaciones con su flag de cobertura y las alertas.
- **PRO-06 · Moneda:** todo se reporta en `base_currency`. Montos en moneda ≠ base se convierten con la **última tasa disponible** (no congelada — es proyección, análogo a FX-04) y se marcan como aproximados. Si no hay tasa, se usa 1 y se advierte.

---

## Matriz requerimiento → reglas

| Req | Reglas |
|---|---|
| R1 gastos | TXN-01…09, GLO-01/02 |
| R2 catálogos | CAT-01…08 |
| R3 tarjetas | TAR-01…06, TDC-01…16, CAT-08 |
| R4 MSI | MSI-01…10 |
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
| R17 pronóstico | PRO-01…06, TDC-04/09, MSI-04, REC-01, TAR-05 |

## Casos de prueba obligatorios (mínimos)

1. **TDC-02/04:** tarjeta con corte `last` y `payment_due_days=20` en febrero bisiesto y no bisiesto; corte 28 en todos los meses.
2. **TDC-05:** compra exactamente el día de corte con ambas políticas (`include`/`next_cycle`).
3. **MSI-02:** `1000.00 / 3` ⇒ cuotas `333.33, 333.33, 333.34`; `Σ == total` para 1000 combinaciones aleatorias (property-based, hypothesis).
4. **MSI-03/DSH-02:** compra MSI de 12,000 a 12 meses ⇒ el gasto del mes de compra refleja 1,000, no 12,000, y ningún agregado suma 13,000.
5. **REC-02:** ejecutar el job 2 veces el mismo día ⇒ cero duplicados; REC-05 con 10 días de downtime ⇒ 10 instancias correctas.
6. **FX-03:** editar una transacción vieja no cambia su tasa persistida; un gasto USD del 2026-01-15 usa la tasa de esa fecha aunque hoy sea otra.
7. **TDC-10:** pago mayor al statement ⇒ saldo a favor aplicado al siguiente cierre.
8. **GLO-05/ESP-03:** un viewer no puede mutar nada (test de permisos por endpoint); un usuario sin membresía recibe 404 (no 403, para no filtrar existencia).
9. **TAR-04/05/DSH-02:** un gasto de 500 con tarjeta de débito descuenta el saldo, NO toca ningún statement y cuenta como salida en su fecha; una nómina (income) hacia el método de la tarjeta sube el saldo. Gasto que excede el saldo sin `allow_overdraft` ⇒ 422; con `allow_overdraft=true` ⇒ permitido (saldo negativo).
10. **PAT-01:** `patrimonio = inversiones + saldos de tarjetas no-crédito − deuda de crédito`; al cambiar un saldo (nuevo gasto/ingreso) el siguiente snapshot lo refleja.
11. **PRO-05 (sobregiro):** TDC con `due_date` el día 17 y nómina recurrente el día 15. Si el ingreso acumulado antes del 17 + caja inicial no cubre el pago del statement ⇒ la obligación se marca **no cubierta** con el faltante exacto y se reporta el primer sobregiro; si la nómina alcanza ⇒ sin sobregiro. Una compra MSI cuyas cuotas caen en cortes futuros (PRO-03) empuja el sobregiro al mes correcto. El pronóstico no materializa statements (conteo de `card_statements` constante antes/después).
12. **TDC-16:** reembolso (`income`) el día después del corte con un statement `closed` pendiente cuyo `due_date` aún no pasa ⇒ se resta de ese `computed_total`, no del ciclo abierto siguiente. Mismo reembolso sin ningún statement pendiente en esa ventana (tarjeta recién creada, o fecha posterior al `due_date`) ⇒ cae en la asignación normal de TDC-05.
