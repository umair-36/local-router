#!/usr/bin/env bash
set -euo pipefail
CONFIG=${LOCAL_ROUTER_CONFIG:-config/dev.yaml}
PROFILE=${LOCAL_ROUTER_PROFILE:-opencode}
exec local-router serve --config "$CONFIG" --profile "$PROFILE"
