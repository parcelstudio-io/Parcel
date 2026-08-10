"""D3 SEARCH→NAVIGATE lock-on: detection-triggered single SE2Goal (pure).

When D1 (:class:`~parcel_robot.detection_adapter.multi_view_confirm.MultiViewConfirm`)
confirms a hypothesis and SigLIP similarity clears the recalibrated threshold,
this module proposes **one** :class:`~parcel_robot.instructnav.arbiter.SE2Goal`
through the existing ProposerBus / GoalArbiter contract. Classical A* +
reactive gate remain the sole disposers; learned components only propose.

Frozen surfaces
---------------
``DetectionLockOnSession.observe(...) -> LockOnDecision | None``
``DetectionLockOnSession.build_se2_goal(...) -> SE2Goal`` carrying the live
``(task_id, plan_revision)`` stamp for P0-C mid-run correction.

Flag-off (caller does not construct a session) keeps the frustum multi-view
commit path byte-identical. This module never publishes on its own.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from parcel_robot.contracts import SCHEMA_VERSION, DetectionMsg, EvidenceEnvelopeV1
from parcel_robot.contracts.freshness import expires_from_ttl
from parcel_robot.detection_adapter.metric_localizer import (
    MetricLocalizer,
    MetricMeasurement,
)
from parcel_robot.detection_adapter.multi_view_confirm import MultiViewConfirm
from parcel_robot.instructnav.arbiter import SE2Goal
from parcel_robot.instructnav.siglip import SIGLIP2_MATCH_THRESHOLD, SigLIP2Matcher

LOCK_ON_PROPOSER_SOURCE = "detection_lock_on"
LOCK_ON_PLAN_STEP_ID = "align_then_translate"
DEFAULT_DETECTION_TTL_NS = 500_000_000

#: Pre-registered T-cam vs oracle SR margin (absolute fraction). Gate: T-cam
#: success rate must sit within this of the oracle path on paired seeds.
T_CAM_ORACLE_SR_MARGIN = 0.10

DOES_NOT_PROVE = (
    (
        "Lock-on cells prove detection-triggered SE2Goal propose/dispose and "
        "P0-C revision stamping; they do not prove real D455 recognition."
    ),
    (
        "Paired-seed T-cam vs oracle SR margin is a sim machinery gate, not "
        "field open-vocab recall."
    ),
)


@dataclass(frozen=True, slots=True)
class DetectionLockOnConfig:
    """Numeric policy for the SEARCH→NAVIGATE commit gate."""

    siglip_threshold: float = SIGLIP2_MATCH_THRESHOLD
    se2_ttl_s: float = 2.0
    se2_priority: int = 10
    se2_confidence_floor: float = 0.5
    default_sigma_bearing_rad: float = math.radians(2.0)

    def __post_init__(self) -> None:
        if not 0.0 <= self.siglip_threshold <= 1.0:
            raise ValueError("siglip_threshold must be in [0, 1]")
        if not math.isfinite(self.se2_ttl_s) or self.se2_ttl_s <= 0.0:
            raise ValueError("se2_ttl_s must be finite and positive")
        if not 0.0 <= self.se2_confidence_floor <= 1.0:
            raise ValueError("se2_confidence_floor must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class LockOnDecision:
    """One committed lock-on: metric pose + D2 covariance + evidence."""

    candidate_id: str
    label: str
    position: tuple[float, float]
    covariance: tuple[tuple[float, float], tuple[float, float]]
    yaw_facing_rad: float
    credibility: float
    siglip_score: float
    confidence: float
    source_candidate: Any | None = None


class DetectionLockOnSession:
    """Stateful D1+D2+SigLIP gate that emits at most one lock-on commit."""

    def __init__(
        self,
        *,
        config: DetectionLockOnConfig | None = None,
        confirmer: MultiViewConfirm | None = None,
        localizer: MetricLocalizer | None = None,
        matcher: SigLIP2Matcher | None = None,
    ) -> None:
        self.config = config if config is not None else DetectionLockOnConfig()
        self.confirmer = confirmer if confirmer is not None else MultiViewConfirm()
        self.localizer = localizer if localizer is not None else MetricLocalizer()
        self.matcher = matcher if matcher is not None else SigLIP2Matcher(
            real_threshold=self.config.siglip_threshold
        )
        self._committed = False
        self._view_sequence = 0
        self._last_candidate: Any | None = None
        self._last_label = ""
        self._last_candidate_id = ""
        self._last_siglip = 0.0

    def reset(self) -> None:
        self.confirmer.reset()
        self.localizer.reset()
        self._committed = False
        self._view_sequence = 0
        self._last_candidate = None
        self._last_label = ""
        self._last_candidate_id = ""
        self._last_siglip = 0.0

    @property
    def committed(self) -> bool:
        return self._committed

    def observe(
        self,
        *,
        query: str,
        detection: DetectionMsg | None,
        world_xy: tuple[float, float] | None = None,
        covariance: tuple[tuple[float, float], tuple[float, float]] | None = None,
        robot_xy: tuple[float, float] | None = None,
        candidate: Any | None = None,
    ) -> LockOnDecision | None:
        """Feed one view. Returns a decision only on the confirming tick."""

        if self._committed:
            return None

        confirmed, credibility, _rejected = self.confirmer.update(detection)
        if detection is not None and world_xy is not None and covariance is not None:
            self.localizer.update(
                MetricMeasurement(
                    x=float(world_xy[0]),
                    y=float(world_xy[1]),
                    covariance=covariance,
                    depth_reliable=True,
                    camera_x=None if robot_xy is None else float(robot_xy[0]),
                    camera_y=None if robot_xy is None else float(robot_xy[1]),
                    world_bearing_rad=(
                        None
                        if robot_xy is None
                        else math.atan2(
                            float(world_xy[1]) - float(robot_xy[1]),
                            float(world_xy[0]) - float(robot_xy[0]),
                        )
                    ),
                    source_id=detection.envelope.evidence_id,
                )
            )
            self._last_candidate = candidate
            self._last_label = str(detection.class_id)
            self._last_candidate_id = str(
                getattr(candidate, "candidate_id", "") or detection.track_id or detection.class_id
            )
            self._last_siglip = _siglip_score(
                self.matcher, query, detection.class_id, self.config.siglip_threshold
            )

        if not confirmed:
            return None
        if self._last_siglip < self.config.siglip_threshold:
            return None
        estimate = self.localizer.estimate
        if estimate is None:
            return None

        if robot_xy is None:
            yaw = 0.0
        else:
            yaw = math.atan2(
                estimate.position[1] - float(robot_xy[1]),
                estimate.position[0] - float(robot_xy[0]),
            )
        confidence = max(
            self.config.se2_confidence_floor,
            min(1.0, float(credibility) * max(self._last_siglip, 0.0)),
        )
        decision = LockOnDecision(
            candidate_id=self._last_candidate_id or "lock_on",
            label=self._last_label or str(query),
            position=estimate.position,
            covariance=estimate.covariance,
            yaw_facing_rad=yaw,
            credibility=float(credibility),
            siglip_score=float(self._last_siglip),
            confidence=confidence,
            source_candidate=self._last_candidate,
        )
        self._committed = True
        return decision

    def observe_candidate(
        self,
        *,
        query: str,
        candidate: Any | None,
        robot_xy: tuple[float, float],
        now_ns: int,
    ) -> LockOnDecision | None:
        """Adapt a ``SemanticCandidate`` (or None) into one observe() view."""

        self._view_sequence += 1
        if candidate is None:
            return self.observe(query=query, detection=None, robot_xy=robot_xy)
        detection = candidate_to_detection_msg(
            candidate,
            robot_xy=robot_xy,
            sequence=self._view_sequence,
            now_ns=now_ns,
        )
        cov = covariance_from_candidate(candidate, robot_xy=robot_xy)
        return self.observe(
            query=query,
            detection=detection,
            world_xy=(float(candidate.x), float(candidate.y)),
            covariance=cov,
            robot_xy=robot_xy,
            candidate=candidate,
        )

    def build_se2_goal(
        self,
        decision: LockOnDecision,
        *,
        task_id: str,
        plan_revision: int,
        now_s: float,
    ) -> SE2Goal:
        """ONE SE2Goal stamped with the mission's (task_id, plan_revision)."""

        return SE2Goal(
            source=LOCK_ON_PROPOSER_SOURCE,
            pose=(
                float(decision.position[0]),
                float(decision.position[1]),
                float(decision.yaw_facing_rad),
            ),
            confidence=float(decision.confidence),
            ttl_s=float(self.config.se2_ttl_s),
            plan_step_id=LOCK_ON_PLAN_STEP_ID,
            issued_s=float(now_s),
            priority=int(self.config.se2_priority),
            task_id=str(task_id),
            plan_revision=int(plan_revision),
        )


