#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ "${1:-}" = "" ]; then
  echo "usage: ./setup_server.sh <weights-url> [model-id]" >&2
  exit 2
fi

WEIGHTS_URL="$1"
MODEL_ID="${2:-local-gguf}"
MODEL_FILE="model.gguf"
SUDO=""

if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

${SUDO} apt-get update
${SUDO} apt-get install -y python3 python3-venv python3-pip curl build-essential

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --upgrade "fastapi>=0.111" "uvicorn[standard]>=0.30" "llama-cpp-python>=0.2.90"

TMP_FILE="${MODEL_FILE}.download"
curl -L --fail --continue-at - --output "$TMP_FILE" "$WEIGHTS_URL"
mv "$TMP_FILE" "$MODEL_FILE"

cat > server.env <<EOF
MODEL_PATH=$(pwd)/${MODEL_FILE}
MODEL_ID=${MODEL_ID}
N_CTX=${N_CTX:-4096}
N_GPU_LAYERS=${N_GPU_LAYERS:--1}
HOST=127.0.0.1
PORT=${PORT:-8000}
EOF

echo "ready: $(pwd)/server.env"
