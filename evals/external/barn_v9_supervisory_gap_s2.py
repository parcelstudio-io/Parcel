"""Verify and materialize the frozen V9 supervisory-gap S2 challenger.

S2 is a deployment-disabled, training-only successor to S1.  The exact
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
    / "supervisory_gap_s2"
)
SCRATCH_FREEZE_PATH = EXPERIMENT_ROOT / "SCRATCH_FREEZE.json"

SCRATCH_FREEZE_SHA256 = "9afdd17eeaa880a108a73545a87fe5c60527cd71157333233d8418112ac212a4"
SOURCE_CONTRACT_SHA256 = "eb74d5f10108c13bba3add06b0c0e2bf8511e52327b34d45cc73854cf17637eb"
CANDIDATE_PACKAGE_SHA256 = "68e3e66638aea3549bb26618c6b29e02a8e2a309726dddc55c4ef53ad5a0159c"
CANDIDATE_MANIFEST_SHA256 = "04867ea70a7c4f7f0d9f6383815e2d592df635eafb2d8833e193f70d4de4dad7"
REFERENCE_PACKAGE_SHA256 = "189ac31f0f6a461da9e10fad2ac21b2bc3a485a4d5245c517b1492b2a16eb7d9"
REFERENCE_MANIFEST_SHA256 = "d3bca126041d69afb5553ac29656a0152242c00f29a7b987803e9dc536914115"

S1_PACKAGE_SHA256 = "841597cdb34920506f1c41fd1989faeea04416e616548361868a9f1d3bfd0172"
S1_MANIFEST_SHA256 = "465842ec8f61886626f4f3e5e6b77fcb321fa18832e77d07e5fabf4e83500e74"
S1_REPORT_SHA256 = "c70e2a8d42c1c6890a1b657e620142b308a36d270b7bafab281a8be8cd8f9e28"
S1_ANALYSIS_SHA256 = "d17e1dcefd7503889007d5570cc05e7221097e341644385746bab517f7b0d4c3"


class SupervisoryGapS2Error(RuntimeError):
    """Raised when the S2 challenger no longer matches its freeze."""


@dataclass(frozen=True, slots=True)
class VerifiedSupervisoryGapS2:
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
                raise SupervisoryGapS2Error(
                    f"scratch freeze contains duplicate field: {key}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> NoReturn:
        raise SupervisoryGapS2Error(
            f"scratch freeze contains non-finite value: {value}"
        )

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SupervisoryGapS2Error("scratch freeze is not strict JSON") from error
    if not isinstance(value, dict):
        raise SupervisoryGapS2Error("scratch freeze must contain an object")
    return value


def _read_unique_regular(path: str | Path) -> tuple[Path, bytes]:
    requested = _lexical_absolute(path)
    for component in (requested, *requested.parents):
        if os.path.lexists(component) and stat.S_ISLNK(os.lstat(component).st_mode):
            raise SupervisoryGapS2Error(
                f"scratch freeze path contains a symbolic link: {component}"
            )
    try:
        metadata = os.lstat(requested)
    except FileNotFoundError:
        raise SupervisoryGapS2Error(f"scratch freeze is missing: {requested}") from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise SupervisoryGapS2Error(
            "scratch freeze must be a uniquely linked regular file"
        )
    return requested, requested.read_bytes()


def verify_supervisory_gap_s2(
    *,
    experiment_root: str | Path = EXPERIMENT_ROOT,
    freeze_path: str | Path = SCRATCH_FREEZE_PATH,
) -> VerifiedSupervisoryGapS2:
    """Recompute the one-factor candidate and compare every frozen identity."""

    checked_path, raw = _read_unique_regular(freeze_path)
    observed_sha = _sha256_bytes(raw)
    if observed_sha != SCRATCH_FREEZE_SHA256:
        raise SupervisoryGapS2Error("scratch freeze raw identity changed")
    freeze = _strict_json(raw)
    candidate = freeze.get("candidate")
    reference = freeze.get("reference")
    incumbent = freeze.get("scratch_incumbent")
    screen = freeze.get("scratch_screen")
    if (
        freeze.get("schema_version") != 1
        or freeze.get("freeze_id")
        != "parcel-v9-supervisory-gap-s2-scratch-candidate-freeze-v1"
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
        or incumbent.get("package_sha256") != S1_PACKAGE_SHA256
        or incumbent.get("manifest_sha256") != S1_MANIFEST_SHA256
        or incumbent.get("report_sha256") != S1_REPORT_SHA256
        or incumbent.get("analysis_sha256") != S1_ANALYSIS_SHA256
        or not isinstance(screen, dict)
        or screen.get("training_only") is not True
        or screen.get("accepted_for_next_training_stage_only_if_all_conditions_pass")
        is not True
        or screen.get("screening_can_never_authorize_development_holdout_or_deployment")
        is not True
        or screen.get("screen_world_ids") != list(range(5000, 5010))
    ):
        raise SupervisoryGapS2Error("scratch freeze semantic contract is invalid")

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
        raise SupervisoryGapS2Error(
            "scratch candidate derivation differs from its freeze"
        )
    return VerifiedSupervisoryGapS2(
        plan=plan,
        freeze_path=checked_path,
        freeze_sha256=observed_sha,
        freeze=freeze,
    )


def prepare_supervisory_gap_s2_bundle(
    *,
    destination_root: str | Path,
) -> V9CandidateBundle:
    """Materialize the exact challenger only after its freeze re-verifies."""

    verified = verify_supervisory_gap_s2()
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
        raise SupervisoryGapS2Error(
            "materialized scratch bundle differs from the frozen plan"
        )
    return bundle


__all__ = [
    "CANDIDATE_MANIFEST_SHA256",
    "CANDIDATE_PACKAGE_SHA256",
    "EXPERIMENT_ROOT",
    "REFERENCE_MANIFEST_SHA256",
    "REFERENCE_PACKAGE_SHA256",
    "S1_ANALYSIS_SHA256",
    "S1_MANIFEST_SHA256",
    "S1_PACKAGE_SHA256",
    "S1_REPORT_SHA256",
    "SCRATCH_FREEZE_PATH",
    "SCRATCH_FREEZE_SHA256",
    "SOURCE_CONTRACT_SHA256",
    "SupervisoryGapS2Error",
    "VerifiedSupervisoryGapS2",
    "prepare_supervisory_gap_s2_bundle",
    "verify_supervisory_gap_s2",
]
