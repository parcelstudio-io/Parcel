"""Verified nonblocking commissioned gateway state cache."""

from __future__ import annotations

import math
import threading
import time

from parcel_robot.bridge.gateway_client import MotionStateV2
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.models import VelocityCommand

from .models import FaultReason, RobotMotionState
from .motion_gateway_common import (
    CommissionedGatewayError,
    StateObserver,
    low_state_payload_without_age,
    sport_payload_without_age,
)
from .motion_gateway_session import _CommissionedGatewaySessionV1


class CommissionedGatewayStateSourceV1:
    """Nonblocking cache of verified gateway feedback.

    The gateway client is a serialized request/response transport. Calling it
    from :meth:`latest` used to put a socket timeout inside the
    :class:`ControlManager` tick lock. This source instead owns a bounded
    background poller. The shared commissioned session publishes *every*
    verified state read into this cache, including reads performed while
    fencing arm, command, and stop transactions.

    ``latest()`` takes only the cache lock. Re-polls return the same
    :class:`RobotMotionState` object with its original conservative receipt
    timestamp, so delayed I/O naturally ages the evidence into staleness. No
    host timestamp or Sport sequence is synthesized to keep a sample fresh.
    ``RobotMotionState.sequence`` orders the adapter's merged Sport/LowState
    output; both unchanged wire sequences are retained in ``vendor_extra``.
    """

    name = "motion_gateway_commissioned_state"
    origin = EvidenceOrigin.UNKNOWN

    def __init__(
        self,
        session: _CommissionedGatewaySessionV1,
        *,
        poll_interval_s: float = 0.02,
        shutdown_timeout_s: float = 1.0,
    ) -> None:
        interval = float(poll_interval_s)
        shutdown_timeout = float(shutdown_timeout_s)
        if not math.isfinite(interval) or interval <= 0.0:
            raise ValueError("gateway state poll_interval_s must be positive and finite")
        if not math.isfinite(shutdown_timeout) or shutdown_timeout <= 0.0:
            raise ValueError("gateway state shutdown_timeout_s must be positive and finite")
        self._session = session
        self._closed = False
        self._lock = threading.Lock()
        self._started = False
        self._starting = False
        self._poll_interval_s = interval
        self._shutdown_timeout_s = shutdown_timeout
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._terminal_error: str | None = None
        self._last_wire_state: MotionStateV2 | None = None
        self._last_motion_state: RobotMotionState | None = None
        self._wire_observer: StateObserver = self._accept_wire_state
        register = getattr(session, "register_state_observer", None)
        self._session_publishes_state = callable(register)
        if self._session_publishes_state:
            register(self._wire_observer)

    @property
    def poller_alive(self) -> bool:
        """Whether the background state reader is currently alive."""

        with self._lock:
            thread = self._poll_thread
            return thread is not None and thread.is_alive()

    @property
    def poll_error(self) -> str | None:
        """Terminal poll/ordering failure, if one has occurred."""

        with self._lock:
            return self._terminal_error

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise CommissionedGatewayError("the commissioned gateway state source is closed")
            if self._terminal_error is not None:
                raise CommissionedGatewayError(self._terminal_error)
            if self._started:
                return
            if self._starting:
                raise CommissionedGatewayError(
                    "the commissioned gateway state source is already starting"
                )
            self._starting = True
        try:
            connect = getattr(self._session, "connect", None)
            if callable(connect):
                connect()
            elif not bool(getattr(self._session, "connected", False)):
                raise CommissionedGatewayError(
                    "the commissioned gateway state session is not connected"
                )

            # Production connect publishes its attested state through the
            # registered observer. Small test/commissioning sessions without
            # that hook receive one synchronous seed at this lifecycle seam.
            if not self._session_publishes_state:
                query_started_at = time.monotonic()
                self._accept_wire_state(self._session.state(), query_started_at)
            with self._lock:
                if self._last_motion_state is None:
                    raise CommissionedGatewayError(
                        "gateway connect produced no verified state sample"
                    )
                if self._closed:
                    raise CommissionedGatewayError(
                        "the commissioned gateway state source closed during start"
                    )
                self._stop_event.clear()
                thread = threading.Thread(
                    target=self._poll,
                    name="parcel-motion-gateway-state-poll",
                    daemon=True,
                )
                self._poll_thread = thread
                self._started = True
                self._starting = False
                thread.start()
        except BaseException as error:
            with self._lock:
                self._starting = False
                if isinstance(error, Exception) and self._terminal_error is None:
                    self._terminal_error = str(error) or type(error).__name__
            self._stop_event.set()
            raise

    def latest(self) -> RobotMotionState | None:
        """Return cached evidence without performing gateway or session I/O."""

        with self._lock:
            if self._closed:
                return None
            if self._terminal_error is not None:
                raise CommissionedGatewayError(self._terminal_error)
            return self._last_motion_state

    def _accept_wire_state(self, state: MotionStateV2, query_started_at: float) -> None:
        """Validate ordering and atomically publish one verified wire sample."""

        try:
            if not isinstance(state, MotionStateV2):
                raise CommissionedGatewayError(
                    "commissioned gateway state cache requires MotionStateV2"
                )
            self._accept_wire_state_locked(state, query_started_at)
        except Exception as error:
            with self._lock:
                if not self._closed and self._terminal_error is None:
                    self._terminal_error = str(error) or type(error).__name__
            self._stop_event.set()
            raise

    def _accept_wire_state_locked(
        self,
        state: MotionStateV2,
        query_started_at: float,
    ) -> None:
        """Publish under ``_lock``; caller records any terminal exception."""

        with self._lock:
            if self._closed:
                return
            if self._terminal_error is not None:
                raise CommissionedGatewayError(self._terminal_error)
            previous_wire = self._last_wire_state
            previous_motion = self._last_motion_state
            if not self._wire_state_advanced(state, previous_wire, previous_motion):
                return
            adapted = self._adapt_wire_state(
                state,
                query_started_at=query_started_at,
                previous_wire=previous_wire,
                previous_motion=previous_motion,
            )
            self._last_wire_state = state
            self._last_motion_state = adapted

    @staticmethod
    def _wire_state_advanced(
        state: MotionStateV2,
        previous_wire: MotionStateV2 | None,
        previous_motion: RobotMotionState | None,
    ) -> bool:
        same_epoch = previous_wire is not None and state.boot_epoch == previous_wire.boot_epoch
        if same_epoch and state.state_sequence < previous_wire.state_sequence:
            raise CommissionedGatewayError("gateway Sport state sequence regressed")
        if same_epoch and state.low_state_sequence < previous_wire.low_state_sequence:
            raise CommissionedGatewayError("gateway LowState sequence regressed")
        if (
            same_epoch
            and state.low_state_sequence == previous_wire.low_state_sequence
            and low_state_payload_without_age(state) != low_state_payload_without_age(previous_wire)
        ):
            raise CommissionedGatewayError(
                "gateway changed LowState payload without advancing its sequence"
            )
        same_sport_sample = (
            same_epoch
            and previous_motion is not None
            and state.state_sequence == previous_wire.state_sequence
        )
        if not same_sport_sample:
            return True
        if sport_payload_without_age(state) != sport_payload_without_age(previous_wire):
            raise CommissionedGatewayError(
                "gateway changed feedback payload without advancing state_sequence"
            )
        return state.low_state_sequence != previous_wire.low_state_sequence

    def _adapt_wire_state(
        self,
        state: MotionStateV2,
        *,
        query_started_at: float,
        previous_wire: MotionStateV2 | None,
        previous_motion: RobotMotionState | None,
    ) -> RobotMotionState:
        same_sport_sample = (
            previous_wire is not None
            and previous_motion is not None
            and state.boot_epoch == previous_wire.boot_epoch
            and state.state_sequence == previous_wire.state_sequence
        )
        received_at = (
            previous_motion.received_at
            if same_sport_sample
            else query_started_at - float(state.state_age_ms) / 1000.0
        )
        if not math.isfinite(received_at):
            raise CommissionedGatewayError("gateway feedback age produced a non-finite timestamp")
        output_sequence = (
            state.state_sequence
            if previous_motion is None
            else max(previous_motion.sequence + 1, state.state_sequence)
        )
        return RobotMotionState(
            received_at=received_at,
            sequence=output_sequence,
            roll=state.vendor_rpy_rad[0],
            pitch=state.vendor_rpy_rad[1],
            velocity=VelocityCommand(
                vx=state.vx_mps,
                vy=state.vy_mps,
                vyaw=state.vyaw_rad_s,
            ),
            mode=state.mode,
            error_code=(0 if state.feedback_integrity_ok is True else state.error_code),
            source=self.name,
            fault_reason=self._fault_reason(state),
            vendor_extra=self._vendor_extra(state, output_sequence=output_sequence),
            origin=self.origin,
            source_time_s=state.source_time_s,
            session_epoch=self._session.session_epoch,
        )

    @staticmethod
    def _fault_reason(state: MotionStateV2) -> FaultReason:
        if state.feedback_integrity_ok is False:
            return FaultReason.VENDOR_FAULT
        if state.commissioned_soc_ok is False:
            return FaultReason.POWER
        return FaultReason.COMMS if state.phase == "latched" else FaultReason.NONE

    def _vendor_extra(
        self,
        state: MotionStateV2,
        *,
        output_sequence: int,
    ) -> tuple[tuple[str, object], ...]:
        return (
            self._sport_vendor_extra(state, output_sequence=output_sequence)
            + self._low_state_vendor_extra(state)
            + (
                (
                    "gateway_commissioning_record_id",
                    self._session.commissioning_record_id,
                ),
            )
        )

    @staticmethod
    def _sport_vendor_extra(
        state: MotionStateV2,
        *,
        output_sequence: int,
    ) -> tuple[tuple[str, object], ...]:
        return (
            ("gateway_boot_epoch", state.boot_epoch),
            ("gateway_phase", state.phase),
            ("gateway_body_kind", state.body_kind.value),
            ("gateway_writer_id", state.writer_id),
            ("gateway_state_sequence", str(state.state_sequence)),
            ("gateway_cache_sequence", str(output_sequence)),
            ("gateway_last_stop_sequence", str(state.last_stop_sequence)),
            ("gateway_last_stop_reason", state.last_stop_reason),
            (
                "unitree_feedback_integrity_ok",
                (
                    "unavailable"
                    if state.feedback_integrity_ok is None
                    else str(state.feedback_integrity_ok).lower()
                ),
            ),
            ("unitree_feedback_integrity_reason", state.feedback_integrity_reason),
            ("unitree_sport_error_code_raw", str(state.error_code)),
            (
                "unitree_commissioned_soc_ok",
                (
                    "unavailable"
                    if state.commissioned_soc_ok is None
                    else str(state.commissioned_soc_ok).lower()
                ),
            ),
            ("unitree_commissioned_soc_reason", state.commissioned_soc_reason),
            (
                "unitree_vendor_position_m",
                ",".join(str(value) for value in state.vendor_position_m),
            ),
            (
                "unitree_vendor_rpy_rad",
                ",".join(str(value) for value in state.vendor_rpy_rad),
            ),
            (
                "unitree_sport_foot_force_raw_unordered",
                ",".join(str(value) for value in state.sport_foot_force_raw),
            ),
        )

    @staticmethod
    def _low_state_vendor_extra(
        state: MotionStateV2,
    ) -> tuple[tuple[str, object], ...]:
        return (
            ("unitree_low_state_sequence", str(state.low_state_sequence)),
            ("unitree_low_state_tick_raw", str(state.low_state_tick)),
            ("unitree_battery_soc_percent", str(state.battery_soc_percent)),
            ("unitree_power_v", str(state.power_v)),
            ("unitree_power_a", str(state.power_a)),
            (
                "unitree_max_motor_temperature_raw",
                str(state.max_motor_temperature_raw),
            ),
            ("unitree_motor_lost_max_raw", str(state.motor_lost_max_raw)),
            (
                "unitree_foot_force_est_raw",
                ",".join(str(value) for value in state.foot_force_est_raw),
            ),
            ("unitree_imu_temperature_raw", str(state.imu_temperature_raw)),
            (
                "unitree_temperature_ntc_raw",
                ",".join(str(value) for value in state.temperature_ntc_raw),
            ),
            ("unitree_bms_status_raw", str(state.bms_status)),
        )

    def _poll(self) -> None:
        """Perform bounded state exchanges off the manager's control thread."""

        while not self._stop_event.wait(self._poll_interval_s):
            query_started_at = time.monotonic()
            try:
                safe_poll = getattr(self._session, "state_if_disarmed", None)
                state = safe_poll() if callable(safe_poll) else self._session.state()
                if self._stop_event.is_set():
                    return
                if state is not None and not self._session_publishes_state:
                    self._accept_wire_state(state, query_started_at)
            except Exception as error:  # noqa: BLE001 - any poll failure is terminal
                with self._lock:
                    if self._closed or self._stop_event.is_set():
                        return
                    if self._terminal_error is None:
                        self._terminal_error = (
                            f"gateway state poll failed: {str(error) or type(error).__name__}"
                        )
                self._stop_event.set()
                return

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._started = False
            self._stop_event.set()
            thread = self._poll_thread
        unregister = getattr(self._session, "unregister_state_observer", None)
        if callable(unregister):
            unregister(self._wire_observer)

        # Socket operations carry their own timeout. Give an in-flight poll its
        # full configured budget before closing the shared session. Normal
        # ControlManager teardown has already closed the controller's side and
        # returns immediately here.
        if (
            thread is not None
            and thread is not threading.current_thread()
            and thread.ident is not None
        ):
            thread.join(timeout=self._shutdown_timeout_s)
        self._session.close()
        if (
            thread is not None
            and thread is not threading.current_thread()
            and thread.ident is not None
            and thread.is_alive()
        ):
            thread.join(timeout=self._shutdown_timeout_s)
        if thread is not None and thread.is_alive():
            raise CommissionedGatewayError(
                "gateway state poller did not stop within its bounded shutdown window"
            )
