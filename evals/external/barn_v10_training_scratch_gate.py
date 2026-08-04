"""Authenticate, gate, and immutably record the V10 ten-world training run.

V10 deliberately reuses the V9 training evidence protocol and its processor
identities.  This wrapper adds candidate-specific package, manifest, freeze,
and planner-profile bindings; it does not reinterpret the V9 metrics or grant
development, holdout, promotion, leaderboard, or deployment authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .barn_v9_training_scratch_gate import evaluate_training_scratch_gate
from .barn_v10_planner_profile import (
    CANDIDATE_FREEZE_PATH,
    CANDIDATE_FREEZE_SHA256,
    CANDIDATE_MANIFEST_SHA256,
    CANDIDATE_PACKAGE_SHA256,
    NAVIGATION_CONFIG_SHA256,
    PROFILE_SHA256,
    REFERENCE_MANIFEST_SHA256,
    REFERENCE_PACKAGE_SHA256,
    REFERENCE_PROFILE_SHA256,
    TRAINING_WORLD_IDS,
    V10_GATE_ID,
    verify_v10_planner_profile,
)
from .barn_v10_planner_profile_candidate import PROFILE_DESTINATION

SCHEMA_VERSION = 1
DECISION_ID = "parcel-barn-v10-planner-profile-training-gate-decision-v1"
V10_GATE_DECLARATION_SHA256 = "f196691c9b231d41d543a9f21a934f0eb31078d03689cb02482d838740a2df30"
EXPECTED_CHECK_COUNT = 38
EXPECTED_EXPERIMENT_ID = "barn-v10-training-planner-profile-f0b3c157"
DEFAULT_DECISION_NAME = "v10-planner-profile-training-gate-decision-v1.json"

_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


class V10TrainingGateError(RuntimeError):
    """Raised when V10 evidence differs from the frozen candidate contract."""


@dataclass(frozen=True, slots=True)
class V10GateDecisionWriteResult:
    path: Path
    sha256: str
    size_bytes: int


def _canonical_json(value: object, *, pretty: bool = False) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=True,
        )
        + ("\n" if pretty else "")
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _lexical_absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _reject_symlink_components(path: Path, *, label: str) -> None:
    for component in (path, *path.parents):
        if os.path.lexists(component) and stat.S_ISLNK(os.lstat(component).st_mode):
            raise V10TrainingGateError(f"{label} path contains a symbolic link: {component}")


def _require_v10_bindings(result: Mapping[str, Any]) -> None:
    policy_pair = result.get("policy_pair")
    bindings = result.get("policy_bindings")
    evidence = result.get("evidence_contract")
    if not isinstance(policy_pair, Mapping) or not isinstance(bindings, Mapping):
        raise V10TrainingGateError("generic gate omitted V10 policy bindings")
    if not isinstance(evidence, Mapping):
        raise V10TrainingGateError("generic gate omitted its evidence contract")
    expected_bindings = {
        "reference_package_sha256": REFERENCE_PACKAGE_SHA256,
        "candidate_package_sha256": CANDIDATE_PACKAGE_SHA256,
        "reference_manifest_sha256": REFERENCE_MANIFEST_SHA256,
        "candidate_manifest_sha256": CANDIDATE_MANIFEST_SHA256,
        "candidate_experiment_id": EXPECTED_EXPERIMENT_ID,
        "candidate_freeze_path": str(CANDIDATE_FREEZE_PATH.resolve()),
        "candidate_freeze_sha256": CANDIDATE_FREEZE_SHA256,
        "manifest_bindings_available": True,
        "isolated_pair_binding_available": True,
        "executed_policy_provenance_available": True,
        "planner_profile_factor_available": True,
        "planner_profile_authorization_available": True,
        "reference_model_artifact_sha256": REFERENCE_PROFILE_SHA256,
        "candidate_model_artifact_sha256": PROFILE_SHA256,
        "active_model_relative_path": PROFILE_DESTINATION,
        "all_available_bindings_verified": True,
    }
    if dict(bindings) != expected_bindings:
        raise V10TrainingGateError("report bindings are not the exact executed V8/V10 policy pair")
    if dict(policy_pair) != {
        "reference_package_sha256": REFERENCE_PACKAGE_SHA256,
        "candidate_package_sha256": CANDIDATE_PACKAGE_SHA256,
    }:
        raise V10TrainingGateError("generic gate policy pair is not the exact V8/V10 pair")
    if evidence.get("analysis_policy_bindings_match_report") is not True:
        raise V10TrainingGateError("analysis does not bind the same executed V10 policy")


def evaluate_v10_training_scratch_gate(
    report_path: str | Path,
    analysis_path: str | Path,
    *,
    expected_report_sha256: str,
    expected_analysis_sha256: str,
) -> dict[str, Any]:
    """Return a candidate-specific decision over the unchanged V9 gate result."""

    verified = verify_v10_planner_profile()
    screen = verified.freeze["scratch_screen"]
    gate_result = evaluate_training_scratch_gate(
        report_path,
        analysis_path,
        expected_report_sha256=expected_report_sha256,
        expected_analysis_sha256=expected_analysis_sha256,
        gate=screen,
    )
    if (
        gate_result.get("gate_id") != V10_GATE_ID
        or gate_result.get("gate_sha256") != V10_GATE_DECLARATION_SHA256
        or gate_result.get("screen_world_ids") != list(TRAINING_WORLD_IDS)
        or gate_result.get("check_count") != EXPECTED_CHECK_COUNT
    ):
        raise V10TrainingGateError("generic gate result differs from the frozen V10 screen")
    _require_v10_bindings(gate_result)

    core: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "decision_id": DECISION_ID,
        "decision_hash_contract": (
            "sha256 of canonical JSON for every decision field except decision_sha256"
        ),
        "candidate_freeze": {
            "path": str(verified.freeze_path),
            "sha256": verified.freeze_sha256,
        },
        "candidate": {
            "package_sha256": CANDIDATE_PACKAGE_SHA256,
            "manifest_sha256": CANDIDATE_MANIFEST_SHA256,
            "profile_sha256": PROFILE_SHA256,
            "navigation_config_sha256": NAVIGATION_CONFIG_SHA256,
        },
        "reference": {
            "package_sha256": REFERENCE_PACKAGE_SHA256,
            "manifest_sha256": REFERENCE_MANIFEST_SHA256,
            "profile_sha256": REFERENCE_PROFILE_SHA256,
        },
        "protocol_note": "V10 candidate evaluated under unchanged V9 training evidence protocol",
        "claims": {
            "official_score": False,
            "leaderboard": False,
            "promotion_evidence": False,
            "development_authorized": False,
            "holdout_authorized": False,
            "deployment_enabled": False,
            "accepted_for_next_training_stage": gate_result.get("gate_passed") is True,
        },
        "gate_result": gate_result,
    }
    return {**core, "decision_sha256": _sha256(_canonical_json(core))}


def write_v10_gate_decision_exclusive(
    path: str | Path,
    decision: Mapping[str, Any],
) -> V10GateDecisionWriteResult:
    """Write one immutable decision without following links or replacing data."""

    if not isinstance(decision, Mapping):
        raise TypeError("decision must be an object")
    document = dict(decision)
    expected_decision_sha = document.pop("decision_sha256", None)
    if expected_decision_sha != _sha256(_canonical_json(document)):
        raise V10TrainingGateError("decision_sha256 does not authenticate the full decision")
    target = _lexical_absolute(path)
    _reject_symlink_components(target, label="V10 gate decision")
    target.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(target, label="V10 gate decision")
    encoded = _canonical_json(dict(decision), pretty=True)
    try:
        with target.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o444)
            os.fsync(stream.fileno())
    except FileExistsError:
        raise FileExistsError(f"refusing to replace V10 gate decision: {target}") from None
    metadata = os.lstat(target)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_mode & _WRITE_BITS
    ):
        raise V10TrainingGateError("written V10 gate decision is not immutable and unaliased")
    return V10GateDecisionWriteResult(
        path=target,
        sha256=_sha256(encoded),
        size_bytes=len(encoded),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--expected-analysis-sha256", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    decision = evaluate_v10_training_scratch_gate(
        args.report,
        args.analysis,
        expected_report_sha256=args.expected_report_sha256,
        expected_analysis_sha256=args.expected_analysis_sha256,
    )
    output = args.output or args.analysis.parent / DEFAULT_DECISION_NAME
    written = write_v10_gate_decision_exclusive(output, decision)
    gate_result = decision["gate_result"]
    print(
        json.dumps(
            {
                "decision_path": str(written.path),
                "decision_artifact_sha256": written.sha256,
                "decision_sha256": decision["decision_sha256"],
                "gate_declaration_sha256": gate_result["gate_sha256"],
                "gate_passed": gate_result["gate_passed"],
                "failed_check_ids": gate_result["failed_check_ids"],
            },
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if gate_result["gate_passed"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "DECISION_ID",
    "DEFAULT_DECISION_NAME",
    "EXPECTED_CHECK_COUNT",
    "SCHEMA_VERSION",
    "V10_GATE_DECLARATION_SHA256",
    "V10GateDecisionWriteResult",
    "V10TrainingGateError",
    "evaluate_v10_training_scratch_gate",
    "main",
    "write_v10_gate_decision_exclusive",
]
