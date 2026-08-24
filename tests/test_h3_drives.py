"""H3 capability proof — drives propose, existing doors dispose.

The three rows the hypothesis' DESIGN names for this file, plus the two the
new patrol seam owes its own callers:

1.  decay / rise / draw are deterministic given a seed and a clock the caller
    owns (there is no clock inside ``attention/drives.py``);
2.  the quiet window refuses a remark at the REAL door — ``ChatterScheduler``
    from ``realtime/whisperer.py``, not a re-implementation of it here;
3.  ``initiative.travel_radius_m = 0`` (the default) emits no travel proposal
    of any kind — not refused downstream, never formed;
4.  ``CoverageSelection()`` — the default — chooses row 0, which is what every
    caller of ``coverage_candidates`` does today, so the ROAM-1/ROAM-2
    baselines cannot move unless a caller opts in;
5.  the H2 minimum-distance filter fails OPEN: filtering everything away
    degrades to today's row, never to "no objective" (which the patrol reads
    as wander and which a stopped dog would read as a bug).
"""

from __future__ import annotations

import math
import random

import pytest

from parcel_robot.attention.drives import (
    CURIOSITY,
    DEFAULT_DYNAMICS,
    SOCIAL,
    DriveSignal,
    DriveSignalKind,
    DriveState,
    InitiativeDigest,
    InitiativeKind,
    InitiativePolicy,
    propose,
    update_drives,
)
from parcel_robot.patrol.coverage import (
    CoverageSelection,
    coverage_selection_from_config,
    select_coverage_candidate,
)
from parcel_robot.realtime.config import CuriosityConfig
from parcel_robot.realtime.whisperer import (
    CHATTER_SKIP_CONVERSATION,
    CHATTER_SKIP_QUIET_HOURS,
    TIME_BAND_AFTERNOON,
    TIME_BAND_NIGHT,
    ChatterScheduler,
    ChatterState,
)


