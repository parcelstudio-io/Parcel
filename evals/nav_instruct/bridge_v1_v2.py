"""v1 → v2 re-freeze bridge: what each correction moved, separately.

A re-freeze that reports one number ("SR went from X to Y") is unreadable — the
reader cannot tell which of the three approved corrections did what, or how much
of the delta is just the code having moved since the frozen row was measured.
This module produces the bridge table that makes it readable.

Two halves, and they answer different questions.

**Spec bridge** (pure, no sim). For every episode id, the v1 goal, the
v1a goal (correction (a) alone — derived scene truth with v1's spec logic), and
the v2 goal, plus the attribution: ``scene_truth`` / ``episode_spec`` / ``both``
/ ``unchanged``. This is the "what moved and why" half, and it is exact.

**Measured bridge** (runs the sim). Baseline and candidate, each at v1, v1a and
v2, **all on today's tree**, so the deltas are the corrections and nothing else.
This matters: the frozen v1 rows were measured on 2026-08-05/06 code and four
lanes have landed since (Lane D alone moved mean dtg by −0.027 m), so
differencing a fresh v2 run against a stale v1 row would attribute lane work to
the re-freeze. The historical rows are still reported — as context, labelled.

Correction (c), the arrival rule, is isolated *inside* each run: every report
carries ``sr`` (active rule) and ``sr_frozen_rule`` (what v1's hold rule would
have said about the same traces), so (c) never has to be inferred from a
difference between runs. The W0 ``derived_rescoring`` ledger rows are the same
measurement applied to the v1 traces and are quoted for cross-checking.

Nothing here writes to the frozen ledger and nothing here is a baseline.

Usage::

    .parcel/bin/python -m evals.nav_instruct.bridge_v1_v2 --run
    .parcel/bin/python -m evals.nav_instruct.bridge_v1_v2 --spec-only
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.nav_instruct.generator import (
    EPISODE_SET_V1,
    EPISODE_SET_V1A,
    EPISODE_SET_V2,
    EpisodeSpec,
    episode_set_spec,
    generate_minival,
    matrix_digest,
)
from evals.nav_instruct.runner import (
    ARRIVAL_RULE_FOR_VERSION,
    RUNNER_VERSION,
    NavInstructRunner,
    aggregate_results,
)

RESULTS_DIR = Path(__file__).resolve().parent / "results"
LEDGER = RESULTS_DIR / "ledger.jsonl"
BRIDGE_PATH = RESULTS_DIR / "bridge_v1_v2.json"

BRIDGE_VERSIONS: tuple[str, ...] = (EPISODE_SET_V1, EPISODE_SET_V1A, EPISODE_SET_V2)

CORRECTIONS: dict[str, str] = {
    "a": (
        "derived scene truth — the landmark table becomes scene_truth.json's "
        "`derived` section (the scene's own geometry) instead of `transcribed`, "
        "which is wrong in 7 fields across 5 entities"
    ),
    "b": (
        "episode spec fixes — word-boundary class matching (B-05's "
        "'streetlight' no longer matches the tree class) and visible-instance "
        "anchoring for definite references (D-15's 'the tree' anchors to the "
        "tree actually in frame)"
    ),
    "c": (
        "arrival rule — hold-or-trace-end-v1 replaces the frozen hold, which "
        "the runner's own termination made unobservable (U31)"
    ),
}


def _goal_key(episode: EpisodeSpec) -> Any:
    return (episode.target_entity_id, json.dumps(episode.goal.as_dict(), sort_keys=True))


def spec_bridge(*, seed: int = 20260804) -> dict[str, Any]:
    """Per-episode goal changes, attributed to one correction each. Pure."""

    sets = {
        version: {ep.episode_id: ep for ep in generate_minival(seed=seed, version=version)}
        for version in BRIDGE_VERSIONS
    }
    ids_v1 = list(sets[EPISODE_SET_V1])
    rows: list[dict[str, Any]] = []
    counts = {"scene_truth": 0, "episode_spec": 0, "both": 0, "unchanged": 0}
    for episode_id in ids_v1:
        v1 = sets[EPISODE_SET_V1][episode_id]
        v1a = sets[EPISODE_SET_V1A][episode_id]
        v2 = sets[EPISODE_SET_V2][episode_id]
        moved_by_a = _goal_key(v1a) != _goal_key(v1)
        moved_by_b = _goal_key(v2) != _goal_key(v1a)
        if moved_by_a and moved_by_b:
            changed_by = "both"
        elif moved_by_a:
            changed_by = "scene_truth"
        elif moved_by_b:
            changed_by = "episode_spec"
        else:
            changed_by = "unchanged"
        counts[changed_by] += 1
        if changed_by == "unchanged":
            continue
        rows.append(
            {
                "episode_id": episode_id,
                "family": v1.family,
                "tier": v1.tier,
                "instruction": v1.instruction,
                "changed_by": changed_by,
                "v1_target": v1.target_entity_id,
                "v2_target": v2.target_entity_id,
                "v1_goal": v1.goal.as_dict(),
                "v1a_goal": v1a.goal.as_dict(),
                "v2_goal": v2.goal.as_dict(),
                "v1_shortest_path_m": v1.shortest_path_m,
                "v2_shortest_path_m": v2.shortest_path_m,
            }
        )
    return {
        "seed": seed,
        "episode_count": len(ids_v1),
        "digests": {
            version: matrix_digest(tuple(sets[version].values())) for version in BRIDGE_VERSIONS
        },
        # A re-freeze that renamed or dropped episodes would make the old rows
        # unmappable. Every id survives, so the mapping is total and 1:1.
        "id_mapping_is_total": all(
            set(sets[version]) == set(sets[EPISODE_SET_V1]) for version in BRIDGE_VERSIONS
        ),
        "counts_by_change": counts,
        "changed_rows": rows,
    }


def measured_bridge(
    *,
    seed: int = 20260804,
    modes: Sequence[str] = ("baseline", "candidate"),
    max_steps: int = 200,
    versions: Sequence[str] = BRIDGE_VERSIONS,
) -> dict[str, Any]:
    """Run every (mode × version) cell on today's tree and difference them."""

    runs: dict[str, dict[str, Any]] = {}
    for mode in modes:
        runs[mode] = {}
        for version in versions:
            runner = NavInstructRunner(
                max_steps=max_steps,
                mode=mode,
                arrival_rule=ARRIVAL_RULE_FOR_VERSION[version],
            )
            episodes = generate_minival(seed=seed, version=version)
            results = [runner.run_episode(ep) for ep in episodes]
            aggregate = aggregate_results(
                results, episode_set_version=version, scene=runner.scene
            )
            runs[mode][version] = {
                "episode_digest": matrix_digest(episodes),
                "arrival_rule": aggregate["arrival_rule"],
                "sr": aggregate["sr"],
                "sr_frozen_rule": aggregate["sr_frozen_rule"],
                "spl": aggregate["spl"],
                "mean_dtg_m": aggregate["mean_dtg_m"],
                "collision_total": aggregate["collision_total"],
                "failure_histogram": aggregate["failure_histogram"],
                "authority_histogram": aggregate["authority_histogram"],
                "arrival_branch_histogram": aggregate["arrival_branch_histogram"],
                "successes": sorted(r.episode_id for r in results if r.score.success),
                "successes_frozen_rule": sorted(
                    r.episode_id for r in results if r.frozen_rule_success
                ),
            }

    deltas: dict[str, Any] = {}
    for mode, cells in runs.items():
        if not {EPISODE_SET_V1, EPISODE_SET_V1A, EPISODE_SET_V2} <= set(cells):
            continue
        v1, v1a, v2 = cells[EPISODE_SET_V1], cells[EPISODE_SET_V1A], cells[EPISODE_SET_V2]
        deltas[mode] = {
            # (a) and (b) are read under the SAME (frozen) rule on both sides,
            # so neither can borrow credit from (c).
            "a_scene_truth": _delta(v1, v1a, key="sr_frozen_rule"),
            "b_episode_spec": _delta(v1a, v2, key="sr_frozen_rule"),
            "c_arrival_rule": {
                "sr_before": v2["sr_frozen_rule"],
                "sr_after": v2["sr"],
                "sr_delta": v2["sr"] - v2["sr_frozen_rule"],
                "flipped_episodes": sorted(
                    set(v2["successes"]) - set(v2["successes_frozen_rule"])
                ),
                "note": "measured inside the v2 run: same traces, two rules",
            },
            "total_v1_to_v2": {
                "sr_before": v1["sr"],
                "sr_after": v2["sr"],
                "sr_delta": v2["sr"] - v1["sr"],
                "mean_dtg_before_m": v1["mean_dtg_m"],
                "mean_dtg_after_m": v2["mean_dtg_m"],
                "mean_dtg_delta_m": v2["mean_dtg_m"] - v1["mean_dtg_m"],
                "collisions_before": v1["collision_total"],
                "collisions_after": v2["collision_total"],
            },
        }
    return {"runs": runs, "deltas": deltas}


