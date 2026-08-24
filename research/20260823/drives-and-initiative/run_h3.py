"""Run the H3 arms and write the pre-registered rows D1-D8.

    .parcel/bin/python research/20260823/drives-and-initiative/run_h3.py

Four arms x 3 seeds x 60 simulated minutes at 10 Hz, plus two extra
configurations that measure rows the four arms cannot guarantee on their own:

* ``night`` — the radius-6 arm with the clock started at 21:30 so half the run
  is inside the NIGHT band (row D6's second half). The arms run in the
  afternoon so that D1's denominator is a full waking hour.
* ``d5probe`` — the radius-6 arm with an owner turn pulled to +3 s after the
  first admitted initiative and an e-stop to +3 s after the second, so row D5
  is measured against a behaviour that is certainly running. The arms report
  only the overlaps that happened by themselves.

Raw per-run JSON goes to ``results/``; the per-tick JSONL (drive vector,
stimuli, proposal, verdict, command — the Stage-B training corpus shape) is
gzipped, one file per run, under the scratch directory, with the headline
arm's first run copied into ``logs/`` as the format sample.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from arena import (
    ERRAND_BUDGET_S,
    H2_SELECTION,
    HOME_POSE,
    INITIATIVE_REFRACTORY_S,
    MAP_VISIBILITY_RANGE_M,
    InitiativeArena,
    RunConfig,
    shipped_default_candidate_probe,
)

SEEDS = (1, 2, 3)
ARMS = ("baseline", "look_remark", "radius6", "radius10")
HEADLINE_ARM = "radius6"


def _run(payload: dict[str, object]) -> dict[str, object]:
    config = RunConfig(
        arm=str(payload["arm"]),
        seed=int(payload["seed"]),  # type: ignore[arg-type]
        duration_s=float(payload["duration_s"]),  # type: ignore[arg-type]
        start_hour=float(payload["start_hour"]),  # type: ignore[arg-type]
        log_path=Path(str(payload["log_path"])) if payload.get("log_path") else None,
        probe_preemption=bool(payload.get("probe_preemption", False)),
        withhold_time_bands=bool(payload.get("withhold_time_bands", True)),
    )
    summary = InitiativeArena(config).run()
    summary["label"] = payload["label"]
    return summary


def _jobs(scratch: Path, duration_s: float) -> list[dict[str, object]]:
    jobs: list[dict[str, object]] = []
    for arm in ARMS:
        for seed in SEEDS:
            jobs.append(
                {
                    "label": arm,
                    "arm": arm,
                    "seed": seed,
                    "duration_s": duration_s,
                    "start_hour": 14.0,
                    "log_path": str(scratch / f"ticks_{arm}_seed{seed}.jsonl.gz"),
                }
            )
    for seed in SEEDS:
        jobs.append(
            {
                "label": "night",
                "arm": HEADLINE_ARM,
                "seed": seed,
                "duration_s": duration_s,
                "start_hour": 21.5,
                "log_path": str(scratch / f"ticks_night_seed{seed}.jsonl.gz"),
            }
        )
        jobs.append(
            {
                "label": "d5probe",
                "arm": HEADLINE_ARM,
                "seed": seed,
                "duration_s": duration_s,
                "start_hour": 14.0,
                "probe_preemption": True,
                "log_path": str(scratch / f"ticks_d5probe_seed{seed}.jsonl.gz"),
            }
        )
    return jobs


def _mean(values: list[float]) -> float | None:
    return None if not values else statistics.fmean(values)


def _by_label(rows: list[dict[str, object]], label: str) -> list[dict[str, object]]:
    return [row for row in rows if row.get("label") == label]


def _rows_table(rows: list[dict[str, object]]) -> dict[str, object]:
    """The pre-registered table D1-D8, computed from the raw run summaries."""

    headline = _by_label(rows, HEADLINE_ARM)
    look_remark = _by_label(rows, "look_remark")
    baseline = _by_label(rows, "baseline")
    radius10 = _by_label(rows, "radius10")
    night = _by_label(rows, "night")
    probes = _by_label(rows, "d5probe")
    initiative_rows = headline + look_remark + radius10 + night + probes

    by_kind: dict[str, int] = {}
    for row in headline:
        for kind, count in dict(row["admitted_by_kind"]).items():  # type: ignore[arg-type]
            by_kind[kind] = by_kind.get(kind, 0) + int(count)

    proposals = sum(int(row["proposals"]) for row in initiative_rows)  # type: ignore[arg-type]
    admitted = sum(int(row["admitted"]) for row in initiative_rows)  # type: ignore[arg-type]
    refusals: dict[str, int] = {}
    for row in initiative_rows:
        for reason, count in dict(row["refusals"]).items():  # type: ignore[arg-type]
            refusals[reason] = refusals.get(reason, 0) + int(count)

    preemptions = [item for row in initiative_rows for item in row["preemptions"]]  # type: ignore[index]
    latencies = [int(item["ticks_to_yield"]) for item in preemptions]

    quiet = sum(int(row["admitted_in_quiet"]) for row in initiative_rows)  # type: ignore[arg-type]
    night_hits = sum(int(row["admitted_in_night"]) for row in initiative_rows)  # type: ignore[arg-type]

    attributed = sum(int(row["attributed_initiations"]) for row in initiative_rows)  # type: ignore[arg-type]

    baseline_translation = {str(row["translation_sha"]) for row in baseline}
    look_translation = {str(row["translation_sha"]) for row in look_remark}
    baseline_command = {str(row["command_sha"]) for row in baseline}
    look_command = {str(row["command_sha"]) for row in look_remark}

    contacts = sum(int(row["agent_contacts"]) for row in initiative_rows)  # type: ignore[arg-type]
    clearances = [
        float(row["min_agent_clearance_m"])
        for row in initiative_rows
        if row["min_agent_clearance_m"] is not None
    ]
    toward = [
        float(row["min_clearance_toward_agent_m"])
        for row in initiative_rows
        if row["min_clearance_toward_agent_m"] is not None
    ]

    return {
        "D1_initiations_per_hour_headline": {
            "per_run": [row["initiations_per_hour"] for row in headline],
            "mean": _mean([float(row["initiations_per_hour"]) for row in headline]),
            "by_kind_total": by_kind,
            "criterion": "3-8 total per simulated hour (radius-6 arm)",
        },
        "D2_admitted_fraction": {
            "proposals": proposals,
            "admitted": admitted,
            "fraction": None if not proposals else admitted / proposals,
            "refusals": refusals,
            "criterion": ">= 0.80",
        },
        "D3_radius_and_coverage": {
            "max_radius_m_headline": [row["max_radius_m"] for row in headline],
            "max_radius_m_radius10": [row["max_radius_m"] for row in radius10],
            "max_radius_m_look_remark": [row["max_radius_m"] for row in look_remark],
            "max_radius_m_baseline": [row["max_radius_m"] for row in baseline],
            "visited_cell_fraction_headline": [
                row["visited_cell_fraction"] for row in headline
            ],
            "candidates_mean_headline": [row["candidates_mean"] for row in headline],
            "criterion": ">= 6 m; per-block visit fraction reported",
        },
        "D4_contacts_and_clearance": {
            "contacts": contacts,
            "contacts_while_translating": sum(
                int(row["contacts_while_translating"]) for row in initiative_rows  # type: ignore[arg-type]
            ),
            "contacts_while_stationary": sum(
                int(row["contacts_while_stationary"]) for row in initiative_rows  # type: ignore[arg-type]
            ),
            "contact_seconds": sum(
                float(row["contact_seconds"]) for row in initiative_rows  # type: ignore[arg-type]
            ),
            "min_clearance_m": None if not clearances else min(clearances),
            "min_clearance_toward_agent_m": None if not toward else min(toward),
            "person_stop_m": rows[0]["person_stop_m"] if rows else None,
            "static_collisions": sum(
                int(row["static_collisions"]) for row in initiative_rows  # type: ignore[arg-type]
            ),
            "criterion": "0 contacts; clearance >= profile stop distance",
        },
        "D5_preemption": {
            "events": len(preemptions),
            "ticks_to_yield_max": None if not latencies else max(latencies),
            "seconds_to_yield_max": None if not latencies else max(latencies) * 0.1,
            "by_trigger": {
                trigger: len([item for item in preemptions if item["trigger"] == trigger])
                for trigger in {str(item["trigger"]) for item in preemptions}
            },
            "commands_at_yield_all_zero": all(
                all(abs(float(value)) <= 0.0 for value in item["command_at_yield"])  # type: ignore[index]
                for item in preemptions
            ),
            "criterion": "<= 1 tick (0.1 s)",
        },
        "D6_quiet_and_night": {
            "admitted_inside_quiet_window": quiet,
            "admitted_inside_night_band": night_hits,
            "night_runs": len(night),
            "night_run_initiations": [row["expressive_initiations"] for row in night],
            "criterion": "0",
        },
        "D7_radius_zero_changes_no_navigation_command": {
            "baseline_translation_sha": sorted(baseline_translation),
            "look_remark_translation_sha": sorted(look_translation),
            "translation_streams_identical": baseline_translation == look_translation,
            "baseline_command_sha": sorted(baseline_command),
            "look_remark_command_sha": sorted(look_command),
            "full_command_streams_identical": baseline_command == look_command,
            "criterion": "0 (byte-identical motion)",
        },
        "D8_attribution": {
            "initiations": admitted,
            "attributed_to_one_drive": attributed,
            "fraction": None if not admitted else attributed / admitted,
            "criterion": "100 %",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-s", type=float, default=3600.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--f4-probe",
        action="store_true",
        help="only the three night runs, with the time-band withholding OFF",
    )
    parser.add_argument(
        "--scratch",
        type=Path,
        default=Path(
            "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/"
            "0b505906-665b-45ea-a2b7-686b3aecb89d/scratchpad/h3"
        ),
    )
    args = parser.parse_args()

    scratch = args.scratch
    scratch.mkdir(parents=True, exist_ok=True)
    results = HERE / "results"
    results.mkdir(exist_ok=True)

    jobs = _jobs(scratch, args.duration_s)
    if args.f4_probe:
        jobs = [
            {
                "label": "f4probe",
                "arm": HEADLINE_ARM,
                "seed": seed,
                "duration_s": args.duration_s,
                "start_hour": 21.5,
                "withhold_time_bands": False,
                "log_path": str(scratch / f"ticks_f4probe_seed{seed}.jsonl.gz"),
            }
            for seed in SEEDS
        ]
    rows: list[dict[str, object]] = []
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for summary in pool.map(_run, jobs):
            rows.append(summary)
            print(
                f"done {summary['label']:12s} seed={summary['seed']} "
                f"init/h={summary['initiations_per_hour']:.1f} "
                f"admit={summary['admitted_fraction']} "
                f"radius={float(summary['max_radius_m']):.2f} "
                f"contacts={summary['agent_contacts']}",
                flush=True,
            )

    parameters = {
        "home_pose": list(HOME_POSE),
        "map_visibility_range_m": MAP_VISIBILITY_RANGE_M,
        "initiative_refractory_s": INITIATIVE_REFRACTORY_S,
        "errand_budget_s": ERRAND_BUDGET_S,
        "h2_selection": asdict(H2_SELECTION),
        "seeds": list(SEEDS),
        "duration_s": args.duration_s,
        "shipped_default_candidate_probe": shipped_default_candidate_probe(),
    }
    if args.f4_probe:
        (results / "runs_f4probe.json").write_text(
            json.dumps({"parameters": parameters, "runs": rows}, indent=1, sort_keys=True)
        )
        for row in rows:
            print(
                f"f4probe seed={row['seed']} initiations={row['expressive_initiations']} "
                f"in_night={row['admitted_in_night']} in_quiet={row['admitted_in_quiet']}",
                flush=True,
            )
        return 0
    (results / "runs.json").write_text(
        json.dumps({"parameters": parameters, "runs": rows}, indent=1, sort_keys=True)
    )
    (results / "rows.json").write_text(
        json.dumps(
            {"parameters": parameters, "rows": _rows_table(rows)}, indent=1, sort_keys=True
        )
    )
    print(json.dumps(_rows_table(rows), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
