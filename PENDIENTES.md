# PENDIENTES.md — Bugs y deuda técnica detectados

Hallazgos encontrados al implementar o auditar features, que **no** se corrigieron en el momento por estar fuera del alcance del cambio en curso. Cada uno tiene un ID estable (`PEND-01`…) para referenciarlo en commits y PRs, igual que `REGLAS_NEGOCIO.md` (reglas) y `OPORTUNIDADES.md` (features nuevas). Al corregir uno, moverlo a un historial o marcarlo `[RESUELTO]` con el commit que lo cerró.

---

### PEND-01 · `recompute_statement_total` puede sobrescribir un `opening_balance` manual (TDC-14) 🟡 [RESUELTO]

**Qué:** si a un statement `closed` creado como saldo de apertura manual (TDC-14: `computed_total = opening_balance`, sin cargos itemizados en ese momento) se le asigna **después** una transacción — un cargo tardío (TDC-06) o un reembolso (TDC-16) que caiga en su ventana `(period_end, due_date]` —, la siguiente llamada a `recompute_statement_total` (`backend/app/services/cards.py:668-677`) recalcula `computed_total` como `_raw_statement_total(...) - applied_credit`, es decir, **solo la suma de las transacciones itemizadas realmente ligadas al statement**, ignorando por completo el monto manual (`opening_balance`) que el usuario capturó.

**Dónde:** `backend/app/services/cards.py`
- `_raw_statement_total` (línea 640): suma `expense` − `income` + MSI de transacciones con `statement_id == statement.id`; no sabe nada de `opening_balance`.
- `recompute_statement_total` (línea 668): sobrescribe `statement.computed_total` con ese total crudo cada vez que se llama, sin distinguir "statement con opening_balance manual y sin cargos itemizados" de "statement con cargos reales".
- Disparadores: `transactions.py` líneas 279/387/389/432 (crear/editar/borrar transacción) y `cards.py` líneas 1037-1038 (`move_charge_cycle`, TDC-06).

**Por qué importa:** TDC-14 dice explícitamente "si ese corte ya tiene cargos itemizados no se sobrepone un monto manual (409)" — protege el sentido contrario, pero no hay protección para cuando el monto manual **ya existe** y luego llegan cargos/reembolsos itemizados a ese mismo corte: el `opening_balance` capturado por el usuario desaparece silenciosamente, reemplazado por un total que probablemente no refleja la deuda real (p. ej. un statement con `opening_balance = 5000` que recibe un reembolso tardío de 200 quedaría en `computed_total = -200`, no `4800`).

**Cómo reproducir (hipotético, no cubierto por test hoy):** dar de alta una TDC con `opening_balance` (TDC-14) para el corte anterior a hoy; luego, antes de pagarlo, registrar un cargo tardío o un reembolso con fecha dentro de ese periodo. `GET /cards/{id}/statements` mostrará un `computed_total` que ignora el `opening_balance` original.

**Fix sugerido (no implementado):** que `_raw_statement_total`/`recompute_statement_total` sepan distinguir un statement "opening balance puro" (sin transacciones propias al momento de crearse) y, si aún no tiene cargos itemizados propios previos a la nueva transacción, sumen sobre la base del `opening_balance` en vez de reemplazarlo — o, más simple, requerir que TDC-14 marque el statement con un flag (`is_manual_opening`) que bloquee `recompute_statement_total` hasta que el usuario reconcilie manualmente.

**Detectado:** 2026-07-09, durante el diseño de TDC-16 (reembolsos posteriores al corte).

**Resuelto:** 2026-07-10, commit siguiente. Se agregó la columna `card_statements.opening_balance` (migración `0012`, con backfill para statements existentes sin cargos itemizados) y `_raw_statement_total` ahora suma `opening_balance + cargos − reembolsos + MSI` en vez de descartarlo. `set_opening_balance`/`get_opening_balance` (TDC-14) leen/escriben el nuevo campo. Tests de regresión: `test_pend01_late_refund_does_not_wipe_manual_opening_balance`, `test_pend01_late_charge_adds_to_manual_opening_balance` (`backend/tests/test_cards.py`).

---

### PEND-02 · `forecast._income_events` no excluye ingresos ya asignados a un statement de TDC 🟢 [RESUELTO]

**Qué:** en `backend/app/services/forecast.py`, `_non_credit_expense_events` excluye explícitamente gastos con `statement_id IS NOT NULL` (ya contados vía TDC-09/`_card_due_events`) para no duplicarlos en el pronóstico (PRO-01). `_income_events` (líneas ~368-432) **no tiene el filtro equivalente**: un `income` futuro (`date > hoy`) hacia una TDC (p. ej. un reembolso programado) entraría como entrada de caja "in" en el pronóstico general, sin importar que además vaya a reducir el `computed_total` de un statement de TDC contado aparte en `_card_due_events`.

**Por qué importa:** con TDC-16 ahora es más probable que existan `income` hacia TDC con fecha futura cercana (reembolsos capturados por adelantado). Si esa fecha es futura y cae dentro de la ventana de un statement pendiente, el monto podría contarse dos veces en el pronóstico: una vez como "ingreso" genérico (PRO-04) y otra reduciendo la obligación de la TDC (PRO-03).

**Dónde:** `backend/app/services/forecast.py`, función `_income_events`, contrastar con el filtro de `_non_credit_expense_events` (línea ~471, `Transaction.statement_id.is_(None)`).

**Fix sugerido (no implementado):** aplicar el mismo filtro `Transaction.statement_id.is_(None)` (o excluir por `card_id IS NOT NULL` con behavior credit) en `_income_events`.

**Detectado:** 2026-07-09, mismo análisis de TDC-16 (preexistente, no introducido por ese cambio).

**Resuelto:** 2026-07-10, commit siguiente. Se agregó `Transaction.statement_id.is_(None)` al filtro de `_income_events`, igual que ya tenía `_non_credit_expense_events`. Test de regresión: `test_pend02_future_refund_on_statement_not_double_counted` (`backend/tests/test_forecast.py`).
