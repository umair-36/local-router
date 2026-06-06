from __future__ import annotations

import getpass
import ipaddress
import json
import os
import secrets
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import AuthConfig, expand_path

_PH = PasswordHasher()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AuthResult:
    ok: bool
    key_label: str | None = None
    reason: str | None = None


class KeyStore:
    def __init__(self, path: str | Path):
        self.path = expand_path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"keys": []}
        with self.path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        tmp.replace(self.path)

    def add_hash(self, label: str, raw_key: str) -> None:
        data = self.load()
        keys = data.setdefault("keys", [])
        if any(k.get("label") == label for k in keys):
            raise ValueError(f"key label already exists: {label}")
        keys.append({"label": label, "hash": _PH.hash(raw_key), "created_at": utc_now(), "disabled": False})
        self.save(data)

    def remove(self, label: str) -> None:
        data = self.load()
        before = len(data.get("keys", []))
        data["keys"] = [k for k in data.get("keys", []) if k.get("label") != label]
        if len(data["keys"]) == before:
            raise ValueError(f"key label not found: {label}")
        self.save(data)

    def disable(self, label: str) -> None:
        data = self.load()
        for key in data.get("keys", []):
            if key.get("label") == label:
                key["disabled"] = True
                key["disabled_at"] = utc_now()
                self.save(data)
                return
        raise ValueError(f"key label not found: {label}")

    def labels(self) -> list[str]:
        return [str(k.get("label")) for k in self.load().get("keys", [])]

    def has_label(self, label: str) -> bool:
        return label in self.labels()

    def verify(self, raw_key: str) -> str | None:
        for entry in self.load().get("keys", []):
            if entry.get("disabled"):
                continue
            try:
                if _PH.verify(str(entry["hash"]), raw_key):
                    return str(entry.get("label"))
            except (VerifyMismatchError, VerificationError, KeyError):
                continue
        return None


def generate_secret() -> str:
    return "lr_" + secrets.token_urlsafe(32)


def prompt_secret(confirm: bool = True) -> str:
    first = getpass.getpass("API key: ")
    if confirm:
        second = getpass.getpass("Confirm API key: ")
        if first != second:
            raise ValueError("keys did not match")
    if len(first) < 16:
        raise ValueError("key must be at least 16 characters")
    return first


def write_secret_file(path: str | Path, secret: str) -> None:
    target = expand_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        fh.write(secret + "\n")
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "0.0.0.0"


def ip_allowed(ip: str, allowed: list[str]) -> bool:
    address = ipaddress.ip_address(ip)
    return any(address in ipaddress.ip_network(cidr, strict=False) for cidr in allowed)


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, config: AuthConfig):
        super().__init__(app)
        self.config = config
        self.keys = KeyStore(config.key_store_path)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.url.path in {"/healthz", "/readyz"}:
            return await call_next(request)
        result = self.authenticate(request)
        if not result.ok:
            return JSONResponse(status_code=401, content={"error": {"message": result.reason or "unauthorized", "type": "authentication_error", "code": "unauthorized"}})
        request.state.auth_key_label = result.key_label
        return await call_next(request)

    def authenticate(self, request: Request) -> AuthResult:
        mode = self.config.mode
        if mode == "disabled":
            return AuthResult(ok=True)
        ip_ok = ip_allowed(_client_ip(request), self.config.allowed_ips)
        header = request.headers.get("authorization", "")
        raw = header[7:].strip() if header.lower().startswith("bearer ") else ""
        label = self.keys.verify(raw) if raw else None
        key_ok = label is not None
        if mode == "ip_only":
            return AuthResult(ip_ok, reason="client IP is not allowed")
        if mode == "api_key_only":
            return AuthResult(key_ok, label, "invalid API key")
        if mode == "ip_or_key":
            return AuthResult(ip_ok or key_ok, label, "client IP or API key required")
        if mode == "ip_and_key":
            return AuthResult(ip_ok and key_ok, label, "client IP and valid API key required")
        return AuthResult(False, reason="invalid auth mode")
