#!/usr/bin/env bash
# Fase 4: compila el frontend, migra la base, instala el servicio systemd de
# usuario, los respaldos (GLO-08) y el lanzador de escritorio. Idempotente:
# vuelve a correrlo para actualizar después de cambiar código.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

command -v uv >/dev/null || fail "No se encontró uv"
command -v npm >/dev/null || fail "No se encontró npm"
pg_isready -h "$PG_SOCKET_DIR" -q || fail "Postgres no responde; corre scripts/local/setup-postgres.sh"

# --- Config del servicio (fuera del repo, nunca se commitea) ---------------
mkdir -p "$CONFIG_DIR"
if [[ ! -f "$ENV_FILE" ]]; then
  info "Creando $ENV_FILE"
  install -m 600 /dev/null "$ENV_FILE"
  env_set ENV dev
  env_set AUTH_MODE local
  # Instalación nueva: un UUID cualquiera. migrate-from-supabase.sh lo
  # reemplaza por el de tu perfil real.
  env_set LOCAL_USER_ID "$(cat /proc/sys/kernel/random/uuid)"
fi
env_set DATABASE_URL "postgresql+asyncpg://$DB_USER@/$DB_NAME?host=$PG_SOCKET_DIR"
env_set FRONTEND_DIST "$RAIZ/frontend/dist"
env_set SCHEDULER_ENABLED true

# --- Build ----------------------------------------------------------------
info "Instalando dependencias del backend..."
(cd "$RAIZ/backend" && uv sync --quiet)
info "Compilando frontend..."
# VITE_API_URL vacío: la SPA llama a /api en el mismo origen.
(cd "$RAIZ/frontend" && { [[ -d node_modules ]] || npm ci; } && VITE_API_URL= npm run build >/dev/null)

info "Aplicando migraciones..."
(cd "$RAIZ/backend" && set -a && source <(grep -E '^(DATABASE_URL|AUTH_MODE|LOCAL_USER_ID)=' "$ENV_FILE") && set +a && uv run alembic upgrade head)

# --- systemd --user ---------------------------------------------------------
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR" "$BACKUP_DIR"
for unit in finanzas.service finanzas-backup.service finanzas-backup.timer; do
  sed -e "s|@RAIZ@|$RAIZ|g" -e "s|@ENV_FILE@|$ENV_FILE|g" -e "s|@PORT@|$PORT|g" \
      -e "s|@BACKUP_DIR@|$BACKUP_DIR|g" \
      "$RAIZ/scripts/local/systemd/$unit" > "$UNIT_DIR/$unit"
done
systemctl --user daemon-reload
systemctl --user enable --now finanzas-backup.timer >/dev/null
systemctl --user enable finanzas.service >/dev/null
systemctl --user restart finanzas.service

# --- Lanzador de escritorio -------------------------------------------------
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" \
         "$HOME/.local/share/icons/hicolor/256x256/apps"
install -m 755 "$RAIZ/scripts/local/finanzas-open" "$HOME/.local/bin/finanzas-open"
install -m 644 "$RAIZ/frontend/public/finanzas-icon-256.png" \
  "$HOME/.local/share/icons/hicolor/256x256/apps/finanzas.png"
cat > "$HOME/.local/share/applications/Finanzas.desktop" <<DESKTOP
[Desktop Entry]
Version=1.0
Name=Finanzas
Comment=Finanzas personales (local)
Exec=$HOME/.local/bin/finanzas-open
Terminal=false
Type=Application
Icon=finanzas
StartupNotify=true
DESKTOP

for _ in $(seq 60); do curl -sf -o /dev/null "$APP_URL/health" && break; sleep 0.5; done
curl -sf -o /dev/null "$APP_URL/health" || fail "El servicio no respondió; revisa: journalctl --user -u finanzas -n 50"
info "Listo: $APP_URL (abre 'Finanzas' desde el lanzador)"
