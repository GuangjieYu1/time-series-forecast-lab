#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/time-series-forecast-lab}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl tar docker.io docker-compose-plugin
systemctl enable --now docker

mkdir -p "$APP_DIR/backend/data" "$APP_DIR/backend/tmp/uploads" "$APP_DIR/backend/.model_cache"

cd "$APP_DIR"
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
