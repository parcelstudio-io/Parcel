"""Card DR-2 — the cheap half of the degraded-pose arm, at commit tier.

``scripts/ci_gate.py``'s own docstring for :func:`evaluate_pose_drift_arms`
declares the split this module implements: the *arms* are seven full passes over
the 61-cell long-travel substrate and belong to the nightly tier, and what the
commit tier gets instead is everything about them that can be checked in
seconds — the seed derivation, the band algebra, the record shape, the flag-off
byte path, the ``--freeze`` refusal, and the floor arithmetic.

Every property here is paired with a **seeded-failure companion** that breaks
the property on purpose and asserts the check notices, because a green property
test that cannot go red is decoration. The pairs are named
``..._can_fail`` / ``..._reddens_...`` next to the property they falsify.

The last class is the card's required nightly self-test: a seeded drift-arm
failure driven through ``ci_gate``'s real checkers and asserted to flip the
nightly gate red.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evals.nav_instruct import run_drift_arms
from evals.nav_instruct.drift_cells import generate_drift_cells
from evals.nav_instruct.run_drift_arms import (
    DRIFT_ARMS,
    DRIFT_FLOORS,
    DRIFT_FLOORS_PROVENANCE,
    FLOOR_QUANTUM_EPISODES,
    check_floors,
    derive_floors,
    hard_invariants,
    ladder_monotone,
    non_vacuity,
)
from evals.nav_instruct.runner import (
    DIVERGENCE_BAND_HIGH_FACTOR,
    DIVERGENCE_BAND_LOW_FACTOR,
    DIVERGENCE_BAND_MIN_TRAVEL_M,
    DIVERGENCE_REFERENCE_DISTANCE_M,
    DIVERGENCE_REFERENCE_PCT,
    DIVERGENCE_REFERENCE_SEEDS,
    POSE_LOST_HOLD_NOTE,
    NavInstructRunner,
    aggregate_pose_drift,
    divergence_band_pct,
    episode_pose_seed,
    pose_drift_record,
)
from parcel_robot.pose import Frame, PoseHealth, provider_from_config
from parcel_robot.simulation.headless_city import HeadlessCityQualityHarness, _nav_observation

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "evals" / "nav_instruct" / "results"

#: The three noise tiers DR1_STATUS §6 published a distribution for. The
#: ``*_lost`` and ``*_reanchoring`` variants share their base's noise block
#: verbatim (DR1_STATUS §2 pins the equality), so re-sweeping them would
#: re-measure the same numbers.
LADDER = ("calibrated_go2", "go2_aggressive", "go2_degraded")

#: DR1_STATUS §6's published straight-line table, transcribed here ONLY so the
#: sweep below can be checked against the document that motivated the band. The
#: sweep is the measurement; this is the corroboration.
DR1_PUBLISHED_PCT: dict[str, dict[str, float]] = {
    "calibrated_go2": {"mean": 3.42, "median": 2.89, "max": 11.44},
    "go2_aggressive": {"mean": 6.83, "median": 5.76, "max": 22.73},
    "go2_degraded": {"mean": 14.21, "median": 12.43, "max": 46.95},
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sweep(profile: str, seeds: range) -> list[float]:
    """DR1_STATUS §6's instrument: a straight run at the harness cruise.

    0.1 m per 0.1 s tick is the 1 m/s cruise DR-1 measured on, and
    :data:`DIVERGENCE_REFERENCE_DISTANCE_M` metres of it is the reference
    length. Returns divergence as a percentage of distance travelled.
    """

    step = 0.1
    ticks = round(DIVERGENCE_REFERENCE_DISTANCE_M / step)
    out: list[float] = []
    for seed in seeds:
        provider = provider_from_config(profile=profile)
        provider.params = replace(provider.params, seed=seed)
        provider.reset()
        x = 0.0
        provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=0.0)
        for tick in range(ticks):
            x += step
            provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=(tick + 1) * 0.1)
        out.append(100.0 * provider.odom_error_m / provider.travelled_m)
    return out


def _arm_row(
    profile: str | None,
    *,
    n: int = 61,
    sr: float = 0.5,
    collisions: int = 0,
    false_arrival: int = 0,
    drift: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A synthetic Stage-A arm row, shaped exactly like :func:`run_arm`'s."""

    return {
        "profile": profile,
        "n": n,
        "sr": sr,
        "collision_total": collisions,
        "false_arrival": false_arrival,
        "path_m_total": 6.0 * n,
        "path_m_mean": 6.0,
        "pose_drift": drift,
    }


def _drift_block(
    profile: str,
    *,
    n: int = 61,
    banded: int = 30,
    in_band: int | None = None,
    seeds_distinct: int | None = None,
    divergence_m_mean: float = 0.4,
    divergence_pct_mean: float = 3.0,
    lost: int = 0,
    recovered: int | None = None,
    reanchors: int = 0,
) -> dict[str, Any]:
    """A synthetic arm-level ``pose_drift`` block, shaped like the aggregate's."""

    return {
        "profile": profile,
        "episodes": n,
        "episodes_banded": banded,
        "episodes_in_band": banded if in_band is None else in_band,
        "band_pct": list(divergence_band_pct(profile)),
        "divergence_m_mean": divergence_m_mean,
        "divergence_pct_mean": divergence_pct_mean,
        "divergence_pct_min": divergence_pct_mean / 2.0,
        "divergence_pct_max": divergence_pct_mean * 2.0,
        "episodes_with_lost": lost,
        "episodes_lost_recovered": lost if recovered is None else recovered,
        "reanchor_events_total": reanchors,
        "seeds_distinct": n if seeds_distinct is None else seeds_distinct,
    }


def _clean_ladder_rows() -> list[dict[str, Any]]:
    """One green row per pre-registered arm — the shape a passing Stage B has."""

    rows = [_arm_row(None, drift=None)]
    for index, profile in enumerate(DRIFT_ARMS[1:], start=1):
        rows.append(
            _arm_row(
                profile,
                sr=0.2,
                drift=_drift_block(
                    profile,
                    divergence_pct_mean=1.0 + index,
                    lost=5 if profile.endswith("_lost") else 0,
                    reanchors=9 if profile.endswith("_reanchoring") else 0,
                ),
            )
        )
    # The ladder must be monotone in the arm mean: give the three tiers means
    # that increase, independent of the enumeration order above.
    by_profile = {row["profile"]: row for row in rows}
    for index, profile in enumerate(LADDER, start=1):
        by_profile[profile]["pose_drift"]["divergence_pct_mean"] = float(index)
    return rows


