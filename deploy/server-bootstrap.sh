#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/time-series-forecast-lab}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl tar docker.io
if ! docker compose version >/dev/null 2>&1; then
  apt-get install -y docker-compose
fi
systemctl enable --now docker

mkdir -p "$APP_DIR/backend/data" "$APP_DIR/backend/tmp/uploads" "$APP_DIR/backend/.model_cache"

cd "$APP_DIR"
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(docker-compose)
fi
"${COMPOSE[@]}" -f docker-compose.prod.yml up -d --build
"${COMPOSE[@]}" -f docker-compose.prod.yml ps