def _digest(**overrides: object) -> InitiativeDigest:
    base: dict[str, object] = {
        "at_s": 100.0,
        "idle_s": 100.0,
        "owner_present": True,
        "look_bearing_rad": 0.4,
        "look_subject": "bench",
        "person_id": "ped-1",
        "person_range_m": 3.0,
        "person_bearing_rad": -0.2,
        "remark_subject": "bench",
        "place_id": "place-1",
        "place_bearing_rad": 0.9,
        "place_range_m": 5.0,
        "place_age_s": 600.0,
    }
    base.update(overrides)
    return InitiativeDigest(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------- 1. pure
def test_decay_halves_at_the_half_life_and_never_runs_backwards() -> None:
    state = DriveState(at_s=0.0, curiosity=0.8)
    half_life = DEFAULT_DYNAMICS.half_life_s[CURIOSITY]
    decayed = DEFAULT_DYNAMICS.decayed(state, half_life)
    assert decayed.curiosity == pytest.approx(0.4, abs=1e-9)
    assert decayed.at_s == half_life
    with pytest.raises(ValueError):
        DEFAULT_DYNAMICS.decayed(decayed, half_life - 1.0)


def test_rise_sums_deltas_and_an_owner_turn_discharges_the_social_drive() -> None:
    state = DriveState(at_s=10.0, social=0.6, curiosity=0.5)
    noticing = DriveSignal(DriveSignalKind.NOTICING.value, 10.0, 1.0)
    person = DriveSignal(DriveSignalKind.PERSON_SEEN.value, 10.0, 1.0)
    forward = DEFAULT_DYNAMICS.risen(state, [noticing, person])
    backward = DEFAULT_DYNAMICS.risen(state, [person, noticing])
    assert forward == backward
    assert forward.curiosity == pytest.approx(0.5 + 0.150 + 0.030)
    turned = DEFAULT_DYNAMICS.risen(state, [DriveSignal(DriveSignalKind.OWNER_TURN.value, 10.0)])
    assert turned.social < state.social
    assert turned.social == pytest.approx(max(0.0, 0.6 - 0.550))


def test_update_and_propose_replay_exactly_under_one_seed() -> None:
    signals = [DriveSignal(DriveSignalKind.NOTICING.value, float(step), 1.0) for step in range(6)]
    policy = InitiativePolicy(travel_radius_m=6.0, seed=1234)

    def replay() -> list[tuple[float, str | None]]:
        state = DriveState()
        out: list[tuple[float, str | None]] = []
        for step in range(60):
            now = float(step)
            state = update_drives(state, [s for s in signals if s.at_s == now], now_s=now)
            proposal = propose(state, _digest(at_s=now), policy)
            out.append((state.curiosity, None if proposal is None else proposal.kind))
        return out

    assert replay() == replay()
    # And a different seed really is a different draw sequence somewhere.
    other = InitiativePolicy(travel_radius_m=6.0, seed=99)
    state = DriveState(at_s=0.0, curiosity=0.95)
    kinds = {propose(state, _digest(at_s=float(t)), policy).kind for t in range(40)}
    other_kinds = {propose(state, _digest(at_s=float(t)), other).kind for t in range(40)}
    assert kinds and other_kinds


def test_every_proposal_names_exactly_one_drive_row() -> None:
    policy = InitiativePolicy(travel_radius_m=6.0, seed=7)
    state = DriveState(at_s=0.0, curiosity=0.9, social=0.85)
    for tick in range(50):
        proposal = propose(state, _digest(at_s=float(tick)), policy)
        assert proposal is not None
        assert proposal.drive in {CURIOSITY, SOCIAL}
        assert proposal.drive_value >= policy.threshold
        assert proposal.reason.startswith(proposal.drive)


# ------------------------------------------------------- 2. the consent knob
def test_travel_radius_zero_never_forms_a_travel_proposal() -> None:
    policy = InitiativePolicy(seed=3)  # travel_radius_m defaults to 0.0
    assert policy.travel_radius_m == 0.0
    assert not policy.travel_allowed
    state = DriveState(at_s=0.0, curiosity=1.0, social=1.0)
    kinds = set()
    for tick in range(400):
        proposal = propose(state, _digest(at_s=tick * 0.1), policy)
        if proposal is not None:
            kinds.add(proposal.kind)
    assert kinds
    assert not kinds & {InitiativeKind.GO_CHECK.value, InitiativeKind.APPROACH.value}


def test_a_positive_radius_does_admit_travel_so_the_row_above_is_not_vacuous() -> None:
    policy = InitiativePolicy(travel_radius_m=6.0, seed=3)
    state = DriveState(at_s=0.0, curiosity=1.0, social=1.0)
    kinds = {
        proposal.kind
        for tick in range(400)
        if (proposal := propose(state, _digest(at_s=tick * 0.1), policy)) is not None
    }
    assert InitiativeKind.GO_CHECK.value in kinds
    # A place beyond the radius is still not proposable.
    far = _digest(place_range_m=9.0)
    beyond = {
        proposal.kind
        for tick in range(200)
        if (proposal := propose(state, far, policy)) is not None
    }
    assert InitiativeKind.GO_CHECK.value not in beyond


def test_an_emergency_stop_forms_no_proposal_at_all() -> None:
    policy = InitiativePolicy(travel_radius_m=6.0, seed=3)
    state = DriveState(at_s=0.0, curiosity=1.0, social=1.0, duty=1.0, comfort=1.0)
    assert propose(state, _digest(emergency_stopped=True), policy) is None


# --------------------------------------------------- 3. the real remark door
def _scheduler(band: str = TIME_BAND_AFTERNOON) -> tuple[ChatterScheduler, list[float]]:
    clock = [0.0]
    scheduler = ChatterScheduler(
        config=CuriosityConfig(enabled=True),
        clock=lambda: clock[0],
        rng=random.Random(5),
        time_band=lambda: band,
    )
    return scheduler, clock


def test_the_quiet_window_refuses_a_remark_at_the_real_door() -> None:
    scheduler, clock = _scheduler()
    quiet_s = CuriosityConfig().quiet_s
    scheduler.due(ChatterState(at_s=0.0, owner_present=True, lane_busy=False))
    clock[0] = 10.0
    scheduler.note_turn(at=10.0)
    inside = scheduler.due(
        ChatterState(at_s=10.0 + quiet_s - 1.0, owner_present=True, lane_busy=False),
        stimulus=True,
    )
    assert inside is False
    assert scheduler.skips.get(CHATTER_SKIP_CONVERSATION) == 1
    outside = scheduler.due(
        ChatterState(at_s=10.0 + quiet_s + 1.0, owner_present=True, lane_busy=False),
        stimulus=True,
    )
    assert outside is True


def test_the_night_band_refuses_a_remark_at_the_real_door() -> None:
    scheduler, _clock = _scheduler(band=TIME_BAND_NIGHT)
    scheduler.due(ChatterState(at_s=0.0, owner_present=True, lane_busy=False))
    assert (
        scheduler.due(
            ChatterState(at_s=600.0, owner_present=True, lane_busy=False), stimulus=True
        )
        is False
    )
    assert scheduler.skips.get(CHATTER_SKIP_QUIET_HOURS)


# ------------------------------------------------- 4. the ROAM-2 H2 selection
def _rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "entry_id": "near-behind",
            "label": "bench",
            "distance_m": 1.2,
            "bearing_rad": math.pi,
            "age_s": 900.0,
            "surface_x": -1.2,
            "surface_y": 0.0,
        },
        {
            "entry_id": "far-ahead",
            "label": "door",
            "distance_m": 7.0,
            "bearing_rad": 0.05,
            "age_s": 600.0,
            "surface_x": 7.0,
            "surface_y": 0.0,
        },
    )


