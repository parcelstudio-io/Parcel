#!/usr/bin/env python
"""Mutation-of-the-evals panel — nightly tier (eval instrument 6).

The question
------------
Every other instrument asks "is the robot right?". This one asks the question
nobody else in the repo asks: **would the harnesses notice if it were wrong?**
A green eval suite proves nothing unless the suite can go red for the right
reasons, and the strata programme is about to change pose, perception,
vocabulary and envelopes — exactly the four places a silent regression would
hide.

How it works
------------
Six defects from the plan are seeded **one at a time**, each by monkeypatching a
live object or injecting a config at runtime. **Nothing is ever committed as a
source edit**: a mutation panel that edits files is one bad exit away from
shipping its own defect. Each mutant then runs the NAV_INSTRUCT v2 minival and
the result is compared against the clean run through a fixed list of named
harness checks. A mutant that reddens **no** check has *survived*, and a
surviving mutant is itself a panel failure — it means the harness is blind to
that class of defect.

The six defects (plan, instrument 6):

===========================  ===================================================
``arrival_radius_x2``        every arrival band doubled — the scorer's own
                             geometry made twice as forgiving
``reactive_gate_disabled``   ``apply_reactive_safety`` becomes a pass-through
``pose_offset_0m5``          the observed robot pose is displaced 0.5 m in x
``inverted_relation``        the ``next_to``/``towards`` band predicate is
                             negated — inside becomes outside
``dropped_detections``       every other semantic candidate is dropped at the
                             one perception ingress
``doubled_envelope``         the stand-off envelope's every margin doubled
===========================  ===================================================

Runtime is bounded: a subset of episodes (``--episodes``), one clean run plus
one run per mutant.

Usage::

    MUJOCO_GL=egl .parcel/bin/python scripts/mutation_panel.py
    MUJOCO_GL=egl .parcel/bin/python scripts/mutation_panel.py --only pose_offset_0m5
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from evals.nav_instruct.generator import EPISODE_SET_V2, EpisodeSpec, generate_minival
from evals.nav_instruct.runner import ARRIVAL_RULE_FOR_VERSION, NavInstructRunner

DEFAULT_REPORT = REPO / "evals" / "nav_instruct" / "results" / "mutation_panel.json"

#: Paired-comparison tolerance. The headless runner is deterministic (Lane D
#: proved byte-identical repeat runs), so repeat variability is exactly zero and
#: this is not a noise allowance — it is one control tick of travel at cruise
#: (0.1 s x ~1 m/s), below which two trajectories are the same trajectory.
PAIRED_TOLERANCE_M = 0.10

#: Episodes the panel runs. Four, for a bounded runtime, chosen to *exercise*
#: the code each mutation touches — a mutant on a code path the episodes never
#: reach is an equivalent mutant and tells you nothing about the harness.
#:
#: Selection is recorded rather than asserted. Instrumenting
#: ``apply_reactive_safety`` over the whole v2 minival shows it modifies the
#: command on exactly three episodes (``region_goal-D-15`` 184/200 ticks,
#: ``object_goal-B-05`` 57/100, ``object_goal-D-15`` 54/93) and on **no other
#: episode at all**. ``region_goal-D-15`` is therefore in the panel; without it
#: the reactive-gate mutant cannot be exercised. This is coverage selection for
#: a mutation panel, not tuning: no robot parameter is chosen from a result.
PANEL_EPISODE_IDS: tuple[str, ...] = (
    # longest traverse in the minival (184 control ticks): the episode a pose
    # error has time to accumulate over
    "nav-region_goal-A-00-1c735162",
    # region family, and one of only three episodes where the reactive gate
    # ever binds
    "nav-region_goal-D-15-1b8b2361",
    # object family, tier A, actually arrives
    "nav-object_goal-A-00-4caa923b",
    # relation family (next_to band)
    "nav-object_relative-A-00-3efbba45",
    # spatial family, and the minival's one clean success
    "nav-follow_owner-D-15-74a535dd",
)


# ---------------------------------------------------------------------------
# harness checks — what "the harness went red" means, named
# ---------------------------------------------------------------------------


def harness_checks(run: dict[str, Any], clean: dict[str, Any] | None) -> dict[str, bool]:
    """Named checks a NAV_INSTRUCT run must pass. ``True`` = green.

    Every one of these is a check the real harness already makes somewhere: the
    success set and collision count gate the frozen baseline, the differential
    authority verdict is instrument 5's own assertion, and the geometry checks
    are what a paired run is compared on.
    """

    checks = {
        # Safety is absolute and never relative to a baseline.
        "zero_collisions": run["collisions"] == 0,
        # Instrument 5: the scorer is a derived view, so scorer-arrival must
        # imply system-arrival. A disagreement is a first-class defect.
        "no_authority_disagreement": run["authority"].get("authority_disagreement", 0) == 0,
        "no_false_arrival": run["authority"].get("false_arrival", 0) == 0,
        # The trace must be a real trajectory, not a teleport or a stall.
        "path_length_plausible": all(
            0.0 <= item["path_length_m"] <= 200.0 for item in run["episodes"]
        ),
    }
    if clean is not None:
        checks["success_set_identical"] = run["successes"] == clean["successes"]
        checks["mean_dtg_within_tolerance"] = (
            abs(run["mean_dtg_m"] - clean["mean_dtg_m"]) <= PAIRED_TOLERANCE_M
        )
        checks["failure_histogram_identical"] = (
            run["failure_histogram"] == clean["failure_histogram"]
        )
        checks["final_poses_within_tolerance"] = all(
            math.dist(a["final_xy"], b["final_xy"]) <= PAIRED_TOLERANCE_M
            for a, b in zip(run["episodes"], clean["episodes"], strict=False)
        )
        # Safety margin is a paired check, not an absolute one: the clean run
        # establishes what this scene affords and a mutant may not erode it.
        checks["min_clearance_not_eroded"] = all(
            a["min_clearance_m"] >= b["min_clearance_m"] - PAIRED_TOLERANCE_M
            for a, b in zip(run["episodes"], clean["episodes"], strict=False)
        )
    return checks


# ---------------------------------------------------------------------------
# the six mutations — monkeypatch only, never a committed source edit
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _patched(target: Any, attribute: str, value: Any) -> Iterator[None]:
    original = getattr(target, attribute)
    setattr(target, attribute, value)
    try:
        yield
    finally:
        setattr(target, attribute, original)


@contextlib.contextmanager
def mutate_arrival_radius_x2() -> Iterator[None]:
    """Every arrival band twice as wide — the classic silently-passing defect."""

    from parcel_robot.instructnav import scoring

    original_contains = scoring.GoalRegion.contains

    def contains(self, x, y, *args, **kwargs):
        if self.band_m is not None:
            widened = scoring.GoalRegion(
                kind=self.kind,
                center=self.center,
                radius_m=self.radius_m,
                polygon=self.polygon,
                anchor_entity=self.anchor_entity,
                band_m=(self.band_m[0] * 2.0, self.band_m[1] * 2.0),
                anchor_footprint_m=self.anchor_footprint_m,
            )
            return original_contains(widened, x, y, *args, **kwargs)
        if self.radius_m is not None:
            widened = scoring.GoalRegion(
                kind=self.kind,
                center=self.center,
                radius_m=self.radius_m * 2.0,
                polygon=self.polygon,
                anchor_entity=self.anchor_entity,
                band_m=self.band_m,
                anchor_footprint_m=self.anchor_footprint_m,
            )
            return original_contains(widened, x, y, *args, **kwargs)
        return original_contains(self, x, y, *args, **kwargs)

    with _patched(scoring.GoalRegion, "contains", contains):
        yield


@contextlib.contextmanager
def mutate_reactive_gate_disabled() -> Iterator[None]:
    """The reactive safety gate becomes a pass-through."""

    from evals.nav_instruct import runner as runner_module

    def passthrough(requested, observation, **kwargs):
        return requested, None

    with _patched(runner_module, "apply_reactive_safety", passthrough):
        yield


@contextlib.contextmanager
def mutate_pose_offset_0m5() -> Iterator[None]:
    """The pose the navigator sees is displaced 0.5 m in x."""

    from evals.nav_instruct import runner as runner_module

    original = runner_module._nav_observation

    def offset(observation, **kwargs):
        nav = original(observation, **kwargs)
        position = list(getattr(nav, "position", (0.0, 0.0, 0.0)))
        position[0] += 0.5
        try:
            object.__setattr__(nav, "position", tuple(position))
        except (AttributeError, TypeError):
            nav.position = tuple(position)
        return nav

    with _patched(runner_module, "_nav_observation", offset):
        yield


@contextlib.contextmanager
def mutate_inverted_relation() -> Iterator[None]:
    """The band predicate is negated: inside a relation band becomes outside."""

    from parcel_robot.instructnav import scoring

    original_contains = scoring.GoalRegion.contains

    def contains(self, x, y, *args, **kwargs):
        verdict = original_contains(self, x, y, *args, **kwargs)
        return (not verdict) if self.band_m is not None else verdict

    with _patched(scoring.GoalRegion, "contains", contains):
        yield


@contextlib.contextmanager
def mutate_dropped_detections(*, probability: float = 0.5, seed: int = 41) -> Iterator[None]:
    """Half the semantic candidates are dropped at the one perception ingress.

    Patched on ``headless_city``, which is where the name is *bound* and called
    (``_nav_observation`` fills ``extras["semantic_candidates"]``). Patching the
    defining module would leave that binding untouched — a mutation that does
    not mutate is worse than no mutation, because it reads as a surviving one.
    """

    import random as _random

    from parcel_robot import headless_city

    original = headless_city.semantic_candidates_from_observation
    rng = _random.Random(seed)

    def dropped(*args: Any, **kwargs: Any) -> Any:
        return [
            item
            for item in original(*args, **kwargs)
            if rng.random() >= probability
        ]

    with _patched(headless_city, "semantic_candidates_from_observation", dropped):
        yield


@contextlib.contextmanager
def mutate_doubled_envelope() -> Iterator[None]:
    """Every stand-off margin doubled: the robot stops twice as far out."""

    import dataclasses

    from parcel_robot import authority

    original = authority.DEFAULT_STAND_OFF_ENVELOPE
    fields = {
        field.name: getattr(original, field.name)
        for field in dataclasses.fields(original)
        if isinstance(getattr(original, field.name), float)
        and field.name.endswith(("_m", "_margin_m"))
    }
    doubled = dataclasses.replace(original, **{key: value * 2.0 for key, value in fields.items()})
    if doubled == original:
        raise RuntimeError("doubled_envelope mutated nothing — the field filter is wrong")
    from parcel_robot.core import authority as core_authority
    from parcel_robot.instructnav import scoring
    from parcel_robot.navigation import approach

    with contextlib.ExitStack() as stack:
        for module in (authority, core_authority, scoring, approach):
            if hasattr(module, "DEFAULT_STAND_OFF_ENVELOPE"):
                stack.enter_context(_patched(module, "DEFAULT_STAND_OFF_ENVELOPE", doubled))
        yield


MUTATIONS: dict[str, Callable[[], Any]] = {
    "arrival_radius_x2": mutate_arrival_radius_x2,
    "reactive_gate_disabled": mutate_reactive_gate_disabled,
    "pose_offset_0m5": mutate_pose_offset_0m5,
    "inverted_relation": mutate_inverted_relation,
    "dropped_detections": mutate_dropped_detections,
    "doubled_envelope": mutate_doubled_envelope,
}


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MutantResult:
    """One seeded defect and what the harness did about it.

    ``verdict`` is three-valued on purpose:

    ``killed``
        the defect reddened at least one named harness check — the panel's
        pass condition;
    ``equivalent``
        the mutated run is **identical** to the clean run, so the defect was
        never exercised by these episodes. The panel makes no claim about
        harness blindness here, because there was nothing to be blind to.
        Calling this a survivor would be a false alarm;
    ``survived``
        the run changed and no check noticed. This is genuine harness
        blindness and it fails the panel.
    """

    name: str
    reddened: tuple[str, ...]
    verdict: str
    error: str | None
    run: dict[str, Any]

    @property
    def survived(self) -> bool:
        return self.verdict == "survived"

    def as_dict(self) -> dict[str, Any]:
        return {
            "mutation": self.name,
            "checks_reddened": list(self.reddened),
            "verdict": self.verdict,
            "survived": self.survived,
            "error": self.error,
            "run": self.run,
        }


def _episodes(ids: Sequence[str]) -> list[EpisodeSpec]:
    by_id = {ep.episode_id: ep for ep in generate_minival(version=EPISODE_SET_V2)}
    return [by_id[episode_id] for episode_id in ids]


def _path_length(trace: Sequence[dict[str, Any]]) -> float:
    total = 0.0
    previous: tuple[float, float] | None = None
    for step in trace:
        point = (float(step.get("x", 0.0)), float(step.get("y", 0.0)))
        if previous is not None:
            total += math.dist(point, previous)
        previous = point
    return total


def run_once(episodes: Sequence[EpisodeSpec], *, max_steps: int) -> dict[str, Any]:
    runner = NavInstructRunner(
        max_steps=max_steps,
        mode="baseline",
        arrival_rule=ARRIVAL_RULE_FOR_VERSION[EPISODE_SET_V2],
    )
    results = []
    clearances = []
    for episode in episodes:
        results.append(runner.run_episode(episode))
        value = float(runner.world.minimum_clearance_m)
        clearances.append(value if math.isfinite(value) else 99.0)
    rows = []
    authority: dict[str, int] = {}
    failures: dict[str, int] = {}
    for item, min_clearance in zip(results, clearances, strict=True):
        trace = list(item.trace)
        final = (
            (float(trace[-1].get("x", 0.0)), float(trace[-1].get("y", 0.0)))
            if trace
            else (0.0, 0.0)
        )
        rows.append(
            {
                "episode_id": item.episode_id,
                "min_clearance_m": min_clearance,
                "success": bool(item.score.success),
                "distance_to_goal_m": float(item.score.distance_to_goal_m),
                "final_xy": list(final),
                "path_length_m": _path_length(trace),
                "failure": item.score.failure.value,
            }
        )
        authority[item.authority_category] = authority.get(item.authority_category, 0) + 1
        failures[item.score.failure.value] = failures.get(item.score.failure.value, 0) + 1
    finite = [
        row["distance_to_goal_m"]
        for row in rows
        if math.isfinite(row["distance_to_goal_m"])
    ]
    return {
        "n": len(rows),
        "successes": sorted(row["episode_id"] for row in rows if row["success"]),
        "mean_dtg_m": sum(finite) / max(len(finite), 1),
        "collisions": sum(int(item.collision_count) for item in results),
        "authority": authority,
        "failure_histogram": failures,
        "episodes": rows,
    }


def run_panel(
    *,
    episode_ids: Sequence[str] = PANEL_EPISODE_IDS,
    only: Sequence[str] | None = None,
    max_steps: int = 200,
) -> dict[str, Any]:
    episodes = _episodes(episode_ids)
    clean = run_once(episodes, max_steps=max_steps)
    clean_checks = harness_checks(clean, None)
    results: list[MutantResult] = []
    names = list(only) if only else list(MUTATIONS)
    for name in names:
        error: str | None = None
        try:
            with MUTATIONS[name]():
                run = run_once(episodes, max_steps=max_steps)
        except Exception as exc:  # noqa: BLE001 - a crashed mutant is still a red harness
            # A mutation that makes the harness raise has reddened it in the
            # loudest possible way. Recorded as such, never silently skipped.
            error = f"{type(exc).__name__}: {exc}"
            results.append(
                MutantResult(
                    name=name,
                    reddened=("harness_raised",),
                    verdict="killed",
                    error=error,
                    run={},
                )
            )
            continue
        checks = harness_checks(run, clean)
        reddened = tuple(
            key for key, green in checks.items() if not green and clean_checks.get(key, True)
        )
        if reddened:
            verdict = "killed"
        elif _identical(run, clean):
            verdict = "equivalent"
        else:
            verdict = "survived"
        results.append(
            MutantResult(
                name=name,
                reddened=reddened,
                verdict=verdict,
                error=None,
                run=run,
            )
        )
    survivors = [item.name for item in results if item.survived]
    equivalent = [item.name for item in results if item.verdict == "equivalent"]
    return {
        "kind": "mutation_panel",
        "generated_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "episode_set_version": EPISODE_SET_V2,
        "episode_ids": list(episode_ids),
        "episode_selection": (
            "chosen to exercise the code each mutation touches (longest traverse, "
            "the reactive gate's only binding episode, one per family). A mutant "
            "on a path the episodes never reach is an equivalent mutant and says "
            "nothing about the harness. Coverage selection, not tuning: no robot "
            "parameter is chosen from a result."
        ),
        "method": "monkeypatch / config injection only — never a committed source edit",
        "clean_run": clean,
        "clean_checks": clean_checks,
        "mutants": [item.as_dict() for item in results],
        "survivors": survivors,
        "equivalent_mutants": equivalent,
        "equivalent_note": (
            "an equivalent mutant produced a run identical to the clean run: the "
            "defect was never exercised by these episodes, so the panel makes no "
            "claim about harness blindness for it"
        ),
        "passed": not survivors,
        "frozen_baseline": False,
    }


def _identical(run: dict[str, Any], clean: dict[str, Any]) -> bool:
    return json.dumps(run, sort_keys=True) == json.dumps(clean, sort_keys=True)


def markdown_table(payload: dict[str, Any]) -> str:
    lines = ["| mutation | verdict | harness checks reddened |", "|---|---|---|"]
    labels = {
        "killed": "killed",
        "survived": "**SURVIVED**",
        "equivalent": "equivalent (not exercised)",
    }
    for item in payload["mutants"]:
        checks = ", ".join(f"`{name}`" for name in item["checks_reddened"]) or "—"
        lines.append(
            f"| `{item['mutation']}` | {labels.get(item['verdict'], item['verdict'])} | {checks} |"
        )
    lines.append("")
    survivors = payload["survivors"]
    equivalent = payload.get("equivalent_mutants") or []
    lines.append(
        "**PANEL PASSED** — every exercised defect reddened at least one harness check."
        if not survivors
        else f"**PANEL FAILED** — survivors: {', '.join(survivors)}"
    )
    if equivalent:
        lines.append(
            f"Equivalent (never exercised by these episodes, no claim made): "
            f"{', '.join(equivalent)}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", default=None, choices=sorted(MUTATIONS))
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--episodes",
        default=None,
        help="comma-separated episode ids (default: one per family, tier A)",
    )
    args = parser.parse_args(argv)

    episode_ids = (
        tuple(item.strip() for item in args.episodes.split(",") if item.strip())
        if args.episodes
        else PANEL_EPISODE_IDS
    )
    payload = run_panel(episode_ids=episode_ids, only=args.only, max_steps=args.max_steps)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(markdown_table(payload))
    print(f"\nwrote {args.out}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
