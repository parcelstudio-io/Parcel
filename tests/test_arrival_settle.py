"""Card C2 (ARRIVAL-SETTLE-1): the harness observes the settle, and there is ONE
arrival authority.

Three harnesses disagreed about "arrived". MA-1's gold required five stopped
frames inside the band that its own loop could never observe — it broke one
frame after ``done()`` in 133/133 episodes, so *no* episode could be an oracle
success (NAV-GEN-1 ``VERDICT.md`` §5.1). The product harness had the same shape:
:class:`HeadlessCityQualityHarness` breaks on ``command.stop``/``navigator.done()``
and its ``stopped`` is "terminal command zero on ONE frame".

These tests pin the fix and, just as importantly, pin its *limits*:

* the settle window is OBSERVATION ONLY — it issues no command, so it cannot
  reach the A3 latch or the A6 stop path, and the standing command is provably
  untouched across it;
* ``settle_frames=0`` reproduces the pre-card result field for field, so the
  strict one-frame predicate stays comparable to its own frozen history;
* ``arrived_verified`` keeps the authority on the SYSTEM side — it is the
  system's own terminal claim, confirmed by the committed K0 region and the
  settle. A missing or negative receipt is never an arrival, however good the
  geometry looks, and a claim with no committed region is never confirmed.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from parcel_robot.models import VelocityCommand
from parcel_robot.simulation.headless_city import (
    DEFAULT_SETTLE_FRAMES,
    HeadlessCityQualityHarness,
    HeadlessCityWorld,
    HeadlessTaskResult,
    _WorldSnapshot,
)

#: Result fields that existed BEFORE this card. Every one of them must be
#: unmoved by the settle window, which is what makes "strict vs settled" a
#: delta rather than two unrelated measurements.
_PRE_CARD_FIELDS = (
    "directive",
    "status",
    "reason",
    "target_id",
    "terminal_relation",
    "trace",
    "path",
    "collision_count",
    "minimum_clearance_m",
    "required_obstacle_clearance_m",
    "semantic_scan_steps",
    "terminal_command",
)

_START = (0.0, 0.0, 0.0)


@pytest.fixture(scope="module")
def world() -> HeadlessCityWorld:
    return HeadlessCityWorld()


def _run(world: HeadlessCityWorld, directive: str, *, settle_frames: int) -> HeadlessTaskResult:
    harness = HeadlessCityQualityHarness(world, settle_frames=settle_frames)
    # NAV-GEN-1's own order-independence recipe (``run.py``): reseed the scan
    # RNG and reset the pose, so a run cannot inherit the previous one's noise
    # stream. Without it two runs of the SAME directive already differ on this
    # module-scoped world, and this file would be measuring that instead of
    # the settle window.
    world._scan_rng = np.random.default_rng(7)
    world.reset(robot=_START)
    return harness.run(directive, max_steps=600)


@pytest.mark.slow  # one headless city mission per run
def test_settle_window_leaves_every_pre_card_field_untouched(world: HeadlessCityWorld) -> None:
    """The strict one-frame predicate is literally the number it always was."""

    without = _run(world, "go to the lamppost", settle_frames=0)
    with_settle = _run(world, "go to the lamppost", settle_frames=DEFAULT_SETTLE_FRAMES)

    for field in _PRE_CARD_FIELDS:
        assert getattr(with_settle, field) == getattr(without, field), (
            f"the settle window moved the pre-card field {field!r} — every one "
            "of them must be frozen at the terminal frame"
        )
    # final_observation is a dataclass of arrays; compare the pose that every
    # consumer actually reads off it.
    before, after = without.final_observation.robot, with_settle.final_observation.robot
    assert (after.x, after.y, after.yaw) == (before.x, before.y, before.yaw)
    assert without.stopped == with_settle.stopped
    # ...and the settle is a pure addition on top.
    assert without.settle_frames_observed == 0 and without.settled is False
    assert with_settle.settle_frames_observed == DEFAULT_SETTLE_FRAMES


@pytest.mark.slow
def test_a_verified_arrival_holds_still_inside_the_committed_region(
    world: HeadlessCityWorld,
) -> None:
    """MA-1's gold predicate, finally observable: five stopped frames in band."""

    result = _run(world, "go to the lamppost", settle_frames=DEFAULT_SETTLE_FRAMES)

    assert result.status == "arrived" and result.reason == "arrived_verified"
    assert result.inside_arrival_region is True
    assert result.settled is True
    assert result.settle_frames_observed == DEFAULT_SETTLE_FRAMES
    assert result.arrived_verified is True
    # The standing command is what the mission left behind; the window never
    # wrote one of its own.
    assert world.command == result.terminal_command
    assert result.goal_source == "semantic_search"


