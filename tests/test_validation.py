from local_router.config import BackendConfig, RouterConfig
from local_router.validation import validate_config


def test_default_config_is_production_valid_for_opencode():
    report = validate_config(RouterConfig(), profile="opencode")
    assert report.ok, report.errors


def test_litert_selection_fails_validation_until_adapter_exists():
    cfg = RouterConfig(backend=BackendConfig(provider="litert"))
    report = validate_config(cfg, profile="opencode")
    assert not report.ok
    assert any("not production-ready" in error for error in report.errors)
