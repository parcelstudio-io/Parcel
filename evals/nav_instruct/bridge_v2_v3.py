"""v2 → v3 re-freeze bridge: ONE correction, isolated.

v3 carries exactly one change against v2 — correction **(d)**, the ``next_to``
band re-anchored from the anchor's *centre* to its *surface* (card S-1,
2026-08-09). Everything else is v2 byte-for-byte: the same landmark table, the
same word-boundary class matching, the same visible-instance anchoring, the
same arrival rule, the same seed, the same 25 episode ids.

That makes this bridge narrower than ``bridge_v1_v2`` and it is deliberately
built that way: with one correction there is no attribution problem to solve, so
the only questions are

1. **which episodes moved at all** (spec bridge, pure) — under (d) only goals
   built by the ``next_to`` builder can move, so the answer must be exactly the
   five ``object_relative`` episodes and nothing else;
2. **what that did to a run** (measured bridge) — both modes, both versions,
   **all four cells in one process on one tree**, so the difference is the band
   and cannot be anything that landed in ``src/`` between two runs.

The prior card's read-only re-scoring of the frozen v2 traces predicted exactly
one episode's K0 arrival predicate flips (``nav-object_relative-A-00``, the
bench) with headline SR unchanged. This bridge is the measurement that confirms
or refutes that prediction on fresh runs, and ``predicted_vs_measured`` in the
payload states which.

Nothing here writes to the frozen ledger and nothing here is a baseline.

Usage::

    .parcel/bin/python -m evals.nav_instruct.bridge_v2_v3 --run
    .parcel/bin/python -m evals.nav_instruct.bridge_v2_v3 --spec-only
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.nav_instruct.generator import (
    EPISODE_SET_V2,
    EPISODE_SET_V3,
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
BRIDGE_PATH = RESULTS_DIR / "bridge_v2_v3.json"

BRIDGE_VERSIONS: tuple[str, ...] = (EPISODE_SET_V2, EPISODE_SET_V3)

CORRECTIONS: dict[str, str] = {
    "d": (
        "surface-anchored next_to band — NEXT_TO_BAND_M becomes a distance to "
        "the anchor's SURFACE instead of its CENTRE, materialised in exactly "
        "one place (instructnav.scoring.next_to_band_from_centre). The band's "
        "1.1 m width no longer shrinks with the anchor's radius, so next_to is "
        "achievable for bench/tree/planter instead of for the lamppost alone"
    ),
}

#: What the prior card's read-only re-scoring of the frozen v2 traces predicted
#: (scrum/20260808/task_3/BENCH_PLACEMENT_STATUS.md). Recorded here so the
#: measurement can contradict it rather than be written to agree with it.
PREDICTION: dict[str, Any] = {
    "source": "scrum/20260808/task_3/BENCH_PLACEMENT_STATUS.md (read-only re-scoring)",
    "k0_predicate_flips": ["nav-object_relative-A-00-3efbba45"],
    "episode_success_delta": 0,
    "note": (
        "one episode's K0 arrival predicate flips (the bench), in both modes; "
        "episode success additionally requires the settle hold and was 0/5 "
        "before and after, so headline SR was predicted not to move"
    ),
}


def _goal_key(episode: EpisodeSpec) -> Any:
    return (episode.target_entity_id, json.dumps(episode.goal.as_dict(), sort_keys=True))


def spec_bridge(*, seed: int = 20260804) -> dict[str, Any]:
    """Per-episode goal changes from v2 to v3. Pure; no sim."""

    sets = {
        version: {ep.episode_id: ep for ep in generate_minival(seed=seed, version=version)}
        for version in BRIDGE_VERSIONS
    }
    rows: list[dict[str, Any]] = []
    counts = {"next_to_band": 0, "unchanged": 0}
    for episode_id, v2 in sets[EPISODE_SET_V2].items():
        v3 = sets[EPISODE_SET_V3][episode_id]
        if _goal_key(v3) == _goal_key(v2):
            counts["unchanged"] += 1
            continue
        counts["next_to_band"] += 1
        rows.append(
            {
                "episode_id": episode_id,
                "family": v2.family,
                "tier": v2.tier,
                "instruction": v2.instruction,
                "changed_by": "next_to_band",
                "target": v2.target_entity_id,
                "anchor_footprint_m": v2.goal.anchor_footprint_m,
                "v2_band_m": list(v2.goal.band_m or ()),
                "v3_band_m": list(v3.goal.band_m or ()),
                "v2_shortest_path_m": v2.shortest_path_m,
                "v3_shortest_path_m": v3.shortest_path_m,
            }
        )
    families_moved = sorted({row["family"] for row in rows})
    return {
        "seed": seed,
        "episode_count": len(sets[EPISODE_SET_V2]),
        "digests": {
            version: matrix_digest(tuple(sets[version].values()))
            for version in BRIDGE_VERSIONS
        },
        "id_mapping_is_total": set(sets[EPISODE_SET_V2]) == set(sets[EPISODE_SET_V3]),
        "counts_by_change": counts,
        # (d) can only reach goals built by the next_to builder. If any other
        # family shows up here, the change leaked.
        "families_moved": families_moved,
        "only_object_relative_moved": families_moved == ["object_relative"],
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
                # The K0 arrival predicate on the final pose, with no settle
                # hold — this is the verdict the prediction is about, and it is
                # NOT episode success.
                "scorer_arrival": sorted(
                    r.episode_id for r in results if r.score.scorer_arrival
                ),
                "dtg_by_episode": {
                    r.episode_id: r.score.distance_to_goal_m for r in results
                },
            }

    deltas: dict[str, Any] = {}
    for mode, cells in runs.items():
        v2, v3 = cells[EPISODE_SET_V2], cells[EPISODE_SET_V3]
        deltas[mode] = {
            "d_next_to_band": {
                "sr_before": v2["sr"],
                "sr_after": v3["sr"],
                "sr_delta": v3["sr"] - v2["sr"],
                "mean_dtg_before_m": v2["mean_dtg_m"],
                "mean_dtg_after_m": v3["mean_dtg_m"],
                "mean_dtg_delta_m": v3["mean_dtg_m"] - v2["mean_dtg_m"],
                "collisions_before": v2["collision_total"],
                "collisions_after": v3["collision_total"],
                "episodes_gained": sorted(set(v3["successes"]) - set(v2["successes"])),
                "episodes_lost": sorted(set(v2["successes"]) - set(v3["successes"])),
                "k0_arrival_gained": sorted(
                    set(v3["scorer_arrival"]) - set(v2["scorer_arrival"])
                ),
                "k0_arrival_lost": sorted(
                    set(v2["scorer_arrival"]) - set(v3["scorer_arrival"])
                ),
                "rule": "both sides on the v2 arrival rule (v3 does not change it)",
            }
        }
    return {"runs": runs, "deltas": deltas}


def compare_with_prediction(measured: dict[str, Any]) -> dict[str, Any]:
    """Did the prior card's read-only re-scoring predict this run? Say so."""

    out: dict[str, Any] = {"prediction": PREDICTION, "per_mode": {}}
    agreed = True
    for mode, cells in (measured.get("deltas") or {}).items():
        cell = cells["d_next_to_band"]
        flips = sorted(set(cell["k0_arrival_gained"]) | set(cell["k0_arrival_lost"]))
        matches_flips = flips == PREDICTION["k0_predicate_flips"]
        matches_sr = cell["sr_delta"] == PREDICTION["episode_success_delta"]
        agreed = agreed and matches_flips and matches_sr
        out["per_mode"][mode] = {
            "k0_predicate_flips": flips,
            "matches_predicted_flips": matches_flips,
            "sr_delta": cell["sr_delta"],
            "matches_predicted_sr_delta": matches_sr,
        }
    out["prediction_confirmed"] = agreed
    return out