def test_the_default_selection_is_exactly_todays_row_zero() -> None:
    selection = CoverageSelection()
    assert selection.is_shipped_default
    assert coverage_selection_from_config(None) == selection
    choice = select_coverage_candidate(_rows(), selection=selection)
    assert choice is not None
    assert choice.row is _rows()[0] or choice.row["entry_id"] == "near-behind"
    assert select_coverage_candidate(()) is None


def test_the_h2_options_prefer_the_far_forward_candidate() -> None:
    selection = CoverageSelection(min_candidate_distance_m=3.0, forward_bearing_weight=0.6)
    choice = select_coverage_candidate(_rows(), selection=selection)
    assert choice is not None
    assert choice.row["entry_id"] == "far-ahead"
    assert choice.after_min_distance == 1
    assert choice.filtered_out_all is False


def test_a_minimum_distance_that_empties_the_list_fails_open() -> None:
    selection = CoverageSelection(min_candidate_distance_m=50.0, forward_bearing_weight=0.6)
    choice = select_coverage_candidate(_rows(), selection=selection)
    assert choice is not None
    assert choice.filtered_out_all is True
    assert choice.after_min_distance == 0
    assert choice.row["entry_id"] in {"near-behind", "far-ahead"}


def test_the_scored_selection_does_not_depend_on_the_row_order() -> None:
    """Reproducibility row: map entry ids are uuid4, so row order is not stable.

    ``coverage_candidates`` sorts oldest-first and breaks its remaining ties on
    ``entry_id`` — which ``online_map.py`` mints with ``uuid.uuid4()``. Two
    processes therefore see the same places in a different order, and a
    selection that inherited that order would not replay. Ties here are broken
    on distance/bearing/surface point instead, so a permuted input picks the
    same row.
    """

    tied = tuple(
        {
            "entry_id": f"place-{index}",
            "label": "bench",
            "distance_m": 4.0 + index * 0.5,
            "bearing_rad": 0.2,
            "age_s": 500.0,
            "surface_x": 4.0 + index * 0.5,
            "surface_y": 0.0,
        }
        for index in range(4)
    )
    selection = CoverageSelection(min_candidate_distance_m=3.0, forward_bearing_weight=0.6)
    first = select_coverage_candidate(tied, selection=selection)
    reversed_choice = select_coverage_candidate(tuple(reversed(tied)), selection=selection)
    rotated = select_coverage_candidate(tied[2:] + tied[:2], selection=selection)
    assert first is not None
    assert reversed_choice is not None and rotated is not None
    assert first.row["entry_id"] == reversed_choice.row["entry_id"] == rotated.row["entry_id"]


def test_config_reading_fails_closed_on_a_typo() -> None:
    with pytest.raises(ValueError):
        coverage_selection_from_config({"min_candidate_distanc_m": 3.0})
    parsed = coverage_selection_from_config({"min_candidate_distance_m": 2.5})
    assert parsed.min_candidate_distance_m == 2.5
    assert not parsed.is_shipped_default


# ------------------------------------------------------- 5. the patrol's own
def test_the_patrol_boxed_in_escape_cannot_fire_under_the_shipped_limits() -> None:
    """Measured H3 finding, pinned so a future fix has a test to turn green.

    ``PatrolPolicy._turn`` checks ``turn_giveup_after_s`` (12 s) BEFORE it
    applies ``turn_flip_after_s`` (4 s) — and the flip RESETS the same clock
    the give-up reads, so ``turning_for`` can never exceed 4 s and the
    ``boxed_in`` branch is unreachable with any limits where flip < give-up.
    A wedged patrol therefore turns on the spot for its whole budget.
    """

    from parcel_robot.patrol.mission import PatrolLimits, PatrolPolicy, PatrolSense

    limits = PatrolLimits()
    assert limits.turn_flip_after_s < limits.turn_giveup_after_s
    policy = PatrolPolicy(limits)
    reasons = {
        policy.step(
            PatrolSense(elapsed_s=step * 0.1, x=0.0, y=0.0, yaw=0.0, forward_clearance_m=0.4)
        ).reason
        for step in range(int(limits.budget_s * 10))
    }
    assert reasons == {"turn_blocked"}
    assert "boxed_in" not in reasons
