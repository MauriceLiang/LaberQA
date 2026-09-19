#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="${ROOT_DIR}/backups"
STAMP="$(date +%Y%m%d_%H%M%S)"
TARGET="${BACKUP_ROOT}/${STAMP}"

mkdir -p "${TARGET}"

cd "${ROOT_DIR}"

docker compose stop backend

cleanup() {
  docker compose start backend >/dev/null 2>&1 || true
}

trap cleanup EXIT

tar -czf "${TARGET}/laborqa-runtime.tar.gz" \
  data \
  uploads

docker compose start backend

trap - EXIT

echo "Backup created: ${TARGET}/laborqa-runtime.tar.gz"
