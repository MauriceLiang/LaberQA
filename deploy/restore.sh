#!/usr/bin/env bash

set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <backup.tar.gz>"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_FILE="$(realpath "$1")"
STAMP="$(date +%Y%m%d_%H%M%S)"

cd "${ROOT_DIR}"

docker compose down

mkdir -p "backups/pre-restore-${STAMP}"

if [ -d data ] || [ -d uploads ]; then
  tar -czf \
    "backups/pre-restore-${STAMP}/current-runtime.tar.gz" \
    data \
    uploads
fi

rm -rf data uploads

tar -xzf "${BACKUP_FILE}" -C "${ROOT_DIR}"

docker compose up -d

docker compose ps
