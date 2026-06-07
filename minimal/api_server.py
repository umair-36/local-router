import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from gguf_engine import GgufEngine


MODEL_ID = os.environ.get("MODEL_ID", "local-gguf")
engine: GgufEngine | None = None
serve_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    with GgufEngine.from_env() as loaded:
        engine = loaded
        yield
    engine = None


app = FastAPI(lifespan=lifespan)


def params(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "max_tokens": body.get("max_tokens", body.get("max_completion_tokens", 512)),
        "temperature": body.get("temperature", 0.7),
        "top_p": body.get("top_p", 0.95),
        "stop": body.get("stop"),
        "stream": False,
    }


async def run_blocking(fn, **kwargs: Any) -> dict[str, Any]:
    async with serve_lock:
        return await asyncio.to_thread(fn, **kwargs)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    if engine is None or engine.llm is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    return {"status": "ready"}


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local"}]}


@app.post("/v1/chat/completions")
async def chat_completions(body: dict[str, Any]) -> JSONResponse:
    if engine is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    if body.get("stream"):
        raise HTTPException(status_code=400, detail="streaming is not implemented in minimal server")
    result = await run_blocking(engine.chat, messages=body["messages"], **params(body))
    result["model"] = MODEL_ID
    return JSONResponse(result)


@app.post("/v1/completions")
async def completions(body: dict[str, Any]) -> JSONResponse:
    if engine is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    if body.get("stream"):
        raise HTTPException(status_code=400, detail="streaming is not implemented in minimal server")
    result = await run_blocking(engine.complete, prompt=body["prompt"], **params(body))
    result["model"] = MODEL_ID
    return JSONResponse(result)
