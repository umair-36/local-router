from __future__ import annotations

from ..catalog import ModelEntry
from ..config import BackendConfig, ModelConfig
from .base import Backend
from .litert import LiteRTBackend
from .llama_cpp import LlamaCppBackend
from .ollama import OllamaBackend


def create_backend(config: BackendConfig, model_config: ModelConfig, model: ModelEntry) -> Backend:
    if config.provider == "ollama":
        return OllamaBackend(config, model_config, model)
    if config.provider == "llama_cpp":
        return LlamaCppBackend(config, model_config, model)
    if config.provider == "litert":
        return LiteRTBackend(config, model_config, model)
    raise ValueError(f"unsupported backend: {config.provider}")
