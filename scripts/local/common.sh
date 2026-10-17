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

info() { printf '\033[1;34m[finanzas]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[finanzas] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# psql/pg_dump contra la base local por socket (auth peer, sin contraseña).
local_psql() { psql -h "$PG_SOCKET_DIR" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 "$@"; }

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