def _payload(rows: list[dict[str, Any]], *, stage: str = "b") -> dict[str, Any]:
    return {
        "stage": stage,
        "n": 61,
        "arms": rows,
        "problems": [],
        "passed": True,
    }


# ---------------------------------------------------------------------------
# 1. Seed derivation — the DR-1 handoff warning, made structural
# ---------------------------------------------------------------------------


class TestSeedDerivation:
    def test_the_seed_is_a_pure_function_of_the_episode_id(self) -> None:
        assert episode_pose_seed(20260807, "nav-drift-a") == episode_pose_seed(
            20260807, "nav-drift-a"
        )
        assert episode_pose_seed(20260807, "nav-drift-a") != episode_pose_seed(
            20260807, "nav-drift-b"
        )

    def test_every_episode_of_the_real_substrate_draws_its_own_seed(self) -> None:
        """n episodes on one seed would be a sample of size one (DR1_STATUS §6)."""

        episodes = generate_drift_cells()
        seeds = {episode_pose_seed(20260807, ep.episode_id) for ep in episodes}
        assert len(seeds) == len(episodes) == 61

    def test_slicing_or_reordering_the_set_re_rolls_nothing(self) -> None:
        """``--limit`` must not silently change another episode's draw."""

        episodes = generate_drift_cells()
        full = {ep.episode_id: episode_pose_seed(7, ep.episode_id) for ep in episodes}
        for ep in list(reversed(episodes))[:10]:
            assert episode_pose_seed(7, ep.episode_id) == full[ep.episode_id]

    def test_the_ladder_shares_common_random_numbers(self) -> None:
        """Every profile ships seed 20260807, so an episode pairs with itself."""

        seeds = {
            provider_from_config(profile=profile).params.seed for profile in LADDER
        }
        assert seeds == {20260807}
        one = "nav-drift-object_goal-00-1d1e67a2"
        assert len({episode_pose_seed(seed, one) for seed in seeds}) == 1

    def test_the_seed_stays_inside_the_32_bit_window(self) -> None:
        for ep in generate_drift_cells():
            seed = episode_pose_seed(20260807, ep.episode_id)
            assert 0 <= seed <= 0xFFFFFFFF

    def test_a_varied_seed_really_moves_the_measurement(self) -> None:
        """Non-vacuity for the variation itself: distinct seeds, distinct drift."""

        episodes = generate_drift_cells()[:6]
        errors = set()
        for ep in episodes:
            provider = provider_from_config(profile="go2_degraded")
            provider.params = replace(
                provider.params, seed=episode_pose_seed(provider.params.seed, ep.episode_id)
            )
            provider.reset()
            x = 0.0
            provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=0.0)
            for tick in range(100):
                x += 0.1
                provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=(tick + 1) * 0.1)
            errors.add(round(provider.odom_error_m, 9))
        assert len(errors) == len(episodes)

    def test_the_distinct_seed_check_can_fail(self) -> None:
        """SEEDED FAILURE — the fixed-seed trap the AUDIT flagged, caught."""

        row = _arm_row(
            "go2_degraded",
            drift=_drift_block("go2_degraded", seeds_distinct=1),
        )
        problems = non_vacuity(row)
        assert any("per-episode seed did not vary" in problem for problem in problems)

    def test_the_fixed_shipped_seed_is_the_trap_dr1_measured(self) -> None:
        """The 25.8-vs-14.2 finding, re-measured rather than quoted."""

        fixed = _sweep("go2_degraded", range(20260807, 20260808))[0]
        distribution = _sweep("go2_degraded", range(DIVERGENCE_REFERENCE_SEEDS))
        mean = sum(distribution) / len(distribution)
        assert fixed > 1.5 * mean, (
            "the shipped seed no longer sits deep in the tail; the per-episode "
            f"variation argument needs re-deriving (fixed={fixed:.2f} mean={mean:.2f})"
        )


# ---------------------------------------------------------------------------
# 2. Band algebra — sized off the tail, never off the mean
# ---------------------------------------------------------------------------


