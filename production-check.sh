#!/usr/bin/env bash
set -euo pipefail
VENV=${LOCAL_ROUTER_VENV:-.venv}
PYTHON=${PYTHON:-python3}

if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install -e '.[dev]'
"$VENV/bin/python" -m pytest -q
"$VENV/bin/local-router" config validate --config config/dev.yaml --profile opencode
"$VENV/bin/local-router" config validate --config config/config.docker.yaml --profile opencode
bash -n router.sh test-docker.sh production-check.sh
"$VENV/bin/python" -m compileall local_router tests/smoke

"$VENV/bin/python" - <<'PY'
from pathlib import Path

blocked = [
    "mo" + "ck",
    "place" + "holder",
    "ex" + "ample",
    "TO" + "DO",
    "FIX" + "ME",
    "not " + "implemented",
    "Not" + "Implemented",
    "half" + "-done",
]
allowed_paths = {Path("LICENSE"), Path(".env")}
violations: list[str] = []
for path in Path(".").rglob("*"):
    if not path.is_file():
        continue
    if ".git" in path.parts or ".venv" in path.parts or ".run" in path.parts or "minimal" in path.parts or ".local-router-test" in path.parts or "__pycache__" in path.parts or path in allowed_paths:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore").replace(".env.example", "")
    for term in blocked:
        if term in text:
            violations.append(f"{path}: contains blocked production-check term {term!r}")
if violations:
    raise SystemExit("\n".join(violations))
PY

if command -v docker >/dev/null 2>&1; then
  docker compose config >/dev/null
else
  echo "WARN: docker not installed; skipping docker compose config validation" >&2
fi
