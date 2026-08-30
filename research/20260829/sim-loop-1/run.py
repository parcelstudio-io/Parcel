"""LIT-1 runner — N seeded episodes, one results.json, the environment pinned.

Everything amendment L10 asks the run to guarantee is set HERE, once, before a
runtime exists, so no episode can be run with a different environment than the
one RESULTS.md reports:

* ``TMPDIR`` unset (a long ``TMPDIR`` breaks the unix-socket path);
* ``PARCEL_MEMORY_PATH`` -> scratch under this experiment's own cache dir, and
  ``PARCEL_MEMORY_PURPOSE`` removed (the owner's store is never opened);
* ``PARCEL_REALTIME_SPEND_LEDGER`` -> the WAVE ledger shared with MB-1;
* ``PARCEL_REALTIME_CONFIG`` -> the wave-local realtime yaml (staged by MB-1),
  set for EVERY tier and not only the hosted one, so ``_realtime_spend_note``
  names the wave file in the fake runs too and the assertion the amendment asks
  for is actually testable there;
* a wave-local ``robot.yaml`` carrying ``audio.ear.governor`` with the wave's
  envelope, reused from MB-1's copy when MB-1 already made one.

Usage
-----
``.parcel/bin/python research/20260829/sim-loop-1/run.py --scenario door_sofa_keys --voice fake --seed 20260829 --runs 5``
``.parcel/bin/python research/20260829/sim-loop-1/run.py --scenario door_sofa_keys --voice hosted --runs 3``
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

WORKROOT = Path(os.path.expanduser("~/.cache/parcel-0e/lit1"))
WAVE_DIR = Path(os.path.expanduser("~/.cache/parcel-0e/wave20260829"))
WAVE_LEDGER = WAVE_DIR / "spend.jsonl"
MB1_DIR = Path(os.path.expanduser("~/.cache/parcel-0e/mb1"))
MB1_REALTIME = MB1_DIR / "realtime.yaml"
MB1_ROBOT = MB1_DIR / "robot.yaml"
LIT1_ROBOT = WORKROOT / "robot.yaml"

#: This experiment's sub-cap inside the wave's $5.00.  Enforced here as a REFUSAL
#: to start another hosted episode, on top of (never instead of) the product's
#: own ear governor and arming gate.
LIT1_SUBCAP_USD = 2.00
WAVE_CAP_USD = 5.00

#: The ear-governor block amendment L10 pins for this wave.
GOVERNOR_BLOCK = {
    "envelope_usd": 5.0,
    "reserve_usd": 0.0,
    "warn_usd": 4.0,
    "daily_cap_usd": 5.0,
    "refuse_when_unknown": True,
}


def prepare_environment(*, voice: str) -> dict:
    """Pin the environment and return what was pinned, for the results file."""

    os.environ.pop("TMPDIR", None)
    os.environ.pop("PARCEL_MEMORY_PURPOSE", None)
    WORKROOT.mkdir(parents=True, exist_ok=True)
    WAVE_DIR.mkdir(parents=True, exist_ok=True)
    WAVE_LEDGER.touch(exist_ok=True)
    os.environ["PARCEL_MEMORY_PATH"] = str(WORKROOT / "memory-lit1.sqlite3")
    os.environ["PARCEL_REALTIME_SPEND_LEDGER"] = str(WAVE_LEDGER)

    robot_yaml = _wave_robot_yaml()
    if MB1_REALTIME.exists():
        os.environ["PARCEL_REALTIME_CONFIG"] = str(MB1_REALTIME)
    return {
        "TMPDIR": os.environ.get("TMPDIR"),
        "PARCEL_MEMORY_PATH": os.environ.get("PARCEL_MEMORY_PATH"),
        "PARCEL_MEMORY_PURPOSE": os.environ.get("PARCEL_MEMORY_PURPOSE"),
        "PARCEL_REALTIME_SPEND_LEDGER": os.environ.get("PARCEL_REALTIME_SPEND_LEDGER"),
        "PARCEL_REALTIME_CONFIG": os.environ.get("PARCEL_REALTIME_CONFIG"),
        "wave_robot_yaml": str(robot_yaml) if robot_yaml else None,
        "voice": voice,
        "credential_present": bool(
            os.environ.get(
                os.environ.get("PARCEL_REALTIME_KEY_ENV", "").strip() or "OPENAI_API_KEY", ""
            ).strip()
        ),
        "_credential_note": (
            "presence only — the value is never read, logged, printed or passed on"
        ),
    }


def _wave_robot_yaml() -> Path | None:
    """The wave-local ``robot.yaml`` with this wave's ear governor.

    MB-1 may already have made one; reuse it rather than writing a second file
    with a second opinion about the envelope.  Otherwise copy the shipped
    ``configs/robot.yaml`` and overlay ONLY ``audio.ear.governor``.
    """

    import yaml

    if MB1_ROBOT.exists():
        return MB1_ROBOT
    source = REPO / "configs" / "robot.yaml"
    if not source.exists():
        return None
    if not LIT1_ROBOT.exists():
        config = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        audio = config.setdefault("audio", {})
        ear = audio.setdefault("ear", {})
        ear["governor"] = dict(GOVERNOR_BLOCK)
        LIT1_ROBOT.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return LIT1_ROBOT


def ledger_total() -> float:
    if not WAVE_LEDGER.exists():
        return 0.0
    total = 0.0
    for line in WAVE_LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        for key in ("estimated_usd", "usd", "cost_usd", "estimated_cost_usd"):
            if key in row:
                total += float(row[key])
                break
    return total


def _percentiles(values: list[float]) -> dict:
    """p50 always (with n); p95 ONLY when n >= 20 (amendment L9)."""

    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return {"n": 0, "p50": None, "p95": None, "p95_note": "no samples"}
    row = {
        "n": len(clean),
        "p50": round(statistics.median(clean), 1),
        "min": round(clean[0], 1),
        "max": round(clean[-1], 1),
    }
    if len(clean) >= 20:
        index = max(0, min(len(clean) - 1, round(0.95 * (len(clean) - 1))))
        row["p95"] = round(clean[index], 1)
        row["p95_note"] = ""
    else:
        row["p95"] = None
        row["p95_note"] = f"withheld: n={len(clean)} < 20 (amendment L9)"
    return row


def grounding_check(jsonl: str | Path, scenario: dict) -> dict:
    """Amendment L8's keys clause, scored POST HOC against everything spoken.

    Computed from the JSONL rather than inside the loop so it can be re-scored
    on any recorded run, including ones made before this check existed.

    Read it for what it is per tier. In the FAKE tier every spoken line is a
    fixture this experiment wrote, so a pass proves the fixture is honest and
    nothing more — it is a check on the scenario, not on a model. It becomes a
    claim about a MODEL only on a hosted run, where the sentences are the
    provider's.
    """

    expected = scenario.get("expected_honest_keys_response") or {}
    path = Path(jsonl)
    if not expected or not path.exists():
        return {"scored": False, "reason": "no expectation, or no log"}
    spoken: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("hop") in {"voice_turn", "narration_event", "voice_offer"}:
            for key in ("spoken", "text"):
                value = row.get(key)
                if isinstance(value, str) and value:
                    spoken.append(value)
    blob = " ".join(spoken).lower()
    honest_hits = [
        phrase
        for phrase in expected.get("must_contain_any", [])
        if str(phrase).lower() in blob
    ]
    invented = [
        phrase
        for phrase in expected.get("must_not_contain_any", [])
        if str(phrase).lower() in blob
    ]
    offered = ("do you want me" in blob) or ("should i" in blob) or ("want me to" in blob)
    return {
        "scored": True,
        "lines_scored": len(spoken),
        "honest_capability_refusal": bool(honest_hits),
        "honest_phrases_found": honest_hits,
        "invented_result_claims": invented,
        "offered_return": offered,
        "passes": bool(honest_hits) and not invented and (
            offered or not expected.get("must_offer_return")
        ),
        "_tier_note": (
            "fake tier: the spoken lines are LIT-1's own fixtures, so this scores "
            "the scenario's honesty, never a model's"
        ),
    }


def aggregate(results: list[dict]) -> dict:
    """The RESULTS.md tables, computed once so prose cannot drift from them."""

    sequences = [tuple(row["receipt_kinds"]) for row in results if row.get("ok")]
    identical = len(set(sequences)) <= 1 and bool(sequences)
    hops: dict[str, list[float]] = {}
    for row in results:
        latencies = row.get("latencies") or {}
        for key in (
            "handle_text_ms",
            "utterance_to_cue_ms",
            "speech_end_to_receipt_ms",
            "cue_to_receipt_ms",
            "switch_ms",
        ):
            value = latencies.get(key)
            if isinstance(value, (int, float)):
                hops.setdefault(key, []).append(float(value))
        for key, value in (row.get("voice_latency_ms") or {}).items():
            if isinstance(value, (int, float)):
                hops.setdefault(key, []).append(float(value))
    provenance: dict[str, int] = {}
    for row in results:
        for key, count in (row.get("provenance_counts") or {}).items():
            provenance[key] = provenance.get(key, 0) + int(count)
    return {
        "runs": len(results),
        "ok_runs": sum(1 for row in results if row.get("ok")),
        "receipt_sequences": [list(seq) for seq in sequences],
        "distinct_sequences": [list(seq) for seq in sorted(set(sequences))],
        "identical_receipt_kinds": identical,
        "identical_n_of_m": f"{sequences.count(sequences[0]) if sequences else 0}/{len(results)}",
        "per_hop_latency_ms": {key: _percentiles(values) for key, values in hops.items()},
        "spend_usd_total": round(sum(float(row.get("spend_usd") or 0.0) for row in results), 6),
        "provenance_counts": provenance,
        "refusals": [item for row in results for item in (row.get("refusals") or [])],
        "name_scan_leaks": [
            item for row in results for item in (row.get("name_scan_leaks") or [])
        ],
        "teardown_clean": all(
            (row.get("teardown") or {}).get("clean", False) for row in results
        ),
        "motion_during_speech": [row.get("motion_during_speech") for row in results],
        "grounding_checks": [row.get("grounding_check") for row in results],
    }


def pgrep_proof() -> dict:
    """Amendment L3, at the very end of the run: no LIT-1 sim is left alive."""

    out = subprocess.run(
        ["pgrep", "-af", "parcel_robot.sim"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    ).stdout
    mine = [line for line in out.splitlines() if str(WORKROOT) in line]
    return {
        "all_sims_on_host": out.splitlines(),
        "lit1_sims_alive": mine,
        "clean": not mine,
        "_note": "only LIT-1's own sockets are this run's business; peers' sims are listed, never killed",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LIT-1 — run N episodes of the loop")
    parser.add_argument("--scenario", default="door_sofa_keys")
    parser.add_argument("--variant", default="base")
    parser.add_argument("--voice", choices=("fake", "hosted", "none"), default="fake")
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--index", type=int, default=1)
    parser.add_argument("--outdir", default=str(HERE / "artifacts"))
    parser.add_argument("--results", default=str(HERE / "results.json"))
    parser.add_argument(
        "--merge",
        action="store_true",
        help="merge into an existing results.json instead of replacing it",
    )
    args = parser.parse_args(argv)

    env = prepare_environment(voice=args.voice)
    print("[lit1] environment:", json.dumps(env, indent=2))

    if args.voice == "hosted" and not env["credential_present"]:
        # NOT a short circuit.  With no credential the lane's transport factory
        # resolves to ``None``, arming answers ``no_transport``, and
        # ``submit_realtime_text`` raises before a socket is opened — so ONE
        # episode is run anyway, at a cost of exactly $0, because the refusal
        # ROWS (the governor snapshot, the typed refusal, the untouched ledger)
        # are the evidence that the fail-closed path is the one that runs.  The
        # tier is still reported UNMEASURED: a refusal is not a latency.
        print(
            "[lit1] NO REALTIME CREDENTIAL in this session's environment. The lane "
            "cannot arm (`no_transport`). Running ONE hosted episode anyway to "
            "record the refusal rows; the tier will be reported UNMEASURED and "
            "nothing is worked around."
        )
        args.runs = 1

    # Imported AFTER the environment is pinned: the module reads it at import.
    sys.path.insert(0, str(HERE))
    import sim_loop

    scenario = sim_loop.scenario_variant(
        sim_loop.load_scenario(args.scenario), args.variant
    )
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for offset in range(args.runs):
        run_index = args.index + offset
        if args.voice == "hosted":
            spent = ledger_total()
            if spent >= LIT1_SUBCAP_USD or spent >= WAVE_CAP_USD:
                print(
                    f"[lit1] STOPPING before run {run_index}: the shared wave ledger "
                    f"reads ${spent:.4f}, at or past LIT-1's ${LIT1_SUBCAP_USD:.2f} sub-cap."
                )
                results.append(
                    {
                        "voice": "hosted",
                        "run_index": run_index,
                        "status": "UNMEASURED",
                        "reason": f"sub-cap reached (ledger ${spent:.4f})",
                        "spend_usd": 0.0,
                    }
                )
                break
        print(f"[lit1] --- run {run_index} ({args.voice}, {scenario['id']}) ---")
        result = sim_loop.run_scenario(
            scenario,
            voice=args.voice,
            seed=args.seed,
            index=run_index,
            outdir=outdir,
            variant=args.variant,
        )
        row = result.as_dict()
        row["grounding_check"] = grounding_check(row.get("jsonl", ""), scenario)
        if args.voice == "hosted" and not env["credential_present"]:
            row["status"] = "UNMEASURED"
            row["status_reason"] = (
                "no realtime credential in the environment; the lane answers "
                "no_transport and no hosted turn was ever billed"
            )
        results.append(row)
        print(f"[lit1] receipt kinds: {row['receipt_kinds']}")
        print(f"[lit1] ok={row['ok']} error={row['error']!r} spend=${row['spend_usd']}")

    _write_results(Path(args.results), results, args, env, merge=args.merge)
    return 0


def _write_results(path: Path, results: list[dict], args, env: dict, *, merge: bool) -> None:
    key = f"{args.scenario}:{args.variant}:{args.voice}"
    payload = {}
    if merge and path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            payload = {}
    payload.setdefault("experiment", "LIT-1")
    payload.setdefault("groups", {})
    payload["environment"] = env
    payload["wave_ledger_total_usd"] = round(ledger_total(), 6)
    payload["lit1_subcap_usd"] = LIT1_SUBCAP_USD
    payload["groups"][key] = {
        "scenario": args.scenario,
        "variant": args.variant,
        "voice": args.voice,
        "seed": args.seed,
        "runs": results,
        "summary": aggregate([row for row in results if "receipt_kinds" in row]),
    }
    payload["teardown_proof"] = pgrep_proof()
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"[lit1] wrote {path}")
    summary = payload["groups"][key]["summary"]
    print(
        f"[lit1] SUMMARY {key}: ok={summary['ok_runs']}/{summary['runs']} "
        f"identical_kinds={summary['identical_receipt_kinds']} "
        f"({summary['identical_n_of_m']}) spend=${summary['spend_usd_total']}"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
