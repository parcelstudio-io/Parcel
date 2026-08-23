"""N27 — source/package release parity.

A wheel ships only ``src/parcel_robot/runtime_assets``; a source checkout never
reads it (``paths.parcel_roots`` puts the inferred repo root first). So drift
between the two is invisible in development and ships to the robot. At HEAD
``8473a51`` the packaged navigation config carried ``safety.max_vx: 0.45``
against source ``0.9``, ``progress_watchdog.timeout_steps: 400`` against ``200``,
``align_enter_deg: 28.0`` against ``55.0``, and omitted the ``perception:`` and
``route_memory:`` blocks entirely — while ``tests/test_runtime_assets.py`` was
green, because it only asserted those files EXIST.

These tests assert byte-parity against the canonical source and that every
default asset resolves *under* the packaged root, which is what a wheel gets.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from parcel_robot import paths as paths_mod
from parcel_robot.paths import load_packaged_manifest, packaged_assets_root, resolve_asset

REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "tools" / "sync_runtime_assets.py"
PACKAGED = packaged_assets_root()

# Pinned literal, in the tests/test_ci_gate.py house style: a shrinking ship set
# must fail loudly rather than quietly packaging less.
# 2026-08-22, card FZ-1 (scrum/20260822/task_13): 90 → 99. The ship set grew by
# the nine per-version persona snapshots under
# prompts/personalities/_frozen/<si_version>/ (3 versions × 3 personalities),
# which a wheel must carry or a packaged install cannot render any historical
# si_version at all. Moved deliberately, which is what this pin is for.
EXPECTED_ASSET_COUNT = 99

# Every asset a product entry point resolves by a repo-relative name.
DEFAULT_FILE_ASSETS = (
    "configs/robot.yaml",
    "configs/personality.yaml",
    "configs/navigation/default.yaml",
    "configs/navigation/pose.yaml",
    "configs/navigation/cities/demo_pois.yaml",
    "configs/scenes/city_block.semantics.yaml",
    "configs/perception/low_viewpoint_samples.yaml",
    "maps/neighborhood_v1.json",
    "maps/overture_places_v1.json",
    "fixtures/storefronts/manifest.yaml",
)
DEFAULT_DIR_ASSETS = ("configs/skills", "configs/navigation/models", "prompts")

DEV_ONLY_PREFIXES = (
    "configs/navigation/experiments/",
    "configs/scenes/generated/",
    "configs/reasoner/",
)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return load_packaged_manifest()


def _run_generator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )


def test_manifest_covers_every_packaged_file(manifest: dict) -> None:
    on_disk = {
        path.relative_to(PACKAGED).as_posix()
        for path in PACKAGED.rglob("*")
        if path.is_file() and path.name != "MANIFEST.json"
    }
    recorded = {entry["packaged"] for entry in manifest["assets"]}
    assert on_disk == recorded, f"unlisted={sorted(on_disk - recorded)} missing={sorted(recorded - on_disk)}"


def test_manifest_asset_count_is_the_pinned_literal(manifest: dict) -> None:
    assert manifest["count"] == EXPECTED_ASSET_COUNT
    assert len(manifest["assets"]) == EXPECTED_ASSET_COUNT


def test_every_manifest_digest_matches_the_packaged_bytes(manifest: dict) -> None:
    import hashlib

    for entry in manifest["assets"]:
        payload = (PACKAGED / entry["packaged"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"], entry["packaged"]
        assert len(payload) == entry["size"], entry["packaged"]


def test_every_mirrored_asset_is_byte_identical_to_its_source(manifest: dict) -> None:
    """The test that would have caught default.yaml and grid.yaml at HEAD."""

    drifted = [
        entry["packaged"]
        for entry in manifest["assets"]
        if entry["origin"] == "mirror"
        and (REPO / entry["source"]).read_bytes() != (PACKAGED / entry["packaged"]).read_bytes()
    ]
    assert not drifted, f"packaged bytes != source for: {drifted}"


def test_side_mirror_robot_yaml_is_byte_identical(manifest: dict) -> None:
    canonical = (REPO / "configs" / "robot.yaml").read_bytes()
    assert (PACKAGED / "configs" / "robot.yaml").read_bytes() == canonical
    for entry in manifest["side_mirrors"]:
        assert (REPO / entry["target"]).read_bytes() == (REPO / entry["source"]).read_bytes()


def test_generator_reports_no_drift() -> None:
    result = _run_generator("--check")
    assert result.returncode == 0, result.stderr


def test_generator_is_idempotent_and_zero_diff(tmp_path: Path) -> None:
    first = tmp_path / "one"
    assert _run_generator("--write", "--dest", str(first)).returncode == 0
    rendered = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()}

    committed = {p.relative_to(PACKAGED).as_posix(): p.read_bytes() for p in PACKAGED.rglob("*") if p.is_file()}
    assert rendered == committed

    # A second write into the same destination must change nothing.
    second = _run_generator("--write", "--dest", str(first))
    assert second.returncode == 0
    assert "0 written, 0 removed" in second.stdout


def test_ship_set_excludes_dev_only_and_ground_truth(manifest: dict) -> None:
    for entry in manifest["assets"]:
        packaged = entry["packaged"]
        assert not packaged.endswith(".truth.json"), packaged
        assert packaged != "configs/robot.acoustic.yaml"
        for prefix in DEV_ONLY_PREFIXES:
            assert not packaged.startswith(prefix), packaged


def test_every_default_asset_resolves_under_the_packaged_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolution must land INSIDE the packaged tree, not fall through to source.

    ``paths.parcel_roots`` appends the inferred repo root after ``PARCEL_ROOT``,
    so an asset missing from the packaged tree still resolves — against the
    checkout. Asserting ``is_relative_to`` is what makes this test load-bearing.
    """

    monkeypatch.setenv("PARCEL_ROOT", str(PACKAGED))
    paths_mod.parcel_roots.cache_clear()
    try:
        for relative in DEFAULT_FILE_ASSETS:
            resolved = resolve_asset(*Path(relative).parts, kind="file")
            assert resolved.is_relative_to(PACKAGED), f"{relative} resolved outside the wheel: {resolved}"
        for relative in DEFAULT_DIR_ASSETS:
            resolved = resolve_asset(*Path(relative).parts, kind="dir")
            assert resolved.is_relative_to(PACKAGED), f"{relative} resolved outside the wheel: {resolved}"
    finally:
        paths_mod.parcel_roots.cache_clear()


def test_effective_config_is_equal_under_source_and_packaged_roots(tmp_path: Path) -> None:
    """N27's exit criterion, measured over resolved VALUES rather than files present."""

    probe = REPO / "tools" / "release_parity_probe.py"

    def run(root: str | None) -> dict:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
        if root is not None:
            env["PARCEL_ROOT"] = root
        result = subprocess.run(
            [sys.executable, str(probe)],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            env=env,
            check=True,
        )
        return json.loads(result.stdout)

    source = run(None)
    packaged = run(str(PACKAGED))
    assert not any(str(v).startswith("ERROR:") for v in source["components"].values()), source
    assert source["components"] == packaged["components"]
    assert source["digest"] == packaged["digest"]
