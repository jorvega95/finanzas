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

info "Comprobando versiones de esquema..."
src_ver=$(remote_psql -Atc "SELECT version_num FROM public.alembic_version")
dst_ver=$(local_q -Atc "SELECT version_num FROM public.alembic_version")
[[ "$src_ver" == "$dst_ver" ]] || fail "Esquema distinto: Supabase=$src_ver local=$dst_ver (corre alembic upgrade en ambos)"

info "Deteniendo el servicio local mientras se copia..."
systemctl --user stop finanzas.service 2>/dev/null || true

if [[ $(local_q -Atc "SELECT count(*) FROM public.profiles") != 0 ]]; then
  $FORCE || fail "La base local ya tiene datos; vuelve a correr con --force para vaciarla"
  info "Vaciando base local (--force)..."
  tables=$(local_q -Atc "SELECT string_agg(format('public.%I', tablename), ', ') FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")
  local_q -c "TRUNCATE $tables CASCADE" >/dev/null
fi

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
# replica: no dispara triggers ni valida FKs durante la carga (hay FKs
# circulares profiles <-> spaces); requiere superusuario, de ahí el sudo.
{ echo "SET session_replication_role = replica;"; cat "$WORK/data.sql"; } \
  | sudo -u postgres psql -X -q -1 -v ON_ERROR_STOP=1 -d "$DB_NAME" >/dev/null

# --- Verificación -----------------------------------------------------------
info "Verificando..."
# Una consulta por tabla: conteo, suma de cada columna numérica y md5 del
# contenido completo ordenado. Se genera del catálogo local y corre en ambos.
cat > "$WORK/gen.sql" <<'SQL'
SELECT string_agg(q, E'\nUNION ALL\n' ORDER BY t) || E'\nORDER BY 1;'
FROM (
  SELECT c.relname AS t, format(
    $f$SELECT %L AS tabla, count(*)::text AS filas, %s AS sumas, md5(coalesce(string_agg(x::text, '' ORDER BY x::text), '')) AS md5 FROM public.%I x$f$,
    c.relname,
    coalesce(
      (SELECT string_agg(format('coalesce(sum(%I),0)::text', a.attname), $s$ || '|' || $s$ ORDER BY a.attnum)
       FROM pg_attribute a
       WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
         AND a.atttypid IN ('numeric'::regtype, 'int4'::regtype, 'int8'::regtype)),
      $d$'-'$d$),
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
