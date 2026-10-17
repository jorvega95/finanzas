#!/usr/bin/env bash
# Fase 1: instala Postgres nativo (Arch/Omarchy) y crea la base `finanzas`
# con un rol = tu usuario de Linux (auth peer por socket, sin contraseña).
# Requiere sudo. Idempotente.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if ! pacman -Q postgresql >/dev/null 2>&1; then
  info "Instalando postgresql..."
  sudo pacman -S --needed --noconfirm postgresql
fi

if ! sudo test -f /var/lib/postgres/data/PG_VERSION; then
  info "Inicializando cluster (initdb)..."
  sudo -u postgres initdb --locale=C.UTF-8 --encoding=UTF8 -D /var/lib/postgres/data
fi

# Solo socket local: nada escucha en la red (GLO-07).
CONF=/var/lib/postgres/data/postgresql.conf
if ! sudo grep -q "^listen_addresses = ''" "$CONF"; then
  echo "listen_addresses = ''" | sudo tee -a "$CONF" >/dev/null
fi

sudo systemctl enable --now postgresql
sudo systemctl restart postgresql
for _ in $(seq 30); do pg_isready -h "$PG_SOCKET_DIR" -q && break; sleep 0.5; done

if ! sudo -u postgres psql -Atc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
  info "Creando rol $DB_USER..."
  sudo -u postgres createuser "$DB_USER"
fi
if ! sudo -u postgres psql -Atc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
  info "Creando base $DB_NAME..."
  sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"
fi

local_psql -Atc "SELECT 'Conectado a ' || current_database() || ' como ' || current_user"
info "Postgres listo. Siguiente: scripts/local/install.sh"
