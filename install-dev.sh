#!/usr/bin/env bash
set -euo pipefail
VENV=${LOCAL_ROUTER_VENV:-.venv}
PYTHON=${PYTHON:-python3}

if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install -e '.[dev]'
