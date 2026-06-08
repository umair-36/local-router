# local-router

A headless local LLM router. It sits in front of a local model runtime
(Ollama or llama.cpp) and exposes a stable OpenAI/OpenRouter-compatible API
under `/v1`, adding the operational pieces local backends usually lack: stable
model IDs, request queueing, API-key auth, readiness/preload hooks, and
structured compliance logging.

There are two ways to run a local model from this repo:

- **This router** — full features, set up with one command below.
- **[`minimal/`](minimal/README.md)** — a single self-contained GGUF server
  when you want the smallest possible thing.

## Quickstart

```bash
cp .env.example .env     # defaults work as-is; edit if you like
./router.sh up
```

`./router.sh up` does the whole setup: it creates a `.venv` and installs the
package, makes sure the backend (Ollama by default) is running with the model
pulled, provisions an API key, starts the router, and waits until it is ready.
When it finishes it prints the URL and API key.

Then:

```bash
./router.sh test         # smoke-test the running router
./router.sh opencode     # write an OpenCode provider config
./router.sh status       # is it up and ready?
./router.sh logs         # follow the log
./router.sh down         # stop it
```

That is the entire setup. Everything below is reference.

## Configuration: `.env`

`./router.sh` reads `.env` (it copies `.env.example` on first run). Every
setting has a working default.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ROUTER_MODEL` | `qwen2.5-0.5b-instruct` | Router-facing model id (must exist in `models/catalog.yaml`). |
| `ROUTER_BACKEND` | `ollama` | Runtime that serves the model: `ollama` or `llama_cpp`. |
| `ROUTER_HOST` / `ROUTER_PORT` | `127.0.0.1` / `8080` | Address the router listens on. |
| `ROUTER_CONTEXT_LENGTH` | `16384` | Context window the router advertises and requests. |
| `ROUTER_AUTH_MODE` | `api_key_only` | `api_key_only`, `ip_only`, `ip_or_key`, `ip_and_key`, or `disabled`. |
| `ROUTER_KEY_STORE` / `ROUTER_LOG_PATH` | under `.run/` | Hashed key store and usage log location. |
| `ROUTER_PUBLIC_BASE_URL` | unset | Public URL clients use, when different from `host:port`. |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434/v1` | Where the router reaches Ollama. |
| `OLLAMA_MODEL_TAG` | derived from catalog | Ollama tag to pull. |
| `LLAMA_BASE_URL` | `http://127.0.0.1:8081/v1` | Where the router reaches a running `llama-server`. |
| `LLAMA_GPU_LAYERS` | `off` | GPU offload hint for a router-managed `llama-server`. |

## `router.sh` commands

| Command | What it does |
| --- | --- |
| `up` (default) | Install, start the backend, serve the router. Idempotent. |
| `down` | Stop the router (`down --all` also stops a router-started Ollama). |
| `restart` | `down` then `up`. |
| `status` | Show whether the router is up and ready. |
| `logs` | Follow the router log. |
| `test` | Run the smoke test against the running router. |
| `key [show\|create\|list]` | Inspect or create the API key. |
| `opencode [path]` | Write an OpenCode provider config (default `opencode.local-router.json`). |
| `nginx` | Front the router with nginx on port 80 for public access. |

## Backends

- **Ollama** (default): fully automated by `router.sh` — it installs Ollama if
  missing, starts it, and pulls the model. Router auth is still required because
  Ollama's OpenAI-compatible API does not enforce client-provided keys.
- **llama.cpp**: run a `llama-server` yourself (the `minimal/` folder ships one),
  set `ROUTER_BACKEND=llama_cpp` and `LLAMA_BASE_URL`, then `./router.sh up`.
  For a router-managed `llama-server` with GPU offload, use a YAML config (below).

LiteRT is represented in capability/config validation but has no serve adapter;
selecting it fails validation clearly.

## Public IP access

Keep the router on `127.0.0.1` and put nginx in front of it:

```bash
./router.sh up
sudo ./router.sh nginx
```

