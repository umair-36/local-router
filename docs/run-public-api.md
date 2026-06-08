# Public API run process

This runbook exposes `local-router` on a public interface while keeping router
API-key authentication enabled. It builds on `./router.sh`.

## 1. Configure

```bash
cp .env.example .env
```

Keep the router bound to loopback and let nginx terminate public traffic:

```bash
ROUTER_HOST=127.0.0.1
ROUTER_PORT=8080
ROUTER_AUTH_MODE=api_key_only
ROUTER_PUBLIC_BASE_URL=http://YOUR_PUBLIC_IP/v1
```

`api_key_only` means the API key guards every `/v1` request regardless of source
IP, which is what you want behind a proxy. `/healthz` and `/readyz` stay
unauthenticated as readiness probes.

## 2. Bring the router up

```bash
./router.sh up
```

This installs the package, ensures the backend is serving the model, provisions
an API key under `.run/`, and starts the router. The printed API key (also at
`.run/api-key`) is the client secret.

## 3. Put nginx in front

```bash
sudo ./router.sh nginx
```

nginx listens on port 80 and proxies to `http://127.0.0.1:8080`. Open port 80 in
your firewall/security group.

## 4. Smoke test

Local:

```bash
./router.sh test
```

Public IP:

```bash
.venv/bin/python tests/smoke/openai_smoke.py \
  --base-url http://YOUR_PUBLIC_IP/v1 \
  --model qwen2.5-0.5b-instruct \
  --api-key-file .run/api-key
```

A successful run prints `"ok": true` with an `assistant_sample`.

From another machine, the same call as plain curl:

```bash
curl -s http://YOUR_PUBLIC_IP/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5-0.5b-instruct","messages":[{"role":"user","content":"Say hello"}],"max_tokens":64}'
```

## 5. Operator check

```bash
./production-check.sh
```

Keep generated runtime state (the `.run/` directory, raw key files, logs) out of
version control; it is already ignored by git.
