"""Expressive liveness: idle breathing and conversation reaction hooks.

This is the layer that makes the dog look *alive* between commands — it
breathes, shifts its weight, glances around, orients toward the owner when
they start speaking, and holds a visible "thinking" posture across the gap
between the end of a question and the first synthesized word.

Three design rules, all load-bearing:

1. **Additive and subordinate.** Expression produces small joint *offsets*
   layered on top of whatever the pose runner, gait, or trajectory player is
   already holding (see ``PoseController.set_expression``). It never writes a
   target, never touches the SE2 velocity channel, and never cancels another
   controller. Collision avoidance, the arbiter, and E-stop always win because
   expression is not in their path at all.
2. **Gated by what the body is doing.** ``ExpressionGate.mode`` downgrades to
   head-only while navigating/following and to fully off during skills,
   proximity events, critical battery, or a latched E-stop (the ELEGNT rule:
   expression must never compete with a task the body is committed to).
3. **Clamped in exactly one place.** ``ExpressiveOffsets.clamped`` is the only
   amplitude authority, so no producer can grow a motion past what the body
   can absorb while standing.

Head yaw/pitch have no actuator on a Go2 (no articulated neck): they are
published in the runtime snapshot so the viewer can render gaze, and are
reserved for a future head mechanism. Body height/pitch do actuate.
"""

from __future__ import annotations

import math
import random
import threading
from collections import deque
from dataclasses import dataclass, replace

from parcel_robot.motion.gait import leg_ik
from parcel_robot.robot_profile import RobotProfile

# The single amplitude authority. Values are what a standing quadruped can
# absorb without disturbing its support polygon (research doc §1: ±2 cm body
# height, ±10-12 deg head pitch).
MAX_BODY_HEIGHT_M = 0.02
MAX_BODY_PITCH_RAD = math.radians(6.0)
MAX_HEAD_YAW_RAD = math.radians(40.0)
MAX_HEAD_PITCH_RAD = math.radians(12.0)
# Per-joint bound on the additive overlay, matching (and never exceeding)
# sim_ipc.MAX_EXPRESSION_OFFSET_RAD. Some morphologies (short links, deep
# stance) turn a legal body offset into a large joint delta; clamping at the
# source keeps the IPC boundary from rejecting every frame — which previously
# killed the whole expression channel in silence (2026-08-04 sprint review).
MAX_JOINT_OFFSET_RAD = 0.5

MODE_OFF = "off"
MODE_HEAD_ONLY = "head_only"
MODE_FULL = "full"


