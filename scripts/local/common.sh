# Variables compartidas por los scripts locales (GLO-07). Se hace `source`.
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/finanzas"
ENV_FILE="$CONFIG_DIR/finanzas.env"
PORT="${FINANZAS_PORT:-8765}"
APP_URL="http://127.0.0.1:$PORT"
DB_NAME="finanzas"
DB_USER="$USER"
PG_SOCKET_DIR="/run/postgresql"
BACKUP_DIR="${FINANZAS_BACKUP_DIR:-$HOME/Documents/finanzas-backups}"
# FAC-10: facturas, acuses y comprobantes (fuera de la BD). Un FILES_DIR en
# ENV_FILE manda sobre este default; backup.sh lo respalda (GLO-08).
FILES_DIR_DEFAULT="${XDG_DATA_HOME:-$HOME/.local/share}/finanzas/files"

info() { printf '\033[1;34m[finanzas]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[finanzas] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# Con sudo, $USER/$HOME serían los de root: rol de Postgres, config y
# servicio systemd --user quedarían bajo root. Cada script pide sudo solo
# en los pasos que lo necesitan.
if [[ $EUID -eq 0 ]]; then
  fail "No corras este script con sudo; ejecútalo como tu usuario (pedirá sudo cuando haga falta)"
fi

# psql/pg_dump contra la base local por socket (auth peer, sin contraseña).
local_psql() { psql -h "$PG_SOCKET_DIR" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 "$@"; }

# alembic contra la base local con la config del servicio (ENV_FILE).
local_alembic() {
  (cd "$RAIZ/backend" && set -a \
    && source <(grep -E '^(DATABASE_URL|AUTH_MODE|LOCAL_USER_ID)=' "$ENV_FILE") \
    && set +a && uv run alembic "$@")
}

# Lee una clave de ENV_FILE sin hacer source (no ejecuta su contenido).
env_get() { [[ -f "$ENV_FILE" ]] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1; }

env_set() {
  local key="$1" value="$2"
  if grep -q "^$key=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^$key=.*|$key=$value|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}
