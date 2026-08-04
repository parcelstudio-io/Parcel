"""Verify and materialize the frozen V9 supervisory-gap S4 challenger.

S4 is a deployment-disabled, training-only successor to S2.  The exact
content-addressed V8 experimental control remains the parent bundle, and the
only candidate payload delta is the reviewed local-tracker subsystem.  This
module authenticates the pre-materialization freeze before it may create the
read-only candidate bundle.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from .barn_v9_policy_bundle import (
    V9CandidateBundle,
    V9CandidatePlan,
    plan_v9_candidate_bundle,
    prepare_v9_candidate_bundle,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ROOT = (
    REPO_ROOT
    / "evals/external/experiments/barn_sampled_predictive_tracker_v9/scratch_challengers"
    / "supervisory_gap_s4"
)
SCRATCH_FREEZE_PATH = EXPERIMENT_ROOT / "SCRATCH_FREEZE.json"

SCRATCH_FREEZE_SHA256 = "a26c32c92f85bd4e3d63f042578d8a5c9b3d66ef8c6690dde91a00797a140b9c"
SOURCE_CONTRACT_SHA256 = "53d19110a960c6a4972aa72737ab8191f3fc283bd23def976ae4df42155f08dc"
CANDIDATE_PACKAGE_SHA256 = "3c7396633e5b5df611e343d6ca8c5cf253e1bc975019a524394c48ffb7f3fec9"
CANDIDATE_MANIFEST_SHA256 = "a80c074cb3a23148c24b4a5b217c7e9fd744ef863d635f01e9e9b112a43e6b29"
REFERENCE_PACKAGE_SHA256 = "189ac31f0f6a461da9e10fad2ac21b2bc3a485a4d5245c517b1492b2a16eb7d9"
REFERENCE_MANIFEST_SHA256 = "d3bca126041d69afb5553ac29656a0152242c00f29a7b987803e9dc536914115"

S2_PACKAGE_SHA256 = "68e3e66638aea3549bb26618c6b29e02a8e2a309726dddc55c4ef53ad5a0159c"
S2_MANIFEST_SHA256 = "04867ea70a7c4f7f0d9f6383815e2d592df635eafb2d8833e193f70d4de4dad7"
S2_REPORT_SHA256 = "3ccce81f675a7556fa9618cb8c14dfea1ff5f0d35cd17732699dcaa49157962d"
S2_ANALYSIS_SHA256 = "1cc259ed55ee96ccfae9d784d9734924a7537f0e9da9b80418c05cc645a6ff9f"
S2_TRAINING_GATE_SHA256 = "254d53ac946c19a5c73dcfc6651f7e2f9c6b25911c2d8d4c43d8ea34f0e3"


class SupervisoryGapS4Error(RuntimeError):
    """Raised when the S4 challenger no longer matches its freeze."""


@dataclass(frozen=True, slots=True)
class VerifiedSupervisoryGapS4:
    plan: V9CandidatePlan
    freeze_path: Path
    freeze_sha256: str
    freeze: dict[str, Any]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _lexical_absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _strict_json(raw: bytes) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise SupervisoryGapS4Error(
                    f"scratch freeze contains duplicate field: {key}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> NoReturn:
        raise SupervisoryGapS4Error(
            f"scratch freeze contains non-finite value: {value}"
        )

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SupervisoryGapS4Error("scratch freeze is not strict JSON") from error
    if not isinstance(value, dict):
        raise SupervisoryGapS4Error("scratch freeze must contain an object")
    return value


def _read_unique_regular(path: str | Path) -> tuple[Path, bytes]:
    requested = _lexical_absolute(path)
    for component in (requested, *requested.parents):
        if os.path.lexists(component) and stat.S_ISLNK(os.lstat(component).st_mode):
            raise SupervisoryGapS4Error(
                f"scratch freeze path contains a symbolic link: {component}"
            )
    try:
        metadata = os.lstat(requested)
    except FileNotFoundError:
        raise SupervisoryGapS4Error(f"scratch freeze is missing: {requested}") from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise SupervisoryGapS4Error(
            "scratch freeze must be a uniquely linked regular file"
        )
    return requested, requested.read_bytes()


def verify_supervisory_gap_s4(
    *,
    experiment_root: str | Path = EXPERIMENT_ROOT,
    freeze_path: str | Path = SCRATCH_FREEZE_PATH,
) -> VerifiedSupervisoryGapS4:
    """Recompute the one-factor candidate and compare every frozen identity."""

    checked_path, raw = _read_unique_regular(freeze_path)
    observed_sha = _sha256_bytes(raw)
    if observed_sha != SCRATCH_FREEZE_SHA256:
        raise SupervisoryGapS4Error("scratch freeze raw identity changed")
    freeze = _strict_json(raw)
    candidate = freeze.get("candidate")
    reference = freeze.get("reference")
    incumbent = freeze.get("scratch_incumbent")
    screen = freeze.get("scratch_screen")
    if (
        freeze.get("schema_version") != 1
        or freeze.get("freeze_id")
        != "parcel-v9-supervisory-gap-s4-scratch-candidate-freeze-v1"
        or freeze.get("candidate_source_contract_sha256") != SOURCE_CONTRACT_SHA256
        or freeze.get("frozen_before_materialization") is not True
        or freeze.get("experimental") is not True
        or freeze.get("deployment_enabled") is not False
        or freeze.get("development_execution_authorized") is not False
        or freeze.get("holdout_execution_authorized") is not False
        or not isinstance(candidate, dict)
        or candidate.get("package_sha256") != CANDIDATE_PACKAGE_SHA256
        or candidate.get("manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or not isinstance(reference, dict)
        or reference.get("package_sha256") != REFERENCE_PACKAGE_SHA256
        or reference.get("manifest_sha256") != REFERENCE_MANIFEST_SHA256
        or not isinstance(incumbent, dict)
        or incumbent.get("package_sha256") != S2_PACKAGE_SHA256
        or incumbent.get("manifest_sha256") != S2_MANIFEST_SHA256
        or incumbent.get("report_sha256") != S2_REPORT_SHA256
        or incumbent.get("analysis_sha256") != S2_ANALYSIS_SHA256
        or incumbent.get("training_gate_sha256") != S2_TRAINING_GATE_SHA256
        or not isinstance(screen, dict)
        or screen.get("candidate_package_sha256") != CANDIDATE_PACKAGE_SHA256
        or screen.get("gate_id")
        != "parcel-v9-supervisory-gap-s4-training-screen10-gate-v1"
        or screen.get("training_only") is not True
        or screen.get("accepted_for_next_training_stage_only_if_all_conditions_pass")
        is not True
        or screen.get("screening_can_never_authorize_development_holdout_or_deployment")
        is not True
        or screen.get("screen_world_ids") != list(range(5000, 5010))
    ):
        raise SupervisoryGapS4Error("scratch freeze semantic contract is invalid")

    plan = plan_v9_candidate_bundle(
        experiment_root=experiment_root,
        expected_reference_package_sha256=REFERENCE_PACKAGE_SHA256,
        expected_reference_manifest_sha256=REFERENCE_MANIFEST_SHA256,
    )
    if (
        plan.package_sha256 != CANDIDATE_PACKAGE_SHA256
        or plan.manifest_sha256 != CANDIDATE_MANIFEST_SHA256
        or plan.source_contract.contract_sha256 != SOURCE_CONTRACT_SHA256
        or plan.reference.package_sha256 != REFERENCE_PACKAGE_SHA256
        or plan.reference.manifest_sha256 != REFERENCE_MANIFEST_SHA256
        or plan.delta.get("one_factor_tracker_subsystem_delta") is not True
        or plan.delta.get("all_other_file_bytes_identical_to_reference") is not True
        or plan.delta.get("all_ray_safety_shield_changed") is not False
        or plan.delta.get("adapter_or_evaluator_source_changed") is not False
        or plan.delta.get("deployment_enabled") is not False
    ):
        raise SupervisoryGapS4Error(
            "scratch candidate derivation differs from its freeze"
        )
    return VerifiedSupervisoryGapS4(
        plan=plan,
        freeze_path=checked_path,
        freeze_sha256=observed_sha,
        freeze=freeze,
    )


def prepare_supervisory_gap_s4_bundle(
    *,
    destination_root: str | Path,
) -> V9CandidateBundle:
    """Materialize the exact challenger only after its freeze re-verifies."""

    verified = verify_supervisory_gap_s4()
    bundle = prepare_v9_candidate_bundle(
        expected_candidate_package_sha256=CANDIDATE_PACKAGE_SHA256,
        expected_candidate_manifest_sha256=CANDIDATE_MANIFEST_SHA256,
        experiment_root=EXPERIMENT_ROOT,
        reference_root=verified.plan.reference.root,
        expected_reference_package_sha256=REFERENCE_PACKAGE_SHA256,
        expected_reference_manifest_sha256=REFERENCE_MANIFEST_SHA256,
        destination_root=destination_root,
    )
    if bundle.delta != verified.plan.delta:
        raise SupervisoryGapS4Error(
            "materialized scratch bundle differs from the frozen plan"
        )
    return bundle


__all__ = [
    "CANDIDATE_MANIFEST_SHA256",
    "CANDIDATE_PACKAGE_SHA256",
    "EXPERIMENT_ROOT",
    "REFERENCE_MANIFEST_SHA256",
    "REFERENCE_PACKAGE_SHA256",
    "S2_ANALYSIS_SHA256",
    "S2_MANIFEST_SHA256",
    "S2_PACKAGE_SHA256",
    "S2_REPORT_SHA256",
    "S2_TRAINING_GATE_SHA256",
    "SCRATCH_FREEZE_PATH",
    "SCRATCH_FREEZE_SHA256",
    "SOURCE_CONTRACT_SHA256",
    "SupervisoryGapS4Error",
    "VerifiedSupervisoryGapS4",
    "prepare_supervisory_gap_s4_bundle",
    "verify_supervisory_gap_s4",
]
