from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from .config import LogConfig, expand_path

_SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key|token|password|secret)(['\"\s:=]+)([^\s'\",}]+)", re.I),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]+=*", re.I),
]


def redact(value: Any) -> Any:
    if isinstance(value, str):
        out = value
        for pattern in _SECRET_PATTERNS:
            out = pattern.sub(lambda m: f"{m.group(1) if m.lastindex and m.lastindex >= 1 else 'secret'}[REDACTED]", out)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if re.search("key|token|password|secret", str(k), re.I) else redact(v)) for k, v in value.items()}
    return value


class ComplianceLogger:
    def __init__(self, config: LogConfig):
        self.config = config
        self.path = expand_path(config.path)

    def emit(self, event: dict[str, Any]) -> None:
        if not self.config.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.config.redact_secrets:
            event = redact(event)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True, default=str) + "\n")


class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, logger: ComplianceLogger):
        super().__init__(app)
        self.logger = logger

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            self.logger.emit({
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status,
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
                "client_ip": request.client.host if request.client else None,
                "auth_key_label": getattr(request.state, "auth_key_label", None),
                "client_profile": request.headers.get("x-local-router-client", "unknown"),
            })
