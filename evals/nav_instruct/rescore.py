"""Derived re-scoring of persisted NAV_INSTRUCT traces (U31 / U32 closure).

Why this exists
---------------
The NAV_INSTRUCT runner ends an episode on the mission's own
``arrived_verified`` — one 0.1 s control tick after the first ``stopped=True``
sample. ``score_episode`` requires the robot to be inside the GoalRegion and
stopped for ``arrival_hold_s = 1.0 s``. Those two facts are incompatible: the
hold window can never accumulate, so a trace that genuinely settles in the goal
is scored ``success=False``. That is U31 — a *measurement* defect, not a
navigation one.

This module re-scores the **persisted traces** of already-completed runs under a
corrected rule and writes the result as NEW ledger rows tagged
``kind="derived_rescoring"`` with a ``parent_run_id``. Nothing that is frozen is
touched: the report JSONs are opened read-only, the frozen ledger rows are never
rewritten, and no re-freeze decision is needed (U31 "to verify", option 1).

The derived arrival rule — ``hold-or-trace-end-v1``
---------------------------------------------------
An episode counts as arrived when **either**:

(a) the frozen rule holds — some contiguous run of trace samples that are all
    inside the GoalRegion *and* stopped spans at least ``arrival_hold_s``; **or**

(b) the trace **ends** inside-and-stopped — the final sample is inside the
    GoalRegion, is stopped by :func:`~parcel_robot.instructnav.scoring.sample_stopped`,
    and the trace was **not** cut off by the runner's step limit (no
    ``step_limit`` flag and no ``navigation_step_limit`` note on the final
    sample).

Branch (b) is the correction. It says: when the recording stops while the robot
is stopped inside the goal, the hold is *unobservable*, not *unmet*. The step
limit exclusion is what keeps it honest — a trace that ran out of budget did not
choose to stop, so it gets no credit. Every input to the rule is read from the
trace itself, so the rule can be applied to any persisted run at the same
``runner_version``.

What this rule assumes, stated plainly: that a robot stopped inside the goal at
the instant the recording ended would have stayed there for the remaining 0.9 s.
That is an assumption, not a measurement — which is exactly why these rows are
derived diagnostics and can never replace a frozen baseline. The honest fix for
the frozen rows is the runner change (U31 option 2), which is a separate,
behaviour-changing card.

Usage::

    .parcel/bin/python -m evals.nav_instruct.rescore --all --append-ledger
    .parcel/bin/python -m evals.nav_instruct.rescore --report <file.json>
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.nav_instruct.generator import EpisodeSpec, generate_minival, matrix_digest
from parcel_robot.instructnav.scoring import (
    ARRIVAL_BOUNDARY_EPSILON_M,
    SCORING_VERSION,
    AttributionLayer,
    AuthorityCategory,
    EpisodeScore,
    FailureClass,
    GoalRegion,
    sample_stopped,
    score_episode,
    system_arrival_claim,
)

#: Identifier of the derived arrival rule documented in the module docstring.
DERIVED_RULE_ID = "hold-or-trace-end-v1"

#: Families the runner drives through the spatial/follow harness. They are
#: scored with ``arrival_hold_s=0.0`` by the runner, so the derived rule cannot
#: change them — recorded here so the re-scoring reproduces the frozen numbers
#: exactly instead of guessing at the parameters.
SPATIAL_FAMILIES: frozenset[str] = frozenset({"follow_owner", "circle_owner"})

#: Runner constants the persisted reports do not carry. Both are the defaults of
#: ``run_nav_instruct_v1`` at the runner_version these reports were produced at.
MAX_STEPS = 200
CONTROL_DT_S = 0.1

RESULTS_DIR = Path(__file__).resolve().parent / "results"
LEDGER = RESULTS_DIR / "ledger.jsonl"

#: Runs this module knows how to re-score: full-trace reports at the K0 runner
#: version. Frozen baseline first, candidate second.
DEFAULT_REPORTS: tuple[str, ...] = (
    "nav-instruct-v1-baseline-20260805T070524Z.json",
    "nav-instruct-v1-candidate-20260806T070335Z.json",
)


@dataclass(frozen=True)
class EpisodeRescore:
    """One episode scored twice: frozen hold rule and derived hold rule."""

    episode_id: str
    family: str
    tier: str
    mission_status: str
    reason: str
    system_arrival: bool
    scorer_arrival: bool
    authority_category: str
    recorded_success: bool
    frozen_success: bool
    derived_success: bool
    derived_branch: str
    frozen_failure: str
    derived_failure: str
    distance_to_goal_m: float
    trailing_hold_s: float

    @property
    def hold_flip(self) -> bool:
        return self.derived_success and not self.frozen_success

    def as_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "family": self.family,
            "tier": self.tier,
            "mission_status": self.mission_status,
            "reason": self.reason,
            "system_arrival": self.system_arrival,
            "scorer_arrival": self.scorer_arrival,
            "authority_category": self.authority_category,
            "recorded_success": self.recorded_success,
            "frozen_success": self.frozen_success,
            "derived_success": self.derived_success,
            "derived_branch": self.derived_branch,
            "frozen_failure": self.frozen_failure,
            "derived_failure": self.derived_failure,
            "distance_to_goal_m": self.distance_to_goal_m,
            "trailing_hold_s": self.trailing_hold_s,
            "hold_flip": self.hold_flip,
        }


def arrival_hold_s_for_family(family: str) -> float:
    """The hold the runner actually used for this family (frozen rule)."""

    return 0.0 if family in SPATIAL_FAMILIES else 1.0


def trailing_inside_stopped_s(
    trace: Sequence[Mapping[str, Any]],
    goal: GoalRegion,
    *,
    anchor_xy: tuple[float, float] | None,
) -> float:
    """Duration of the inside-and-stopped run that the trace *ends* on.

    ``0.0`` when the final sample is not inside-and-stopped. This is the number
    the frozen 1.0 s hold was asking for and never got; reporting it is what
    makes the derived rule auditable rather than a bare claim.
    """

    if not trace:
        return 0.0
    end_t: float | None = None
    start_t: float | None = None
    for step in reversed(trace):
        x, y = _xy(step)
        if not (goal.contains(x, y, anchor_xy=anchor_xy) and sample_stopped(step)):
            break
        t = _t_s(step)
        if end_t is None:
            end_t = t
        start_t = t
    if end_t is None or start_t is None:
        return 0.0
    return float(end_t - start_t)


def truncated_by_step_limit(trace: Sequence[Mapping[str, Any]]) -> bool:
    """True when the runner's step budget, not the mission, ended the trace."""

    if not trace:
        return False
    final = trace[-1]
    note = str(final.get("note") or "").lower()
    return bool(final.get("step_limit")) or "navigation_step_limit" in note


