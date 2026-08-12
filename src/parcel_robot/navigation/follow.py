from __future__ import annotations

import math
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from typing import Any, ClassVar

from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE
from parcel_robot.backends.base import SimObservation
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.owner_prediction import PredictedPath
from parcel_robot.navigation.reactive_safety import (
    OWNER_IDENTITY_CONFIDENCE_MIN,
    OWNER_STAND_OFF_MARGIN_M,
    ReactiveSafetyPolicy,
    apply_reactive_safety,
)
from parcel_robot.navigation.yield_aside import (
    YieldAsideLimits,
    planar_free_range,
    propose_yield_aside,
)

# ---------------------------------------------------------------------------
# The owner stand-off family, DERIVED (owner-authorized person-clearance
# retune, 2026-08-10 — "1. person clearance. Implement your recommendation").
#
# ``apply_reactive_safety`` treats the owner as a person by subtracting
# ``owner_collision_envelope_m`` from the owner CENTER distance and comparing
# the remainder against ``person_stop_m``. So the ring at which the final gate
# refuses to translate toward the owner is exactly
# ``person_stop_m + owner_collision_envelope_m`` — that is what
# ``owner_keepout_m`` names, and why it is a derivation and not a knob.
#
# The nominal follow stand-off must sit OUTSIDE that ring, or the controller's
# own target is inside its own keepout and it brakes against itself (measured:
# FOLLOW_BENCH_V1 follow_success 9/9 -> 6/9 when person_stop_m moved 1.0 -> 1.2
# and ``desired_distance_m`` was left at 1.6; see
# scrum/20260809/task_15/E2_SAFETY_WIRING_STATUS.md).
#
# The margin is not chosen either: it is the same margin
# ``StandOffEnvelope`` already puts between a minimum clearance and the
# stand-off that wraps it —
# ``stand_off(r) == minimum_vicinity(r) + arrival_radius_m + stand_off_margin_m``
# — i.e. the controller's terminal position tolerance plus the authority's
# standing trailing margin. Applied here to the owner keepout ring instead of
# an object's minimum vicinity, the same two terms give the follow stand-off.
_OWNER_COLLISION_ENVELOPE_M = 0.55
_OWNER_KEEPOUT_M = DEFAULT_SAFETY_ENVELOPE.person_stop(0.0) + _OWNER_COLLISION_ENVELOPE_M
#: ``arrival_radius_m`` (0.06, controller position tolerance at the terminal
#: pose) + ``stand_off_margin_m`` (0.04). Re-exported from
#: :mod:`parcel_robot.navigation.reactive_safety`, which is where it moved
#: (lane E6, 2026-08-11) when the reactive gate became a consumer: the OWNER's
#: comfort band is exactly this margin, so the gate's band and the controller's
#: stand-off are now provably the same ring rather than two computations of the
#: same formula. Imported, not restated, so the two ``owner_keepout_m + margin``
#: floors below cannot drift from it either.
_FOLLOW_DESIRED_DISTANCE_M = _OWNER_KEEPOUT_M + OWNER_STAND_OFF_MARGIN_M


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


