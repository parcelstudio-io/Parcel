"""BodyIntentV1 — one body-neutral intent stream, and what a body can do with it.

Today a stationary dog is the *absence* of a command: ``_dispatch_active``
emits while an intent is live, sends one ``stop("intent_expired")`` when it
lapses, and then says nothing at all.  Expression breathes on its own 50 Hz
thread, publishes only on change, and actuates in MuJoCo only.  There is no
single artifact that says "this is what the body is doing right now", so a
second body cannot be driven from the same brain and a HOLD cannot be
distinguished from a dropped link.

``BodyIntentV1`` is that artifact.  It is emitted every tick, HOLD included,
and it carries exactly what a quadruped body can be asked for above the
locomotion boundary: where the base is going (or an explicit
:data:`HOLD`), how the trunk is offset, where the head is looking, where the
breath is in its cycle, and a style hint.

Three rules make it safe to hand to any body:

1.  **It is BELOW the safety chain on the locomotion axis.**  ``locomotion``
    carries a velocity that ``finalize_command`` has already produced; nothing
    here may originate, scale, or resurrect one.  The type has no arithmetic.
2.  **A body says what it has; it is never assumed.**
    :class:`BodyCapabilityManifest` is that declaration, and
    :func:`degrade` is the only sanctioned way to fit an intent to a body.
3.  **Degrading may only ever remove motion.**  Every axis of the result is
    weaker than or equal to its input, HOLD never becomes a velocity, and a
    zero never becomes a nonzero — see :func:`is_no_stronger_than`, which is
    the property the capability test asserts over random intents.

Pure dataclasses: no I/O, no runtime, no vendor SDK.  Adapters live with their
body (``simulation/body_adapter.py``, ``control/go2_sport_body_adapter.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

SCHEMA_VERSION = 1

#: Gait/affect hint.  Advisory: a body that has one gait ignores it.
BODY_STYLES = frozenset({"calm", "alert", "playful"})

#: Axis names used by :attr:`BodyCapabilityManifest.max_rates`.
RATE_AXES = frozenset({"posture_dz", "posture_pitch", "posture_roll", "gaze_yaw", "gaze_pitch"})


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class Velocity:
    """A body-frame SE(2) velocity that some authority above has FINALIZED.

    Deliberately not ``models.VelocityCommand``: this package may not depend on
    the command path, and the distinction keeps "a velocity the safety chain
    produced" from being confused with "a velocity a behaviour would like".
    Adapters convert at their own boundary and the conversion is exact.
    """

    vx: float = 0.0
    vy: float = 0.0
    vyaw: float = 0.0

    def __post_init__(self) -> None:
        for name in ("vx", "vy", "vyaw"):
            _finite(getattr(self, name), f"velocity {name}")

    @property
    def is_zero(self) -> bool:
        return self.vx == 0.0 and self.vy == 0.0 and self.vyaw == 0.0

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.vx, self.vy, self.vyaw)


@dataclass(frozen=True, slots=True)
class Hold:
    """An explicit "stand still" — a COMMAND, not the absence of one.

    The whole point of the stream: a body that receives HOLD every tick can
    tell "stay" from "the link died", and a watchdog can tell both from
    "nothing was ever sent".
    """

    def as_tuple(self) -> tuple[float, float, float]:
        return (0.0, 0.0, 0.0)


#: The single HOLD value.  Compare with ``is``; it carries no state.
HOLD = Hold()

Locomotion = Velocity | Hold


@dataclass(frozen=True, slots=True)
class BodyIntentV1:
    """One tick of whole-body intent, emitted continuously at 20-50 Hz."""

    stamp_ns: int
    epoch: int
    seq: int
    ttl_ms: int
    locomotion: Locomotion
    posture: tuple[float, float, float] = (0.0, 0.0, 0.0)
    gaze: tuple[float, float] = (0.0, 0.0)
    breathing_phase: float = 0.0
    style: str = "calm"
    source: str = "body_composer"
    priority: int = 0

    def __post_init__(self) -> None:
        for name in ("stamp_ns", "epoch", "seq", "ttl_ms", "priority"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"body intent {name} must be an integer")
        if self.stamp_ns < 0 or self.epoch < 0 or self.seq < 0:
            raise ValueError("body intent stamp/epoch/seq must be non-negative")
        if not 1 <= self.ttl_ms <= 5_000:
            raise ValueError("body intent ttl_ms must be between 1 and 5000")
        if not 0 <= self.priority <= 100:
            raise ValueError("body intent priority must be between 0 and 100")
        if not isinstance(self.locomotion, (Velocity, Hold)):
            raise TypeError("body intent locomotion must be a Velocity or HOLD")
        if not isinstance(self.posture, tuple) or len(self.posture) != 3:
            raise ValueError("body intent posture must be (dz, pitch, roll)")
        if not isinstance(self.gaze, tuple) or len(self.gaze) != 2:
            raise ValueError("body intent gaze must be (yaw, pitch)")
        for index, value in enumerate(self.posture):
            _finite(value, f"body intent posture[{index}]")
        for index, value in enumerate(self.gaze):
            _finite(value, f"body intent gaze[{index}]")
        phase = _finite(self.breathing_phase, "body intent breathing_phase")
        if not 0.0 <= phase < 1.0:
            raise ValueError("body intent breathing_phase must be in [0, 1)")
        if self.style not in BODY_STYLES:
            raise ValueError(f"unsupported body style: {self.style!r}")
        if not self.source or len(self.source) > 80:
            raise ValueError("body intent source must be a short non-empty string")

    @property
    def is_hold(self) -> bool:
        return isinstance(self.locomotion, Hold)

    @property
    def velocity(self) -> Velocity | None:
        """The finalized velocity, or ``None`` when this tick is a HOLD."""

        return self.locomotion if isinstance(self.locomotion, Velocity) else None

    def expired(self, now_ns: int) -> bool:
        return now_ns - self.stamp_ns > self.ttl_ms * 1_000_000

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stamp_ns": self.stamp_ns,
            "epoch": self.epoch,
            "seq": self.seq,
            "ttl_ms": self.ttl_ms,
            "hold": self.is_hold,
            "locomotion": list(self.locomotion.as_tuple()),
            "posture": list(self.posture),
            "gaze": list(self.gaze),
            "breathing_phase": self.breathing_phase,
            "style": self.style,
            "source": self.source,
            "priority": self.priority,
        }


@dataclass(frozen=True, slots=True)
class BodyCapabilityManifest:
    """What one body can actually be asked for.

    ``max_rates`` is a tuple of ``(axis, max_rate_per_second)`` pairs rather
    than a mapping so the manifest stays frozen and hashable — the same shape
    ``RobotMotionState.vendor_extra`` uses.  It is ADVISORY to the composer
    (which owns the limiter) and INFORMATIVE to an adapter that wants to check
    what it is being handed; :func:`degrade` never reads it, because rate
    limiting is shaping and this function only ever drops.
    """

    name: str
    locomotion_velocity: bool = True
    hold_is_command: bool = True
    posture_offsets: bool = True
    gaze_yaw: bool = True
    gaze_pitch: bool = True
    gestures: tuple[str, ...] = ()
    max_rates: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        if not self.name or len(self.name) > 80:
            raise ValueError("manifest name must be a short non-empty string")
        for flag in (
            "locomotion_velocity",
            "hold_is_command",
            "posture_offsets",
            "gaze_yaw",
            "gaze_pitch",
        ):
            if not isinstance(getattr(self, flag), bool):
                raise TypeError(f"manifest {flag} must be a boolean")
        if not isinstance(self.gestures, tuple) or any(
            not isinstance(name, str) or not name for name in self.gestures
        ):
            raise TypeError("manifest gestures must be a tuple of non-empty strings")
        if not isinstance(self.max_rates, tuple):
            raise TypeError("manifest max_rates must be a tuple of (axis, rate) pairs")
        seen: set[str] = set()
        for pair in self.max_rates:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise TypeError("manifest max_rates entries must be (axis, rate) pairs")
            axis, rate = pair
            if axis not in RATE_AXES:
                raise ValueError(f"unknown manifest rate axis: {axis!r}")
            if axis in seen:
                raise ValueError(f"duplicate manifest rate axis: {axis!r}")
            seen.add(axis)
            value = _finite(rate, f"manifest max_rates[{axis}]")
            if value <= 0.0:
                raise ValueError("manifest rates must be positive")

    def rate(self, axis: str, default: float | None = None) -> float | None:
        for name, value in self.max_rates:
            if name == axis:
                return value
        return default

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "locomotion_velocity": self.locomotion_velocity,
            "hold_is_command": self.hold_is_command,
            "posture_offsets": self.posture_offsets,
            "gaze_yaw": self.gaze_yaw,
            "gaze_pitch": self.gaze_pitch,
            "gestures": list(self.gestures),
            "max_rates": [list(pair) for pair in self.max_rates],
        }


def degrade(intent: BodyIntentV1, manifest: BodyCapabilityManifest) -> BodyIntentV1:
    """Fit ``intent`` to ``manifest`` by REMOVING what the body cannot do.

    The one invariant, checked by ``tests/test_h4_body_intent.py`` over random
    intents and random manifests: the result is never stronger than the input
    on any axis (:func:`is_no_stronger_than`).  In particular a body without a
    velocity channel is given :data:`HOLD` — standing still is the only safe
    reading of "cannot go" — and a HOLD is never turned back into a velocity,
    whatever the manifest says.

    ``hold_is_command`` is not consulted here: it tells the ADAPTER whether the
    body needs an explicit stop on the wire or holds by silence.  The intent
    stream carries HOLD either way, which is the entire point of the stream.
    """

    if not isinstance(intent, BodyIntentV1):
        raise TypeError("degrade expects a BodyIntentV1")
    if not isinstance(manifest, BodyCapabilityManifest):
        raise TypeError("degrade expects a BodyCapabilityManifest")

    locomotion: Locomotion = intent.locomotion
    if not manifest.locomotion_velocity and isinstance(locomotion, Velocity):
        locomotion = HOLD

    posture = intent.posture if manifest.posture_offsets else (0.0, 0.0, 0.0)
    gaze = (
        intent.gaze[0] if manifest.gaze_yaw else 0.0,
        intent.gaze[1] if manifest.gaze_pitch else 0.0,
    )
    return replace(intent, locomotion=locomotion, posture=posture, gaze=gaze)


def dropped_axes(intent: BodyIntentV1, manifest: BodyCapabilityManifest) -> tuple[str, ...]:
    """The named axes :func:`degrade` would zero for ``manifest`` — for logs.

    Only axes that were actually carrying something are named, so a body with
    no neck does not report "gaze_yaw dropped" on every tick it was not
    looking anywhere.
    """

    dropped: list[str] = []
    locomotion = intent.locomotion
    if (
        not manifest.locomotion_velocity
        and isinstance(locomotion, Velocity)
        and not locomotion.is_zero
    ):
        dropped.append("locomotion")
    if not manifest.posture_offsets and any(value != 0.0 for value in intent.posture):
        dropped.append("posture")
    if not manifest.gaze_yaw and intent.gaze[0] != 0.0:
        dropped.append("gaze_yaw")
    if not manifest.gaze_pitch and intent.gaze[1] != 0.0:
        dropped.append("gaze_pitch")
    return tuple(dropped)


def is_no_stronger_than(candidate: BodyIntentV1, reference: BodyIntentV1) -> bool:
    """True when ``candidate`` asks the body for no more motion than ``reference``.

    Axis-wise: HOLD may replace a velocity but never the reverse; every
    velocity, posture and gaze component keeps its sign and does not grow in
    magnitude.  This is the machine-checkable reading of "degrade never invents
    motion", and it is what makes a manifest safe to trust from an adapter that
    was written by somebody else.
    """

    reference_velocity = reference.velocity
    candidate_velocity = candidate.velocity
    if candidate_velocity is not None:
        if reference_velocity is None:
            return False
        for value, bound in zip(candidate_velocity.as_tuple(), reference_velocity.as_tuple()):
            if not _weaker(value, bound):
                return False
    for value, bound in zip(candidate.posture, reference.posture):
        if not _weaker(value, bound):
            return False
    for value, bound in zip(candidate.gaze, reference.gaze):
        if not _weaker(value, bound):
            return False
    return True


def _weaker(value: float, bound: float) -> bool:
    """``value`` is ``bound`` with motion removed: same sign, no larger."""

    if value == 0.0:
        return True
    if value * bound < 0.0:
        return False
    return abs(value) <= abs(bound)
