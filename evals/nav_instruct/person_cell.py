"""Declared-bystander clearance sweep for D-15 (card D15-C, additive cell).

Why this cell exists
--------------------
``nav-object_goal-D-15-109547e2`` flipped SUCCESS -> FAIL on the owner-authorized
``person_stop_m`` 1.0 -> 1.2 retune (E5, 2026-08-10). The mechanism, bisected in
``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §1.1: the headless world places a
DEFAULT OWNER at (2.00, -0.50) in every nav_instruct episode, the reactive gate
correctly treats a visible owner as a person, and at 1.2632 m of clearance the
predictive person stop at cruise speed (1.3020 m) vetoes translation on every
tick — invisibly to the planner, which replans the same blocked route until the
budget expires.

Two gaps, one of them this cell's:

* the CAPABILITY gap is card D15-B (``person_aware_nav``);
* the EVAL-HONESTY gap is that the bystander was never DECLARED. No frozen row
  says "there is a stationary human 1.26 m off this route", nothing publishes
  that human to the planner, and no cell exercised the class.

This cell declares one, three ways, and measures what each declaration buys:

``none``            the frozen condition — the planner is blind (D-15 itself);
``owner_track``     declared as the owner (planner cost weight 0.6);
``dynamic_agents``  declared as a bystander/stranger (planner cost weight 2.5).

The route is the ray from D-15's own start pose THROUGH the real default
bystander — free of static obstacles for 10 m (measured) — and the bystander is
slid along it to set the clearance. Everything else is production: the real
pipeline, the real planner, the real world, and the real, untouched
``apply_reactive_safety`` as the disposer of every tick.

Deliberately NOT a counterfactual at ``person_stop_m = 1.0``: E5's undercut
guard makes that policy unconstructible on this tree (``ValueError``,
adjudication #12). The 1.0 outcome is DERIVED from D15-A's formula and labelled
``derived-not-run`` in the report.

Discipline: this cell writes its own report file into a directory the caller
names. It NEVER appends to ``evals/nav_instruct/results/ledger.jsonl``, never
writes an episode file, and never touches a frozen artifact.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.nav_instruct.generator import EpisodeSpec, generate_minival
from parcel_robot.headless_city import (
    DEFAULT_ROBOT_CONFIG,
    HeadlessCityQualityHarness,
    HeadlessCityWorld,
    _nav_observation,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.base import GoalPose, Mission
from parcel_robot.navigation.person_keepout import (
    compliant_speed,
    keepout_radius_m,
    predictive_person_stop_m,
)
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.reactive_safety import apply_reactive_safety

#: The episode this cell is the declared-bystander variant of.
D15_EPISODE_ID = "nav-object_goal-D-15-109547e2"
D15_EPISODE_VERSION = "v4"
D15_EPISODE_SEED = 20260804
#: The world's undeclared default bystander (headless_city owner mocap).
DEFAULT_BYSTANDER_XY = (2.00, -0.50)
#: Length of the synthetic point goal along the route ray. The ray is clear of
#: static obstacles for 10 m from the start (measured with
#: ``HeadlessCityWorld.truth_minimum_clearance``), so what the run measures is
#: the bystander and nothing else.
ROUTE_LENGTH_M = 8.0
#: Cruise speed of the grid_v1 controller (``configs/navigation/models/grid.yaml``)
#: — the speed the frozen D-15 rows were measured at, and the speed the veto
#: boundary is quoted for.
CRUISE_SPEED_MPS = 0.85
#: D-15's own measured clearance, and the pin the declaration probe runs at.
D15_CLEARANCE_M = 1.2632
#: Clearances swept, spanning the gate's predictive boundary (1.3020 m at cruise)
#: and its standing-start floor (``person_stop_m`` = 1.20 m).
DEFAULT_CLEARANCES_M: tuple[float, ...] = (1.10, 1.2632, 1.35, 1.60, 2.20, 3.00)
#: How the bystander is published to the PLANNER. The gate always sees them.
DECLARATION_CHANNELS: tuple[str, ...] = ("none", "owner_track", "dynamic_agents")
#: Net along-route progress below this is "did not get going".
PROGRESS_EPSILON_M = 0.50
#: Lateral excursion at or above this is a route DETOUR rather than a straight pass.
DETOUR_LATERAL_M = 0.30
#: Fraction of translating ticks the gate must veto for the outcome to be a
#: DEADLOCK rather than a voluntary hold.
DEADLOCK_VETO_FRACTION = 0.50

DOES_NOT_PROVE: tuple[str, ...] = (
    "does not prove the retune optimal — only that the flip is caused by it",
    "does not prove detour safety at higher pedestrian density (one bystander)",
    (
        "does not re-measure any frozen row: this cell runs its own synthetic "
        "placements and writes its own report"
    ),
    (
        "the person_stop_m=1.0 row is DERIVED from the gate's inequality, not "
        "run (E5's undercut guard refuses the policy)"
    ),
    (
        "outcomes are budget-limited: a run that neither deadlocks nor arrives "
        "inside max_steps is reported as it ended, not extrapolated"
    ),
)


@dataclass(frozen=True)
class CellOutcome:
    """One (clearance, declaration, flag) run of the declared-bystander episode."""

    clearance_m: float
    declaration: str
    person_aware_nav: bool
    outcome: str
    steps: int
    progress_m: float
    along_route_m: float
    lateral_m: float
    passed_bystander: bool
    min_clearance_m: float
    veto_fraction: float
    blind_veto_ticks: int
    distance_to_goal_m: float
    collisions: int
    person_costs_published_ticks: int
    compliant_cap_ticks: int
    predictive_stop_at_cruise_m: float
    gate_vetoes_at_cruise: bool
    compliant_speed_mps: float
    keepout_radius_at_cruise_m: float


def d15_episode(version: str = D15_EPISODE_VERSION) -> EpisodeSpec:
    """The frozen D-15 episode spec, read (never written)."""

    for episode in generate_minival(seed=D15_EPISODE_SEED, version=version):
        if episode.episode_id == D15_EPISODE_ID:
            return episode
    raise LookupError(f"{D15_EPISODE_ID} is not in the {version} minival")


def route_frame(
    episode: EpisodeSpec,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """``(start_xy, unit, normal)`` of the ray start -> default bystander."""

    start = (float(episode.start_pose[0]), float(episode.start_pose[1]))
    dx = DEFAULT_BYSTANDER_XY[0] - start[0]
    dy = DEFAULT_BYSTANDER_XY[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 0.0:
        raise ValueError("degenerate route: bystander is at the start pose")
    unit = (dx / length, dy / length)
    return start, unit, (unit[1], -unit[0])


def bystander_position(
    episode: EpisodeSpec,
    clearance_m: float,
    *,
    envelope_m: float,
) -> tuple[float, float]:
    """Bystander ON the route at ``clearance_m`` of clearance from the start.

    The gate compares a clearance (base centre to person surface), so the centre
    distance is ``clearance + envelope`` — the same conversion
    ``apply_reactive_safety`` makes on the owner's centre distance.
    """

    start, unit, _ = route_frame(episode)
    distance = clearance_m + envelope_m
    return (start[0] + unit[0] * distance, start[1] + unit[1] * distance)


def goal_pose(episode: EpisodeSpec) -> GoalPose:
    start, unit, _ = route_frame(episode)
    return GoalPose(
        x=start[0] + unit[0] * ROUTE_LENGTH_M,
        y=start[1] + unit[1] * ROUTE_LENGTH_M,
        label="declared_bystander_cell_goal",
    )


def _declaration_payload(observation: Any, envelope_m: float) -> list[dict[str, Any]]:
    return [
        {
            "id": observation.owner.owner_id,
            "x": float(observation.owner.x),
            "y": float(observation.owner.y),
            "vx": 0.0,
            "vy": 0.0,
            "radius_m": envelope_m,
        }
    ]


def classify_outcome(
    *,
    along_route_m: float,
    lateral_m: float,
    veto_fraction: float,
    passed_bystander: bool,
) -> str:
    """Name what happened, from geometry and the gate's own verdicts.

    ``deadlock`` is the D-15 class: the gate is stopping the robot on most
    translating ticks and it never got past the human. ``yield_hold`` is the
    compliant version of the same standoff — the robot slowed itself instead of
    being stopped. ``detour``/``pass`` mean it got by; ``detour_incomplete``
    means it was routing around when the step budget ran out.
    """

    if passed_bystander:
        return "detour" if lateral_m >= DETOUR_LATERAL_M else "pass"
    if veto_fraction >= DEADLOCK_VETO_FRACTION:
        return "deadlock"
    if lateral_m >= DETOUR_LATERAL_M:
        return "detour_incomplete"
    if along_route_m < PROGRESS_EPSILON_M:
        return "yield_hold"
    return "yield_progress"


def run_cell(
    clearance_m: float,
    *,
    declaration: str,
    person_aware_nav: bool,
    world: HeadlessCityWorld,
    harness: HeadlessCityQualityHarness,
    episode: EpisodeSpec,
    max_steps: int = 800,
) -> CellOutcome:
    """Run the declared-bystander episode once."""

    if declaration not in DECLARATION_CHANNELS:
        raise ValueError(f"declaration must be one of {DECLARATION_CHANNELS}")
    policy = harness.reactive_safety
    envelope_m = policy.owner_collision_envelope_m
    bystander = bystander_position(episode, clearance_m, envelope_m=envelope_m)
    start_pose = (
        float(episode.start_pose[0]),
        float(episode.start_pose[1]),
        math.atan2(
            bystander[1] - float(episode.start_pose[1]),
            bystander[0] - float(episode.start_pose[0]),
        ),
    )
    world.reset(robot=start_pose, owner=bystander, restore_semantics=True)

    goal = goal_pose(episode)
    navigator = DirectiveNavigator.from_config(
        harness.navigation_config, person_aware_nav=person_aware_nav
    )
    mission = Mission(directive="declared-bystander cell: hold the route", goal=goal)
    navigator.start(mission)

    start_xy, unit, normal = route_frame(episode)
    previous = (start_pose[0], start_pose[1])
    progress_m = 0.0
    lateral_m = 0.0
    along_m = 0.0
    min_clearance_m = math.inf
    vetoes = 0
    blind_vetoes = 0
    translating = 0
    steps = 0

    def _record(point: tuple[float, float]) -> None:
        nonlocal progress_m, lateral_m, along_m, min_clearance_m, previous
        progress_m += math.dist(point, previous)
        previous = point
        offset = (point[0] - start_xy[0], point[1] - start_xy[1])
        along_m = offset[0] * unit[0] + offset[1] * unit[1]
        lateral_m = max(lateral_m, abs(offset[0] * normal[0] + offset[1] * normal[1]))
        min_clearance_m = min(min_clearance_m, math.dist(point, bystander) - envelope_m)

    try:
        # Same tick shape as ``NavInstructRunner._run_navigation``: observe,
        # plan, gate, apply, step — so an outcome here means what it means there.
        for _ in range(max_steps):
            steps += 1
            observation = world.observe()
            _record((float(observation.robot.x), float(observation.robot.y)))
            nav_observation = _nav_observation(
                observation,
                measured_velocity=world.command,
                stop_confirmed=world.stopped,
                settled_linear_speed_mps=harness._settled_linear_speed_mps,
                settled_yaw_speed_rad_s=harness._settled_yaw_speed_rad_s,
            )
            # THE DECLARATION. ``none`` is the frozen condition: the planner
            # cannot know a human is standing on its route, which is exactly the
            # eval-honesty gap D-15 exposed (FOLLOWUP_DESIGNS.md §1.2). The other
            # two publish the bystander in the payload the runtime already
            # publishes and ``grid_navigator`` already consumes.
            if declaration != "none":
                nav_observation.extras[declaration] = _declaration_payload(
                    observation, envelope_m
                )
            command = navigator.step(nav_observation)
            note = command.note or ""
            requested = (
                VelocityCommand()
                if command.stop
                else VelocityCommand(command.vx, command.vy, command.vyaw)
            )
            velocity, _gate_note = apply_reactive_safety(
                requested,
                observation,
                policy=policy,
                owner_orbit=False,
                orbit_radius_m=0.0,
                now=observation.timestamp,
                require_fresh_telemetry=False,
            )
            if math.hypot(requested.vx, requested.vy) > 1e-6:
                translating += 1
                if math.hypot(velocity.vx, velocity.vy) <= 1e-9:
                    vetoes += 1
                    # The D-15 signature: the gate stopped the robot on a tick
                    # the planner believed was a clear, planned route.
                    if "status=planned" in note and "|clear" in note:
                        blind_vetoes += 1
            world.apply(velocity)
            if command.stop or navigator.done():
                break
            world.step()
        final = world.observe()
        _record((float(final.robot.x), float(final.robot.y)))
    finally:
        world.stop()
        navigator.close()

    veto_fraction = vetoes / translating if translating else 0.0
    passed = along_m > clearance_m + envelope_m
    outcome = classify_outcome(
        along_route_m=along_m,
        lateral_m=lateral_m,
        veto_fraction=veto_fraction,
        passed_bystander=passed,
    )

    return CellOutcome(
        clearance_m=round(clearance_m, 6),
        declaration=declaration,
        person_aware_nav=person_aware_nav,
        outcome=outcome,
        steps=steps,
        progress_m=round(progress_m, 6),
        along_route_m=round(along_m, 6),
        lateral_m=round(lateral_m, 6),
        passed_bystander=bool(passed),
        min_clearance_m=round(min_clearance_m, 6),
        veto_fraction=round(veto_fraction, 6),
        blind_veto_ticks=blind_vetoes,
        distance_to_goal_m=round(math.dist(previous, (goal.x, goal.y)), 6),
        collisions=int(world.collision_count),
        person_costs_published_ticks=int(navigator.person_costs_published_ticks),
        compliant_cap_ticks=int(navigator.person_compliant_cap_ticks),
        predictive_stop_at_cruise_m=round(
            predictive_person_stop_m(policy, CRUISE_SPEED_MPS), 6
        ),
        gate_vetoes_at_cruise=bool(
            clearance_m <= predictive_person_stop_m(policy, CRUISE_SPEED_MPS)
        ),
        compliant_speed_mps=round(compliant_speed(clearance_m, policy=policy), 6),
        keepout_radius_at_cruise_m=round(keepout_radius_m(policy, CRUISE_SPEED_MPS), 6),
    )


def derived_person_stop_row(
    old_person_stop_m: float,
    clearance_m: float,
    *,
    reaction_time_s: float,
    speed_mps: float = CRUISE_SPEED_MPS,
) -> dict[str, Any]:
    """The un-runnable counterfactual, computed from the gate's own inequality.

    E5's guard refuses ``person_stop_m`` below ``SafetyEnvelope.person_stop(0)``
    (adjudication #12), so this arm cannot be RUN on this tree. It is arithmetic
    on the same expression the gate evaluates, and it is labelled as such.
    """

    threshold = old_person_stop_m + speed_mps * reaction_time_s
    return {
        "label": "derived-not-run",
        "person_stop_m": old_person_stop_m,
        "clearance_m": round(clearance_m, 6),
        "speed_mps": speed_mps,
        "predictive_stop_m": round(threshold, 6),
        "gate_vetoes": bool(clearance_m <= threshold),
        "why_not_run": (
            "ReactiveSafetyPolicy refuses person_stop_m below "
            "SafetyEnvelope.person_stop(0.0) (E5 undercut guard)"
        ),
    }


def run_sweep(
    clearances_m: tuple[float, ...] = DEFAULT_CLEARANCES_M,
    *,
    arms: tuple[bool, ...] = (False, True),
    declarations: tuple[str, ...] = ("none", "dynamic_agents"),
    probe_declarations: tuple[str, ...] = DECLARATION_CHANNELS,
    max_steps: int = 800,
    robot_config: str | Path = DEFAULT_ROBOT_CONFIG,
    episode_version: str = D15_EPISODE_VERSION,
) -> dict[str, Any]:
    """Sweep the bystander's clearance across the gate's veto boundary.

    Three measurements, one world:

    * ``signature`` — the frozen condition (UNDECLARED bystander at D-15's own
      clearance, flag off): does the deadlock reproduce?
    * ``sweep`` — clearance steps either side of the boundary, both flag arms;
    * ``declaration_probe`` — the pin clearance under each declaration channel,
      both arms: what does DECLARING buy, and what does the flag add?
    """

    episode = d15_episode(episode_version)
    world = HeadlessCityWorld()
    harness = HeadlessCityQualityHarness(world, robot_config=robot_config)
    policy = harness.reactive_safety

    def _run(clearance: float, channel: str, flag: bool) -> CellOutcome:
        return run_cell(
            clearance,
            declaration=channel,
            person_aware_nav=flag,
            world=world,
            harness=harness,
            episode=episode,
            max_steps=max_steps,
        )

    signature = _run(D15_CLEARANCE_M, "none", False)
    sweep = [
        _run(clearance, channel, flag)
        for channel in declarations
        for clearance in clearances_m
        for flag in arms
    ]
    probe = [
        _run(D15_CLEARANCE_M, channel, flag)
        for channel in probe_declarations
        for flag in arms
    ]
    start_xy, unit, _ = route_frame(episode)
    return {
        "cell_id": "d15-declared-bystander-sweep",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "episode_id": episode.episode_id,
        "episode_version": episode_version,
        "route": {
            "start_xy": list(start_xy),
            "unit": list(unit),
            "length_m": ROUTE_LENGTH_M,
            "goal_xy": [goal_pose(episode).x, goal_pose(episode).y],
            "default_bystander_xy": list(DEFAULT_BYSTANDER_XY),
        },
        "policy": {
            "person_stop_m": policy.person_stop_m,
            "person_slow_m": policy.person_slow_m,
            "owner_slow_m": policy.owner_slow_m,
            "reaction_time_s": policy.reaction_time_s,
            "owner_collision_envelope_m": policy.owner_collision_envelope_m,
        },
        "cruise_speed_mps": CRUISE_SPEED_MPS,
        "veto_boundary_m": round(predictive_person_stop_m(policy, CRUISE_SPEED_MPS), 6),
        "veto_boundary_formula": "person_stop_m + speed * reaction_time_s",
        "standing_start_boundary_m": policy.person_stop_m,
        "max_steps": max_steps,
        "signature": asdict(signature),
        "sweep_declarations": list(declarations),
        "sweep": [asdict(item) for item in sweep],
        "declaration_probe": [asdict(item) for item in probe],
        "counterfactual": derived_person_stop_row(
            1.0,
            D15_CLEARANCE_M,
            reaction_time_s=policy.reaction_time_s,
        ),
        "does_not_prove": list(DOES_NOT_PROVE),
    }


def write_report(payload: dict[str, Any], out_dir: str | Path) -> Path:
    """Write the sweep report. Never the ledger, never a frozen artifact."""

    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{payload['cell_id']}-{payload['generated_utc']}.json"
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def _rows(outcomes: list[dict[str, Any]]) -> list[str]:
    return [
        "| {clearance_m} | {declaration} | {person_aware_nav} | {outcome} "
        "| {along_route_m} | {lateral_m} | {veto_fraction} | {blind_veto_ticks} "
        "| {min_clearance_m} | {compliant_cap_ticks} |".format(**row)
        for row in outcomes
    ]


def markdown_table(payload: dict[str, Any]) -> str:
    header = [
        (
            f"veto boundary at cruise {payload['cruise_speed_mps']} m/s: "
            f"{payload['veto_boundary_m']} m "
            f"({payload['veto_boundary_formula']}); standing start: "
            f"{payload['standing_start_boundary_m']} m"
        ),
        "",
        (
            "| clearance | declared | flag | outcome | along | lateral | veto frac "
            "| blind vetoes | min clearance | cap ticks |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    body = _rows([payload["signature"], *payload["sweep"], *payload["declaration_probe"]])
    return "\n".join([*header, *body])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "results" / "person_cell",
        help="directory for this cell's own report (never the ledger)",
    )
    parser.add_argument("--max-steps", type=int, default=800)
    parser.add_argument(
        "--clearance",
        type=float,
        action="append",
        default=[],
        help="clearance (m) to sweep; repeatable (default: the registered sweep)",
    )
    parser.add_argument(
        "--declaration",
        action="append",
        default=[],
        choices=sorted(DECLARATION_CHANNELS),
        help=(
            "channel(s) the sweep declares the bystander on; repeatable "
            "(default: 'none' — the frozen condition — and 'dynamic_agents')"
        ),
    )
    parser.add_argument("--episode-version", default=D15_EPISODE_VERSION)
    args = parser.parse_args(argv)

    clearances = tuple(args.clearance) if args.clearance else DEFAULT_CLEARANCES_M
    payload = run_sweep(
        clearances,
        declarations=tuple(args.declaration) if args.declaration else ("none", "dynamic_agents"),
        max_steps=args.max_steps,
        episode_version=args.episode_version,
    )
    path = write_report(payload, args.out)
    print(markdown_table(payload))
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI
    raise SystemExit(main())
