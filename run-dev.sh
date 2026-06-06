#!/usr/bin/env bash
set -euo pipefail
CONFIG=${LOCAL_ROUTER_CONFIG:-config/dev.yaml}
PROFILE=${LOCAL_ROUTER_PROFILE:-opencode}
if [ -n "${LOCAL_ROUTER_BIN:-}" ]; then
  :
elif [ -x .venv/bin/local-router ]; then
  LOCAL_ROUTER_BIN=.venv/bin/local-router
else
  LOCAL_ROUTER_BIN=local-router
fi

exec "$LOCAL_ROUTER_BIN" serve --config "$CONFIG" --profile "$PROFILE"