def derived_arrival(
    trace: Sequence[Mapping[str, Any]],
    goal: GoalRegion,
    *,
    frozen_success: bool,
    anchor_xy: tuple[float, float] | None,
) -> tuple[bool, str]:
    """Apply ``hold-or-trace-end-v1``; returns ``(success, branch)``.

    ``branch`` names which half of the rule fired: ``"frozen_hold"``,
    ``"trace_end_hold"``, or ``"none"``.
    """

    if frozen_success:
        return True, "frozen_hold"
    if not trace or truncated_by_step_limit(trace):
        return False, "none"
    final = trace[-1]
    x, y = _xy(final)
    if goal.contains(x, y, anchor_xy=anchor_xy) and sample_stopped(final):
        return True, "trace_end_hold"
    return False, "none"


def rescore_episode(
    episode: EpisodeSpec,
    record: Mapping[str, Any],
) -> tuple[EpisodeRescore, EpisodeScore, EpisodeScore]:
    """Re-score one persisted episode under both rules.

    Returns ``(summary, frozen_score, derived_score)``. The frozen score is the
    current scorer replaying the *same* parameters the runner used, so it must
    reproduce the recorded ``success`` — the caller asserts that.
    """

    trace = [dict(step) for step in record.get("trace") or ()]
    goal = episode.goal
    family = episode.family
    hold_s = arrival_hold_s_for_family(family)
    anchor = None if family in SPATIAL_FAMILIES else goal.center
    claim = system_arrival_claim(record.get("mission_status"), record.get("reason"))
    common = {
        "shortest_path_m": max(episode.shortest_path_m, 1e-3),
        "max_time_s": MAX_STEPS * CONTROL_DT_S,
        "anchor_xy": anchor,
        "system_arrival": claim,
    }
    frozen = score_episode(trace, goal, arrival_hold_s=hold_s, **common)
    derived_success, branch = derived_arrival(
        trace, goal, frozen_success=frozen.success, anchor_xy=anchor
    )
    derived = (
        frozen
        if derived_success == frozen.success
        else promoted_derived_score(
            frozen, trace, shortest_path_m=episode.shortest_path_m
        )
    )
    summary = EpisodeRescore(
        episode_id=str(record.get("episode_id")),
        family=family,
        tier=episode.tier,
        mission_status=str(record.get("mission_status")),
        reason=str(record.get("reason")),
        system_arrival=bool(claim),
        scorer_arrival=bool(frozen.scorer_arrival),
        authority_category=frozen.authority_category.value,
        recorded_success=bool((record.get("score") or {}).get("success")),
        frozen_success=bool(frozen.success),
        derived_success=bool(derived.success),
        derived_branch=branch,
        frozen_failure=frozen.failure.value,
        derived_failure=derived.failure.value,
        distance_to_goal_m=float(frozen.distance_to_goal_m),
        trailing_hold_s=trailing_inside_stopped_s(trace, goal, anchor_xy=anchor),
    )
    return summary, frozen, derived


