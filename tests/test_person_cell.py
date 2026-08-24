"""Card D15-C — the declared-bystander cell: geometry, honesty, and the signature.

The cell's job is to make the D-15 class VISIBLE: a stationary human standing on
the route, declared, at a clearance the run gets to choose. These tests pin the
parts that must not drift:

* the route geometry is the ray from D-15's own start pose through the world's
  real (undeclared) default bystander, and ``clearance`` means what the gate
  means by it — base centre to person SURFACE;
* the deadlock signature reproduces end-to-end at ``person_stop_m`` = 1.2 with
  the real pipeline and the real, untouched gate: translation vetoed on
  essentially every tick, the planner still calling the route ``planned|clear``,
  and no progress;
* the ``person_stop_m`` = 1.0 counterfactual is LABELLED derived-not-run,
  because E5's undercut guard makes it unrunnable (adjudication #12);
* the cell writes only where it is told, and never the ledger.

Frozen-artifact discipline: nothing here regenerates an episode set, and the
cell reads the v4 minival without writing it.
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

from evals.nav_instruct import person_cell
from evals.nav_instruct.person_cell import (
    D15_CLEARANCE_M,
    D15_EPISODE_ID,
    DEFAULT_BYSTANDER_XY,
    bystander_position,
    classify_outcome,
    d15_episode,
    derived_person_stop_row,
    goal_pose,
    route_frame,
    run_cell,
    write_report,
)
from parcel_robot.navigation.reactive_safety import ReactiveSafetyPolicy
from parcel_robot.simulation.headless_city import HeadlessCityQualityHarness, HeadlessCityWorld

REPO = Path(__file__).resolve().parents[1]


def test_cell_is_anchored_on_the_frozen_d15_episode() -> None:
    episode = d15_episode()
    assert episode.episode_id == D15_EPISODE_ID
    assert episode.start_pose[:2] == (0.1, -0.05)


def test_route_runs_from_the_start_pose_through_the_real_bystander() -> None:
    episode = d15_episode()
    start, unit, normal = route_frame(episode)

    assert start == (0.1, -0.05)
    assert math.isclose(math.hypot(*unit), 1.0)
    assert math.isclose(unit[0] * normal[0] + unit[1] * normal[1], 0.0, abs_tol=1e-12)
    # The ray passes through the world's own undeclared default bystander.
    distance = math.dist(start, DEFAULT_BYSTANDER_XY)
    projected = (start[0] + unit[0] * distance, start[1] + unit[1] * distance)
    assert projected == pytest.approx(DEFAULT_BYSTANDER_XY, abs=1e-9)


def test_bystander_placement_means_the_gates_clearance() -> None:
    episode = d15_episode()
    policy = ReactiveSafetyPolicy()
    start, _, _ = route_frame(episode)

    placed = bystander_position(
        episode, D15_CLEARANCE_M, envelope_m=policy.owner_collision_envelope_m
    )
    centre_distance = math.dist(start, placed)

    # Centre distance minus the envelope IS the gate's clearance.
    assert centre_distance - policy.owner_collision_envelope_m == pytest.approx(
        D15_CLEARANCE_M
    )
    # And that is D-15's measured geometry: 1.8132 m of centre distance.
    assert centre_distance == pytest.approx(1.8132, abs=1e-4)
    # The goal sits well beyond the bystander, so they are ON the route.
    goal = goal_pose(episode)
    assert math.dist(start, (goal.x, goal.y)) > centre_distance


def test_outcome_classes_are_distinguishable() -> None:
    assert (
        classify_outcome(
            along_route_m=0.02, lateral_m=0.01, veto_fraction=0.99, passed_bystander=False
        )
        == "deadlock"
    )
    assert (
        classify_outcome(
            along_route_m=0.06, lateral_m=0.03, veto_fraction=0.05, passed_bystander=False
        )
        == "yield_hold"
    )
    assert (
        classify_outcome(
            along_route_m=2.0, lateral_m=2.7, veto_fraction=0.0, passed_bystander=True
        )
        == "detour"
    )
    assert (
        classify_outcome(
            along_route_m=2.0, lateral_m=0.05, veto_fraction=0.0, passed_bystander=True
        )
        == "pass"
    )
    assert (
        classify_outcome(
            along_route_m=2.3, lateral_m=2.1, veto_fraction=0.0, passed_bystander=False
        )
        == "detour_incomplete"
    )


def test_person_stop_10_counterfactual_is_labelled_derived_not_run() -> None:
    policy = ReactiveSafetyPolicy()
    row = derived_person_stop_row(
        1.0, D15_CLEARANCE_M, reaction_time_s=policy.reaction_time_s
    )

    assert row["label"] == "derived-not-run"
    assert row["predictive_stop_m"] == pytest.approx(1.1020, abs=1e-6)
    assert row["gate_vetoes"] is False  # the old arm passes this tick
    # It was unrunnable when this row was derived, which is WHY it is derived.
    # Card P1-E (2026-08-22) lowered the person floor from the shipped 1.2 m
    # social zone to the named PERSON_SOCIAL_ZONE_FLOOR_M (0.68 m), so 1.0 IS
    # constructible now. The row stays labelled "derived-not-run" because it
    # was never run, not because it could not be; what is re-pinned here is the
    # floor that does still refuse.
    assert ReactiveSafetyPolicy(person_stop_m=1.0).person_stop_m == 1.0
    with pytest.raises(ValueError, match="person_stop_m must not undercut"):
        ReactiveSafetyPolicy(person_stop_m=0.6)
    # The shipped value vetoes the same geometry at cruise.
    shipped = derived_person_stop_row(
        policy.person_stop_m, D15_CLEARANCE_M, reaction_time_s=policy.reaction_time_s
    )
    assert shipped["predictive_stop_m"] == pytest.approx(1.3020, abs=1e-6)
    assert shipped["gate_vetoes"] is True


def test_cell_writes_only_where_it_is_told_and_never_the_ledger(tmp_path: Path) -> None:
    ledger = REPO / "evals" / "nav_instruct" / "results" / "ledger.jsonl"
    before = ledger.read_bytes() if ledger.exists() else None

    payload = {"cell_id": "unit-test-cell", "generated_utc": "20260811T000000Z"}
    path = write_report(payload, tmp_path)

    assert path.parent == tmp_path
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert (ledger.read_bytes() if ledger.exists() else None) == before
    # Structural: the module's ONLY filesystem writes are the report file and
    # the directory it goes in, so no invocation can append to a ledger.
    source = Path(person_cell.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    writers = sorted(
        {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in {"write_text", "write_bytes", "open", "touch", "mkdir"}
        }
        | {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == "open"
        }
    )
    assert writers == ["mkdir", "write_text"]
    assert "run_nav_instruct_v1" not in source  # nor reach a ledger through the CLI


@pytest.mark.slow
def test_deadlock_signature_reproduces_with_an_undeclared_bystander() -> None:
    """End-to-end: the D-15 signature, on a synthetic episode, at person_stop 1.2.

    Real pipeline, real planner, real world, real ``apply_reactive_safety``. The
    bystander stands on the route at D-15's own clearance and is NOT declared to
    the planner — the frozen condition. Expected: the gate vetoes translation on
    essentially every tick, the planner keeps calling the route planned-and-clear
    while that happens, and the robot goes nowhere.
    """

    world = HeadlessCityWorld()
    harness = HeadlessCityQualityHarness(world)
    outcome = run_cell(
        D15_CLEARANCE_M,
        declaration="none",
        person_aware_nav=False,
        world=world,
        harness=harness,
        episode=d15_episode(),
        max_steps=40,
    )

    assert harness.reactive_safety.person_stop_m == 1.2
    assert outcome.outcome == "deadlock"
    assert outcome.veto_fraction >= 0.9
    assert outcome.blind_veto_ticks > 0  # vetoed while the planner said "clear"
    assert outcome.along_route_m < 0.05
    assert outcome.passed_bystander is False
    assert outcome.collisions == 0
    assert outcome.gate_vetoes_at_cruise is True
    assert outcome.predictive_stop_at_cruise_m == pytest.approx(1.3020, abs=1e-6)
    assert outcome.compliant_speed_mps == pytest.approx(0.5266, abs=1e-4)
