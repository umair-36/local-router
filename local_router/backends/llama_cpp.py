from __future__ import annotations

from typing import Any, AsyncIterator

import httpx

from .base import Backend, BackendCapabilities, BackendUnavailableError


class LlamaCppBackend(Backend):
    @property
    def base_url(self) -> str:
        return (self.config.base_url or "http://127.0.0.1:8081/v1").rstrip("/")

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name="llama_cpp",
            supports_chat_completions=True,
            supports_completions=True,
            supports_responses_native=True,
            supports_responses_translated=False,
            supports_streaming=True,
            supports_parallel_requests=True,
            supports_native_auth=True,
            requires_router_auth=True,
            opencode_supported=True,
            production_ready=True,
            limitations=[
                "OpenAI compatibility depends on llama-server version, chat template, and GGUF metadata.",
                "Configure --ctx-size and --parallel high enough for OpenCode workflows.",
            ],
        )

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url.removesuffix('/v1')}/health")
            return {"ok": response.status_code == 200, "status_code": response.status_code}

    def _payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload)
        out["model"] = self.model.id
        return out

    async def chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=self._payload(payload))
            response.raise_for_status()
            return response.json()

    async def completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(f"{self.base_url}/completions", json=self._payload(payload))
            response.raise_for_status()
            return response.json()

    async def responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(f"{self.base_url}/responses", json=self._payload(payload))
            response.raise_for_status()
            return response.json()

    async def stream_chat_completions(self, payload: dict[str, Any]) -> AsyncIterator[bytes]:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", json=self._payload(payload)) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk
