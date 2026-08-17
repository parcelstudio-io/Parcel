"""Asset packaging resolution for K7 (headless/CI without divergent fallback)."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_package_fallback_robot_yaml_is_byte_identical_to_canonical() -> None:
    """The in-package fallback is a declared side mirror, not a licensed fork.

    This assertion replaces a key-by-key "speech contract" check (N27). That
    check asserted only that a few keys were absent from the fallback, which
    encoded *permission* for the third copy to diverge — and it was vacuous
    besides, because those keys had been removed from canonical on 2026-08-04.
    All five console scripts read this copy in a wheel without going through
    ``parcel_robot.paths``, so it must be byte-equal or the released artifact
    runs a different configuration than the checkout it was cut from.
    """

    canonical = (REPO / "configs" / "robot.yaml").read_bytes()
    fallback = (REPO / "src" / "parcel_robot" / "config" / "robot.yaml").read_bytes()
    assert fallback == canonical

    manifest = json.loads(
        (packaged_assets_root() / "MANIFEST.json").read_text(encoding="utf-8")
    )
    mirrors = {entry["target"]: entry["source"] for entry in manifest["side_mirrors"]}
    assert mirrors["src/parcel_robot/config/robot.yaml"] == "configs/robot.yaml", (
        "the fallback must stay under the release-parity manifest, not hand-synced outside it"
    )


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