def _delta(before: dict[str, Any], after: dict[str, Any], *, key: str) -> dict[str, Any]:
    return {
        "sr_before": before[key],
        "sr_after": after[key],
        "sr_delta": after[key] - before[key],
        "mean_dtg_before_m": before["mean_dtg_m"],
        "mean_dtg_after_m": after["mean_dtg_m"],
        "mean_dtg_delta_m": after["mean_dtg_m"] - before["mean_dtg_m"],
        "episodes_gained": sorted(
            set(after["successes_frozen_rule"]) - set(before["successes_frozen_rule"])
        ),
        "episodes_lost": sorted(
            set(before["successes_frozen_rule"]) - set(after["successes_frozen_rule"])
        ),
        "rule": "both sides scored under the frozen hold rule",
    }


def historical_v1_rows(ledger: str | Path = LEDGER) -> list[dict[str, Any]]:
    """The frozen v1 ledger rows, quoted verbatim for context.

    They were measured on 2026-08-05/06 code. They are NOT differenced against
    anything here: four lanes have landed since, so any difference would be
    lane work plus re-freeze, inseparably.
    """

    path = Path(ledger)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("report_id") in {
            "nav-instruct-v1-baseline-20260805T070524Z",
            "nav-instruct-v1-candidate-20260806T070335Z",
        } or row.get("kind") == "derived_rescoring":
            rows.append(
                {
                    key: row.get(key)
                    for key in (
                        "report_id",
                        "parent_run_id",
                        "kind",
                        "mode",
                        "sr",
                        "sr_frozen_rule",
                        "sr_derived_rule",
                        "rescore_rule",
                        "episode_digest",
                        "frozen_baseline",
                    )
                    if key in row
                }
            )
    return rows


