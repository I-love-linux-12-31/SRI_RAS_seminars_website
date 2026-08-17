#!/bin/sh
# Резервная копия базы и загруженных файлов.
# Запускается systemd-таймером; путь назначения задаётся BACKUP_DIR.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/var/backups/iki-seminar}"
KEEP_DAYS="${KEEP_DAYS:-30}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"

# custom-формат (-Fc) вместо plain SQL: сжат и позволяет частичное
# восстановление через pg_restore.
pg_dump --format=custom --file="$BACKUP_DIR/db-$STAMP.dump" "$DATABASE_URL"

if [ -d "${MEDIA_ROOT:-/opt/iki-seminar/media}" ]; then
  tar -czf "$BACKUP_DIR/media-$STAMP.tar.gz" -C "$(dirname "${MEDIA_ROOT:-/opt/iki-seminar/media}")" \
    "$(basename "${MEDIA_ROOT:-/opt/iki-seminar/media}")"
fi

find "$BACKUP_DIR" -type f -mtime "+$KEEP_DAYS" -delete

echo "Копия готова: $BACKUP_DIR/db-$STAMP.dump"
echo "ПРОВЕРЬТЕ ВОССТАНОВЛЕНИЕ: pg_restore -d <пустая_база> $BACKUP_DIR/db-$STAMP.dump"