@dataclass(frozen=True)
class FollowPredictionConfig:
    """Anticipatory following and the uncertainty brake that pays for it.

    Aiming at where the owner will be is only safe while the prediction is
    trustworthy, so the two halves ship together: ``min_confidence`` decides
    whether the lead point is used at all, and the brake scales translation
    down as confidence falls, reaching a standstill at ``brake_stop_confidence``.
    Both are evaluated against the predictor's windowed-NIS confidence.
    """

    enabled: bool = False
    lead_s: float = 0.6
    min_confidence: float = 0.45
    # Linear ramp: full speed at or above ``brake_full_confidence``, standstill
    # at or below ``brake_stop_confidence``. The defaults put the card's worked
    # example (x0.5 at confidence 0.3) exactly on the ramp.
    brake_full_confidence: float = 0.5
    brake_stop_confidence: float = 0.1

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("owner_follow.prediction.enabled must be a boolean")
        if not math.isfinite(self.lead_s) or self.lead_s <= 0.0:
            raise ValueError("owner_follow.prediction.lead_s must be positive and finite")
        confidences = {
            "min_confidence": self.min_confidence,
            "brake_full_confidence": self.brake_full_confidence,
            "brake_stop_confidence": self.brake_stop_confidence,
        }
        for name, value in confidences.items():
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"owner_follow.prediction.{name} must be within [0, 1]")
        if self.brake_stop_confidence >= self.brake_full_confidence:
            raise ValueError(
                "owner_follow.prediction.brake_stop_confidence must be below "
                "brake_full_confidence"
            )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> FollowPredictionConfig:
        allowed = {item.name for item in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown owner_follow.prediction settings: {sorted(unknown)}")
        values: dict[str, Any] = {}
        for key, value in raw.items():
            if key == "enabled":
                if not isinstance(value, bool):
                    raise TypeError("owner_follow.prediction.enabled must be a boolean")
                values[key] = value
            else:
                values[key] = float(value)
        return cls(**values)

    def speed_scale(self, confidence: float) -> float:
        """Return the uncertainty brake factor for one prediction confidence."""

        if not math.isfinite(confidence):
            return 0.0
        if confidence >= self.brake_full_confidence:
            return 1.0
        if confidence <= self.brake_stop_confidence:
            return 0.0
        span = self.brake_full_confidence - self.brake_stop_confidence
        return (confidence - self.brake_stop_confidence) / span


@dataclass(frozen=True)
class FollowYieldConfig:
    """Whether direct follow may rotate its aim around a stranger stream (card Y-2).

    Deliberately one switch and nothing else, mirroring
    :class:`FollowPredictionConfig`'s shape: every geometry the proposer uses is
    DERIVED from ``FollowConfig`` and the safety authority
    (``navigation.yield_aside``), so there is no threshold here to configure,
    and therefore none to mis-configure. Default OFF; the flag-off path does not
    even build the proposer's limits.
    """

    enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("owner_follow.yield_aside.enabled must be a boolean")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> FollowYieldConfig:
        allowed = {item.name for item in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown owner_follow.yield_aside settings: {sorted(unknown)}")
        values: dict[str, Any] = {}
        for key, value in raw.items():
            if key == "enabled" and not isinstance(value, bool):
                raise TypeError("owner_follow.yield_aside.enabled must be a boolean")
            values[key] = value
        return cls(**values)


@dataclass(frozen=True)
class FollowConfig:
    """Bounds for direct follow and the camera-derived behind formation.

    ``OwnerTrack`` positions and observation timestamps are the only source of
    owner motion used here. In production those tracks must be camera-derived
    and transformed into the robot odometry frame before entering this
    controller; no simulator pose or actor heading is consumed.
    """

    MODES: ClassVar[frozenset[str]] = frozenset({"direct", "behind"})

    #: DERIVED (see ``_FOLLOW_DESIRED_DISTANCE_M`` above): the owner keepout
    #: ring plus the authority's stand-off margin. 1.6 -> 1.85 as part of the
    #: owner-authorized 2026-08-10 person-clearance retune; it is not exposed in
    #: ``robot.yaml`` on purpose, so it can never be configured back inside the
    #: keepout it is defined against.
    desired_distance_m: float = _FOLLOW_DESIRED_DISTANCE_M
    distance_deadband_m: float = 0.18
    max_vx: float = 0.35
    max_vyaw: float = 0.75
    distance_gain: float = 0.65
    yaw_gain: float = 1.2
    turn_in_place_rad: float = 0.8
    #: The stack's one answer to "is this track the owner?". Derived by reference
    #: from :data:`~parcel_robot.navigation.reactive_safety.OWNER_IDENTITY_CONFIDENCE_MIN`
    #: (lane E6, 2026-08-11, value unchanged at 0.65): the reactive gate now
    #: grants a relaxed comfort band on the same question this field answers, and
    #: the gate must never be more willing to believe a track than the controller
    #: that follows it.
    min_confidence: float = OWNER_IDENTITY_CONFIDENCE_MIN
    occlusion_grace_s: float = 0.7
    stale_after_s: float = 0.6
    obstacle_stop_m: float = 0.65
    #: H-1 (LANE_A_STATUS.md), 2026-08-07: this was the live drift in the
    #: ``obstacle_slow_m`` family — six copies of the comfort band, five of them
    #: 1.2 (``collision.py``, ``reactive_safety.py``, ``pipeline.py``,
    #: ``headless_city.py``, ``configs/robot.yaml``) and this one 1.25. It is
    #: now derived by reference from the one authority instead of restated, so
    #: the family cannot drift apart again. This is a VALUE change (1.25 ->
    #: 1.2); the paired FOLLOW_BENCH_V1 evidence is in
    #: scrum/20260807/task_2/NAV_FINISH_STATUS.md.
    obstacle_slow_m: float = DEFAULT_SAFETY_ENVELOPE.obstacle_comfort_band_m
    #: Same authority as ``ReactiveSafetyPolicy``: 1.0/2.0 were restated
    #: literals that undercut ``SafetyEnvelope`` by 0.2 m / 0.5 m. Derived by
    #: reference now (1.2 / 2.5), owner-authorized 2026-08-10.
    person_stop_m: float = DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)
    person_slow_m: float = DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m
    owner_collision_envelope_m: float = _OWNER_COLLISION_ENVELOPE_M

    behind_distance_m: float = 1.9
    max_behind_distance_m: float = 3.0
    formation_deadband_m: float = 0.20
    #: DERIVED: ``person_stop_m + owner_collision_envelope_m`` (1.55 -> 1.75).
    owner_keepout_m: float = _OWNER_KEEPOUT_M
    staging_radius_m: float = 2.1
    staging_lookahead_rad: float = 0.35
    heading_min_dt_s: float = 0.05
    heading_history_gap_s: float = 0.9
    heading_stale_after_s: float = 0.8
    heading_min_displacement_m: float = 0.08
    heading_min_speed_mps: float = 0.10
    heading_max_speed_mps: float = 3.0
    heading_smoothing_alpha: float = 0.35
    heading_min_updates: int = 2
    prediction_horizon_s: float = 0.25
    prediction_max_m: float = 0.25

    def __post_init__(self) -> None:
        numeric = [
            getattr(self, item.name)
            for item in fields(self)
            if item.name != "heading_min_updates"
        ]
        if any(not math.isfinite(value) or value <= 0.0 for value in numeric):
            raise ValueError("follow configuration values must be positive and finite")
        if self.obstacle_stop_m >= self.obstacle_slow_m:
            raise ValueError("follow obstacle stop distance must be below slow distance")
        if self.person_stop_m >= self.person_slow_m:
            raise ValueError("follow person stop distance must be below slow distance")
        if self.heading_min_dt_s >= self.heading_history_gap_s:
            raise ValueError("heading minimum dt must be below the history gap")
        if self.heading_stale_after_s > self.heading_history_gap_s:
            raise ValueError("heading stale time must not exceed the history gap")
        if self.heading_min_speed_mps >= self.heading_max_speed_mps:
            raise ValueError("heading minimum speed must be below maximum speed")
        if not 0.0 < self.heading_smoothing_alpha <= 1.0:
            raise ValueError("heading smoothing alpha must be in (0, 1]")
        if self.heading_min_updates < 1:
            raise ValueError("heading_min_updates must be positive")
        minimum_keepout = self.person_stop_m + self.owner_collision_envelope_m
        if self.owner_keepout_m + 1e-9 < minimum_keepout:
            raise ValueError(
                "owner_keepout_m must include person stop distance and owner envelope"
            )
        # The defect this guard exists for: raising ``person_stop_m`` raises
        # ``owner_keepout_m``, and a follow stand-off left behind ends up INSIDE
        # its own keepout, so the controller brakes against the reactive gate it
        # shares (measured cost when this was unguarded: FOLLOW_BENCH_V1
        # follow_success 9/9 -> 6/9). Same floor the behind formation uses.
        minimum_stand_off = self.owner_keepout_m + OWNER_STAND_OFF_MARGIN_M
        if self.desired_distance_m + 1e-9 < minimum_stand_off:
            raise ValueError(
                "desired_distance_m must clear owner_keepout_m by the stand-off "
                f"margin (minimum {minimum_stand_off:.2f} m)"
            )
        if self.behind_distance_m <= self.owner_keepout_m:
            raise ValueError("behind distance must be outside the owner keepout")
        if self.max_behind_distance_m < self.behind_distance_m:
            raise ValueError("maximum behind distance must include the default distance")
        if self.staging_radius_m < self.behind_distance_m:
            raise ValueError("staging radius must be at least the behind distance")
        if self.staging_lookahead_rad >= math.pi / 2.0:
            raise ValueError("staging lookahead must be below pi/2")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> FollowConfig:
        """Load a strict optional config section without silently accepting typos."""

        allowed = {item.name for item in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown owner_follow settings: {sorted(unknown)}")
        values: dict[str, float | int] = {}
        for key, value in raw.items():
            if key == "heading_min_updates":
                if isinstance(value, bool):
                    raise TypeError("heading_min_updates must be an integer")
                converted = int(value)
                if converted != value:
                    raise ValueError("heading_min_updates must be an integer")
                values[key] = converted
            else:
                values[key] = float(value)
        return cls(**values)


@dataclass(frozen=True)
class FollowDecision:
    state: str
    command: VelocityCommand
    reason: str
    distance_m: float | None = None
    owner_id: str | None = None
    mode: str = "direct"
    owner_heading_rad: float | None = None
    target_x_m: float | None = None
    target_y_m: float | None = None
    stage_side: str | None = None
    # Anticipatory following (card W2). ``prediction_active`` says the command
    # was aimed at a lead point rather than the measured owner position;
    # ``speed_scale`` is the uncertainty brake actually applied.
    prediction_active: bool = False
    prediction_confidence: float | None = None
    lead_x_m: float | None = None
    lead_y_m: float | None = None
    speed_scale: float = 1.0
    # Yield-aside (card Y-2), additive and defaulted: a decision produced with
    # the flag off is field-for-field what it was before the card.
    yield_active: bool = False
    yield_reason: str = "idle"
    yield_side: int = 0
    yield_offset_m: float | None = None
    yield_clearance_m: float | None = None


@dataclass(frozen=True)
class _MotionEstimate:
    heading_rad: float
    speed_mps: float


@dataclass(frozen=True)
class _LeadPoint:
    """Where the owner is expected to be, and how much that is trusted."""

    x: float
    y: float
    heading_rad: float
    confidence: float


_IDLE_PREDICTION_STATE: dict[str, object] = {
    "enabled": False,
    "active": False,
    "reason": "idle",
    "confidence": None,
    "lead_x_m": None,
    "lead_y_m": None,
    "speed_scale": 1.0,
}

_IDLE_YIELD_STATE: dict[str, object] = {
    "enabled": False,
    "active": False,
    "reason": "idle",
    "side": 0,
    "offset_m": None,
    "baseline_clearance_m": None,
    "aside_clearance_m": None,
    "aim_x_m": None,
    "aim_y_m": None,
}


class FollowOwnerController:
    """Fail-closed owner-follow controller over camera/LiDAR observations.

    The legacy/default ``direct`` mode retains the original distance-following
    behavior. ``behind`` is an explicit formation mode: it derives owner heading
    from timestamped owner tracks, and it never falls back to chasing the owner
    point when that heading is unavailable.
    """

    def __init__(
        self,
        config: FollowConfig | None = None,
        *,
        safety_policy: ReactiveSafetyPolicy | None = None,
        prediction: FollowPredictionConfig | None = None,
        yield_aside: FollowYieldConfig | None = None,
    ):
        self.config = config or FollowConfig()
        self.prediction = prediction or FollowPredictionConfig()
        self.yield_aside = yield_aside or FollowYieldConfig()
        self._prediction_state: dict[str, object] = _IDLE_PREDICTION_STATE
        self._yield_state: dict[str, object] = _IDLE_YIELD_STATE
        self._yield_side = 0
        self._yield_engaged = False
        self._lock = threading.RLock()
        self._enabled = False
        self._mode = "direct"
        self._last_seen_at: float | None = None
        self._state = "idle"
        self._last_owner_id: str | None = None
        self._last_track: tuple[float, float, float] | None = None
        self._heading_anchor: tuple[float, float, float] | None = None
        self._filtered_velocity: tuple[float, float] | None = None
        self._heading_updated_at: float | None = None
        self._heading_updates = 0
        self._last_passive_seen_at: float | None = None
        self._latest_track_valid = False
        self._latest_track_status = "not_observed"
        self._stage_side: int | None = None
        self._active_behind_distance_m = self.config.behind_distance_m
        self._safety_policy = safety_policy or ReactiveSafetyPolicy(
            obstacle_stop_m=self.config.obstacle_stop_m,
            obstacle_slow_m=self.config.obstacle_slow_m,
            person_stop_m=self.config.person_stop_m,
            person_slow_m=self.config.person_slow_m,
            telemetry_stale_s=self.config.stale_after_s,
            owner_collision_envelope_m=self.config.owner_collision_envelope_m,
        )
        policy_owner_keepout = (
            self._safety_policy.person_stop_m
            + self._safety_policy.owner_collision_envelope_m
        )
        if self.config.owner_keepout_m + 1e-9 < policy_owner_keepout:
            raise ValueError(
                "owner keepout must include the supplied safety policy's person envelope"
            )
        # Built ONLY when the flag is on: the limits validate the closed-loop
        # equilibrium precondition and would be a new construction-time failure
        # mode on a path that is otherwise byte-identical to today's.
        self._yield_limits: YieldAsideLimits | None = None
        if self.yield_aside.enabled:
            self._yield_limits = YieldAsideLimits(
                desired_distance_m=self.config.desired_distance_m,
                deadband_m=self.config.distance_deadband_m,
                max_vx_mps=self.config.max_vx,
                owner_keepout_m=self.config.owner_keepout_m,
                obstacle_stop_m=self.config.obstacle_stop_m,
                person_stop_m=self.config.person_stop_m,
                person_slow_m=self.config.person_slow_m,
            )

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    def start(self, mode: str = "direct") -> None:
        if mode not in self.config.MODES:
            raise ValueError(f"unknown follow mode: {mode}")
        with self._lock:
            self._enabled = True
            self._mode = mode
            self._active_behind_distance_m = self.config.behind_distance_m
            self._last_seen_at = None
            self._state = "acquiring" if mode == "direct" else "acquiring_heading"
            self._prediction_state = _IDLE_PREDICTION_STATE
            self._yield_state = _IDLE_YIELD_STATE
            self._yield_side = 0
            self._yield_engaged = False
            # Passive camera history deliberately survives activation. A plan
            # admitted on a fresh heading must not throw that evidence away at
            # the exact moment it acquires the base resource.
            self._stage_side = None

    # Formation relation -> controller mode. "follow" is plain owner-tracking
    # (no heading estimate needed); "behind" stages on the owner's motion
    # heading. Both are reachable from the FollowFormation contract.
    FORMATION_MODES: ClassVar[dict[str, str]] = {"follow": "direct", "behind": "behind"}

    def start_formation(self, relation: str, *, distance_m: float | None = None) -> None:
        """Semantic entry point used by the ``FollowFormation`` PlanIR skill."""

        mode = self.FORMATION_MODES.get(relation)
        if mode is None:
            raise ValueError(f"unsupported owner formation relation: {relation}")
        if mode == "direct":
            # Plain follow has one standoff, owned by the controller; a
            # model-authored distance must not silently retune it.
            with self._lock:
                self.start("direct")
            return
        distance = self.config.behind_distance_m if distance_m is None else float(distance_m)
        if not math.isfinite(distance):
            raise ValueError("behind formation distance must be finite")
        minimum = self.config.owner_keepout_m + OWNER_STAND_OFF_MARGIN_M
        if not minimum <= distance <= self.config.max_behind_distance_m:
            raise ValueError(
                "behind formation distance must be between "
                f"{minimum:.2f} and {self.config.max_behind_distance_m:.2f} meters"
            )
        with self._lock:
            self.start("behind")
            self._active_behind_distance_m = distance

    def stop(self) -> None:
        with self._lock:
            self._enabled = False
            self._mode = "direct"
            self._last_seen_at = None
            self._state = "idle"
            # Cancellation removes every active path choice and guarantees the
            # next step emits no motion. Fresh passive heading history may be
            # reused by a later, separately admitted formation request.
            self._stage_side = None
            self._active_behind_distance_m = self.config.behind_distance_m
            self._prediction_state = _IDLE_PREDICTION_STATE
            self._yield_state = _IDLE_YIELD_STATE
            self._yield_side = 0
            self._yield_engaged = False

    def observe_owner(
        self,
        observation: SimObservation | None,
        now: float | None = None,
    ) -> str:
        """Passively update camera-track motion history without producing motion.

        This method is safe to call on every perception tick regardless of
        whether follow is enabled. Its return value is diagnostic only; callers
        should use :meth:`heading_available` as the formation admission gate.
        """

        current = time.monotonic() if now is None else now
        with self._lock:
            return self._observe_owner_locked(observation, current)

    def heading_available(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            return self._motion_estimate(current) is not None

    def heading_snapshot(self, now: float | None = None) -> dict[str, object]:
        """Return bounded passive heading evidence for planner admission/telemetry."""

        current = time.monotonic() if now is None else now
        with self._lock:
            estimate = self._motion_estimate(current)
            return {
                "available": estimate is not None,
                "owner_id": self._last_owner_id,
                "heading_rad": estimate.heading_rad if estimate is not None else None,
                "speed_mps": estimate.speed_mps if estimate is not None else None,
                "track_status": self._latest_track_status,
                "track_age_s": (
                    max(0.0, current - self._last_passive_seen_at)
                    if self._last_passive_seen_at is not None
                    else None
                ),
            }

    def step(
        self,
        observation: SimObservation | None,
        now: float | None = None,
        *,
        prediction: PredictedPath | None = None,
    ) -> FollowDecision:
        """Advance one tick, optionally anticipating the owner's motion.

        ``prediction`` comes from the runtime-owned ``OwnerMotionPredictor``
        fed by this same owner track. Passing ``None`` — or a path the
        configuration does not trust — reproduces the unpredicted behavior
        exactly, which is what makes the fallback safe to rely on.
        """

        with self._lock:
            return self._step_locked(observation, now, prediction)

    def _step_locked(
        self,
        observation: SimObservation | None,
        now: float | None,
        prediction: PredictedPath | None = None,
    ) -> FollowDecision:
        current = time.monotonic() if now is None else now
        zero = VelocityCommand()
        motion_status = self._observe_owner_locked(observation, current)
        lead = self._resolve_lead(prediction)
        if not self._enabled:
            self._state = "idle"
            return self._decision(zero, "follow_disabled")
        if observation is None:
            self._state = "acquiring"
            return self._decision(zero, "no_observation")
        if current - observation.timestamp > self.config.stale_after_s:
            self._state = "stale"
            return self._decision(zero, "stale_observation")

        owner = observation.owner
        if not _finite_track(observation):
            self._state = "invalid"
            return self._decision(zero, "invalid_owner_track", owner_id=owner.owner_id)
        if not owner.visible or owner.confidence < self.config.min_confidence:
            if (
                self._last_seen_at is not None
                and current - self._last_seen_at <= self.config.occlusion_grace_s
            ):
                self._state = "occluded"
                reason = "owner_temporarily_occluded"
            else:
                self._state = "lost" if self._last_seen_at is not None else "acquiring"
                reason = "owner_lost" if self._last_seen_at is not None else "owner_not_acquired"
            return self._decision(zero, reason, owner_id=owner.owner_id)

        self._last_seen_at = current
        if self._mode == "behind":
            decision = self._step_behind(observation, current, motion_status, lead)
        else:
            decision = self._step_direct(observation, lead)
        return self._braked(decision)

    def _resolve_lead(self, prediction: PredictedPath | None) -> _LeadPoint | None:
        """Turn a predicted path into a trusted lead point, or refuse it.

        The refusal reasons are recorded rather than swallowed: a deployment
        that thinks it is anticipating and is silently falling back every tick
        is the failure mode this block exists to make visible.
        """

        config = self.prediction
        state: dict[str, object] = {
            "enabled": config.enabled,
            "active": False,
            "reason": "disabled" if not config.enabled else "no_prediction",
            "confidence": None,
            "lead_x_m": None,
            "lead_y_m": None,
            "speed_scale": 1.0,
        }
        if not config.enabled or prediction is None:
            self._prediction_state = state
            return None

        confidence = float(prediction.confidence)
        state["confidence"] = confidence
        state["speed_scale"] = config.speed_scale(confidence)
        if confidence < config.min_confidence:
            # Still braked: an untrusted prediction is itself evidence that the
            # owner is doing something we cannot anticipate.
            state["reason"] = "confidence_below_threshold"
            self._prediction_state = state
            return None

        index = max(1, round(config.lead_s / prediction.step_s)) - 1
        if index >= len(prediction.points):
            state["reason"] = "lead_beyond_horizon"
            self._prediction_state = state
            return None
        x, y = prediction.points[index]
        if not (math.isfinite(x) and math.isfinite(y)):
            state["reason"] = "non_finite_prediction"
            self._prediction_state = state
            return None

        state["active"] = True
        state["reason"] = "predicted_lead_point"
        state["lead_x_m"] = x
        state["lead_y_m"] = y
        self._prediction_state = state
        return _LeadPoint(x, y, float(prediction.heading_rad), confidence)

    def _clamped_lead(
        self,
        lead: _LeadPoint | None,
        observation: SimObservation,
        standoff_m: float,
    ) -> _LeadPoint | None:
        """Limit how far ahead of the *measured* owner the aim point may sit.

        Holding ``standoff_m`` from a lead point is holding
        ``standoff_m - lead_distance`` from the owner we can actually see. Left
        uncapped that quietly trades owner clearance for anticipation, so the
        lead is clamped to whatever the mode's declared owner keepout leaves
        over. When the clamp bites it is reported, not absorbed.
        """

        if lead is None:
            return None
        owner = observation.owner
        offset_x = lead.x - owner.x
        offset_y = lead.y - owner.y
        distance = math.hypot(offset_x, offset_y)
        budget = max(0.0, standoff_m - self.config.owner_keepout_m)
        if distance <= budget + 1e-9:
            return lead
        state = dict(self._prediction_state)
        if distance <= 1e-9:
            state["reason"] = "lead_clamped_to_owner_keepout"
            state["lead_x_m"] = owner.x
            state["lead_y_m"] = owner.y
            self._prediction_state = state
            return _LeadPoint(owner.x, owner.y, lead.heading_rad, lead.confidence)
        scale = budget / distance
        clamped = _LeadPoint(
            owner.x + offset_x * scale,
            owner.y + offset_y * scale,
            lead.heading_rad,
            lead.confidence,
        )
        state["reason"] = "lead_clamped_to_owner_keepout"
        state["lead_x_m"] = clamped.x
        state["lead_y_m"] = clamped.y
        self._prediction_state = state
        return clamped

    def _yield_aim(
        self,
        observation: SimObservation,
        aim_x: float,
        aim_y: float,
    ) -> tuple[float, float]:
        """Offer the aim to the yield-aside proposer; return what direct follow chases.

        Flag OFF is the whole story for today's behaviour: the guard below is
        the first statement, nothing is computed, and the aim is returned
        unchanged — the byte-identity claim in the card's gate rests on exactly
        that. Flag ON, an ACTIVE proposal replaces the aim outright, which
        deliberately discards ``_clamped_lead``'s anticipation budget for this
        tick: that clamp polices LEAD-anticipation of a moving owner (standoff
        minus keepout, ~0.10 m), not a commanded stance rotation at constant
        owner distance. What replaces it is the proposer's unit-enforced
        equilibrium precondition plus the untouched reactive gate's owner band;
        that trade is recorded in the status doc's ``does_not_prove``.
        """

        limits = self._yield_limits
        if limits is None:
            return (aim_x, aim_y)
        owner = observation.owner
        proposal = propose_yield_aside(
            robot_xy=(observation.robot.x, observation.robot.y),
            owner_xy=(owner.x, owner.y),
            tracks=_stranger_tracks(observation),
            limits=limits,
            free_range_m=_scan_free_range(observation),
            latched_side=self._yield_side,
            engaged=self._yield_engaged,
        )
        state = {
            "enabled": True,
            "active": proposal.active,
            "reason": proposal.reason,
            "side": proposal.side,
            "offset_m": proposal.offset_m if proposal.active else None,
            "baseline_clearance_m": proposal.baseline_clearance_m,
            "aside_clearance_m": proposal.aside_clearance_m,
            "aim_x_m": proposal.aim_x_m,
            "aim_y_m": proposal.aim_y_m,
        }
        self._yield_state = state
        if not proposal.active:
            self._yield_engaged = False
            self._yield_side = 0
            return (aim_x, aim_y)
        self._yield_engaged = True
        self._yield_side = proposal.side
        return (float(proposal.aim_x_m), float(proposal.aim_y_m))

    def _braked(self, decision: FollowDecision) -> FollowDecision:
        """Apply the uncertainty brake to translation, never to the yaw.

        Scaling translation strictly reduces the command, so the brake composes
        under the reactive policy and the final collision gate rather than
        competing with them. Yaw is left alone: keeping the owner in frame is
        exactly what an uncertain follower should still be allowed to do.
        """

        scale = float(self._prediction_state.get("speed_scale", 1.0))
        state = dict(self._prediction_state)
        if scale >= 1.0 - 1e-9:
            state["speed_scale"] = 1.0
            self._prediction_state = state
            return decision
        command = decision.command
        braked = VelocityCommand(
            vx=command.vx * scale,
            vy=command.vy * scale,
            vyaw=command.vyaw,
        )
        self._prediction_state = state
        return replace(
            decision,
            command=braked,
            reason=(
                decision.reason
                if braked == command
                else f"{decision.reason}_uncertainty_braked"
            ),
            speed_scale=scale,
        )

    def _step_direct(
        self,
        observation: SimObservation,
        lead: _LeadPoint | None = None,
    ) -> FollowDecision:
        owner = observation.owner
        # The lead point *is* the owner as far as the distance law is
        # concerned: holding ``desired_distance_m`` from where the owner will
        # be in ``lead_s`` is the same control law aimed one step ahead.
        lead = self._clamped_lead(lead, observation, self.config.desired_distance_m)
        owner_x = owner.x if lead is None else lead.x
        owner_y = owner.y if lead is None else lead.y
        # Card Y-2: the yield-aside PROPOSAL, immediately after the lead clamp
        # and upstream of everything else. It replaces the aim point only; the
        # command the law derives from it still goes through the untouched
        # dispatch chain (smoother -> apply_reactive_safety -> TTC -> shaper),
        # which remains the sole runtime disposer.
        owner_x, owner_y = self._yield_aim(observation, owner_x, owner_y)
        dx = owner_x - observation.robot.x
        dy = owner_y - observation.robot.y
        distance = math.hypot(dx, dy)
        obstacle = observation.nearest_obstacle_m
        obstacle_bearing = observation.nearest_obstacle_bearing_rad
        obstacle_in_path = obstacle_bearing is None or abs(obstacle_bearing) < 1.15
        if observation.collision and obstacle_in_path:
            self._state = "blocked"
            return self._decision(
                VelocityCommand(), "collision_contact", distance, owner.owner_id
            )
        if (
            obstacle_in_path
            and obstacle is not None
            and obstacle <= self.config.obstacle_stop_m
        ):
            self._state = "blocked"
            return self._decision(VelocityCommand(), "obstacle_stop", distance, owner.owner_id)

        target_heading = math.atan2(dy, dx)
        yaw_error = _wrap_angle(target_heading - observation.robot.yaw)
        vyaw = _clamp(yaw_error * self.config.yaw_gain, self.config.max_vyaw)
        distance_error = distance - self.config.desired_distance_m
        if distance_error <= self.config.distance_deadband_m:
            self._state = "holding"
            turn = vyaw if abs(yaw_error) > 0.35 else 0.0
            return self._decision(
                VelocityCommand(vyaw=turn),
                "at_follow_distance",
                distance,
                owner.owner_id,
            )

        vx = min(self.config.max_vx, distance_error * self.config.distance_gain)
        if abs(yaw_error) >= self.config.turn_in_place_rad:
            vx = 0.0
        elif (
            obstacle_in_path
            and obstacle is not None
            and obstacle < self.config.obstacle_slow_m
        ):
            span = self.config.obstacle_slow_m - self.config.obstacle_stop_m
            scale = max(0.2, (obstacle - self.config.obstacle_stop_m) / span)
            vx *= scale
        self._state = "following"
        return self._decision(
            VelocityCommand(vx=vx, vyaw=vyaw),
            "tracking_owner",
            distance,
            owner.owner_id,
        )

    def _step_behind(
        self,
        observation: SimObservation,
        current: float,
        motion_status: str,
        lead: _LeadPoint | None = None,
    ) -> FollowDecision:
        owner = observation.owner
        owner_distance = math.hypot(
            owner.x - observation.robot.x,
            owner.y - observation.robot.y,
        )
        if observation.collision:
            self._state = "blocked"
            return self._decision(
                VelocityCommand(),
                "collision_contact",
                owner_distance,
                owner.owner_id,
            )
        if motion_status == "outlier":
            self._state = "holding"
            return self._decision(
                VelocityCommand(),
                "owner_motion_outlier",
                owner_distance,
                owner.owner_id,
            )
        estimate = self._motion_estimate(current)
        if estimate is None:
            self._state = "acquiring_heading"
            reason = (
                "owner_heading_stale"
                if self._heading_updated_at is not None
                and self._heading_updates >= self.config.heading_min_updates
                and current - self._heading_updated_at > self.config.heading_stale_after_s
                else "owner_heading_unavailable"
            )
            return self._decision(
                VelocityCommand(), reason, owner_distance, owner.owner_id
            )

        # The formation anchor moves to the predicted owner; the keepout
        # geometry below deliberately does not. A prediction may say where to
        # aim, but it may never license driving through where the owner has
        # actually been measured.
        lead = self._clamped_lead(lead, observation, self._active_behind_distance_m)
        anchor_heading_rad = estimate.heading_rad if lead is None else lead.heading_rad
        anchor_x = owner.x if lead is None else lead.x
        anchor_y = owner.y if lead is None else lead.y
        heading_x = math.cos(anchor_heading_rad)
        heading_y = math.sin(anchor_heading_rad)
        prediction = (
            min(
                self.config.prediction_max_m,
                estimate.speed_mps * self.config.prediction_horizon_s,
            )
            # The lead point already carries the lookahead; adding the legacy
            # short-horizon extrapolation on top would double-count it.
            if lead is None
            else 0.0
        )
        effective_rear_distance = max(
            self.config.owner_keepout_m + OWNER_STAND_OFF_MARGIN_M,
            self._active_behind_distance_m - prediction,
        )
        target_x = anchor_x - heading_x * effective_rear_distance
        target_y = anchor_y - heading_y * effective_rear_distance
        robot_rel = (
            observation.robot.x - owner.x,
            observation.robot.y - owner.y,
        )
        target_rel = (target_x - owner.x, target_y - owner.y)
        direct_clearance = _segment_origin_clearance(robot_rel, target_rel)

        if direct_clearance + 1e-9 < self.config.owner_keepout_m:
            target_x, target_y, reason = self._staging_target(
                observation,
                target_heading=math.atan2(target_rel[1], target_rel[0]),
            )
            state = "staging"
        else:
            self._stage_side = None
            reason = "tracking_behind_anchor"
            state = "tracking_behind"

        target_distance = math.hypot(
            target_x - observation.robot.x,
            target_y - observation.robot.y,
        )
        if state == "tracking_behind" and target_distance <= self.config.formation_deadband_m:
            yaw_error = _wrap_angle(anchor_heading_rad - observation.robot.yaw)
            turn = (
                _clamp(yaw_error * self.config.yaw_gain, self.config.max_vyaw)
                if abs(yaw_error) > 0.25
                else 0.0
            )
            self._state = "holding_behind"
            return self._decision(
                VelocityCommand(vyaw=turn),
                "behind_formation_reached",
                owner_distance,
                owner.owner_id,
                owner_heading=anchor_heading_rad,
                target=(target_x, target_y),
            )

        command = self._command_to_target(observation, target_x, target_y)
        safe_command, safety_state = apply_reactive_safety(
            command,
            observation,
            policy=self._safety_policy,
            now=current,
        )
        if safety_state == "stopped" and math.hypot(command.vx, command.vy) > 1e-6:
            self._state = "blocked"
            reason = "formation_proximity_stop"
        else:
            self._state = state
            if safety_state == "slowing":
                reason = f"{reason}_slowed"
        return self._decision(
            safe_command,
            reason,
            owner_distance,
            owner.owner_id,
            owner_heading=anchor_heading_rad,
            target=(target_x, target_y),
        )

    def _observe_owner_locked(
        self,
        observation: SimObservation | None,
        current: float,
    ) -> str:
        if observation is None:
            self._latest_track_valid = False
            self._latest_track_status = "no_observation"
            return self._latest_track_status

        owner = observation.owner
        if owner.owner_id != self._last_owner_id:
            self._reset_motion_history()
            self._last_owner_id = owner.owner_id
        if current - observation.timestamp > self.config.stale_after_s:
            self._latest_track_valid = False
            self._latest_track_status = "stale_observation"
            return self._latest_track_status
        if not _finite_track(observation):
            self._latest_track_valid = False
            self._latest_track_status = "invalid_owner_track"
            return self._latest_track_status
        if not owner.visible:
            self._latest_track_valid = False
            self._latest_track_status = "owner_not_visible"
            return self._latest_track_status
        if owner.confidence < self.config.min_confidence:
            self._latest_track_valid = False
            self._latest_track_status = "owner_low_confidence"
            return self._latest_track_status

        status = self._update_motion_estimate(observation, current)
        self._latest_track_valid = status != "outlier"
        self._latest_track_status = status
        if self._latest_track_valid:
            self._last_passive_seen_at = current
        return status

    def _update_motion_estimate(
        self,
        observation: SimObservation,
        current: float,
    ) -> str:
        owner = observation.owner
        sample = (observation.timestamp, owner.x, owner.y)
        if owner.owner_id != self._last_owner_id:
            self._reset_motion_history()
            self._last_owner_id = owner.owner_id
            self._last_track = sample
            self._heading_anchor = sample
            return "seeded"
        if self._last_track is None or self._heading_anchor is None:
            self._last_track = sample
            self._heading_anchor = sample
            return "seeded"

        last_t, last_x, last_y = self._last_track
        dt_last = sample[0] - last_t
        if dt_last <= 0.0:
            if dt_last < 0.0:
                self._reset_motion_history()
                self._last_owner_id = owner.owner_id
                self._last_track = sample
                self._heading_anchor = sample
                return "clock_reset"
            return "duplicate"
        if dt_last > self.config.heading_history_gap_s:
            self._reset_motion_history()
            self._last_owner_id = owner.owner_id
            self._last_track = sample
            self._heading_anchor = sample
            return "history_gap"

        raw_step_speed = math.hypot(sample[1] - last_x, sample[2] - last_y) / dt_last
        if raw_step_speed > self.config.heading_max_speed_mps:
            return "outlier"
        self._last_track = sample

        anchor_t, anchor_x, anchor_y = self._heading_anchor
        dt = sample[0] - anchor_t
        if dt < self.config.heading_min_dt_s:
            return "insufficient_dt"
        dx = sample[1] - anchor_x
        dy = sample[2] - anchor_y
        displacement = math.hypot(dx, dy)
        speed = displacement / dt
        if (
            displacement < self.config.heading_min_displacement_m
            or speed < self.config.heading_min_speed_mps
        ):
            return "insufficient_motion"
        if speed > self.config.heading_max_speed_mps:
            return "outlier"

        raw_vx = dx / dt
        raw_vy = dy / dt
        if self._filtered_velocity is None:
            filtered = (raw_vx, raw_vy)
        else:
            alpha = self.config.heading_smoothing_alpha
            filtered = (
                alpha * raw_vx + (1.0 - alpha) * self._filtered_velocity[0],
                alpha * raw_vy + (1.0 - alpha) * self._filtered_velocity[1],
            )
        filtered_speed = math.hypot(*filtered)
        if filtered_speed < self.config.heading_min_speed_mps:
            return "insufficient_filtered_motion"
        if filtered_speed > self.config.heading_max_speed_mps:
            scale = self.config.heading_max_speed_mps / filtered_speed
            filtered = (filtered[0] * scale, filtered[1] * scale)
        self._filtered_velocity = filtered
        self._heading_anchor = sample
        self._heading_updated_at = current
        self._heading_updates += 1
        return "updated"

    def _motion_estimate(self, current: float) -> _MotionEstimate | None:
        if (
            not self._latest_track_valid
            or self._last_passive_seen_at is None
            or current - self._last_passive_seen_at > self.config.stale_after_s
            or self._filtered_velocity is None
            or self._heading_updated_at is None
            or self._heading_updates < self.config.heading_min_updates
            or current - self._heading_updated_at > self.config.heading_stale_after_s
        ):
            return None
        vx, vy = self._filtered_velocity
        return _MotionEstimate(
            math.atan2(vy, vx),
            min(math.hypot(vx, vy), self.config.heading_max_speed_mps),
        )

    def _staging_target(
        self,
        observation: SimObservation,
        *,
        target_heading: float,
    ) -> tuple[float, float, str]:
        """Select a persistent, collision-clear polar lookahead around the owner."""

        owner = observation.owner
        rx = observation.robot.x - owner.x
        ry = observation.robot.y - owner.y
        radius = math.hypot(rx, ry)
        robot_angle = math.atan2(ry, rx)
        if self._stage_side is None:
            delta = _wrap_angle(target_heading - robot_angle)
            self._stage_side = 1 if delta > 0.0 else -1
        side = self._stage_side

        # If the owner entered the keepout, move radially away before attempting
        # a tangential transition. This path cannot move through the owner.
        if radius + 1e-9 < self.config.owner_keepout_m:
            stage_angle = robot_angle
            reason = "recovering_owner_clearance"
        else:
            directed_remaining = (
                (target_heading - robot_angle) % (2.0 * math.pi)
                if side > 0
                else (robot_angle - target_heading) % (2.0 * math.pi)
            )
            lookahead = min(self.config.staging_lookahead_rad, directed_remaining)
            stage_angle = robot_angle + side * lookahead
            reason = "staging_around_owner"

        stage_radius = max(self.config.staging_radius_m, self.config.owner_keepout_m)
        stage_rel = (
            math.cos(stage_angle) * stage_radius,
            math.sin(stage_angle) * stage_radius,
        )
        if (
            radius >= self.config.owner_keepout_m
            and _segment_origin_clearance((rx, ry), stage_rel)
            + 1e-9
            < self.config.owner_keepout_m
        ):
            # A deliberately conservative fallback for unusual custom radii or
            # lookahead settings: establish radial clearance first.
            stage_rel = (
                math.cos(robot_angle) * stage_radius,
                math.sin(robot_angle) * stage_radius,
            )
            reason = "establishing_staging_clearance"
        return owner.x + stage_rel[0], owner.y + stage_rel[1], reason

    def _command_to_target(
        self,
        observation: SimObservation,
        target_x: float,
        target_y: float,
    ) -> VelocityCommand:
        dx = target_x - observation.robot.x
        dy = target_y - observation.robot.y
        distance = math.hypot(dx, dy)
        target_heading = math.atan2(dy, dx)
        yaw_error = _wrap_angle(target_heading - observation.robot.yaw)
        vyaw = _clamp(yaw_error * self.config.yaw_gain, self.config.max_vyaw)
        if distance <= self.config.formation_deadband_m:
            return VelocityCommand(vyaw=vyaw if abs(yaw_error) > 0.25 else 0.0)
        vx = min(self.config.max_vx, distance * self.config.distance_gain)
        if abs(yaw_error) >= self.config.turn_in_place_rad:
            vx = 0.0
        return VelocityCommand(vx=vx, vyaw=vyaw)

    def _decision(
        self,
        command: VelocityCommand,
        reason: str,
        distance: float | None = None,
        owner_id: str | None = None,
        *,
        owner_heading: float | None = None,
        target: tuple[float, float] | None = None,
    ) -> FollowDecision:
        return FollowDecision(
            state=self._state,
            command=command,
            reason=reason,
            distance_m=distance,
            owner_id=owner_id,
            mode=self._mode,
            owner_heading_rad=owner_heading,
            target_x_m=target[0] if target is not None else None,
            target_y_m=target[1] if target is not None else None,
            stage_side=(
                "left" if self._stage_side == 1 else "right" if self._stage_side == -1 else None
            ),
            prediction_active=bool(self._prediction_state.get("active", False)),
            prediction_confidence=(
                None
                if self._prediction_state.get("confidence") is None
                else float(self._prediction_state["confidence"])  # type: ignore[arg-type]
            ),
            lead_x_m=(
                None
                if self._prediction_state.get("lead_x_m") is None
                else float(self._prediction_state["lead_x_m"])  # type: ignore[arg-type]
            ),
            lead_y_m=(
                None
                if self._prediction_state.get("lead_y_m") is None
                else float(self._prediction_state["lead_y_m"])  # type: ignore[arg-type]
            ),
            yield_active=bool(self._yield_state.get("active", False)),
            yield_reason=str(self._yield_state.get("reason", "idle")),
            yield_side=int(self._yield_state.get("side", 0)),  # type: ignore[arg-type]
            yield_offset_m=(
                None
                if self._yield_state.get("offset_m") is None
                else float(self._yield_state["offset_m"])  # type: ignore[arg-type]
            ),
            yield_clearance_m=(
                None
                if self._yield_state.get("aside_clearance_m") is None
                else float(self._yield_state["aside_clearance_m"])  # type: ignore[arg-type]
            ),
        )

    def _reset_motion_history(self) -> None:
        self._last_owner_id = None
        self._last_track = None
        self._heading_anchor = None
        self._filtered_velocity = None
        self._heading_updated_at = None
        self._heading_updates = 0
        self._last_passive_seen_at = None
        self._latest_track_valid = False
        self._latest_track_status = "not_observed"
        self._stage_side = None

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            estimate = self._motion_estimate(time.monotonic())
            return {
                "enabled": self._enabled,
                "state": self._state,
                "mode": self._mode,
                "desired_distance_m": (
                    self._active_behind_distance_m
                    if self._mode == "behind"
                    else self.config.desired_distance_m
                ),
                "heading_available": estimate is not None,
                "owner_heading_rad": estimate.heading_rad if estimate is not None else None,
                "owner_speed_mps": estimate.speed_mps if estimate is not None else None,
                "heading_track_status": self._latest_track_status,
                "stage_side": (
                    "left"
                    if self._stage_side == 1
                    else "right"
                    if self._stage_side == -1
                    else None
                ),
                "perception_basis": "camera_owner_track+robot_odometry+lidar",
                "prediction": dict(self._prediction_state),
                "yield_aside": dict(self._yield_state),
            }


def _stranger_tracks(observation: SimObservation) -> tuple[object, ...]:
    """The ``dynamic_agents`` set with the owner's own track removed.

    A perception stack that publishes the owner as a person track would
    otherwise have the follower yielding away from the person it is following.
    "Is this track the owner?" is answered geometrically here, by the same
    ``owner_collision_envelope_m`` the reactive gate uses to turn an owner
    CENTER distance into a surface clearance: a track inside the owner's own
    body envelope is the owner, and no stranger can be distinguished from him
    at that range anyway.
    """

    owner = observation.owner
    envelope = _OWNER_COLLISION_ENVELOPE_M
    kept: list[object] = []
    for track in observation.dynamic_agents:
        if not all(
            math.isfinite(value)
            for value in (track.x, track.y, track.vx, track.vy, track.radius_m)
        ):
            continue
        if math.hypot(track.x - owner.x, track.y - owner.y) <= envelope:
            continue
        kept.append(track)
    return tuple(kept)


def _scan_free_range(observation: SimObservation):
    """Bind the observation's planar scan into the proposer's free-range query.

    Returns ``None`` when no calibrated scan is available, which the proposer
    treats as the fail-closed ``no_scan`` exit rather than as open space.
    """

    ranges = observation.lidar_ranges
    increment = observation.lidar_angle_increment_rad
    angle_min = observation.lidar_angle_min_rad
    range_max = observation.lidar_range_max_m
    if not ranges or increment is None or angle_min is None or range_max is None:
        return None

    def free_range(bearing_rad: float, span_m: float) -> float:
        return planar_free_range(
            ranges,
            angle_min_rad=angle_min,
            angle_increment_rad=increment,
            range_max_m=range_max,
            robot_yaw_rad=observation.robot.yaw,
            bearing_rad=bearing_rad,
            span_m=span_m,
        )

    return free_range


def _finite_track(observation: SimObservation) -> bool:
    return all(
        math.isfinite(value)
        for value in (
            observation.timestamp,
            observation.owner.x,
            observation.owner.y,
            observation.owner.confidence,
            observation.robot.x,
            observation.robot.y,
            observation.robot.yaw,
        )
    )


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _segment_origin_clearance(
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Minimum distance from the owner origin to one proposed path segment."""

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.hypot(*start)
    projection = -(start[0] * dx + start[1] * dy) / length_sq
    fraction = max(0.0, min(1.0, projection))
    return math.hypot(start[0] + fraction * dx, start[1] + fraction * dy)
