"""Disarmed runtime supervision for the authoritative execution journal.

This module deliberately stops at deterministic Model-B frames.  It owns no
provider, audio, socket, or actuator handle, and it does not bind the frames to
a live speech session.  A continuity, authentication, freshness, lifecycle, or
capacity failure latches the lane closed and discards every undelivered frame.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from parcel_robot.brain.execution_narrative_bridge import (
    ExecutiveJournalContinuityError,
    NarratingTaskExecutiveV1,
)
from parcel_robot.brain.executive import TaskExecutive

from .execution_narrative import (
    ModelBNarrationFrameV1,
    NarrativeConsumerStateV1,
    TrustedExecutionNarrativeAuthenticatorV1,
    consume_execution_narrative_event,
)


@dataclass(frozen=True, slots=True)
class JournalOnlyNarrativeStatusV1:
    """Observable state for the non-speaking, non-actuating journal lane."""

    source_epoch: int
    speech_generation: int
    consumed_event_sequence: int
    bridge_journal_cursor: int
    bridge_queued_events: int
    queued_frames: int
    frame_capacity: int
    fault_code: str | None

    @property
    def authorizes_actuation(self) -> bool:
        return False

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": "journal_only_disarmed",
            "source_epoch": self.source_epoch,
            "speech_generation": self.speech_generation,
            "consumed_event_sequence": self.consumed_event_sequence,
            "bridge_journal_cursor": self.bridge_journal_cursor,
            "bridge_queued_events": self.bridge_queued_events,
            "queued_frames": self.queued_frames,
            "frame_capacity": self.frame_capacity,
            "fault_code": self.fault_code,
            "live_session_bound": False,
            "provider_bound": False,
            "audio_bound": False,
            "persistent_cursor_bound": False,
            "resume_parent_lineage_bound": False,
            "authentication_scope": "process_local",
            "authorizes_actuation": False,
        }


class JournalOnlyNarrativeRuntimeV1:
    """Poll one executive journal into authenticated, wording-only frames.

    The executive remains the runtime's API-compatible owner.  The DMC-4
    facade is used only as a journal reader here, so composition cannot alter
    task submission, scheduling, interruption, or dispatch behavior. Because
    submissions bypass that facade, the optional DMC-4 child-to-suspended-
    parent lineage field is deliberately unbound in this first composition;
    current same-task suspend/resume transitions remain journaled, but no
    separate-child resume claim is made.
    """

    def __init__(
        self,
        executive: TaskExecutive,
        *,
        source_epoch: int | None = None,
        authentication_key: bytes | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        event_ttl_ns: int = 5_000_000_000,
        event_capacity: int = 4096,
        frame_capacity: int = 4096,
    ) -> None:
        if not isinstance(executive, TaskExecutive):
            raise TypeError("executive must be TaskExecutive")
        if not callable(monotonic_ns):
            raise TypeError("monotonic_ns must be callable")
        if isinstance(frame_capacity, bool) or not isinstance(frame_capacity, int):
            raise TypeError("frame_capacity must be an integer")
        if not 1 <= frame_capacity <= 65_536:
            raise ValueError("frame_capacity must be between 1 and 65536")
        epoch = secrets.randbits(64) or 1 if source_epoch is None else source_epoch
        key = secrets.token_bytes(32) if authentication_key is None else authentication_key
        self._authenticator = TrustedExecutionNarrativeAuthenticatorV1(
            authenticator_id="parcel-runtime-journal-v1",
            key=key,
        )
        self._bridge = NarratingTaskExecutiveV1(
            executive,
            authenticator=self._authenticator,
            source_epoch=epoch,
            # This is intentionally not a claim of live-session binding.
            speech_generation_provider=lambda: 0,
            monotonic_ns=monotonic_ns,
            event_ttl_ns=event_ttl_ns,
            event_capacity=event_capacity,
        )
        self._state = NarrativeConsumerStateV1(
            source_epoch=epoch,
            speech_generation=0,
        )
        self._monotonic_ns = monotonic_ns
        self._frames: deque[ModelBNarrationFrameV1] = deque()
        self._frame_capacity = frame_capacity
        self._fault_code: str | None = None
        self._lock = threading.RLock()

    @property
    def authorizes_actuation(self) -> bool:
        return False

    def poll(self) -> int:
        """Consume one complete journal suffix, or latch the lane closed."""

        with self._lock:
            if self._fault_code is not None:
                return 0
            try:
                self._bridge.sync_narrative_transitions()
                bridge_status = self._bridge.narrative_queue_status()
                if bridge_status.fault_code is not None:
                    self._latch_fault(bridge_status.fault_code)
                    return 0
                # A conservative preflight keeps the batch atomic even when
                # some events would reduce silently: no event is removed until
                # enough bounded space exists for the worst case.
                if bridge_status.queued > self._frame_capacity - len(self._frames):
                    self._latch_fault("narrative_frame_queue_overflow")
                    return 0
                authenticated_events = self._bridge.drain_narrative_events()
                if not authenticated_events:
                    return 0
                now_ns = self._monotonic_ns()
                next_state = self._state
                prepared_frames: list[ModelBNarrationFrameV1] = []
                for authenticated in authenticated_events:
                    consumed = consume_execution_narrative_event(
                        next_state,
                        authenticated,
                        authenticator=self._authenticator,
                        now_monotonic_ns=now_ns,
                    )
                    if not consumed.accepted:
                        self._latch_fault(f"narrative_consumer_{consumed.reason}")
                        return 0
                    next_state = consumed.state
                    if consumed.frame is not None:
                        prepared_frames.append(consumed.frame)
                self._state = next_state
                self._frames.extend(prepared_frames)
                return len(authenticated_events)
            except ExecutiveJournalContinuityError as error:
                self._latch_fault(error.fault_code)
                return 0
            except Exception as error:  # noqa: BLE001 - optional lane isolation boundary
                self._latch_fault(f"narrative_consumer_internal_{type(error).__name__.lower()}")
                return 0

    def drain_frames(
        self,
        *,
        maximum: int | None = None,
    ) -> tuple[ModelBNarrationFrameV1, ...]:
        """Return still-current frames; a fault makes output permanently empty.

        Poll-time validation is insufficient because a frame can expire or a
        speech session can advance while it waits in this bounded queue.  The
        selected batch is therefore revalidated atomically immediately before
        release; no frame is removed if any selected frame is stale.
        """

        with self._lock:
            if maximum is not None and (
                isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 0
            ):
                raise ValueError("maximum must be a non-negative integer or null")
            if self._fault_code is not None:
                return ()
            count = len(self._frames) if maximum is None else maximum
            selected_count = min(count, len(self._frames))
            if selected_count == 0:
                return ()
            selected = tuple(self._frames[index] for index in range(selected_count))
            now_ns = self._monotonic_ns()
            for frame in selected:
                fault_code = self._frame_release_fault(frame, now_ns=now_ns)
                if fault_code is not None:
                    self._latch_fault(fault_code)
                    return ()
            for _ in range(selected_count):
                self._frames.popleft()
            return selected

    def status(self) -> JournalOnlyNarrativeStatusV1:
        with self._lock:
            bridge_status = self._bridge.narrative_queue_status()
            return JournalOnlyNarrativeStatusV1(
                source_epoch=self._state.source_epoch,
                speech_generation=self._state.speech_generation,
                consumed_event_sequence=self._state.last_event_sequence,
                bridge_journal_cursor=bridge_status.journal_cursor,
                bridge_queued_events=bridge_status.queued,
                queued_frames=len(self._frames),
                frame_capacity=self._frame_capacity,
                fault_code=self._fault_code or bridge_status.fault_code,
            )

    def _latch_fault(self, fault_code: str) -> None:
        if self._fault_code is None:
            self._fault_code = fault_code
        # No previously prepared wording survives a continuity or integrity
        # fault.  The authoritative executive remains untouched.
        self._frames.clear()

    def _frame_release_fault(
        self,
        frame: ModelBNarrationFrameV1,
        *,
        now_ns: int,
    ) -> str | None:
        if frame.source_epoch != self._state.source_epoch:
            return "narrative_frame_source_epoch_mismatch_at_drain"
        if frame.speech_generation != self._state.speech_generation:
            return "narrative_frame_speech_generation_mismatch_at_drain"
        if frame.issued_at_monotonic_ns > now_ns:
            return "narrative_frame_from_future_at_drain"
        if now_ns >= frame.claimable_until_monotonic_ns:
            return "narrative_frame_expired_at_drain"
        return None


__all__ = [
    "JournalOnlyNarrativeRuntimeV1",
    "JournalOnlyNarrativeStatusV1",
]