def build_bridge(*, seed: int = 20260804, run: bool, max_steps: int = 200) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "refreeze_bridge",
        "generated_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "runner_version": RUNNER_VERSION,
        "from_version": EPISODE_SET_V2,
        "to_version": EPISODE_SET_V3,
        "corrections": CORRECTIONS,
        "episode_set_provenance": {
            version: episode_set_spec(version).provenance for version in BRIDGE_VERSIONS
        },
        "next_to_band_reference": {
            version: episode_set_spec(version).next_to_band_reference
            for version in BRIDGE_VERSIONS
        },
        "frozen_baseline": False,
        "spec_bridge": spec_bridge(seed=seed),
    }
    if run:
        measured = measured_bridge(seed=seed, max_steps=max_steps)
        payload["measured_bridge"] = {
            "measured_on": "one tree, one process, all four cells",
            "why_not_the_frozen_v2_rows": (
                "the v2 ledger rows were measured on 2026-08-08 code; "
                "differencing against them would charge whatever landed since "
                "to the band change"
            ),
            **measured,
        }
        payload["predicted_vs_measured"] = compare_with_prediction(measured)
    return payload


def markdown_table(payload: dict[str, Any]) -> str:
    """The bridge as a table a human reads, not a JSON a script reads."""

    lines = [
        "| mode | correction | SR before | SR after | Δ SR | Δ mean dtg (m) | K0 flips |",
        "|---|---|---|---|---|---|---|",
    ]
    measured = payload.get("measured_bridge") or {}
    for mode, cells in sorted((measured.get("deltas") or {}).items()):
        cell = cells.get("d_next_to_band") or {}
        dtg = cell.get("mean_dtg_delta_m")
        flips = sorted(
            set(cell.get("k0_arrival_gained") or ()) | set(cell.get("k0_arrival_lost") or ())
        )
        lines.append(
            f"| {mode} | (d) surface-anchored next_to band | {cell.get('sr_before')} | "
            f"{cell.get('sr_after')} | {cell.get('sr_delta')} | "
            f"{'—' if dtg is None else f'{dtg:+.4f}'} | {', '.join(flips) or 'none'} |"
        )
    spec = payload["spec_bridge"]
    lines.append("")
    lines.append("| episode | instruction | anchor R (m) | v2 band | v3 band |")
    lines.append("|---|---|---|---|---|")
    for row in spec["changed_rows"]:
        lines.append(
            f"| `{row['episode_id']}` | {row['instruction']} | "
            f"{row['anchor_footprint_m']:.6f} | "
            f"({row['v2_band_m'][0]:.4f}, {row['v2_band_m'][1]:.4f}) | "
            f"({row['v3_band_m'][0]:.4f}, {row['v3_band_m'][1]:.4f}) |"
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
    table = markdown_table(payload)
    if args.markdown is not None:
        args.markdown.write_text(table + "\n", encoding="utf-8")
    print(table)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
