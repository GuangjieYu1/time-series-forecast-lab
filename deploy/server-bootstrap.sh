#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/time-series-forecast-lab}"
DOCKER_REGISTRY_MIRRORS="${DOCKER_REGISTRY_MIRRORS:-https://docker.1panel.live,https://docker.m.daocloud.io,https://docker.1ms.run}"
DOCKER_DNS_SERVERS="${DOCKER_DNS_SERVERS:-223.5.5.5,223.6.6.6,1.1.1.1,8.8.8.8}"
BACKEND_PYTHON_BASE_IMAGE="${BACKEND_PYTHON_BASE_IMAGE:-python:3.12-slim}"
FRONTEND_NODE_BASE_IMAGE="${FRONTEND_NODE_BASE_IMAGE:-node:22-alpine}"
FRONTEND_NGINX_BASE_IMAGE="${FRONTEND_NGINX_BASE_IMAGE:-nginx:1.27-alpine}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl python3 tar docker.io
if ! docker compose version >/dev/null 2>&1; then
  apt-get install -y docker-compose
fi

mkdir -p /etc/docker
if [ -f /etc/docker/daemon.json ]; then
  cp /etc/docker/daemon.json "/etc/docker/daemon.json.bak.$(date +%Y%m%d%H%M%S)"
fi
export DOCKER_REGISTRY_MIRRORS DOCKER_DNS_SERVERS
python3 - <<'PY'
import json
import os
from pathlib import Path

daemon_path = Path("/etc/docker/daemon.json")
if daemon_path.exists():
    try:
        config = json.loads(daemon_path.read_text())
    except json.JSONDecodeError:
        config = {}
else:
    config = {}

mirrors = [item.strip() for item in os.environ["DOCKER_REGISTRY_MIRRORS"].split(",") if item.strip()]
dns_servers = [item.strip() for item in os.environ["DOCKER_DNS_SERVERS"].split(",") if item.strip()]

config["registry-mirrors"] = mirrors
config["dns"] = dns_servers

daemon_path.write_text(json.dumps(config, indent=2) + "\n")
PY
systemctl enable --now docker
systemctl restart docker

for image in \
  hello-world \
  "$BACKEND_PYTHON_BASE_IMAGE" \
  "$FRONTEND_NODE_BASE_IMAGE" \
  "$FRONTEND_NGINX_BASE_IMAGE"
do
  docker pull "$image" >/dev/null
done

mkdir -p "$APP_DIR/backend/data" "$APP_DIR/backend/tmp/uploads" "$APP_DIR/backend/.model_cache"

cd "$APP_DIR"
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(docker-compose)
fi
"${COMPOSE[@]}" -f docker-compose.prod.yml up -d --build
"${COMPOSE[@]}" -f docker-compose.prod.yml ps
