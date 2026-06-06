from pathlib import Path

from local_router.auth import KeyStore
from local_router.catalog import ModelCatalog
from local_router.memory import estimate_memory


def test_catalog_loads_qwen_and_gemma_entries():
    catalog = ModelCatalog.load("models/catalog.yaml")
    ids = [model.id for model in catalog.list("opencode")]
    assert "qwen2.5-0.5b-instruct" in ids
    assert "gemma3-4b" in ids
    assert catalog.get("qwen2.5-0.5b-instruct").backend_ref("ollama")["model"] == "qwen2.5:0.5b-instruct"


def test_memory_estimate_scales_with_context_and_parallel():
    model = ModelCatalog.load("models/catalog.yaml").get("gemma3-1b")
    small = estimate_memory(model, context_length=8192, parallel=1)
    large = estimate_memory(model, context_length=16384, parallel=2)
    assert large.total_gb > small.total_gb


def test_key_store_hashes_and_verifies_without_storing_secret(tmp_path: Path):
    store = KeyStore(tmp_path / "keys.json")
    store.add_hash("opencode", "test-secret-value-123")
    assert store.verify("test-secret-value-123") == "opencode"
    assert store.verify("wrong-secret") is None
    assert "test-secret-value-123" not in (tmp_path / "keys.json").read_text()
