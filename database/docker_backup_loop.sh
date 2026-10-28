#!/usr/bin/env bash
set -euo pipefail

if [[ ! "${DB_NAME:-}" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "DB_NAME must contain only letters, numbers, and underscores." >&2
  exit 2
fi

mkdir -p /var/opt/mssql/backups
while true; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  file="${DB_NAME}_${stamp}.bak"
  echo "Starting SQL Server backup: ${file}"
  /opt/mssql-tools18/bin/sqlcmd \
    -S db -U sa -P "${MSSQL_SA_PASSWORD}" -C -b \
    -Q "BACKUP DATABASE [${DB_NAME}] TO DISK=N'/var/opt/mssql/backups/${file}' WITH INIT, COMPRESSION, CHECKSUM;"
  find /var/opt/mssql/backups -maxdepth 1 -type f -name "${DB_NAME}_*.bak" \
    -mtime "+${BACKUP_RETENTION_DAYS:-14}" -delete
  echo "Backup completed: /var/opt/mssql/backups/${file}"
  sleep "${BACKUP_INTERVAL_SECONDS:-86400}"
done
