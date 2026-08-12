"""Pure final-stop authority for the actuator dispatch boundary.

This module deliberately owns no runtime wiring.  The product-path consumer
must call :func:`finalize_command` after every velocity shaper and immediately
before dispatch, then honor every reset obligation in the returned decision.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import IntEnum

from parcel_robot.core.stop_ramp import enforce_monotone_stop
from parcel_robot.models import VelocityCommand

ZERO_COMMAND = VelocityCommand()


class InterventionSeverity(IntEnum):
    """Ordered final-monitor intervention classes.

    The three original values are an ON-DISK contract: they are pinned by test
    and dispatched by identity, so a new class is APPENDED and nothing is ever
    renumbered. ``NOMINAL_STOP`` (card J-B, 2026-08-11) is deliberately 3 rather
    than "between" PROXIMITY_STOP and HARD_STOP for exactly that reason — the
    numeric order is not a severity order and no comparison relies on it.
    """

    CLEAR = 0
    PROXIMITY_STOP = 1
    HARD_STOP = 2
    #: A NOMINAL (non-emergency) zero intent whose command may decay along the
    #: monotone ramp of :mod:`parcel_robot.core.stop_ramp` instead of snapping
    #: to zero. Every emergency arm — arbiter e-stop, input-health latch,
    #: proximity stop, expired intent — keeps its own severity and P0-A's
    #: instant zero. The caller must supply ``previous_command``; without it,
    #: or on any non-monotone candidate, this fails closed to ``HARD_STOP``.
    NOMINAL_STOP = 3


@dataclass(frozen=True)
class ResetObligation:
    """One stateful command stage that must be reset after a hard stop."""

    name: str
    reset: Callable[[], None]

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("reset obligation name must be non-empty")
        if not callable(self.reset):
            raise TypeError("reset obligation reset must be callable")


@dataclass(frozen=True)
class FinalStopDecision:
    """Final command plus the reset outcome required by its severity."""

    command: VelocityCommand
    severity: InterventionSeverity
    reset_required: bool
    reset_attempted: tuple[str, ...] = ()
    reset_failures: tuple[str, ...] = ()

    @property
    def dispatch_allowed(self) -> bool:
        """A failed reset may never be followed by motion."""

        return not self.reset_failures or self.command == ZERO_COMMAND


def finalize_command(
    candidate: VelocityCommand,
    severity: InterventionSeverity,
    *,
    downstream_stages: Iterable[ResetObligation] = (),
    previous_command: VelocityCommand | None = None,
) -> FinalStopDecision:
    """Return the command for the dispatch boundary and reset stateful stages.

    ``HARD_STOP`` always returns the exact all-axis zero command, even when the
    candidate is malformed or a reset callback fails.  Every supplied reset is
    attempted exactly once; one broken stage cannot prevent later stages from
    being reset.  ``PROXIMITY_STOP`` preserves finite yaw while zeroing only
    translation, matching Parcel's existing proximity convention.

    ``NOMINAL_STOP`` passes the candidate through ONLY when
    :func:`~parcel_robot.core.stop_ramp.enforce_monotone_stop` accepts it as a
    legal continuation of ``previous_command`` (finite, non-increasing in
    magnitude per axis, sign preserved or collapsed).  A missing
    ``previous_command`` or any rejected candidate takes the untouched
    ``HARD_STOP`` branch, resets included.

    Unknown severities and non-finite commands fail closed as ``HARD_STOP``.
    The tail below is EXPLICITLY fail-closed: before card J-B it returned the
    candidate for any severity that was not HARD/PROXIMITY, so appending a
    member would have opened a hole.  Every reachable input today is
    byte-unaffected by that hardening.
    """

    resolved = _severity_or_hard_stop(severity)
    if not _finite_command(candidate):
        resolved = InterventionSeverity.HARD_STOP

    if resolved is InterventionSeverity.NOMINAL_STOP:
        allowed = _monotone_stop_or_none(previous_command, candidate)
        if allowed is None:
            resolved = InterventionSeverity.HARD_STOP
        else:
            candidate = allowed

    if resolved is InterventionSeverity.PROXIMITY_STOP:
        return FinalStopDecision(
            command=VelocityCommand(vyaw=candidate.vyaw),
            severity=resolved,
            reset_required=False,
        )
    if resolved is InterventionSeverity.NOMINAL_STOP:
        return FinalStopDecision(
            command=candidate,
            severity=resolved,
            reset_required=False,
        )
    if resolved is InterventionSeverity.CLEAR:
        return FinalStopDecision(
            command=candidate,
            severity=resolved,
            reset_required=False,
        )
    attempted, failures = _reset_all(downstream_stages)
    return FinalStopDecision(
        command=ZERO_COMMAND,
        severity=InterventionSeverity.HARD_STOP,
        reset_required=True,
        reset_attempted=attempted,
        reset_failures=failures,
    )


def _monotone_stop_or_none(
    previous: VelocityCommand | None,
    candidate: VelocityCommand,
) -> VelocityCommand | None:
    """The nominal-ramp boundary check, in command space."""

    if not isinstance(previous, VelocityCommand):
        return None
    allowed = enforce_monotone_stop(
        (previous.vx, previous.vy, previous.vyaw),
        (candidate.vx, candidate.vy, candidate.vyaw),
    )
    if allowed is None:
        return None
    return VelocityCommand(vx=allowed[0], vy=allowed[1], vyaw=allowed[2])


def _severity_or_hard_stop(value: object) -> InterventionSeverity:
    if isinstance(value, InterventionSeverity):
        return value
    return InterventionSeverity.HARD_STOP


def _finite_command(command: object) -> bool:
    if not isinstance(command, VelocityCommand):
        return False
    return all(math.isfinite(value) for value in (command.vx, command.vy, command.vyaw))


def _reset_all(
    stages: Iterable[ResetObligation],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    attempted: list[str] = []
    failures: list[str] = []
    try:
        iterator = iter(stages)
    except Exception as error:  # noqa: BLE001 - malformed reset lists fail closed
        return (), (f"<reset-list>:{type(error).__name__}",)
    while True:
        try:
            stage = next(iterator)
        except StopIteration:
            break
        except Exception as error:  # noqa: BLE001 - retain exact-zero decision
            failures.append(f"<reset-list>:{type(error).__name__}")
            break
        if not isinstance(stage, ResetObligation):
            failures.append("<invalid-reset-obligation>:TypeError")
            continue
        attempted.append(stage.name)
        try:
            stage.reset()
        except Exception as error:  # noqa: BLE001 - attempt every remaining reset
            failures.append(f"{stage.name}:{type(error).__name__}")
    return tuple(attempted), tuple(failures)


__all__ = [
    "ZERO_COMMAND",
    "FinalStopDecision",
    "InterventionSeverity",
    "ResetObligation",
    "finalize_command",
]
