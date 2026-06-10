#!/usr/bin/env bash
#
# router.sh - one entry point to set up and run local-router.
#
#   ./router.sh up         install, start the backend, serve, write OpenCode config
#   ./router.sh down        stop the router
#   ./router.sh restart     down then up
#   ./router.sh status      show whether the router is up and ready
#   ./router.sh logs        follow the router log
#   ./router.sh test        smoke-test the running router
#   ./router.sh curl        send a sample chat request to the running router
#   ./router.sh key [...]   show / create / list API keys
#   ./router.sh opencode    write the OpenCode provider config
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
  sed -n '/^# router\.sh - /,/^# Configuration is read/p' "$0" | sed 's/^# \{0,1\}//'
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
  : "${OPENCODE_CONFIG:=opencode.local-router.json}"

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
    if ! python3 -m venv "$VENV"; then
      die "could not create a virtualenv at $VENV. On Debian/Ubuntu install the venv package first: sudo apt-get install python3-venv"
    fi
  fi
  # A venv created without ensurepip (the usual symptom of a missing
  # python3-venv on Debian/Ubuntu) has no pip, which later surfaces as a
  # cryptic "No module named pip". Detect it here and give a fixable message.
  if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    log "bootstrapping pip in $VENV"
    if ! "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1; then
      die "the virtualenv at $VENV has no pip and ensurepip is unavailable. Install your Python's venv package (Debian/Ubuntu: sudo apt-get install python3-venv), remove $VENV, then retry."
    fi
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
    if [ -n "$sudo" ] && ! $sudo -n true 2>/dev/null; then
      die "ollama is not installed and its installer needs root, but passwordless sudo is unavailable. Install ollama manually from https://ollama.com/download (or run this once with sudo), then retry. Once ollama is on PATH you can also set ROUTER_SKIP_OLLAMA_INSTALL=1."
    fi
    log "installing ollama"
    if ! curl -fsSL https://ollama.com/install.sh | $sudo sh; then
      die "automatic ollama install failed. Install it manually from https://ollama.com/download, then retry (set ROUTER_SKIP_OLLAMA_INSTALL=1 once ollama is on PATH)."
    fi
    command -v ollama >/dev/null 2>&1 || die "ollama still not found after install; install it manually from https://ollama.com/download and retry."
  fi

  if ! curl -fsS -o /dev/null "$native/api/tags" 2>/dev/null; then
    log "starting ollama server"
    nohup ollama serve >"$OLLAMA_LOG_FILE" 2>&1 &
    echo "$!" >"$OLLAMA_PID_FILE"
    wait_for "$native/api/tags" 60 "ollama server" || die "ollama did not start; see $OLLAMA_LOG_FILE"
  fi

  local tag="${OLLAMA_MODEL_TAG:-}"
  if [ -z "$tag" ]; then
    # Resolve the ollama tag from the catalog. Report a clear, actionable error
    # (instead of a raw Python traceback) when ROUTER_MODEL is unknown or has no
    # ollama backend - the usual symptom of pointing ROUTER_BACKEND=ollama at a
    # llama.cpp-only model such as gemma-4-12b-qat.
    if ! tag="$("$VENV/bin/python" - "$ROUTER_MODEL" <<'PY' 2>&1
import sys

from local_router.catalog import ModelCatalog

model_id = sys.argv[1]
try:
    entry = ModelCatalog.load("models/catalog.yaml").get(model_id)
except KeyError:
    sys.exit(f"unknown ROUTER_MODEL '{model_id}': it is not listed in models/catalog.yaml")

ref = entry.backend_ref("ollama")
if not ref or not ref.get("model"):
    backends = ", ".join((entry.data.get("backends") or {}).keys()) or "none"
    sys.exit(
        f"ROUTER_MODEL '{model_id}' has no ollama backend (catalog backends: {backends}). "
        f"Set ROUTER_BACKEND in .env to one of those, or set OLLAMA_MODEL_TAG to a tag to pull directly."
    )
print(ref["model"])
PY
)"; then
      die "$tag"
    fi
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
  printf '  URL:       %s\n' "$(router_url)"
  printf '  model:     %s (%s backend)\n' "$ROUTER_MODEL" "$ROUTER_BACKEND"
  if [ -s "$KEY_FILE" ]; then
    printf '  API key:   %s\n' "$(cat "$KEY_FILE")"
    printf '  key file:  %s\n' "$KEY_FILE"
  else
    printf '  auth:      %s (no key required)\n' "$ROUTER_AUTH_MODE"
  fi
  [ -s "$OPENCODE_CONFIG" ] && printf '  opencode:  %s\n' "$OPENCODE_CONFIG"
  echo
  echo "  call the API:    ./router.sh curl"
  echo "  use in OpenCode: opencode --config $OPENCODE_CONFIG"
  echo "  smoke test:      ./router.sh test"
  echo "  logs / stop:     ./router.sh logs   |   ./router.sh down"
}

write_opencode() {
  if [ -s "$KEY_FILE" ]; then
    "$VENV/bin/local-router" opencode config --output "$OPENCODE_CONFIG" --api-key-file "$KEY_FILE" >/dev/null
  else
    "$VENV/bin/local-router" opencode config --output "$OPENCODE_CONFIG" >/dev/null
  fi
}

cmd_up() {
  ensure_venv
  ensure_backend
  ensure_key
  start_router
  write_opencode
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

# Show the OpenAI-compatible request shape, then run it against the live router.
cmd_curl() {
  router_running || die "router is not running; start it with ./router.sh up"
  local url data
  url="$(router_url)/chat/completions"
  data='{"model":"'"$ROUTER_MODEL"'","messages":[{"role":"user","content":"Say hello in five words."}],"max_tokens":64}'

  log "POST $url"
  echo "  curl -s $url \\"
  if [ -s "$KEY_FILE" ]; then
    echo "    -H \"Authorization: Bearer \$(cat $KEY_FILE)\" \\"
  fi
  echo "    -H 'Content-Type: application/json' \\"
  echo "    -d '$data'"
  echo
  if [ -s "$KEY_FILE" ]; then
    curl -s "$url" -H "Authorization: Bearer $(cat "$KEY_FILE")" -H "Content-Type: application/json" -d "$data"
  else
    curl -s "$url" -H "Content-Type: application/json" -d "$data"
  fi
  echo
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
  OPENCODE_CONFIG="${1:-$OPENCODE_CONFIG}"
  write_opencode
  log "wrote $OPENCODE_CONFIG"
  echo "  launch: opencode --config $OPENCODE_CONFIG"
  echo "  model:  local-router/$ROUTER_MODEL"
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
    curl | api)    cmd_curl "$@" ;;
    key | keys)    cmd_key "$@" ;;
    opencode)      cmd_opencode "$@" ;;
    nginx)         cmd_nginx "$@" ;;
    setup)         ensure_venv; ensure_backend; ensure_key; log "setup complete; run ./router.sh up to serve" ;;
    *)             usage; die "unknown command: $cmd" ;;
  esac
}

main "$@"
