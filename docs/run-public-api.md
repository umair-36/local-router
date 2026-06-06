# Public API Run Process

This runbook starts `local-router` on a public interface while keeping router API-key authentication enabled.

## 1. Prepare Python

```bash
./install-dev.sh
```

The script creates `.venv` when needed and installs the package in editable mode with test dependencies.

## 2. Start Or Verify Ollama

Run Ollama as a service or foreground process, then make sure the configured model is present:

```bash
ollama list
ollama pull qwen2.5:0.5b-instruct
```

The default router config expects Ollama at `http://127.0.0.1:11434/v1`.

## 3. Create A Public Runtime Config

Keep the public runtime config and key store outside tracked files. One working layout is under `.local-router-test/`, which is already ignored by git.

```bash
mkdir -p .local-router-test
cp config/dev.yaml .local-router-test/public-run.yaml
```

Edit `.local-router-test/public-run.yaml`:

```yaml
server:
  host: 0.0.0.0
  port: 8080
  public_base_url: http://YOUR_PUBLIC_IP:8080/v1
auth:
  mode: api_key_only
  key_store_path: .local-router-test/keys.json
logging:
  path: .local-router-test/usage.jsonl
paths:
  runtime_dir: .local-router-test/run
```

Leave `auth.mode` enabled for public runs. The router authenticates `/v1` endpoints with `Authorization: Bearer ...`; `/healthz` and `/readyz` remain unauthenticated readiness probes.

## 4. Create A Test Key

```bash
.venv/bin/local-router keys add \
  --config .local-router-test/public-run.yaml \
  --label public-test \
  --generate \
  --write-secret-file .local-router-test/public-test-key
```

The key store keeps only the hash. The raw key file should stay untracked.

## 5. Run The Router

```bash
.venv/bin/local-router serve --config .local-router-test/public-run.yaml --profile opencode
```

The expected startup line is:

```text
Uvicorn running on http://0.0.0.0:8080
```

## 6. Smoke Test

Local check:

```bash
.venv/bin/python tests/smoke/openai_smoke.py \
  --base-url http://127.0.0.1:8080/v1 \
  --model qwen2.5-0.5b-instruct \
  --api-key-file .local-router-test/public-test-key
```

Public-IP check:

```bash
.venv/bin/python tests/smoke/openai_smoke.py \
  --base-url http://YOUR_PUBLIC_IP:8080/v1 \
  --model qwen2.5-0.5b-instruct \
  --api-key-file .local-router-test/public-test-key
```

Successful output includes:

```json
{
  "ok": true,
  "model": "qwen2.5-0.5b-instruct",
  "assistant_sample": "local-router-ok"
}
```

## 7. Operator Checks

Run the full repository check before publishing changes:

```bash
./production-check.sh
```
