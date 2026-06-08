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
pulled, provisions an API key, starts the router, writes an OpenCode provider
config, and waits until it is ready. When it finishes it prints the URL, the API
key, and the OpenCode config path.

Then:

```bash
./router.sh curl         # send a chat request and see the response
./router.sh test         # smoke-test the running router
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
| `up` (default) | Install, start the backend, serve the router, write the OpenCode config. Idempotent. |
| `down` | Stop the router (`down --all` also stops a router-started Ollama). |
| `restart` | `down` then `up`. |
| `status` | Show whether the router is up and ready. |
| `logs` | Follow the router log. |
| `test` | Run the smoke test against the running router. |
| `curl` | Print the OpenAI-compatible chat request and run it against the router. |
| `key [show\|create\|list]` | Inspect or create the API key. |
| `opencode [path]` | Write the OpenCode provider config (default `opencode.local-router.json`). |
| `nginx` | Front the router with nginx on port 80 for public access. |

## Calling the API

The router speaks the OpenAI/OpenRouter `/v1` API, which is what OpenCode and
other clients expect. With `ROUTER_AUTH_MODE=api_key_only` every `/v1` call
carries `Authorization: Bearer <key>` — the key printed by `up`, also stored at
`.run/api-key`. `./router.sh curl` prints the request and runs it for you; the
raw forms are:

List models:

```bash
curl -s http://127.0.0.1:8080/v1/models \
  -H "Authorization: Bearer $(cat .run/api-key)"
```

Chat completion:

```bash
curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H "Authorization: Bearer $(cat .run/api-key)" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-0.5b-instruct",
    "messages": [{"role": "user", "content": "Say hello"}],
    "max_tokens": 64
  }'
```

`model` is the router-facing id from `models/catalog.yaml`, not the backend's
internal name. `/v1/completions` and `/v1/responses` work the same way. From
another machine, swap the host for your public address (see Public IP access).
Responses match the OpenAI schema, so any OpenAI-compatible SDK works by setting
its base URL to the router's `/v1` and its key to the router key.

## Backends

- **Ollama** (default): fully automated by `router.sh` — it installs Ollama if
  missing, starts it, and pulls the model. Router auth is still required because
  Ollama's OpenAI-compatible API does not enforce client-provided keys.
- **llama.cpp**: run a `llama-server` yourself (the `minimal/` folder ships one),
  set `ROUTER_BACKEND=llama_cpp` and `LLAMA_BASE_URL`, then `./router.sh up`.
  For a router-managed `llama-server` with GPU offload, use a YAML config (below).

LiteRT is represented in capability/config validation but has no serve adapter;
selecting it fails validation clearly.

## 256K context: Gemma 4 12B (GGUF via llama.cpp)

The default Ollama/Qwen path is for smoke tests. To serve **Gemma 4 12B** with
its full **256K-token** context window, run it as a GGUF through llama.cpp. The
model id `gemma-4-12b-qat` is already in [`models/catalog.yaml`](models/catalog.yaml)
with `context_length: 262144`.

> Heads-up on memory: the Q4_K_XL weights are ~6.7 GB, but a full 256K KV cache
> adds many more GB. Plan for a large-RAM host or a GPU. The flags below quantize
> the KV cache and enable flash attention to keep it manageable; if it still does
> not fit, lower `--ctx-size` and `ROUTER_CONTEXT_LENGTH` together (e.g. `65536`).

**1. Download the GGUF** into `models/`:

```bash
curl -L -o models/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf \
  https://huggingface.co/unsloth/gemma-4-12B-it-qat-GGUF/resolve/main/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf
```

**2. Serve it with llama.cpp's `llama-server`** at the full context. Use a
[llama.cpp build](https://github.com/ggml-org/llama.cpp) (the router talks to
`llama-server`'s `/health` and `/v1` endpoints):

```bash
llama-server \
  --model models/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf \
  --ctx-size 262144 \
  --flash-attn \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --host 127.0.0.1 --port 8081
  # add: --n-gpu-layers 99   to offload to a GPU
```

**3. Point the router at it** in `.env`:

```bash
ROUTER_BACKEND=llama_cpp
ROUTER_MODEL=gemma-4-12b-qat
ROUTER_CONTEXT_LENGTH=262144
LLAMA_BASE_URL=http://127.0.0.1:8081/v1
```

**4. Bring the router up** and test:

```bash
./router.sh up
./router.sh curl     # now hits Gemma 4 12B through the router
```

`router.sh up` waits for the `llama-server` at `LLAMA_BASE_URL` to be reachable,
so start it (step 2) first. The router then advertises the 256K window on
`/v1/models` and writes the OpenCode config with `gemma-4-12b-qat` available.

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

`./router.sh up` already writes the provider config to `OPENCODE_CONFIG`
(default `opencode.local-router.json`). Regenerate it any time:

```bash
./router.sh opencode
```

Point OpenCode at it:

```bash
opencode --config opencode.local-router.json
```

The config uses `@ai-sdk/openai-compatible`, sets `baseURL` to the router's
`/v1`, references the API key file so the raw secret stays out of the config,
and exposes stable router model IDs. The default model is
`local-router/qwen2.5-0.5b-instruct`. A trimmed view:

```json
{
  "provider": {
    "local-router": {
      "npm": "@ai-sdk/openai-compatible",
      "options": { "baseURL": "http://127.0.0.1:8080/v1", "apiKey": "{file:.run/api-key}" },
      "models": { "qwen2.5-0.5b-instruct": { "name": "Qwen2.5 0.5B Instruct Local" } }
    }
  },
  "model": "local-router/qwen2.5-0.5b-instruct"
}
```

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
