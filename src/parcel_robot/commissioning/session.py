"""The armed commissioning session: journal, read-only observer, one-axis steps.

Card W0-B. This is the *measurement* path for supervised hardware bring-up. It
exists because ``control/factory.py`` requires ``enable_lease`` /
``axes_commissioned`` / ``state_frame_commissioned`` / ``allowed_modes`` to be
true before it will build anything, and those four flags are precisely what a
commissioning run is supposed to establish — so the normal path cannot bootstrap
itself without pre-claiming its own conclusion.

The three structural rules this module enforces:

* **It cannot enter the autonomous runtime.** :class:`CommissioningSession` is
  not a ``ControlManager`` and does not expose one. It holds its manager in a
  private attribute, offers no ``set_target``/``tick``/``state_source`` surface,
  and is not registered in the controller registry, so
  ``create_control_manager`` can never return one. Nothing in ``parcel_robot``
  outside this package and the one lazily-imported builder in
  ``control/factory.py`` imports it, and this package imports no runtime module.
* **Every default refuses.** No arming token, no motion. No observed modes, no
  motion. Wrong process, expired token, two axes, out-of-band speed, over-long
  duration or TTL: refused, never clamped.
* **Failure latches.** Interruption, feedback loss, a foreign writer, a
  controller fault, an unconfirmed stop, or a previous process that died
  mid-session all latch permanently. A latched session refuses everything
  afterwards, its record can only say ``failed``, and its journal is poisoned so
  a re-run on the same journal latches again instead of quietly starting over.

Durability: the journal is an fsync'd append-only JSONL file. It is the only
part of a session that survives ``kill -9``, which is what makes "process exit
produces a latched failure" enforceable rather than aspirational.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import time
import uuid
from collections.abc import Iterable, Sequence
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from parcel_robot.control.manager import ControlNotReadyError
from parcel_robot.control.models import ControlLifecycle, RobotMotionState

from .limits import (
    COMMISSIONING_SOURCE,
    DEFAULT_MAX_DURATION_S,
    MAX_TTL_S,
    CommissioningArming,
    CommissioningAxis,
    CommissioningLatchedError,
    CommissioningLimits,
    CommissioningRefusedError,
    LatchReason,
    RefusalReason,
    assert_commissioning_command,
    assert_commissioning_duration,
    assert_commissioning_ttl,
    single_axis_command,
)
from .record import (
    AxisSignEvidence,
    CommissioningRecordV1,
    ObservationEvidence,
    ObservedDirection,
    RecordOutcome,
    StopEvidence,
    artifact_hashes_for,
    sha256_bytes,
)

if TYPE_CHECKING:  # pragma: no cover - annotations only; never evaluated at runtime
    from typing import Self

JOURNAL_SCHEMA = "parcel.commissioning.journal.v1"

#: Command-renewal and feedback-sampling period inside a step. Derived: one
#: production control period (``ControlTiming.control_hz`` 50 Hz -> 0.02 s)
#: halved, so the commissioning driver never becomes the slow link in the
#: 50 Hz loop it is feeding, and a 0.15 s step still yields >10 samples.
_DRIVE_POLL_S = 0.01


class JournalState(str, Enum):
    """Durable session state. Only ``COMPLETE`` may be followed by nothing."""

    OPENED = "opened"
    ARMED = "armed"
    MOVING = "moving"
    SETTLING = "settling"
    IDLE = "idle"
    LATCHED = "latched"
    COMPLETE = "complete"


#: A journal whose last line is one of these was not abandoned mid-run.
TERMINAL_JOURNAL_STATES = frozenset({JournalState.LATCHED, JournalState.COMPLETE})


class CommissioningJournal:
    """Append-only, fsync'd record of what a session did, line by line."""

    def __init__(self, path: Path | str, *, session_id: str, clock=time.time) -> None:
        self.path = Path(path)
        self.session_id = session_id
        self._clock = clock
        self._finalized = False

    # -------------------------------------------------------------- lifecycle

    @classmethod
    def begin(
        cls,
        path: Path | str,
        *,
        session_id: str,
        clock=time.time,
        pid: int | None = None,
    ) -> CommissioningJournal:
        """Open a fresh journal, or refuse/latch on an already-used one.

        A journal file is used exactly once. If a previous session left a
        non-terminal last line, that session's process died while it may have
        had the robot moving: this records the latch durably and raises.
        """

        target = Path(path)
        journal = cls(target, session_id=session_id, clock=clock)
        if target.exists():
            entries = journal.entries()
            last = entries[-1] if entries else None
            last_state = None if last is None else str(last.get("state", ""))
            if last_state in {state.value for state in TERMINAL_JOURNAL_STATES}:
                raise CommissioningRefusedError(
                    RefusalReason.JOURNAL_ALREADY_USED,
                    f"{target} already holds a finished session ({last_state}); "
                    "start a new journal file",
                )
            journal._write(
                JournalState.LATCHED,
                latch_reason=LatchReason.PROCESS_EXIT.value,
                detail=(
                    f"previous session left state {last_state!r}; that process exited "
                    "without confirming a stop"
                ),
                recovered_by_pid=os.getpid() if pid is None else pid,
            )
            journal._finalized = True
            raise CommissioningLatchedError(
                LatchReason.PROCESS_EXIT,
                f"{target} was left at state {last_state!r} by an earlier process",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        journal._write(JournalState.OPENED, schema=JOURNAL_SCHEMA, pid=os.getpid())
        return journal

    def append(self, state: JournalState, **fields: object) -> None:
        if self._finalized:
            raise CommissioningRefusedError(
                RefusalReason.JOURNAL_ALREADY_USED,
                "this journal has already been finalized",
            )
        self._write(state, **fields)

    def finish(self, state: JournalState, **fields: object) -> None:
        if self._finalized:
            return
        if state not in TERMINAL_JOURNAL_STATES:
            raise ValueError("a journal is finished with LATCHED or COMPLETE")
        self._write(state, **fields)
        self._finalized = True

    # -------------------------------------------------- best-effort variants
    #
    # The durable journal lives on a filesystem that can be full, read-only, or
    # over quota — a session that cannot write its journal must still be able to
    # hand back its record. These three never raise; they report.

    def try_append(self, state: JournalState, **fields: object) -> str:
        """Append if possible. Returns ``""`` on success, else why it failed."""

        try:
            self.append(state, **fields)
        except CommissioningRefusedError:
            return "journal was already finalized"
        except OSError as error:
            return f"journal append failed: {error}"
        return ""

    def try_finish(self, state: JournalState, **fields: object) -> str:
        """Finalize if possible. Returns ``""`` on success, else why it failed."""

        try:
            self.finish(state, **fields)
        except OSError as error:
            # Nothing more can be written. The on-disk journal deliberately
            # stays non-terminal, so re-opening this path latches PROCESS_EXIT —
            # a journal that could not record its own ending is abandoned.
            self._finalized = True
            return f"journal finish failed: {error}"
        return ""

    def try_digest(self) -> str:
        """The digest of whatever landed, or ``""`` if it cannot be read."""

        try:
            return self.digest()
        except OSError:
            return ""

    @property
    def finalized(self) -> bool:
        return self._finalized

    # ------------------------------------------------------------------- data

    def entries(self) -> tuple[dict[str, object], ...]:
        if not self.path.exists():
            return ()
        rows: list[dict[str, object]] = []
        for line in self.path.read_text().splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                # A torn final line is itself evidence of an abrupt exit.
                rows.append({"state": "torn", "raw": stripped})
                continue
            rows.append(payload)
        return tuple(rows)

    def digest(self) -> str:
        if not self.path.exists():
            return ""
        return sha256_bytes(self.path.read_bytes())

    # ---------------------------------------------------------------- private

    def _write(self, state: JournalState, **fields: object) -> None:
        payload: dict[str, object] = {
            "schema": JOURNAL_SCHEMA,
            "session_id": self.session_id,
            "state": state.value,
            "at": float(self._clock()),
        }
        payload.update(fields)
        line = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


class CommissioningObserver:
    """Read-only feedback phase. Holds a state source and no controller at all.

    This object cannot command anything: there is no controller, no
    ``ControlManager``, and no method that writes. It exists so the modes,
    rates, and resting feedback a commissioning step needs can be established
    before anything claims a lease.
    """

    def __init__(
        self,
        state_source,
        *,
        declared_velocity_frame: str,
        limits: CommissioningLimits | None = None,
        clock=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        self._state_source = state_source
        self.declared_velocity_frame = str(declared_velocity_frame)
        self.limits = limits or CommissioningLimits()
        self._clock = clock
        self._sleeper = sleeper
        self._started = False
        self._closed = False

    def start(self) -> None:
        if self._closed:
            raise CommissioningRefusedError(RefusalReason.SESSION_CLOSED)
        self._state_source.start()
        self._started = True

    def observe(self, *, min_samples: int = 20, timeout_s: float = 5.0) -> ObservationEvidence:
        """Collect distinct feedback samples while nothing is commanded."""

        if self._closed:
            raise CommissioningRefusedError(RefusalReason.SESSION_CLOSED)
        if not self._started:
            raise CommissioningRefusedError(RefusalReason.SESSION_NOT_STARTED)
        if min_samples < 1:
            raise ValueError("observation requires at least one sample")
        started = self._clock()
        deadline = started + float(timeout_s)
        seen_sequences: set[int] = set()
        receipts: list[float] = []
        modes: set[int] = set()
        error_codes: set[int] = set()
        max_linear = 0.0
        max_yaw = 0.0
        source_name = str(getattr(self._state_source, "name", ""))
        while self._clock() < deadline and len(seen_sequences) < min_samples:
            state = self._state_source.latest()
            if state is not None and state.sequence not in seen_sequences:
                seen_sequences.add(state.sequence)
                receipts.append(state.received_at)
                if state.mode is not None:
                    modes.add(int(state.mode))
                error_codes.add(int(state.error_code))
                max_linear = max(max_linear, math.hypot(state.velocity.vx, state.velocity.vy))
                max_yaw = max(max_yaw, abs(state.velocity.vyaw))
            self._sleeper(0.005)
        duration = self._clock() - started
        if len(seen_sequences) < min_samples:
            raise CommissioningRefusedError(
                RefusalReason.NO_FEEDBACK,
                f"saw {len(seen_sequences)} distinct feedback samples in {duration:.2f}s; "
                f"needed {min_samples}",
            )
        receipts.sort()
        gaps = [b - a for a, b in itertools.pairwise(receipts)]
        evidence = ObservationEvidence(
            samples=len(seen_sequences),
            duration_s=max(0.0, duration),
            modes_seen=tuple(sorted(modes)),
            error_codes_seen=tuple(sorted(error_codes)),
            max_interval_s=max(gaps) if gaps else 0.0,
            mean_interval_s=(sum(gaps) / len(gaps)) if gaps else 0.0,
            max_linear_speed_mps=max_linear,
            max_yaw_speed_rad_s=max_yaw,
            declared_velocity_frame=self.declared_velocity_frame,
            state_source=source_name,
        )
        if (
            evidence.max_linear_speed_mps > self.limits.settled_linear_mps
            or evidence.max_yaw_speed_rad_s > self.limits.settled_yaw_rad_s
        ):
            raise CommissioningRefusedError(
                RefusalReason.ROBOT_NOT_STATIONARY,
                f"feedback shows {evidence.max_linear_speed_mps:.4f} m/s / "
                f"{evidence.max_yaw_speed_rad_s:.4f} rad/s while nothing is commanded",
            )
        faults = error_codes - {0}
        if faults:
            raise CommissioningRefusedError(
                RefusalReason.VENDOR_FAULT,
                f"vendor reported error code(s) {sorted(faults)} before any command",
            )
        return evidence

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._started = False
        self._state_source.close()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class CommissioningSession:
    """One armed, journalled, one-axis-at-a-time commissioning session.

    Not a ``ControlManager`` and not convertible into one. The manager it drives
    is private and its public surface is only: start, run one axis step, build a
    record, close.
    """

    def __init__(
        self,
        manager,
        *,
        arming: CommissioningArming,
        journal: CommissioningJournal,
        declared_velocity_frame: str,
        limits: CommissioningLimits | None = None,
        clock=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        if not isinstance(arming, CommissioningArming):
            raise CommissioningRefusedError(
                RefusalReason.NOT_ARMED,
                "a commissioning session requires an explicit CommissioningArming token",
            )
        if not isinstance(journal, CommissioningJournal):
            raise TypeError("a commissioning session requires a CommissioningJournal")
        timing = manager.timing
        self._manager = manager
        self._state_source = manager.state_source
        self._arming = arming
        self._journal = journal
        self.declared_velocity_frame = str(declared_velocity_frame)
        self._limits = limits or CommissioningLimits(
            max_duration_s=min(DEFAULT_MAX_DURATION_S, float(timing.stop_timeout_s)),
            max_ttl_s=min(MAX_TTL_S, float(timing.command_timeout_s)),
        )
        self._ttl_s = min(self._limits.max_ttl_s, float(timing.command_timeout_s))
        self._clock = clock
        self._sleeper = sleeper
        self._started = False
        self._closed = False
        self._latch: tuple[LatchReason, str] | None = None
        self._axis_evidence: dict[CommissioningAxis, AxisSignEvidence] = {}
        self._stop_evidence: StopEvidence | None = None
        self._observation: ObservationEvidence | None = None
        self._steps = 0

    # ------------------------------------------------------------- properties

    @property
    def operator(self) -> str:
        return self._arming.operator

    @property
    def robot_serial(self) -> str:
        return self._arming.robot_serial

    @property
    def limits(self) -> CommissioningLimits:
        return self._limits

    @property
    def ttl_s(self) -> float:
        return self._ttl_s

    @property
    def latched(self) -> bool:
        return self._latch is not None

    @property
    def latch_reason(self) -> LatchReason | None:
        return None if self._latch is None else self._latch[0]

    @property
    def latch_detail(self) -> str:
        return "" if self._latch is None else self._latch[1]

    @property
    def journal_path(self) -> Path:
        return self._journal.path

    @property
    def steps_run(self) -> int:
        return self._steps

    # ------------------------------------------------------------- lifecycle

    def adopt_observation(self, observation: ObservationEvidence) -> None:
        """Carry the read-only phase's evidence into this session's record."""

        if not isinstance(observation, ObservationEvidence):
            raise TypeError("observation must be an ObservationEvidence")
        self._observation = observation

    def start(self) -> None:
        self._guard()
        if self._started:
            return
        self._arming.assert_valid(self._clock())
        self._journal_or_latch(
            JournalState.ARMED,
            arming=self._arming.as_dict(),
            limits=self._limits.as_dict(),
            ttl_s=self._ttl_s,
        )
        self._manager.start()
        self._started = True
        self._wait_until_ready()

    def run_axis_step(
        self,
        axis: CommissioningAxis,
        speed: float,
        duration_s: float,
        *,
        observed_direction: ObservedDirection = ObservedDirection.UNCERTAIN,
    ) -> AxisSignEvidence:
        """Command exactly one axis, briefly, then stop and confirm the stop."""

        self._guard()
        if not self._started:
            raise CommissioningRefusedError(RefusalReason.SESSION_NOT_STARTED)
        now = self._clock()
        self._arming.assert_valid(now)
        if not self._arming.observed_modes:
            raise CommissioningRefusedError(
                RefusalReason.MODES_NOT_OBSERVED,
                "run the read-only observation phase and arm with the modes it saw",
            )
        command = single_axis_command(axis, speed)
        confirmed_axis = assert_commissioning_command(command, self._limits)
        duration = assert_commissioning_duration(duration_s, self._limits)
        ttl = assert_commissioning_ttl(self._ttl_s, self._limits)
        self._journal_or_latch(
            JournalState.MOVING,
            axis=confirmed_axis.value,
            speed=float(speed),
            duration_s=duration,
            ttl_s=ttl,
        )
        self._steps += 1
        samples = self._drive(command, duration, ttl)
        stop_evidence = self._stop_and_confirm("commissioning_step_complete")
        self._stop_evidence = stop_evidence
        evidence = self._axis_evidence_from(
            confirmed_axis, float(speed), samples, observed_direction
        )
        self._axis_evidence[confirmed_axis] = evidence
        # Best effort, deliberately: the evidence is already in memory and the
        # record is what the operator needs. Losing this line latches, but must
        # not throw away the step that just completed.
        self._journal_best_effort(
            JournalState.IDLE,
            axis=confirmed_axis.value,
            evidence=evidence.as_dict(),
            stop=stop_evidence.as_dict(),
        )
        if not stop_evidence.confirmed:
            self._latch_failure(
                LatchReason.STOP_NOT_CONFIRMED,
                f"stop was not feedback-confirmed within {stop_evidence.timeout_s:g}s",
            )
            raise CommissioningLatchedError(
                LatchReason.STOP_NOT_CONFIRMED,
                f"settle latency {stop_evidence.settle_latency_s:.3f}s exceeded the budget",
            )
        return evidence

    def record(
        self,
        *,
        record_id: str | None = None,
        performed_at: str,
        software_revision: str = "",
        artifact_paths: Iterable[Path | str] = (),
    ) -> CommissioningRecordV1:
        """Build the evidence record. Always available, including after a latch."""

        self.close()
        artifacts = list(artifact_paths)
        hashes = artifact_hashes_for(artifacts) if artifacts else ()
        axis_signs = tuple(
            self._axis_evidence[axis] for axis in CommissioningAxis if axis in self._axis_evidence
        )
        if self._latch is not None:
            outcome = RecordOutcome.FAILED
            failure_reason = f"{self._latch[0].value}: {self._latch[1]}"
        elif self._complete():
            outcome = RecordOutcome.PASSED
            failure_reason = ""
        else:
            outcome = RecordOutcome.ABORTED
            failure_reason = "session ended before every axis produced sign evidence"
        return CommissioningRecordV1(
            record_id=record_id or f"commissioning-{uuid.uuid4().hex[:12]}",
            operator=self._arming.operator,
            robot_serial=self._arming.robot_serial,
            performed_at=performed_at,
            outcome=outcome,
            failure_reason=failure_reason,
            declared_velocity_frame=self.declared_velocity_frame,
            observed_modes=self._arming.observed_modes,
            axis_signs=axis_signs,
            observation=self._observation,
            stop=self._stop_evidence,
            limits=self._limits,
            artifact_hashes=hashes,
            # Best effort: an unreadable journal costs the record its digest —
            # which fails closed, since `missing_evidence` then lists it — but
            # never costs the operator the record itself.
            journal_digest=self._journal.try_digest(),
            software_revision=software_revision,
        )

    def close(self) -> None:
        """Tear down and finalize. **Never raises on a teardown failure.**

        `close` is on the evidence path — `record` calls it first — so a failure
        here must be written down, not propagated. A `ControlManager` whose stop
        was never delivered raises `ControlNotReadyError` out of its own
        `close()`; letting that escape would destroy the record in exactly the
        case the record matters most (the stop did not work). So a failed
        teardown latches, lands in the journal, and surfaces as a `FAILED`
        record plus a non-zero CLI exit instead of an exception.
        """

        if self._closed:
            return
        self._closed = True
        try:
            if self._started:
                try:
                    self._manager.stop("commissioning_shutdown")
                except BaseException as error:  # noqa: BLE001 - a failed stop must latch
                    self._latch_failure(
                        LatchReason.STOP_NOT_CONFIRMED,
                        f"shutdown stop failed: {error}",
                        stop_robot=False,
                    )
                finally:
                    try:
                        self._manager.close()
                    except BaseException as error:  # noqa: BLE001 - teardown is the finding
                        self._latch_failure(
                            LatchReason.TEARDOWN_FAILED,
                            f"controller close failed: {error}",
                            stop_robot=False,
                        )
        finally:
            self._started = False
            # Finalization is best effort for the same reason the rest of
            # teardown is: the filesystem holding the journal can be full, over
            # quota, or read-only, and none of that may cost the operator the
            # record. A failed finalize latches in memory and is reported in
            # `failure_reason`; the on-disk journal stays non-terminal, so
            # re-opening it latches PROCESS_EXIT.
            if self._latch is not None:
                problem = self._journal.try_finish(
                    JournalState.LATCHED,
                    latch_reason=self._latch[0].value,
                    detail=self._latch[1],
                )
            else:
                problem = self._journal.try_finish(
                    JournalState.COMPLETE, steps=self._steps
                )
            if problem:
                self._latch_in_memory(LatchReason.JOURNAL_WRITE_FAILED, problem)

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type, exc, _tb) -> None:
        if exc_type is not None and self._latch is None:
            reason = (
                LatchReason.INTERRUPTED
                if issubclass(exc_type, KeyboardInterrupt)
                else LatchReason.UNEXPECTED_ERROR
            )
            self._latch_failure(reason, f"{exc_type.__name__}: {exc}")
        self.close()

    # ---------------------------------------------------------------- private

    def _guard(self) -> None:
        if self._latch is not None:
            raise CommissioningLatchedError(self._latch[0], self._latch[1])
        if self._closed:
            raise CommissioningRefusedError(RefusalReason.SESSION_CLOSED)

    def _latch_in_memory(self, reason: LatchReason, detail: str) -> None:
        """Latch without touching the journal. The first latch always wins."""

        if self._latch is None:
            self._latch = (reason, detail)

    def _journal_best_effort(self, state: JournalState, **fields: object) -> str:
        """Journal a transition; a write failure latches and is never raised."""

        problem = self._journal.try_append(state, **fields)
        if problem:
            self._latch_in_memory(LatchReason.JOURNAL_WRITE_FAILED, problem)
        return problem

    def _journal_or_latch(self, state: JournalState, **fields: object) -> None:
        """Journal a live-path transition. A write failure ends the session.

        On the live path a lost journal line means the durable record of what
        this session did is already incomplete, so the session stops rather than
        keeps commanding. It latches under its own name and raises a named
        latch — never a bare ``OSError`` — and ``record()`` still works.
        """

        problem = self._journal_best_effort(state, **fields)
        if problem:
            raise CommissioningLatchedError(LatchReason.JOURNAL_WRITE_FAILED, problem)

    def _latch_failure(
        self,
        reason: LatchReason,
        detail: str,
        *,
        stop_robot: bool = True,
    ) -> None:
        if self._latch is None:
            self._latch = (reason, detail)
            # Best effort: a journal that cannot be written must not turn a
            # latched failure into a lost record.
            self._journal.try_append(
                JournalState.LATCHED,
                latch_reason=reason.value,
                detail=detail,
            )
        if stop_robot and self._started:
            try:
                self._manager.emergency_stop()
            except BaseException:  # noqa: BLE001, S110 - the latch is the finding
                pass

    def _wait_until_ready(self) -> None:
        deadline = self._clock() + float(self._manager.timing.startup_timeout_s)
        while self._clock() < deadline:
            status = self._manager.snapshot()
            if status.lifecycle == ControlLifecycle.IDLE:
                return
            if status.lifecycle == ControlLifecycle.FAULTED:
                self._latch_failure(
                    LatchReason.CONTROLLER_FAULT,
                    status.fault or "controller faulted while arming",
                )
                raise CommissioningLatchedError(
                    LatchReason.CONTROLLER_FAULT,
                    status.fault or "controller faulted while arming",
                )
            self._sleeper(0.01)
        self._latch_failure(
            LatchReason.STATE_LOST,
            "controller feedback did not become ready before the startup timeout",
        )
        raise CommissioningLatchedError(
            LatchReason.STATE_LOST,
            "controller feedback did not become ready before the startup timeout",
        )

    def _drive(
        self,
        command,
        duration: float,
        ttl: float,
    ) -> tuple[RobotMotionState, ...]:
        samples: list[RobotMotionState] = []
        seen: set[int] = set()
        started = self._clock()
        state_timeout = float(self._manager.timing.state_timeout_s)
        try:
            while True:
                now = self._clock()
                remaining = duration - (now - started)
                if remaining <= 0.0:
                    break
                if self._arming.expired(now):
                    self._latch_failure(
                        LatchReason.ARMING_EXPIRED_MID_STEP,
                        "the arming token expired while a step was running",
                    )
                    raise CommissioningLatchedError(LatchReason.ARMING_EXPIRED_MID_STEP)
                try:
                    self._manager.set_target(
                        command,
                        source=COMMISSIONING_SOURCE,
                        ttl=ttl,
                        now=now,
                    )
                except ControlNotReadyError as error:
                    self._latch_failure(LatchReason.STATE_LOST, str(error))
                    raise CommissioningLatchedError(LatchReason.STATE_LOST, str(error)) from error
                status = self._manager.snapshot(now=now)
                if status.lifecycle == ControlLifecycle.FAULTED or status.fault:
                    detail = status.fault or "controller faulted"
                    self._latch_failure(LatchReason.CONTROLLER_FAULT, detail)
                    raise CommissioningLatchedError(LatchReason.CONTROLLER_FAULT, detail)
                if status.target_source not in (None, COMMISSIONING_SOURCE):
                    detail = f"another writer set the target source to {status.target_source!r}"
                    self._latch_failure(LatchReason.FOREIGN_WRITER, detail)
                    raise CommissioningLatchedError(LatchReason.FOREIGN_WRITER, detail)
                state = self._state_source.latest()
                if state is None or (now - state.received_at) >= state_timeout:
                    detail = (
                        "robot feedback went stale during a commissioning step"
                        if state is not None
                        else "robot feedback disappeared during a commissioning step"
                    )
                    self._latch_failure(LatchReason.STATE_LOST, detail)
                    raise CommissioningLatchedError(LatchReason.STATE_LOST, detail)
                if state.sequence not in seen:
                    seen.add(state.sequence)
                    samples.append(state)
                # Renew well inside the lease, and sample feedback faster than
                # the lease so a short step still yields enough evidence.
                self._sleeper(min(_DRIVE_POLL_S, ttl / 3.0, max(0.0, remaining)))
        except KeyboardInterrupt as error:
            interrupted = "keyboard interrupt while a commissioning step was running"
            self._latch_failure(LatchReason.INTERRUPTED, interrupted)
            raise CommissioningLatchedError(LatchReason.INTERRUPTED, interrupted) from error
        except BaseException as error:
            # An already-latched failure keeps its own reason; anything else is
            # an unexpected error and latches under that name. Either way the
            # exception propagates: a commissioning step never fails quietly.
            if not isinstance(error, CommissioningLatchedError):
                self._latch_failure(
                    LatchReason.UNEXPECTED_ERROR,
                    f"{type(error).__name__}: {error}",
                )
            raise
        return tuple(samples)

    def _stop_and_confirm(self, reason: str) -> StopEvidence:
        timing = self._manager.timing
        timeout_s = float(timing.stop_timeout_s)
        before = self._state_source.latest()
        # Best effort: a lost journal line must never stop the session from
        # issuing the stop that follows it.
        self._journal_best_effort(JournalState.SETTLING, reason=reason)
        requested_at = self._clock()
        try:
            self._manager.stop(reason)
        except BaseException as error:
            self._latch_failure(
                LatchReason.STOP_NOT_CONFIRMED,
                f"stop request raised: {error}",
            )
            raise CommissioningLatchedError(
                LatchReason.STOP_NOT_CONFIRMED,
                f"stop request raised: {error}",
            ) from error
        request_latency = max(0.0, self._clock() - requested_at)
        deadline = requested_at + timeout_s
        confirmed = False
        settled_at = self._clock()
        path: list[RobotMotionState] = []
        seen: set[int] = set()
        while self._clock() <= deadline:
            status = self._manager.snapshot()
            state = self._state_source.latest()
            if state is not None and state.sequence not in seen:
                seen.add(state.sequence)
                path.append(state)
            settled_at = self._clock()
            if status.stop_confirmed and self._state_is_settled(state):
                confirmed = True
                break
            if status.lifecycle == ControlLifecycle.FAULTED:
                break
            self._sleeper(0.005)
        settle_latency = max(0.0, settled_at - requested_at)
        distance, method = self._stop_distance(before, path)
        return StopEvidence(
            request_latency_s=request_latency,
            settle_latency_s=settle_latency,
            distance_m=distance,
            distance_method=method,
            settled_linear_mps=self._limits.settled_linear_mps,
            settled_yaw_rad_s=self._limits.settled_yaw_rad_s,
            confirmed=confirmed,
            timeout_s=timeout_s,
        )

    def _state_is_settled(self, state: RobotMotionState | None) -> bool:
        """This path's own stationarity test, independent of manager timing.

        ``configs/robot.yaml`` calls 0.08 m/s settled, which is above the entire
        commissioning band - a robot moving at a commissioned speed would pass
        it. Commissioning uses its own, tighter threshold on top of the
        manager's confirmation.
        """

        if state is None:
            return False
        return (
            math.hypot(state.velocity.vx, state.velocity.vy) <= self._limits.settled_linear_mps
            and abs(state.velocity.vyaw) <= self._limits.settled_yaw_rad_s
        )

    def _stop_distance(
        self,
        before: RobotMotionState | None,
        path: Sequence[RobotMotionState],
    ) -> tuple[float, str]:
        if before is not None and path:
            last = path[-1]
            positions = (*before.position, *last.position)
            if any(abs(value) > 0.0 for value in positions):
                delta = math.hypot(
                    last.position[0] - before.position[0],
                    last.position[1] - before.position[1],
                )
                return (delta, "odom_delta")
        total = 0.0
        for earlier, later in itertools.pairwise(path):
            dt = max(0.0, later.received_at - earlier.received_at)
            speed = math.hypot(earlier.velocity.vx, earlier.velocity.vy)
            total += speed * dt
        return (total, "speed_integral")

    def _axis_evidence_from(
        self,
        axis: CommissioningAxis,
        commanded_speed: float,
        samples: Sequence[RobotMotionState],
        observed_direction: ObservedDirection,
    ) -> AxisSignEvidence:
        count = len(samples)
        if count:
            measured = [self._axis_value(axis, state) for state in samples]
            cross = [self._cross_axis_value(axis, state) for state in samples]
            mean_measured = sum(measured) / count
            mean_cross = sum(cross) / count
            # Circular mean: a plain average of yaw is wrong across +/-pi.
            mean_yaw = math.atan2(
                sum(math.sin(state.yaw) for state in samples) / count,
                sum(math.cos(state.yaw) for state in samples) / count,
            )
        else:
            mean_measured = 0.0
            mean_cross = 0.0
            mean_yaw = 0.0
        return AxisSignEvidence(
            axis=axis,
            commanded_speed=commanded_speed,
            samples=count,
            mean_measured_speed=mean_measured,
            mean_cross_axis_speed=mean_cross,
            mean_yaw_rad=mean_yaw,
            evidence_floor=self._limits.evidence_floor(axis),
            observed_direction=observed_direction,
            declared_velocity_frame=self.declared_velocity_frame,
        )

    @staticmethod
    def _axis_value(axis: CommissioningAxis, state: RobotMotionState) -> float:
        return float(getattr(state.velocity, axis.value))

    @staticmethod
    def _cross_axis_value(axis: CommissioningAxis, state: RobotMotionState) -> float:
        if axis is CommissioningAxis.VX:
            return float(state.velocity.vy)
        if axis is CommissioningAxis.VY:
            return float(state.velocity.vx)
        return math.hypot(state.velocity.vx, state.velocity.vy)

    def _complete(self) -> bool:
        return (
            self._observation is not None
            and self._stop_evidence is not None
            and self._stop_evidence.confirmed
            and all(axis in self._axis_evidence for axis in CommissioningAxis)
            and all(evidence.sign is not None for evidence in self._axis_evidence.values())
        )


DOES_NOT_PROVE: tuple[str, ...] = (
    (
        "Nothing in this module has ever driven real hardware. Every proof in "
        "tests/test_w0b_commissioning.py runs against in-process fakes through "
        "the existing bounded vendor seams; the vendor transport is unexercised."
    ),
    (
        "The journal makes an abandoned session detectable, not impossible. A "
        "process killed between the vendor accepting a Move and the journal's "
        "fsync leaves a robot that this file cannot describe - which is why the "
        "operator instructions put a human on a physical E-stop."
    ),
    (
        "Stop latency and distance are measured through the vendor's own "
        "feedback at its own rate. They are the numbers this path can see, not "
        "ground truth."
    ),
)
