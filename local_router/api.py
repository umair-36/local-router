from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .auth import AuthMiddleware
from .backends import create_backend
from .backends.base import BackendError, BackendOperationUnsupported, BackendUnavailableError
from .catalog import ModelCatalog
from .config import LoggingMode, RouterConfig
from .logging import ComplianceLogger, LoggingMiddleware
from .scheduler import RequestScheduler, SchedulerFull


def error_response(status: int, message: str, typ: str = "server_error", code: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"message": message, "type": typ, "code": code or typ}})


def create_app(config: RouterConfig) -> FastAPI:
    catalog = ModelCatalog.load(config.paths.catalog)
    model = catalog.get(config.model.id)
    backend = create_backend(config.backend, config.model, model)
    scheduler = RequestScheduler(config.scheduler.max_in_flight, config.scheduler.max_queue, config.scheduler.queue_timeout_seconds)
    compliance = ComplianceLogger(config.logging)
    ready: dict[str, Any] = {"ok": False, "backend_health": None}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await backend.start()
        if not backend.capabilities.production_ready:
            raise BackendUnavailableError(f"backend {backend.capabilities.name} is not production-ready for serving")
        if config.model.preload:
            await backend.preload()
        health = await backend.health()
        ready["backend_health"] = health
        if not health.get("ok"):
            raise BackendUnavailableError(f"backend {backend.capabilities.name} failed readiness health check: {health}")
        ready["ok"] = True
        compliance.emit({"event": "router_ready", "backend": backend.capabilities.name, "model": model.id, "backend_health": health})
        try:
            yield
        finally:
            ready["ok"] = False
            await backend.stop()

    app = FastAPI(title="local-router", version="0.1.0", lifespan=lifespan)
    app.add_middleware(AuthMiddleware, config=config.auth)
    app.add_middleware(LoggingMiddleware, logger=compliance)
    app.state.config = config
    app.state.catalog = catalog
    app.state.backend = backend

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "service": "local-router"}

    @app.get("/readyz", response_model=None)
    async def readyz() -> JSONResponse | dict[str, Any]:
        if not ready["ok"]:
            return error_response(503, "router is not ready", "service_unavailable")
        return {"ok": True, "backend": backend.capabilities.name, "model": model.id, "backend_health": ready["backend_health"]}

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {"object": "list", "data": [m.openai_model() for m in catalog.list()]}

    @app.get("/v1/models/{model_id}", response_model=None)
    async def model_detail(model_id: str) -> JSONResponse | dict[str, Any]:
        try:
            return catalog.get(model_id).openai_model()
        except KeyError:
            return error_response(404, f"model not found: {model_id}", "invalid_request_error", "model_not_found")

    @app.post("/v1/chat/completions", response_model=None)
    async def chat_completions(request: Request) -> JSONResponse | StreamingResponse | dict[str, Any]:
        payload = await request.json()
        payload["model"] = model.id
        if payload.get("stream"):
            if not backend.capabilities.supports_streaming:
                return error_response(400, "streaming is not supported by selected backend", "invalid_request_error")
            try:
                ticket = await scheduler.acquire()
            except SchedulerFull as exc:
                return error_response(429, str(exc), "server_overloaded")
            compliance.emit(_generation_event("stream_start", request, config.logging.mode, payload, None, model.id, backend.capabilities.name, ticket.wait_ms))

            async def guarded_stream():
                try:
                    async for chunk in backend.stream_chat_completions(payload):
                        yield chunk
                    compliance.emit({"event": "stream_end", "request_id": request.state.request_id, "model": model.id, "backend": backend.capabilities.name})
                finally:
                    scheduler.release()

            return StreamingResponse(guarded_stream(), media_type="text/event-stream")
        try:
            async with scheduler.slot() as ticket:
                compliance.emit(_generation_event("generation_start", request, config.logging.mode, payload, None, model.id, backend.capabilities.name, ticket.wait_ms))
                response = await backend.chat_completions(payload)
                compliance.emit(_generation_event("generation_end", request, config.logging.mode, payload, response, model.id, backend.capabilities.name, ticket.wait_ms, response.get("usage")))
                return response
        except SchedulerFull as exc:
            return error_response(429, str(exc), "server_overloaded")
        except BackendOperationUnsupported as exc:
            return error_response(501, str(exc), "not_implemented")
        except BackendError as exc:
            return error_response(502, str(exc), "backend_error")

    @app.post("/v1/completions", response_model=None)
    async def completions(request: Request) -> JSONResponse | dict[str, Any]:
        payload = await request.json()
        payload["model"] = model.id
        try:
            async with scheduler.slot() as ticket:
                compliance.emit(_generation_event("generation_start", request, config.logging.mode, payload, None, model.id, backend.capabilities.name, ticket.wait_ms))
                response = await backend.completions(payload)
                compliance.emit(_generation_event("generation_end", request, config.logging.mode, payload, response, model.id, backend.capabilities.name, ticket.wait_ms, response.get("usage")))
                return response
        except SchedulerFull as exc:
            return error_response(429, str(exc), "server_overloaded")
        except BackendOperationUnsupported as exc:
            return error_response(501, str(exc), "not_implemented")
        except BackendError as exc:
            return error_response(502, str(exc), "backend_error")

    @app.post("/v1/responses", response_model=None)
    async def responses(request: Request) -> JSONResponse | dict[str, Any]:
        payload = await request.json()
        payload["model"] = model.id
        try:
            async with scheduler.slot() as ticket:
                compliance.emit(_generation_event("generation_start", request, config.logging.mode, payload, None, model.id, backend.capabilities.name, ticket.wait_ms))
                response = await backend.responses(payload)
                compliance.emit(_generation_event("generation_end", request, config.logging.mode, payload, response, model.id, backend.capabilities.name, ticket.wait_ms, response.get("usage")))
                return response
        except SchedulerFull as exc:
            return error_response(429, str(exc), "server_overloaded")
        except BackendOperationUnsupported as exc:
            return error_response(501, str(exc), "not_implemented")
        except BackendError as exc:
            return error_response(502, str(exc), "backend_error")

    @app.get("/v1/local-router/backends")
    async def backend_info() -> dict[str, Any]:
        return {"selected": backend.capabilities.__dict__}

    return app


def _safe_params(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: payload.get(k) for k in ("temperature", "top_p", "max_tokens", "stream", "tools", "tool_choice") if k in payload}


def _generation_event(event: str, request: Request, mode: LoggingMode, payload: dict[str, Any], response: dict[str, Any] | None, model_id: str, backend_name: str, queue_wait_ms: float, usage: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "event": event,
        "request_id": request.state.request_id,
        "endpoint": request.url.path,
        "model": model_id,
        "backend": backend_name,
        "queue_wait_ms": queue_wait_ms,
        "parameters": _safe_params(payload),
    }
    if usage is not None:
        out["usage"] = usage
    if mode == "full_content":
        out["request_payload"] = payload
        if response is not None:
            out["response_payload"] = response
    return out
