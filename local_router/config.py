from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


AuthMode = Literal["disabled", "ip_only", "api_key_only", "ip_or_key", "ip_and_key"]
BackendName = Literal["ollama", "llama_cpp", "litert"]
GpuLayers = int | Literal["auto", "all"]
LoggingMode = Literal["usage_only", "full_content"]


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8080
    public_base_url: str | None = None
    request_timeout_seconds: float = 600


class AuthConfig(BaseModel):
    mode: AuthMode = "api_key_only"
    allowed_ips: list[str] = Field(default_factory=lambda: ["127.0.0.1/32", "::1/128"])
    key_store_path: str = "~/.local-router/keys.json"


class BackendGpuConfig(BaseModel):
    enabled: bool = False
    layers: GpuLayers = "all"


class BackendConfig(BaseModel):
    provider: BackendName = "ollama"
    base_url: str | None = None
    executable: str | None = None
    model_path: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    extra_args: list[str] = Field(default_factory=list)
    manage_process: bool = False
    startup_timeout_seconds: float = 300
    gpu: BackendGpuConfig = Field(default_factory=BackendGpuConfig)


class ModelConfig(BaseModel):
    id: str = "qwen2.5-0.5b-instruct"
    context_length: int = 8192
    preload: bool = True
    keep_alive: str | int = -1


class SchedulerConfig(BaseModel):
    max_in_flight: int = 1
    max_queue: int = 32
    queue_timeout_seconds: float = 300

    @field_validator("max_in_flight", "max_queue")
    @classmethod
    def positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        return value


class LogConfig(BaseModel):
    enabled: bool = True
    mode: LoggingMode = "usage_only"
    path: str = "~/.local-router/logs/usage.jsonl"
    redact_secrets: bool = True


class PathsConfig(BaseModel):
    catalog: str = "models/catalog.yaml"
    runtime_dir: str = "~/.local-router/run"


class ProfileConfig(BaseModel):
    context_length: int | None = None
    preferred_context_length: int | None = None
    streaming: bool = True
    queue_timeout_seconds: float | None = None


class RouterConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    backend: BackendConfig = Field(default_factory=BackendConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    logging: LogConfig = Field(default_factory=LogConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    profiles: dict[str, ProfileConfig] = Field(default_factory=lambda: {
        "opencode": ProfileConfig(context_length=16384, preferred_context_length=32768, queue_timeout_seconds=300),
    })

    def apply_profile(self, profile: str | None) -> "RouterConfig":
        if not profile:
            return self
        if profile not in self.profiles:
            raise ValueError(f"unknown profile: {profile}")
        cfg = self.model_copy(deep=True)
        prof = cfg.profiles[profile]
        if prof.context_length:
            cfg.model.context_length = prof.context_length
        if prof.queue_timeout_seconds:
            cfg.scheduler.queue_timeout_seconds = prof.queue_timeout_seconds
        return cfg


def expand_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def load_config(path: str | Path | None = None, profile: str | None = None) -> RouterConfig:
    if path is None:
        cfg = RouterConfig()
    else:
        with open(expand_path(path), "r", encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh) or {}
        cfg = RouterConfig.model_validate(data)
    return cfg.apply_profile(profile)


def save_config_template(path: str | Path) -> None:
    data = RouterConfig().model_dump(mode="json")
    target = expand_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)
