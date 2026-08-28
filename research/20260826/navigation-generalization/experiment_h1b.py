"""Exploratory H1b: bound both explicit unroutable planner states.

H1b was specified only after run 1 exposed ``status=goal_blocked`` as the
seven-case survivor. It is therefore exploratory evidence, not a confirmation
on an untouched holdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import experiment as h1

from parcel_robot.backends.base import VelocityCommand
from parcel_robot.perception_source.selection import (
    SOURCE_LEARNED_MAP,
    SemanticSourcePolicy,
    use_learned_map,
    use_semantic_source,
)

HERE = Path(__file__).resolve().parent
RUN1 = HERE / "results-run1.json"
UNROUTABLE_STATUSES = ("status=no_path", "status=goal_blocked")


class BoundedUnroutableArm(h1.ArmShipped):
    """Commissioned arm plus a bound on both observed unroutable states."""

    arm = "bounded_unroutable_h1b"

    def __init__(self, spec: Any) -> None:
        super().__init__(spec)
        self._unroutable_streak = 0
        self._bounded_done = False

    def command(
        self, observation: Any, t_s: float
    ) -> tuple[VelocityCommand, bool, str]:
        requested, declared, note = super().command(observation, t_s)
        if not declared and any(status in note for status in UNROUTABLE_STATUSES):
            self._unroutable_streak += 1
        else:
            self._unroutable_streak = 0
        if self._unroutable_streak < h1.NO_PATH_TICKS:
            return requested, declared, note
        self._bounded_done = True
        matched = next(status for status in UNROUTABLE_STATUSES if status in note)
        self.result.failure_type = "unreachable"
        self.result.extra["unroutable_status"] = matched.removeprefix("status=")
        self.result.extra["unroutable_streak_ticks"] = self._unroutable_streak
        self.result.extra["unroutable_terminal_t_s"] = round(float(t_s), 3)
        return VelocityCommand(), False, "bounded_unroutable"

    def done(self) -> bool:
        return self._bounded_done


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> dict[str, Any]:
    if not RUN1.exists():
        raise FileNotFoundError(f"run-1 artifact missing: {RUN1}")
    run1 = json.loads(RUN1.read_text(encoding="utf-8"))
    started = time.perf_counter()
    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    try:
        nominal = [
            h1._run(spec, BoundedUnroutableArm) for spec in h1._nominal_specs()
        ]
        blockers = [
            h1._run(spec, BoundedUnroutableArm) for spec in h1._blocked_specs()
        ]
    finally:
        use_learned_map(None)
        use_semantic_source(None)
        owner = getattr(h1.nav_accept, "_OWNER", None)
        if owner is not None:
            owner.close()

    baseline_nominal = run1["experiments"]["nominal"]["baseline"]
    baseline_blockers = run1["experiments"]["moved_obstacle"]["baseline"]
    checks = {
        "nominal_true_arrivals_60": sum(row["arrived"] for row in nominal) == 60,
        "nominal_paired_outcomes_unchanged": not h1._paired_changes(
            baseline_nominal, nominal
        ),
        "blocker_typed_24": sum(
            row["failure_type"] in h1.TYPED_TERMINALS for row in blockers
        )
        == 24,
        "blocker_silent_zero": not any(
            row["failure_type"] == "silent_stall_step_limit" for row in blockers
        ),
        "false_arrivals_zero": not any(row["false_arrival"] for row in blockers),
        "contacts_zero": not any(row["contacts"] for row in blockers),
        "registered_30_tick_bound": all(
            row["extra"].get("unroutable_streak_ticks") == h1.NO_PATH_TICKS
            for row in blockers
        ),
    }
    deterministic = {
        "schema": "parcel.navigation-generalization.h1b.v1",
        "status_set": list(UNROUTABLE_STATUSES),
        "bound_ticks": h1.NO_PATH_TICKS,
        "bound_s": h1.NO_PATH_TICKS / h1.CONTROL_HZ,
        "provenance": {
            "classification": "post-run exploratory",
            "run1_payload_sha256": run1["deterministic_payload_sha256"],
            "run1_artifact_sha256": _file_sha256(RUN1),
        },
        "summaries": {
            "nominal_baseline": h1._summarize(baseline_nominal),
            "nominal_h1b": h1._summarize(nominal),
            "blocker_baseline": h1._summarize(baseline_blockers),
            "blocker_h1b": h1._summarize(blockers),
        },
        "paired_changes": {
            "nominal": h1._paired_changes(baseline_nominal, nominal),
            "blockers": h1._paired_changes(baseline_blockers, blockers),
        },
        "checks": checks,
        "verdict": "SUPPORTED_EXPLORATORY" if all(checks.values()) else "REFUTED",
        "rows": {"nominal": nominal, "blockers": blockers},
    }
    digest = hashlib.sha256(
        json.dumps(deterministic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema": "parcel.navigation-generalization-h1b-report.v1",
        "environment": {
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "host": platform.node(),
            "python": platform.python_version(),
            "repository_head": "f3ecb5cd9e09058c7bc29ba61b63e18f92a308d8",
            "hardware_used": "none",
            "wall_s": round(time.perf_counter() - started, 3),
        },
        "deterministic_payload_sha256": digest,
        **deterministic,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "results-h1b.json")
    args = parser.parse_args()
    payload = run()
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summaries"], indent=2))
    print(json.dumps({"checks": payload["checks"], "verdict": payload["verdict"]}, indent=2))
    print(f"deterministic_payload_sha256={payload['deterministic_payload_sha256']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
