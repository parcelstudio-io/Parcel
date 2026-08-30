"""Combined fail-closed acceptance wrapper for completed DSOAK-1 artifacts.

The preregistered runner's exit code is not evidence.  This wrapper requires
both the independent result oracle and the post-start continuity monitor to
accept the same final bytes.  It deliberately keeps the two detailed reports
intact so a structural failure cannot be mistaken for a scientific red result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from verify_monitor import verify as verify_monitor
from verify_results import Audit

HERE = Path(__file__).resolve().parent


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def verify(result_path: Path, monitor_path: Path) -> dict[str, Any]:
    raw = result_path.read_bytes()
    value = json.loads(raw, parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise TypeError("result must be a JSON object")
    result_report = Audit(value, result_path).run()
    monitor_report = verify_monitor(monitor_path, result_path=result_path)
    accepted = bool(
        result_report.get("completion_acceptance_pass")
        and monitor_report.get("continuity_observed_to_completion")
    )
    return {
        "schema": "parcel.duplex_soak.final_verification.v1",
        "completion_acceptance_pass": accepted,
        "result_sha256": hashlib.sha256(raw).hexdigest(),
        "monitor_sha256": _sha256(monitor_path),
        "verify_results_sha256": _sha256(HERE / "verify_results.py"),
        "verify_monitor_sha256": _sha256(HERE / "verify_monitor.py"),
        "combined_verifier_sha256": _sha256(Path(__file__)),
        "result_verification": result_report,
        "monitor_verification": monitor_report,
        "scope_warning": (
            "Acceptance supports only durability of the frozen desktop procedural "
            "program plus continuity from the monitor's late start. It is not "
            "narration truth, physical safety, social-navigation, or mount evidence."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, default=HERE / "results.json")
    parser.add_argument("--monitor", type=Path, default=HERE / "external-monitor.jsonl")
    args = parser.parse_args()
    try:
        report = verify(args.result, args.monitor)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        report = {
            "schema": "parcel.duplex_soak.final_verification.v1",
            "completion_acceptance_pass": False,
            "errors": [str(error)],
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["completion_acceptance_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
