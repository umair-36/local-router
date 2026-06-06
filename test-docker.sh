#!/usr/bin/env bash
set -euo pipefail
MODEL=${LOCAL_ROUTER_TEST_MODEL:-qwen2.5-0.5b-instruct}
BASE_URL=${LOCAL_ROUTER_TEST_BASE_URL:-http://127.0.0.1:8080/v1}
KEY_FILE=${LOCAL_ROUTER_TEST_KEY_FILE:-.local-router-test/docker-opencode-key}
KEY_LABEL=${LOCAL_ROUTER_TEST_KEY_LABEL:-opencode-docker-smoke}

mkdir -p "$(dirname "$KEY_FILE")"
docker compose build local-router
docker compose up -d ollama
docker compose run --rm ollama-pull-qwen

if [ ! -s "$KEY_FILE" ]; then
  SECRET=$(docker compose run --rm local-router keys add --label "$KEY_LABEL" --generate --print-secret | awk '/^lr_/ {print; exit}')
  if [ -z "$SECRET" ]; then
    echo "Failed to generate docker API key" >&2
    exit 1
  fi
  printf '%s\n' "$SECRET" > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
else
  docker compose run --rm -v "$PWD/$KEY_FILE:/tmp/local-router-key:ro" local-router keys remove --label "$KEY_LABEL" >/dev/null 2>&1 || true
  docker compose run --rm -v "$PWD/$KEY_FILE:/tmp/local-router-key:ro" local-router keys add --label "$KEY_LABEL" --secret-file /tmp/local-router-key
fi

docker compose up -d local-router
python tests/smoke/openai_smoke.py --base-url "$BASE_URL" --model "$MODEL" --api-key-file "$KEY_FILE"
