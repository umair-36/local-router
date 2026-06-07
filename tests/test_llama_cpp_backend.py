from local_router.backends.llama_cpp import LlamaCppBackend
from local_router.catalog import ModelCatalog
from local_router.config import BackendConfig, BackendGpuConfig, ModelConfig


def test_managed_llama_cpp_command_omits_gpu_flag_by_default():
    model = ModelCatalog.load("models/catalog.yaml").get("qwen2.5-0.5b-instruct")
    backend = LlamaCppBackend(
        BackendConfig(provider="llama_cpp", manage_process=True, model_path="/models/qwen.gguf"),
        ModelConfig(context_length=8192),
        model,
    )

    command = backend.managed_command()

    assert "--n-gpu-layers" not in command
    assert command[command.index("--ctx-size") + 1] == "8192"


def test_managed_llama_cpp_command_adds_opted_in_gpu_layers():
    model = ModelCatalog.load("models/catalog.yaml").get("qwen2.5-0.5b-instruct")
    backend = LlamaCppBackend(
        BackendConfig(
            provider="llama_cpp",
            base_url="http://127.0.0.1:8081/v1",
            manage_process=True,
            model_path="/models/qwen.gguf",
            gpu=BackendGpuConfig(enabled=True, layers="all"),
        ),
        ModelConfig(context_length=16384),
        model,
    )

    command = backend.managed_command()

    assert command[command.index("--n-gpu-layers") + 1] == "all"
    assert command[command.index("--port") + 1] == "8081"
