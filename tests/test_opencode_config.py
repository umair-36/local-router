from local_router.catalog import ModelCatalog
from local_router.config import RouterConfig
from local_router.integrations.opencode import build_config


def test_opencode_config_uses_openai_compatible_provider():
    cfg = RouterConfig()
    data = build_config(cfg, ModelCatalog.load("models/catalog.yaml"), api_key_file="~/.local-router/opencode-key")
    provider = data["provider"]["local-router"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"]["baseURL"].endswith("/v1")
    assert "qwen2.5-0.5b-instruct" in provider["models"]
    assert data["model"] == "local-router/qwen2.5-0.5b-instruct"