def _siglip_score(
    matcher: SigLIP2Matcher, query: str, class_id: str, threshold: float
) -> float:
    match = matcher.match(str(query), [str(class_id)])
    if match is None:
        # Exact/alias path: treat string-equal (casefold) as full confidence so
        # the string_fallback matcher never blocks a confirmed detection of the
        # queried class when match() returns None for non-aliases.
        if str(query).casefold().strip() == str(class_id).casefold().strip():
            return 1.0
        return 0.0
    return float(match.score)


def _stable_embedding(text: str, *, dim: int = 16) -> tuple[float, ...]:
    seed = abs(hash(str(text).casefold())) + 1
    values = []
    state = seed
    for _ in range(dim):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        values.append((state / 0x7FFFFFFF) * 2.0 - 1.0)
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return tuple(v / norm for v in values)


def candidate_to_detection_msg(
    candidate: Any,
    *,
    robot_xy: tuple[float, float],
    sequence: int,
    now_ns: int,
    ttl_ns: int = DEFAULT_DETECTION_TTL_NS,
) -> DetectionMsg:
    """Build a contract ``DetectionMsg`` from a navigator SemanticCandidate."""

    meta = getattr(candidate, "metadata", None) or {}
    if not isinstance(meta, dict):
        meta = {}
    cx, cy = float(candidate.x), float(candidate.y)
    rx, ry = float(robot_xy[0]), float(robot_xy[1])
    bearing = float(meta.get("bearing_rad")) if meta.get("bearing_rad") is not None else math.atan2(
        cy - ry, cx - rx
    )
    # DetectionMsg requires bearing in [-π, π].
    bearing = (bearing + math.pi) % (2.0 * math.pi) - math.pi
    range_m = float(meta.get("range_m")) if meta.get("range_m") is not None else math.hypot(
        cx - rx, cy - ry
    )
    range_m = max(0.0, min(200.0, range_m))
    score = float(getattr(candidate, "confidence", 0.0) or 0.0)
    score = 0.0 if score < 0.0 else min(1.0, score)
    label = str(getattr(candidate, "label", "") or "object")
    cid = str(getattr(candidate, "candidate_id", "") or f"cand-{sequence}")
    safe_id = "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in cid)
    if not safe_id or not safe_id[0].isalnum():
        safe_id = f"det_{sequence}"
    track = "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in cid)
    if track and not track[0].isalnum():
        track = f"t_{track}"
    envelope = EvidenceEnvelopeV1(
        schema_version=SCHEMA_VERSION,
        evidence_id=safe_id[:128],
        source=str(getattr(candidate, "source", "") or "semantic_candidate"),
        source_timestamp_ns=int(now_ns),
        received_monotonic_ns=int(now_ns),
        sequence=int(sequence),
        frame_id="map",
        scene_revision=0,
        expires_monotonic_ns=expires_from_ttl(
            received_monotonic_ns=int(now_ns), ttl_ns=int(ttl_ns)
        ),
        calibration_id="lock-on-candidate",
        provenance=("detection_lock_on",),
    )
    return DetectionMsg(
        envelope=envelope,
        class_id=label[:64],
        embedding=_stable_embedding(label),
        bearing_rad=bearing,
        range_m=range_m,
        score=score,
        track_id=track[:128] if track else "",
    )


