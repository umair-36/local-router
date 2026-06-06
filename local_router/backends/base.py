from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from ..catalog import ModelEntry
from ..config import BackendConfig, ModelConfig


class BackendError(RuntimeError):
    """Base class for backend lifecycle and serving failures."""


class BackendUnavailableError(BackendError):
    """Raised when a configured backend cannot serve traffic."""


class BackendOperationUnsupported(BackendError):
    """Raised when a backend does not support a requested endpoint."""


@dataclass(frozen=True)
class BackendCapabilities:
    name: str
    supports_chat_completions: bool
    supports_completions: bool
    supports_responses_native: bool
    supports_responses_translated: bool
    supports_streaming: bool
    supports_parallel_requests: bool
    supports_native_auth: bool
    requires_router_auth: bool
    opencode_supported: bool
    production_ready: bool
    limitations: list[str] = field(default_factory=list)


class Backend(ABC):
    def __init__(self, config: BackendConfig, model_config: ModelConfig, model: ModelEntry):
        self.config = config
        self.model_config = model_config
        self.model = model

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities:
        raise BackendOperationUnsupported("backend capabilities are not defined")

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def preload(self) -> None:
        return None

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        raise BackendUnavailableError("backend health check is not defined")

    @abstractmethod
    async def chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise BackendOperationUnsupported(f"{self.capabilities.name} does not support chat completions")

    async def completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise BackendOperationUnsupported(f"{self.capabilities.name} does not support completions")

    async def responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.capabilities.supports_responses_translated:
            raise BackendOperationUnsupported(f"{self.capabilities.name} does not support responses")
        input_value = payload.get("input", "")
        messages = input_value if isinstance(input_value, list) else [{"role": "user", "content": str(input_value)}]
        chat = await self.chat_completions({"model": payload.get("model", self.model.id), "messages": messages, "stream": False})
        text = chat.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {
            "id": chat.get("id", "resp_local"),
            "object": "response",
            "created_at": chat.get("created", 0),
            "model": self.model.id,
            "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}],
            "usage": chat.get("usage"),
            "metadata": {"local_router_responses_translation": True},
        }

    async def stream_chat_completions(self, payload: dict[str, Any]) -> AsyncIterator[bytes]:
        raise BackendOperationUnsupported(f"{self.capabilities.name} does not support streaming")
