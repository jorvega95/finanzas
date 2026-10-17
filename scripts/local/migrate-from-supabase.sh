#!/usr/bin/env bash
# Fases 0 y 2: respaldo final de Supabase + copia de datos a la base local +
# verificación tabla por tabla (conteos, sumas de columnas numéricas y md5 del
# contenido). Al final fija LOCAL_USER_ID con tu perfil (GLO-07).
#
# Uso:
#   SUPABASE_DB_URL='postgresql://postgres.<ref>:<pass>@<host>:5432/postgres' \
#     scripts/local/migrate-from-supabase.sh [--force]
# Si SUPABASE_DB_URL no está definido se toma DATABASE_URL de backend/.env.
# Usa la conexión directa o el *session* pooler (puerto 5432), no el de 6543.
# --force: vacía la base local antes de copiar (si ya tiene datos).
# No necesita sudo.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

SRC="${SUPABASE_DB_URL:-}"
if [[ -z "$SRC" && -f "$RAIZ/backend/.env" ]]; then
  SRC=$(sed -n 's/^DATABASE_URL=//p' "$RAIZ/backend/.env" | tail -n1)
fi
SRC="${SRC/postgresql+asyncpg:/postgresql:}"
[[ "$SRC" == *supabase* ]] || fail "Define SUPABASE_DB_URL con la conexión de Supabase"
[[ "$SRC" == *:6543/* ]] && fail "El transaction pooler (6543) no sirve para pg_dump; usa el puerto 5432"
[[ "$SRC" == *sslmode=* ]] || SRC="$SRC$([[ "$SRC" == *\?* ]] && echo '&' || echo '?')sslmode=require"

pg_isready -h "$PG_SOCKET_DIR" -q || fail "Postgres local no responde (setup-postgres.sh)"
[[ -f "$ENV_FILE" ]] || fail "Falta $ENV_FILE; corre primero scripts/local/install.sh"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

remote_psql() { PGTZ=UTC psql "$SRC" -X -v ON_ERROR_STOP=1 "$@"; }
local_q() { PGTZ=UTC local_psql -X "$@"; }

info "Deteniendo el servicio local mientras se copia..."
systemctl --user stop finanzas.service 2>/dev/null || true

if [[ $(local_q -Atc "SELECT count(*) FROM public.profiles") != 0 ]]; then
  $FORCE || fail "La base local ya tiene datos; vuelve a correr con --force para vaciarla"
  info "Vaciando base local (--force)..."
  tables=$(local_q -Atc "SELECT string_agg(format('public.%I', tablename), ', ') FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")
  local_q -c "TRUNCATE $tables CASCADE" >/dev/null
fi

# La copia y la verificación exigen el mismo esquema en ambos lados. No basta
# con alembic_version: en Supabase pueden haberse aplicado cambios a mano sin
# actualizarla. Se compara la estructura real (columnas y tipos) y se elige la
# versión local que coincida: head, o la que declara Supabase. Supabase nunca
# se modifica.
FINGERPRINT="SELECT table_name, column_name, data_type,
  coalesce(character_maximum_length::text, ''), coalesce(numeric_precision::text, ''),
  coalesce(numeric_scale::text, ''), is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name <> 'alembic_version'
ORDER BY 1, 2"
remote_psql -At -c "$FINGERPRINT" > "$WORK/fp_remote.txt"
local_fp() { local_q -At -c "$FINGERPRINT" > "$WORK/fp_local.txt"; cmp -s "$WORK/fp_remote.txt" "$WORK/fp_local.txt"; }

# Deriva típica: una migración posterior aplicada a mano en Supabase sin
# subir alembic_version (p. ej. 0015 ensancha recurring_rules.frequency). Si
# la ÚNICA diferencia son varchar más largos en Supabase, se ensanchan en la
# local y se copian los CHECK de esas tablas tal cual están en Supabase. Luego
# `alembic upgrade head` aplica las migraciones reales sobre los datos.
fp_row() { awk -F'|' -v t="$2" -v c="$3" '$1 == t && $2 == c' "$1"; }

# (Dentro de los `while read`, psql va con </dev/null para no comerse la
# entrada del bucle.)
reconcile_widened_columns() {
  local keys_r keys_l t c typ rlen llen
  keys_r=$(cut -d'|' -f1,2 "$WORK/fp_remote.txt")
  keys_l=$(cut -d'|' -f1,2 "$WORK/fp_local.txt")
  [[ "$keys_r" == "$keys_l" ]] || return 1
  local -a tables=()
  while IFS='|' read -r t c typ rlen _; do
    llen=$(fp_row "$WORK/fp_local.txt" "$t" "$c" | cut -d'|' -f4)
    [[ "$typ" == "character varying" && -n "$rlen" && -n "$llen" ]] || return 1
    (( rlen > llen )) || return 1
    # Las demás columnas de la fila (nulabilidad, etc.) deben coincidir.
    [[ "$(fp_row "$WORK/fp_remote.txt" "$t" "$c" | cut -d'|' -f5-)" \
       == "$(fp_row "$WORK/fp_local.txt" "$t" "$c" | cut -d'|' -f5-)" ]] || return 1
    tables+=("$t")
    info "Supabase tiene $t.$c como varchar($rlen) (local: $llen); se ensancha en local"
    local_q -qc "ALTER TABLE public.\"$t\" ALTER COLUMN \"$c\" TYPE varchar($rlen)" </dev/null
  done < <(comm -23 "$WORK/fp_remote.txt" "$WORK/fp_local.txt")
  (( ${#tables[@]} )) || return 1
  local name def
  for t in $(printf '%s\n' "${tables[@]}" | sort -u); do
    # Los CHECK locales viejos rechazarían los valores nuevos: se reemplazan
    # por los de Supabase.
    while read -r name; do
      [[ -n "$name" ]] && local_q -qc "ALTER TABLE public.\"$t\" DROP CONSTRAINT \"$name\"" </dev/null
    done < <(local_q -At -c "SELECT conname FROM pg_constraint WHERE conrelid = 'public.$t'::regclass AND contype = 'c'")
    while IFS=$'\t' read -r name def; do
      [[ -n "$name" ]] || continue
      info "Copiando el CHECK $name de Supabase"
      local_q -qc "ALTER TABLE public.\"$t\" ADD CONSTRAINT \"$name\" $def" </dev/null
    done < <(remote_psql -At -F $'\t' -c "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
               WHERE conrelid = 'public.$t'::regclass AND contype = 'c' ORDER BY conname")
  done
  local_fp
}

info "Comprobando esquemas..."
src_ver=$(remote_psql -Atc "SELECT version_num FROM public.alembic_version")
local_alembic upgrade head >/dev/null 2>&1 || fail "alembic upgrade head falló en la base local"
head_ver=$(local_q -Atc "SELECT version_num FROM public.alembic_version")
if local_fp; then
  copy_ver=$head_ver
  [[ "$src_ver" == "$head_ver" ]] \
    || info "Supabase dice $src_ver pero su estructura ya es $head_ver; se copia en $head_ver"
else
  info "Supabase=$src_ver, local=$head_ver: probando la base local en $src_ver..."
  local_alembic downgrade "$src_ver" >/dev/null 2>&1 \
    || fail "No se pudo bajar la local a $src_ver"
  if ! local_fp && ! reconcile_widened_columns; then
    diff "$WORK/fp_remote.txt" "$WORK/fp_local.txt" | head -40 || true
    local_alembic upgrade head >/dev/null 2>&1 || true
    fail "La estructura de Supabase no coincide con ninguna versión local (arriba: < Supabase, > local)"
  fi
  copy_ver=$src_ver
fi
info "Esquemas idénticos en $copy_ver"

# --- Fase 0: respaldo final completo de Supabase (red de seguridad) -------
mkdir -p "$BACKUP_DIR"
final="$BACKUP_DIR/supabase-final-$(date +%Y%m%d-%H%M%S).dump"
info "Respaldo completo de Supabase -> $final"
pg_dump "$SRC" --schema=public -Fc -f "$final"
pg_restore --list "$final" >/dev/null || fail "El respaldo de Supabase no es legible"

# --- Fase 2: copia de datos -------------------------------------------------
info "Exportando datos de Supabase..."
pg_dump "$SRC" --data-only --schema=public --exclude-table=public.alembic_version \
  --no-owner --no-privileges -f "$WORK/data.sql"

info "Restaurando en la base local..."
# pg_dump ordena las tablas por dependencias de FK. La única circular es
# categories -> categories (padre), y Postgres valida esa FK al final de cada
# COPY, así que basta tu propio usuario. -1: todo o nada.
local_q -q -1 -f "$WORK/data.sql" >/dev/null

# --- Verificación -----------------------------------------------------------
info "Verificando..."
# Una consulta por tabla: conteo, suma de cada columna numérica y md5 del
# contenido completo ordenado. Se genera del catálogo local y corre en ambos.
cat > "$WORK/gen.sql" <<'SQL'
SELECT string_agg(q, E'\nUNION ALL\n' ORDER BY t) || E'\nORDER BY 1;'
FROM (
  SELECT c.relname AS t, format(
    $f$SELECT %L AS tabla, count(*)::text AS filas, %s AS sumas, md5(coalesce(string_agg(__row, '' ORDER BY __row), '')) AS md5 FROM (SELECT x.*, ROW(%s)::text AS __row FROM public.%I x) x$f$,
    c.relname,
    coalesce(
      (SELECT string_agg(format('coalesce(sum(%I),0)::text', a.attname), $s$ || '|' || $s$ ORDER BY a.attnum)
       FROM pg_attribute a
       WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
         AND a.atttypid IN ('numeric'::regtype, 'int4'::regtype, 'int8'::regtype)),
      $d$'-'$d$),
    (SELECT string_agg(format('x.%I', a.attname), ', ' ORDER BY a.attname)
     FROM pg_attribute a
     WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped),
    c.relname) AS q
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> 'alembic_version'
) s;
SQL
local_q -At -f "$WORK/gen.sql" > "$WORK/verify.sql"

remote_psql -At -F $'\t' -f "$WORK/verify.sql" > "$WORK/remote.tsv"
local_q -At -F $'\t' -f "$WORK/verify.sql" > "$WORK/local.tsv"

if ! diff -u "$WORK/remote.tsv" "$WORK/local.tsv" > "$WORK/diff.txt"; then
  cat "$WORK/diff.txt"
  fail "Los datos NO coinciden (arriba el diff Supabase vs local). Supabase quedó intacto."
fi
printf '%-28s %8s\n' TABLA FILAS
awk -F'\t' '{ printf "%-28s %8s\n", $1, $2 }' "$WORK/local.tsv"
info "Verificación OK: conteos, sumas y md5 idénticos en $(wc -l < "$WORK/local.tsv") tablas"

if [[ "$copy_ver" != "$head_ver" ]]; then
  info "Subiendo la base local de $copy_ver a $head_ver..."
  local_alembic upgrade head
fi

# --- LOCAL_USER_ID (GLO-07) -------------------------------------------------
mapfile -t profiles < <(local_q -At -F $'\t' -c "SELECT id, coalesce(email,''), display_name FROM public.profiles ORDER BY created_at")
if (( ${#profiles[@]} == 1 )); then
  choice="${profiles[0]}"
else
  info "Hay ${#profiles[@]} perfiles; ¿cuál eres tú?"
  select choice in "${profiles[@]}"; do [[ -n "$choice" ]] && break; done
fi
user_id=$(cut -f1 <<<"$choice")
user_email=$(cut -f2 <<<"$choice")
env_set LOCAL_USER_ID "$user_id"
[[ -n "$user_email" ]] && env_set LOCAL_USER_EMAIL "$user_email"
info "LOCAL_USER_ID=$user_id ($user_email)"

systemctl --user start finanzas.service
info "Migración completa. Supabase NO se modificó; páusalo cuando valides la app."
