"""Commissioning band, arming token, and refusal guards.

Card W0-B (``scrum/20260812/task_2/W0_PRODUCT_CARDS.md``). This module holds the
*measurement* envelope for supervised hardware bring-up: the one-axis /
low-speed / short-duration band a commissioning step may use, the explicit
arming token that must exist before any command is built, and the pure guards
that refuse everything outside the band.

Nothing here touches a robot. Every value defaults to a refusing state and every
guard raises :class:`CommissioningRefusedError` rather than clamping — a
commissioning run that silently clamped an operator's over-limit request would
be measuring something other than what the operator wrote down.

Derivations (card rule 6: constants derive or carry documented provenance)
-------------------------------------------------------------------------
``MIN_LINEAR_MPS`` / ``MAX_LINEAR_MPS`` (0.02 / 0.05 m/s)
    Card verbatim: "0.02-0.05 m/s". The only two literals in this module that
    are given rather than derived.
``MIN_YAW_RAD_S`` / ``MAX_YAW_RAD_S``
    Derived: the tangential speed at the body-inscribing radius must stay
    inside the same band as the linear speed, so ``omega = v /
    footprint_radius_m``. ``footprint_radius_m`` is *mirrored* from
    :data:`parcel_robot.robot_profile.DEFAULT_ROBOT_PROFILE` (0.32 m) and
    ``tests/test_w0b_commissioning.py`` pins the mirror against the live
    profile, so a morphology change reddens the gate instead of leaving this
    derivation quietly false.
``SETTLED_LINEAR_MPS`` / ``SETTLED_YAW_RAD_S``
    Derived: half the *smallest* speed commissioning ever commands. A robot
    still moving at the slowest commissioned speed can then never be reported
    "settled". This matters: the live production thresholds
    (``configs/robot.yaml`` ``settled_linear_speed_mps: 0.08``,
    ``settled_yaw_speed_rad_s: 0.12``) are *above* the whole commissioning
    band, so stop confirmation at commissioning speed would otherwise be
    satisfied by a robot that never stopped. Commissioning tightens them for
    its own manager only; the production values are untouched.
``SIGN_EVIDENCE_FLOOR_MPS`` / ``SIGN_EVIDENCE_FLOOR_RAD_S``
    Equal to the settled thresholds: a sign claim requires the mean measured
    speed to exceed the speed at which this path is willing to call the robot
    stationary. Below that there is no evidence, and the record fails closed
    with an unknown sign rather than guessing.
``MAX_TTL_S`` (0.35 s)
    The live production command TTL (``control/models.py`` ``ControlTiming.
    command_timeout_s``, ``configs/robot.yaml`` ``control.command_timeout_s``).
    Commissioning is never *more* permissive than production, so it takes the
    production value as its ceiling and the configured value when that is
    shorter.
``DEFAULT_MAX_DURATION_S`` (1.0 s)
    The live production ``ControlTiming.stop_timeout_s``. Rationale: a
    commissioning step must never command motion for longer than the worst-case
    time to stop it, so the robot is never more than one stop budget away from
    stationary. Total commanded travel is therefore bounded by
    ``MAX_LINEAR_MPS * (duration + stop_timeout) = 0.05 * 2.0 = 0.10 m``. The
    session recomputes this from its manager's *live* timing; the constant is
    only the fallback and is pinned against ``ControlTiming()`` by test.
``ARMING_TTL_S`` (120 s)
    Procedural, not derived, and labelled as such: arming must not outlive the
    operator's presence at the robot. Two minutes is the stated working
    assumption for "an operator who armed this is still standing there"; it is
    falsifiable by operator trial and carries no safety derivation.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from parcel_robot.models import VelocityCommand

#: Only source string this path ever writes to a control setpoint.
COMMISSIONING_SOURCE = "commissioning"

#: Card-given speed band.
MIN_LINEAR_MPS = 0.02
MAX_LINEAR_MPS = 0.05

#: Mirrored morphology constant. Deliberately a literal rather than an import
#: of ``DEFAULT_ROBOT_PROFILE.footprint_radius_m``, so this module stays a leaf;
#: ``test_derived_constants_are_pinned_by_reference`` asserts the mirror equals
#: the live profile, so a morphology change reddens the gate.
FOOTPRINT_RADIUS_M = 0.32

MIN_YAW_RAD_S = MIN_LINEAR_MPS / FOOTPRINT_RADIUS_M
MAX_YAW_RAD_S = MAX_LINEAR_MPS / FOOTPRINT_RADIUS_M

#: Stationarity thresholds, and the same numbers serve as the sign-evidence
#: floor: a sign claim requires mean measured speed above the speed at which
#: this path is willing to call the robot stopped. Read through
#: ``CommissioningLimits.evidence_floor(axis)``, which is the only accessor.
SETTLED_LINEAR_MPS = MIN_LINEAR_MPS / 2.0
SETTLED_YAW_RAD_S = MIN_YAW_RAD_S / 2.0

MAX_TTL_S = 0.35
DEFAULT_MAX_DURATION_S = 1.0
ARMING_TTL_S = 120.0

#: Below this magnitude a velocity component counts as "not commanded".
AXIS_EPSILON = 1e-9

#: Every acknowledgement an operator must make before an arming token exists.
REQUIRED_ACKNOWLEDGEMENTS = frozenset(
    {
        "support_rig",
        "fenced_area",
        "estop_operator",
    }
)

#: Printed by the CLI before anything is constructed. One line per required
#: acknowledgement, plus the procedure that makes the numbers meaningful.
OPERATOR_INSTRUCTIONS: tuple[str, ...] = (
    (
        "support_rig: the robot hangs in a support rig or stands on blocks with "
        "its feet clear of the ground, so a wrong-signed axis cannot walk it "
        "anywhere."
    ),
    (
        "fenced_area: the working area is fenced or barriered, empty of people "
        "and obstacles, and no one is inside the fence while a step runs."
    ),
    (
        "estop_operator: a second person, not the person running this command, "
        "holds the physical E-stop, is watching the robot, and can reach it."
    ),
    (
        "Procedure: run the read-only observation phase first and write down the "
        "modes and the resting feedback. Then run ONE axis at a time, lowest "
        "speed first, and confirm the robot stopped by eye as well as by this "
        "tool."
    ),
    (
        "If anything is unexpected - a sign you did not predict, a stop that was "
        "not confirmed, a fault, or this tool refusing - use the physical E-stop "
        "and stop the session. A latched failure is never cleared by re-running."
    ),
)


class CommissioningAxis(str, Enum):
    """The one axis a commissioning step is allowed to command."""

    VX = "vx"
    VY = "vy"
    VYAW = "vyaw"

    @property
    def is_angular(self) -> bool:
        return self is CommissioningAxis.VYAW


class RefusalReason(str, Enum):
    """Why a commissioning request was refused. Refusals are not latches."""

    NOT_ARMED = "not_armed"
    ARMING_EXPIRED = "arming_expired"
    ARMING_FOREIGN_PROCESS = "arming_foreign_process"
    MISSING_ACKNOWLEDGEMENT = "missing_acknowledgement"
    MULTI_AXIS = "multi_axis"
    ZERO_COMMAND = "zero_command"
    NON_FINITE = "non_finite"
    OVER_LIMIT = "over_limit"
    UNDER_LIMIT = "under_limit"
    OVER_DURATION = "over_duration"
    OVER_TTL = "over_ttl"
    MODES_NOT_OBSERVED = "modes_not_observed"
    NO_FEEDBACK = "no_feedback"
    ROBOT_NOT_STATIONARY = "robot_not_stationary"
    VENDOR_FAULT = "vendor_fault"
    SESSION_NOT_STARTED = "session_not_started"
    SESSION_CLOSED = "session_closed"
    JOURNAL_ALREADY_USED = "journal_already_used"


class LatchReason(str, Enum):
    """Why a commissioning session latched. A latch is permanent."""

    INTERRUPTED = "interrupted"
    STATE_LOST = "state_lost"
    PROCESS_EXIT = "process_exit"
    STOP_NOT_CONFIRMED = "stop_not_confirmed"
    TEARDOWN_FAILED = "teardown_failed"
    JOURNAL_WRITE_FAILED = "journal_write_failed"
    FOREIGN_WRITER = "foreign_writer"
    CONTROLLER_FAULT = "controller_fault"
    ARMING_EXPIRED_MID_STEP = "arming_expired_mid_step"
    UNEXPECTED_ERROR = "unexpected_error"


class CommissioningError(RuntimeError):
    """Base class for every refusal and latch raised by this package."""


class CommissioningRefusedError(CommissioningError):
    """A request was refused. The session may still be used."""

    def __init__(self, reason: RefusalReason, detail: str = "") -> None:
        self.reason = reason
        message = f"commissioning refused: {reason.value}"
        super().__init__(f"{message}; {detail}" if detail else message)


class CommissioningLatchedError(CommissioningError):
    """The session latched a failure. Nothing clears it but a new session."""

    def __init__(self, reason: LatchReason, detail: str = "") -> None:
        self.reason = reason
        message = (
            f"commissioning latched: {reason.value}; this session is finished. "
            "Confirm the robot is stationary and use the physical E-stop if it is not"
        )
        super().__init__(f"{message}; {detail}" if detail else message)


@dataclass(frozen=True)
class CommissioningLimits:
    """The band a commissioning step may use. Cannot be widened past the module.

    Constructing wider limits than the module band raises: a caller cannot ask
    this package for permission it does not have.
    """

    min_linear_mps: float = MIN_LINEAR_MPS
    max_linear_mps: float = MAX_LINEAR_MPS
    min_yaw_rad_s: float = MIN_YAW_RAD_S
    max_yaw_rad_s: float = MAX_YAW_RAD_S
    max_duration_s: float = DEFAULT_MAX_DURATION_S
    max_ttl_s: float = MAX_TTL_S
    settled_linear_mps: float = SETTLED_LINEAR_MPS
    settled_yaw_rad_s: float = SETTLED_YAW_RAD_S

    def __post_init__(self) -> None:
        values = (
            self.min_linear_mps,
            self.max_linear_mps,
            self.min_yaw_rad_s,
            self.max_yaw_rad_s,
            self.max_duration_s,
            self.max_ttl_s,
            self.settled_linear_mps,
            self.settled_yaw_rad_s,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            raise ValueError("commissioning limits must be positive and finite")
        if self.min_linear_mps > self.max_linear_mps or self.min_yaw_rad_s > self.max_yaw_rad_s:
            raise ValueError("commissioning band minimum cannot exceed its maximum")
        if self.min_linear_mps < MIN_LINEAR_MPS or self.max_linear_mps > MAX_LINEAR_MPS:
            raise ValueError(
                "commissioning linear band must stay inside "
                f"[{MIN_LINEAR_MPS:g}, {MAX_LINEAR_MPS:g}] m/s"
            )
        if self.min_yaw_rad_s < MIN_YAW_RAD_S or self.max_yaw_rad_s > MAX_YAW_RAD_S:
            raise ValueError(
                "commissioning yaw band must stay inside "
                f"[{MIN_YAW_RAD_S:g}, {MAX_YAW_RAD_S:g}] rad/s"
            )
        if self.max_duration_s > DEFAULT_MAX_DURATION_S:
            raise ValueError(
                f"commissioning step duration cannot exceed {DEFAULT_MAX_DURATION_S:g} s"
            )
        if self.max_ttl_s > MAX_TTL_S:
            raise ValueError(f"commissioning command TTL cannot exceed {MAX_TTL_S:g} s")
        if self.settled_linear_mps > SETTLED_LINEAR_MPS:
            raise ValueError(
                "commissioning stationarity threshold cannot exceed "
                f"{SETTLED_LINEAR_MPS:g} m/s"
            )
        if self.settled_yaw_rad_s > SETTLED_YAW_RAD_S:
            raise ValueError(
                "commissioning yaw stationarity threshold cannot exceed "
                f"{SETTLED_YAW_RAD_S:g} rad/s"
            )

    def band(self, axis: CommissioningAxis) -> tuple[float, float]:
        if axis.is_angular:
            return (self.min_yaw_rad_s, self.max_yaw_rad_s)
        return (self.min_linear_mps, self.max_linear_mps)

    def evidence_floor(self, axis: CommissioningAxis) -> float:
        """Smallest mean measured magnitude that counts as sign evidence."""

        return self.settled_yaw_rad_s if axis.is_angular else self.settled_linear_mps

    def as_dict(self) -> dict[str, float]:
        return {
            "min_linear_mps": self.min_linear_mps,
            "max_linear_mps": self.max_linear_mps,
            "min_yaw_rad_s": self.min_yaw_rad_s,
            "max_yaw_rad_s": self.max_yaw_rad_s,
            "max_duration_s": self.max_duration_s,
            "max_ttl_s": self.max_ttl_s,
            "settled_linear_mps": self.settled_linear_mps,
            "settled_yaw_rad_s": self.settled_yaw_rad_s,
        }

    @classmethod
    def from_mapping(cls, payload: dict[str, object]) -> CommissioningLimits:
        fields = {key: float(value) for key, value in payload.items()}  # type: ignore[arg-type]
        return cls(**fields)


@dataclass(frozen=True)
class CommissioningArming:
    """Explicit, process-local, expiring permission to command one axis.

    There is no default construction: an operator identity, a robot identity and
    every acknowledgement must be supplied. ``observed_modes`` stays empty until
    the read-only observation phase has actually seen modes, and an empty tuple
    refuses every motion step.
    """

    operator: str
    robot_serial: str
    acknowledgements: frozenset[str]
    armed_at: float
    pid: int
    observed_modes: tuple[int, ...] = ()
    ttl_s: float = ARMING_TTL_S
    limits: CommissioningLimits = field(default_factory=CommissioningLimits)

    def __post_init__(self) -> None:
        if not self.operator.strip() or len(self.operator) > 80:
            raise ValueError("commissioning operator must be a short non-empty name")
        if not self.robot_serial.strip() or len(self.robot_serial) > 80:
            raise ValueError("commissioning robot_serial must be a short non-empty string")
        acknowledgements = frozenset(self.acknowledgements)
        unknown = acknowledgements - REQUIRED_ACKNOWLEDGEMENTS
        if unknown:
            raise ValueError(f"unknown commissioning acknowledgement(s): {sorted(unknown)}")
        missing = REQUIRED_ACKNOWLEDGEMENTS - acknowledgements
        if missing:
            raise CommissioningRefusedError(
                RefusalReason.MISSING_ACKNOWLEDGEMENT,
                f"missing: {', '.join(sorted(missing))}",
            )
        object.__setattr__(self, "acknowledgements", acknowledgements)
        if not math.isfinite(self.armed_at):
            raise ValueError("commissioning arming timestamp must be finite")
        if not math.isfinite(self.ttl_s) or not 0.0 < self.ttl_s <= ARMING_TTL_S:
            raise ValueError(f"commissioning arming TTL must be in (0, {ARMING_TTL_S:g}] seconds")
        if isinstance(self.pid, bool) or not isinstance(self.pid, int) or self.pid <= 0:
            raise ValueError("commissioning arming pid must be a positive integer")
        modes = tuple(self.observed_modes)
        if any(isinstance(mode, bool) or not isinstance(mode, int) for mode in modes):
            raise TypeError("commissioning observed_modes must contain integers")
        if any(mode < 0 or mode > 255 for mode in modes):
            raise ValueError("commissioning observed_modes must contain byte-sized integers")
        object.__setattr__(self, "observed_modes", modes)

    @classmethod
    def arm(
        cls,
        *,
        operator: str,
        robot_serial: str,
        acknowledgements: Iterable[str],
        observed_modes: Iterable[int] = (),
        ttl_s: float = ARMING_TTL_S,
        limits: CommissioningLimits | None = None,
        clock=time.monotonic,
    ) -> CommissioningArming:
        """Build an arming token in *this* process, valid from *now*."""

        return cls(
            operator=operator,
            robot_serial=robot_serial,
            acknowledgements=frozenset(acknowledgements),
            armed_at=float(clock()),
            pid=os.getpid(),
            observed_modes=tuple(int(mode) for mode in observed_modes),
            ttl_s=float(ttl_s),
            limits=limits or CommissioningLimits(),
        )

    def with_observed_modes(self, modes: Iterable[int]) -> CommissioningArming:
        """Re-issue this token carrying the modes the observation phase saw."""

        return CommissioningArming(
            operator=self.operator,
            robot_serial=self.robot_serial,
            acknowledgements=self.acknowledgements,
            armed_at=self.armed_at,
            pid=self.pid,
            observed_modes=tuple(int(mode) for mode in modes),
            ttl_s=self.ttl_s,
            limits=self.limits,
        )

    def expired(self, now: float) -> bool:
        return now - self.armed_at >= self.ttl_s

    def assert_valid(self, now: float) -> None:
        """Refuse a token that is expired or belongs to another process."""

        if self.pid != os.getpid():
            raise CommissioningRefusedError(
                RefusalReason.ARMING_FOREIGN_PROCESS,
                f"armed by pid {self.pid}, running as pid {os.getpid()}",
            )
        if self.expired(now):
            raise CommissioningRefusedError(
                RefusalReason.ARMING_EXPIRED,
                f"armed {now - self.armed_at:.1f}s ago, TTL {self.ttl_s:g}s",
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "operator": self.operator,
            "robot_serial": self.robot_serial,
            "acknowledgements": sorted(self.acknowledgements),
            "observed_modes": list(self.observed_modes),
            "ttl_s": self.ttl_s,
            "pid": self.pid,
            "limits": self.limits.as_dict(),
        }


def single_axis_command(axis: CommissioningAxis, speed: float) -> VelocityCommand:
    """Build the only shape of command this path can produce: one axis."""

    if not isinstance(axis, CommissioningAxis):
        raise TypeError("commissioning axis must be a CommissioningAxis")
    value = float(speed)
    if not math.isfinite(value):
        raise CommissioningRefusedError(RefusalReason.NON_FINITE, f"speed={speed!r}")
    if axis is CommissioningAxis.VX:
        return VelocityCommand(vx=value)
    if axis is CommissioningAxis.VY:
        return VelocityCommand(vy=value)
    return VelocityCommand(vyaw=value)


def commanded_axes(command: VelocityCommand) -> tuple[CommissioningAxis, ...]:
    """Axes whose magnitude is above the not-commanded epsilon."""

    pairs = (
        (CommissioningAxis.VX, command.vx),
        (CommissioningAxis.VY, command.vy),
        (CommissioningAxis.VYAW, command.vyaw),
    )
    return tuple(axis for axis, value in pairs if abs(value) > AXIS_EPSILON)


def assert_commissioning_command(
    command: VelocityCommand,
    limits: CommissioningLimits,
) -> CommissioningAxis:
    """Refuse anything that is not exactly one in-band axis. Never clamps."""

    values = (command.vx, command.vy, command.vyaw)
    if any(not math.isfinite(value) for value in values):
        raise CommissioningRefusedError(RefusalReason.NON_FINITE, f"command={values!r}")
    axes = commanded_axes(command)
    if not axes:
        raise CommissioningRefusedError(RefusalReason.ZERO_COMMAND)
    if len(axes) > 1:
        raise CommissioningRefusedError(
            RefusalReason.MULTI_AXIS,
            f"commanded {', '.join(axis.value for axis in axes)}; commission one axis at a time",
        )
    axis = axes[0]
    magnitude = abs(getattr(command, axis.value))
    low, high = limits.band(axis)
    if magnitude > high:
        raise CommissioningRefusedError(
            RefusalReason.OVER_LIMIT,
            f"{axis.value}={magnitude:g} exceeds the commissioning cap {high:g}",
        )
    if magnitude < low:
        raise CommissioningRefusedError(
            RefusalReason.UNDER_LIMIT,
            f"{axis.value}={magnitude:g} is below the commissioning floor {low:g}; "
            "a speed this small produces no sign evidence",
        )
    return axis


def assert_commissioning_duration(duration_s: float, limits: CommissioningLimits) -> float:
    """Refuse a step longer than the band's duration cap."""

    value = float(duration_s)
    if not math.isfinite(value) or value <= 0.0:
        raise CommissioningRefusedError(RefusalReason.NON_FINITE, f"duration={duration_s!r}")
    if value > limits.max_duration_s:
        raise CommissioningRefusedError(
            RefusalReason.OVER_DURATION,
            f"duration={value:g}s exceeds the commissioning cap {limits.max_duration_s:g}s",
        )
    return value


def assert_commissioning_ttl(ttl_s: float, limits: CommissioningLimits) -> float:
    """Refuse a command lease longer than production's own command TTL."""

    value = float(ttl_s)
    if not math.isfinite(value) or value <= 0.0:
        raise CommissioningRefusedError(RefusalReason.NON_FINITE, f"ttl={ttl_s!r}")
    if value > limits.max_ttl_s:
        raise CommissioningRefusedError(
            RefusalReason.OVER_TTL,
            f"ttl={value:g}s exceeds the commissioning cap {limits.max_ttl_s:g}s",
        )
    return value


DOES_NOT_PROVE: tuple[str, ...] = (
    (
        "The band is an envelope, not a safety proof: nothing here establishes "
        "that 0.05 m/s is safe on any particular robot, rig, or floor. It "
        "establishes that this path cannot ask for more."
    ),
    (
        "FOOTPRINT_RADIUS_M is mirrored from the Go2 profile. On another "
        "morphology the yaw band is wrong until the profile (and the pinning "
        "test) move."
    ),
    (
        "ARMING_TTL_S is a procedural assumption about operator presence, not a "
        "derived latency budget."
    ),
)
