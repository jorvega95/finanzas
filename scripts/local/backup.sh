#!/usr/bin/env bash
# GLO-08: respaldo diario con rotación (14 diarios + 12 mensuales). Un
# respaldo solo cuenta si pg_restore --list lo puede leer.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/monthly"
today=$(date +%F)
month=$(date +%Y-%m)
out="$BACKUP_DIR/daily/finanzas-$today.dump"
tmp="$out.partial"

pg_dump -h "$PG_SOCKET_DIR" -U "$DB_USER" -d "$DB_NAME" -Fc -f "$tmp"
pg_restore --list "$tmp" >/dev/null || { rm -f "$tmp"; fail "Respaldo ilegible: $tmp"; }
mv "$tmp" "$out"
[[ -f "$BACKUP_DIR/monthly/finanzas-$month.dump" ]] || cp "$out" "$BACKUP_DIR/monthly/finanzas-$month.dump"

# Rotación: los nombres llevan fecha ISO, así que el orden léxico es cronológico.
ls -1 "$BACKUP_DIR"/daily/finanzas-*.dump | head -n -14 | xargs -r rm -f
ls -1 "$BACKUP_DIR"/monthly/finanzas-*.dump | head -n -12 | xargs -r rm -f
info "Respaldo OK: $out ($(du -h "$out" | cut -f1))"