def covariance_from_candidate(
    candidate: Any,
    *,
    robot_xy: tuple[float, float],
    default_sigma_bearing_rad: float = math.radians(2.0),
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Rebuild D2-shaped planar covariance from candidate metadata.

    Ingress stamps ``sigma_range_m`` / bearing / range (V-A) but not the full
    2×2 matrix (camera_channel is out of V-E OWNS). Reconstruct the polar
    form identical to ``pixel_detections._polar_covariance_xy``.
    """

    meta = getattr(candidate, "metadata", None) or {}
    if not isinstance(meta, dict):
        meta = {}
    raw = meta.get("covariance_xy")
    if (
        isinstance(raw, (list, tuple))
        and len(raw) == 2
        and isinstance(raw[0], (list, tuple))
        and isinstance(raw[1], (list, tuple))
        and len(raw[0]) >= 2
        and len(raw[1]) >= 2
    ):
        return (
            (float(raw[0][0]), float(raw[0][1])),
            (float(raw[1][0]), float(raw[1][1])),
        )
    cx, cy = float(candidate.x), float(candidate.y)
    rx, ry = float(robot_xy[0]), float(robot_xy[1])
    world_bearing = math.atan2(cy - ry, cx - rx)
    range_m = float(meta.get("range_m")) if meta.get("range_m") is not None else math.hypot(
        cx - rx, cy - ry
    )
    sigma_range = float(meta.get("sigma_range_m") or 0.0)
    if not math.isfinite(sigma_range) or sigma_range < 0.0:
        sigma_range = 0.0
    sigma_bearing = float(meta.get("sigma_bearing_rad") or default_sigma_bearing_rad)
    if not math.isfinite(sigma_bearing) or sigma_bearing < 0.0:
        sigma_bearing = default_sigma_bearing_rad
    return _polar_covariance_xy(
        world_bearing_rad=world_bearing,
        range_m=max(range_m, 0.0),
        sigma_range_m=sigma_range,
        sigma_bearing_rad=sigma_bearing,
    )


def _polar_covariance_xy(
    *,
    world_bearing_rad: float,
    range_m: float,
    sigma_range_m: float,
    sigma_bearing_rad: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    var_range = sigma_range_m * sigma_range_m
    var_cross = (range_m * sigma_bearing_rad) ** 2
    c, s = math.cos(world_bearing_rad), math.sin(world_bearing_rad)
    c00 = c * c * var_range + s * s * var_cross
    c01 = c * s * (var_range - var_cross)
    c11 = s * s * var_range + c * c * var_cross
    return ((c00, c01), (c01, c11))


__all__ = [
    "DOES_NOT_PROVE",
    "LOCK_ON_PLAN_STEP_ID",
    "LOCK_ON_PROPOSER_SOURCE",
    "T_CAM_ORACLE_SR_MARGIN",
    "DetectionLockOnConfig",
    "DetectionLockOnSession",
    "LockOnDecision",
    "candidate_to_detection_msg",
    "covariance_from_candidate",
]
