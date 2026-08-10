"""CLI for WALK_WITH_ME_V1 frozen integration pack (K8).

Usage:
    .parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --smoke
    .parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --mode stub
    .parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --write-freeze
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from evals.walk_with_me.generator import (
    FREEZE_SEED,
    default_freeze_path,
    generate_frozen_pack,
    matrix_digest,
    write_frozen_manifest,
)
from evals.walk_with_me.runner import (
    DOES_NOT_PROVE,
    RUNNER_VERSION,
    WalkWithMeRunner,
    aggregate_results,
    load_pack_from_freeze,
)

DEFAULT_OUT = Path(__file__).resolve().parent / "results"
SMOKE_IDS = ("wwm-pause-resume", "wwm-barge-in-tts")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=FREEZE_SEED)
    parser.add_argument("--mode", default="stub", choices=("stub", "headless"))
    parser.add_argument("--max-steps", type=int, default=80)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="CI-light: load freeze + run pause/resume + barge-in stubs",
    )
    parser.add_argument(
        "--script",
        action="append",
        default=[],
        help="optional script_id filter (repeatable)",
    )
    parser.add_argument(
        "--write-freeze",
        action="store_true",
        help="regenerate evals/walk_with_me/freeze/manifest.json from generator",
    )
    parser.add_argument(
        "--pose-profile",
        default=None,
        help=(
            "stratum-1 pose tier from configs/navigation/pose.yaml "
            "(default: the truth passthrough, which is behavior-preserving)"
        ),
    )
    parser.add_argument(
        "--validate-freeze-only",
        action="store_true",
        help="load + digest-check the frozen manifest and exit",
    )
    args = parser.parse_args(argv)

    if args.write_freeze:
        path = write_frozen_manifest(default_freeze_path(), seed=args.seed)
        manifest, scripts = load_pack_from_freeze(path)
        print(
            json.dumps(
                {
                    "wrote": str(path),
                    "count": len(scripts),
                    "digest": manifest["digest"],
                    "freeze_seed": manifest["freeze_seed"],
                },
                sort_keys=True,
                indent=2,
            )
        )
        return 0

    if args.validate_freeze_only:
        manifest, scripts = load_pack_from_freeze()
        expected = matrix_digest(generate_frozen_pack(seed=int(manifest["freeze_seed"])))
        ok = manifest["digest"] == expected and len(scripts) == int(manifest["count"])
        print(
            json.dumps(
                {
                    "ok": ok,
                    "count": len(scripts),
                    "digest": manifest["digest"],
                    "themes": manifest.get("themes"),
                    "does_not_prove_n": len(manifest.get("does_not_prove") or []),
                },
                sort_keys=True,
                indent=2,
            )
        )
        return 0 if ok else 1

    freeze_path = default_freeze_path()
    if freeze_path.is_file():
        manifest, scripts = load_pack_from_freeze(freeze_path)
    else:
        scripts = generate_frozen_pack(seed=args.seed)
        manifest = {
            "pack_id": "walk-with-me-v1",
            "freeze_seed": args.seed,
            "digest": matrix_digest(scripts),
            "does_not_prove": list(DOES_NOT_PROVE),
        }

    script_ids: tuple[str, ...] | None = None
    if args.smoke:
        script_ids = SMOKE_IDS
    elif args.script:
        script_ids = tuple(args.script)

    runner = WalkWithMeRunner(
        mode=args.mode,
        max_steps=args.max_steps,
        pose_profile=args.pose_profile,
    )
    started = time.perf_counter()
    results = runner.run_pack(scripts, script_ids=script_ids)
    elapsed_s = time.perf_counter() - started
    aggregate = aggregate_results(results)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_id = f"walk-with-me-v1-{args.mode}-{stamp}"
    report = {
        "report_id": report_id,
        "runner_version": RUNNER_VERSION,
        "mode": args.mode,
        "smoke": bool(args.smoke),
        "pose_profile": args.pose_profile or "truth",
        "freeze_seed": manifest.get("freeze_seed", args.seed),
        "episode_digest": manifest.get("digest") or matrix_digest(scripts),
        "elapsed_s": elapsed_s,
        "aggregate": aggregate,
        "does_not_prove": list(DOES_NOT_PROVE),
        "scripts": [item.as_dict() for item in results],
    }

    args.out.mkdir(parents=True, exist_ok=True)
    report_path = args.out / f"{report_id}.json"
    report_path.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    ledger_row = {
        "report_id": report_id,
        "mode": args.mode,
        "smoke": bool(args.smoke),
        "n": aggregate["n"],
        "sr": aggregate["sr"],
        "hard_collision_total": int(aggregate["hard_collision_total"]),
        "failure_histogram": aggregate["failure_histogram"],
        "attribution_histogram": aggregate["attribution_histogram"],
        # Instrument 5 — differential arrival verdicts, per run.
        "authority_histogram": aggregate["authority_histogram"],
        "arrival_epsilon_m": aggregate["arrival_epsilon_m"],
        "episode_digest": report["episode_digest"],
        "report": report_path.name,
    }
    ledger_path = args.out / "ledger.jsonl"
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(ledger_row, sort_keys=True) + "\n")

    print(
        json.dumps(
            {
                "report": str(report_path),
                "n": aggregate["n"],
                "sr": aggregate["sr"],
                "mode": args.mode,
                "failure_histogram": aggregate["failure_histogram"],
                "attribution_histogram": aggregate["attribution_histogram"],
                "authority_histogram": aggregate["authority_histogram"],
            },
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
