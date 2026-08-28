"""Independent completion authority over the frozen NAV-CORE/NAV-ACCEPT loop.

Research-only.  This module adds counterfactual completion arms and synthetic
sensor adapters around the existing commissioned navigator.  It does not edit
or monkey-patch product safety code, prior research artifacts, or eval ledgers.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import platform
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parcel_robot.backends.base import VelocityCommand
from parcel_robot.perception_source.selection import (
    SOURCE_LEARNED_MAP,
    SemanticSourcePolicy,
    use_learned_map,
    use_semantic_source,
)
from parcel_robot.pose import PoseHealth

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NAV_CORE = ROOT / "research" / "20260824" / "nav-core"
NAV_ACCEPT = ROOT / "research" / "20260824" / "nav-accept"
for dependency in (NAV_CORE, NAV_ACCEPT):
    if str(dependency) not in sys.path:
        sys.path.insert(0, str(dependency))

nav_accept = importlib.import_module("nav_accept")
arms = nav_accept.arms
room = nav_accept.room
stack = importlib.import_module("stack")
world_map = nav_accept.world_map
ArmShipped = nav_accept.ArmShipped

MATRIX_SCHEMA = "parcel.independent-completion.matrix.v1"
PAYLOAD_SCHEMA = "parcel.independent-completion.v1"
REPORT_SCHEMA = "parcel.independent-completion-report.v1"
REPOSITORY_HEAD = "f3ecb5cd9e09058c7bc29ba61b63e18f92a308d8"

CONTROL_DT_S = float(stack.CONTROL_DT_S)
CONTROL_HZ = 1.0 / CONTROL_DT_S
STREAK_TICKS = 5
DISCONTINUITY_THRESHOLD = 0.70
WITNESS_SCORE_MIN = 0.65
WITNESS_MARGIN_MIN = 0.12
WITNESS_FRESHNESS_S = 0.35
WITNESS_RANGE_M = (0.90, 2.30)
WITNESS_PAIR_SEPARATION_S = 0.20
WITNESS_PAIR_WINDOW_S = 1.00
WITNESS_CADENCE_TICKS = 2
WITNESS_RANGE_MAX_M = 3.20
UNCERTAINTY_TIMEOUT_S = 3.50
BASE_FRAME_LOSS = 0.08
ALIAS_KIDNAP_TIMES_S = (0.0, 0.2, 0.4, 0.6)
DROPOUT_BY_LAYOUT_S = (0.60, 1.20, 1.80, 4.20)
FORBIDDEN_SEEDS = frozenset({101, 202, 303, 404, 505, 606})
SCORER_ONLY_FIELDS = frozenset(
    {
        "truth_pose",
        "truth_distance_m",
        "arrived",
        "false_arrival",
        "case_kind",
        "kidnap_at_s",
    }
)
POLICY_EVIDENCE_FIELDS = frozenset(
    {
        "stamp_s",
        "map_claim",
        "map_healthy",
        "discontinuity_score",
        "witness",
    }
)

SOURCE_PATHS = (
    "research/20260824/nav-core/arms.py",
    "research/20260824/nav-core/room.py",
    "research/20260824/nav-core/stack.py",
    "research/20260824/nav-accept/nav_accept.py",
    "research/20260826/navigation-generalization/experiment.py",
    "research/20260826/independent-completion/DESIGN.md",
    "research/20260826/independent-completion/experiment.py",
)

TWIN_BY_ID = {
    "place_bed": "place_couch",
    "place_couch": "place_bed",
    "place_desk": "place_bowl",
    "place_bowl": "place_desk",
    "place_shelf": "place_counter",
    "place_counter": "place_shelf",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _sha256_bytes(encoded)


def _u01(key: str) -> float:
    raw = hashlib.sha256(key.encode()).digest()[:8]
    return (int.from_bytes(raw, "big") + 0.5) / float(1 << 64)


def _normal(key: str) -> float:
    u1 = max(_u01(key + "|u1"), 1e-15)
    u2 = _u01(key + "|u2")
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _seed_for(case_id: str) -> int:
    seed = int.from_bytes(hashlib.sha256(case_id.encode()).digest()[:4], "big")
    seed = 1 + seed % 2_000_000_000
    while seed in FORBIDDEN_SEEDS:
        seed += 1
    return seed


@dataclass(frozen=True)
class Case:
    """A preregistered case; no scorer result is stored here."""

    case_id: str
    case_kind: str
    case_index: int
    layout: int | str
    start_index: int
    goal_id: str
    seed: int
    kidnap_at_s: float | None = None
    witness_blackout_s: float = 0.0
    discontinuity_blind: bool = False
    false_latch_on_claim: bool = False

    def matrix_row(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_kind": self.case_kind,
            "case_index": self.case_index,
            "layout": str(self.layout),
            "start_index": self.start_index,
            "goal_id": self.goal_id,
            "seed": self.seed,
            "kidnap_at_s": self.kidnap_at_s,
            "witness_blackout_s": self.witness_blackout_s,
            "discontinuity_blind": self.discontinuity_blind,
            "false_latch_on_claim": self.false_latch_on_claim,
        }


def build_matrix() -> list[Case]:
    """Generate the untouched 120 + 120 + 120 factorial."""

    cases: list[Case] = []
    index = 0
    goal_ids = tuple(place.place_id for place in room.PLACES)

    for layout in range(len(room.LAYOUTS)):
        for start_index in range(len(room.STARTS)):
            for goal_id in goal_ids:
                case_id = (
                    f"{MATRIX_SCHEMA}|nominal|L{layout}|S{start_index}|{goal_id}"
                )
                cases.append(
                    Case(
                        case_id=case_id,
                        case_kind="nominal",
                        case_index=index,
                        layout=layout,
                        start_index=start_index,
                        goal_id=goal_id,
                        seed=_seed_for(case_id),
                        false_latch_on_claim=index % 10 == 0,
                    )
                )
                index += 1

    alias_local_index = 0
    for start_index in range(len(room.STARTS)):
        for goal_id in goal_ids:
            for kidnap_at_s in ALIAS_KIDNAP_TIMES_S:
                case_id = (
                    f"{MATRIX_SCHEMA}|alias|S{start_index}|{goal_id}|"
                    f"T{kidnap_at_s:.1f}"
                )
                cases.append(
                    Case(
                        case_id=case_id,
                        case_kind="alias",
                        case_index=index,
                        layout="aliased",
                        start_index=start_index,
                        goal_id=goal_id,
                        seed=_seed_for(case_id),
                        kidnap_at_s=kidnap_at_s,
                        discontinuity_blind=alias_local_index % 8 == 0,
                    )
                )
                index += 1
                alias_local_index += 1

    dropout_local_index = 0
    for layout in range(len(room.LAYOUTS)):
        for start_index in range(len(room.STARTS)):
            for goal_id in goal_ids:
                case_id = (
                    f"{MATRIX_SCHEMA}|dropout|L{layout}|S{start_index}|{goal_id}"
                )
                cases.append(
                    Case(
                        case_id=case_id,
                        case_kind="dropout",
                        case_index=index,
                        layout=layout,
                        start_index=start_index,
                        goal_id=goal_id,
                        seed=_seed_for(case_id),
                        witness_blackout_s=DROPOUT_BY_LAYOUT_S[layout],
                        false_latch_on_claim=dropout_local_index % 5 == 0,
                    )
                )
                index += 1
                dropout_local_index += 1

    if len(cases) != 360 or len({case.case_id for case in cases}) != 360:
        raise AssertionError("the preregistered matrix must contain 360 unique cases")
    if any(case.seed in FORBIDDEN_SEEDS for case in cases):
        raise AssertionError("a prior-design seed leaked into the new matrix")
    return cases


@dataclass(frozen=True)
class WitnessObservation:
    """Noisy policy-facing target-relative evidence; no identity/truth label."""

    captured_at_s: float
    delivered_at_s: float
    target_score: float
    runner_up_score: float
    measured_range_m: float

    @property
    def margin(self) -> float:
        return self.target_score - self.runner_up_score


@dataclass(frozen=True)
class CompletionEvidence:
    """The complete policy boundary; scorer fields are intentionally absent."""

    stamp_s: float
    map_claim: bool
    map_healthy: bool
    discontinuity_score: float | None
    witness: WitnessObservation | None


@dataclass(frozen=True)
class AuthorityDecision:
    action: str
    reason: str


class TargetRelativeSensor:
    """Synthetic active landmark scan independent of MAP pose and covariance."""

    def __init__(self, case: Case) -> None:
        self.case = case
        self._blackout_started_at_s: float | None = None
        self._blackout_until_s: float | None = None
        self.stats = {
            "scheduled_queries": 0,
            "missing_queries": 0,
            "delivered_frames": 0,
            "raw_target_high_frames": 0,
            "margin_qualified_frames": 0,
            "no_visible_landmark": 0,
        }

    @staticmethod
    def _base_score(observed_id: str, class_id: str) -> float:
        if observed_id == class_id:
            return 0.95
        if TWIN_BY_ID[observed_id] == class_id:
            return 0.72
        # Deterministic low cross-class similarity, independent of case/run.
        return 0.16 + 0.10 * _u01(f"descriptor-cross|{observed_id}|{class_id}")

    def _score(self, observed_id: str, class_id: str, tick: int) -> float:
        noise = 0.035 * _normal(
            f"{self.case.case_id}|descriptor|{tick}|{observed_id}|{class_id}"
        )
        return min(1.0, max(0.0, self._base_score(observed_id, class_id) + noise))

    def observe(
        self,
        *,
        physical_pose: tuple[float, float, float],
        target_id: str,
        t_s: float,
        query_active: bool,
        map_claim: bool,
    ) -> WitnessObservation | None:
        """Convert simulator physics into a noisy schema, then discard physics."""

        if map_claim and self._blackout_started_at_s is None:
            self._blackout_started_at_s = t_s
            self._blackout_until_s = t_s + self.case.witness_blackout_s
        if not query_active:
            return None
        tick = round(t_s / CONTROL_DT_S)
        phase = self.case.seed % WITNESS_CADENCE_TICKS
        if tick % WITNESS_CADENCE_TICKS != phase:
            return None

        self.stats["scheduled_queries"] += 1
        if self._blackout_until_s is not None and t_s < self._blackout_until_s:
            self.stats["missing_queries"] += 1
            return None
        if _u01(f"{self.case.case_id}|base-frame-loss|{tick}") < BASE_FRAME_LOSS:
            self.stats["missing_queries"] += 1
            return None

        x, y, _yaw = physical_pose
        visible: list[tuple[str, float]] = []
        for place in room.PLACES:
            landmark_range = math.hypot(place.marker.cx - x, place.marker.cy - y)
            if landmark_range <= WITNESS_RANGE_MAX_M:
                visible.append((place.place_id, landmark_range))
        if not visible:
            self.stats["missing_queries"] += 1
            self.stats["no_visible_landmark"] += 1
            return None

        # Targeted retrieval chooses the physical detection with the largest
        # target-query score. It does not learn which detection is true.
        scored = [
            (self._score(observed_id, target_id, tick), observed_id, distance)
            for observed_id, distance in visible
        ]
        target_score, observed_id, physical_range = max(
            scored, key=lambda row: (row[0], -row[2], row[1])
        )
        all_scores = [
            self._score(observed_id, class_id, tick)
            for class_id in TWIN_BY_ID
        ]
        class_ids = list(TWIN_BY_ID)
        runner_up = max(
            score
            for class_id, score in zip(class_ids, all_scores, strict=True)
            if class_id != target_id
        )
        range_noise = 0.04 * _normal(
            f"{self.case.case_id}|range|{tick}|{observed_id}"
        )
        latency_ticks = int(
            3.0 * _u01(f"{self.case.case_id}|latency|{tick}|{observed_id}")
        )
        latency_s = latency_ticks * CONTROL_DT_S
        observation = WitnessObservation(
            captured_at_s=round(t_s - latency_s, 6),
            delivered_at_s=round(t_s, 6),
            target_score=round(float(target_score), 6),
            runner_up_score=round(float(runner_up), 6),
            measured_range_m=round(max(0.0, physical_range + range_noise), 6),
        )
        self.stats["delivered_frames"] += 1
        self.stats["raw_target_high_frames"] += int(
            observation.target_score >= WITNESS_SCORE_MIN
        )
        self.stats["margin_qualified_frames"] += int(
            observation.target_score >= WITNESS_SCORE_MIN
            and observation.margin >= WITNESS_MARGIN_MIN
        )
        return observation


class DiscontinuitySensor:
    """Noisy independent impulse/displacement proxy; deliberately imperfect."""

    def __init__(self, case: Case, initial_pose: tuple[float, float, float]) -> None:
        self.case = case
        self._previous = initial_pose
        self._blind_sample_used = False
        self.stats = {
            "samples": 0,
            "detections": 0,
            "blind_jump_samples": 0,
            "injected_artifacts": 0,
        }

    def observe(
        self,
        *,
        physical_pose: tuple[float, float, float],
        t_s: float,
        artifact: bool,
    ) -> float | None:
        previous = self._previous
        self._previous = physical_pose
        translation = math.hypot(
            physical_pose[0] - previous[0], physical_pose[1] - previous[1]
        )
        yaw_delta = abs(
            math.atan2(
                math.sin(physical_pose[2] - previous[2]),
                math.cos(physical_pose[2] - previous[2]),
            )
        )
        impulse_proxy = max(translation, 0.25 * yaw_delta)
        if (
            self.case.discontinuity_blind
            and impulse_proxy > 1.0
            and not self._blind_sample_used
        ):
            self._blind_sample_used = True
            self.stats["blind_jump_samples"] += 1
            return None
        self.stats["samples"] += 1
        if artifact:
            self.stats["injected_artifacts"] += 1
            score = 0.95
        else:
            noise = 0.03 * _normal(
                f"{self.case.case_id}|discontinuity|{round(t_s, 3):.3f}"
            )
            score = min(1.0, max(0.0, (impulse_proxy - 0.12) / 0.75 + noise))
        self.stats["detections"] += int(score >= DISCONTINUITY_THRESHOLD)
        return round(score, 6)


class IndependentCompletionAuthority:
    """Pure policy over :class:`CompletionEvidence`; it never sees simulator truth."""

    def __init__(self) -> None:
        self.latched = False
        self.latch_started_at_s: float | None = None
        self.first_map_claim_at_s: float | None = None
        self.authorization_latency_s: float | None = None
        self.rearm_latency_s: float | None = None
        self.uncertain_reason = ""
        self.latch_count = 0
        self.rearm_count = 0
        self._qualified_stamps: list[float] = []

    @staticmethod
    def _witness_qualifies(
        witness: WitnessObservation | None, stamp_s: float
    ) -> bool:
        if witness is None:
            return False
        age_s = stamp_s - witness.captured_at_s
        return (
            0.0 <= age_s <= WITNESS_FRESHNESS_S
            and witness.target_score >= WITNESS_SCORE_MIN
            and witness.margin >= WITNESS_MARGIN_MIN
            and WITNESS_RANGE_M[0]
            <= witness.measured_range_m
            <= WITNESS_RANGE_M[1]
        )

    def _observe_witness(self, evidence: CompletionEvidence) -> None:
        cutoff = evidence.stamp_s - WITNESS_PAIR_WINDOW_S
        self._qualified_stamps = [
            stamp for stamp in self._qualified_stamps if stamp >= cutoff
        ]
        if not self._witness_qualifies(evidence.witness, evidence.stamp_s):
            return
        assert evidence.witness is not None
        stamp = evidence.witness.captured_at_s
        if not self._qualified_stamps or (
            stamp - self._qualified_stamps[-1] >= WITNESS_PAIR_SEPARATION_S - 1e-9
        ):
            self._qualified_stamps.append(stamp)

    def _has_pair(self) -> bool:
        if len(self._qualified_stamps) < 2:
            return False
        return (
            self._qualified_stamps[-1] - self._qualified_stamps[-2]
            >= WITNESS_PAIR_SEPARATION_S - 1e-9
        )

    def step(self, evidence: CompletionEvidence) -> AuthorityDecision:
        score = evidence.discontinuity_score
        if score is not None and score >= DISCONTINUITY_THRESHOLD and not self.latched:
            self.latched = True
            self.latch_count += 1
            self.latch_started_at_s = evidence.stamp_s
            self._qualified_stamps.clear()

        if evidence.map_claim and self.first_map_claim_at_s is None:
            self.first_map_claim_at_s = evidence.stamp_s
        self._observe_witness(evidence)

        if evidence.map_claim and evidence.map_healthy and self._has_pair():
            if self.latched:
                self.latched = False
                self.rearm_count += 1
                assert self.latch_started_at_s is not None
                self.rearm_latency_s = round(
                    evidence.stamp_s - self.latch_started_at_s, 6
                )
            assert self.first_map_claim_at_s is not None
            self.authorization_latency_s = round(
                evidence.stamp_s - self.first_map_claim_at_s, 6
            )
            return AuthorityDecision("arrive", "independent_witness_pair")

        wait_started = self.latch_started_at_s
        wait_reason = "latched_discontinuity"
        if wait_started is None and self.first_map_claim_at_s is not None:
            wait_started = self.first_map_claim_at_s
            wait_reason = "independent_witness_unavailable"
        if wait_started is not None:
            if evidence.stamp_s - wait_started >= UNCERTAINTY_TIMEOUT_S - 1e-9:
                self.uncertain_reason = wait_reason
                return AuthorityDecision("uncertain", wait_reason)
            return AuthorityDecision("hold", wait_reason)
        return AuthorityDecision("continue", "no_completion_candidate")


class CovarianceOnlyArm(ArmShipped):
    arm = "covariance_only"

    def __init__(self, spec: Any) -> None:
        super().__init__(spec)
        self._first_map_claim_at_s: float | None = None

    def command(
        self, observation: Any, t_s: float
    ) -> tuple[VelocityCommand, bool, str]:
        requested, declared, note = super().command(observation, t_s)
        if declared and self._first_map_claim_at_s is None:
            self._first_map_claim_at_s = t_s
        return requested, declared, note

    def finish(self) -> None:
        super().finish()
        self.result.extra["first_map_claim_at_s"] = self._first_map_claim_at_s


class CorrelatedStreakArm(ArmShipped):
    arm = "correlated_streak_5"

    def __init__(self, spec: Any) -> None:
        super().__init__(spec)
        self._streak = 0
        self._first_map_claim_at_s: float | None = None

    def command(
        self, observation: Any, t_s: float
    ) -> tuple[VelocityCommand, bool, str]:
        requested, map_claim, note = super().command(observation, t_s)
        if map_claim:
            if self._first_map_claim_at_s is None:
                self._first_map_claim_at_s = t_s
            self._streak += 1
        else:
            self._streak = 0
        if map_claim and self._streak < STREAK_TICKS:
            return VelocityCommand(), False, "correlated_arrival_quarantine"
        return requested, map_claim, note

    def finish(self) -> None:
        super().finish()
        self.result.extra["first_map_claim_at_s"] = self._first_map_claim_at_s
        self.result.extra["arrival_streak_ticks"] = self._streak


class IndependentWitnessArm(ArmShipped):
    arm = "independent_witness_latch"

    def __init__(self, spec: Any) -> None:
        super().__init__(spec)
        self.case: Case = spec.independent_completion_case
        self.authority = IndependentCompletionAuthority()
        self.target_sensor = TargetRelativeSensor(self.case)
        self.discontinuity_sensor = DiscontinuitySensor(self.case, spec.start)
        self._false_artifact_injected = False
        self._uncertain_done = False

    def command(
        self, observation: Any, t_s: float
    ) -> tuple[VelocityCommand, bool, str]:
        requested, map_claim, note = super().command(observation, t_s)
        artifact = bool(
            map_claim
            and self.case.false_latch_on_claim
            and not self._false_artifact_injected
        )
        if artifact:
            self._false_artifact_injected = True
        discontinuity_score = self.discontinuity_sensor.observe(
            physical_pose=self.body.pose,
            t_s=t_s,
            artifact=artifact,
        )
        will_latch = bool(
            discontinuity_score is not None
            and discontinuity_score >= DISCONTINUITY_THRESHOLD
        )
        witness = self.target_sensor.observe(
            physical_pose=self.body.pose,
            target_id=self.spec.goal_id,
            t_s=t_s,
            query_active=map_claim or self.authority.latched or will_latch,
            map_claim=map_claim,
        )
        evidence = CompletionEvidence(
            stamp_s=t_s,
            map_claim=map_claim,
            map_healthy=self.stack.map_pose().health is PoseHealth.HEALTHY,
            discontinuity_score=discontinuity_score,
            witness=witness,
        )
        decision = self.authority.step(evidence)
        if decision.action == "arrive":
            self.result.status = "arrived_independent"
            return VelocityCommand(), True, decision.reason
        if decision.action == "uncertain":
            self._uncertain_done = True
            self.result.status = "localization_uncertain"
            self.result.failure_type = "localization_uncertain"
            return VelocityCommand(), False, decision.reason
        if decision.action == "hold":
            self.result.status = "hold_independent_completion"
            return VelocityCommand(), False, decision.reason
        # A raw MAP completion never escapes without independent evidence.
        return requested, False, note

    def done(self) -> bool:
        return self._uncertain_done

    def finish(self) -> None:
        super().finish()
        self.result.extra.update(
            {
                "first_map_claim_at_s": self.authority.first_map_claim_at_s,
                "authorization_latency_s": self.authority.authorization_latency_s,
                "rearm_latency_s": self.authority.rearm_latency_s,
                "latch_count": self.authority.latch_count,
                "rearm_count": self.authority.rearm_count,
                "final_latched": self.authority.latched,
                "uncertain_reason": self.authority.uncertain_reason,
                "false_artifact_injected": self._false_artifact_injected,
                "target_sensor": dict(self.target_sensor.stats),
                "discontinuity_sensor": dict(self.discontinuity_sensor.stats),
            }
        )

    def run(self) -> Any:
        result = super().run()
        # Frozen NAV-CORE does not know this research-only typed outcome and
        # normalizes unknown strings to silent_stall_step_limit after finish.
        # Restore the local arm's terminal after the inherited loop returns.
        if self._uncertain_done:
            result.failure_type = "localization_uncertain"
        return result


ARM_CLASSES = (CovarianceOnlyArm, CorrelatedStreakArm, IndependentWitnessArm)


def _episode_spec(case: Case, learned_map: Any) -> Any:
    spec = arms.EpisodeSpec(
        episode=10_000 + case.case_index,
        seed_index=20 + case.case_index,
        seed=case.seed,
        layout=case.layout,
        goal_id=case.goal_id,
        start=room.STARTS[case.start_index],
        directive=nav_accept.bench.directive_for(case.goal_id),
        learned_map=learned_map,
        scan_gap=(1_000.0, 1_002.0),
        kidnap_at_s=case.kidnap_at_s,
    )
    spec.scenario_id = case.case_id
    spec.independent_completion_case = case
    return spec


def _project_row(case: Case, result: Any) -> dict[str, Any]:
    row = result.as_row()
    extra = row.get("extra") or {}
    projected = {
        **case.matrix_row(),
        "arm": row["arm"],
        "declared_arrival": bool(row["declared_arrival"]),
        "arrived": bool(row["arrived"]),
        "false_arrival": bool(row["false_arrival"]),
        "truth_distance_m": row["truth_distance_m"],
        "contacts": int(row["contacts"]),
        "steps": int(row["steps"]),
        "time_to_goal_s": row["time_to_goal_s"],
        "failure_type": str(row["failure_type"]),
        "final_health": str(row["final_health"]),
        "first_map_claim_at_s": extra.get("first_map_claim_at_s"),
        "arrival_confidence": extra.get("arrival_confidence"),
        "authorization_latency_s": extra.get("authorization_latency_s"),
        "rearm_latency_s": extra.get("rearm_latency_s"),
        "latch_count": int(extra.get("latch_count", 0)),
        "rearm_count": int(extra.get("rearm_count", 0)),
        "final_latched": bool(extra.get("final_latched", False)),
        "uncertain_reason": str(extra.get("uncertain_reason", "")),
        "false_artifact_injected": bool(
            extra.get("false_artifact_injected", False)
        ),
        "target_sensor": extra.get("target_sensor", {}),
        "discontinuity_sensor": extra.get("discontinuity_sensor", {}),
    }
    return projected


def _run_cases(cases: list[Case]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_number, case in enumerate(cases, start=1):
        learned = world_map.seed_room_map()
        use_learned_map(learned)
        try:
            spec = _episode_spec(case, learned)
            for arm_cls in ARM_CLASSES:
                result = arm_cls(spec).run()
                rows.append(_project_row(case, result))
        finally:
            learned.close()
        if case_number % 20 == 0 or case_number == len(cases):
            print(f"completed_cases={case_number}/{len(cases)}", flush=True)
    return rows


def _nearest_rank(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return round(ordered[index], 6)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "episodes": len(rows),
        "declared_arrivals": sum(row["declared_arrival"] for row in rows),
        "true_arrivals": sum(row["arrived"] for row in rows),
        "false_arrivals": sum(row["false_arrival"] for row in rows),
        "contacts": sum(row["contacts"] for row in rows),
        "localization_uncertain": sum(
            row["failure_type"] == "localization_uncertain" for row in rows
        ),
        "silent_timeouts": sum(
            row["failure_type"] == "silent_stall_step_limit" for row in rows
        ),
        "authorization_latency_p50_s": _nearest_rank(
            (
                row["authorization_latency_s"]
                for row in rows
                if row["authorization_latency_s"] is not None
            ),
            0.50,
        ),
        "authorization_latency_p95_s": _nearest_rank(
            (
                row["authorization_latency_s"]
                for row in rows
                if row["authorization_latency_s"] is not None
            ),
            0.95,
        ),
        "rearm_latency_p95_s": _nearest_rank(
            (
                row["rearm_latency_s"]
                for row in rows
                if row["rearm_latency_s"] is not None
            ),
            0.95,
        ),
    }


def _select(
    rows: list[dict[str, Any]], *, arm: str, kind: str | None = None
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["arm"] == arm and (kind is None or row["case_kind"] == kind)
    ]


def _aggregate_sensor(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    aggregate: dict[str, int] = {}
    for row in rows:
        for metric, value in row.get(key, {}).items():
            aggregate[metric] = aggregate.get(metric, 0) + int(value)
    return dict(sorted(aggregate.items()))


def _summarize_and_check(
    matrix: list[Case], rows: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, bool], dict[str, Any]]:
    summaries: dict[str, Any] = {}
    for kind in ("nominal", "alias", "dropout"):
        summaries[kind] = {
            arm_cls.arm: _summary(_select(rows, arm=arm_cls.arm, kind=kind))
            for arm_cls in ARM_CLASSES
        }

    covariance_alias = _select(rows, arm=CovarianceOnlyArm.arm, kind="alias")
    opportunity_ids = {
        row["case_id"] for row in covariance_alias if row["false_arrival"]
    }
    opportunity_rates: dict[str, float] = {}
    for arm_cls in ARM_CLASSES:
        arm_rows = [
            row
            for row in _select(rows, arm=arm_cls.arm, kind="alias")
            if row["case_id"] in opportunity_ids
        ]
        opportunity_rates[arm_cls.arm] = (
            sum(row["false_arrival"] for row in arm_rows) / len(arm_rows)
            if arm_rows
            else 0.0
        )

    candidate = _select(rows, arm=IndependentWitnessArm.arm)
    candidate_alias = [row for row in candidate if row["case_kind"] == "alias"]
    candidate_nominal = [row for row in candidate if row["case_kind"] == "nominal"]
    candidate_dropout = [row for row in candidate if row["case_kind"] == "dropout"]
    covariance_nominal = _select(rows, arm=CovarianceOnlyArm.arm, kind="nominal")
    short_dropout = [
        row for row in candidate_dropout if row["witness_blackout_s"] < 4.0
    ]
    long_dropout = [
        row for row in candidate_dropout if row["witness_blackout_s"] >= 4.0
    ]
    recovered_short = [row for row in short_dropout if row["arrived"]]
    false_latch_rows = [
        row
        for row in candidate
        if row["false_latch_on_claim"] and row["false_artifact_injected"]
    ]
    false_latch_rearmed = [
        row for row in false_latch_rows if row["rearm_latency_s"] is not None
    ]
    unresolved_alias_or_dropout = [
        row
        for row in candidate_alias + candidate_dropout
        if not row["declared_arrival"]
    ]
    candidate_blind_alias = [
        row for row in candidate_alias if row["discontinuity_blind"]
    ]

    target_audit = _aggregate_sensor(candidate, "target_sensor")
    alias_target_audit = _aggregate_sensor(candidate_alias, "target_sensor")
    discontinuity_audit = _aggregate_sensor(candidate, "discontinuity_sensor")
    short_latency_p95 = _nearest_rank(
        (
            row["authorization_latency_s"]
            for row in recovered_short
            if row["authorization_latency_s"] is not None
        ),
        0.95,
    )
    false_latch_rearm_p95 = _nearest_rank(
        (row["rearm_latency_s"] for row in false_latch_rearmed), 0.95
    )

    evidence_audit = {
        "policy_evidence_fields": sorted(POLICY_EVIDENCE_FIELDS),
        "scorer_only_fields": sorted(SCORER_ONLY_FIELDS),
        "schema_intersection": sorted(POLICY_EVIDENCE_FIELDS & SCORER_ONLY_FIELDS),
        "target_sensor_all_candidate": target_audit,
        "target_sensor_alias": alias_target_audit,
        "discontinuity_sensor_all_candidate": discontinuity_audit,
        "alias_discontinuity_blind_cases": len(candidate_blind_alias),
        "alias_discontinuity_blind_false_arrivals": sum(
            row["false_arrival"] for row in candidate_blind_alias
        ),
    }
    decision_facts = {
        "matrix_cases": len(matrix),
        "rows": len(rows),
        "alias_opportunity_cases": len(opportunity_ids),
        "alias_opportunity_false_arrival_rates": opportunity_rates,
        "candidate_nominal_true_arrivals": sum(
            row["arrived"] for row in candidate_nominal
        ),
        "covariance_nominal_true_arrivals": sum(
            row["arrived"] for row in covariance_nominal
        ),
        "candidate_nominal_contacts": sum(row["contacts"] for row in candidate_nominal),
        "covariance_nominal_contacts": sum(row["contacts"] for row in covariance_nominal),
        "candidate_alias_false_arrivals": sum(
            row["false_arrival"] for row in candidate_alias
        ),
        "candidate_blind_alias_false_arrivals": sum(
            row["false_arrival"] for row in candidate_blind_alias
        ),
        "short_dropout_cases": len(short_dropout),
        "short_dropout_recovered": len(recovered_short),
        "short_dropout_authorization_latency_p95_s": short_latency_p95,
        "long_dropout_cases": len(long_dropout),
        "long_dropout_uncertain": sum(
            row["failure_type"] == "localization_uncertain" for row in long_dropout
        ),
        "unresolved_alias_or_dropout": len(unresolved_alias_or_dropout),
        "unresolved_alias_or_dropout_typed_uncertain": sum(
            row["failure_type"] == "localization_uncertain"
            for row in unresolved_alias_or_dropout
        ),
        "candidate_silent_timeouts": sum(
            row["failure_type"] == "silent_stall_step_limit" for row in candidate
        ),
        "injected_false_latch_cases": len(false_latch_rows),
        "false_latch_rearmed": len(false_latch_rearmed),
        "false_latch_rearm_latency_p95_s": false_latch_rearm_p95,
    }

    rows_by_arm_kind = {
        (arm_cls.arm, kind): len(_select(rows, arm=arm_cls.arm, kind=kind))
        for arm_cls in ARM_CLASSES
        for kind in ("nominal", "alias", "dropout")
    }
    matrix_counts = {
        kind: sum(case.case_kind == kind for case in matrix)
        for kind in ("nominal", "alias", "dropout")
    }
    checks = {
        "matrix_exactly_120_each": all(value == 120 for value in matrix_counts.values()),
        "matrix_360_unique_ids": len({case.case_id for case in matrix}) == 360,
        "all_arms_run_every_case": all(value == 120 for value in rows_by_arm_kind.values()),
        "alias_opportunities_at_least_80": len(opportunity_ids) >= 80,
        "covariance_false_on_80pct_opportunities": opportunity_rates[
            CovarianceOnlyArm.arm
        ]
        >= 0.80,
        "streak_false_on_80pct_opportunities": opportunity_rates[
            CorrelatedStreakArm.arm
        ]
        >= 0.80,
        "candidate_zero_alias_false_arrivals": decision_facts[
            "candidate_alias_false_arrivals"
        ]
        == 0,
        "candidate_zero_blind_alias_false_arrivals": decision_facts[
            "candidate_blind_alias_false_arrivals"
        ]
        == 0,
        "candidate_nominal_recall_at_least_118": decision_facts[
            "candidate_nominal_true_arrivals"
        ]
        >= 118,
        "candidate_nominal_contacts_noninferior": decision_facts[
            "candidate_nominal_contacts"
        ]
        <= decision_facts["covariance_nominal_contacts"],
        "short_dropout_recovery_at_least_85": len(recovered_short) >= 85,
        "short_dropout_latency_p95_at_most_2_5s": (
            short_latency_p95 is not None and short_latency_p95 <= 2.50
        ),
        "unresolved_alias_dropout_all_typed_uncertain": (
            len(unresolved_alias_or_dropout)
            == decision_facts["unresolved_alias_or_dropout_typed_uncertain"]
        ),
        "all_long_dropout_typed_uncertain": decision_facts[
            "long_dropout_uncertain"
        ]
        == 30,
        "candidate_zero_silent_timeouts": decision_facts[
            "candidate_silent_timeouts"
        ]
        == 0,
        "false_latch_rearm_at_least_20": len(false_latch_rearmed) >= 20,
        "false_latch_rearm_p95_at_most_2_5s": (
            false_latch_rearm_p95 is not None and false_latch_rearm_p95 <= 2.50
        ),
        "policy_schema_excludes_scorer_fields": not (
            POLICY_EVIDENCE_FIELDS & SCORER_ONLY_FIELDS
        ),
        "sensor_has_missing_or_ambiguous_queries": (
            target_audit.get("missing_queries", 0) > 0
        ),
        "alias_sensor_has_raw_high_target_nonoracle_frames": (
            alias_target_audit.get("raw_target_high_frames", 0) > 0
        ),
    }
    return summaries, checks, {
        "decision_facts": decision_facts,
        "evidence_audit": evidence_audit,
    }


def _source_integrity() -> dict[str, str]:
    return {
        relative: _sha256_bytes((ROOT / relative).read_bytes())
        for relative in SOURCE_PATHS
    }


def run_experiment(*, smoke: bool = False) -> dict[str, Any]:
    matrix = build_matrix()
    if smoke:
        matrix = [
            next(case for case in matrix if case.case_kind == kind)
            for kind in ("nominal", "alias", "dropout")
        ]
    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    started = time.perf_counter()
    try:
        rows = _run_cases(matrix)
    finally:
        use_learned_map(None)
        use_semantic_source(None)
        owner = getattr(nav_accept, "_OWNER", None)
        if owner is not None:
            owner.close()
            nav_accept._OWNER = None

    if smoke:
        deterministic = {
            "schema": PAYLOAD_SCHEMA + ".smoke",
            "matrix": [case.matrix_row() for case in matrix],
            "rows": rows,
        }
    else:
        summaries, checks, facts = _summarize_and_check(matrix, rows)
        deterministic = {
            "schema": PAYLOAD_SCHEMA,
            "registered_parameters": {
                "matrix_schema": MATRIX_SCHEMA,
                "control_hz": CONTROL_HZ,
                "streak_ticks": STREAK_TICKS,
                "discontinuity_threshold": DISCONTINUITY_THRESHOLD,
                "witness_score_min": WITNESS_SCORE_MIN,
                "witness_margin_min": WITNESS_MARGIN_MIN,
                "witness_freshness_s": WITNESS_FRESHNESS_S,
                "witness_range_m": list(WITNESS_RANGE_M),
                "witness_pair_separation_s": WITNESS_PAIR_SEPARATION_S,
                "witness_pair_window_s": WITNESS_PAIR_WINDOW_S,
                "witness_cadence_ticks": WITNESS_CADENCE_TICKS,
                "witness_range_max_m": WITNESS_RANGE_MAX_M,
                "uncertainty_timeout_s": UNCERTAINTY_TIMEOUT_S,
                "base_frame_loss": BASE_FRAME_LOSS,
                "alias_kidnap_times_s": list(ALIAS_KIDNAP_TIMES_S),
                "dropout_by_layout_s": list(DROPOUT_BY_LAYOUT_S),
                "repository_head": REPOSITORY_HEAD,
            },
            "matrix_sha256": _canonical_digest(
                [case.matrix_row() for case in matrix]
            ),
            "source_integrity": _source_integrity(),
            "matrix": [case.matrix_row() for case in matrix],
            "rows": rows,
            "summaries": summaries,
            **facts,
            "checks": checks,
            "run_verdict": "SUPPORTED_PENDING_REPLAY"
            if all(checks.values())
            else "REFUTED",
        }
    digest = _canonical_digest(deterministic)
    return {
        "report_schema": REPORT_SCHEMA,
        "environment": {
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "host": platform.node(),
            "python": platform.python_version(),
            "repository_head": REPOSITORY_HEAD,
            "hardware_used": "none",
            "evidence_tier": "deterministic_synthetic_architecture",
            "wall_s": round(time.perf_counter() - started, 3),
            "smoke": smoke,
        },
        "deterministic_payload_sha256": digest,
        **deterministic,
    }


def _check_payload(payload: dict[str, Any], *, smoke: bool) -> None:
    assert payload["deterministic_payload_sha256"]
    assert not (POLICY_EVIDENCE_FIELDS & SCORER_ONLY_FIELDS)
    if smoke:
        assert len(payload["rows"]) == 9
        return
    assert len(payload["matrix"]) == 360
    assert len(payload["rows"]) == 1_080
    assert set(payload["checks"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    payload = run_experiment(smoke=args.smoke)
    _check_payload(payload, smoke=args.smoke)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if not args.smoke:
        print(json.dumps(payload["decision_facts"], indent=2))
        print(json.dumps(payload["checks"], indent=2))
        print(f"run_verdict={payload['run_verdict']}")
    print(f"deterministic_payload_sha256={payload['deterministic_payload_sha256']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