def build_bridge(*, seed: int = 20260804, run: bool, max_steps: int = 200) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "refreeze_bridge",
        "generated_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "runner_version": RUNNER_VERSION,
        "from_version": EPISODE_SET_V1,
        "to_version": EPISODE_SET_V2,
        "corrections": CORRECTIONS,
        "episode_set_provenance": {
            version: episode_set_spec(version).provenance for version in BRIDGE_VERSIONS
        },
        "frozen_baseline": False,
        "spec_bridge": spec_bridge(seed=seed),
        "historic_v1_rows_for_context_only": historical_v1_rows(),
    }
    if run:
        payload["measured_bridge"] = {
            "measured_on": "today's tree (post Lane A-D), all cells, same process",
            "why_not_the_frozen_rows": (
                "the frozen v1 rows were measured on 2026-08-05/06 code; "
                "differencing against them would attribute four lanes of work "
                "to the re-freeze"
            ),
            **measured_bridge(seed=seed, max_steps=max_steps),
        }
    return payload


def markdown_table(payload: dict[str, Any]) -> str:
    """The bridge as a table a human reads, not a JSON a script reads."""

    lines = ["| mode | correction | SR before | SR after | Δ SR | Δ mean dtg (m) |", "|---|---|---|---|---|---|"]
    measured = payload.get("measured_bridge") or {}
    for mode, cells in sorted((measured.get("deltas") or {}).items()):
        for key, label in (
            ("a_scene_truth", "(a) derived scene truth"),
            ("b_episode_spec", "(b) episode spec fixes"),
            ("c_arrival_rule", "(c) arrival rule"),
            ("total_v1_to_v2", "**total v1 → v2**"),
        ):
            cell = cells.get(key) or {}
            dtg = cell.get("mean_dtg_delta_m")
            lines.append(
                f"| {mode} | {label} | {cell.get('sr_before')} | {cell.get('sr_after')} | "
                f"{cell.get('sr_delta')} | {'—' if dtg is None else f'{dtg:+.4f}'} |"
            )
    spec = payload["spec_bridge"]
    lines.append("")
    lines.append("| episode | instruction | moved by | v1 anchor | v2 anchor |")
    lines.append("|---|---|---|---|---|")
    for row in spec["changed_rows"]:
        lines.append(
            f"| `{row['episode_id']}` | {row['instruction']} | {row['changed_by']} | "
            f"{row['v1_target']} | {row['v2_target']} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument(
        "--run",
        action="store_true",
        help="also run the sim cells (mode × version) and difference them",
    )
    parser.add_argument(
        "--spec-only",
        action="store_true",
        help="pure spec bridge only; never touches the sim",
    )
    parser.add_argument("--out", type=Path, default=BRIDGE_PATH)
    parser.add_argument("--markdown", type=Path, default=None)
    args = parser.parse_args(argv)

    payload = build_bridge(
        seed=args.seed, run=args.run and not args.spec_only, max_steps=args.max_steps
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if args.markdown is not None:
        args.markdown.write_text(markdown_table(payload) + "\n", encoding="utf-8")
    print(markdown_table(payload))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
