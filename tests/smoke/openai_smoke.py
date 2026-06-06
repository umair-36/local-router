#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(method: str, url: str, api_key: str | None = None, body: dict | None = None, timeout: float = 30) -> tuple[int, dict]:
    headers = {"Accept": "application/json", "X-Local-Router-Client": "smoke-test"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"raw": payload}
        return exc.code, parsed


def wait_ready(base_url: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, _ = request_json("GET", base_url.removesuffix("/v1") + "/readyz", timeout=5)
            if status == 200:
                return
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
        time.sleep(2)
    raise SystemExit(f"router did not become ready within {timeout_seconds}s; last_error={last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test local-router with qwen2.5:0.5b-instruct through OpenAI-compatible APIs.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="qwen2.5-0.5b-instruct")
    parser.add_argument("--api-key-file")
    parser.add_argument("--api-key")
    parser.add_argument("--ready-timeout", type=float, default=180)
    args = parser.parse_args()

    api_key = args.api_key
    if args.api_key_file:
        with open(args.api_key_file, "r", encoding="utf-8") as fh:
            api_key = fh.read().strip()

    wait_ready(args.base_url, args.ready_timeout)

    status, models = request_json("GET", args.base_url.rstrip("/") + "/models", api_key=api_key)
    if status != 200:
        print(json.dumps(models, indent=2), file=sys.stderr)
        raise SystemExit(f"GET /models failed with {status}")
    model_ids = [item.get("id") for item in models.get("data", [])]
    if args.model not in model_ids:
        raise SystemExit(f"expected model {args.model!r} in /models, saw {model_ids!r}")

    chat_body = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": "You are a concise local smoke-test assistant."},
            {"role": "user", "content": "Reply with exactly: local-router-ok"},
        ],
        "temperature": 0,
        "max_tokens": 32,
    }
    status, chat = request_json("POST", args.base_url.rstrip("/") + "/chat/completions", api_key=api_key, body=chat_body, timeout=120)
    if status != 200:
        print(json.dumps(chat, indent=2), file=sys.stderr)
        raise SystemExit(f"POST /chat/completions failed with {status}")
    content = chat.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        print(json.dumps(chat, indent=2), file=sys.stderr)
        raise SystemExit("chat completion returned no assistant content")

    tool_body = {
        "model": args.model,
        "messages": [{"role": "user", "content": "If useful, call the echo tool with text local-router-tool."}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo text for smoke testing.",
                "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            },
        }],
        "temperature": 0,
        "max_tokens": 64,
    }
    status, tool_chat = request_json("POST", args.base_url.rstrip("/") + "/chat/completions", api_key=api_key, body=tool_body, timeout=120)
    if status != 200:
        print(json.dumps(tool_chat, indent=2), file=sys.stderr)
        raise SystemExit(f"tool-shaped chat request failed with {status}")

    print(json.dumps({"ok": True, "model": args.model, "assistant_sample": content[:120]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