class TestBandAlgebra:
    def test_the_band_is_the_reference_envelope_scaled_by_the_pinned_factors(
        self,
    ) -> None:
        for profile, (low, high) in DIVERGENCE_REFERENCE_PCT.items():
            assert divergence_band_pct(profile) == (
                low * DIVERGENCE_BAND_LOW_FACTOR,
                high * DIVERGENCE_BAND_HIGH_FACTOR,
            )

    def test_an_unknown_profile_fails_loudly(self) -> None:
        with pytest.raises(ValueError, match="no pre-registered divergence reference"):
            divergence_band_pct("go2_imaginary")

    def test_every_arm_the_card_registers_has_a_band(self) -> None:
        for profile in DRIFT_ARMS:
            if profile is not None:
                divergence_band_pct(profile)

    @pytest.mark.parametrize("profile", LADDER)
    def test_the_reference_distribution_reproduces_a_fresh_sweep(
        self, profile: str
    ) -> None:
        """The constants are MEASURED here, not transcribed from a status doc."""

        values = sorted(_sweep(profile, range(DIVERGENCE_REFERENCE_SEEDS)))
        low, high = DIVERGENCE_REFERENCE_PCT[profile]
        # Pinned to 2 decimals: the constant is the measured extreme rounded.
        assert round(min(values), 2) == pytest.approx(low, abs=5e-3)
        assert round(max(values), 2) == pytest.approx(high, abs=5e-3)
        published = DR1_PUBLISHED_PCT[profile]
        mean = sum(values) / len(values)
        median = 0.5 * (values[len(values) // 2 - 1] + values[len(values) // 2])
        assert mean == pytest.approx(published["mean"], abs=0.01)
        assert median == pytest.approx(published["median"], abs=0.01)
        assert max(values) == pytest.approx(published["max"], abs=0.01)

    @pytest.mark.parametrize("profile", LADDER)
    def test_the_band_clears_the_tail_that_a_mean_sized_band_would_red_on(
        self, profile: str
    ) -> None:
        """DR1_STATUS §6's binding warning, asserted as a property of the band.

        A band written against the 60-seed MEAN reds on the profile's own p90
        and on its own shipped seed. The pinned band must contain both, or the
        nightly non-vacuity gate is a coin flip.
        """

        values = sorted(_sweep(profile, range(DIVERGENCE_REFERENCE_SEEDS)))
        mean = sum(values) / len(values)
        p90 = values[int(0.9 * len(values))]
        low, high = divergence_band_pct(profile)
        assert p90 > mean, "the p90 is the tail; if it is not above the mean, re-derive"
        assert low <= p90 <= high
        assert low <= max(values) <= high
        assert high > mean, "a mean-sized ceiling is exactly the spurious-red trap"

    def test_a_truth_pose_episode_falls_out_of_every_band(self) -> None:
        """The band's falsifiable claim: a row measured with the injector OFF."""

        for profile in DIVERGENCE_REFERENCE_PCT:
            low, _high = divergence_band_pct(profile)
            assert low > 0.0

    def test_the_band_check_can_fail(self) -> None:
        """SEEDED FAILURE — an out-of-envelope episode reddens non-vacuity."""

        row = _arm_row(
            "calibrated_go2",
            drift=_drift_block("calibrated_go2", banded=30, in_band=29),
        )
        problems = non_vacuity(row)
        assert any("banded episodes inside" in problem for problem in problems)

    def test_a_zero_divergence_arm_reddens(self) -> None:
        """SEEDED FAILURE — an arm that silently ran on truth is not green."""

        row = _arm_row(
            "calibrated_go2",
            drift=_drift_block("calibrated_go2", divergence_m_mean=0.0),
        )
        assert any("divergence is 0" in problem for problem in non_vacuity(row))


# ---------------------------------------------------------------------------
# 3. Record shape — what a persisted row is obliged to carry
# ---------------------------------------------------------------------------


class TestRecordShape:
    def _driven(self, profile: str, *, metres: float, stamp_step: float = 0.1):
        provider = provider_from_config(profile=profile)
        provider.reset()
        x = 0.0
        provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=0.0)
        for tick in range(round(metres / 0.1)):
            x += 0.1
            provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=(tick + 1) * stamp_step)
        return provider

    def test_no_profile_means_no_record(self) -> None:
        provider = self._driven("calibrated_go2", metres=12.0)
        assert pose_drift_record(provider, profile=None, seed=1) is None
        assert pose_drift_record(None, profile="calibrated_go2", seed=1) is None

    def test_a_record_carries_every_field_the_card_requires(self) -> None:
        provider = self._driven("go2_degraded", metres=12.0)
        record = pose_drift_record(provider, profile="go2_degraded", seed=99)
        assert record is not None
        for key in (
            "profile",
            "seed",
            "distance_m",
            "divergence_m",
            "divergence_pct",
            "yaw_divergence_rad",
            "slip_events",
            "band_pct",
            "band_applied",
            "in_band",
        ):
            assert key in record, key
        assert record["seed"] == 99
        assert record["distance_m"] == pytest.approx(12.0, abs=1e-6)
        assert record["divergence_pct"] == pytest.approx(
            100.0 * record["divergence_m"] / record["distance_m"]
        )

    def test_a_short_episode_records_metres_but_is_not_banded(self) -> None:
        """Below half the reference length a percentage is not comparable."""

        provider = self._driven("calibrated_go2", metres=1.0)
        record = pose_drift_record(provider, profile="calibrated_go2", seed=1)
        assert record is not None
        assert record["distance_m"] < DIVERGENCE_BAND_MIN_TRAVEL_M
        assert record["band_applied"] is False
        assert record["in_band"] is False
        assert record["divergence_m"] > 0.0

    def test_the_minimum_travel_is_half_the_reference_length(self) -> None:
        assert DIVERGENCE_BAND_MIN_TRAVEL_M == DIVERGENCE_REFERENCE_DISTANCE_M / 2.0

    def test_the_aggregate_counts_in_band_against_banded_not_against_all(self) -> None:
        rows = [
            {"profile": "calibrated_go2", "seed": i, "distance_m": 10.0,
             "divergence_m": 0.3, "divergence_pct": 3.0, "band_applied": True,
             "in_band": True, "band_pct": [0.1, 22.9], "slip_events": 0}
            for i in range(4)
        ]
        rows.append(
            {"profile": "calibrated_go2", "seed": 99, "distance_m": 1.0,
             "divergence_m": 0.05, "divergence_pct": 5.0, "band_applied": False,
             "in_band": False, "band_pct": [0.1, 22.9], "slip_events": 0}
        )
        summary = aggregate_pose_drift(
            [SimpleNamespace(pose_drift=row) for row in rows]  # type: ignore[list-item]
        )
        assert summary is not None
        assert summary["episodes"] == 5
        assert summary["episodes_banded"] == 4
        assert summary["episodes_in_band"] == 4
        assert summary["seeds_distinct"] == 5

    def test_one_out_of_envelope_row_cannot_hide_behind_a_mean(self) -> None:
        """SEEDED FAILURE — flip one row's verdict; the count must move."""

        rows = [
            {"profile": "calibrated_go2", "seed": i, "distance_m": 10.0,
             "divergence_m": 0.3, "divergence_pct": 3.0, "band_applied": True,
             "in_band": i != 0, "band_pct": [0.1, 22.9], "slip_events": 0}
            for i in range(4)
        ]
        summary = aggregate_pose_drift(
            [SimpleNamespace(pose_drift=row) for row in rows]  # type: ignore[list-item]
        )
        assert summary is not None
        assert summary["episodes_in_band"] == 3 < summary["episodes_banded"]

    def test_the_aggregate_is_none_without_any_drift_row(self) -> None:
        assert aggregate_pose_drift([SimpleNamespace(pose_drift=None)]) is None  # type: ignore[list-item]

    def test_the_observer_sees_a_scheduled_window_hold_and_recover(self) -> None:
        from evals.nav_instruct.runner import _PoseDriftObserver

        provider = provider_from_config(profile="calibrated_go2_lost")
        provider.reset()
        observer = _PoseDriftObserver(provider)
        x = 0.0
        for tick in range(120):
            provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=tick * 0.1)
            observer.sample((x, 0.0), tick * 0.1)
            x += 0.1
        # DR-1's derived window is (start 4.0 s, duration 3.0 s) = 30 ticks.
        assert observer.lost_ticks == 30
        assert observer.recovered_t_s is not None
        assert observer.first_lost_t_s == pytest.approx(4.0, abs=1e-6)
        record = pose_drift_record(
            provider, profile="calibrated_go2_lost", seed=1, observer=observer
        )
        assert record is not None
        assert record["lost_recovered"] is True

    def test_the_observer_counts_map_reanchor_jumps(self) -> None:
        from evals.nav_instruct.runner import _PoseDriftObserver

        provider = provider_from_config(profile="calibrated_go2_reanchoring")
        provider.reset()
        observer = _PoseDriftObserver(provider)
        x = 0.0
        for tick in range(300):
            provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=tick * 0.1)
            observer.sample((x, 0.0), tick * 0.1)
            x += 0.1
        # 30 s at the yaml's 5.0 s correction interval.
        assert observer.reanchor_events >= 5

    def test_a_truth_passthrough_profile_never_reanchors(self) -> None:
        """Scoping proof: asserting ``> 0`` off the map-correction profile would
        be asserting a bug, which is why ``non_vacuity`` scopes it."""

        from evals.nav_instruct.runner import _PoseDriftObserver

        provider = provider_from_config(profile="calibrated_go2")
        provider.reset()
        observer = _PoseDriftObserver(provider)
        x = 0.0
        for tick in range(300):
            provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=tick * 0.1)
            observer.sample((x, 0.0), tick * 0.1)
            x += 0.1
        assert observer.reanchor_events == 0
        assert provider.get_pose(Frame.MAP).health is PoseHealth.HEALTHY

    def test_the_lost_and_reanchor_checks_can_fail(self) -> None:
        """SEEDED FAILURE — both scoped metrics, broken on purpose."""

        never_held = _arm_row(
            "calibrated_go2_lost", drift=_drift_block("calibrated_go2_lost", lost=0)
        )
        assert any("never held" in p for p in non_vacuity(never_held))
        never_recovered = _arm_row(
            "go2_degraded_lost",
            drift=_drift_block("go2_degraded_lost", lost=5, recovered=4),
        )
        assert any("LOST episodes recovered" in p for p in non_vacuity(never_recovered))
        never_anchored = _arm_row(
            "calibrated_go2_reanchoring",
            drift=_drift_block("calibrated_go2_reanchoring", reanchors=0),
        )
        assert any("re-anchor event" in p for p in non_vacuity(never_anchored))

    def test_the_truth_control_must_record_no_drift_at_all(self) -> None:
        assert non_vacuity(_arm_row(None, drift=None)) == []
        polluted = _arm_row(None, drift=_drift_block("calibrated_go2"))
        assert any("truth control recorded" in p for p in non_vacuity(polluted))