def rescore_report(path: str | Path) -> dict[str, Any]:
    """Re-score every episode of a persisted report. Read-only on ``path``."""

    report_path = Path(path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    episodes = generate_minival(seed=int(report.get("seed", 20260804)))
    digest = matrix_digest(episodes)
    recorded_digest = str(report.get("episode_digest") or "")
    if recorded_digest and recorded_digest != digest:
        raise ValueError(
            "episode set drift: report was produced against episode_digest "
            f"{recorded_digest} but the generator now emits {digest}; the "
            "traces cannot be paired to goal regions"
        )
    by_id = {ep.episode_id: ep for ep in episodes}
    records = list(report.get("episodes") or ())
    if len(records) != len(episodes):
        raise ValueError(
            f"report holds {len(records)} episodes, generator emits {len(episodes)}"
        )

    rows: list[EpisodeRescore] = []
    frozen_hist = {item.value: 0 for item in FailureClass}
    derived_hist = {item.value: 0 for item in FailureClass}
    authority_hist = {item.value: 0 for item in AuthorityCategory}
    frozen_spl = 0.0
    derived_spl = 0.0
    for record in records:
        episode = by_id.get(str(record.get("episode_id")))
        if episode is None:
            raise ValueError(f"unknown episode in report: {record.get('episode_id')!r}")
        summary, frozen, derived = rescore_episode(episode, record)
        if summary.frozen_success != summary.recorded_success:
            raise ValueError(
                f"{summary.episode_id}: replaying the frozen rule gave "
                f"success={summary.frozen_success} but the report recorded "
                f"{summary.recorded_success}; the re-scoring is not paired"
            )
        rows.append(summary)
        frozen_hist[frozen.failure.value] += 1
        derived_hist[derived.failure.value] += 1
        authority_hist[summary.authority_category] += 1
        frozen_spl += float(frozen.spl)
        derived_spl += float(derived.spl)

    n = max(len(rows), 1)
    sr_frozen = sum(1 for row in rows if row.frozen_success) / n
    sr_derived = sum(1 for row in rows if row.derived_success) / n
    return {
        "kind": "derived_rescoring",
        "parent_run_id": str(report.get("report_id")),
        "parent_report": report_path.name,
        "runner_version": str(report.get("runner_version")),
        "scorer_version": SCORING_VERSION,
        "rescore_rule": DERIVED_RULE_ID,
        "mode": str(report.get("mode")),
        "seed": int(report.get("seed", 20260804)),
        "minival": bool(report.get("minival")),
        "episode_digest": digest,
        "n": len(rows),
        "arrival_hold_s_navigation": 1.0,
        "arrival_hold_s_spatial": 0.0,
        "arrival_epsilon_m": ARRIVAL_BOUNDARY_EPSILON_M,
        "sr_recorded": float(report.get("aggregate", {}).get("sr", float("nan"))),
        "sr_frozen_rule": sr_frozen,
        "sr_derived_rule": sr_derived,
        "sr_delta": sr_derived - sr_frozen,
        "spl_frozen_rule": frozen_spl / n,
        "spl_derived_rule": derived_spl / n,
        "failure_histogram_frozen_rule": frozen_hist,
        "failure_histogram_derived_rule": derived_hist,
        "authority_histogram": authority_hist,
        "hold_flip_episodes": [row.episode_id for row in rows if row.hold_flip],
        "false_arrival_episodes": [
            row.episode_id
            for row in rows
            if row.derived_failure == FailureClass.FALSE_ARRIVAL.value
        ],
        "authority_disagreement_episodes": [
            row.episode_id
            for row in rows
            if row.authority_category == AuthorityCategory.AUTHORITY_DISAGREEMENT.value
        ],
        # A derived row is never a baseline and never freezes anything.
        "frozen_baseline": False,
        "episodes": [row.as_dict() for row in rows],
    }


def ledger_row(rescoring: Mapping[str, Any]) -> dict[str, Any]:
    """The append-only ledger projection of a re-scoring (no per-episode traces)."""

    row = {key: value for key, value in rescoring.items() if key != "episodes"}
    row["generated_at"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return row


def append_ledger_rows(
    rescorings: Sequence[Mapping[str, Any]],
    *,
    ledger: str | Path = LEDGER,
) -> list[dict[str, Any]]:
    """Append derived rows. Existing rows are read-only — never rewritten."""

    rows = [ledger_row(item) for item in rescorings]
    path = Path(ledger)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return rows


def promoted_derived_score(
    frozen: EpisodeScore,
    trace: Sequence[Mapping[str, Any]],
    *,
    shortest_path_m: float,
) -> EpisodeScore:
    """Rebuild the score as a success under the derived rule.

    SPL uses the same ``S · L / max(L, P)`` definition as
    :func:`score_episode`; ``time_to_goal_s`` is the timestamp of the final
    sample, which is when the (truncated) hold began and ended.

    Public because the v2 runner scores live episodes under the same rule and
    must promote them **identically** to the derived re-scoring of the v1
    traces — one implementation, so the bridge's (c) column compares like with
    like.
    """

    shortest = max(shortest_path_m, 1e-3)
    path_length = _path_length(trace)
    spl = shortest / max(shortest, path_length) if shortest > 0.0 else 0.0
    return EpisodeScore(
        success=True,
        spl=float(spl),
        distance_to_goal_m=frozen.distance_to_goal_m,
        time_to_goal_s=_t_s(trace[-1]) if trace else None,
        failure=FailureClass.NONE,
        detail=f"derived_success:{DERIVED_RULE_ID}",
        oracle_success=True,
        oracle_sr_gap=0.0,
        attribution_layer=AttributionLayer.NONE,
        scorer_arrival=frozen.scorer_arrival,
        system_arrival=frozen.system_arrival,
        authority_category=frozen.authority_category,
    )


def _path_length(trace: Sequence[Mapping[str, Any]]) -> float:
    total = 0.0
    previous: tuple[float, float] | None = None
    for step in trace:
        xy = _xy(step)
        if previous is not None:
            total += math.hypot(xy[0] - previous[0], xy[1] - previous[1])
        previous = xy
    return total


def _xy(step: Mapping[str, Any]) -> tuple[float, float]:
    return float(step.get("x", 0.0)), float(step.get("y", 0.0))


def _t_s(step: Mapping[str, Any]) -> float:
    value = step.get("t_s", 0.0)
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        action="append",
        default=None,
        help="report JSON to re-score (repeatable)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=f"re-score the known full-trace reports: {', '.join(DEFAULT_REPORTS)}",
    )
    parser.add_argument(
        "--append-ledger",
        action="store_true",
        help="append kind=derived_rescoring rows (frozen rows are never touched)",
    )
    args = parser.parse_args(argv)

    reports = list(args.report or ())
    if args.all or not reports:
        reports = [RESULTS_DIR / name for name in DEFAULT_REPORTS]

    rescorings = [rescore_report(path) for path in reports]
    if args.append_ledger:
        append_ledger_rows(rescorings)
    print(
        json.dumps(
            [
                {
                    key: value
                    for key, value in item.items()
                    if key != "episodes"
                }
                for item in rescorings
            ],
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
