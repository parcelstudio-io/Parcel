"""Config-side ratchet for the retired embodiment families.

The AST walker in ``test_authority_no_literal_drift.py`` only sees Python. The
same families also live in YAML, and the audit's "second inconsistent radius"
is a YAML value. These tests pin the config surface: what agrees with the
profile must keep agreeing, and the one known disagreement is pinned *as a
disagreement* so nobody silently widens or "fixes" it without the paired run
the value-change protocol requires.
"""

from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROBOT_CONFIGS = (
    REPO_ROOT / "configs" / "robot.yaml",
    REPO_ROOT / "src" / "parcel_robot" / "config" / "robot.yaml",
)
NAV_DEFAULT = REPO_ROOT / "configs" / "navigation" / "default.yaml"
GRID_MODEL = REPO_ROOT / "configs" / "navigation" / "models" / "grid.yaml"


def _load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", ROBOT_CONFIGS, ids=lambda p: p.as_posix()[-40:])
def test_robot_config_ttc_radius_is_the_pinned_f_robot_radius_drift(
    path: pathlib.Path,
) -> None:
    """0.35 vs the profile's 0.32 — the audit's second inconsistent radius.

    This test asserts the drift *still exists at exactly 0.35*. It is not an
    endorsement: it is the ratchet. Resolving it is a value change owned by
    whoever owns ``runtime.py``'s TTC gate, and it needs a paired-seed run on a
    harness that actually builds that gate (``walk_with_me`` /
    ``voice_nav_e2e``, not NAV_INSTRUCT). When they resolve it, this test
    changes in the same commit.
    """

    ttc = _load(path)["safety"]["time_to_collision"]
    assert ttc["robot_radius_m"] == 0.35
    assert ttc["robot_radius_m"] != DEFAULT_ROBOT_PROFILE.footprint_radius_m


@pytest.mark.parametrize("path", ROBOT_CONFIGS, ids=lambda p: p.as_posix()[-40:])
def test_robot_config_safety_bands_agree_with_the_envelope_authority(
    path: pathlib.Path,
) -> None:
    safety = _load(path)["safety"]
    assert safety["obstacle_slow_m"] == DEFAULT_SAFETY_ENVELOPE.obstacle_comfort_band_m
    assert safety["person_slow_m"] <= DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m


@pytest.mark.parametrize("path", ROBOT_CONFIGS, ids=lambda p: p.as_posix()[-40:])
def test_robot_config_decel_matches_the_profile_it_is_the_provenance_for(
    path: pathlib.Path,
) -> None:
    """``RobotProfile.decel_max_mps2`` was derived from this key; keep them tied."""

    shaping = _load(path)["motion"]["smoothing"]
    assert shaping["linear_decel"] == DEFAULT_ROBOT_PROFILE.decel_max_mps2


def test_the_two_robot_configs_are_still_byte_identical() -> None:
    """``configs/robot.yaml`` and the packaged copy must not fork."""

    first, second = (path.read_bytes() for path in ROBOT_CONFIGS)
    assert first == second


def test_speed_regime_reference_matches_the_configs_it_was_transcribed_from() -> None:
    """If a speed raise edits the YAML, the authority's reference must follow."""

    from parcel_robot.authority import DEFAULT_SPEED_REGIME

    controller = _load(GRID_MODEL)["controller"]
    nav_safety = _load(NAV_DEFAULT)["safety"]
    cruise = DEFAULT_SPEED_REGIME.cruise
    assert cruise.vx_mps == controller["cruise_vx"]
    assert cruise.vyaw_radps == controller["max_yaw_rate"]
    assert cruise.accel_mps2 == controller["max_linear_accel"]
    assert cruise.yaw_accel_radps2 == controller["max_yaw_accel"]
    assert cruise.vy_mps == nav_safety["max_vy"]
    assert DEFAULT_SPEED_REGIME.search.vyaw_radps == (
        _load(NAV_DEFAULT)["semantic_search"]["yaw_rate"]
    )
    assert DEFAULT_SPEED_REGIME.recover.vx_mps == abs(controller["recovery_reverse_vx"])
    assert DEFAULT_SPEED_REGIME.recover.vyaw_radps == controller["recovery_yaw_rate"]


def test_the_nav_clamp_is_not_below_the_cruise_regime_it_bounds() -> None:
    """The 2026-08-05 finding, expressed as a standing assertion.

    ``configs/navigation/default.yaml safety.max_vx`` silently capped clear-path
    speed below ``grid.yaml cruise_vx`` for a whole day. The elementwise-min
    arbitration rule makes that class of miss a one-line check.
    """

    from parcel_robot.authority import DEFAULT_SPEED_REGIME

    assert _load(NAV_DEFAULT)["safety"]["max_vx"] >= DEFAULT_SPEED_REGIME.cruise.vx_mps
