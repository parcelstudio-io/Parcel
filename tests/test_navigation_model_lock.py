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


def test_citywalker_artifact_is_immutable_and_license_scope_is_explicit() -> None:
    module = _fetch_module()
    model = module.load_lock()["citywalker_2000hr"]

    assert len(model["sha256"]) == 64
    assert model["size_bytes"] == 1_752_028_242
    assert model["url"] == (
        "https://github.com/ai4ce/CityWalker/releases/download/v1.0/"
        "CityWalker_2000hr.ckpt"
    )
    assert model["sha256"] == (
        "a42326778e5e318c6222575dc5e02f1794d9a60cce4dc8f8a2ee5df7dc6d1c29"
    )
    assert model["source_commit"] == "6fdae3809f66304e4a0f8bb077aaf7f93c1a3227"
    assert model["repository_review_commit"] == (
        "ab0ef60b17dc4d1d16c7d95dd143e6dac91abed1"
    )
    assert model["repository_code_license"] == "Apache-2.0"
    assert model["checkpoint_license"] == "NOASSERTION"
    evidence = model["checkpoint_license_evidence"]
    assert evidence["release_asset_specific_notice"] is False
    assert evidence["official_converted_model_license"] == "Apache-2.0"
    assert evidence["official_converted_model_url"] == (
        "https://huggingface.co/ai4ce/citywalker"
    )
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
