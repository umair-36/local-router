#!/usr/bin/env bash
set -euo pipefail

python -m pip install -e '.[dev]'
python -m pytest -q
local-router config validate --config config/dev.yaml --profile opencode
local-router config validate --config config/config.docker.yaml --profile opencode
bash -n install-dev.sh run-dev.sh test-dev.sh test-docker.sh production-check.sh
python -m compileall local_router tests/smoke

python - <<'PY'
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
allowed_paths = {Path("LICENSE")}
violations: list[str] = []
for path in Path(".").rglob("*"):
    if not path.is_file():
        continue
    if ".git" in path.parts or "__pycache__" in path.parts or path in allowed_paths:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
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