@pytest.mark.slow
def test_a_poi_arrival_with_no_committed_region_is_not_verified(
    world: HeadlessCityWorld,
) -> None:
    """The POI second oracle claims arrival with no K0 region to confirm it.

    ``go to the crosswalk`` is grounded by ``PlaceGrounder`` to a hardcoded
    point (``goal_source: known_poi``; NAV-GEN-1 ``VERDICT.md`` §5.2, card C1),
    and that path commits no arrival region at all. The mission may still say
    ``arrived`` — this card does not change ``status``/``reason`` — but the one
    arrival authority refuses to *confirm* it, and says why in the fields
    rather than in prose. When C1 lands and the crosswalk grounds to the scene
    region, ``inside_arrival_region`` stops being ``None`` here.
    """

    result = _run(world, "go to the crosswalk", settle_frames=DEFAULT_SETTLE_FRAMES)

    assert result.goal_source == "known_poi"
    assert result.inside_arrival_region is None
    assert result.settled is False
    assert result.settle_frames_observed == 0
    assert result.arrived_verified is False


def _result_for(
    harness: HeadlessCityQualityHarness,
    *,
    status: str,
    reason: str,
    inside: bool | None,
    settled: bool,
) -> HeadlessTaskResult:
    snapshot = _WorldSnapshot(
        final_observation=harness.world.observe(),
        path=harness.world.path,
        collision_count=harness.world.collision_count,
        minimum_clearance_m=harness.world.minimum_clearance_m,
    )
    return harness._result(
        "go to the lamppost",
        status=status,
        reason=reason,
        target_id="lamp_post_1",
        terminal_relation="near",
        trace=[],
        semantic_scan_steps=0,
        terminal_command=VelocityCommand(),
        required_obstacle_clearance_m=0.65,
        snapshot=snapshot,
        settled=settled,
        settle_frames_observed=DEFAULT_SETTLE_FRAMES if settled else 0,
        inside_arrival_region=inside,
        mission_metadata={},
        system_status=status,
        system_reason=reason,
    )


@pytest.mark.parametrize(
    ("status", "reason", "inside", "settled", "expected"),
    (
        ("arrived", "arrived_verified", True, True, True),
        # Authority stays with the SYSTEM: no claim, no arrival, however good
        # the geometry is. This is the half that must never be relaxed into
        # "claim arrival when the receipt is missing".
        ("failed", "semantic_arrival_verification_failed", True, True, False),
        ("timed_out", "navigation_step_limit_inside_goal", True, True, False),
        # ...and a system claim alone is not enough either: without the
        # committed K0 region, or without the settle, nothing is confirmed.
        ("arrived", "arrived_verified", None, False, False),
        ("arrived", "arrived_verified", False, True, False),
        ("arrived", "arrived_verified", True, False, False),
    ),
)
def test_arrived_verified_needs_the_claim_the_region_and_the_settle(
    world: HeadlessCityWorld,
    status: str,
    reason: str,
    inside: bool | None,
    settled: bool,
    expected: bool,
) -> None:
    harness = HeadlessCityQualityHarness(world)
    result = _result_for(
        harness, status=status, reason=reason, inside=inside, settled=settled
    )
    assert result.arrived_verified is expected
    # ``status``/``reason`` semantics are untouched by this card (E3).
    assert result.status == status and result.reason == reason


def test_settle_frames_must_be_nonnegative(world: HeadlessCityWorld) -> None:
    with pytest.raises(ValueError, match="settle_frames"):
        HeadlessCityQualityHarness(world, settle_frames=-1)


def test_the_two_predicates_are_independent_fields(world: HeadlessCityWorld) -> None:
    """``stopped`` and ``settled`` are reported side by side, never merged.

    A result may be stopped-on-one-frame and not settled (the interesting
    delta), and the dataclass has to be able to say so without either field
    being derived from the other.
    """

    harness = HeadlessCityQualityHarness(world)
    stopped_not_settled = _result_for(
        harness, status="arrived", reason="arrived_verified", inside=True, settled=False
    )
    assert stopped_not_settled.stopped is True
    assert stopped_not_settled.settled is False
    moving = dataclasses.replace(
        stopped_not_settled, terminal_command=VelocityCommand(vx=0.3), settled=True
    )
    assert moving.stopped is False and moving.settled is True
