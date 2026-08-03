from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest


def _fetch_module():
    path = Path(__file__).resolve().parents[1] / "models" / "reasoner" / "fetch_models.py"
    spec = importlib.util.spec_from_file_location("parcel_fetch_reasoner_models", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ministral_challengers_are_official_pinned_and_deployment_disabled() -> None:
    models = _fetch_module().load_lock()

    assert set(models) == {
        "ministral_3_8b_instruct_2512_q4_k_m",
        "ministral_3_8b_reasoning_2512_q4_k_m",
    }
    assert models["ministral_3_8b_instruct_2512_q4_k_m"]["size_bytes"] == 5_198_911_904
    assert models["ministral_3_8b_reasoning_2512_q4_k_m"]["size_bytes"] == 5_198_910_368
    for model in models.values():
        assert len(model["source_commit"]) == 40
        assert len(model["sha256"]) == 64
        assert model["license"] == "Apache-2.0"
        assert model["activation"].startswith("challenger_only")
        assert "/resolve/" + model["source_commit"] + "/" in model["url"]


def test_reasoner_fetch_rejects_path_escape(tmp_path: Path) -> None:
    module = _fetch_module()
    lock = tmp_path / "bad.json"
    lock.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "models": {
                    "bad": {
                        "filename": "../escape.gguf",
                        "url": "https://example.test/escape.gguf",
                        "size_bytes": 1,
                        "sha256": "0" * 64,
                        "source_commit": "1" * 40,
                        "license": "Apache-2.0",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    model = module.load_lock(lock)["bad"]

    with pytest.raises(ValueError, match="unsafe"):
        module.fetch_model("bad", model, root=tmp_path / "models")


def test_reasoner_lock_rejects_non_apache_artifact(tmp_path: Path) -> None:
    lock = tmp_path / "bad-license.json"
    lock.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "models": {
                    "bad": {
                        "source_commit": "1" * 40,
                        "license": "unknown",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not admitted"):
        _fetch_module().load_lock(lock)


def test_reasoner_fetch_does_not_follow_incomplete_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _fetch_module()
    model_root = tmp_path / "models"
    model_root.mkdir()
    outside = tmp_path / "outside.gguf"
    outside.write_bytes(b"preserve")
    (model_root / "safe.gguf.incomplete").symlink_to(outside)
    payload = b"x"
    spec = {
        "filename": "safe.gguf",
        "url": "https://example.test/safe.gguf",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(payload),
    )

    with pytest.raises(OSError):
        module.fetch_model("safe", spec, root=model_root)
    assert outside.read_bytes() == b"preserve"
