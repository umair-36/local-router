#!/usr/bin/env bash
#
# router.sh - one entry point to set up and run local-router.
#
#   ./router.sh up         install deps, start the backend, serve the router
#   ./router.sh down        stop the router
#   ./router.sh restart     down then up
#   ./router.sh status      show whether the router is up and ready
#   ./router.sh logs        follow the router log
#   ./router.sh test        smoke-test the running router
#   ./router.sh key [...]   show / create / list API keys
#   ./router.sh opencode    write an OpenCode provider config
#   ./router.sh nginx       front the router with nginx on port 80
#
# Configuration is read from .env (created from .env.example on first run).

set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
RUN_DIR=".run"
ENV_FILE=".env"
ENV_TEMPLATE=".env.example"
PID_FILE="$RUN_DIR/router.pid"
LOG_FILE="$RUN_DIR/router.log"
OLLAMA_PID_FILE="$RUN_DIR/ollama.pid"
OLLAMA_LOG_FILE="$RUN_DIR/ollama.log"

log()  { printf '\033[1;36m[router]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[router]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[router]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'
}

load_env() {
  if [ ! -f "$ENV_FILE" ]; then
    cp "$ENV_TEMPLATE" "$ENV_FILE"
    log "created $ENV_FILE from $ENV_TEMPLATE"
  fi
  set -a
  # shellcheck disable=SC1090
  . "./$ENV_FILE"
  set +a

  : "${ROUTER_MODEL:=qwen2.5-0.5b-instruct}"
  : "${ROUTER_BACKEND:=ollama}"
  : "${ROUTER_HOST:=127.0.0.1}"
  : "${ROUTER_PORT:=8080}"
  : "${ROUTER_AUTH_MODE:=api_key_only}"
  : "${ROUTER_KEY_STORE:=$RUN_DIR/keys.json}"
  : "${OLLAMA_BASE_URL:=http://127.0.0.1:11434/v1}"
  : "${LLAMA_BASE_URL:=http://127.0.0.1:8081/v1}"

  KEY_FILE="${ROUTER_KEY_FILE:-$RUN_DIR/api-key}"
  KEY_LABEL="${ROUTER_KEY_LABEL:-opencode}"

  PROBE_HOST="$ROUTER_HOST"
  case "$ROUTER_HOST" in
    0.0.0.0 | :: | "") PROBE_HOST="127.0.0.1" ;;
  esac

  mkdir -p "$RUN_DIR"
}

router_url() { printf 'http://%s:%s/v1' "$PROBE_HOST" "$ROUTER_PORT"; }

router_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

# wait_for <url> <timeout-seconds> <label>; returns non-zero on timeout.
wait_for() {
  local url="$1" timeout="${2:-60}" label="${3:-endpoint}" waited=0
  while [ "$waited" -lt "$timeout" ]; do
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  warn "$label was not reachable at $url within ${timeout}s"
  return 1
}

ensure_venv() {
  if [ ! -x "$VENV/bin/python" ]; then
    log "creating virtualenv at $VENV"
    python3 -m venv "$VENV"
  fi
  if [ ! -x "$VENV/bin/local-router" ] || [ "${ROUTER_FORCE_INSTALL:-0}" = "1" ]; then
    log "installing local-router into $VENV"
    "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
    "$VENV/bin/python" -m pip install -e .
  fi
}

ensure_ollama() {
  local native="${OLLAMA_BASE_URL%/v1}"
  local sudo=""
  [ "$(id -u)" -eq 0 ] || sudo="sudo"

  if ! command -v ollama >/dev/null 2>&1; then
    if [ "${ROUTER_SKIP_OLLAMA_INSTALL:-0}" = "1" ]; then
      die "ollama is not installed (ROUTER_SKIP_OLLAMA_INSTALL=1); install it from https://ollama.com/download"
    fi
    log "installing ollama"
    curl -fsSL https://ollama.com/install.sh | $sudo sh
  fi

  if ! curl -fsS -o /dev/null "$native/api/tags" 2>/dev/null; then
    log "starting ollama server"
    nohup ollama serve >"$OLLAMA_LOG_FILE" 2>&1 &
    echo "$!" >"$OLLAMA_PID_FILE"
    wait_for "$native/api/tags" 60 "ollama server" || die "ollama did not start; see $OLLAMA_LOG_FILE"
  fi

  local tag="${OLLAMA_MODEL_TAG:-}"
  if [ -z "$tag" ]; then
    tag="$("$VENV/bin/python" -c "from local_router.catalog import ModelCatalog; print(ModelCatalog.load('models/catalog.yaml').get('$ROUTER_MODEL').backend_ref('ollama')['model'])")"
  fi
  log "pulling model $tag"
  ollama pull "$tag"
}