# ---------------------------------------------------------------------------
# 4. Flag-off byte path — naming no profile changes nothing
# ---------------------------------------------------------------------------


class TestFlagOffBytePath:
    def test_no_profile_builds_the_stock_harness(self) -> None:
        runner = NavInstructRunner()
        assert type(runner.harness) is HeadlessCityQualityHarness
        assert runner.harness.pose_profile is None
        assert runner.pose_drift_profile is None

    def test_a_profile_builds_the_seeded_subclass(self) -> None:
        from evals.nav_instruct.runner import _DriftSeededHarness

        runner = NavInstructRunner(pose_drift_profile="go2_degraded")
        assert isinstance(runner.harness, _DriftSeededHarness)
        assert runner.harness.pose_profile == "go2_degraded"

    def test_no_profile_yields_no_provider(self) -> None:
        runner = NavInstructRunner()
        assert runner._new_pose_provider() == (None, None)

    def test_a_mistyped_profile_fails_at_construction_not_at_episode_one(self) -> None:
        """A typo must never quietly measure the nominal tier as 'degraded'."""

        with pytest.raises((KeyError, ValueError)):
            NavInstructRunner(pose_drift_profile="calibrated_go3")

    def test_the_observation_is_byte_identical_without_a_provider(self) -> None:
        """The ONLY new argument on the truth path, proved inert."""

        runner = NavInstructRunner()
        episode = generate_drift_cells()[0]
        runner.world.reset(robot=episode.start_pose, restore_semantics=True)
        observation = runner.world.observe()
        kwargs = {
            "measured_velocity": runner.world.command,
            "stop_confirmed": runner.world.stopped,
            "settled_linear_speed_mps": runner.harness._settled_linear_speed_mps,
            "settled_yaw_speed_rad_s": runner.harness._settled_yaw_speed_rad_s,
        }
        without = _nav_observation(observation, **kwargs)
        with_none = _nav_observation(observation, pose_provider=None, **kwargs)
        assert with_none.position == without.position
        assert with_none.heading_deg == without.heading_deg
        assert sorted(with_none.extras) == sorted(without.extras)
        assert with_none.extras["pose_provider"] is None
        assert without.extras["pose_provider"] is None

    def test_a_truth_pose_observation_is_healthy_so_the_hold_can_never_fire(
        self,
    ) -> None:
        """``pipeline._pose_lost_hold`` needs a LOST MAP pose; ``None`` cannot
        produce one, which is what makes the runner's new note guard inert."""

        from parcel_robot.pose import observation_pose

        runner = NavInstructRunner()
        episode = generate_drift_cells()[0]
        runner.world.reset(robot=episode.start_pose, restore_semantics=True)
        observation = runner.world.observe()
        nav = _nav_observation(
            observation,
            measured_velocity=runner.world.command,
            stop_confirmed=runner.world.stopped,
            settled_linear_speed_mps=runner.harness._settled_linear_speed_mps,
            settled_yaw_speed_rad_s=runner.harness._settled_yaw_speed_rad_s,
            pose_provider=None,
        )
        assert observation_pose(nav, Frame.MAP).health is PoseHealth.HEALTHY

    def test_a_flag_off_row_carries_no_drift_keys(self) -> None:
        runner = NavInstructRunner(max_steps=30, mode="candidate")
        result = runner.run_episode(generate_drift_cells()[0])
        payload = result.as_dict()
        assert "pose_drift_profile" not in payload
        assert "pose_drift" not in payload
        assert result.pose_drift is None

    def test_a_flag_on_row_names_its_arm_and_its_seed(self) -> None:
        episode = generate_drift_cells()[0]
        runner = NavInstructRunner(
            max_steps=30, mode="candidate", pose_drift_profile="go2_degraded"
        )
        result = runner.run_episode(episode)
        payload = result.as_dict()
        assert payload["pose_drift_profile"] == "go2_degraded"
        assert payload["pose_drift"]["seed"] == episode_pose_seed(
            20260807, episode.episode_id
        )

    def test_the_pose_lost_note_guard_is_inert_on_the_truth_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DIGEST-LEVEL flag-off proof for the one existing line DR-2 changed.

        The runner's terminal condition gained ``and note != POSE_LOST_HOLD_NOTE``.
        Rebinding that constant to a note no command can ever carry restores the
        pre-DR-2 condition **exactly**, so if the added conjunct did anything on
        a truth-pose run the two payload digests would differ.
        """

        episode = generate_drift_cells()[0]

        def digest() -> str:
            runner = NavInstructRunner(max_steps=60, mode="candidate")
            payload = runner.run_episode(episode).as_dict()
            return hashlib.sha256(
                json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()

        with_guard = digest()
        monkeypatch.setattr(
            "evals.nav_instruct.runner.POSE_LOST_HOLD_NOTE",
            "\x00-a-note-no-command-can-carry",
        )
        without_guard = digest()
        assert with_guard == without_guard

    def test_the_guard_note_is_the_pipeline_s_own_note(self) -> None:
        source = (
            REPO / "src" / "parcel_robot" / "navigation" / "pipeline.py"
        ).read_text(encoding="utf-8")
        assert f'note="{POSE_LOST_HOLD_NOTE}"' in source


# ---------------------------------------------------------------------------
# 5. --freeze refusal
# ---------------------------------------------------------------------------


class TestFreezeRefusal:
    def test_freeze_refuses_a_pose_drift_profile(self, capsys) -> None:
        from evals.nav_instruct.run_nav_instruct_v1 import main

        with pytest.raises(SystemExit) as excinfo:
            main(["--freeze", "--mode", "baseline", "--pose-drift-profile", "go2_degraded"])
        assert excinfo.value.code == 2
        assert "refuses a degraded-pose run" in capsys.readouterr().err

    def test_freeze_refuses_the_additive_drift_substrate(self, capsys) -> None:
        from evals.nav_instruct.run_nav_instruct_v1 import main

        with pytest.raises(SystemExit) as excinfo:
            main(["--freeze", "--mode", "baseline", "--drift-cells"])
        assert excinfo.value.code == 2
        assert "refuses the additive" in capsys.readouterr().err

    def test_an_unregistered_profile_is_refused_by_the_cli(self, capsys) -> None:
        from evals.nav_instruct.run_nav_instruct_v1 import main

        with pytest.raises(SystemExit):
            main(["--pose-drift-profile", "go2_imaginary"])
        assert "invalid choice" in capsys.readouterr().err

    def test_the_cli_offers_exactly_the_registered_profiles(self) -> None:
        from evals.nav_instruct.run_nav_instruct_v1 import DIVERGENCE_REFERENCE_PCT as cli

        assert set(cli) == set(DIVERGENCE_REFERENCE_PCT)

    def test_the_persisted_report_header_names_the_arm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: the report used to be written BEFORE the drift stamp.

        Every episode row named the arm; the report header did not, because the
        stamp landed after ``report_path.write_text`` and was only flushed again
        on the ``--refreeze-provenance`` path. Measured on
        ``nav-instruct-v1-candidate-v4d-go2_degraded-20260812T055104Z.json``.
        """

        import evals.nav_instruct.run_nav_instruct_v1 as cli

        monkeypatch.setattr(cli, "LEDGER", tmp_path / "ledger.jsonl")
        assert (
            cli.main(
                [
                    "--drift-cells",
                    "--mode", "candidate",
                    "--limit", "1",
                    "--max-steps", "5",
                    "--pose-drift-profile", "calibrated_go2",
                    "--out", str(tmp_path),
                ]
            )
            == 0
        )
        report = json.loads(
            next(
                path
                for path in tmp_path.glob("nav-instruct-v1-candidate-v4d-*.json")
            ).read_text(encoding="utf-8")
        )
        assert report["pose_drift_profile"] == "calibrated_go2"
        assert report["baseline_version"] == "v4d"
        assert report["episodes"][0]["pose_drift"]["profile"] == "calibrated_go2"
        ledger = json.loads((tmp_path / "ledger.jsonl").read_text(encoding="utf-8"))
        assert ledger["frozen_baseline"] is False
        assert ledger["pose_drift_profile"] == "calibrated_go2"
        assert ledger["episode_set"] == "v4d"


