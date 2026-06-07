from __future__ import annotations

import asyncio
import os
from typing import Any, AsyncIterator
from urllib.parse import urlsplit

import httpx

from .base import Backend, BackendCapabilities, BackendUnavailableError


class LlamaCppBackend(Backend):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._process: asyncio.subprocess.Process | None = None

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
                "Managed GPU offload requires a llama.cpp build with a supported GPU backend.",
            ],
        )

    def managed_command(self) -> list[str]:
        executable = self.config.executable or "llama-server"
        if not self.config.model_path:
            raise BackendUnavailableError("backend.model_path is required when backend.manage_process is enabled")
        parsed = urlsplit(self.base_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        command = [
            executable,
            "--model",
            self.config.model_path,
            "--host",
            host,
            "--port",
            str(port),
            "--ctx-size",
            str(self.model_config.context_length),
        ]
        if self.config.gpu.enabled:
            command.extend(["--n-gpu-layers", str(self.config.gpu.layers)])
        command.extend(self.config.extra_args)
        return command

    async def start(self) -> None:
        if not self.config.manage_process:
            return None
        if self._process and self._process.returncode is None:
            return None
        env = os.environ.copy()
        env.update(self.config.env)
        command = self.managed_command()
        try:
            self._process = await asyncio.create_subprocess_exec(*command, env=env)
            await self._wait_until_ready()
        except FileNotFoundError as exc:
            raise BackendUnavailableError(f"llama.cpp executable not found: {command[0]}") from exc
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        if self._process is None:
            return None
        process = self._process
        self._process = None
        if process.returncode is not None:
            return None
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def _wait_until_ready(self) -> None:
        timeout = max(self.config.startup_timeout_seconds, 0)
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if self._process and self._process.returncode is not None:
                raise BackendUnavailableError(f"managed llama-server exited with code {self._process.returncode}")
            health = await self.health()
            if health.get("ok"):
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise BackendUnavailableError(f"managed llama-server was not ready within {timeout:g} seconds: {health}")
            await asyncio.sleep(0.5)

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url.removesuffix('/v1')}/health")
                return {"ok": response.status_code == 200, "status_code": response.status_code}
        except httpx.HTTPError as exc:
            return {"ok": False, "error": str(exc)}

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
