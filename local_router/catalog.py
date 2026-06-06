from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import expand_path


@dataclass(frozen=True)
class ModelEntry:
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.data["id"])

    @property
    def name(self) -> str:
        return str(self.data.get("name", self.id))

    @property
    def memory_load_gb(self) -> float:
        return float(self.data.get("memory", {}).get("load_gb", 0.0))

    def backend_ref(self, backend: str) -> dict[str, Any] | None:
        value = self.data.get("backends", {}).get(backend)
        return value if isinstance(value, dict) else None

    def opencode_compatible(self) -> bool:
        return bool(self.data.get("opencode", {}).get("compatible", False))

    def openai_model(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "object": "model",
            "created": 0,
            "owned_by": "local-router",
            "metadata": {
                "name": self.name,
                "family": self.data.get("family"),
                "quantization": self.data.get("quantization"),
                "context_length": self.data.get("context_length"),
                "memory_load_gb": self.memory_load_gb,
                "opencode": self.data.get("opencode", {}),
            },
        }


class ModelCatalog:
    def __init__(self, models: list[ModelEntry]):
        self.models = models
        self._by_id = {m.id: m for m in models}

    @classmethod
    def load(cls, path: str | Path) -> "ModelCatalog":
        target = expand_path(path)
        with target.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls([ModelEntry(item) for item in data.get("models", [])])

    def get(self, model_id: str) -> ModelEntry:
        try:
            return self._by_id[model_id]
        except KeyError as exc:
            raise KeyError(f"unknown model id: {model_id}") from exc

    def list(self, for_client: str | None = None) -> list[ModelEntry]:
        if for_client == "opencode":
            return [m for m in self.models if m.opencode_compatible()]
        return list(self.models)
