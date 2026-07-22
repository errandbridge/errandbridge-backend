#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
SERVICES=(db api ml prometheus grafana)
GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-}"

load_local_env_defaults() {
  local env_file="$PROJECT_DIR/.env"
  local raw_line=""

  if [[ -f "$env_file" ]]; then
    if [[ -z "$GRAFANA_ADMIN_USER" ]]; then
      raw_line="$(grep -E '^GRAFANA_ADMIN_USER=' "$env_file" | tail -1 || true)"
      if [[ -n "$raw_line" ]]; then
        GRAFANA_ADMIN_USER="${raw_line#GRAFANA_ADMIN_USER=}"
      fi
    fi

    if [[ -z "$GRAFANA_ADMIN_PASSWORD" ]]; then
      raw_line="$(grep -E '^GRAFANA_ADMIN_PASSWORD=' "$env_file" | tail -1 || true)"
      if [[ -n "$raw_line" ]]; then
        GRAFANA_ADMIN_PASSWORD="${raw_line#GRAFANA_ADMIN_PASSWORD=}"
      fi
    fi
  fi

  : "${GRAFANA_ADMIN_USER:=admin}"
  : "${GRAFANA_ADMIN_PASSWORD:=admin}"
}

detect_lan_ip() {
  local iface=""
  local ip=""

  iface="$(route get default 2>/dev/null | awk '/interface:/{print $2; exit}')"
  if [[ -n "$iface" ]] && command -v ipconfig >/dev/null 2>&1; then
    ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
  fi

  if [[ -z "$ip" ]] && command -v hostname >/dev/null 2>&1; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  fi

  printf '%s' "$ip"
}

compose() {
  cd "$PROJECT_DIR"
  docker compose "$@"
}

grafana_volume_name() {
  docker volume ls -q \
    --filter "label=com.docker.compose.project=$PROJECT_NAME" \
    --filter "label=com.docker.compose.volume=grafana_data" \
    | head -n 1
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-40}"
  local delay_seconds="${4:-2}"
  local attempt

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "✓ $name ready: $url"
      return 0
    fi
    sleep "$delay_seconds"
  done

  echo "✗ Timed out waiting for $name at $url" >&2
  return 1
}

reset_grafana_admin_password() {
  echo "Resetting Grafana admin password for local dev..."
  compose exec -T grafana grafana cli admin reset-admin-password "$GRAFANA_ADMIN_PASSWORD" >/dev/null
  echo "✓ Grafana admin password reset for user '$GRAFANA_ADMIN_USER'"
}

reset_grafana_volume() {
  local volume_name=""

  echo "Recreating Grafana data volume for local dev..."
  compose stop grafana >/dev/null
  compose rm -sf grafana >/dev/null

  volume_name="$(grafana_volume_name)"
  if [[ -n "$volume_name" ]]; then
    docker volume rm "$volume_name" >/dev/null
    echo "✓ Removed volume '$volume_name'"
  else
    echo "ℹ No existing Grafana data volume found for project '$PROJECT_NAME'"
  fi

  start_stack
}

print_urls() {
  local lan_ip="${1:-}"

  cat <<EOF

Local service URLs:
- API:         http://localhost:8001/
- Docs:        http://localhost:8001/docs
- GraphQL:     http://localhost:8001/graphql
- Metrics:     http://localhost:8001/metrics
- ML health:   http://localhost:8011/health
- Prometheus:  http://localhost:9090
- Grafana:     http://localhost:3001

EOF

  if [[ -n "$lan_ip" ]]; then
    cat <<EOF
- API (LAN):   http://$lan_ip:8001/
- Prometheus:  http://$lan_ip:9090
- Grafana:     http://$lan_ip:3001

Note: on Docker Desktop for macOS, this same Mac may not reliably curl its own
LAN URL. Use the LAN URL from another device on your network.
EOF
  fi

  cat <<EOF

Grafana defaults:
- Username: $GRAFANA_ADMIN_USER
- Password: $GRAFANA_ADMIN_PASSWORD

If you change GRAFANA_ADMIN_USER on an existing local Grafana volume, the new
username will only take effect after recreating the grafana_data volume.
EOF
}

usage() {
  cat <<EOF
Usage: ./scripts/dev_stack.sh [start|status|logs|stop|restart]

Commands:
  start    Start db, api, ml, prometheus, grafana and wait for them
  status   Show compose status for the local dev stack
  logs     Tail logs for the local dev stack
  reset-grafana-admin  Reset Grafana admin password to the local dev default
  reset-grafana-volume Recreate only Grafana data so a new admin username applies
  stop     Stop the local dev stack services
  restart  Restart the local dev stack services and re-run readiness checks
EOF
}

start_stack() {
  local lan_ip=""

  echo "Starting local ErrandBridge backend stack..."
  compose up -d "${SERVICES[@]}"

  echo "Waiting for services to become ready..."
  wait_for_http "API" "http://127.0.0.1:8001/health"
  wait_for_http "ML" "http://127.0.0.1:8011/health"
  wait_for_http "Prometheus" "http://127.0.0.1:9090/-/ready"
  wait_for_http "Grafana" "http://127.0.0.1:3001/login"
  reset_grafana_admin_password

  lan_ip="$(detect_lan_ip)"

  echo
  compose ps "${SERVICES[@]}"
  print_urls "$lan_ip"
}

load_local_env_defaults

ACTION="${1:-start}"

case "$ACTION" in
  start)
    start_stack
    ;;
  status)
    compose ps "${SERVICES[@]}"
    ;;
  logs)
    compose logs -f "${SERVICES[@]}"
    ;;
  reset-grafana-admin)
    reset_grafana_admin_password
    ;;
  reset-grafana-volume)
    reset_grafana_volume
    ;;
  stop)
    compose stop "${SERVICES[@]}"
    ;;
  restart)
    compose stop "${SERVICES[@]}"
    start_stack
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
