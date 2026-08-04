from __future__ import annotations

import math
import threading
import time

from parcel_robot.models import VelocityCommand

from .base import LocomotionController, RobotStateSource
from .models import (
    ControllerStatus,
    ControlLifecycle,
    ControlLimits,
    ControlTiming,
    FaultReason,
    RobotMotionState,
    TimedVelocitySetpoint,
)


class ControlNotReadyError(RuntimeError):
    """Raised when a target cannot safely cross the controller boundary."""


class ControlManager:
    """Single writer, feedback watchdog, and lifecycle owner for locomotion."""

    def __init__(
        self,
        controller: LocomotionController,
        state_source: RobotStateSource,
        *,
        limits: ControlLimits | None = None,
        timing: ControlTiming | None = None,
        clock=time.monotonic,
    ) -> None:
        self.controller = controller
        self.state_source = state_source
        self.limits = limits or ControlLimits()
        self.timing = timing or ControlTiming()
        self._clock = clock
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._tick_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._emergency_thread: threading.Thread | None = None
        self._lifecycle = ControlLifecycle.DISARMED
        self._target: TimedVelocitySetpoint | None = None
        self._last_state: RobotMotionState | None = None
        self._sequence = 0
        self._started_at: float | None = None
        self._fault: str | None = None
        self._last_stop_reason = "not_started"
        self._watchdog_stops = 0
        self._stop_delivered = True
        self._awaiting_stop_confirmation = False
        self._stop_requested_at: float | None = None
        self._stop_completed_at: float | None = None
        self._stop_feedback_sequence: int | None = None
        self._stop_settled_samples = 0
        self._stop_last_settled_sequence: int | None = None
        self._last_stop_attempt_at: float | None = None
        self._emergency_stopped = False
        self._emergency_in_flight = False
        self._emergency_clear_in_flight = False
        self._emergency_reassert_requested = False
        self._updates_in_flight = 0
        self._controller_calls_in_flight = 0
        self._stop_delivery_generation = 0
        self._controller_activated = False
        self._starting = False
        self._closing = False
        self._close_in_progress = False
        self._tearing_down = False
        self._teardown_committed = False
        self._intent_epoch = 0

    def start(self, *, threaded: bool = True) -> None:
        with self._lock:
            if self._closing or self._lifecycle in {
                ControlLifecycle.CLOSING,
                ControlLifecycle.CLOSED,
            }:
                raise RuntimeError("control manager is closed")
            if self._starting:
                raise ControlNotReadyError("control manager startup is already in progress")
            if self._lifecycle != ControlLifecycle.DISARMED:
                if threaded and (self._thread is None or not self._thread.is_alive()):
                    self._stop_event.clear()
                    self._start_thread_locked()
                return
            if self._emergency_stopped:
                raise ControlNotReadyError(
                    "clear the pre-start emergency stop before activating the controller"
                )
            self._starting = True
            self._lifecycle = ControlLifecycle.ARMING
            self._started_at = self._clock()
            self._stop_event.clear()
            try:
                # State and controller activation are bounded passive calls.
                # Release the lifecycle lock so an E-stop/close can latch while
                # a vendor implementation is still returning.
                self._lock.release()
                try:
                    self.state_source.start()
                finally:
                    self._lock.acquire()
                self._call_controller_unlocked(self.controller.activate)
                self._controller_activated = True
                baseline_state = self.state_source.latest()
                self._last_state = baseline_state
                stop_requested_at = self._clock()
                self._stop_delivered = False
                self._awaiting_stop_confirmation = True
                self._stop_requested_at = stop_requested_at
                self._stop_completed_at = None
                self._stop_feedback_sequence = (
                    baseline_state.sequence if baseline_state is not None else None
                )
                self._stop_settled_samples = 0
                self._stop_last_settled_sequence = None
                self._last_stop_attempt_at = stop_requested_at

                # Establish a known stationary boundary before accepting the
                # first lease. An E-stop that crossed passive activation wins;
                # otherwise this is StopMove, never Damp/StandDown.
                delivered_emergency = self._emergency_stopped
                if delivered_emergency:
                    self._call_controller_unlocked(self.controller.emergency_stop)
                    self._last_stop_reason = "emergency_stop_during_start"
                else:
                    self._call_controller_unlocked(
                        lambda: self.controller.stop("manager_start")
                    )
                    self._last_stop_reason = "manager_start"
                if not delivered_emergency and self._emergency_stopped:
                    # E-stop latched while the ordinary startup stop was in
                    # flight. Make the emergency operation the final boundary.
                    self._call_controller_unlocked(self.controller.emergency_stop)
                    self._last_stop_reason = "emergency_stop_during_start"
                self._stop_delivered = True
                self._mark_stop_completed_locked()
            except BaseException:
                try:
                    self._call_controller_unlocked(self.controller.close)
                except BaseException:  # noqa: BLE001, S110 - preserve activation failure
                    pass
                self._controller_activated = False
                self._lock.release()
                try:
                    try:
                        self.state_source.close()
                    except BaseException:  # noqa: BLE001, S110 - preserve activation failure
                        pass
                finally:
                    self._lock.acquire()
                self._starting = False
                self._condition.notify_all()
                self._lifecycle = (
                    ControlLifecycle.CLOSING
                    if self._closing
                    else ControlLifecycle.DISARMED
                )
                raise
            self._started_at = self._clock()
            if self._closing:
                self._lifecycle = ControlLifecycle.CLOSING
            elif self._emergency_stopped:
                self._lifecycle = ControlLifecycle.EMERGENCY_STOPPED
            elif self._awaiting_stop_confirmation:
                self._lifecycle = ControlLifecycle.ARMING
            else:
                self._lifecycle = ControlLifecycle.IDLE
            self._intent_epoch += 1
            self._starting = False
            self._condition.notify_all()
            if threaded and not self._closing:
                self._start_thread_locked()

    def _validate_capabilities(self, command: VelocityCommand) -> None:
        """Reject motion the active controller declares itself unable to do.

        These flags were previously decorative; a declared capability limit now
        fails closed at the dispatch boundary instead of silently commanding a
        robot that cannot comply (e.g. strafing a non-holonomic platform).
        """

        capabilities = self.controller.capabilities
        if not capabilities.body_velocity and not _is_zero(command):
            raise ControlNotReadyError(
                f"controller {self.controller.name!r} does not accept body-velocity commands"
            )
        if not capabilities.lateral_velocity and abs(command.vy) > 1e-9:
            raise ControlNotReadyError(
                f"controller {self.controller.name!r} cannot strafe; vy must be zero"
            )

    def set_target(
        self,
        command: VelocityCommand,
        *,
        source: str,
        ttl: float | None = None,
        now: float | None = None,
    ) -> TimedVelocitySetpoint:
        current = self._clock() if now is None else float(now)
        lease = self.timing.command_timeout_s if ttl is None else float(ttl)
        if not math.isfinite(current):
            raise ValueError("control target timestamp must be finite")
        if not math.isfinite(lease) or lease <= 0.0:
            raise ValueError("control target TTL must be positive and finite")
        self.limits.validate(command)
        self._validate_capabilities(command)
        if _is_zero(command):
            self.stop("zero_target")
            with self._lock:
                self._sequence += 1
                return TimedVelocitySetpoint(
                    command=command,
                    source=source,
                    sequence=self._sequence,
                    issued_at=current,
                    valid_until=current + lease,
                )
        with self._lock:
            if self._starting or self._closing or self._lifecycle in {
                ControlLifecycle.DISARMED,
                ControlLifecycle.FAULTED,
                ControlLifecycle.EMERGENCY_STOPPED,
                ControlLifecycle.CLOSING,
                ControlLifecycle.CLOSED,
            }:
                raise ControlNotReadyError(
                    f"controller cannot accept motion while {self._lifecycle.value}"
                )
            try:
                state = self.state_source.latest()
            except Exception as error:
                self._fault_locked(f"robot_state_read_failed: {error}")
                raise ControlNotReadyError(
                    "controller cannot move because robot feedback failed"
                ) from error
            if not self._state_is_fresh(state, current):
                raise ControlNotReadyError("controller cannot move without fresh robot feedback")
            assert state is not None
            self._last_state = state
            if self._awaiting_stop_confirmation and not self._update_stop_confirmation_locked(
                state, current
            ):
                raise ControlNotReadyError(
                    "controller cannot move until the previous stop is confirmed"
                )
            self._sequence += 1
            previous = self._target
            if previous is None or previous.command != command or previous.source != source:
                self._intent_epoch += 1
            target = TimedVelocitySetpoint(
                command=command,
                source=source,
                sequence=self._sequence,
                issued_at=current,
                valid_until=current + lease,
            )
            self._target = target
            self._stop_delivered = False
            self._awaiting_stop_confirmation = False
            self._stop_requested_at = None
            self._stop_completed_at = None
            self._stop_feedback_sequence = None
            self._stop_settled_samples = 0
            self._stop_last_settled_sequence = None
            return target

    def tick(self, *, now: float | None = None) -> None:
        current = self._clock() if now is None else float(now)
        if not math.isfinite(current):
            raise ValueError("control tick timestamp must be finite")
        with self._tick_lock:
            self._tick_once(current)

    def _tick_once(self, current: float) -> None:
        with self._lock:
            if self._lifecycle in {ControlLifecycle.DISARMED, ControlLifecycle.CLOSED}:
                return
            try:
                state = self.state_source.latest()
            except Exception as error:  # noqa: BLE001 - feedback plugins are a fault boundary
                reason = f"robot_state_read_failed: {error}"
                if self._closing:
                    self._fault = reason
                    if self._awaiting_stop_confirmation and not self._tearing_down:
                        self._retry_stop_if_due_locked("close_stop_feedback_failed", current)
                elif self._emergency_stopped:
                    self._fault = reason
                    self._retry_stop_if_due_locked("emergency_stop_feedback_failed", current)
                else:
                    self._fault_locked(reason)
                return
            self._last_state = state
            if self._closing:
                if self._state_is_fresh(state, current):
                    assert state is not None
                    if self._update_stop_confirmation_locked(state, current):
                        return
                if self._awaiting_stop_confirmation and not self._tearing_down:
                    self._retry_stop_if_due_locked("close_stop_retry", current)
                return
            if self._emergency_stopped:
                if self._state_is_fresh(state, current):
                    assert state is not None
                    if self._update_stop_confirmation_locked(state, current):
                        return
                self._retry_stop_if_due_locked("emergency_stop_retry", current)
                return
            if self._lifecycle == ControlLifecycle.FAULTED:
                if self._state_is_fresh(state, current):
                    assert state is not None
                    if self._update_stop_confirmation_locked(state, current):
                        return
                self._retry_stop_if_due_locked("fault_stop_retry", current)
                return
            if not self._state_is_fresh(state, current):
                started_at = self._started_at if self._started_at is not None else current
                if self._lifecycle == ControlLifecycle.ARMING:
                    if current - started_at < self.timing.startup_timeout_s:
                        return
                    reason = "robot_state_startup_timeout"
                else:
                    reason = "robot_state_stale"
                self._fault_locked(reason)
                return
            assert state is not None
            if state.fault_reason is not FaultReason.NONE:
                # Preserve the historical fault string when a raw vendor code
                # exists; otherwise report the generic classification.
                if state.error_code:
                    self._fault_locked(f"robot_error_code_{state.error_code}")
                else:
                    self._fault_locked(f"robot_fault_{state.fault_reason.value}")
                return
            if (
                abs(state.roll) > self.limits.max_tilt_rad
                or abs(state.pitch) > self.limits.max_tilt_rad
            ):
                self._fault_locked("robot_tilt_limit")
                return
            if self._awaiting_stop_confirmation and not self._update_stop_confirmation_locked(
                state, current
            ):
                self._retry_stop_if_due_locked("physical_stop_retry", current)
                if not self._closing and self._lifecycle != ControlLifecycle.FAULTED:
                    self._lifecycle = ControlLifecycle.STOPPING
                return
            if self._lifecycle == ControlLifecycle.ARMING:
                self._lifecycle = ControlLifecycle.IDLE
            target = self._target
            if target is None:
                if not self._state_is_stopped(state) and not self._awaiting_stop_confirmation:
                    self._stop_delivered = False
                self._stop_locked("no_target", raise_on_error=False)
                if self._closing:
                    return
                confirmed = self._update_stop_confirmation_locked(state, current)
                if self._lifecycle != ControlLifecycle.FAULTED:
                    self._lifecycle = (
                        ControlLifecycle.IDLE if confirmed else ControlLifecycle.STOPPING
                    )
                return
            if target.expired(current):
                self._target = None
                self._intent_epoch += 1
                self._watchdog_stops += 1
                self._stop_delivered = False
                self._stop_locked("command_watchdog_expired", raise_on_error=False)
                if self._closing:
                    return
                confirmed = self._update_stop_confirmation_locked(state, current)
                if self._lifecycle != ControlLifecycle.FAULTED:
                    self._lifecycle = (
                        ControlLifecycle.IDLE if confirmed else ControlLifecycle.STOPPING
                    )
                return
            delivery_epoch = self._intent_epoch
            self._updates_in_flight += 1
            try:
                self._call_controller_unlocked(
                    lambda: self.controller.update(target, state, now=current)
                )
            except Exception as error:  # noqa: BLE001 - controller plugins are a fault boundary
                self._updates_in_flight -= 1
                self._fault_locked(f"controller_update_failed: {error}")
                return
            self._updates_in_flight -= 1
            if (
                delivery_epoch != self._intent_epoch
                or self._closing
                or self._emergency_stopped
                or self._lifecycle
                in {
                    ControlLifecycle.FAULTED,
                    ControlLifecycle.EMERGENCY_STOPPED,
                    ControlLifecycle.CLOSING,
                    ControlLifecycle.CLOSED,
                }
            ):
                # An E-stop/stop may have crossed this no-reply update while it
                # was in flight. Deliver a compensating stop after the stale
                # call returns so Move can never be the final transport action.
                self._stop_delivered = False
                self._stop_locked(
                    "command_superseded_during_delivery",
                    force=True,
                    raise_on_error=False,
                )
                if self._lifecycle not in {
                    ControlLifecycle.FAULTED,
                    ControlLifecycle.EMERGENCY_STOPPED,
                    ControlLifecycle.CLOSING,
                    ControlLifecycle.CLOSED,
                }:
                    self._lifecycle = (
                        ControlLifecycle.STOPPING
                        if self._awaiting_stop_confirmation
                        else ControlLifecycle.IDLE
                    )
                return
            completed_at = self._clock()
            if target.expired(completed_at):
                self._target = None
                self._intent_epoch += 1
                self._watchdog_stops += 1
                self._stop_delivered = False
                self._stop_locked(
                    "command_expired_during_delivery",
                    force=True,
                    raise_on_error=False,
                )
                if self._lifecycle != ControlLifecycle.FAULTED:
                    self._lifecycle = (
                        ControlLifecycle.STOPPING
                        if self._awaiting_stop_confirmation
                        else ControlLifecycle.IDLE
                    )
                return
            if not self._state_is_fresh(state, completed_at):
                self._fault_locked("robot_state_stale_during_delivery")
                return
            self._stop_delivered = False
            self._awaiting_stop_confirmation = False
            self._stop_requested_at = None
            self._stop_completed_at = None
            self._stop_feedback_sequence = None
            self._stop_settled_samples = 0
            self._stop_last_settled_sequence = None
            self._lifecycle = ControlLifecycle.ACTIVE

    def stop(self, reason: str = "requested") -> None:
        with self._lock:
            self._target = None
            self._intent_epoch += 1
            if self._starting:
                self._stop_delivered = False
                self._last_stop_reason = reason
                return
            if self._closing or self._lifecycle in {
                ControlLifecycle.DISARMED,
                ControlLifecycle.CLOSING,
                ControlLifecycle.CLOSED,
            }:
                self._last_stop_reason = reason
                return
            current = self._clock()
            state_error: Exception | None = None
            try:
                state = self.state_source.latest()
            except Exception as error:  # noqa: BLE001 - stopping must not depend on feedback
                state = None
                state_error = error
            if state is not None:
                self._last_state = state
            # An explicit operator stop is always delivered. This preserves a
            # useful transport-level stop boundary even when the manager was
            # already idle or did not observe the preceding motion command.
            self._stop_delivered = False
            self._stop_locked(reason)
            if self._closing:
                self._lifecycle = ControlLifecycle.CLOSING
                return
            if state_error is not None:
                self._fault = f"robot_state_read_failed_during_stop: {state_error}"
                self._lifecycle = ControlLifecycle.FAULTED
                return
            if self._lifecycle not in {
                ControlLifecycle.FAULTED,
                ControlLifecycle.EMERGENCY_STOPPED,
            }:
                confirmed = not self._awaiting_stop_confirmation or (
                    state is not None
                    and self._state_is_fresh(state, current)
                    and self._update_stop_confirmation_locked(state, current)
                )
                if self._lifecycle != ControlLifecycle.FAULTED:
                    self._lifecycle = (
                        ControlLifecycle.IDLE if confirmed else ControlLifecycle.STOPPING
                    )

    def emergency_stop(self) -> None:
        with self._lock:
            if self._lifecycle == ControlLifecycle.CLOSED:
                return
            self._target = None
            self._intent_epoch += 1
            if self._emergency_clear_in_flight:
                # A newer E-stop always wins over a clear whose vendor call is
                # currently outside the lifecycle lock.
                self._emergency_stopped = True
                self._emergency_reassert_requested = True
                self._stop_delivered = False
                self._last_stop_reason = "emergency_stop_during_clear"
                return
            if self._emergency_stopped:
                return
            self._emergency_stopped = True
            if self._lifecycle == ControlLifecycle.DISARMED:
                self._last_stop_reason = "emergency_stop_before_start"
                return
            if self._starting:
                self._stop_delivered = False
                self._last_stop_reason = "emergency_stop_during_start"
                return
            if self._closing:
                if self._teardown_committed:
                    self._last_stop_reason = "emergency_stop_after_teardown_commit"
                    return
                self._last_stop_reason = "emergency_stop_during_close"
                if not self._controller_activated:
                    return
                self._launch_emergency_stop_locked()
                return
            self._launch_emergency_stop_locked()

    def clear_emergency_stop(self) -> None:
        with self._lock:
            if self._closing or self._lifecycle in {
                ControlLifecycle.CLOSING,
                ControlLifecycle.CLOSED,
            }:
                raise RuntimeError("control manager is closed")
            if not self._emergency_stopped:
                return
            if self._starting:
                raise ControlNotReadyError("controller startup is still in flight")
            if self._lifecycle == ControlLifecycle.DISARMED:
                self._emergency_stopped = False
                self._fault = None
                self._last_stop_reason = "emergency_stop_cleared_before_start"
                return
            if self._emergency_in_flight:
                raise ControlNotReadyError("emergency stop delivery is still in flight")
            if self._updates_in_flight:
                raise ControlNotReadyError("a superseded controller update is still in flight")
            if self.controller.capabilities.requires_stop_confirmation:
                state = self.state_source.latest()
                current = self._clock()
                if not self._state_is_fresh(state, current):
                    raise ControlNotReadyError(
                        "cannot clear emergency stop without fresh feedback"
                    )
                assert state is not None
                self._last_state = state
                if (
                    self._awaiting_stop_confirmation
                    and not self._update_stop_confirmation_locked(state, current)
                ) or not self._state_is_stopped(state):
                    raise ControlNotReadyError(
                        "cannot clear emergency stop until physical stopping is confirmed"
                    )
            self._emergency_clear_in_flight = True
            self._emergency_reassert_requested = False
            try:
                self._call_controller_unlocked(self.controller.clear_emergency_stop)
            except Exception:
                self._emergency_clear_in_flight = False
                self._condition.notify_all()
                if self._emergency_reassert_requested and not self._teardown_committed:
                    self._emergency_reassert_requested = False
                    self._launch_emergency_stop_locked()
                raise
            superseded = self._emergency_reassert_requested or self._closing
            self._emergency_clear_in_flight = False
            self._condition.notify_all()
            if superseded:
                reassert = self._emergency_reassert_requested
                self._emergency_reassert_requested = False
                self._emergency_stopped = True
                self._stop_delivered = False
                if reassert and not self._teardown_committed:
                    self._launch_emergency_stop_locked()
                    raise RuntimeError("emergency stop was reasserted while clearing")
                raise RuntimeError("control manager began closing while clearing emergency stop")
            self._target = None
            self._intent_epoch += 1
            self._emergency_stopped = False
            self._fault = None
            self._stop_delivered = True
            self._awaiting_stop_confirmation = False
            self._stop_requested_at = None
            self._stop_completed_at = None
            self._stop_feedback_sequence = None
            self._stop_settled_samples = 0
            self._stop_last_settled_sequence = None
            self._last_stop_attempt_at = None
            self._last_stop_reason = "emergency_stop_cleared"
            self._lifecycle = ControlLifecycle.IDLE

    def clear_fault(self) -> None:
        with self._lock:
            if self._closing or self._lifecycle in {
                ControlLifecycle.CLOSING,
                ControlLifecycle.CLOSED,
            }:
                raise RuntimeError("control manager is closed")
            if self._lifecycle != ControlLifecycle.FAULTED:
                return
            state = self.state_source.latest()
            current = self._clock()
            if not self._state_is_fresh(state, current):
                raise ControlNotReadyError("cannot clear controller fault without fresh feedback")
            assert state is not None
            self._last_state = state
            if state.fault_reason is not FaultReason.NONE:
                raise ControlNotReadyError(
                    "cannot clear controller fault while robot reports an error"
                )
            if (
                self._awaiting_stop_confirmation
                and not self._update_stop_confirmation_locked(state, current)
            ) or not self._state_is_stopped(state):
                raise ControlNotReadyError(
                    "cannot clear controller fault until physical stopping is confirmed"
                )
            self._target = None
            self._intent_epoch += 1
            self._fault = None
            self._stop_delivered = True
            self._awaiting_stop_confirmation = False
            self._stop_requested_at = None
            self._stop_completed_at = None
            self._stop_feedback_sequence = None
            self._stop_settled_samples = 0
            self._stop_last_settled_sequence = None
            self._last_stop_attempt_at = None
            self._last_stop_reason = "fault_cleared"
            self._lifecycle = ControlLifecycle.IDLE

    def snapshot(self, *, now: float | None = None) -> ControllerStatus:
        current = self._clock() if now is None else float(now)
        with self._lock:
            target = self._target
            state = self._last_state
            if state is None:
                try:
                    state = self.state_source.latest()
                except Exception:  # noqa: BLE001 - fault telemetry must remain observable
                    state = None
            return ControllerStatus(
                lifecycle=self._lifecycle,
                controller=self.controller.name,
                target=target.command if target is not None else VelocityCommand(),
                measured=state.velocity if state is not None else VelocityCommand(),
                target_source=target.source if target is not None else None,
                target_sequence=target.sequence if target is not None else None,
                command_age_ms=(
                    round(max(0.0, current - target.issued_at) * 1000.0, 3)
                    if target is not None
                    else None
                ),
                feedback_age_ms=(
                    round(max(0.0, current - state.received_at) * 1000.0, 3)
                    if state is not None
                    else None
                ),
                watchdog_stops=self._watchdog_stops,
                last_stop_reason=self._last_stop_reason,
                fault=self._fault,
                emergency_stopped=self._emergency_stopped,
                stop_confirmed=self._stop_delivered
                and not self._awaiting_stop_confirmation,
            )

    def close(self) -> None:
        deadline = time.monotonic() + self.timing.io_quiesce_timeout_s
        requires_confirmation = self.controller.capabilities.requires_stop_confirmation
        with self._lock:
            if self._lifecycle == ControlLifecycle.CLOSED:
                return
            if self._closing:
                while self._close_in_progress and self._lifecycle != ControlLifecycle.CLOSED:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.0:
                        raise ControlNotReadyError("control manager close is still in progress")
                    self._condition.wait(min(0.01, remaining))
                if self._lifecycle == ControlLifecycle.CLOSED:
                    return
                # A prior close attempt timed out waiting for a bounded plugin
                # call. The irreversible closing latch remains, but this caller
                # may resume teardown once that call has returned.
                was_disarmed = False
            else:
                was_disarmed = self._lifecycle == ControlLifecycle.DISARMED
                self._closing = True
            self._close_in_progress = True
            self._lifecycle = ControlLifecycle.CLOSING
            self._target = None
            self._intent_epoch += 1
            if self._emergency_clear_in_flight:
                self._stop_delivered = False
            self._condition.notify_all()

        # Do not tear a controller down under an activation, update, E-stop,
        # or clear call. Once quiescent, the closing latch prevents any new one.
        in_flight_unresolved = False
        while not was_disarmed:
            with self._lock:
                busy = (
                    self._starting
                    or self._emergency_clear_in_flight
                    or self._controller_calls_in_flight > 0
                )
                if not busy:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    in_flight_unresolved = True
                    break
                self._condition.wait(min(0.01, remaining))

        if in_flight_unresolved:
            with self._lock:
                self._fault = "controller_call_in_flight_during_close"
                self._last_stop_reason = "controller_call_in_flight_during_close"
                self._lifecycle = ControlLifecycle.CLOSING
                self._close_in_progress = False
                self._condition.notify_all()
            raise ControlNotReadyError(
                "controller call did not quiesce before close; retry close after it returns"
            )

        # Quiescence and physical stop confirmation each receive their own
        # bounded interval; slow passive activation cannot consume the stop
        # feedback budget.
        deadline = time.monotonic() + self.timing.stop_timeout_s

        with self._lock:
            if not was_disarmed:
                try:
                    state = self.state_source.latest()
                except Exception:  # noqa: BLE001 - final stop does not depend on feedback
                    state = None
                if state is not None:
                    self._last_state = state
                    if self._state_is_fresh(state, self._clock()) and not self._state_is_stopped(
                        state
                    ):
                        self._stop_delivered = False
                if not self._stop_delivered:
                    self._stop_locked(
                        "manager_closed",
                        force=True,
                        raise_on_error=False,
                    )
                self._lifecycle = ControlLifecycle.CLOSING

        while not was_disarmed:
            with self._lock:
                stop_done = self._stop_delivered and (
                    not requires_confirmation or not self._awaiting_stop_confirmation
                )
                if stop_done:
                    break
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                break
            if self._thread is None or not self._thread.is_alive():
                try:
                    self.tick()
                except Exception:  # noqa: BLE001, S110 - final fault is recorded below
                    pass
            time.sleep(min(0.01, remaining))

        # Freeze the close retry loop, then wait once more for a StopMove that
        # may have crossed the feedback deadline. Plugin teardown never races a
        # manager-owned controller call.
        with self._lock:
            self._tearing_down = True
            self._stop_event.set()
            if was_disarmed:
                self._teardown_committed = True
        final_io_deadline = time.monotonic() + self.timing.io_quiesce_timeout_s
        final_io_unresolved = False
        while not was_disarmed:
            with self._lock:
                if self._controller_calls_in_flight == 0:
                    self._teardown_committed = True
                    break
                remaining = final_io_deadline - time.monotonic()
                if remaining <= 0.0:
                    final_io_unresolved = True
                    break
                self._condition.wait(min(0.01, remaining))

        if final_io_unresolved:
            with self._lock:
                self._fault = "controller_call_in_flight_during_close"
                self._last_stop_reason = "controller_call_in_flight_during_close"
                self._lifecycle = ControlLifecycle.CLOSING
                self._tearing_down = False
                self._close_in_progress = False
                self._condition.notify_all()
            raise ControlNotReadyError(
                "controller call did not quiesce before close; retry close after it returns"
            )

        with self._lock:
            if self._awaiting_stop_confirmation:
                try:
                    final_state = self.state_source.latest()
                except Exception:  # noqa: BLE001 - reflected as unconfirmed below
                    final_state = None
                final_now = self._clock()
                if self._state_is_fresh(final_state, final_now):
                    assert final_state is not None
                    self._last_state = final_state
                    self._update_stop_confirmation_locked(final_state, final_now)
            stop_unconfirmed = (
                requires_confirmation and not was_disarmed and self._awaiting_stop_confirmation
            )
            stop_delivery_failed = not was_disarmed and not self._stop_delivered
            if stop_delivery_failed:
                self._fault = "stop_delivery_failed_during_close"
                self._last_stop_reason = "stop_delivery_failed_during_close"
            elif stop_unconfirmed:
                self._fault = "physical_stop_not_confirmed_during_close"
                self._last_stop_reason = "physical_stop_not_confirmed_during_close"
            self._stop_event.set()
        join_error: RuntimeError | None = None
        control_thread = self._thread
        emergency_thread = self._emergency_thread
        for thread, timeout in (
            (control_thread, max(1.0, self.timing.period_s * 5.0)),
            (emergency_thread, max(1.0, self.timing.stop_timeout_s)),
        ):
            if (
                thread is None
                or thread is threading.current_thread()
                or thread.ident is None
            ):
                continue
            try:
                thread.join(timeout=timeout)
            except RuntimeError as error:
                join_error = join_error or error
        close_error: Exception | None = None
        try:
            self.controller.close()
        except Exception as error:  # noqa: BLE001 - always release feedback resources
            close_error = error
        finally:
            try:
                self.state_source.close()
            finally:
                with self._lock:
                    self._lifecycle = ControlLifecycle.CLOSED
                    self._controller_activated = False
                    self._tearing_down = False
                    self._teardown_committed = True
                    self._close_in_progress = False
                    self._condition.notify_all()
        if close_error is not None:
            raise close_error
        if join_error is not None:
            raise join_error
        if stop_delivery_failed:
            raise ControlNotReadyError("stop delivery failed before controller close")
        if stop_unconfirmed:
            raise ControlNotReadyError("physical stop was not confirmed before controller close")

    def _run(self) -> None:
        next_tick = self._clock()
        while not self._stop_event.is_set():
            try:
                self.tick()
            except BaseException as error:  # noqa: BLE001 - never silently lose the watchdog
                with self._lock:
                    if self._closing:
                        self._fault = f"control_loop_failed_during_close: {error}"
                    elif self._lifecycle == ControlLifecycle.EMERGENCY_STOPPED:
                        self._fault = f"control_loop_failed: {error}"
                        self._retry_stop_if_due_locked(
                            "emergency_stop_control_loop_failed",
                            self._clock(),
                        )
                    elif self._lifecycle not in {
                        ControlLifecycle.DISARMED,
                        ControlLifecycle.CLOSED,
                    }:
                        self._fault_locked(f"control_loop_failed: {error}")
            next_tick += self.timing.period_s
            delay = max(0.0, next_tick - self._clock())
            self._stop_event.wait(delay)

    def _start_thread_locked(self) -> None:
        thread = threading.Thread(
            target=self._run,
            name=f"parcel-{self.controller.name}-control",
            daemon=True,
        )
        self._thread = thread
        try:
            thread.start()
        except BaseException as error:
            if thread.ident is None:
                self._thread = None
            self._fault_locked(f"control_thread_start_failed: {error}")
            raise

    def _state_is_fresh(self, state: RobotMotionState | None, now: float) -> bool:
        if state is None:
            return False
        age = now - state.received_at
        return -0.05 <= age < self.timing.state_timeout_s

    def _stop_locked(
        self,
        reason: str,
        *,
        force: bool = False,
        raise_on_error: bool = True,
    ) -> bool:
        self._last_stop_reason = reason
        if self._stop_delivered and not force:
            return True
        attempted_at = self._clock()
        self._last_stop_attempt_at = attempted_at
        self._awaiting_stop_confirmation = True
        if self._stop_requested_at is None:
            self._stop_requested_at = attempted_at
            self._stop_completed_at = None
            self._stop_feedback_sequence = (
                self._last_state.sequence if self._last_state is not None else None
            )
            self._stop_settled_samples = 0
            self._stop_last_settled_sequence = None
        delivery_generation = self._begin_stop_delivery_locked()
        try:
            self._call_controller_unlocked(lambda: self.controller.stop(reason))
        except Exception as error:
            failure_is_current = delivery_generation == self._stop_delivery_generation
            if failure_is_current:
                self._fault = f"controller_stop_failed: {error}"
                self._stop_delivered = False
                if (
                    not self._emergency_stopped
                    and not self._closing
                    and self._lifecycle != ControlLifecycle.CLOSED
                ):
                    self._lifecycle = ControlLifecycle.FAULTED
            if raise_on_error:
                raise
            return not failure_is_current
        self._complete_stop_delivery_locked(delivery_generation, reason=reason)
        return True

    def _fault_locked(self, reason: str) -> None:
        self._target = None
        self._intent_epoch += 1
        self._fault = reason
        self._last_stop_reason = reason
        self._stop_delivered = False
        self._awaiting_stop_confirmation = True
        if self._stop_requested_at is None:
            self._stop_requested_at = self._clock()
            self._stop_completed_at = None
            self._stop_feedback_sequence = (
                self._last_state.sequence if self._last_state is not None else None
            )
            self._stop_settled_samples = 0
            self._stop_last_settled_sequence = None
        stopped = self._stop_locked(reason, force=True, raise_on_error=False)
        if not stopped:
            stop_fault = self._fault
            self._fault = f"{reason}; {stop_fault}"
        if not self._closing:
            self._lifecycle = (
                ControlLifecycle.EMERGENCY_STOPPED
                if self._emergency_stopped
                else ControlLifecycle.FAULTED
            )

    def _retry_stop_if_due_locked(self, reason: str, now: float) -> None:
        # Once teardown is frozen, no feedback path may create fresh vendor I/O.
        # In particular, a late manual tick can overlap controller.close() even
        # after the close path has passed its final in-flight-call barrier.
        if self._tearing_down or self._teardown_committed:
            return
        last_attempt = self._last_stop_attempt_at
        if last_attempt is not None and now - last_attempt < self.timing.stop_retry_s:
            return
        self._stop_delivered = False
        self._stop_locked(reason, force=True, raise_on_error=False)

    def _call_controller_unlocked(self, call):
        """Run vendor I/O without blocking lifecycle/E-stop state transitions.

        The caller must hold ``_lock`` exactly once. After an update returns,
        its captured intent epoch is checked and a compensating stop is sent if
        a stop crossed the call while it was in flight.
        """

        self._controller_calls_in_flight += 1
        self._lock.release()
        try:
            return call()
        finally:
            self._lock.acquire()
            self._controller_calls_in_flight -= 1
            self._condition.notify_all()

    def _launch_emergency_stop_locked(self) -> None:
        self._awaiting_stop_confirmation = True
        requested_at = self._clock()
        self._stop_requested_at = requested_at
        self._stop_completed_at = None
        self._stop_feedback_sequence = (
            self._last_state.sequence if self._last_state is not None else None
        )
        self._stop_settled_samples = 0
        self._stop_last_settled_sequence = None
        self._last_stop_attempt_at = requested_at
        self._stop_delivered = False
        self._emergency_in_flight = True
        self._controller_calls_in_flight += 1
        delivery_generation = self._begin_stop_delivery_locked()
        if not self._closing:
            self._lifecycle = ControlLifecycle.EMERGENCY_STOPPED
        self._emergency_thread = threading.Thread(
            target=self._deliver_emergency_stop,
            args=(delivery_generation,),
            name=f"parcel-{self.controller.name}-emergency-stop",
            daemon=True,
        )
        try:
            self._emergency_thread.start()
        except BaseException as error:
            self._emergency_in_flight = False
            self._controller_calls_in_flight -= 1
            self._emergency_thread = None
            self._condition.notify_all()
            self._fault = f"emergency_stop_thread_failed: {error}"
            self._stop_locked(
                "emergency_stop_thread_failed",
                force=True,
                raise_on_error=False,
            )
            if not isinstance(error, RuntimeError):
                raise

    def _deliver_emergency_stop(self, delivery_generation: int) -> None:
        error: Exception | None = None
        try:
            self.controller.emergency_stop()
        except BaseException as caught:  # noqa: BLE001 - E-stop must contain plugin failures
            error = caught
        with self._lock:
            self._emergency_in_flight = False
            self._controller_calls_in_flight -= 1
            self._condition.notify_all()
            if delivery_generation != self._stop_delivery_generation:
                # A later StopMove superseded this call after it physically
                # returned but before this worker reacquired the lifecycle
                # lock. Its delayed bookkeeping must not move the feedback
                # boundary forward or invalidate the newer successful stop.
                return
            if error is None:
                self._complete_stop_delivery_locked(
                    delivery_generation,
                    reason="emergency_stop",
                )
            else:
                self._fault = f"emergency_stop_failed: {error}"
                self._stop_delivered = False

    def _begin_stop_delivery_locked(self) -> int:
        self._stop_delivery_generation += 1
        return self._stop_delivery_generation

    def _complete_stop_delivery_locked(
        self,
        delivery_generation: int,
        *,
        reason: str,
    ) -> bool:
        if delivery_generation != self._stop_delivery_generation:
            return False
        self._last_stop_reason = reason
        self._stop_delivered = True
        self._mark_stop_completed_locked()
        return True

    def _mark_stop_completed_locked(self) -> None:
        self._stop_completed_at = self._clock()
        try:
            latest = self.state_source.latest()
        except Exception:  # noqa: BLE001 - delivery succeeded; retain the prior boundary
            latest = None
        if latest is not None:
            self._last_state = latest
            if (
                self._stop_feedback_sequence is None
                or latest.sequence > self._stop_feedback_sequence
            ):
                self._stop_feedback_sequence = latest.sequence
        self._stop_settled_samples = 0
        self._stop_last_settled_sequence = None
        if not self.controller.capabilities.requires_stop_confirmation:
            self._clear_stop_confirmation_locked()

    def _update_stop_confirmation_locked(
        self,
        state: RobotMotionState,
        now: float,
    ) -> bool:
        if not self._awaiting_stop_confirmation:
            return True
        if not self.controller.capabilities.requires_stop_confirmation:
            self._clear_stop_confirmation_locked()
            return True
        is_post_stop = (
            self._stop_completed_at is not None
            and state.received_at > self._stop_completed_at
            and (
                self._stop_feedback_sequence is None
                or state.sequence > self._stop_feedback_sequence
            )
        )
        if is_post_stop and self._state_is_stopped(state):
            if state.sequence != self._stop_last_settled_sequence:
                self._stop_settled_samples += 1
                self._stop_last_settled_sequence = state.sequence
            if self._stop_settled_samples < self.timing.stop_settled_samples:
                return False
            self._clear_stop_confirmation_locked()
            return True
        if is_post_stop:
            self._stop_settled_samples = 0
            self._stop_last_settled_sequence = None
        requested_at = self._stop_requested_at if self._stop_requested_at is not None else now
        if now - requested_at >= self.timing.stop_timeout_s:
            self._fault = "physical_stop_not_confirmed"
            self._last_stop_reason = "physical_stop_not_confirmed"
            if not self._emergency_stopped and not self._closing:
                self._lifecycle = ControlLifecycle.FAULTED
        return False

    def _clear_stop_confirmation_locked(self) -> None:
        self._awaiting_stop_confirmation = False
        self._stop_requested_at = None
        self._stop_completed_at = None
        self._stop_feedback_sequence = None
        self._stop_settled_samples = 0
        self._stop_last_settled_sequence = None
        self._last_stop_attempt_at = None
        self._condition.notify_all()

    def _state_is_stopped(self, state: RobotMotionState) -> bool:
        return (
            math.hypot(state.velocity.vx, state.velocity.vy) <= self.timing.settled_linear_speed_mps
            and abs(state.velocity.vyaw) <= self.timing.settled_yaw_speed_rad_s
        )


def _is_zero(command: VelocityCommand) -> bool:
    return all(abs(value) <= 1e-9 for value in (command.vx, command.vy, command.vyaw))
