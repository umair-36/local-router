from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
import uvicorn

from .api import create_app
from .auth import KeyStore, generate_secret, prompt_secret, write_secret_file
from .backends import create_backend
from .catalog import ModelCatalog
from .config import RouterConfig, load_config, save_config_template
from .integrations.opencode import build_config, write_config
from .memory import estimate_memory
from .validation import validate_config

app = typer.Typer(help="Headless local LLM router with OpenAI/OpenRouter-compatible API.")
keys_app = typer.Typer(help="Manage hashed API keys.")
models_app = typer.Typer(help="Inspect model catalog.")
opencode_app = typer.Typer(help="Generate and validate OpenCode integration config.")
backends_app = typer.Typer(help="Inspect backend capabilities.")
config_app = typer.Typer(help="Create and validate router config.")
app.add_typer(keys_app, name="keys")
app.add_typer(models_app, name="models")
app.add_typer(opencode_app, name="opencode")
app.add_typer(backends_app, name="backends")
app.add_typer(config_app, name="config")


def _cfg(config: Optional[Path], profile: Optional[str]) -> RouterConfig:
    return load_config(config, profile)


@app.command()
def serve(config: Optional[Path] = typer.Option(None, "--config", "-c"), profile: Optional[str] = typer.Option(None, "--profile")) -> None:
    """Run the router API."""
    cfg = _cfg(config, profile)
    uvicorn.run(create_app(cfg), host=cfg.server.host, port=cfg.server.port)


@app.command()
def estimate(model: Optional[str] = typer.Option(None), backend: Optional[str] = typer.Option(None), context: Optional[int] = typer.Option(None), parallel: Optional[int] = typer.Option(None), config: Optional[Path] = typer.Option(None, "--config", "-c"), profile: Optional[str] = typer.Option(None, "--profile")) -> None:
    """Print rough memory estimate."""
    cfg = _cfg(config, profile)
    if model:
        cfg.model.id = model
    if backend:
        cfg.backend.provider = backend  # type: ignore[assignment]
    if context:
        cfg.model.context_length = context
    catalog = ModelCatalog.load(cfg.paths.catalog)
    entry = catalog.get(cfg.model.id)
    est = estimate_memory(entry, cfg.model.context_length, parallel or cfg.scheduler.max_in_flight)
    typer.echo(json.dumps({"model": entry.id, "backend": cfg.backend.provider, "context_length": cfg.model.context_length, "estimate_gb": est.__dict__ | {"total_gb": est.total_gb}, "warning": "Approximate; KV cache and backend overhead vary by runtime."}, indent=2))


@config_app.command("init")
def config_init(output: Path = typer.Option(Path("config/dev.yaml"), "--output", "-o")) -> None:
    save_config_template(output)
    typer.echo(f"wrote {output}")


@config_app.command("validate")
def config_validate(config: Optional[Path] = typer.Option(None, "--config", "-c"), profile: Optional[str] = typer.Option(None, "--profile")) -> None:
    cfg = _cfg(config, profile)
    report = validate_config(cfg, profile)
    for warning in report.warnings:
        typer.echo(f"WARN: {warning}")
    for error in report.errors:
        typer.echo(f"ERROR: {error}", err=True)
    if not report.ok:
        raise typer.Exit(1)


@models_app.command("list")
def models_list(config: Optional[Path] = typer.Option(None, "--config", "-c"), for_client: Optional[str] = typer.Option(None, "--for")) -> None:
    catalog = ModelCatalog.load(_cfg(config, None).paths.catalog)
    for model in catalog.list(for_client):
        typer.echo(f"{model.id}\t{model.name}\t~{model.memory_load_gb} GB load")


@models_app.command("show")
def models_show(model_id: str, config: Optional[Path] = typer.Option(None, "--config", "-c")) -> None:
    catalog = ModelCatalog.load(_cfg(config, None).paths.catalog)
    typer.echo(json.dumps(catalog.get(model_id).data, indent=2))


@keys_app.command("add")
def keys_add(label: str = typer.Option(...), config: Optional[Path] = typer.Option(None, "--config", "-c"), generate: bool = typer.Option(False), secret_file: Optional[Path] = typer.Option(None, "--secret-file"), write_secret: Optional[Path] = typer.Option(None, "--write-secret-file"), print_secret: bool = typer.Option(False)) -> None:
    cfg = _cfg(config, None)
    if secret_file and generate:
        raise typer.BadParameter("--secret-file and --generate are mutually exclusive")
    if secret_file:
        secret = secret_file.expanduser().read_text(encoding="utf-8").strip()
    else:
        secret = generate_secret() if generate else prompt_secret()
    KeyStore(cfg.auth.key_store_path).add_hash(label, secret)
    if write_secret:
        write_secret_file(write_secret, secret)
        typer.echo(f"wrote secret file {write_secret}")
    if print_secret:
        typer.echo(secret)
    typer.echo(f"stored hash for key label {label}")


@keys_app.command("remove")
def keys_remove(label: str = typer.Option(...), config: Optional[Path] = typer.Option(None, "--config", "-c")) -> None:
    KeyStore(_cfg(config, None).auth.key_store_path).remove(label)
    typer.echo(f"removed {label}")


@keys_app.command("disable")
def keys_disable(label: str = typer.Option(...), config: Optional[Path] = typer.Option(None, "--config", "-c")) -> None:
    KeyStore(_cfg(config, None).auth.key_store_path).disable(label)
    typer.echo(f"disabled {label}")


@keys_app.command("list")
def keys_list(config: Optional[Path] = typer.Option(None, "--config", "-c")) -> None:
    for label in KeyStore(_cfg(config, None).auth.key_store_path).labels():
        typer.echo(label)


@opencode_app.command("config")
def opencode_config(output: Optional[Path] = typer.Option(None, "--output", "-o"), provider_id: str = typer.Option("local-router"), model: Optional[str] = typer.Option(None), api_key_file: Optional[str] = typer.Option(None), config: Optional[Path] = typer.Option(None, "--config", "-c"), profile: str = typer.Option("opencode")) -> None:
    cfg = _cfg(config, profile)
    data = build_config(cfg, ModelCatalog.load(cfg.paths.catalog), provider_id, model, api_key_file)
    if output:
        write_config(output, data)
        typer.echo(f"wrote {output}")
    else:
        typer.echo(json.dumps(data, indent=2))


@opencode_app.command("check")
def opencode_check(base_url: str = typer.Option(...), model: str = typer.Option(...), api_key: Optional[str] = typer.Option(None)) -> None:
    """Print a curl-based smoke checklist for a running router."""
    auth = f" -H 'Authorization: Bearer {api_key}'" if api_key else ""
    typer.echo(f"curl{auth} {base_url.rstrip('/')}/models")
    typer.echo(f"curl{auth} -H 'Content-Type: application/json' -d '{{\"model\":\"{model}\",\"messages\":[{{\"role\":\"user\",\"content\":\"hello\"}}]}}' {base_url.rstrip('/')}/chat/completions")


@backends_app.command("inspect")
def backends_inspect(config: Optional[Path] = typer.Option(None, "--config", "-c")) -> None:
    cfg = _cfg(config, None)
    catalog = ModelCatalog.load(cfg.paths.catalog)
    backend = create_backend(cfg.backend, cfg.model, catalog.get(cfg.model.id))
    typer.echo(json.dumps(backend.capabilities.__dict__, indent=2))


if __name__ == "__main__":
    app()
