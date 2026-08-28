"""Deterministic navigation-generalization probes over NAV-CORE/NAV-ACCEPT.

This is research-only. It imports the frozen research harness and constructs
counterfactual arms without changing product code or persisted eval ledgers.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parcel_robot.backends.base import VelocityCommand
from parcel_robot.perception_source.selection import (
    SOURCE_LEARNED_MAP,
    SemanticSourcePolicy,
    use_learned_map,
    use_semantic_source,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NAV_CORE = ROOT / "research" / "20260824" / "nav-core"
NAV_ACCEPT = ROOT / "research" / "20260824" / "nav-accept"
for path in (NAV_CORE, NAV_ACCEPT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

nav_accept = importlib.import_module("nav_accept")
bench = nav_accept.bench
arms = nav_accept.arms
room = nav_accept.room
world_map = nav_accept.world_map
ArmShipped = nav_accept.ArmShipped

CONTROL_HZ = 10.0
NO_PATH_TICKS = 30
TEMPORAL_ARRIVAL_TICKS = 5
HELD_OUT_SEEDS = (404, 505, 606)
TYPED_TERMINALS = frozenset(arms.TYPED_FAILURES)


class BoundedNoPathArm(ArmShipped):
    """Commissioned arm plus a persistent explicit-no-path terminal."""

    arm = "bounded_no_path"

    def __init__(self, spec: Any) -> None:
        super().__init__(spec)
        self._no_path_streak = 0
        self._bounded_done = False

    def command(
        self, observation: Any, t_s: float
    ) -> tuple[VelocityCommand, bool, str]:
        requested, declared, note = super().command(observation, t_s)
        if not declared and "status=no_path" in note:
            self._no_path_streak += 1
        else:
            self._no_path_streak = 0
        if self._no_path_streak < NO_PATH_TICKS:
            return requested, declared, note
        self._bounded_done = True
        self.result.failure_type = "unreachable"
        self.result.extra["no_path_streak_ticks"] = self._no_path_streak
        self.result.extra["no_path_terminal_t_s"] = round(float(t_s), 3)
        return VelocityCommand(), False, "bounded_no_path_unreachable"

    def done(self) -> bool:
        return self._bounded_done


class TemporalArrivalArm(ArmShipped):
    """Negative-control arm: quarantine correlated arrival claims for 5 ticks."""

    arm = "temporal_arrival_5"

    def __init__(self, spec: Any) -> None:
        super().__init__(spec)
        self._arrival_streak = 0

    def command(
        self, observation: Any, t_s: float
    ) -> tuple[VelocityCommand, bool, str]:
        requested, declared, note = super().command(observation, t_s)
        if declared:
            self._arrival_streak += 1
        else:
            self._arrival_streak = 0
        self.result.extra["arrival_streak_ticks"] = self._arrival_streak
        if not declared or self._arrival_streak >= TEMPORAL_ARRIVAL_TICKS:
            return requested, declared, note
        return VelocityCommand(), False, "arrival_temporal_quarantine"


def _run(spec: Any, arm_cls: type[Any]) -> dict[str, Any]:
    use_learned_map(spec.learned_map)
    row = arm_cls(spec).run().as_row()
    row["scenario_id"] = str(getattr(spec, "scenario_id", spec.episode))
    return row


def _nominal_specs() -> list[Any]:
    specs: list[Any] = []
    for seed_index, seed in enumerate(bench.SEEDS):
        learned = world_map.seed_room_map()
        specs.extend(bench._episode_specs(seed_index, seed, learned))
    return specs


def _blocked_specs() -> list[Any]:
    specs: list[Any] = []
    episode = 300
    for seed_index, seed in enumerate(HELD_OUT_SEEDS, start=3):
        learned = world_map.seed_room_map()
        for layout in range(len(room.LAYOUTS)):
            for onset_index, onset_s in enumerate((3.0, 6.0)):
                start_index = (layout + onset_index + seed_index) % len(room.STARTS)
                goal_index = (layout * 2 + onset_index + seed_index) % len(room.PLACES)
                goal = room.PLACES[goal_index]
                spec = arms.EpisodeSpec(
                    episode=episode,
                    seed_index=seed_index,
                    seed=seed,
                    layout=layout,
                    goal_id=goal.place_id,
                    start=room.STARTS[start_index],
                    directive=bench.directive_for(goal.place_id),
                    learned_map=learned,
                    moved_obstacle_at_s=onset_s,
                    scan_gap=(1_000.0, 1_002.0),
                )
                spec.scenario_id = (
                    f"blocked-s{seed}-l{layout}-t{onset_s:.0f}-"
                    f"start{start_index}-{goal.place_id}"
                )
                specs.append(spec)
                episode += 1
    return specs


def _alias_specs() -> list[Any]:
    specs: list[Any] = []
    for seed_index, seed in enumerate(HELD_OUT_SEEDS, start=3):
        learned = world_map.seed_room_map()
        spec = arms.EpisodeSpec(
            episode=400 + seed_index,
            seed_index=seed_index,
            seed=seed,
            layout="aliased",
            goal_id=room.ALIASED_GOAL_ID,
            start=room.ALIASED_START,
            directive=bench.directive_for(room.ALIASED_GOAL_ID),
            learned_map=learned,
            kidnap_at_s=6.0,
            scan_gap=(1_000.0, 1_002.0),
        )
        spec.scenario_id = f"alias-kidnap-s{seed}"
        specs.append(spec)
    return specs


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    nonarrivals = [row for row in rows if not row["declared_arrival"]]
    times = [float(row["time_to_goal_s"]) for row in rows if row["time_to_goal_s"]]
    return {
        "episodes": len(rows),
        "declared_arrivals": sum(bool(row["declared_arrival"]) for row in rows),
        "true_arrivals": sum(bool(row["arrived"]) for row in rows),
        "false_arrivals": sum(bool(row["false_arrival"]) for row in rows),
        "contacts": sum(int(row["contacts"]) for row in rows),
        "nonarrivals": len(nonarrivals),
        "typed_nonarrivals": sum(
            str(row["failure_type"]) in TYPED_TERMINALS for row in nonarrivals
        ),
        "silent_timeouts": sum(
            row["failure_type"] == "silent_stall_step_limit" for row in rows
        ),
        "median_terminal_steps": statistics.median(
            int(row["steps"]) for row in rows
        ),
        "median_arrival_s": statistics.median(times) if times else None,
    }


def _paired_changes(
    baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    left = {row["scenario_id"]: row for row in baseline}
    right = {row["scenario_id"]: row for row in candidate}
    if left.keys() != right.keys():
        raise AssertionError("paired scenario IDs differ")
    changes = []
    for scenario_id in sorted(left):
        before, after = left[scenario_id], right[scenario_id]
        fields = (
            "declared_arrival",
            "arrived",
            "false_arrival",
            "contacts",
            "failure_type",
            "steps",
        )
        delta = {
            key: {"baseline": before[key], "candidate": after[key]}
            for key in fields
            if before[key] != after[key]
        }
        if delta:
            changes.append({"scenario_id": scenario_id, "changes": delta})
    return changes


def _h1_verdict(
    nominal_baseline: list[dict[str, Any]],
    nominal_candidate: list[dict[str, Any]],
    blocked_candidate: list[dict[str, Any]],
) -> dict[str, Any]:
    nominal_base = _summarize(nominal_baseline)
    nominal_arm = _summarize(nominal_candidate)
    supervisor_rows = [
        row
        for row in blocked_candidate
        if row["note"] == "bounded_no_path_unreachable"
    ]
    bounded = all(
        int(row["extra"].get("no_path_streak_ticks", -1)) == NO_PATH_TICKS
        for row in supervisor_rows
    )
    checks = {
        "nominal_true_arrivals_equal": (
            nominal_arm["true_arrivals"] == nominal_base["true_arrivals"]
        ),
        "nominal_false_arrivals_equal": (
            nominal_arm["false_arrivals"] == nominal_base["false_arrivals"]
        ),
        "nominal_contacts_equal": nominal_arm["contacts"] == nominal_base["contacts"],
        "candidate_blocked_false_arrivals_zero": (
            not any(row["false_arrival"] for row in blocked_candidate)
        ),
        "candidate_blocked_contacts_zero": (
            not any(row["contacts"] for row in blocked_candidate)
        ),
        "candidate_blocked_silent_nonarrivals_zero": all(
            row["declared_arrival"]
            or str(row["failure_type"]) in TYPED_TERMINALS
            for row in blocked_candidate
        ),
        "supervisor_terminations_use_registered_bound": bounded,
    }
    return {
        "hypothesis": "H1",
        "verdict": "SUPPORTED" if all(checks.values()) else "REFUTED",
        "checks": checks,
        "supervisor_terminations": len(supervisor_rows),
    }


def _h2_verdict(alias_candidate: list[dict[str, Any]]) -> dict[str, Any]:
    false_arrivals = sum(bool(row["false_arrival"]) for row in alias_candidate)
    return {
        "hypothesis": "H2",
        "verdict": "SUPPORTED" if false_arrivals > 0 else "REFUTED",
        "meaning": (
            "temporal confirmation remains correlated and is rejected as the "
            "aliased-localization remedy"
            if false_arrivals > 0
            else "the negative hypothesis did not reproduce"
        ),
        "temporal_filter_false_arrivals": false_arrivals,
    }


def run_experiment() -> dict[str, Any]:
    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    started = time.perf_counter()
    try:
        nominal_specs = _nominal_specs()
        blocked_specs = _blocked_specs()
        alias_specs = _alias_specs()
        experiments = {
            "registered_parameters": {
                "control_hz": CONTROL_HZ,
                "no_path_ticks": NO_PATH_TICKS,
                "no_path_bound_s": NO_PATH_TICKS / CONTROL_HZ,
                "temporal_arrival_ticks": TEMPORAL_ARRIVAL_TICKS,
                "held_out_seeds": list(HELD_OUT_SEEDS),
            },
            "nominal": {
                "baseline": [_run(spec, ArmShipped) for spec in nominal_specs],
                "candidate": [_run(spec, BoundedNoPathArm) for spec in nominal_specs],
            },
            "moved_obstacle": {
                "baseline": [_run(spec, ArmShipped) for spec in blocked_specs],
                "candidate": [_run(spec, BoundedNoPathArm) for spec in blocked_specs],
            },
            "alias_kidnap": {
                "baseline": [_run(spec, ArmShipped) for spec in alias_specs],
                "temporal_candidate": [
                    _run(spec, TemporalArrivalArm) for spec in alias_specs
                ],
            },
        }
    finally:
        use_learned_map(None)
        use_semantic_source(None)
        owner = getattr(nav_accept, "_OWNER", None)
        if owner is not None:
            owner.close()

    nominal = experiments["nominal"]
    blocked = experiments["moved_obstacle"]
    alias = experiments["alias_kidnap"]
    summaries = {
        "nominal": {
            "baseline": _summarize(nominal["baseline"]),
            "candidate": _summarize(nominal["candidate"]),
            "paired_changes": _paired_changes(
                nominal["baseline"], nominal["candidate"]
            ),
        },
        "moved_obstacle": {
            "baseline": _summarize(blocked["baseline"]),
            "candidate": _summarize(blocked["candidate"]),
            "paired_changes": _paired_changes(
                blocked["baseline"], blocked["candidate"]
            ),
        },
        "alias_kidnap": {
            "baseline": _summarize(alias["baseline"]),
            "temporal_candidate": _summarize(alias["temporal_candidate"]),
            "paired_changes": _paired_changes(
                alias["baseline"], alias["temporal_candidate"]
            ),
        },
    }
    verdicts = {
        "H1": _h1_verdict(
            nominal["baseline"], nominal["candidate"], blocked["candidate"]
        ),
        "H2": _h2_verdict(alias["temporal_candidate"]),
    }
    deterministic = {
        "schema": "parcel.navigation-generalization.v1",
        "experiments": experiments,
        "summaries": summaries,
        "verdicts": verdicts,
    }
    digest = hashlib.sha256(
        json.dumps(deterministic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema": "parcel.navigation-generalization-report.v1",
        "environment": {
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "host": platform.node(),
            "python": platform.python_version(),
            "repository_head": "f3ecb5cd9e09058c7bc29ba61b63e18f92a308d8",
            "hardware_used": "none",
            "evidence_tier": "desktop_sim_physical_shaped_inputs",
            "wall_s": round(time.perf_counter() - started, 3),
        },
        "deterministic_payload_sha256": digest,
        **deterministic,
    }


def _check(payload: dict[str, Any]) -> None:
    experiments = payload["experiments"]
    assert len(experiments["nominal"]["baseline"]) == 60
    assert len(experiments["nominal"]["candidate"]) == 60
    assert len(experiments["moved_obstacle"]["baseline"]) == 24
    assert len(experiments["moved_obstacle"]["candidate"]) == 24
    assert len(experiments["alias_kidnap"]["baseline"]) == 3
    assert len(experiments["alias_kidnap"]["temporal_candidate"]) == 3
    for scenario in ("nominal", "moved_obstacle"):
        assert not any(
            row["contacts"] < 0
            for arm_rows in experiments[scenario].values()
            for row in arm_rows
        )
    assert payload["deterministic_payload_sha256"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    args = parser.parse_args()
    payload = run_experiment()
    _check(payload)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summaries"], indent=2))
    print(json.dumps(payload["verdicts"], indent=2))
    print(f"deterministic_payload_sha256={payload['deterministic_payload_sha256']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