ensure_backend() {
  case "$ROUTER_BACKEND" in
    ollama)
      ensure_ollama
      ;;
    llama_cpp)
      local native="${LLAMA_BASE_URL%/v1}"
      if ! curl -fsS -o /dev/null "$native/health" 2>/dev/null; then
        die "llama.cpp endpoint $LLAMA_BASE_URL is not reachable. Start a llama-server with your GGUF (the minimal/ folder ships one) and set LLAMA_BASE_URL in .env."
      fi
      log "using llama.cpp endpoint $LLAMA_BASE_URL"
      ;;
    *)
      die "unsupported ROUTER_BACKEND '$ROUTER_BACKEND' (use ollama or llama_cpp)"
      ;;
  esac
}

ensure_key() {
  case "$ROUTER_AUTH_MODE" in
    disabled | ip_only)
      log "auth mode '$ROUTER_AUTH_MODE' needs no API key"
      return 0
      ;;
  esac

  local has_label="no"
  if "$VENV/bin/local-router" keys list 2>/dev/null | grep -Fxq "$KEY_LABEL"; then
    has_label="yes"
  fi

  if [ "$has_label" = "yes" ] && [ -s "$KEY_FILE" ]; then
    log "reusing API key '$KEY_LABEL' ($KEY_FILE)"
    return 0
  fi
  if [ "$has_label" = "no" ] && [ -s "$KEY_FILE" ]; then
    log "registering existing key file under label '$KEY_LABEL'"
    "$VENV/bin/local-router" keys add --label "$KEY_LABEL" --secret-file "$KEY_FILE"
    return 0
  fi
  log "generating API key '$KEY_LABEL'"
  "$VENV/bin/local-router" keys add --label "$KEY_LABEL" --generate --write-secret-file "$KEY_FILE"
}

start_router() {
  if router_running; then
    log "already up: $(router_url)"
    return 0
  fi
  log "starting router"
  (
    # shellcheck disable=SC1091
    . "$VENV/bin/activate"
    while true; do
      local-router serve >>"$LOG_FILE" 2>&1 || true
      sleep 2
    done
  ) >/dev/null 2>&1 &
  echo "$!" >"$PID_FILE"

  if ! wait_for "http://$PROBE_HOST:$ROUTER_PORT/readyz" "${ROUTER_READY_TIMEOUT:-180}" "router"; then
    warn "last router log lines:"
    tail -n 30 "$LOG_FILE" >&2 2>/dev/null || true
    cmd_down
    die "router failed to become ready"
  fi
}

print_summary() {
  log "router ready"
  echo
  printf '  URL:      %s\n' "$(router_url)"
  printf '  model:    %s (%s backend)\n' "$ROUTER_MODEL" "$ROUTER_BACKEND"
  if [ -s "$KEY_FILE" ]; then
    printf '  API key:  %s\n' "$(cat "$KEY_FILE")"
    printf '  key file: %s\n' "$KEY_FILE"
  else
    printf '  auth:     %s (no key required)\n' "$ROUTER_AUTH_MODE"
  fi
  echo
  echo "  test:     ./router.sh test"
  echo "  opencode: ./router.sh opencode"
  echo "  logs:     ./router.sh logs"
  echo "  stop:     ./router.sh down"
}

cmd_up() {
  ensure_venv
  ensure_backend
  ensure_key
  start_router
  print_summary
}

