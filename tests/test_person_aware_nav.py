"""Card D15-B — ``person_aware_nav`` wiring: flag-off identity, flag-on capability.

The D-15 regression (``nav-object_goal-D-15-109547e2``) is a compliant robot
deadlocking behind an undeclared bystander: at 1.2632 m of clearance the gate's
predictive person stop at the v3/v4 cruise speed is 1.3020 m, so
``apply_reactive_safety`` vetoed translation on every tick while the planner —
blind to the veto — replanned the same straight route
(``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §1.1).

What is proved here, with the REAL gate as the judge in every case:

* flag-OFF, the person channel changes nothing — the same observation with and
  without the person payload produces identical commands, and neither
  flag-on branch is ever entered (non-vacuity's control arm);
* flag-ON at the measured D-15 geometry, the commanded speed is capped to the
  float-lattice compliant speed and the UNMODIFIED
  ``apply_reactive_safety`` then lets the robot move, where flag-OFF it
  ``_stop_translation``s — the deadlock and its remedy, in one test;
* flag-ON publishes a person the planner would be BLIND to into the payload its
  own additive cost layer consumes, so the route cost near that person rises —
  and never double-counts a person the payload already carries;
* the cap only ever reduces speed, only toward people, only inside the band.

Not proved here (see W1_D15_STATUS.md): anything about the frozen nav_instruct
rows. Those are measured by running the harness, not by unit tests; and the
stock harness publishes no person channel at all, which is handoff H-1.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from evals.nav_instruct.runner import ALLOWED_NAVIGATOR_OVERRIDES
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.dynamic_layer import DynamicAgentCostConfig, merged_cost_mask
from parcel_robot.navigation.person_keepout import (
    compliant_speed,
    gate_vetoes,
    keepout_radius_m,
    predictive_person_stop_m,
)
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.reactive_safety import ReactiveSafetyPolicy, apply_reactive_safety
from parcel_robot.navigation.traffic_aware import tracks_from_payload

REPO = Path(__file__).resolve().parents[1]
NAV_CFG = REPO / "configs" / "navigation" / "default.yaml"

#: Heading that leaves the stub/point-goal controller already aligned on the
#: POI used below, so the commands under test are translations, not turns.
ALIGNED_HEADING_DEG = 11.4
#: D-15's measured owner geometry: centre distance 1.8132 m, i.e. 1.2632 m of
#: clearance once the gate's ``owner_collision_envelope_m`` is subtracted.
D15_OWNER_CENTER_DISTANCE_M = 1.8132
DIRECTIVE = "go to the coffee shop at 42nd street"


def _owner_payload() -> dict[str, float | str]:
    angle = math.radians(ALIGNED_HEADING_DEG)
    return {
        "id": "owner-1",
        "x": D15_OWNER_CENTER_DISTANCE_M * math.cos(angle),
        "y": D15_OWNER_CENTER_DISTANCE_M * math.sin(angle),
        "vx": 0.0,
        "vy": 0.0,
        "radius_m": 0.35,
    }


def _observation(*, with_person: bool) -> NavObservation:
    extras = {"owner_track": [_owner_payload()]} if with_person else {}
    return NavObservation(
        position=(0.0, 0.0, 0.0),
        heading_deg=ALIGNED_HEADING_DEG,
        extras=extras,
    )


def _drive(*, person_aware_nav: bool, with_person: bool, ticks: int = 12):
    """Run the pipeline open-loop from rest; returns (commands, navigator)."""

    nav = DirectiveNavigator.from_config(NAV_CFG, person_aware_nav=person_aware_nav)
    nav.start(DIRECTIVE)
    commands = [nav.step(_observation(with_person=with_person)) for _ in range(ticks)]
    nav.close()
    return commands, nav


def _gate_verdict(speed_mps: float) -> tuple[VelocityCommand, str]:
    """The REAL gate's verdict on a command of ``speed_mps`` at D-15's geometry."""

    angle = math.radians(ALIGNED_HEADING_DEG)
    observation = SimObservation(
        timestamp=0.0,
        robot=RobotPose(x=0.0, y=0.0, z=0.0, yaw=angle),
        owner=OwnerTrack(
            owner_id="owner-1",
            x=D15_OWNER_CENTER_DISTANCE_M * math.cos(angle),
            y=D15_OWNER_CENTER_DISTANCE_M * math.sin(angle),
            visible=True,
            confidence=1.0,
        ),
        # A far, bearing-less obstacle: a present scan (P0-B input health) that
        # is nowhere near any threshold, so the only live gate is the person.
        nearest_obstacle_m=8.0,
        backend="test",
    )
    return apply_reactive_safety(
        VelocityCommand(vx=speed_mps, vy=0.0, vyaw=0.0),
        observation,
        policy=ReactiveSafetyPolicy(),
        now=0.0,
        require_fresh_telemetry=False,
    )


# ---------------------------------------------------------------------------
# Flag-off identity
# ---------------------------------------------------------------------------


def test_flag_defaults_off_everywhere() -> None:
    nav = DirectiveNavigator.from_config(NAV_CFG)
    try:
        assert nav.person_aware_nav is False
        assert nav.person_costs_published_ticks == 0
        assert nav.person_compliant_cap_ticks == 0
    finally:
        nav.close()


def test_flag_off_person_channel_changes_nothing() -> None:
    """Control arm: flag-off, declaring a person has no effect on any command."""

    with_person, nav_a = _drive(person_aware_nav=False, with_person=True)
    without, _ = _drive(person_aware_nav=False, with_person=False)

    assert [(c.vx, c.vy, c.vyaw, c.note, c.stop) for c in with_person] == [
        (c.vx, c.vy, c.vyaw, c.note, c.stop) for c in without
    ]
    assert nav_a.person_costs_published_ticks == 0
    assert nav_a.person_compliant_cap_ticks == 0
    assert all("person_compliant_cap" not in (c.note or "") for c in with_person)


# ---------------------------------------------------------------------------
# Flag-on capability — the D-15 deadlock and its remedy
# ---------------------------------------------------------------------------


def test_flag_on_cap_lets_the_untouched_gate_approve_the_d15_geometry() -> None:
    policy = ReactiveSafetyPolicy()
    clearance = D15_OWNER_CENTER_DISTANCE_M - policy.owner_collision_envelope_m
    limit = compliant_speed(clearance, policy=policy)

    flag_off, _ = _drive(person_aware_nav=False, with_person=True)
    flag_on, nav_on = _drive(person_aware_nav=True, with_person=True)

    uncapped = flag_off[-1].vx
    capped = flag_on[-1].vx
    # The proposer: flag-off asks for the speed that deadlocked D-15, flag-on
    # asks for the largest speed the gate's own inequality accepts.
    assert uncapped == pytest.approx(0.85, abs=1e-5)  # grid_v1 cruise speed
    assert capped == pytest.approx(limit, abs=1e-12)
    assert capped < uncapped
    assert predictive_person_stop_m(policy, uncapped) > clearance
    assert predictive_person_stop_m(policy, capped) < clearance

    # The disposer, unmodified, on those two commands.
    stopped_command, stopped_note = _gate_verdict(uncapped)
    moving_command, moving_note = _gate_verdict(capped)
    assert (stopped_command.vx, stopped_command.vy) == (0.0, 0.0)
    assert stopped_note == "stopped"
    assert moving_command.vx > 0.0
    assert moving_note in {"clear", "slowing"}

    # Non-vacuity: the flag-on path really ran.
    assert nav_on.person_compliant_cap_ticks > 0
    assert nav_on.person_costs_published_ticks == 0  # payload path, not the sensed one
    assert any("person_compliant_cap" in (c.note or "") for c in flag_on)


def test_cap_engages_only_inside_the_band_and_only_toward_the_person() -> None:
    nav = DirectiveNavigator.from_config(NAV_CFG, person_aware_nav=True)
    try:
        policy = ReactiveSafetyPolicy()
        far = NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            extras={"owner_track": [{"id": "o", "x": 12.0, "y": 0.0}]},
        )
        behind = NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            extras={"owner_track": [{"id": "o", "x": -1.8132, "y": 0.0}]},
        )
        ahead = NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            extras={"owner_track": [{"id": "o", "x": 1.8132, "y": 0.0}]},
        )

        assert nav._person_compliant_translation(far, 0.85, 0.0) == (0.85, 0.0, "")
        assert nav._person_compliant_translation(behind, 0.85, 0.0) == (0.85, 0.0, "")
        capped_vx, capped_vy, note = nav._person_compliant_translation(ahead, 0.85, 0.0)
        assert capped_vx < 0.85
        assert capped_vy == 0.0
        assert note.startswith("person_compliant_cap=")
        # Never a raise: a command already below the limit is returned as-is.
        assert nav._person_compliant_translation(ahead, 0.1, 0.0) == (0.1, 0.0, "")
        # Inside the stop distance no speed is compliant, so the proposal is a stop.
        inside = NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            extras={
                "owner_track": [
                    {"id": "o", "x": policy.person_stop_m, "y": 0.0},
                ]
            },
        )
        stop_vx, stop_vy, _ = nav._person_compliant_translation(inside, 0.85, 0.0)
        assert (stop_vx, stop_vy) == (0.0, 0.0)
    finally:
        nav.close()


@pytest.mark.parametrize(
    "clearance",
    [1.2000001, 1.2632, 1.30, 1.3019, 1.302, 1.35, 1.9, 2.4999],
)
def test_capped_command_is_gate_approved_by_construction(clearance: float) -> None:
    """The emitted magnitude is proved against the gate's own inequality.

    Scaling by ``limit / speed`` is not exact on the float lattice, and one ULP
    over the boundary is the difference between a moving robot and a vetoed one:
    unguarded, this cost 0.519 of translating ticks on the declared-bystander
    cell. The cap walks the lattice down until the gate's expression says False.
    """

    nav = DirectiveNavigator.from_config(NAV_CFG, person_aware_nav=True)
    try:
        policy = ReactiveSafetyPolicy()
        for heading in (0.0, 0.4, -0.9, 1.4):
            observation = NavObservation(
                position=(0.0, 0.0, 0.0),
                heading_deg=0.0,
                nearest_person_m=clearance,
                extras={"person_bearing_rad": heading},
            )
            vx, vy, _note = nav._person_compliant_translation(observation, 0.85, 0.0)
            magnitude = math.hypot(vx, vy)
            assert magnitude <= 0.85
            if magnitude > 0.0:
                assert (
                    gate_vetoes(clearance, magnitude, policy=policy) is False
                ), f"gate would veto {magnitude!r} at clearance {clearance!r}"
    finally:
        nav.close()


def test_cap_reads_the_nearest_person_channel_too() -> None:
    """``nearest_person_m`` is already a CLEARANCE — used without conversion."""

    nav = DirectiveNavigator.from_config(NAV_CFG, person_aware_nav=True)
    try:
        policy = ReactiveSafetyPolicy()
        clearance = 1.2632
        observation = NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            nearest_person_m=clearance,
            extras={"person_bearing_rad": 0.0},
        )
        vx, _vy, note = nav._person_compliant_translation(observation, 0.85, 0.0)
        assert vx == pytest.approx(compliant_speed(clearance, policy=policy), abs=1e-12)
        assert note.startswith("person_compliant_cap=")
    finally:
        nav.close()


# ---------------------------------------------------------------------------
# Flag-on capability — keepout painting
# ---------------------------------------------------------------------------


def test_flag_on_publishes_a_sensed_person_into_the_planner_cost_payload() -> None:
    nav = DirectiveNavigator.from_config(NAV_CFG, person_aware_nav=True)
    try:
        policy = ReactiveSafetyPolicy()
        clearance = D15_OWNER_CENTER_DISTANCE_M - policy.owner_collision_envelope_m
        observation = NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            nearest_person_m=clearance,
            extras={"person_bearing_rad": 0.0, "person_id": "ped-1"},
        )

        published = nav._publish_person_costs(observation)

        assert published is not observation
        assert "dynamic_agents" not in observation.extras  # caller untouched
        entry = published.extras["dynamic_agents"][0]
        # Placed at the sensed CENTRE: clearance is surface-referenced, so the
        # person's own envelope is added back, exactly as the gate subtracts it.
        assert entry["x"] == pytest.approx(
            clearance + policy.owner_collision_envelope_m
        )
        assert entry["y"] == pytest.approx(0.0)
        assert entry["radius_m"] == pytest.approx(policy.owner_collision_envelope_m)
        assert nav.person_costs_published_ticks == 1

        # The planner's own additive layer now costs the cells around them.
        config = DynamicAgentCostConfig(enabled=True)  # as shipped in grid.yaml
        centers = np.array([[x / 10.0, 0.0] for x in range(-40, 41)], dtype=float)
        costs = merged_cost_mask(
            config=config,
            agent_tracks=tracks_from_payload(published.extras["dynamic_agents"]),
            owner_tracks=(),
            cell_centers_xy=centers,
            robot_xy=(0.0, 0.0),
        )
        assert float(costs.max()) > 0.0
        assert float(costs.min()) >= 0.0
        # Peak sits on the person, not on the robot: the gradient A* needs.
        peak = centers[int(np.argmax(costs))][0]
        assert peak == pytest.approx(entry["x"], abs=0.2)
    finally:
        nav.close()


def test_publishing_never_double_counts_a_person_the_payload_carries() -> None:
    """The runtime publishes both channels for one body; cost it once."""

    nav = DirectiveNavigator.from_config(NAV_CFG, person_aware_nav=True)
    try:
        observation = NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            nearest_person_m=1.2632,
            extras={
                "person_bearing_rad": 0.0,
                "owner_track": [_owner_payload()],
            },
        )
        assert nav._publish_person_costs(observation) is observation
        assert nav.person_costs_published_ticks == 0
    finally:
        nav.close()


def test_publishing_is_a_no_op_without_a_person_channel() -> None:
    """A harness that declares no bystander gets no behaviour change, flag-on."""

    nav = DirectiveNavigator.from_config(NAV_CFG, person_aware_nav=True)
    try:
        observation = NavObservation(position=(0.0, 0.0, 0.0), heading_deg=0.0)
        assert nav._publish_person_costs(observation) is observation
        assert nav.person_costs_published_ticks == 0
        assert nav._declared_people(observation) == []
    finally:
        nav.close()


def test_keepout_ring_is_available_for_the_planner_layer_handoff() -> None:
    """D15-A's ring is derived and consumable; its cost-layer home is H-2."""

    policy = ReactiveSafetyPolicy()
    ring = keepout_radius_m(policy, 0.85)
    assert ring == pytest.approx(
        policy.person_stop_m + 0.85 * policy.reaction_time_s
        + policy.owner_collision_envelope_m
    )


