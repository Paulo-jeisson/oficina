#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

: "${DATABASE_URL:?DATABASE_URL deve apontar para o PostgreSQL}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/oficina}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="${BACKUP_DIR}/oficina_${STAMP}.dump"

mkdir -p "${BACKUP_DIR}"
pg_dump --dbname="${DATABASE_URL}" --format=custom --compress=9 --no-owner --file="${TARGET}"
pg_restore --list "${TARGET}" >/dev/null
find "${BACKUP_DIR}" -type f -name 'oficina_*.dump' -mtime "+${RETENTION_DAYS}" -delete
printf 'Backup criado e validado: %s\n' "${TARGET}"
