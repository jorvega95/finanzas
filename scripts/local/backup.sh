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

# FAC-10: los archivos subidos no viven en la BD. Se copian a un espejo sin
# --delete (cada archivo es inmutable y con nombre único): borrar uno en la app
# no lo borra del respaldo.
files_dir="$(env_get FILES_DIR)"
files_dir="${files_dir:-$FILES_DIR_DEFAULT}"
if [[ -d "$files_dir" ]]; then
  mkdir -p "$BACKUP_DIR/files"
  rsync -a "$files_dir/" "$BACKUP_DIR/files/"
  info "Archivos OK: $BACKUP_DIR/files ($(du -sh "$BACKUP_DIR/files" | cut -f1))"
fi