def test_malformed_person_payload_degrades_to_no_capability() -> None:
    nav = DirectiveNavigator.from_config(NAV_CFG, person_aware_nav=True)
    try:
        observation = NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            extras={
                "owner_track": [{"x": "not-a-number", "y": 0.0}, {"y": 1.0}, "junk"],
                "dynamic_agents": {"x": 1.0},
            },
        )
        assert nav._declared_people(observation) == []
        assert nav._person_compliant_translation(observation, 0.85, 0.0) == (0.85, 0.0, "")
    finally:
        nav.close()


# ---------------------------------------------------------------------------
# Harness plumbing
# ---------------------------------------------------------------------------


def test_runner_allowlist_carries_the_flag() -> None:
    assert "person_aware_nav" in ALLOWED_NAVIGATOR_OVERRIDES
    # The pre-existing flags are untouched (additive one-liner).
    assert {"value_directed_search", "detection_lock_on"} <= ALLOWED_NAVIGATOR_OVERRIDES
    # Card VS-4 added exactly one name (``lock_on_verify_on_approach``) in
    # Wave 2; card RM-3 (SLAM_M_PLAN.md r2, Wave 3) added exactly one more
    # (``route_memory``, the enumerated amendment RM2_STATUS.md §8.2 handoff 2
    # asked for). The count stays EXACT so no flag can appear undeclared.
    assert len(ALLOWED_NAVIGATOR_OVERRIDES) == 5