nginx then proxies `http://<public-ip>/` to the router. Keep
`ROUTER_AUTH_MODE=api_key_only` so the API key is what guards access. See
[`docs/run-public-api.md`](docs/run-public-api.md) for the full runbook.

## OpenCode integration

```bash
./router.sh opencode
```

This writes `opencode.local-router.json` using `@ai-sdk/openai-compatible`,
pointing `baseURL` at the router's `/v1` and exposing stable router model IDs
such as `local-router/qwen2.5-0.5b-instruct`. The generated file references the
API key file so the raw secret stays out of the config.

## Model catalog

Models live in [`models/catalog.yaml`](models/catalog.yaml). Each entry has a
router-facing `id`, backend-specific references, quantization/context metadata,
a rough load-memory estimate, and OpenCode suitability metadata. Inspect them:

```bash
.venv/bin/local-router models list --for opencode
.venv/bin/local-router models show qwen2.5-0.5b-instruct
.venv/bin/local-router estimate --model qwen2.5-0.5b-instruct --backend ollama
```

Memory estimates are intentionally rough and exclude dynamic KV cache/context
memory, which scales with context length and parallel slots.

## API keys

`./router.sh up` provisions a key automatically. To manage keys directly:

```bash
.venv/bin/local-router keys list
.venv/bin/local-router keys add --label operator
.venv/bin/local-router keys disable --label opencode
.venv/bin/local-router keys remove --label opencode
```

Only the argon2 hash is stored; raw secrets are written to `0600` files.

## Endpoints

- `GET /healthz`, `GET /readyz`
- `GET /v1/models`, `GET /v1/models/{model}`
- `POST /v1/chat/completions`, `POST /v1/completions`, `POST /v1/responses`
- `GET /v1/local-router/backends`

`/healthz` and `/readyz` stay unauthenticated; `/v1` endpoints require auth per
`ROUTER_AUTH_MODE`.

## Compliance logging

The router writes structured JSONL usage logs (`ROUTER_LOG_PATH`). Logged
metadata includes request id, endpoint, client IP, key label, backend/model,
queue wait, generation parameters, latency, status, and backend-reported usage.
Full prompt/response logging can be enabled with `logging.mode: full_content` in
a YAML config once compliance requirements are confirmed.

## Docker

```bash
./test-docker.sh
```

This builds the image, starts Ollama, pulls the model, provisions a hashed key,
starts the router, and runs the smoke test through the Dockerized router. To run
the services directly:

```bash
docker compose build local-router
docker compose up -d ollama
docker compose run --rm ollama-pull-qwen
docker compose run --rm local-router keys add --label opencode --generate --print-secret
docker compose up -d local-router
```

For an NVIDIA GPU-backed run, add the opt-in override:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d ollama local-router
```

The Docker image keeps the same CLI entrypoint, so key management works inside
the container. The container config is `config/config.docker.yaml`. Persistent
volumes hold Ollama data (`ollama-data`), the key store (`local-router-data`),
and logs (`local-router-logs`).

## Advanced: YAML config

`.env` covers the common path. For multiple profiles, a router-managed
`llama-server`, GPU offload, or per-field tuning, use a YAML config instead. It
takes precedence over `.env` when supplied via `--config` or
`LOCAL_ROUTER_CONFIG`.

```bash
.venv/bin/local-router config init --output config/dev.yaml
.venv/bin/local-router config validate --config config/dev.yaml --profile opencode
.venv/bin/local-router serve --config config/dev.yaml --profile opencode
```

Router-managed llama.cpp with GPU offload:

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

`layers` is passed to `llama-server` as `--n-gpu-layers` and accepts a layer
count, `auto`, or `all`. The `llama-server` binary must be built with the
relevant GPU backend (CUDA, Metal, ROCm, or Vulkan).

## Production check

```bash
./production-check.sh
```

This runs unit tests, config validation, shell syntax checks, Python
compilation, Docker Compose config validation (when Docker is available), and a
source scan for blocked scaffold/prototype terms.
