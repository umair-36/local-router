from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..catalog import ModelCatalog
from ..config import RouterConfig, expand_path


def build_config(config: RouterConfig, catalog: ModelCatalog, provider_id: str = "local-router", model_id: str | None = None, api_key_file: str | None = None) -> dict[str, Any]:
    base = config.server.public_base_url or f"http://{config.server.host}:{config.server.port}/v1"
    models = catalog.list("opencode")
    selected = model_id or config.model.id
    model_map = {m.id: {"name": m.data.get("opencode", {}).get("display_name", m.name)} for m in models}
    provider: dict[str, Any] = {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Local Router",
        "options": {"baseURL": base},
        "models": model_map,
    }
    if api_key_file:
        provider["options"]["apiKey"] = "{file:" + str(Path(api_key_file).expanduser()) + "}"
    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {provider_id: provider},
        "model": f"{provider_id}/{selected}",
    }


def write_config(path: str | Path, data: dict[str, Any]) -> None:
    target = expand_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
