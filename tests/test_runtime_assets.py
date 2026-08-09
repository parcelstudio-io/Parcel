"""Asset packaging resolution for K7 (headless/CI without divergent fallback)."""

from __future__ import annotations

from pathlib import Path

import yaml

from parcel_robot.config import ConfigStore
from parcel_robot.paths import (
    packaged_assets_root,
    parcel_roots,
    resolve_config_yaml,
    resolve_navigation_config,
    resolve_prompts_root,
    resolve_skills_root,
)

REPO = Path(__file__).resolve().parents[1]


def test_packaged_runtime_assets_contain_required_trees() -> None:
    root = packaged_assets_root()
    assert (root / "configs" / "skills" / "catalog.yaml").is_file()
    assert (root / "configs" / "navigation" / "default.yaml").is_file()
    assert (root / "configs" / "robot.yaml").is_file()
    assert (root / "prompts" / "system" / "core.md").is_file()


def test_resolve_helpers_find_canonical_checkout_assets() -> None:
    roots = parcel_roots()
    assert any(r == REPO.resolve() or (r / "configs").is_dir() for r in roots)
    assert resolve_skills_root().is_dir()
    assert resolve_prompts_root().is_dir()
    assert resolve_navigation_config().is_file()
    assert resolve_config_yaml().is_file()


def test_package_fallback_robot_yaml_matches_canonical_speech_contract() -> None:
    canonical = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))
    fallback = yaml.safe_load(
        (REPO / "src" / "parcel_robot" / "config" / "robot.yaml").read_text(encoding="utf-8")
    )
    assert "navigation" in fallback
    assert "fish_streaming" not in (fallback.get("speech") or {})
    assert "barge_in" not in (fallback.get("speech") or {})
    assert fallback["speech"]["mode"] == canonical["speech"]["mode"]
    assert "endpointing" in fallback["speech"]


def test_config_store_skills_and_prompts_resolve_via_paths(tmp_path: Path, monkeypatch) -> None:
    # Point PARCEL_ROOT at packaged assets only and hide the real repo root by
    # using the packaged tree as the sole env root.
    packaged = packaged_assets_root()
    monkeypatch.setenv("PARCEL_ROOT", str(packaged))
    from parcel_robot import paths as paths_mod

    paths_mod.parcel_roots.cache_clear()
    try:
        cfg = tmp_path / "robot.yaml"
        cfg.write_text(
            "skills:\n  root: configs/skills\nagent:\n  prompts_root: prompts\n",
            encoding="utf-8",
        )
        store = ConfigStore(cfg)
        assert store.skills_root() == (packaged / "configs" / "skills").resolve()
        assert store.prompts_root() == (packaged / "prompts").resolve()
    finally:
        paths_mod.parcel_roots.cache_clear()