def _clamp(value: float, limit: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(-limit, min(limit, value))


def _ease(alpha: float) -> float:
    """Cosine ease-in/out over a normalized 0..1 progress."""

    clamped = max(0.0, min(1.0, alpha))
    return 0.5 - 0.5 * math.cos(math.pi * clamped)


@dataclass(frozen=True)
class ExpressiveOffsets:
    """Additive body/head offsets contributed by the expression layer."""

    body_height_m: float = 0.0
    body_pitch_rad: float = 0.0
    head_yaw_rad: float = 0.0
    head_pitch_rad: float = 0.0

    def clamped(self) -> ExpressiveOffsets:
        return ExpressiveOffsets(
            body_height_m=_clamp(self.body_height_m, MAX_BODY_HEIGHT_M),
            body_pitch_rad=_clamp(self.body_pitch_rad, MAX_BODY_PITCH_RAD),
            head_yaw_rad=_clamp(self.head_yaw_rad, MAX_HEAD_YAW_RAD),
            head_pitch_rad=_clamp(self.head_pitch_rad, MAX_HEAD_PITCH_RAD),
        )

    def scaled(self, factor: float) -> ExpressiveOffsets:
        if not math.isfinite(factor):
            raise ValueError("expression scale must be finite")
        return ExpressiveOffsets(
            body_height_m=self.body_height_m * factor,
            body_pitch_rad=self.body_pitch_rad * factor,
            head_yaw_rad=self.head_yaw_rad * factor,
            head_pitch_rad=self.head_pitch_rad * factor,
        )

    def head_only(self) -> ExpressiveOffsets:
        return replace(self, body_height_m=0.0, body_pitch_rad=0.0)

    def __add__(self, other: ExpressiveOffsets) -> ExpressiveOffsets:
        return ExpressiveOffsets(
            body_height_m=self.body_height_m + other.body_height_m,
            body_pitch_rad=self.body_pitch_rad + other.body_pitch_rad,
            head_yaw_rad=self.head_yaw_rad + other.head_yaw_rad,
            head_pitch_rad=self.head_pitch_rad + other.head_pitch_rad,
        )

    @property
    def is_zero(self) -> bool:
        return all(
            abs(value) <= 1e-9
            for value in (
                self.body_height_m,
                self.body_pitch_rad,
                self.head_yaw_rad,
                self.head_pitch_rad,
            )
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "body_height_m": round(self.body_height_m, 5),
            "body_pitch_rad": round(self.body_pitch_rad, 5),
            "head_yaw_rad": round(self.head_yaw_rad, 5),
            "head_pitch_rad": round(self.head_pitch_rad, 5),
        }


ZERO_OFFSETS = ExpressiveOffsets()


@dataclass(frozen=True)
class ExpressionGate:
    """What the body is currently committed to, and therefore how much
    expression is admissible."""

    emergency_stopped: bool = False
    proximity_clear: bool = True
    battery_critical: bool = False
    skill_active: bool = False
    navigation_active: bool = False
    follow_active: bool = False
    spatial_active: bool = False
    # Direct velocity motion (manual teleop / voice walk commands): the body
    # is committed to a gait the same as during navigation, so full-body
    # expression must yield (ELEGNT rule — sprint review found this source
    # class was the one gap in the matrix).
    teleop_active: bool = False

    @property
    def mode(self) -> str:
        if (
            self.emergency_stopped
            or self.battery_critical
            or self.skill_active
            or not self.proximity_clear
        ):
            return MODE_OFF
        if (
            self.navigation_active
            or self.follow_active
            or self.spatial_active
            or self.teleop_active
        ):
            return MODE_HEAD_ONLY
        return MODE_FULL

    def apply(self, offsets: ExpressiveOffsets) -> ExpressiveOffsets:
        mode = self.mode
        if mode == MODE_OFF:
            return ZERO_OFFSETS
        if mode == MODE_HEAD_ONLY:
            return offsets.head_only()
        return offsets


class IdleLayer:
    """Always-on liveness: breathing, weight shifts, look-arounds.

    Every stochastic decision comes from an injected ``random.Random`` so
    tests are deterministic and two runtimes with the same seed animate
    identically.
    """

    def __init__(
        self,
        *,
        breathing_hz: float = 0.25,
        breathing_amplitude_m: float = 0.004,
        gesture_interval_s: tuple[float, float] = (4.0, 8.0),
        gesture_duration_s: float = 1.6,
        rng: random.Random | None = None,
    ):
        if not 0.05 <= breathing_hz <= 2.0:
            raise ValueError("breathing rate must be between 0.05 and 2 Hz")
        if not 0.0 <= breathing_amplitude_m <= MAX_BODY_HEIGHT_M:
            raise ValueError("breathing amplitude must fit the body-height clamp")
        low, high = gesture_interval_s
        if not 0.5 <= low <= high <= 120.0:
            raise ValueError("gesture interval must be an increasing range in seconds")
        if not 0.2 <= gesture_duration_s <= 10.0:
            raise ValueError("gesture duration must be between 0.2 and 10 seconds")
        self.breathing_hz = breathing_hz
        self.breathing_amplitude_m = breathing_amplitude_m
        self.gesture_interval_s = gesture_interval_s
        self.gesture_duration_s = gesture_duration_s
        self._rng = rng if rng is not None else random.Random(20260804)
        self._epoch: float | None = None
        self._next_gesture_at: float | None = None
        self._gesture: tuple[str, float, float] | None = None  # kind, start, magnitude
        self.gestures_played = 0

    def _schedule_next(self, now: float) -> None:
        low, high = self.gesture_interval_s
        self._next_gesture_at = now + self._rng.uniform(low, high)

    def step(self, now: float, *, suppress_head: bool = False) -> ExpressiveOffsets:
        if self._epoch is None:
            self._epoch = now
            self._schedule_next(now)
        elapsed = now - self._epoch

        # Breathing runs continuously; it is the baseline signal of "alive".
        height = self.breathing_amplitude_m * math.sin(
            2.0 * math.pi * self.breathing_hz * elapsed
        )
        offsets = ExpressiveOffsets(body_height_m=height)

        if self._gesture is not None:
            kind, start, magnitude = self._gesture
            progress = (now - start) / self.gesture_duration_s
            if progress >= 1.0:
                self._gesture = None
                self._schedule_next(now)
            else:
                # One smooth there-and-back arc over the gesture duration.
                shape = math.sin(math.pi * max(0.0, min(1.0, progress)))
                if kind == "look_around":
                    if not suppress_head:
                        offsets += ExpressiveOffsets(head_yaw_rad=magnitude * shape)
                else:  # weight_shift
                    offsets += ExpressiveOffsets(body_pitch_rad=magnitude * shape)
        elif self._next_gesture_at is not None and now >= self._next_gesture_at:
            kind = "look_around" if self._rng.random() < 0.6 else "weight_shift"
            if kind == "look_around":
                magnitude = self._rng.uniform(0.25, 0.6) * self._rng.choice((-1.0, 1.0))
            else:
                magnitude = self._rng.uniform(0.3, 0.7) * MAX_BODY_PITCH_RAD
                magnitude *= self._rng.choice((-1.0, 1.0))
            self._gesture = (kind, now, magnitude)
            self.gestures_played += 1

        return offsets

    def reset(self) -> None:
        self._epoch = None
        self._next_gesture_at = None
        self._gesture = None


class ReactionHooks:
    """Conversation-driven reactions: orient to speech, hold a thinking pose.

    Each reaction is a small state machine with an explicit duration and
    cosine easing, so a reaction is always visibly *arriving* rather than
    snapping. Reactions own the head channels while active; the idle layer
    yields them (``suppress_head``) so the two never fight.
    """

    ORIENT_RISE_S = 0.30
    THINKING_RISE_S = 0.25
    RELEASE_S = 0.35
    THINKING_HEAD_PITCH_RAD = math.radians(8.0)
    THINKING_BODY_HEIGHT_M = -0.006

    def __init__(self) -> None:
        self._orient_started_at: float | None = None
        self._orient_target_rad = 0.0
        self._orient_released_at: float | None = None
        self._orient_release_from = 0.0
        self._thinking_started_at: float | None = None
        self._thinking_released_at: float | None = None
        self._thinking_release_scale = 0.0
        self.orients_triggered = 0
        self.thinking_holds = 0

    @property
    def active(self) -> bool:
        return any(
            value is not None
            for value in (
                self._orient_started_at,
                self._orient_released_at,
                self._thinking_started_at,
                self._thinking_released_at,
            )
        )

    def on_speech_start(self, now: float, owner_bearing_rad: float = 0.0) -> None:
        """Owner began speaking: turn to look at them."""

        if not math.isfinite(owner_bearing_rad):
            owner_bearing_rad = 0.0
        self._orient_target_rad = _clamp(owner_bearing_rad, MAX_HEAD_YAW_RAD)
        self._orient_started_at = now
        self._orient_released_at = None
        self.orients_triggered += 1

    def on_speech_end(self, now: float) -> None:
        if self._orient_started_at is not None:
            self._orient_release_from = self._orient_value(now)
            self._orient_started_at = None
            self._orient_released_at = now

    def on_turn_pending(self, now: float) -> None:
        """A turn was submitted and the reply has not started: think visibly."""

        if self._thinking_started_at is None:
            self._thinking_started_at = now
            self._thinking_released_at = None
            self.thinking_holds += 1

    def on_reply_started(self, now: float) -> None:
        """First synthesized audio: drop the thinking pose."""

        if self._thinking_started_at is not None:
            self._thinking_release_scale = self._thinking_scale(now)
            self._thinking_started_at = None
            self._thinking_released_at = now

    def _orient_value(self, now: float) -> float:
        if self._orient_started_at is not None:
            alpha = (now - self._orient_started_at) / self.ORIENT_RISE_S
            return self._orient_target_rad * _ease(alpha)
        if self._orient_released_at is not None:
            alpha = (now - self._orient_released_at) / self.RELEASE_S
            if alpha >= 1.0:
                self._orient_released_at = None
                return 0.0
            return self._orient_release_from * (1.0 - _ease(alpha))
        return 0.0

    def _thinking_scale(self, now: float) -> float:
        if self._thinking_started_at is not None:
            alpha = (now - self._thinking_started_at) / self.THINKING_RISE_S
            return _ease(alpha)
        if self._thinking_released_at is not None:
            alpha = (now - self._thinking_released_at) / self.RELEASE_S
            if alpha >= 1.0:
                self._thinking_released_at = None
                return 0.0
            return self._thinking_release_scale * (1.0 - _ease(alpha))
        return 0.0

    def step(self, now: float) -> ExpressiveOffsets:
        yaw = self._orient_value(now)
        thinking = self._thinking_scale(now)
        return ExpressiveOffsets(
            body_height_m=self.THINKING_BODY_HEIGHT_M * thinking,
            head_yaw_rad=yaw,
            head_pitch_rad=self.THINKING_HEAD_PITCH_RAD * thinking,
        )

    def reset(self) -> None:
        self._orient_started_at = None
        self._orient_released_at = None
        self._thinking_started_at = None
        self._thinking_released_at = None


@dataclass(frozen=True)
class ScheduledNod:
    apex_s: float
    amplitude_rad: float
    rise_s: float
    fall_s: float

    def value(self, now: float) -> float:
        """Raised-cosine nod centred on the apex (0 outside its window)."""

        if now <= self.apex_s - self.rise_s or now >= self.apex_s + self.fall_s:
            return 0.0
        if now <= self.apex_s:
            phase = (now - (self.apex_s - self.rise_s)) / self.rise_s
        else:
            phase = 1.0 - (now - self.apex_s) / self.fall_s
        return self.amplitude_rad * _ease(phase)


class BeatLayer:
    """Head nods scheduled against the *audio playback* clock.

    The prosody analyzer runs before a chunk is played, so the schedule is
    known ahead of time — the lookahead a live-reactive system structurally
    cannot have. Nods are armed when playback of their chunk actually starts
    and are tagged with the speech epoch, so a barge-in drops every pending
    nod along with the audio it belonged to.
    """

    # Nodding is a downward dip of the head; positive pitch is down here.
    BASE_AMPLITUDE_RAD = math.radians(7.0)

    def __init__(
        self,
        *,
        base_amplitude_rad: float = BASE_AMPLITUDE_RAD,
        rise_s: float = 0.12,
        fall_s: float = 0.18,
        lag_compensation_s: float = 0.0,
        max_pending: int = 128,
    ):
        if not 0.0 <= base_amplitude_rad <= MAX_HEAD_PITCH_RAD:
            raise ValueError("nod amplitude must fit the head-pitch clamp")
        if rise_s <= 0.0 or fall_s <= 0.0:
            raise ValueError("nod rise and fall must be positive")
        if not -0.5 <= lag_compensation_s <= 0.5:
            raise ValueError("lag compensation must be within +/-0.5 s")
        if max_pending < 1:
            raise ValueError("max pending nods must be positive")
        self.base_amplitude_rad = base_amplitude_rad
        self.rise_s = rise_s
        self.fall_s = fall_s
        self.lag_compensation_s = lag_compensation_s
        self.max_pending = max_pending
        # arm() runs on the speaker-sink worker, step() on the expression
        # thread, clear()/supersede on voice threads, stats on HTTP readers.
        # Without the lock, an arm() racing step()'s list rebuild loses nods
        # (2026-08-04 sprint review).
        self._lock = threading.Lock()
        self._nods: list[ScheduledNod] = []
        self._epoch = 0
        self._pending_apexes: list[float] = []
        self._last_step_s: float | None = None
        self.nods_scheduled = 0
        self.nods_delivered = 0
        # Bounded: one entry per delivered nod would otherwise grow for the
        # lifetime of the process; recent history is all the stats need.
        self.apex_errors_s: deque[float] = deque(maxlen=512)

    @property
    def active(self) -> bool:
        return bool(self._nods)

    def arm(self, track, *, playback_start_s: float, epoch: int) -> int:
        """Schedule nods for one synthesized chunk that is starting to play.

        ``track`` is a ``prosody.BeatTrack``; only its accents and arousal are
        read, so the DSP module stays an unimported implementation detail.
        """

        with self._lock:
            if epoch != self._epoch:
                self._nods.clear()
                self._pending_apexes.clear()
                self._epoch = epoch
            accents = getattr(track, "accents", ())
            if not accents:
                return 0
            arousal = float(getattr(track, "arousal", 0.0))
            # Quiet speech still nods, loud speech nods harder, but never past
            # the single amplitude authority.
            gain = 0.6 + 0.6 * max(0.0, min(1.0, arousal))
            scheduled = 0
            for accent in accents:
                if len(self._nods) >= self.max_pending:
                    break
                apex = playback_start_s + float(accent.time_s) - self.lag_compensation_s
                amplitude = self.base_amplitude_rad * gain * float(accent.strength)
                self._nods.append(
                    ScheduledNod(
                        apex_s=apex,
                        amplitude_rad=min(amplitude, MAX_HEAD_PITCH_RAD),
                        rise_s=self.rise_s,
                        fall_s=self.fall_s,
                    )
                )
                self._pending_apexes.append(apex)
                scheduled += 1
            self.nods_scheduled += scheduled
            return scheduled

    def clear(self) -> None:
        with self._lock:
            self._nods.clear()
            self._pending_apexes.clear()

    def step(self, now: float, *, epoch: int) -> ExpressiveOffsets:
        with self._lock:
            if epoch != self._epoch:
                # The audio these nods belonged to was superseded.
                self._nods.clear()
                self._pending_apexes.clear()
                self._epoch = epoch
                self._last_step_s = now
                return ZERO_OFFSETS
            if not self._nods:
                self._last_step_s = now
                return ZERO_OFFSETS

            # Apex-delivery error: the sampling grid cannot land exactly on
            # an apex, so record the nearest sample's distance from it.
            previous = self._last_step_s
            remaining_apexes: list[float] = []
            for apex in self._pending_apexes:
                if now >= apex:
                    here = now - apex
                    there = abs(apex - previous) if previous is not None else here
                    self.apex_errors_s.append(min(here, there))
                    self.nods_delivered += 1
                else:
                    remaining_apexes.append(apex)
            self._pending_apexes = remaining_apexes

            pitch = 0.0
            live: list[ScheduledNod] = []
            for nod in self._nods:
                if now >= nod.apex_s + nod.fall_s:
                    continue
                live.append(nod)
                pitch += nod.value(now)
            self._nods = live
            self._last_step_s = now
            return ExpressiveOffsets(head_pitch_rad=pitch)

    def apex_error_stats(self) -> dict[str, float]:
        with self._lock:
            ordered = sorted(self.apex_errors_s)
        if not ordered:
            return {"count": 0, "p50_ms": 0.0, "p95_ms": 0.0}

        def percentile(fraction: float) -> float:
            index = min(len(ordered) - 1, int(fraction * len(ordered)))
            return ordered[index] * 1000.0

        return {
            "count": len(ordered),
            "p50_ms": round(percentile(0.5), 2),
            "p95_ms": round(percentile(0.95), 2),
        }


def stance_joint_offsets(
    profile: RobotProfile, offsets: ExpressiveOffsets
) -> dict[str, float]:
    """Map body height/pitch offsets to additive per-joint deltas.

    Deltas are differences of the profile's own leg IK about the neutral
    stance, so a robot with different link lengths produces different joint
    numbers for the same body motion. Front legs are identified by a leading
    ``F`` in the leg prefix (falling back to the first half of the leg list),
    which is what makes a pitch offset raise the chest and drop the hips.
    """

    if offsets.body_height_m == 0.0 and offsets.body_pitch_rad == 0.0:
        return {}
    legs = profile.leg_prefixes
    front = {leg for leg in legs if leg.upper().startswith("F")}
    if not front or len(front) == len(legs):
        front = set(legs[: max(1, len(legs) // 2)])
    # Pitch is expressed as a height differential across the body; half the
    # footprint diameter is the effective lever arm between front and rear.
    pitch_height = math.tan(offsets.body_pitch_rad) * profile.footprint_radius_m
    base_thigh, base_calf = leg_ik(profile, 0.0, profile.stance_z_m)
    joint_offsets: dict[str, float] = {}
    for leg in legs:
        lift = offsets.body_height_m + (pitch_height if leg in front else -pitch_height)
        # A taller body means the foot sits farther below the hip.
        thigh, calf = leg_ik(profile, 0.0, profile.stance_z_m - lift)
        joint_offsets[profile.joint_name(leg, 1)] = _clamp(
            thigh - base_thigh, MAX_JOINT_OFFSET_RAD
        )
        joint_offsets[profile.joint_name(leg, 2)] = _clamp(
            calf - base_calf, MAX_JOINT_OFFSET_RAD
        )
    return joint_offsets


class ExpressionEngine:
    """Composes the expression producers into one clamped, gated result."""

    def __init__(
        self,
        profile: RobotProfile,
        *,
        idle: IdleLayer | None = None,
        reactions: ReactionHooks | None = None,
        beats: BeatLayer | None = None,
        enabled: bool = True,
    ):
        self.profile = profile
        self.idle = idle if idle is not None else IdleLayer()
        self.reactions = reactions if reactions is not None else ReactionHooks()
        self.beats = beats if beats is not None else BeatLayer()
        self.enabled = enabled
        self.offsets = ZERO_OFFSETS
        self.mode = MODE_OFF
        self.producer = "none"
        self.speech_epoch = 0

    def supersede_speech(self) -> None:
        """Barge-in/interrupt: drop every nod scheduled for cancelled audio."""

        self.speech_epoch += 1
        self.beats.clear()

    def step(self, now: float, gate: ExpressionGate) -> ExpressiveOffsets:
        if not self.enabled:
            self.offsets = ZERO_OFFSETS
            self.mode = MODE_OFF
            self.producer = "disabled"
            return self.offsets
        mode = gate.mode
        if mode == MODE_OFF:
            # Keep the phase running so expression resumes mid-breath rather
            # than snapping back to the start when the body frees up.
            self.idle.step(now, suppress_head=True)
            self.beats.clear()
            self.offsets = ZERO_OFFSETS
            self.mode = mode
            self.producer = "gated"
            return self.offsets
        beat = self.beats.step(now, epoch=self.speech_epoch)
        beating = not beat.is_zero
        reacting = self.reactions.active
        combined = (
            self.idle.step(now, suppress_head=reacting or beating)
            + self.reactions.step(now)
            + beat
        )
        self.offsets = gate.apply(combined).clamped()
        self.mode = mode
        if beating:
            self.producer = "beat"
        elif reacting:
            self.producer = "reaction"
        else:
            self.producer = "idle"
        return self.offsets

    def joint_offsets(self) -> dict[str, float]:
        return stance_joint_offsets(self.profile, self.offsets)

    def snapshot(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "producer": self.producer,
            "offsets": self.offsets.as_dict(),
            "gestures_played": self.idle.gestures_played,
            "orients_triggered": self.reactions.orients_triggered,
            "thinking_holds": self.reactions.thinking_holds,
            "nods_scheduled": self.beats.nods_scheduled,
            "nods_delivered": self.beats.nods_delivered,
            "apex_error": self.beats.apex_error_stats(),
        }
