import os
from contextlib import AbstractContextManager
from typing import Any

from llama_cpp import Llama


class GgufEngine(AbstractContextManager):
    def __init__(self, model_path: str, n_ctx: int = 4096, n_gpu_layers: int = -1):
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.llm: Llama | None = None

    @classmethod
    def from_env(cls) -> "GgufEngine":
        model_path = os.environ.get("MODEL_PATH", "model.gguf")
        n_ctx = int(os.environ.get("N_CTX", "4096"))
        n_gpu_layers = int(os.environ.get("N_GPU_LAYERS", "-1"))
        return cls(model_path=model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers)

    def __enter__(self) -> "GgufEngine":
        self.llm = Llama(
            model_path=self.model_path,
            n_ctx=self.n_ctx,
            n_gpu_layers=self.n_gpu_layers,
            verbose=False,
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.llm = None

    def chat(self, **kwargs: Any) -> dict[str, Any]:
        if self.llm is None:
            raise RuntimeError("engine is not loaded")
        return self.llm.create_chat_completion(**kwargs)

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        if self.llm is None:
            raise RuntimeError("engine is not loaded")
        return self.llm.create_completion(**kwargs)
