from pathlib import Path

import yaml

from local_router.cli import _cfg


def test_cli_config_defaults_to_local_router_config_env(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "router.yaml"
    config_path.write_text(yaml.safe_dump({"auth": {"key_store_path": str(tmp_path / "keys.json")}}), encoding="utf-8")
    monkeypatch.setenv("LOCAL_ROUTER_CONFIG", str(config_path))

    cfg = _cfg(None, None)

    assert cfg.auth.key_store_path == str(tmp_path / "keys.json")
