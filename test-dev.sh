#!/usr/bin/env bash
set -euo pipefail
BASE_CONFIG=${LOCAL_ROUTER_CONFIG:-config/dev.yaml}
WORK_DIR=${LOCAL_ROUTER_TEST_DIR:-.local-router-test}
CONFIG="$WORK_DIR/dev-smoke-config.yaml"
KEY_FILE=${LOCAL_ROUTER_TEST_KEY_FILE:-$WORK_DIR/opencode-key}
KEY_LABEL=${LOCAL_ROUTER_TEST_KEY_LABEL:-opencode-smoke}
MODEL=${LOCAL_ROUTER_TEST_MODEL:-qwen2.5-0.5b-instruct}
BASE_URL=${LOCAL_ROUTER_TEST_BASE_URL:-http://127.0.0.1:8080/v1}
SKIP_START=${LOCAL_ROUTER_TEST_SKIP_START:-0}

mkdir -p "$WORK_DIR" "$(dirname "$KEY_FILE")"
python -m pip install -e '.[dev]'
python - <<PY
from pathlib import Path
import yaml
base = Path('$BASE_CONFIG')
out = Path('$CONFIG')
data = yaml.safe_load(base.read_text())
data['auth']['key_store_path'] = str(Path('$WORK_DIR') / 'keys.json')
data['logging']['path'] = str(Path('$WORK_DIR') / 'usage.jsonl')
data['model']['id'] = '$MODEL'
data['paths']['catalog'] = 'models/catalog.yaml'
out.write_text(yaml.safe_dump(data, sort_keys=False))
PY

if command -v ollama >/dev/null 2>&1; then
  ollama pull qwen2.5:0.5b-instruct
else
  echo "WARN: ollama CLI not found; assuming an Ollama server already has qwen2.5:0.5b-instruct available." >&2
fi

if [ ! -s "$KEY_FILE" ]; then
  local-router keys add --config "$CONFIG" --label "$KEY_LABEL" --generate --write-secret-file "$KEY_FILE"
elif ! local-router keys list --config "$CONFIG" | grep -Fxq "$KEY_LABEL"; then
  local-router keys add --config "$CONFIG" --label "$KEY_LABEL" --secret-file "$KEY_FILE"
fi

if [ "$SKIP_START" = "1" ]; then
  python tests/smoke/openai_smoke.py --base-url "$BASE_URL" --model "$MODEL" --api-key-file "$KEY_FILE"
else
  local-router serve --config "$CONFIG" --profile opencode >"$WORK_DIR/router.log" 2>&1 &
  ROUTER_PID=$!
  trap 'kill "$ROUTER_PID" 2>/dev/null || true' EXIT
  python tests/smoke/openai_smoke.py --base-url "$BASE_URL" --model "$MODEL" --api-key-file "$KEY_FILE"
fi
