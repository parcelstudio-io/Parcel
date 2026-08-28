"""Verify the fixed-source H2b replay pair and write canonical artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUN_A = HERE / "results-run4.json"
RUN_B = HERE / "results-run5.json"
CANONICAL = HERE / "results.json"
VERIFICATION = HERE / "verification.json"


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def verify() -> dict[str, Any]:
    first = _load(RUN_A)
    second = _load(RUN_B)
    payload = first["payload"]
    rows = payload["rows"]
    matrix = payload["matrix"]
    source_matches = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
        for path, expected in payload["source_digests"].items()
    }
    family_counts = Counter(row["family"] for row in matrix)
    row_counts = Counter((row["case_id"], row["arm"]) for row in rows)
    checks = {
        "payload_digest_recomputes_run4": first["payload_digest"] == _digest(payload),
        "payload_digest_recomputes_run5": second["payload_digest"]
        == _digest(second["payload"]),
        "fixed_source_payloads_identical": payload == second["payload"],
        "fixed_source_digests_identical": first["payload_digest"]
        == second["payload_digest"],
        "all_source_digests_current": all(source_matches.values()),
        "matrix_600_unique": len(matrix) == 600
        and len({row["case_id"] for row in matrix}) == 600,
        "families_120_each": set(family_counts.values()) == {120}
        and len(family_counts) == 5,
        "rows_1800_exact_arms": len(rows) == 1800
        and len(row_counts) == 1800
        and set(row_counts.values()) == {1},
        "matrix_digest_recomputes": payload["matrix_digest"] == _digest(matrix),
        "nine_pre_replay_gates_present": len(payload["gates"]) == 9,
        "exactly_alias_recovery_gate_failed": [
            name for name, passed in payload["gates"].items() if not passed
        ]
        == ["alias_recovery"],
        "motion_authorizations_zero": payload["summary"]["h2b_motion_authorizations"]
        == 0,
        "false_claims_zero": payload["summary"]["h2b_false_claims_total"] == 0,
    }
    return {
        "schema": "parcel.independent-completion-h2b.verification.v1",
        "canonical_run": RUN_A.name,
        "replay_run": RUN_B.name,
        "excluded_pilots": [
            {
                "path": "results-run1.json",
                "reason": "deadline sampled 2 ms before first-candidate + 4 s",
            },
            {
                "path": "results-run2.json",
                "reason": "identity-missing harness omitted the initial candidate",
            },
            {
                "path": "results-run3.json",
                "reason": "replay of the same identity-missing harness defect",
            },
        ],
        "payload_digest": first["payload_digest"],
        "source_matches": source_matches,
        "checks": checks,
        "integrity_pass": all(checks.values()),
        "experiment_supported": all(payload["gates"].values())
        and all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-canonical", action="store_true")
    args = parser.parse_args()
    result = verify()
    if args.write_canonical:
        shutil.copyfile(RUN_A, CANONICAL)
        VERIFICATION.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["integrity_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
