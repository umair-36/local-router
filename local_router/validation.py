from __future__ import annotations

from dataclasses import dataclass, field

from .backends import create_backend
from .catalog import ModelCatalog
from .config import RouterConfig
from .memory import estimate_memory


@dataclass(frozen=True)
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_config(config: RouterConfig, profile: str | None = None) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    catalog = ModelCatalog.load(config.paths.catalog)
    model = catalog.get(config.model.id)
    backend_ref = model.backend_ref(config.backend.provider)
    if backend_ref is None:
        errors.append(f"model {model.id} has no backend reference for {config.backend.provider}")
    backend = create_backend(config.backend, config.model, model)
    if not backend.capabilities.production_ready:
        errors.append(f"backend {backend.capabilities.name} is not production-ready for OpenAI-compatible serving")
    warnings.extend(backend.capabilities.limitations)
    if config.auth.mode == "disabled":
        warnings.append("auth is disabled; this should only be used for explicitly trusted loopback-only development")
    if not config.logging.enabled:
        errors.append("compliance logging is disabled")
    if profile == "opencode":
        opc = model.data.get("opencode", {})
        if not opc.get("compatible"):
            errors.append(f"model {model.id} is not marked OpenCode-compatible")
        minimum = int(opc.get("min_context_recommended", 16384))
        if config.model.context_length < minimum:
            warnings.append(f"OpenCode profile recommends at least {minimum} context tokens; configured {config.model.context_length}")
        if not backend.capabilities.opencode_supported:
            errors.append(f"backend {backend.capabilities.name} is not currently marked OpenCode-supported")
    est = estimate_memory(model, config.model.context_length, config.scheduler.max_in_flight)
    warnings.append(f"rough memory estimate: {est.total_gb:.2f} GB (load {est.load_gb:.2f} + KV {est.kv_cache_gb:.2f} + overhead {est.overhead_gb:.2f})")
    return ValidationReport(errors=errors, warnings=warnings)
