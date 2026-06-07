# local-router

A minimal, headless mechanism to deploy a local LLM and expose it through an OpenAI/OpenRouter-like API suitable for tools such as OpenCode.

## Goals

`local-router` is designed to sit in front of local model runtimes and provide the operational controls that local backends often do not provide by themselves:

- OpenAI/OpenRouter-like HTTP API under `/v1`.
- Stable router model IDs hiding backend-specific model names or GGUF paths.
- Request queueing so a second request is queued instead of refused while one generation is running.
- API-key hash authentication and/or IP allowlisting.
- Secure CLI commands for adding/removing hashed API keys.
- Model preload/readiness hooks so the selected model is warm while the API is up.
- Structured compliance logging.
- Backend capability warnings, especially when a backend cannot satisfy a requirement natively.
- Headless CLI-only operation.
- OpenCode config generation.

## Supported backend options

| Backend | Status | Notes |
| --- | --- | --- |
| Ollama | Initial default | Proxies Ollama's OpenAI-compatible `/v1` API and uses Ollama native preload calls. Router auth is still required because Ollama's OpenAI-compatible API does not enforce client-provided API keys. |
| llama.cpp / GGUF | Initial adapter | Proxies an existing `llama-server` OpenAI-compatible endpoint. Chat template and GGUF metadata quality matter for OpenCode behavior. |
| LiteRT | Declared but not serve-enabled | LiteRT remains represented in capability/config validation. Selecting it now fails validation/startup clearly because no OpenAI-compatible LiteRT serving adapter is configured. |

## Install for development

```bash
python -m pip install -e '.[dev]'
```

## Create a config

```bash
local-router config init --output config/dev.yaml
local-router config validate --config config/dev.yaml --profile opencode
```

Important config sections:

- `server`: public router host/port.
- `auth`: IP allowlist and API-key hash store.
- `backend`: selected runtime (`ollama`, `llama_cpp`, or `litert`).
- `model`: stable router model id and context length.
- `scheduler`: in-flight and queue limits.
- `logging`: JSONL compliance log settings.
- `profiles.opencode`: larger context defaults for OpenCode.

## GPU offload

The minimal GGUF server already passes `N_GPU_LAYERS` into `llama-cpp-python`; its packaged tray path currently defaults that value to `-1`.

For the main router, Ollama and externally started llama.cpp servers keep their own GPU behavior. To have `local-router` start `llama-server` and opt into GPU offload, configure the llama.cpp backend like this:

```yaml
backend:
  provider: llama_cpp
  base_url: http://127.0.0.1:8081/v1
  manage_process: true
  executable: llama-server
  model_path: /path/to/model.gguf
  gpu:
    enabled: true
    layers: all
```

`layers` is passed to `llama-server` as `--n-gpu-layers`; it accepts an exact layer count, `auto`, or `all`. The `llama-server` binary still needs to be built with the relevant GPU backend, such as CUDA, Metal, ROCm, or Vulkan. The router omits the GPU offload flag while `gpu.enabled` is false.

## Manage API keys securely

Generate a key for OpenCode, store only its hash in the router key store, and write the raw secret to a `0600` file for OpenCode to read:

```bash
local-router keys add --label opencode --generate --write-secret-file ~/.local-router/opencode-key
```

Manual key entry is hidden and confirmed:

```bash
local-router keys add --label operator
```

Other commands:

```bash
local-router keys list
local-router keys disable --label opencode
local-router keys remove --label opencode
```

## Model catalog

Initial Qwen and Gemma entries live in [`models/catalog.yaml`](models/catalog.yaml). Add models by appending YAML entries with:

- router-facing `id`;
- backend-specific references;
- quantization and context metadata;
- rough load-memory estimate;
- OpenCode suitability metadata.

Inspect models:

```bash
local-router models list --for opencode
local-router models show qwen2.5-0.5b-instruct
local-router estimate --model qwen2.5-0.5b-instruct --backend ollama --profile opencode
```