cmd_down() {
  if [ -f "$PID_FILE" ]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
  fi
  pkill -f "local-router serve" 2>/dev/null || true
  log "router stopped"
  if [ "${1:-}" = "--all" ] && [ -f "$OLLAMA_PID_FILE" ]; then
    kill "$(cat "$OLLAMA_PID_FILE")" 2>/dev/null || true
    rm -f "$OLLAMA_PID_FILE"
    log "router-managed ollama stopped"
  fi
}

cmd_status() {
  if router_running; then
    log "up (pid $(cat "$PID_FILE")): $(router_url)"
    if curl -fsS "http://$PROBE_HOST:$ROUTER_PORT/readyz" 2>/dev/null; then
      echo
    else
      warn "readiness probe did not return ok yet"
    fi
  else
    log "down"
  fi
}

cmd_logs() {
  [ -f "$LOG_FILE" ] || die "no log yet at $LOG_FILE; start the router with ./router.sh up"
  tail -n "${1:-120}" -f "$LOG_FILE"
}

cmd_test() {
  ensure_venv
  router_running || die "router is not running; start it with ./router.sh up"
  if [ -s "$KEY_FILE" ]; then
    "$VENV/bin/python" tests/smoke/openai_smoke.py --base-url "$(router_url)" --model "$ROUTER_MODEL" --api-key-file "$KEY_FILE"
  else
    "$VENV/bin/python" tests/smoke/openai_smoke.py --base-url "$(router_url)" --model "$ROUTER_MODEL"
  fi
}

cmd_key() {
  ensure_venv
  case "${1:-show}" in
    show)
      [ -s "$KEY_FILE" ] || die "no key yet; run ./router.sh up or ./router.sh key create"
      cat "$KEY_FILE"
      ;;
    create | add)
      ensure_key
      [ -s "$KEY_FILE" ] && cat "$KEY_FILE"
      ;;
    list)
      "$VENV/bin/local-router" keys list
      ;;
    *)
      die "usage: ./router.sh key [show|create|list]"
      ;;
  esac
}

cmd_opencode() {
  ensure_venv
  local out="${1:-opencode.local-router.json}"
  if [ -s "$KEY_FILE" ]; then
    "$VENV/bin/local-router" opencode config --output "$out" --api-key-file "$KEY_FILE"
  else
    "$VENV/bin/local-router" opencode config --output "$out"
  fi
  log "wrote $out (point OpenCode at it with: opencode --config $out)"
}

cmd_nginx() {
  local sudo=""
  [ "$(id -u)" -eq 0 ] || sudo="sudo"
  local upstream="http://127.0.0.1:$ROUTER_PORT"
  local conf="/etc/nginx/sites-available/default"

  if ! command -v nginx >/dev/null 2>&1; then
    log "installing nginx"
    $sudo apt-get update
    $sudo apt-get install -y nginx
  fi

  $sudo tee "$conf" >/dev/null <<NGINX
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass $upstream;
        proxy_http_version 1.1;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        proxy_read_timeout 300s;
        proxy_buffering off;
    }
}
NGINX

  $sudo ln -sfn "$conf" /etc/nginx/sites-enabled/default
  $sudo nginx -t
  $sudo systemctl enable nginx >/dev/null 2>&1 || true
  $sudo systemctl reload nginx || $sudo systemctl restart nginx
  log "nginx now proxies http://<public-ip>/ -> $upstream (keep ROUTER_AUTH_MODE=api_key_only)"
}

main() {
  local cmd="${1:-up}"
  [ "$#" -gt 0 ] && shift || true

  case "$cmd" in
    help | -h | --help)
      usage
      return 0
      ;;
  esac

  load_env

  case "$cmd" in
    up | start)    cmd_up "$@" ;;
    down | stop)   cmd_down "$@" ;;
    restart)       cmd_down; cmd_up "$@" ;;
    status)        cmd_status "$@" ;;
    logs)          cmd_logs "$@" ;;
    test)          cmd_test "$@" ;;
    key | keys)    cmd_key "$@" ;;
    opencode)      cmd_opencode "$@" ;;
    nginx)         cmd_nginx "$@" ;;
    setup)         ensure_venv; ensure_backend; ensure_key; log "setup complete; run ./router.sh up to serve" ;;
    *)             usage; die "unknown command: $cmd" ;;
  esac
}

main "$@"
