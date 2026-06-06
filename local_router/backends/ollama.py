from __future__ import annotations

from typing import Any, AsyncIterator

import httpx

from .base import Backend, BackendCapabilities, BackendUnavailableError


class OllamaBackend(Backend):
    @property
    def base_url(self) -> str:
        return (self.config.base_url or "http://127.0.0.1:11434/v1").rstrip("/")

    @property
    def native_base_url(self) -> str:
        return self.base_url.removesuffix("/v1")

    @property
    def backend_model(self) -> str:
        ref = self.model.backend_ref("ollama") or {}
        return str(ref.get("model", self.model.id))

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name="ollama",
            supports_chat_completions=True,
            supports_completions=True,
            supports_responses_native=False,
            supports_responses_translated=True,
            supports_streaming=True,
            supports_parallel_requests=True,
            supports_native_auth=False,
            requires_router_auth=True,
            opencode_supported=True,
            production_ready=True,
            limitations=[
                "Ollama's OpenAI-compatible API does not enforce the client-provided API key; keep router auth enabled.",
                "Parallel requests increase context/KV memory pressure.",
            ],
        )

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.native_base_url}/api/tags")
            return {"ok": response.status_code == 200, "status_code": response.status_code}

    async def preload(self) -> None:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(f"{self.native_base_url}/api/generate", json={"model": self.backend_model, "prompt": "", "keep_alive": self.model_config.keep_alive})
            response.raise_for_status()

    def _payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload)
        out["model"] = self.backend_model
        return out

    async def chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=self._payload(payload))
            response.raise_for_status()
            data = response.json()
            data["model"] = self.model.id
            return data

    async def completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(f"{self.base_url}/completions", json=self._payload(payload))
            response.raise_for_status()
            data = response.json()
            data["model"] = self.model.id
            return data

    async def stream_chat_completions(self, payload: dict[str, Any]) -> AsyncIterator[bytes]:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", json=self._payload(payload)) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk
