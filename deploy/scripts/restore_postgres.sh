#!/usr/bin/env bash
set -Eeuo pipefail

: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL deve apontar para banco vazio de homologacao}"
: "${BACKUP_FILE:?BACKUP_FILE deve apontar para um arquivo .dump confiavel}"

if [[ "${ALLOW_RESTORE:-}" != "YES" ]]; then
  echo 'Restore bloqueado. Configure ALLOW_RESTORE=YES somente após conferir o banco de destino.' >&2
  exit 2
fi

pg_restore --list "${BACKUP_FILE}" >/dev/null
pg_restore \
  --dbname="${RESTORE_DATABASE_URL}" \
  --no-owner \
  --no-privileges \
  --exit-on-error \
  --single-transaction \
  "${BACKUP_FILE}"
printf 'Restore concluido. Execute check, migrate --check e testes de integridade no destino.\n'