# ---------------------------------------------------------------------------
# 6. Floor arithmetic — mechanical, total, no discretion
# ---------------------------------------------------------------------------


class TestFloorProtocol:
    def test_the_floor_is_the_measured_value_minus_one_episode_quantum(self) -> None:
        rows = [_arm_row("calibrated_go2", n=61, sr=0.25)]
        floors = derive_floors(rows)
        assert floors["calibrated_go2"]["sr"] == pytest.approx(0.25 - 1 / 61)
        assert FLOOR_QUANTUM_EPISODES == 1

    def test_the_floor_never_goes_negative(self) -> None:
        floors = derive_floors([_arm_row("go2_degraded", n=61, sr=0.0)])
        assert floors["go2_degraded"]["sr"] == 0.0

    def test_the_truth_control_carries_no_floor(self) -> None:
        assert derive_floors([_arm_row(None, sr=0.9)]) == {}

    def test_an_arm_exactly_at_its_floor_passes(self, monkeypatch) -> None:
        monkeypatch.setattr(run_drift_arms, "DRIFT_FLOORS", {"x": {"sr": 0.25}})
        assert check_floors([_arm_row("x", sr=0.25)]) == []

    def test_check_floors_can_fail(self, monkeypatch) -> None:
        """SEEDED FAILURE — one episode below the floor reddens Stage B."""

        monkeypatch.setattr(run_drift_arms, "DRIFT_FLOORS", {"x": {"sr": 0.25}})
        problems = check_floors([_arm_row("x", sr=0.25 - 1e-6)])
        assert problems and "below floor" in problems[0]

    def test_an_unpinned_arm_is_a_problem_not_a_free_pass(self, monkeypatch) -> None:
        monkeypatch.setattr(run_drift_arms, "DRIFT_FLOORS", {})
        problems = check_floors([_arm_row("x", sr=0.9)])
        assert problems and "no Stage-B floor is pinned" in problems[0]

    def test_the_pinned_floors_are_exactly_the_recorded_stage_a_artifact(self) -> None:
        """The Y-3 lesson, enforced: a floor must trace to its Stage-A run.

        ``DRIFT_FLOORS_PROVENANCE`` names the artifact; the artifact's own arm
        rows must re-derive the pinned floors bit for bit through the same
        ``derive_floors`` the protocol specifies. Nothing here is transcribed.
        """

        if not DRIFT_FLOORS:
            pytest.skip("Stage A has not been pinned yet")
        name = DRIFT_FLOORS_PROVENANCE.split()[0]
        artifact = RESULTS / name
        assert artifact.exists(), f"pinned provenance names a missing artifact: {name}"
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert payload["stage"] == "a"
        # The artifact must be a FULL run of the PRE-REGISTERED arms. Without
        # these two, a floor pinned from `--limit 3` or from a hand-picked
        # subset of arms would sail through traceability: `derive_floors` is
        # total and would happily re-derive whatever it was given.
        full = len(generate_drift_cells())
        assert full == 61
        assert payload["n"] == full, (
            f"floors pinned from a TRUNCATED Stage A: n={payload['n']} of {full}"
        )
        assert {row["profile"] for row in payload["arms"]} == set(DRIFT_ARMS), (
            "floors pinned from a Stage A that did not run the pre-registered arms"
        )
        for row in payload["arms"]:
            assert int(row["n"]) == full, f"{row['profile']}: n={row['n']} of {full}"
        assert derive_floors(payload["arms"]) == DRIFT_FLOORS

    def test_every_non_control_arm_is_pinned(self) -> None:
        if not DRIFT_FLOORS:
            pytest.skip("Stage A has not been pinned yet")
        assert set(DRIFT_FLOORS) == {arm for arm in DRIFT_ARMS if arm is not None}

    def test_a_truncated_stage_a_artifact_fails_traceability(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEEDED FAILURE — the companion to the traceability pin above.

        Same artifact, same arms, same mechanical derivation — only ``n`` is a
        prefix. Traceability must reject it, or "the floor traces to a Stage-A
        run" would be satisfiable by a three-episode Stage-A run.
        """

        name = DRIFT_FLOORS_PROVENANCE.split()[0]
        payload = json.loads((RESULTS / name).read_text(encoding="utf-8"))
        payload["n"] = 3
        for row in payload["arms"]:
            row["n"] = 3
        seeded = tmp_path / name
        seeded.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(sys.modules[__name__], "RESULTS", tmp_path)
        with pytest.raises(AssertionError, match="TRUNCATED Stage A"):
            TestFloorProtocol().test_the_pinned_floors_are_exactly_the_recorded_stage_a_artifact()

    def test_a_partial_arm_stage_a_artifact_fails_traceability(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEEDED FAILURE — a Stage A that skipped an arm cannot pin floors."""

        name = DRIFT_FLOORS_PROVENANCE.split()[0]
        payload = json.loads((RESULTS / name).read_text(encoding="utf-8"))
        payload["arms"] = [
            row for row in payload["arms"] if row["profile"] != "go2_aggressive"
        ]
        seeded = tmp_path / name
        seeded.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(sys.modules[__name__], "RESULTS", tmp_path)
        with pytest.raises(AssertionError, match="pre-registered arms"):
            TestFloorProtocol().test_the_pinned_floors_are_exactly_the_recorded_stage_a_artifact()


class TestTruncatedStageBCannotCertify:
    """``--limit`` is a smoke knob; it must not be a way to dodge a red floor.

    ``run_arm`` is monkeypatched so these run in milliseconds — what is under
    test is ``run_stage``'s real control flow (which checks it runs, what it
    records, and whether it may pass), not the simulator.
    """

    @staticmethod
    def _patch(monkeypatch, rows_by_profile) -> None:
        def fake_run_arm(profile, episodes, **kwargs):
            n = len(episodes)
            row = dict(rows_by_profile[profile])
            row["n"] = n
            row["path_m_total"] = 6.0 * n
            drift = row.get("pose_drift")
            if drift:
                drift = dict(drift)
                # Keep the synthetic block internally consistent with n, or
                # ``non_vacuity`` reds for the wrong reason.
                banded = min(int(drift["episodes_banded"]), n)
                drift.update(
                    {"episodes": n, "episodes_banded": banded,
                     "episodes_in_band": banded, "seeds_distinct": n,
                     "episodes_with_lost": min(drift["episodes_with_lost"], n),
                     "episodes_lost_recovered": min(
                         drift["episodes_lost_recovered"], n
                     )}
                )
                row["pose_drift"] = drift
            return row

        monkeypatch.setattr(run_drift_arms, "run_arm", fake_run_arm)

    @staticmethod
    def _rows() -> dict[str | None, dict[str, Any]]:
        return {row["profile"]: row for row in _clean_ladder_rows()}

    def test_a_full_stage_b_certifies_and_passes(self, monkeypatch) -> None:
        rows = self._rows()
        self._patch(monkeypatch, rows)
        monkeypatch.setattr(
            run_drift_arms, "DRIFT_FLOORS", {p: {"sr": 0.0} for p in rows if p}
        )
        payload = run_drift_arms.run_stage("b")
        assert payload["floors_certified"] is True
        assert payload["passed"] is True, payload["problems"]

    def test_a_truncated_stage_b_cannot_certify_and_cannot_pass(
        self, monkeypatch
    ) -> None:
        rows = self._rows()
        self._patch(monkeypatch, rows)
        monkeypatch.setattr(
            run_drift_arms, "DRIFT_FLOORS", {p: {"sr": 0.0} for p in rows if p}
        )
        payload = run_drift_arms.run_stage("b", limit=6)
        assert payload["n"] == 6
        assert payload["floors_certified"] is False
        assert payload["passed"] is False
        assert any("cannot certify them" in p for p in payload["problems"])

    def test_a_red_floor_cannot_be_dodged_by_truncating(self, monkeypatch) -> None:
        """SEEDED FAILURE — an arm below its floor, hidden behind ``--limit``."""

        rows = self._rows()
        self._patch(monkeypatch, rows)
        floors = {p: {"sr": 0.9} for p in rows if p}  # every arm is under water
        monkeypatch.setattr(run_drift_arms, "DRIFT_FLOORS", floors)
        full = run_drift_arms.run_stage("b")
        assert full["passed"] is False
        assert any("below floor" in p for p in full["problems"])
        truncated = run_drift_arms.run_stage("b", limit=3)
        assert truncated["passed"] is False, "a --limit run dodged a red floor"

    def test_stage_a_is_unaffected_by_the_guard(self, monkeypatch) -> None:
        """Stage A never certifies a derived number, so it may still pass."""

        rows = self._rows()
        self._patch(monkeypatch, rows)
        monkeypatch.setattr(run_drift_arms, "DRIFT_FLOORS", {})
        payload = run_drift_arms.run_stage("a", limit=6)
        assert payload["floors_certified"] is False
        assert payload["passed"] is True, payload["problems"]

    def test_the_cli_exit_code_follows(self, monkeypatch, tmp_path: Path) -> None:
        rows = self._rows()
        self._patch(monkeypatch, rows)
        monkeypatch.setattr(
            run_drift_arms, "DRIFT_FLOORS", {p: {"sr": 0.0} for p in rows if p}
        )
        assert run_drift_arms.main(["--stage", "b", "--out", str(tmp_path)]) == 0
        assert (
            run_drift_arms.main(
                ["--stage", "b", "--limit", "6", "--out", str(tmp_path)]
            )
            == 1
        )


# ---------------------------------------------------------------------------
# 7. The hard invariants and the ladder
# ---------------------------------------------------------------------------


class TestHardInvariants:
    def test_a_clean_row_is_green(self) -> None:
        assert hard_invariants(_arm_row("calibrated_go2")) == []

    def test_a_collision_reddens(self) -> None:
        """SEEDED FAILURE — hard from day one, no measurement grace."""

        problems = hard_invariants(_arm_row("calibrated_go2", collisions=1))
        assert problems and "collisions=1" in problems[0]

    def test_a_false_arrival_reddens(self) -> None:
        problems = hard_invariants(_arm_row("go2_degraded", false_arrival=1))
        assert problems and "false_arrival=1" in problems[0]

    def test_the_ladder_is_checked_at_the_arm_mean(self) -> None:
        assert ladder_monotone(_clean_ladder_rows()) == []

    def test_a_flat_ladder_reddens(self) -> None:
        """SEEDED FAILURE — an arm that silently ran the nominal tier."""

        rows = _clean_ladder_rows()
        by_profile = {row["profile"]: row for row in rows}
        by_profile["go2_degraded"]["pose_drift"]["divergence_pct_mean"] = 1.0
        problems = ladder_monotone(rows)
        assert problems and "not monotone" in problems[0]

    def test_the_ladder_check_is_silent_when_an_arm_is_absent(self) -> None:
        """``--limit``-style partial runs must not manufacture a red."""

        assert ladder_monotone([_arm_row(None)]) == []


# ---------------------------------------------------------------------------
# 8. The nightly self-test the card requires
# ---------------------------------------------------------------------------


class TestNightlyGateSelfTest:
    """A seeded drift-arm failure must redden ``ci_gate --tier nightly``.

    The seed is injected at the harness boundary (``run_stage``) so every gate
    verdict below is produced by ci_gate's REAL checkers — ``hard_invariants``,
    ``non_vacuity``, ``ladder_monotone``, ``check_floors`` — on a payload shaped
    exactly like a real Stage-B run. Nothing about the gate logic is stubbed.
    """

    @staticmethod
    def _gate(monkeypatch, rows: list[dict[str, Any]], floors: dict[str, Any], *, limit: int = 0):
        from scripts.ci_gate import evaluate_pose_drift_arms

        monkeypatch.setattr(run_drift_arms, "DRIFT_FLOORS", floors)
        monkeypatch.setattr(
            run_drift_arms, "run_stage", lambda stage, **kw: _payload(rows, stage=stage)
        )
        results = evaluate_pose_drift_arms(tier="nightly", limit=limit)
        return {result.name: result for result in results}

    @staticmethod
    def _clean_floors(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return derive_floors(rows)

    def test_a_clean_nightly_run_is_green(self, monkeypatch) -> None:
        rows = _clean_ladder_rows()
        gates = self._gate(monkeypatch, rows, self._clean_floors(rows))
        assert set(gates) == {
            "pose-drift-arms:safety",
            "pose-drift-arms:non-vacuity",
            "pose-drift-arms:floors",
        }
        for gate in gates.values():
            assert gate.status == "pass", gate
            assert gate.hard is True
            assert gate.tier == "nightly"

    def test_a_seeded_collision_reddens_nightly(self, monkeypatch) -> None:
        rows = _clean_ladder_rows()
        rows[3]["collision_total"] = 1
        gates = self._gate(monkeypatch, rows, self._clean_floors(rows))
        assert gates["pose-drift-arms:safety"].status == "fail"
        assert gates["pose-drift-arms:safety"].gating_red is True

    def test_a_seeded_false_arrival_reddens_nightly(self, monkeypatch) -> None:
        rows = _clean_ladder_rows()
        rows[2]["false_arrival"] = 1
        gates = self._gate(monkeypatch, rows, self._clean_floors(rows))
        assert gates["pose-drift-arms:safety"].status == "fail"

    def test_a_seeded_fixed_seed_arm_reddens_nightly(self, monkeypatch) -> None:
        """The AUDIT's cross-lane finding, wired to a gate."""

        rows = _clean_ladder_rows()
        rows[1]["pose_drift"]["seeds_distinct"] = 1
        gates = self._gate(monkeypatch, rows, self._clean_floors(rows))
        assert gates["pose-drift-arms:non-vacuity"].status == "fail"
        assert gates["pose-drift-arms:non-vacuity"].gating_red is True

    def test_a_seeded_out_of_band_episode_reddens_nightly(self, monkeypatch) -> None:
        rows = _clean_ladder_rows()
        rows[1]["pose_drift"]["episodes_in_band"] -= 1
        gates = self._gate(monkeypatch, rows, self._clean_floors(rows))
        assert gates["pose-drift-arms:non-vacuity"].status == "fail"

    def test_an_arm_that_secretly_ran_on_truth_reddens_nightly(self, monkeypatch) -> None:
        rows = _clean_ladder_rows()
        rows[1]["pose_drift"] = None
        gates = self._gate(monkeypatch, rows, self._clean_floors(rows))
        assert gates["pose-drift-arms:safety"].status == "pass"
        assert gates["pose-drift-arms:non-vacuity"].status == "fail"
        assert "no pose_drift evidence" in gates["pose-drift-arms:non-vacuity"].detail

    def test_a_seeded_sr_regression_reddens_nightly(self, monkeypatch) -> None:
        rows = _clean_ladder_rows()
        floors = self._clean_floors(rows)
        rows[1]["sr"] = floors[rows[1]["profile"]]["sr"] - 1e-6
        gates = self._gate(monkeypatch, rows, floors)
        assert gates["pose-drift-arms:floors"].status == "fail"
        assert gates["pose-drift-arms:floors"].gating_red is True

    def test_the_floor_gate_skips_loudly_before_stage_a_is_pinned(
        self, monkeypatch
    ) -> None:
        """A gate that quietly passes because nothing is pinned is worse than
        no gate — so the unpinned state is an explicit, non-hard ``skip``."""

        rows = _clean_ladder_rows()
        gates = self._gate(monkeypatch, rows, {})
        floors = gates["pose-drift-arms:floors"]
        assert floors.status == "skip"
        assert floors.hard is False
        assert "no Stage-B floor pinned yet" in floors.detail

    def test_a_limited_run_refuses_to_certify_the_full_set_s_floors(
        self, monkeypatch
    ) -> None:
        """A partial run measures a different set — it may not judge the floors."""

        rows = _clean_ladder_rows()
        gates = self._gate(monkeypatch, rows, self._clean_floors(rows), limit=6)
        floors = gates["pose-drift-arms:floors"]
        assert floors.status == "skip"
        assert floors.hard is False
        assert "truncates the substrate" in floors.detail
        # The per-episode properties are unaffected by truncation and stay hard.
        assert gates["pose-drift-arms:safety"].hard is True
        assert gates["pose-drift-arms:non-vacuity"].hard is True

    def test_a_limited_run_still_reddens_on_a_seeded_collision(
        self, monkeypatch
    ) -> None:
        rows = _clean_ladder_rows()
        rows[4]["collision_total"] = 2
        gates = self._gate(monkeypatch, rows, self._clean_floors(rows), limit=6)
        assert gates["pose-drift-arms:safety"].status == "fail"

    def test_a_harness_explosion_reddens_rather_than_disappearing(
        self, monkeypatch
    ) -> None:
        from scripts.ci_gate import evaluate_pose_drift_arms

        def boom(stage, **kw):
            raise RuntimeError("substrate generation failed")

        monkeypatch.setattr(run_drift_arms, "run_stage", boom)
        results = evaluate_pose_drift_arms(tier="nightly")
        assert len(results) == 1
        assert results[0].status == "error"
        assert results[0].gating_red is True

    def test_the_nightly_tier_actually_wires_the_arms_in(self) -> None:
        import inspect

        from scripts.ci_gate import run_nightly_tier

        source = inspect.getsource(run_nightly_tier)
        assert "evaluate_pose_drift_arms" in source

    def test_the_commit_tier_does_not_pay_for_the_arms(self) -> None:
        """The card's cadence: nightly arms, commit-tier unit tests only."""

        import inspect

        from scripts.ci_gate import run_commit_tier

        assert "evaluate_pose_drift_arms" not in inspect.getsource(run_commit_tier)


# ---------------------------------------------------------------------------
# 9. Substrate provenance
# ---------------------------------------------------------------------------


class TestSubstrate:
    def test_generation_is_deterministic(self) -> None:
        first = generate_drift_cells()
        second = generate_drift_cells()
        assert [ep.episode_id for ep in first] == [ep.episode_id for ep in second]

    def test_every_cell_is_long_enough_for_dr1_s_lost_window(self) -> None:
        """DR1_STATUS §2's constraint: shorter than ~10 s of travel and the
        derived (4.0 s, 3.0 s) window stops being derivable — a handoff, not a
        local edit, because pose.yaml is DR-1 frozen."""

        from evals.nav_instruct.drift_cells import DRIFT_MIN_ROUTE_M

        for ep in generate_drift_cells():
            assert ep.shortest_path_m >= DRIFT_MIN_ROUTE_M
        assert DRIFT_MIN_ROUTE_M / 0.85 > 7.0

    def test_the_referent_is_unique_in_the_scene_s_own_perception_table(self) -> None:
        """The measured defect this rule exists for: the landmark table handed
        to a generator is a SLICE (``planter_2`` is absent from it), so a
        removal set derived from it left a second planter standing and every
        planter cell resolved ``semantic_target_ambiguous`` on tick 1."""

        from evals.nav_instruct.generator import load_artifact

        derived = load_artifact()["derived"]
        objects = {
            entity_id
            for entity_id, entry in derived.items()
            if entry.get("kind") == "object" and entry.get("label") != "building"
        }
        assert "planter_2" in objects
        for ep in generate_drift_cells():
            removed = set(ep.placement_overrides["remove_entities"])
            assert removed == objects - {ep.target_entity_id}

    def test_the_substrate_is_candidate_only_and_not_an_episode_set_version(
        self,
    ) -> None:
        from evals.nav_instruct.drift_cells import DRIFT_SET_NAME
        from evals.nav_instruct.generator import EPISODE_SETS

        assert DRIFT_SET_NAME not in EPISODE_SETS

    def test_the_cells_add_no_new_arrival_semantics(self) -> None:
        from evals.nav_instruct.drift_cells import DRIFT_TARGETS
        from evals.nav_instruct.generator import V4S_TARGETS

        assert DRIFT_TARGETS == V4S_TARGETS

    def test_a_cap_that_cannot_be_filled_raises_rather_than_shrinking(self) -> None:
        with pytest.raises(ValueError, match="STOP and report"):
            generate_drift_cells(per_target=999)

    def test_the_travel_the_substrate_actually_offers_is_recorded(self) -> None:
        episodes = generate_drift_cells()
        routes = [ep.shortest_path_m for ep in episodes]
        assert len(episodes) == 61
        assert min(routes) >= 10.0
        assert math.isclose(max(routes), 13.5, abs_tol=1e-6)
