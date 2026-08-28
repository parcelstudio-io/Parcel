"""Deterministic preregistered H2b completion holdout.

Synthetic scorer truth is kept outside every product-contract DTO.  This is a
fast architecture experiment, not a sensor or locomotion validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import time
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parcel_robot.navigation.independent_completion import (
    AuthenticatedPlaceIdentityEvidenceV1,
    AuthenticatedPoseEpochVerificationV1,
    AuthenticatedTerminalGeometryEvidenceV1,
    CompletionDispositionV1,
    IndependentCompletionConfigV1,
    IndependentCompletionDecisionV1,
    IndependentCompletionGoalV1,
    IndependentCompletionLatchV1,
    IndependentCompletionObservationV1,
    PlaceIdentityEvidenceV1,
    PoseEpochVerificationV1,
    TerminalGeometryEvidenceV1,
    TrustedPlaceIdentityVerifierV1,
    TrustedPoseEpochVerifierV1,
    TrustedTerminalGeometryVerifierV1,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MATRIX_SCHEMA = "parcel.independent-completion-h2b.holdout.v1"
PAYLOAD_SCHEMA = "parcel.independent-completion-h2b.results.v1"
REPORT_SCHEMA = "parcel.independent-completion-h2b.report.v1"
FAMILIES = ("nominal", "alias_recovery", "outside_boundary", "sensor_dropout", "lineage_attack")
ARMS = ("map_only", "h2_identity_range", "h2b_independent_chain")
SCENES = tuple(range(8))
SENSOR_PROFILES = tuple(range(5))
TARGETS = tuple(range(3))
GOAL_RADIUS_M = 0.50
BASE_TIME_MS = 10_000
NS_PER_MS = 1_000_000
PRIOR_MAX_SEED = 2_000_000_000
SCORER_ONLY_FIELDS = frozenset(
    {"truth_distance_m", "truth_positive", "false_claim", "case_family", "attack_type"}
)
POLICY_DTOS = (
    IndependentCompletionGoalV1,
    IndependentCompletionObservationV1,
    AuthenticatedPlaceIdentityEvidenceV1,
    AuthenticatedPoseEpochVerificationV1,
    AuthenticatedTerminalGeometryEvidenceV1,
    PlaceIdentityEvidenceV1,
    PoseEpochVerificationV1,
    TerminalGeometryEvidenceV1,
    IndependentCompletionDecisionV1,
)
SOURCE_PATHS = (
    "src/parcel_robot/navigation/independent_completion.py",
    "src/parcel_robot/navigation/independent_completion_evidence.py",
    "tests/test_independent_completion_h2b.py",
    "research/20260826/independent-completion-h2b/DESIGN.md",
    "research/20260826/independent-completion-h2b/experiment.py",
)

IDENTITY_VERIFIER = TrustedPlaceIdentityVerifierV1(
    provider_id="synthetic-provider:h2b-place-identity-v1",
    verifier_id="synthetic-verifier:h2b-place-identity-v1",
    key=b"h2b-holdout-identity-channel-key-v1!",
)
POSE_EPOCH_VERIFIER = TrustedPoseEpochVerifierV1(
    provider_id="synthetic-provider:h2b-pose-epoch-v1",
    verifier_id="synthetic-verifier:h2b-pose-epoch-v1",
    key=b"h2b-holdout-pose-epoch-channel-key-v1!",
)
GEOMETRY_VERIFIER = TrustedTerminalGeometryVerifierV1(
    provider_id="synthetic-provider:h2b-terminal-geometry-v1",
    verifier_id="synthetic-verifier:h2b-terminal-geometry-v1",
    key=b"h2b-holdout-terminal-geometry-key-v1!",
)

SENSOR_PARAMETERS = {
    0: {"identity_bias": 0.000, "residual_bias": 0.000, "geometry_bias": 0.000, "sigma_m": 0.012},
    1: {"identity_bias": -0.010, "residual_bias": 0.010, "geometry_bias": 0.005, "sigma_m": 0.014},
    2: {"identity_bias": 0.000, "residual_bias": -0.005, "geometry_bias": -0.004, "sigma_m": 0.016},
    3: {"identity_bias": -0.020, "residual_bias": 0.015, "geometry_bias": 0.008, "sigma_m": 0.018},
    4: {"identity_bias": 0.010, "residual_bias": 0.020, "geometry_bias": -0.006, "sigma_m": 0.020},
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value: Any) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _u01(key: str) -> float:
    raw = hashlib.sha256(key.encode()).digest()[:8]
    return (int.from_bytes(raw, "big") + 0.5) / float(1 << 64)


def _normal(key: str) -> float:
    u1 = max(_u01(key + "|u1"), 1e-15)
    u2 = _u01(key + "|u2")
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _ns(milliseconds: int) -> int:
    return milliseconds * NS_PER_MS


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    family: str
    scene: int
    sensor_profile: int
    target: int
    local_index: int
    seed: int
    subtype: str
    truth_distance_m: float
    recovery_truth_distance_m: float | None = None
    recovery_frame_loss: bool = False

    def matrix_row(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "family": self.family,
            "scene": self.scene,
            "sensor_profile": self.sensor_profile,
            "target": self.target,
            "local_index": self.local_index,
            "seed": self.seed,
            "subtype": self.subtype,
            "truth_distance_m": self.truth_distance_m,
            "recovery_truth_distance_m": self.recovery_truth_distance_m,
            "recovery_frame_loss": self.recovery_frame_loss,
        }


def _subtype(family: str, local_index: int) -> str:
    group = local_index % 3
    if family == "alias_recovery":
        return ("identity_attack", "residual_attack", "geometry_attack")[group]
    if family == "sensor_dropout":
        return ("identity_missing", "epoch_missing", "geometry_missing")[group]
    if family == "lineage_attack":
        return ("identity_replay", "wrong_parent_epoch", "cross_epoch_geometry")[group]
    return "none"


def build_matrix() -> list[Case]:
    cases: list[Case] = []
    for family in FAMILIES:
        local_index = 0
        for scene in SCENES:
            for sensor_profile in SENSOR_PROFILES:
                for target in TARGETS:
                    case_id = f"{MATRIX_SCHEMA}|{family}|S{scene}|P{sensor_profile}|T{target}"
                    seed = (1 << 40) + int.from_bytes(
                        hashlib.sha256(case_id.encode()).digest()[:8], "big"
                    )
                    if family in {"nominal", "sensor_dropout"}:
                        truth_distance = 0.20 + 0.17 * _u01(case_id + "|truth")
                    elif family == "alias_recovery":
                        truth_distance = 4.50 + 2.00 * _u01(case_id + "|truth")
                    elif family == "outside_boundary":
                        truth_distance = 0.501 + 0.079 * _u01(case_id + "|truth")
                    else:
                        truth_distance = 3.50 + 2.00 * _u01(case_id + "|truth")
                    recovery = None
                    recovery_loss = False
                    if family == "alias_recovery":
                        recovery = 0.20 + 0.17 * _u01(case_id + "|recovery-truth")
                        recovery_loss = _u01(case_id + "|recovery-frame-loss") < 0.05
                    cases.append(
                        Case(
                            case_id=case_id,
                            family=family,
                            scene=scene,
                            sensor_profile=sensor_profile,
                            target=target,
                            local_index=local_index,
                            seed=seed,
                            subtype=_subtype(family, local_index),
                            truth_distance_m=round(truth_distance, 6),
                            recovery_truth_distance_m=(
                                None if recovery is None else round(recovery, 6)
                            ),
                            recovery_frame_loss=recovery_loss,
                        )
                    )
                    local_index += 1
    if len(cases) != 600 or len({case.case_id for case in cases}) != 600:
        raise AssertionError("the frozen holdout must have 600 unique cases")
    if any(case.seed <= PRIOR_MAX_SEED for case in cases):
        raise AssertionError("H2-sized seed leaked into H2b")
    return cases


def _identity_scores(case: Case, phase: str, *, discriminative: bool = True) -> tuple[float, float]:
    profile = SENSOR_PARAMETERS[case.sensor_profile]
    if discriminative:
        target = 0.94 + profile["identity_bias"] + 0.025 * _normal(case.case_id + phase + "|id")
        runner = 0.30 + 0.035 * _normal(case.case_id + phase + "|runner")
    else:
        target = 0.72 + 0.020 * _normal(case.case_id + phase + "|id")
        runner = 0.94 + 0.020 * _normal(case.case_id + phase + "|runner")
    return round(_clamp(target, 0.0, 1.0), 6), round(_clamp(runner, 0.0, 1.0), 6)


def _residuals(case: Case, phase: str, *, consistent: bool = True) -> tuple[float, float]:
    profile = SENSOR_PARAMETERS[case.sensor_profile]
    if consistent:
        scan = (
            0.040 + profile["residual_bias"] + abs(0.010 * _normal(case.case_id + phase + "|scan"))
        )
        landmark = (
            0.050
            + profile["residual_bias"]
            + abs(0.012 * _normal(case.case_id + phase + "|landmark"))
        )
    else:
        scan = 0.180 + abs(0.020 * _normal(case.case_id + phase + "|scan"))
        landmark = 0.200 + abs(0.020 * _normal(case.case_id + phase + "|landmark"))
    return round(scan, 6), round(landmark, 6)


def _geometry_measurement(case: Case, phase: str, truth_distance_m: float) -> tuple[float, float]:
    profile = SENSOR_PARAMETERS[case.sensor_profile]
    sigma = profile["sigma_m"]
    estimate = (
        truth_distance_m
        + profile["geometry_bias"]
        + sigma * _normal(case.case_id + phase + "|geometry")
    )
    return round(max(0.0, estimate), 6), round(sigma * sigma, 9)


def _identity(
    case: Case,
    phase: str,
    *,
    observation_id: str,
    place_id: str,
    epoch: int,
    captured_ms: int,
    discriminative: bool = True,
) -> PlaceIdentityEvidenceV1:
    score, runner = _identity_scores(case, phase, discriminative=discriminative)
    return PlaceIdentityEvidenceV1(
        observation_id=observation_id,
        goal_id=f"goal:{case.case_id}",
        goal_nonce=f"nonce:{case.case_id}",
        place_id=place_id,
        pose_epoch=epoch,
        captured_at_monotonic_ns=_ns(captured_ms),
        received_at_monotonic_ns=_ns(captured_ms + 1),
        target_score=score,
        runner_up_score=runner,
    )


def _verification(
    case: Case,
    phase: str,
    *,
    anchor: PlaceIdentityEvidenceV1,
    epoch: int,
    reset_ms: int,
    consistent: bool = True,
) -> PoseEpochVerificationV1:
    scan, landmark = _residuals(case, phase, consistent=consistent)
    return PoseEpochVerificationV1(
        verification_id=f"verify:{case.local_index}:{phase}:{epoch}",
        goal_id=anchor.goal_id,
        goal_nonce=anchor.goal_nonce,
        reset_id=f"reset:{case.local_index}:{phase}:{epoch}",
        anchor_observation_id=anchor.observation_id,
        parent_pose_epoch=anchor.pose_epoch,
        pose_epoch=epoch,
        reset_at_monotonic_ns=_ns(reset_ms),
        verified_at_monotonic_ns=_ns(reset_ms + 10),
        received_at_monotonic_ns=_ns(reset_ms + 11),
        scan_residual_m=scan,
        landmark_residual_m=landmark,
    )


def _geometry(
    case: Case,
    phase: str,
    *,
    identity: PlaceIdentityEvidenceV1,
    captured_ms: int,
    truth_distance_m: float,
    identity_observation_id: str | None = None,
    epoch: int | None = None,
) -> TerminalGeometryEvidenceV1:
    estimate, variance = _geometry_measurement(case, phase, truth_distance_m)
    return TerminalGeometryEvidenceV1(
        evidence_id=f"geometry:{case.local_index}:{phase}:{captured_ms}",
        goal_id=identity.goal_id,
        goal_nonce=identity.goal_nonce,
        target_place_id=identity.place_id,
        identity_observation_id=identity_observation_id or identity.observation_id,
        pose_epoch=identity.pose_epoch if epoch is None else epoch,
        captured_at_monotonic_ns=_ns(captured_ms),
        received_at_monotonic_ns=_ns(captured_ms + 1),
        relative_x_m=estimate,
        relative_y_m=0.0,
        covariance_xx_m2=variance,
        covariance_xy_m2=0.0,
        covariance_yy_m2=variance,
    )


def _step(
    latch: IndependentCompletionLatchV1,
    *,
    now_ms: int,
    epoch: int,
    candidate: bool,
    discontinuity: float | None = None,
    identity: PlaceIdentityEvidenceV1 | None = None,
    verification: PoseEpochVerificationV1 | None = None,
    geometry: TerminalGeometryEvidenceV1 | None = None,
) -> IndependentCompletionDecisionV1:
    return latch.step(
        IndependentCompletionObservationV1(
            now_monotonic_ns=_ns(now_ms),
            current_pose_epoch=epoch,
            map_completion_candidate=candidate,
            map_healthy=True,
            discontinuity_score=discontinuity,
            place_identity=(None if identity is None else IDENTITY_VERIFIER.authenticate(identity)),
            pose_epoch_verification=(
                None if verification is None else POSE_EPOCH_VERIFIER.authenticate(verification)
            ),
            terminal_geometry=(
                None if geometry is None else GEOMETRY_VERIFIER.authenticate(geometry)
            ),
        )
    )


def _valid_chain(
    latch: IndependentCompletionLatchV1,
    case: Case,
    *,
    phase: str,
    parent_epoch: int,
    base_ms: int,
    truth_distance_m: float,
    omit: str = "",
) -> tuple[list[IndependentCompletionDecisionV1], int]:
    decisions: list[IndependentCompletionDecisionV1] = []
    if omit == "identity_missing":
        decisions.append(
            _step(
                latch,
                now_ms=base_ms + 2,
                epoch=parent_epoch,
                candidate=True,
            )
        )
        return decisions, parent_epoch
    anchor = _identity(
        case,
        phase + "|anchor",
        observation_id=f"identity:{case.local_index}:{phase}:anchor",
        place_id=f"anchor:scene-{case.scene}",
        epoch=parent_epoch,
        captured_ms=base_ms,
    )
    decisions.append(
        _step(latch, now_ms=base_ms + 2, epoch=parent_epoch, candidate=True, identity=anchor)
    )
    if omit == "epoch_missing":
        return decisions, parent_epoch
    new_epoch = parent_epoch + 1
    verification = _verification(
        case,
        phase + "|verify",
        anchor=anchor,
        epoch=new_epoch,
        reset_ms=base_ms + 20,
    )
    decisions.append(
        _step(
            latch,
            now_ms=base_ms + 32,
            epoch=new_epoch,
            candidate=False,
            verification=verification,
        )
    )
    target = _identity(
        case,
        phase + "|target",
        observation_id=f"identity:{case.local_index}:{phase}:target",
        place_id=f"target:{case.target}",
        epoch=new_epoch,
        captured_ms=base_ms + 50,
    )
    decisions.append(
        _step(
            latch,
            now_ms=base_ms + 52,
            epoch=new_epoch,
            candidate=False,
            identity=target,
        )
    )
    if omit == "geometry_missing":
        return decisions, new_epoch
    geometry = _geometry(
        case,
        phase + "|geometry",
        identity=target,
        captured_ms=base_ms + 70,
        truth_distance_m=truth_distance_m,
    )
    decisions.append(
        _step(
            latch,
            now_ms=base_ms + 72,
            epoch=new_epoch,
            candidate=True,
            geometry=geometry,
        )
    )
    return decisions, new_epoch


def _initial_alias_attack(
    latch: IndependentCompletionLatchV1,
    case: Case,
    baseline_epoch: int,
) -> tuple[list[IndependentCompletionDecisionV1], int]:
    decisions: list[IndependentCompletionDecisionV1] = []
    ambiguous = case.subtype == "identity_attack"
    anchor = _identity(
        case,
        "alias-initial|anchor",
        observation_id=f"identity:{case.local_index}:alias-initial:anchor",
        place_id=f"anchor:scene-{case.scene}",
        epoch=baseline_epoch,
        captured_ms=BASE_TIME_MS - 2,
        discriminative=not ambiguous,
    )
    decisions.append(
        _step(
            latch,
            now_ms=BASE_TIME_MS,
            epoch=baseline_epoch,
            candidate=True,
            discontinuity=0.95,
            identity=anchor,
        )
    )
    if ambiguous:
        return decisions, baseline_epoch
    new_epoch = baseline_epoch + 1
    verification = _verification(
        case,
        "alias-initial|verify",
        anchor=anchor,
        epoch=new_epoch,
        reset_ms=BASE_TIME_MS + 20,
        consistent=case.subtype != "residual_attack",
    )
    decisions.append(
        _step(
            latch,
            now_ms=BASE_TIME_MS + 32,
            epoch=new_epoch,
            candidate=False,
            verification=verification,
        )
    )
    if case.subtype == "residual_attack":
        return decisions, new_epoch
    target = _identity(
        case,
        "alias-initial|target",
        observation_id=f"identity:{case.local_index}:alias-initial:target",
        place_id=f"target:{case.target}",
        epoch=new_epoch,
        captured_ms=BASE_TIME_MS + 50,
    )
    decisions.append(
        _step(
            latch,
            now_ms=BASE_TIME_MS + 52,
            epoch=new_epoch,
            candidate=False,
            identity=target,
        )
    )
    far_geometry = _geometry(
        case,
        "alias-initial|geometry",
        identity=target,
        captured_ms=BASE_TIME_MS + 70,
        truth_distance_m=case.truth_distance_m,
    )
    decisions.append(
        _step(
            latch,
            now_ms=BASE_TIME_MS + 72,
            epoch=new_epoch,
            candidate=True,
            geometry=far_geometry,
        )
    )
    return decisions, new_epoch


def _lineage_attack(
    latch: IndependentCompletionLatchV1,
    case: Case,
    baseline_epoch: int,
) -> tuple[list[IndependentCompletionDecisionV1], int]:
    decisions: list[IndependentCompletionDecisionV1] = []
    if case.subtype == "identity_replay":
        replay = _identity(
            case,
            "lineage|replay",
            observation_id=f"identity:{case.local_index}:replay",
            place_id=f"anchor:scene-{case.scene}",
            epoch=baseline_epoch,
            captured_ms=BASE_TIME_MS - 30,
        )
        decisions.append(
            _step(
                latch,
                now_ms=BASE_TIME_MS - 20,
                epoch=baseline_epoch,
                candidate=False,
                identity=replay,
            )
        )
        decisions.append(
            _step(
                latch,
                now_ms=BASE_TIME_MS,
                epoch=baseline_epoch,
                candidate=True,
                discontinuity=0.95,
            )
        )
        verification = _verification(
            case,
            "lineage|replay-verify",
            anchor=replay,
            epoch=baseline_epoch + 1,
            reset_ms=BASE_TIME_MS + 20,
        )
        decisions.append(
            _step(
                latch,
                now_ms=BASE_TIME_MS + 32,
                epoch=baseline_epoch + 1,
                candidate=True,
                verification=verification,
            )
        )
        return decisions, baseline_epoch + 1

    decisions.append(
        _step(
            latch,
            now_ms=BASE_TIME_MS,
            epoch=baseline_epoch,
            candidate=True,
            discontinuity=0.95,
        )
    )
    if case.subtype == "wrong_parent_epoch":
        anchor = _identity(
            case,
            "lineage|wrong-parent",
            observation_id=f"identity:{case.local_index}:wrong-parent",
            place_id=f"anchor:scene-{case.scene}",
            epoch=baseline_epoch + 1,
            captured_ms=BASE_TIME_MS + 20,
        )
        decisions.append(
            _step(
                latch,
                now_ms=BASE_TIME_MS + 22,
                epoch=baseline_epoch + 1,
                candidate=True,
                identity=anchor,
            )
        )
        verification = _verification(
            case,
            "lineage|wrong-parent-verify",
            anchor=anchor,
            epoch=baseline_epoch + 2,
            reset_ms=BASE_TIME_MS + 30,
        )
        decisions.append(
            _step(
                latch,
                now_ms=BASE_TIME_MS + 42,
                epoch=baseline_epoch + 2,
                candidate=True,
                verification=verification,
            )
        )
        return decisions, baseline_epoch + 2

    chain, epoch = _valid_chain(
        latch,
        case,
        phase="lineage-cross",
        parent_epoch=baseline_epoch,
        base_ms=BASE_TIME_MS + 10,
        truth_distance_m=case.truth_distance_m,
        omit="geometry_missing",
    )
    decisions.extend(chain)
    target = _identity(
        case,
        "lineage-cross|target-copy",
        observation_id=f"identity:{case.local_index}:lineage-cross:target",
        place_id=f"target:{case.target}",
        epoch=epoch,
        captured_ms=BASE_TIME_MS + 60,
    )
    geometry = _geometry(
        case,
        "lineage-cross|geometry",
        identity=target,
        identity_observation_id="identity:unrelated-epoch",
        captured_ms=BASE_TIME_MS + 90,
        truth_distance_m=case.truth_distance_m,
    )
    decisions.append(
        _step(
            latch,
            now_ms=BASE_TIME_MS + 92,
            epoch=epoch,
            candidate=True,
            geometry=geometry,
        )
    )
    return decisions, epoch


def _h2b_arm(case: Case) -> dict[str, object]:
    baseline_epoch = 1000 + case.local_index * 4
    goal = IndependentCompletionGoalV1(
        goal_id=f"goal:{case.case_id}",
        goal_nonce=f"nonce:{case.case_id}",
        target_place_id=f"target:{case.target}",
        baseline_pose_epoch=baseline_epoch,
        success_radius_m=GOAL_RADIUS_M,
        started_at_monotonic_ns=_ns(BASE_TIME_MS - 100),
    )
    latch = IndependentCompletionLatchV1(
        goal,
        IndependentCompletionConfigV1(enabled=True),
        identity_verifier=IDENTITY_VERIFIER,
        pose_epoch_verifier=POSE_EPOCH_VERIFIER,
        geometry_verifier=GEOMETRY_VERIFIER,
    )
    decisions: list[IndependentCompletionDecisionV1] = []
    initial_count = 0
    current_epoch = baseline_epoch

    if case.family == "alias_recovery":
        attack, current_epoch = _initial_alias_attack(latch, case, baseline_epoch)
        decisions.extend(attack)
        initial_count = len(decisions)
        decisions.append(
            _step(
                latch,
                now_ms=BASE_TIME_MS + 200,
                epoch=current_epoch,
                candidate=True,
                discontinuity=0.95,
            )
        )
        if not case.recovery_frame_loss:
            assert case.recovery_truth_distance_m is not None
            recovery, current_epoch = _valid_chain(
                latch,
                case,
                phase="alias-recovery",
                parent_epoch=current_epoch,
                base_ms=BASE_TIME_MS + 300,
                truth_distance_m=case.recovery_truth_distance_m,
            )
            decisions.extend(recovery)
    elif case.family == "lineage_attack":
        attack, current_epoch = _lineage_attack(latch, case, baseline_epoch)
        decisions.extend(attack)
        initial_count = len(decisions)
    else:
        omit = case.subtype if case.family == "sensor_dropout" else ""
        chain, current_epoch = _valid_chain(
            latch,
            case,
            phase=case.family,
            parent_epoch=baseline_epoch,
            base_ms=BASE_TIME_MS,
            truth_distance_m=case.truth_distance_m,
            omit=omit,
        )
        decisions.extend(chain)

    authorized = [
        index
        for index, decision in enumerate(decisions)
        if decision.disposition is CompletionDispositionV1.AUTHORIZE_TERMINAL_CLAIM
    ]
    initial_claim = any(index < initial_count for index in authorized)
    needs_timeout = not authorized and not any(
        decision.disposition is CompletionDispositionV1.LOCALIZATION_UNCERTAIN
        for decision in decisions
    )
    if needs_timeout:
        decisions.append(
            _step(
                latch,
                # Some chains first assert the candidate at t0+2 ms. Sample
                # beyond, rather than just before, the frozen four-second
                # deadline. Pre-canonical pilot artifacts retain the timing
                # mistakes and are excluded from the fixed-source replay pair.
                now_ms=BASE_TIME_MS + 4_100,
                epoch=current_epoch,
                candidate=True,
            )
        )

    terminal = decisions[-1]
    claimed = any(
        decision.disposition is CompletionDispositionV1.AUTHORIZE_TERMINAL_CLAIM
        for decision in decisions
    )
    truth_distance = (
        case.recovery_truth_distance_m
        if case.family == "alias_recovery" and claimed and not initial_claim
        else case.truth_distance_m
    )
    truth_positive = bool(truth_distance is not None and truth_distance <= GOAL_RADIUS_M)
    false_claim = bool(initial_claim or (claimed and not truth_positive))
    true_claim = bool(claimed and truth_positive and not initial_claim)
    recovered = bool(case.family == "alias_recovery" and true_claim)
    if claimed:
        outcome = "arrived" if true_claim else "false_arrival"
    elif terminal.disposition is CompletionDispositionV1.LOCALIZATION_UNCERTAIN:
        outcome = "localization_uncertain"
    else:
        outcome = "silent"
    claim_index = authorized[-1] if authorized else None
    latency_s = None
    if claim_index is not None:
        # The valid chain's last step is always 72 ms after its base. Alias
        # recovery uses base t0+300 ms; the initial candidate is t0.
        latency_s = 0.372 if case.family == "alias_recovery" else 0.072
    return {
        "arm": "h2b_independent_chain",
        "initial_claim": initial_claim,
        "terminal_claim": claimed,
        "true_claim": true_claim,
        "false_claim": false_claim,
        "recovered": recovered,
        "outcome": outcome,
        "latency_s": latency_s,
        "final_reason": terminal.reason.value,
        "initial_attack_blocked": bool(case.family == "alias_recovery" and not initial_claim),
        "authorizes_motion": any(decision.authorizes_motion for decision in decisions),
        "decision_count": len(decisions),
    }


def _control_arm(case: Case, arm: str) -> dict[str, object]:
    if arm == "map_only":
        initial_claim = case.family in {"alias_recovery", "lineage_attack"}
        claimed = True
    else:
        score, runner = _identity_scores(case, "|h2-control")
        identity_ok = score >= 0.65 and score - runner >= 0.12
        broad_range = 1.55 + 0.12 * _normal(case.case_id + "|h2-range")
        range_ok = 0.90 <= broad_range <= 2.30
        if case.family == "alias_recovery" and case.subtype == "identity_attack":
            score, runner = _identity_scores(case, "|h2-control-alias", discriminative=False)
            identity_ok = score >= 0.65 and score - runner >= 0.12
        if case.family == "sensor_dropout" and case.subtype == "identity_missing":
            identity_ok = False
        initial_claim = bool(
            case.family in {"alias_recovery", "lineage_attack"} and identity_ok and range_ok
        )
        claimed = bool(identity_ok and range_ok)

    truth_positive = case.truth_distance_m <= GOAL_RADIUS_M
    false_claim = bool(claimed and not truth_positive)
    true_claim = bool(claimed and truth_positive)
    if false_claim:
        outcome = "false_arrival"
    elif true_claim:
        outcome = "arrived"
    else:
        outcome = "localization_uncertain"
    return {
        "arm": arm,
        "initial_claim": initial_claim,
        "terminal_claim": claimed,
        "true_claim": true_claim,
        "false_claim": false_claim,
        "recovered": False,
        "outcome": outcome,
        "latency_s": 0.0 if claimed else None,
        "final_reason": "map_candidate" if arm == "map_only" else "h2_identity_range",
        "initial_attack_blocked": bool(case.family == "alias_recovery" and not initial_claim),
        "authorizes_motion": False,
        "decision_count": 1,
    }


def run_cases(cases: list[Case]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for case in cases:
        for arm in ARMS:
            arm_row = _h2b_arm(case) if arm == "h2b_independent_chain" else _control_arm(case, arm)
            rows.append({**case.matrix_row(), **arm_row})
    return rows


def _nearest_rank(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return round(ordered[index], 6)


def _count(rows: list[dict[str, object]], **matches: object) -> int:
    return sum(all(row.get(key) == value for key, value in matches.items()) for row in rows)


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    by_family_arm: dict[str, dict[str, object]] = {}
    for family in FAMILIES:
        for arm in ARMS:
            selected = [row for row in rows if row["family"] == family and row["arm"] == arm]
            by_family_arm[f"{family}|{arm}"] = {
                "cases": len(selected),
                "true_claims": sum(bool(row["true_claim"]) for row in selected),
                "false_claims": sum(bool(row["false_claim"]) for row in selected),
                "initial_claims": sum(bool(row["initial_claim"]) for row in selected),
                "recovered": sum(bool(row["recovered"]) for row in selected),
                "localization_uncertain": sum(
                    row["outcome"] == "localization_uncertain" for row in selected
                ),
                "silent": sum(row["outcome"] == "silent" for row in selected),
            }
    h2b_alias_latency = [
        float(row["latency_s"])
        for row in rows
        if row["arm"] == "h2b_independent_chain"
        and row["family"] == "alias_recovery"
        and row["recovered"]
        and row["latency_s"] is not None
    ]
    return {
        "by_family_arm": by_family_arm,
        "h2b_alias_recovery_latency_p95_s": _nearest_rank(h2b_alias_latency, 0.95),
        "h2b_motion_authorizations": _count(
            rows, arm="h2b_independent_chain", authorizes_motion=True
        ),
        "h2b_false_claims_total": _count(rows, arm="h2b_independent_chain", false_claim=True),
        "h2b_resolvable_true_claims": sum(
            bool(row["true_claim"])
            for row in rows
            if row["arm"] == "h2b_independent_chain"
            and row["family"] in {"nominal", "alias_recovery"}
        ),
    }


def _source_digests() -> dict[str, str]:
    return {path: _sha256((ROOT / path).read_bytes()) for path in SOURCE_PATHS}


def _field_audit() -> dict[str, object]:
    dto_fields = sorted({field.name for dto in POLICY_DTOS for field in fields(dto)})
    decision_fields = {field.name for field in fields(IndependentCompletionDecisionV1)}
    return {
        "dto_fields": dto_fields,
        "scorer_intersection": sorted(SCORER_ONLY_FIELDS.intersection(dto_fields)),
        "decision_command_intersection": sorted(
            decision_fields.intersection({"velocity", "vx", "vy", "yaw_rate", "command"})
        ),
    }


def _channel_audit() -> dict[str, object]:
    bindings = {
        "place_identity": {
            "provider_id": IDENTITY_VERIFIER.provider_id,
            "verifier_id": IDENTITY_VERIFIER.verifier_id,
        },
        "pose_epoch_verification": {
            "provider_id": POSE_EPOCH_VERIFIER.provider_id,
            "verifier_id": POSE_EPOCH_VERIFIER.verifier_id,
        },
        "terminal_geometry": {
            "provider_id": GEOMETRY_VERIFIER.provider_id,
            "verifier_id": GEOMETRY_VERIFIER.verifier_id,
        },
    }
    provider_ids = {binding["provider_id"] for binding in bindings.values()}
    verifier_ids = {binding["verifier_id"] for binding in bindings.values()}
    return {
        "bindings": bindings,
        "three_distinct_provider_ids": len(provider_ids) == 3,
        "three_distinct_verifier_ids": len(verifier_ids) == 3,
        "scope": "process_local_interface_authenticity_only",
    }


def acceptance_gates(
    cases: list[Case], rows: list[dict[str, object]], summary: dict[str, object]
) -> dict[str, bool]:
    h2b = [row for row in rows if row["arm"] == "h2b_independent_chain"]
    field_audit = _field_audit()
    channel_audit = _channel_audit()
    alias_subtype_blocks = all(
        _count(
            h2b,
            family="alias_recovery",
            subtype=subtype,
            initial_attack_blocked=True,
        )
        == 40
        for subtype in ("identity_attack", "residual_attack", "geometry_attack")
    )
    return {
        "matrix_exact_and_disjoint": (
            len(cases) == 600
            and len({case.case_id for case in cases}) == 600
            and len(rows) == 1800
            and all(case.seed > PRIOR_MAX_SEED for case in cases)
            and all(MATRIX_SCHEMA in case.case_id for case in cases)
        ),
        "negative_controls_bite": (
            _count(rows, arm="map_only", family="alias_recovery", false_claim=True) >= 100
            and _count(rows, arm="map_only", family="outside_boundary", false_claim=True) >= 100
            and _count(rows, arm="map_only", family="lineage_attack", false_claim=True) >= 100
            and _count(rows, arm="h2_identity_range", family="outside_boundary", false_claim=True)
            >= 100
        ),
        "zero_h2b_false_claims": summary["h2b_false_claims_total"] == 0,
        "nominal_recall": (
            _count(h2b, family="nominal", true_claim=True) >= 118
            and _count(h2b, family="nominal", true_claim=True)
            >= _count(rows, arm="map_only", family="nominal", true_claim=True) - 2
        ),
        "alias_recovery": (
            _count(h2b, family="alias_recovery", recovered=True) >= 114
            and summary["h2b_alias_recovery_latency_p95_s"] is not None
            and float(summary["h2b_alias_recovery_latency_p95_s"]) <= 2.50
        ),
        "typed_uncertainty_no_silence": (
            _count(h2b, family="sensor_dropout", outcome="localization_uncertain") == 120
            and _count(h2b, family="lineage_attack", outcome="localization_uncertain") == 120
            and _count(h2b, outcome="silent") == 0
        ),
        "all_alias_layers_block": alias_subtype_blocks,
        "selective_coverage_and_risk": (
            int(summary["h2b_resolvable_true_claims"]) >= 232
            and int(summary["h2b_false_claims_total"]) == 0
        ),
        "field_and_motion_audit": (
            not field_audit["scorer_intersection"]
            and not field_audit["decision_command_intersection"]
            and summary["h2b_motion_authorizations"] == 0
            and channel_audit["three_distinct_provider_ids"]
            and channel_audit["three_distinct_verifier_ids"]
        ),
    }


def build_payload() -> dict[str, object]:
    cases = build_matrix()
    matrix_rows = [case.matrix_row() for case in cases]
    source_digests = _source_digests()
    matrix_digest = _digest(matrix_rows)
    rows = run_cases(cases)
    summary = summarize(rows)
    gates = acceptance_gates(cases, rows, summary)
    h2b_config = IndependentCompletionConfigV1(enabled=True)
    return {
        "schema": PAYLOAD_SCHEMA,
        "matrix_schema": MATRIX_SCHEMA,
        "matrix_digest": matrix_digest,
        "source_digests": source_digests,
        "source_digest": _digest(source_digests),
        "field_audit": _field_audit(),
        "channel_audit": _channel_audit(),
        "config": {
            "goal_radius_m": GOAL_RADIUS_M,
            "h2b": {
                field.name: getattr(h2b_config, field.name)
                for field in fields(IndependentCompletionConfigV1)
            },
            "sensor_parameters": SENSOR_PARAMETERS,
        },
        "matrix": matrix_rows,
        "rows": rows,
        "summary": summary,
        "gates": gates,
        "supported_before_replay_gate": all(gates.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    payload = build_payload()
    payload_digest = _digest(payload)
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "wall_time_s": round(time.perf_counter() - started, 6),
        },
        "payload_digest": payload_digest,
        "payload": payload,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"cases={len(payload['matrix'])} rows={len(payload['rows'])}")
    print(f"payload_digest={payload_digest}")
    print(f"supported_before_replay_gate={payload['supported_before_replay_gate']}")
    failed = [name for name, passed in payload["gates"].items() if not passed]
    print(f"failed_gates={','.join(failed) if failed else 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
