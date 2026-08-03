from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _fetch_module():
    path = Path(__file__).resolve().parents[1] / "models" / "nav" / "fetch_models.py"
    spec = importlib.util.spec_from_file_location("parcel_fetch_models", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_citywalker_artifact_is_immutable_and_licensed() -> None:
    module = _fetch_module()
    model = module.load_lock()["citywalker_2000hr"]

    assert len(model["sha256"]) == 64
    assert model["size_bytes"] == 1_752_028_242
    assert len(model["source_commit"]) == 40
    assert model["license"] == "Apache-2.0"
    assert model["activation"].startswith("research_only")


def test_fetch_rejects_cache_escape(tmp_path: Path) -> None:
    module = _fetch_module()
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "models": {
                    "bad": {
                        "filename": "../escape.ckpt",
                        "url": "https://example.com/escape.ckpt",
                        "size_bytes": 1,
                        "sha256": "0" * 64,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    model = module.load_lock(bad)["bad"]

    with pytest.raises(ValueError, match="unsafe"):
        module.fetch_model("bad", model, root=tmp_path / "models")