Memory estimates are intentionally rough. Catalog load memory excludes dynamic KV cache/context memory, which scales with context length and parallel slots.

## Run the router

```bash
local-router serve --config config/dev.yaml --profile opencode
```

Implemented endpoints include:

- `GET /healthz`
- `GET /readyz`
- `GET /v1/models`
- `GET /v1/models/{model}`
- `POST /v1/chat/completions`
- `POST /v1/completions`
- `POST /v1/responses`
- `GET /v1/local-router/backends`

## OpenCode integration

Generate an OpenCode provider config that points at the router rather than at a raw backend:

```bash
local-router opencode config \
  --config config/dev.yaml \
  --provider-id local-router \
  --api-key-file ~/.local-router/opencode-key \
  --output opencode.local-router.json
```

The generated provider uses `@ai-sdk/openai-compatible`, points `baseURL` at the router's `/v1`, and exposes stable router model IDs such as `local-router/qwen2.5-0.5b-instruct`.

## Compliance logging

The router writes structured JSONL usage logs by default. Logged metadata includes request id, endpoint, client IP, auth key label, backend/model information, queue wait, generation parameters, latency, status, and usage when a backend returns it. Full prompt/response content logging can be enabled with `logging.mode: full_content` once an operator has confirmed their compliance requirements.

## Production-readiness notes

- Ollama and llama.cpp adapters proxy already-running backends by default; Docker Compose provides the Ollama deployment path.
- llama.cpp deployments should point `backend.base_url` at a running `llama-server` with the selected GGUF loaded.
- LiteRT is declared for capability visibility, but config validation and startup reject it until a concrete OpenAI-compatible LiteRT adapter is configured.
- OpenAI `/v1/responses` is native for llama.cpp and explicitly translated for Ollama with response metadata marking the translation.

## Up-front scripts

The repository keeps the common operator/dev entrypoints at the repo root:

- `./install-dev.sh` creates `.venv` when needed and installs the direct Python development environment there.
- `./run-dev.sh` runs the router from `config/dev.yaml`.
- `./test-dev.sh` runs the Qwen2.5 0.5B smoke test against a dev/local deployment.
- `./test-docker.sh` builds the image, pulls `qwen2.5:0.5b-instruct`, starts Docker Compose, creates a persisted hashed API key, and runs the same smoke test through the Dockerized router.

The smoke test itself lives at `tests/smoke/openai_smoke.py` and exercises `/readyz`, `/v1/models`, normal chat completions, and a tool-shaped chat request using the persistent `qwen2.5-0.5b-instruct` router model.

For a public-IP run, use [`docs/run-public-api.md`](docs/run-public-api.md). Keep generated runtime config, key stores, raw key files, and logs outside tracked files.


## Production check

Run the repository-level production check before shipping changes:

```bash
./production-check.sh
```

This runs unit checks, config validation, shell syntax checks, Python compilation, Docker Compose config validation when Docker is available, and a source scan that rejects blocked scaffold/prototype terms.

## Docker deployment

Build and run with Docker Compose:

```bash
./test-docker.sh
```

Or run the steps manually:

```bash
docker compose build local-router
docker compose up -d ollama
docker compose run --rm ollama-pull-qwen
docker compose run --rm local-router keys add --label opencode --generate --print-secret
docker compose up -d local-router
```

For an NVIDIA GPU-backed Docker run, include the opt-in override when starting services:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d ollama local-router
```

The Docker image keeps the same CLI entrypoint as the direct Python install. That means key management remains available inside the container:

```bash
docker compose run --rm local-router keys list
docker compose run --rm local-router keys add --label operator
```

Persistent Docker volumes are used for:

- Ollama model data: `ollama-data`.
- Router key store/runtime data: `local-router-data`.
- Router compliance logs: `local-router-logs`.

The Docker config is `config/config.docker.yaml` and defaults to the Qwen smoke-test model.
