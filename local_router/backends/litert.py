from __future__ import annotations

from typing import Any

from .base import Backend, BackendCapabilities, BackendOperationUnsupported, BackendUnavailableError


class LiteRTBackend(Backend):
    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name="litert",
            supports_chat_completions=False,
            supports_completions=False,
            supports_responses_native=False,
            supports_responses_translated=False,
            supports_streaming=False,
            supports_parallel_requests=False,
            supports_native_auth=False,
            requires_router_auth=True,
            opencode_supported=False,
            production_ready=False,
            limitations=[
                "LiteRT is kept as a selectable option but is a runtime, not an OpenAI-compatible HTTP server by itself.",
                "A custom LiteRT adapter must be implemented before this backend can serve OpenCode traffic.",
            ],
        )

    async def start(self) -> None:
        raise BackendUnavailableError("LiteRT is configured but no production LiteRT serving adapter is available")

    async def health(self) -> dict[str, Any]:
        return {"ok": False, "status_code": 501, "limitations": self.capabilities.limitations}

    async def chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise BackendOperationUnsupported("LiteRT cannot serve OpenAI-compatible chat until a serving adapter is configured")
