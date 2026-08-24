"""The composer that is always emitting: one ``BodyIntentV1`` per tick.

What this is, in one line: the place where the FINALIZED body velocity and the
clamped expressive offsets become a single continuous artifact, so that a
stationary dog is a *command* (:data:`~parcel_robot.contracts.body_intent.HOLD`)
rather than silence, and so that a second body can be driven from the same
brain through a capability manifest instead of a 12-DoF joint table.

Four load-bearing rules:

1.  **It consumes a velocity; it never produces one.**  ``compose`` takes the
    command the arbiter / smoother / collision gate / shaper / ``finalize_command``
    chain already agreed on, and copies it.  There is no arithmetic on the
    locomotion axis anywhere in this module.  ``None`` in means HOLD out: the
    absence of an authorized velocity can only ever mean "stand still".
2.  **It always emits.**  Every call returns an intent — breathing, holding,
    e-stopped, or walking.  A consumer can therefore treat a missing intent as
    a fault instead of as a hold.
3.  **Amplitude authority stays where it is.**  Posture and gaze come in as
    ``ExpressiveOffsets`` and go out through ``ExpressiveOffsets.clamped()``,
    which remains the single amplitude authority.  This module adds a *rate*
    authority underneath it and takes no amplitude authority away — it treats
    the amplitude envelope as a wall to decelerate into rather than a value to
    clip at, so the clamp above it stays a belt and never has to bind.
4.  **The rate authority is a LIMITER, not a tracker.**  Posture and gaze pass
    through :class:`_JerkLimitedAxes` unchanged whenever the signal already
    satisfies the axis's rate / acceleration / jerk bounds, and are limited
    only when it does not.  That distinction is the whole design: a tracker
    lags and rings, which would smear a beat nod (``BeatLayer`` holds a
    measured apex-error property) and would push the amplitude clamp into
    clipping — and a clip is a step, the one thing a jerk bound cannot
    survive.  The limiter's arithmetic makes the bound exact rather than
    approximate: the emitted third difference divided by ``dt³`` IS the
    per-tick jerk it clamped, which is what row B3 measures.

The one declared bypass is a stop: ``compose(..., emergency=True)`` snaps the
rate AND the offset to zero in the same tick, exactly as ``ExpressionGate``
mode ``off`` already clears the overlay on an e-stop, and for the same reason
``SCurveVelocityShaper.step(emergency=True)`` gives on the velocity axis
("accel/jerk limits are intentionally ignored: the next command is exact zero
on every axis").  A stop is never delayed by a limiter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from parcel_robot.contracts.body_intent import (
    HOLD,
    BodyIntentV1,
    Locomotion,
    Velocity,
)
from parcel_robot.motion.expression import (
    MAX_BODY_HEIGHT_M,
    MAX_BODY_PITCH_RAD,
    MAX_HEAD_PITCH_RAD,
    MAX_HEAD_YAW_RAD,
    ExpressiveOffsets,
)

#: Composer tick band.  Below 20 Hz a consumer cannot tell a slow tick from a
#: dropped one at a 100 ms TTL; above 50 Hz nothing downstream can use it.
MIN_TICK_HZ = 20.0
MAX_TICK_HZ = 50.0

#: Discretization margin on the catch-up braking cap: the cap is otherwise
#: exactly marginal and one tick of rounding becomes an overshoot.
BRAKE_MARGIN = 0.95


@dataclass(frozen=True)
class AxisRate:
    """Rate authority for one posture/gaze axis.

    ``max_rate`` bounds the offset's first derivative, ``max_accel`` its
    second, ``max_jerk`` its third.  They are a LIMIT, not a target: a signal
    that already respects all three reaches the body untouched.
    """

    max_rate: float
    max_accel: float
    max_jerk: float

    def __post_init__(self) -> None:
        values = (self.max_rate, self.max_accel, self.max_jerk)
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            raise ValueError("axis rate limits must be positive and finite")


@dataclass(frozen=True)
class ComposerLimits:
    """The five rate-authority axes: three posture, two gaze.

    The defaults are calibrated from the expression engine's own raw signal,
    measured at 50 Hz over 10 minutes: breathing needs 0.044 m/s, a weight
    shift 0.14 rad/s, an orient ease 3.1 rad/s, a full beat nod 2.7 rad/s with
    71 rad/s² and 1.9 krad/s³.  Each axis is set just above its own producer's
    demand, so authored motion passes through untouched and the limiter binds
    on exactly one thing: the STEP discontinuities the raw stream contains
    where one producer hands the head channel to another (measured peak 28.9
    rad/s of head yaw — a 0.58 rad jump inside one 20 ms tick).  Those are
    invisible today because head yaw actuates nowhere; they are a step command
    to the first body that has a neck.

    ``max_jerk`` is set at ``max_accel / 0.02 s`` on every axis: at a 50 Hz
    command rate the tightest jerk a discrete limiter can honour is one full
    acceleration step per tick, so a bound below that could only be met by
    refusing to use the acceleration authority above it.  Rate and
    acceleration are the physically meaningful bounds here; the jerk bound is
    the discretization floor, and row B3 reports all three.
    """

    posture_dz: AxisRate = AxisRate(max_rate=0.10, max_accel=2.0, max_jerk=100.0)
    posture_pitch: AxisRate = AxisRate(max_rate=0.50, max_accel=10.0, max_jerk=500.0)
    posture_roll: AxisRate = AxisRate(max_rate=0.50, max_accel=10.0, max_jerk=500.0)
    gaze_yaw: AxisRate = AxisRate(max_rate=4.0, max_accel=80.0, max_jerk=4000.0)
    gaze_pitch: AxisRate = AxisRate(max_rate=4.0, max_accel=100.0, max_jerk=5000.0)

    def as_max_rates(self) -> tuple[tuple[str, float], ...]:
        """The manifest-shaped view of these bounds."""

        return (
            ("posture_dz", self.posture_dz.max_rate),
            ("posture_pitch", self.posture_pitch.max_rate),
            ("posture_roll", self.posture_roll.max_rate),
            ("gaze_yaw", self.gaze_yaw.max_rate),
            ("gaze_pitch", self.gaze_pitch.max_rate),
        )

    def jerk_bounds(self) -> dict[str, float]:
        """The declared third-derivative bound per axis (row B3's criterion)."""

        return {
            "posture_dz": self.posture_dz.max_jerk,
            "posture_pitch": self.posture_pitch.max_jerk,
            "posture_roll": self.posture_roll.max_jerk,
            "gaze_yaw": self.gaze_yaw.max_jerk,
            "gaze_pitch": self.gaze_pitch.max_jerk,
        }


DEFAULT_LIMITS = ComposerLimits()


def _braking_rate(axis: AxisRate, error: float, dt_s: float) -> float:
    """The fastest rate from which ``error`` is still enough room to stop.

    Not the textbook ``sqrt(2·a·e)``: this axis cannot reverse its acceleration
    instantly either, so the answer pays for the ``max_accel/max_jerk``
    reversal plus one tick of travel first — solve ``r²/(2a) + r·τ = e``.
    """

    tau = axis.max_accel / axis.max_jerk + dt_s
    reach = axis.max_accel * tau
    root = math.sqrt(reach * reach + 2.0 * axis.max_accel * error)
    return max(0.0, BRAKE_MARGIN * (root - reach))


class _JerkLimitedAxes:
    """Three offsets held inside a rate / acceleration / jerk envelope.

    Per axis and per tick, with ``x`` the emitted offset, ``r`` its rate and
    ``a`` its acceleration: the acceleration reachable this tick is
    ``[a-j·dt, a+j·dt]`` intersected with ``±max_accel``; that gives the
    reachable rate window, intersected with ``±max_rate``; the requested rate
    ``(target-x)/dt`` is clamped into that window and integrated.  Every bound
    therefore holds by construction, and a target inside all three is hit
    EXACTLY, with no lag and nothing to ring.

    ``limited_ticks`` counts the ticks where a window actually bound — the
    evidence that these numbers are doing work rather than decorating.
    """

    def __init__(
        self,
        axes: tuple[AxisRate, AxisRate, AxisRate],
        envelope: tuple[float, float, float],
    ) -> None:
        self._axes = axes
        self._envelope = envelope
        self._offset = [0.0, 0.0, 0.0]
        self._rate = [0.0, 0.0, 0.0]
        self._accel = [0.0, 0.0, 0.0]
        self.limited_ticks = 0

    @property
    def offset(self) -> tuple[float, float, float]:
        return (self._offset[0], self._offset[1], self._offset[2])

    def snap_to_zero(self) -> None:
        self._offset = [0.0, 0.0, 0.0]
        self._rate = [0.0, 0.0, 0.0]
        self._accel = [0.0, 0.0, 0.0]

    def step(self, target: tuple[float, float, float], dt_s: float) -> None:
        for index, axis in enumerate(self._axes):
            requested = (target[index] - self._offset[index]) / dt_s
            accel_low = max(-axis.max_accel, self._accel[index] - axis.max_jerk * dt_s)
            accel_high = min(axis.max_accel, self._accel[index] + axis.max_jerk * dt_s)
            rate_low = max(self._rate[index] + accel_low * dt_s, -axis.max_rate)
            rate_high = min(self._rate[index] + accel_high * dt_s, axis.max_rate)
            # The amplitude envelope is a WALL, not a post-hoc clip: cap the
            # rate at what can still be braked inside the remaining headroom.
            # Clipping at the wall instead would put a step into the emitted
            # signal, and a step has unbounded jerk.
            limit = self._envelope[index]
            rate_high = min(
                rate_high, _braking_rate(axis, max(0.0, limit - self._offset[index]), dt_s)
            )
            rate_low = max(
                rate_low, -_braking_rate(axis, max(0.0, limit + self._offset[index]), dt_s)
            )
            if rate_low > rate_high:
                # Only reachable if a limit changed under a moving axis: close
                # the gap at the jerk-legal edge rather than jumping.
                rate = rate_low if abs(rate_low) < abs(rate_high) else rate_high
                self.limited_ticks += 1
            elif rate_low <= requested <= rate_high:
                # The signal is already legal: pass it through EXACTLY.
                rate = requested
            else:
                # Catching up. Cap the catch-up at the rate this axis can still
                # brake from inside the remaining error, or it arrives too fast
                # and overshoots — and an overshoot at the envelope edge is a
                # clip, which is a step, which is what the jerk bound is for.
                ceiling = _braking_rate(axis, abs(target[index] - self._offset[index]), dt_s)
                bounded = min(max(requested, -ceiling), ceiling)
                rate = min(max(bounded, rate_low), rate_high)
                self.limited_ticks += 1
            self._accel[index] = (rate - self._rate[index]) / dt_s
            self._rate[index] = rate
            self._offset[index] += rate * dt_s


class BodyComposer:
    """Merge the finalized velocity with the clamped offsets, every tick.

    Stateful only in the way a filter is: a tick counter, an epoch, and the two
    axis limiters.  No I/O, no threads, no clock of its own — ``now_s`` is
    supplied by the caller so a harness and a runtime tick it identically.
    """

    def __init__(
        self,
        *,
        limits: ComposerLimits = DEFAULT_LIMITS,
        ttl_ms: int = 150,
        breathing_hz: float = 0.25,
        style: str = "calm",
        source: str = "body_composer",
    ) -> None:
        if not 1 <= ttl_ms <= 5_000:
            raise ValueError("composer ttl_ms must be between 1 and 5000")
        if not 0.05 <= breathing_hz <= 2.0:
            raise ValueError("composer breathing_hz must match the idle layer's band")
        self.limits = limits
        self.ttl_ms = int(ttl_ms)
        self.breathing_hz = float(breathing_hz)
        self.style = style
        self.source = source
        self._posture = _JerkLimitedAxes(
            (limits.posture_dz, limits.posture_pitch, limits.posture_roll),
            (MAX_BODY_HEIGHT_M, MAX_BODY_PITCH_RAD, MAX_BODY_PITCH_RAD),
        )
        self._gaze = _JerkLimitedAxes(
            (limits.gaze_yaw, limits.gaze_pitch, limits.gaze_pitch),
            (MAX_HEAD_YAW_RAD, MAX_HEAD_PITCH_RAD, MAX_HEAD_PITCH_RAD),
        )
        self._seq = 0
        self._epoch = 0
        self._last_now_s: float | None = None
        self._emergency_latched = False
        self.emergency_ticks = 0
        self.hold_ticks = 0
        self.clamp_events = 0
        self.max_clamp_excess_frac = 0.0

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def limited_ticks(self) -> int:
        """Axis-ticks on which a rate/accel/jerk window actually bound."""

        return self._posture.limited_ticks + self._gaze.limited_ticks

    def compose(
        self,
        *,
        now_s: float,
        finalized_velocity: object | None,
        offsets: ExpressiveOffsets,
        gaze_target: tuple[float, float] | None = None,
        style: str | None = None,
        priority: int = 0,
        emergency: bool = False,
    ) -> BodyIntentV1:
        """One tick of intent.  Always returns; never raises on a stale clock.

        ``finalized_velocity`` is anything with ``vx``/``vy``/``vyaw`` — the
        ``VelocityCommand`` the dispatch boundary already finalized — or
        ``None`` for "no authorized velocity", which composes to HOLD.  It is
        COPIED, never recomputed: rows B7 exists to prove exactly that.
        """

        if not math.isfinite(now_s):
            raise ValueError("composer now_s must be finite")
        dt_s = self._tick_dt(now_s)

        if emergency:
            if not self._emergency_latched:
                self._epoch += 1
                self._emergency_latched = True
            self.emergency_ticks += 1
            self._posture.snap_to_zero()
            self._gaze.snap_to_zero()
            locomotion: Locomotion = HOLD
            clamped = ExpressiveOffsets()
        else:
            self._emergency_latched = False
            clamped = self._shape_body(offsets, gaze_target, dt_s)
            locomotion = self._locomotion(finalized_velocity)

        if locomotion is HOLD:
            self.hold_ticks += 1
        self._seq += 1
        return BodyIntentV1(
            stamp_ns=max(0, int(now_s * 1e9)),
            epoch=self._epoch,
            seq=self._seq,
            ttl_ms=self.ttl_ms,
            locomotion=locomotion,
            posture=(clamped.body_height_m, clamped.body_pitch_rad, 0.0),
            gaze=(clamped.head_yaw_rad, clamped.head_pitch_rad),
            breathing_phase=self._breathing_phase(now_s),
            style=style if style is not None else self.style,
            source=self.source,
            priority=100 if emergency else priority,
        )

    # -- internals ---------------------------------------------------------
    def _tick_dt(self, now_s: float) -> float:
        previous = self._last_now_s
        self._last_now_s = now_s
        if previous is None:
            return 1.0 / MAX_TICK_HZ
        # A stalled caller must not be handed a giant dt: the shaper would
        # legally traverse the whole envelope in one step. Clamp to the slow
        # end of the declared band and let the limiter catch up over ticks.
        return min(max(now_s - previous, 1e-4), 1.0 / MIN_TICK_HZ)

    def _shape_body(
        self,
        offsets: ExpressiveOffsets,
        gaze_target: tuple[float, float] | None,
        dt_s: float,
    ) -> ExpressiveOffsets:
        requested = offsets
        if gaze_target is not None:
            yaw, pitch = gaze_target
            requested = requested + ExpressiveOffsets(head_yaw_rad=yaw, head_pitch_rad=pitch)
        requested = requested.clamped()
        self._posture.step((requested.body_height_m, requested.body_pitch_rad, 0.0), dt_s)
        self._gaze.step((requested.head_yaw_rad, requested.head_pitch_rad, 0.0), dt_s)
        posture = self._posture.offset
        gaze = self._gaze.offset
        raw = ExpressiveOffsets(
            body_height_m=posture[0],
            body_pitch_rad=posture[1],
            head_yaw_rad=gaze[0],
            head_pitch_rad=gaze[1],
        )
        clamped = raw.clamped()
        excess = _envelope_excess(raw)
        if excess > 0.0:
            # An excursion outside the single amplitude authority: the clamp
            # still holds the envelope (row B2 stays 100 %), and these two
            # counters say how hard it had to work.  It can only happen when a
            # producer hand-off reverses the target while the axis is moving at
            # rate — the catch-up braking cap cannot see a reversal that has
            # not happened yet.
            self.clamp_events += 1
            self.max_clamp_excess_frac = max(self.max_clamp_excess_frac, excess)
        return clamped

    def _locomotion(self, finalized_velocity: object | None) -> Locomotion:
        if finalized_velocity is None:
            return HOLD
        return Velocity(
            vx=float(finalized_velocity.vx),  # type: ignore[attr-defined]
            vy=float(finalized_velocity.vy),  # type: ignore[attr-defined]
            vyaw=float(finalized_velocity.vyaw),  # type: ignore[attr-defined]
        )

    def _breathing_phase(self, now_s: float) -> float:
        phase = (now_s * self.breathing_hz) % 1.0
        return phase if 0.0 <= phase < 1.0 else 0.0


def _envelope_excess(offsets: ExpressiveOffsets) -> float:
    """How far outside the amplitude envelope ``offsets`` sits, as a fraction.

    Unit-free so the four axes (one metre, three radians) compare: 0.0 means
    inside, 0.01 means one axis is 1 % of its own limit past it.
    """

    pairs = (
        (offsets.body_height_m, MAX_BODY_HEIGHT_M),
        (offsets.body_pitch_rad, MAX_BODY_PITCH_RAD),
        (offsets.head_yaw_rad, MAX_HEAD_YAW_RAD),
        (offsets.head_pitch_rad, MAX_HEAD_PITCH_RAD),
    )
    worst = max(abs(value) / limit - 1.0 for value, limit in pairs)
    # A landing exactly ON the limit is inside it; only real excursions count.
    return worst if worst > 1e-9 else 0.0
