"""The co-located governor + sole-writer gateway state machine.

Everything HLD §8.8 lists as the gateway's own is owned here: the boot epoch
and restart-disarmed state, the one authenticated lease, the strictly
monotonic per-boot command sequence, the receiver-derived TTL and its
watchdog, the local caps and the allowlisted action catalog (the catalog
declares the bounds and :mod:`gateway.governor` clamps to them, so the
allowlist sits *on* the control path rather than beside it), stop dominance
and ``StopMove``, fresh feedback and a stationary witness, and the bounded
audit ring.

Three decisions are worth reading before the code.

**The TTL never crosses the wire as a deadline.**  ``GatewayCommandV1`` carries
``local_ttl_ms``, a *duration*, because two processes' monotonic clocks are not
comparable.  The deadline is computed here, from this process's clock, at the
instant of receipt — once in :meth:`acquire`, once per :meth:`command` — and it
is re-checked one last time on the writer thread immediately before the vendor
call (:mod:`gateway.writer`).

**Every loss class ends in an exact-zero vendor write, and the last vendor
action after a loss is always a stop.**  There is one stop path,
``_stop_locked``: it bumps the stop epoch (which invalidates any write already
queued or in flight), issues ``StopMove``, then *witnesses* stillness —
``stop_settled_samples`` consecutive feedback samples that are fresh, strictly
advancing, and exactly zero — retrying ``StopMove`` every ``stop_retry_s`` for
``stop_timeout_s``.  A stop it could not witness is not reported as one: the
report carries ``stationary_confirmed=False`` and the gateway **latches**.

**Latching is the default, not the exception.**  ``_should_latch`` inverts the
usual shape: a cause latches unless it appears in the short, named
:data:`NON_LATCHING_CAUSES` list of recoverable losses (TTL expiry, client
disconnect, lease loss, stale feedback, a compensated late Move, shutdown,
boot).  A cause nobody has classified yet therefore latches, which is the
direction a safety gateway should fail in when a future card adds one.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from parcel_robot.bridge.protocol import (
    GatewayAckDispositionV1,
    GatewayAckV1,
    GatewayAcquireV1,
    GatewayCommandV1,
    GatewayHelloV1,
    GatewayPhaseV1,
    GatewayStateQueryV1,
    GatewayStateV1,
    GatewayStopReportV1,
    GatewayStopV1,
)

from .audit import BoundedAuditRingV1
from .catalog import BASE_VELOCITY_ACTION, ActionCatalogV1
from .credentials import CredentialPolicyV1, PeerCredentialV1
from .governor import (
    AuthorityEvidenceV1,
    FinalGovernorV1,
    MotionCandidateV1,
)
from .limits import GovernorLimitsV1, default_limits
from .ports import SportPort, SportSampleV1, read_sport_sample
from .writer import VendorWriterV1, VendorWriteV1

#: The only stop causes that leave the gateway merely DISARMED.  Everything
#: else — and anything not yet classified — latches.
NON_LATCHING_CAUSES = frozenset(
    {
        "gateway_boot",
        "gateway_shutdown",
        "client_disconnected",
        "client_stop",
        "local_ttl_expired",
        "sport_lease_lost",
        "state_stale",
        "late_move_completion_compensation",
    }
)


@dataclass(frozen=True)
class _LeaseV1:
    writer_id: str
    connection_id: int
    peer: PeerCredentialV1
    local_ttl_ms: int
    acquired_at_monotonic_s: float


@dataclass(frozen=True)
class _FeedbackVerdictV1:
    fresh: bool
    sequence_ok: bool
    lease_active: bool
    reason: str


@dataclass(frozen=True)
class VendorWriteOutcomeV1:
    """One bench/health observation of a vendor write. Never on the stop path."""

    write: VendorWriteV1
    outcome: str
    at_monotonic_s: float


class GatewayCoreV1:
    def __init__(
        self,
        sport: SportPort,
        *,
        policy: CredentialPolicyV1,
        limits: GovernorLimitsV1 | None = None,
        boot_epoch: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        audit: BoundedAuditRingV1 | None = None,
        write_observer: Callable[[VendorWriteOutcomeV1], None] | None = None,
        watchdog_observer: Callable[[float], None] | None = None,
    ) -> None:
        self._sport = sport
        self._policy = policy
        self._limits = limits or default_limits()
        self._clock = clock
        self._sleep = sleep
        self._audit = audit or BoundedAuditRingV1(clock=clock)
        self._catalog = ActionCatalogV1(self._limits)
        self._governor = FinalGovernorV1(self._limits, self._catalog)
        self._write_observer = write_observer
        self._watchdog_observer = watchdog_observer
        self.boot_epoch = boot_epoch or uuid.uuid4().hex
        self._lock = threading.RLock()
        # Restart-DISARMED is a construction-time fact, not a later assignment.
        self.phase = GatewayPhaseV1.DISARMED
        self._latched = False
        self._lease: _LeaseV1 | None = None
        self._last_client_sequence = 0
        self._deadline: float | None = None
        self._gateway_sequence = 0
        self._stop_sequence = 0
        self._stop_epoch = 0
        self._last_state_sequence = 0
        self._last_state_advance_at = self._clock()
        self._last_stop_reason = "gateway_boot"
        self._last_stop_confirmed = False
        self._last_stop_report: GatewayStopReportV1 | None = None
        self._closed = False
        self._observer_errors = 0
        self._writer = VendorWriterV1(
            sport,
            stop_epoch_reader=self._current_stop_epoch,
            on_refused=self._on_write_refused,
            on_completed=self._on_write_completed,
            clock=clock,
            idle_poll_s=self._limits.watchdog_period_s,
        )
        self._watch_stop = threading.Event()
        self._watchdog: threading.Thread | None = None
        self._audit.record(
            "gateway_boot",
            boot_epoch=self.boot_epoch,
            phase=self.phase.value,
            regime=self._limits.regime.name,
            catalog_version=self._catalog.version,
            catalog_digest=self._catalog.digest(),
            max_local_ttl_ms=self._limits.max_local_ttl_ms,
        )
        # A gateway that has just restarted does not know what the previous
        # instance left the vendor doing.  Its first act is an exact-zero
        # StopMove with a stationary witness, before any socket exists.
        self._boot_report = self._stop_locked("gateway_boot", latch=False)

    # ---- accessors ------------------------------------------------------

    @property
    def audit(self) -> BoundedAuditRingV1:
        return self._audit

    @property
    def limits(self) -> GovernorLimitsV1:
        return self._limits

    @property
    def catalog(self) -> ActionCatalogV1:
        return self._catalog

    @property
    def policy(self) -> CredentialPolicyV1:
        return self._policy

    @property
    def writer(self) -> VendorWriterV1:
        return self._writer

    @property
    def boot_stop_report(self) -> GatewayStopReportV1:
        return self._boot_report

    @property
    def latched(self) -> bool:
        with self._lock:
            return self._latched

    @property
    def active_writer(self) -> str | None:
        with self._lock:
            return self._lease.writer_id if self._lease is not None else None

    @property
    def stop_sequence(self) -> int:
        """How many stops this boot has issued. Boot's own StopMove is 1."""

        with self._lock:
            return self._stop_sequence

    @property
    def last_stop_reason(self) -> str:
        with self._lock:
            return self._last_stop_reason

    @property
    def last_stop_report(self) -> GatewayStopReportV1 | None:
        """The most recent stop, whichever thread caused it."""

        with self._lock:
            return self._last_stop_report

    @property
    def observer_errors(self) -> int:
        with self._lock:
            return self._observer_errors

    def _current_stop_epoch(self) -> int:
        with self._lock:
            return self._stop_epoch

    # ---- lifecycle ------------------------------------------------------

    def start(self, *, watchdog: bool = True) -> None:
        """Start the vendor writer and, unless told otherwise, the TTL watchdog.

        ``watchdog=False`` exists for the deterministic half of the bench,
        which drives :meth:`tick` itself so a fault's stop report is returned
        rather than swallowed by a thread.  The threaded watchdog is proven
        separately, with no test-driven tick at all.
        """

        self._writer.start()
        if watchdog and self._watchdog is None:
            self._watchdog = threading.Thread(
                target=self._watch,
                name="m1-0-gateway-watchdog",
                daemon=True,
            )
            self._watchdog.start()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self.phase is GatewayPhaseV1.ARMED:
                self._stop_locked("gateway_shutdown", latch=False)
            self._closed = True
        self._watch_stop.set()
        watchdog = self._watchdog
        if watchdog is not None:
            watchdog.join(timeout=1.0)
        self._writer.close()
        self._sport.close()

    def _watch(self) -> None:
        previous = self._clock()
        while not self._watch_stop.wait(self._limits.watchdog_period_s):
            now = self._clock()
            self._observe_watchdog(now - previous)
            previous = now
            self.tick()

    # ---- protocol entry points -----------------------------------------

    def hello(self) -> GatewayHelloV1:
        with self._lock:
            return GatewayHelloV1(
                boot_epoch=self.boot_epoch,
                gateway_sequence=self._next_gateway_sequence_locked(),
                phase=self.phase,
                required_hashes=self._policy.required_hashes,
            )

    def acquire(
        self,
        connection_id: int,
        peer: PeerCredentialV1,
        request: GatewayAcquireV1,
    ) -> GatewayAckV1:
        with self._lock:
            reason = self._acquire_refusal_locked(peer, request)
            if reason:
                self._audit.record(
                    "acquire_refused",
                    boot_epoch=self.boot_epoch,
                    phase=self.phase.value,
                    reason=reason,
                    writer_id=request.writer_id,
                    client_sequence=request.sequence,
                )
                if reason == "writer_conflict":
                    self._stop_locked(reason, latch=True)
                return self._ack_locked(request, accepted=False, reason=reason)
            if not self._sport.acquire_writer(request.writer_id):
                self._stop_locked("sport_writer_conflict", latch=True)
                return self._ack_locked(
                    request, accepted=False, reason="sport_writer_conflict"
                )
            sample = self._safe_sample()
            if sample is None:
                self._stop_locked("sport_state_unreadable", latch=True)
                return self._ack_locked(
                    request, accepted=False, reason="sport_state_unreadable"
                )
            now = self._clock()
            self.phase = GatewayPhaseV1.ARMED
            self._lease = _LeaseV1(
                writer_id=request.writer_id,
                connection_id=connection_id,
                peer=peer,
                local_ttl_ms=request.local_ttl_ms,
                acquired_at_monotonic_s=now,
            )
            self._last_client_sequence = request.sequence
            # Receiver-local derivation: only the duration crossed the wire.
            self._deadline = now + request.local_ttl_ms / 1000.0
            self._last_state_sequence = sample.sequence
            self._last_state_advance_at = now
            self._audit.record(
                "gateway_armed",
                boot_epoch=self.boot_epoch,
                phase=self.phase.value,
                writer_id=request.writer_id,
                peer_uid=peer.uid,
                peer_pid=peer.pid,
                local_ttl_ms=request.local_ttl_ms,
                regime=self._limits.regime.name,
            )
            return self._ack_locked(request, accepted=True)

    def command(
        self,
        connection_id: int,
        peer: PeerCredentialV1,
        request: GatewayCommandV1,
    ) -> GatewayAckV1:
        with self._lock:
            reason = self._authority_refusal_locked(connection_id, peer, request)
            if reason:
                self._stop_locked(reason, latch=self._should_latch(reason))
                return self._ack_locked(request, accepted=False, reason=reason)
            sample = self._safe_sample()
            if sample is None:
                self._stop_locked("sport_state_unreadable", latch=True)
                return self._ack_locked(
                    request, accepted=False, reason="sport_state_unreadable"
                )
            now = self._clock()
            feedback = self._feedback_locked(sample)
            evidence = AuthorityEvidenceV1(
                armed=self.phase is GatewayPhaseV1.ARMED,
                latched=self._latched,
                lease_active=feedback.lease_active,
                state_fresh=feedback.fresh,
                state_sequence_ok=feedback.sequence_ok,
                ttl_remaining_s=(
                    -1.0 if self._deadline is None else self._deadline - now
                ),
                vendor_writer_healthy=(
                    self._writer.in_flight_age_s(now) <= self._limits.vendor_write_stall_s
                ),
            )
            candidate = MotionCandidateV1(
                vx_mps=request.vx_mps,
                vy_mps=request.vy_mps,
                vyaw_rad_s=request.vyaw_rad_s,
            )
            verdict = self._governor.evaluate(BASE_VELOCITY_ACTION, candidate, evidence)
            if not verdict.disposition.permits_motion:
                cause = feedback.reason or verdict.primary_cause or "governor_stop"
                self._stop_locked(cause, latch=self._should_latch(cause))
                return self._ack_locked(request, accepted=False, reason=cause)
            self._last_client_sequence = request.sequence
            self._deadline = now + request.local_ttl_ms / 1000.0
            self._writer.submit(
                VendorWriteV1(
                    writer_id=request.writer_id,
                    vx_mps=verdict.vx_mps,
                    vy_mps=verdict.vy_mps,
                    vyaw_rad_s=verdict.vyaw_rad_s,
                    stop_epoch=self._stop_epoch,
                    client_sequence=request.sequence,
                    deadline_monotonic_s=self._deadline,
                    submitted_at_monotonic_s=now,
                )
            )
            self._audit.record(
                "command_admitted",
                boot_epoch=self.boot_epoch,
                phase=self.phase.value,
                writer_id=request.writer_id,
                client_sequence=request.sequence,
                disposition=verdict.disposition.name,
                causes=",".join(verdict.causes),
                local_ttl_ms=request.local_ttl_ms,
                ack_scope="gateway_admission",
            )
            # The ACK is admission only.  It deliberately does not wait for the
            # vendor write, and is never evidence that the robot moved.
            return self._ack_locked(
                request,
                accepted=True,
                reason="clamped" if verdict.causes else "",
            )

    def explicit_stop(
        self,
        connection_id: int,
        peer: PeerCredentialV1,
        request: GatewayStopV1,
    ) -> GatewayStopReportV1:
        """A stop is never refused. Dominance is unconditional (HLD §8.8)."""

        with self._lock:
            notes: list[str] = []
            latch = request.emergency
            lease = self._lease
            if (
                lease is None
                or connection_id != lease.connection_id
                or request.writer_id != lease.writer_id
                or not self._policy.admits_peer(peer)
            ):
                notes.append("stop_from_non_lease_writer")
                latch = True
            if request.sequence <= self._last_client_sequence:
                notes.append("stop_sequence_replay")
                latch = True
            else:
                self._last_client_sequence = request.sequence
            self._audit.record(
                "client_stop_requested",
                boot_epoch=self.boot_epoch,
                phase=self.phase.value,
                writer_id=request.writer_id,
                emergency=request.emergency,
                notes=",".join(notes),
            )
            return self._stop_locked(f"client_stop:{request.reason}", latch=latch)

    def state(self) -> GatewayStateV1:
        with self._lock:
            self._tick_locked()
            sample = self._safe_sample()
            if sample is None:
                self._stop_locked("sport_state_unreadable", latch=True)
                sample = SportSampleV1(
                    sequence=max(1, self._last_state_sequence),
                    received_at_monotonic_s=self._clock(),
                    vx_mps=0.0,
                    vy_mps=0.0,
                    vyaw_rad_s=0.0,
                    lease_active=False,
                )
            age_ms = max(0.0, (self._clock() - sample.received_at_monotonic_s) * 1000.0)
            lease = self._lease
            return GatewayStateV1(
                boot_epoch=self.boot_epoch,
                gateway_sequence=self._next_gateway_sequence_locked(),
                phase=self.phase,
                # The wire's state_sequence is 1-based; a vendor that has not
                # yet published a sample cannot be reported as sample zero.
                state_sequence=max(1, sample.sequence),
                state_age_ms=age_ms,
                lease_active=sample.lease_active,
                writer_id=lease.writer_id if lease is not None else "",
                vx_mps=sample.vx_mps,
                vy_mps=sample.vy_mps,
                vyaw_rad_s=sample.vyaw_rad_s,
                stationary=sample.max_abs_velocity <= self._limits.exact_zero,
                last_stop_sequence=self._stop_sequence,
                last_stop_reason=self._last_stop_reason,
            )

    def state_query(self, request: GatewayStateQueryV1) -> GatewayStateV1:
        del request
        return self.state()

    def client_lost(self, connection_id: int) -> GatewayStopReportV1 | None:
        with self._lock:
            lease = self._lease
            if lease is None or connection_id != lease.connection_id:
                self._audit.record(
                    "client_closed_without_lease",
                    boot_epoch=self.boot_epoch,
                    phase=self.phase.value,
                    connection_id=connection_id,
                )
                return None
            return self._stop_locked("client_disconnected", latch=False)

    def protocol_fault(self, connection_id: int, reason: str) -> GatewayStopReportV1 | None:
        """Unknown fields, version mismatch, malformed bytes: never permissive."""

        with self._lock:
            self._audit.record(
                "protocol_fault",
                boot_epoch=self.boot_epoch,
                phase=self.phase.value,
                connection_id=connection_id,
                detail=reason,
            )
            if self.phase is not GatewayPhaseV1.ARMED:
                return None
            return self._stop_locked(f"protocol_fault:{reason}"[:160], latch=True)

    def tick(self) -> GatewayStopReportV1 | None:
        """One watchdog cycle. Never raises: an internal error is a latched stop."""

        try:
            with self._lock:
                return self._tick_locked()
        except BaseException as caught:
            if not isinstance(caught, Exception):
                raise
            with self._lock:
                self._audit.record(
                    "watchdog_internal_error",
                    boot_epoch=self.boot_epoch,
                    phase=self.phase.value,
                    detail=repr(caught),
                )
                return self._stop_locked("watchdog_internal_error", latch=True)

    # ---- internals ------------------------------------------------------

    def _tick_locked(self) -> GatewayStopReportV1 | None:
        if self._closed or self.phase is not GatewayPhaseV1.ARMED:
            return None
        now = self._clock()
        if self._writer.in_flight_age_s(now) > self._limits.vendor_write_stall_s:
            return self._stop_locked("vendor_write_stalled", latch=True)
        if self._deadline is None or now >= self._deadline:
            return self._stop_locked("local_ttl_expired", latch=False)
        sample = self._safe_sample()
        if sample is None:
            return self._stop_locked("sport_state_unreadable", latch=True)
        feedback = self._feedback_locked(sample)
        if feedback.reason:
            return self._stop_locked(feedback.reason, latch=self._should_latch(feedback.reason))
        return None

    def _acquire_refusal_locked(
        self,
        peer: PeerCredentialV1,
        request: GatewayAcquireV1,
    ) -> str:
        if self._latched or self.phase is GatewayPhaseV1.LATCHED:
            return "gateway_latched"
        if not self._policy.admits_peer(peer):
            return "peer_not_authorized"
        if request.boot_epoch != self.boot_epoch:
            return "boot_epoch_mismatch"
        if not self._policy.admits_hashes(request.hashes):
            return "contract_hash_mismatch"
        if not self._policy.admits_writer(request.writer_id):
            return "writer_not_authorized"
        if request.local_ttl_ms > self._limits.max_local_ttl_ms:
            return "ttl_over_local_cap"
        if request.sequence <= self._last_client_sequence:
            return "client_sequence_not_increasing"
        if self._lease is not None:
            return "writer_conflict"
        return ""

    def _authority_refusal_locked(
        self,
        connection_id: int,
        peer: PeerCredentialV1,
        request: GatewayCommandV1,
    ) -> str:
        if self._latched or self.phase is GatewayPhaseV1.LATCHED:
            return "gateway_latched"
        if self.phase is not GatewayPhaseV1.ARMED:
            return "gateway_disarmed"
        lease = self._lease
        if lease is None:
            return "gateway_disarmed"
        if not self._policy.admits_peer(peer) or peer != lease.peer:
            return "peer_not_authorized"
        if connection_id != lease.connection_id:
            return "writer_connection_mismatch"
        if request.writer_id != lease.writer_id:
            return "writer_id_mismatch"
        if request.boot_epoch != self.boot_epoch:
            return "boot_epoch_mismatch"
        if not self._policy.admits_hashes(request.hashes):
            return "contract_hash_mismatch"
        if request.local_ttl_ms > self._limits.max_local_ttl_ms:
            return "ttl_over_local_cap"
        if request.sequence <= self._last_client_sequence:
            return "client_sequence_not_increasing"
        return ""

    def _feedback_locked(self, sample: SportSampleV1) -> _FeedbackVerdictV1:
        """Freshness revalidation. Order is deliberate — see the module docstring.

        The clock is read *after* the sample, never before: the vendor stamps
        its receipt time on the same monotonic clock this process uses, so a
        ``now`` captured earlier in the cycle would make every healthy sample
        look like it came from the future.  ``state_from_future`` must mean a
        genuinely inconsistent stamp, not this function's own read order.
        """

        now = self._clock()
        if not sample.lease_active:
            return _FeedbackVerdictV1(False, False, False, "sport_lease_lost")
        if sample.sequence < self._last_state_sequence:
            return _FeedbackVerdictV1(False, False, True, "state_out_of_order")
        if sample.sequence > self._last_state_sequence:
            self._last_state_sequence = sample.sequence
            self._last_state_advance_at = now
        elif now - self._last_state_advance_at >= self._limits.state_timeout_s:
            # The stream itself stopped, whatever its receipt stamps claim.
            return _FeedbackVerdictV1(False, False, True, "state_frozen")
        age = now - sample.received_at_monotonic_s
        if age < 0.0:
            return _FeedbackVerdictV1(False, True, True, "state_from_future")
        if age >= self._limits.state_timeout_s:
            return _FeedbackVerdictV1(False, True, True, "state_stale")
        return _FeedbackVerdictV1(True, True, True, "")

    @staticmethod
    def _should_latch(cause: str) -> bool:
        return cause.split(":", 1)[0] not in NON_LATCHING_CAUSES

    def _stop_locked(self, cause: str, *, latch: bool) -> GatewayStopReportV1:
        # A compensation or retry may strengthen a stop; it may never clear a
        # latch already taken.
        latch = latch or self._latched
        self._stop_epoch += 1
        self._stop_sequence += 1
        self._writer.drop_pending()
        reason = (cause or "unspecified_stop")[:160]
        previous_sequence = self._last_state_sequence
        lease = self._lease
        rpc_completed, confirmed, sample = self._stop_and_witness_locked(reason, previous_sequence)
        if not rpc_completed or not confirmed:
            latch = True
        self._latched = latch
        self.phase = GatewayPhaseV1.LATCHED if latch else GatewayPhaseV1.DISARMED
        self._lease = None
        self._deadline = None
        # The per-boot sequence fence is deliberately NOT reset: disarming must
        # not make a captured acquire/command pair replayable in this epoch.
        self._last_state_sequence = max(previous_sequence, sample.sequence)
        self._last_state_advance_at = self._clock()
        self._last_stop_reason = reason
        self._last_stop_confirmed = confirmed
        self._sport.release_writer(lease.writer_id if lease is not None else None)
        report = GatewayStopReportV1(
            boot_epoch=self.boot_epoch,
            gateway_sequence=self._next_gateway_sequence_locked(),
            stop_sequence=self._stop_sequence,
            reason=reason,
            stop_rpc_completed=rpc_completed,
            stationary_confirmed=confirmed,
            state_sequence=sample.sequence if confirmed else 0,
        )
        self._last_stop_report = report
        detail = report.as_dict()
        detail.pop("boot_epoch", None)
        self._audit.record(
            "gateway_stop_report",
            boot_epoch=self.boot_epoch,
            phase=self.phase.value,
            **detail,
        )
        return report

    def _stop_and_witness_locked(
        self,
        reason: str,
        previous_sequence: int,
    ) -> tuple[bool, bool, SportSampleV1]:
        deadline = self._clock() + self._limits.stop_timeout_s
        next_retry = self._clock() + self._limits.stop_retry_s
        rpc_completed = self._safe_stop_move(reason)
        settled = 0
        witnessed_sequence = previous_sequence
        latest = SportSampleV1(
            sequence=max(0, previous_sequence),
            received_at_monotonic_s=self._clock(),
            vx_mps=0.0,
            vy_mps=0.0,
            vyaw_rad_s=0.0,
            lease_active=False,
        )
        while True:
            sample = self._safe_sample()
            if sample is not None:
                latest = sample
                now = self._clock()
                age = now - sample.received_at_monotonic_s
                fresh = 0.0 <= age < self._limits.state_timeout_s
                still = sample.max_abs_velocity <= self._limits.exact_zero
                if rpc_completed and fresh and still and sample.sequence > witnessed_sequence:
                    settled += 1
                    witnessed_sequence = sample.sequence
                    if settled >= self._limits.stop_settled_samples:
                        return rpc_completed, True, sample
                else:
                    settled = 0
            now = self._clock()
            if now >= deadline:
                return rpc_completed, False, latest
            if not rpc_completed and now >= next_retry:
                rpc_completed = self._safe_stop_move(reason)
                next_retry = now + self._limits.stop_retry_s
            self._sleep(0.002)

    def _safe_stop_move(self, reason: str) -> bool:
        try:
            return bool(self._sport.stop_move(reason=reason))
        except BaseException as caught:
            if not isinstance(caught, Exception):
                raise
            self._audit.record(
                "stop_move_raised",
                boot_epoch=self.boot_epoch,
                phase=self.phase.value,
                detail=repr(caught),
            )
            return False

    def _safe_sample(self) -> SportSampleV1 | None:
        try:
            return read_sport_sample(self._sport)
        except BaseException as caught:
            if not isinstance(caught, Exception):
                raise
            self._audit.record(
                "sport_state_unreadable",
                boot_epoch=self.boot_epoch,
                phase=self.phase.value,
                detail=repr(caught),
            )
            return None

    def _on_write_refused(self, write: VendorWriteV1, cause: str) -> None:
        """The writer declined to reach the vendor. No Move was issued."""

        self._observe_write(write, f"refused:{cause}")
        with self._lock:
            self._audit.record(
                "vendor_write_refused",
                boot_epoch=self.boot_epoch,
                phase=self.phase.value,
                client_sequence=write.client_sequence,
                cause=cause,
            )
            if cause == "stop_dominance":
                # A stop already happened; the setpoint died with it.
                return
            if self.phase is GatewayPhaseV1.ARMED:
                self._stop_locked(cause, latch=self._should_latch(cause))

    def _on_write_completed(
        self,
        write: VendorWriteV1,
        applied_at: float,
        error: BaseException | None,
    ) -> None:
        self._observe_write(write, "error" if error is not None else "applied")
        with self._lock:
            if error is not None:
                self._stop_locked(f"move_failed:{error}"[:160], latch=True)
                return
            if write.stop_epoch != self._stop_epoch or self.phase is not GatewayPhaseV1.ARMED:
                # A Move that completed across a stop boundary must never be
                # the last thing the vendor was told.
                self._stop_locked("late_move_completion_compensation", latch=False)
                return
            self._audit.record(
                "vendor_write_applied",
                boot_epoch=self.boot_epoch,
                phase=self.phase.value,
                client_sequence=write.client_sequence,
                latency_ms=round((applied_at - write.submitted_at_monotonic_s) * 1000.0, 3),
            )

    def _observe_write(self, write: VendorWriteV1, outcome: str) -> None:
        observer = self._write_observer
        if observer is None:
            return
        try:
            observer(
                VendorWriteOutcomeV1(write=write, outcome=outcome, at_monotonic_s=self._clock())
            )
        except BaseException as caught:
            if not isinstance(caught, Exception):
                raise
            with self._lock:
                self._observer_errors += 1

    def _observe_watchdog(self, interval_s: float) -> None:
        observer = self._watchdog_observer
        if observer is None:
            return
        try:
            observer(interval_s)
        except BaseException as caught:
            if not isinstance(caught, Exception):
                raise
            with self._lock:
                self._observer_errors += 1

    def _ack_locked(
        self,
        request: GatewayAcquireV1 | GatewayCommandV1,
        *,
        accepted: bool,
        reason: str = "",
    ) -> GatewayAckV1:
        return GatewayAckV1(
            boot_epoch=self.boot_epoch,
            gateway_sequence=self._next_gateway_sequence_locked(),
            acknowledged_kind=request.kind,
            acknowledged_sequence=request.sequence,
            disposition=(
                GatewayAckDispositionV1.ACCEPTED if accepted else GatewayAckDispositionV1.REJECTED
            ),
            reason=reason[:160],
        )

    def _next_gateway_sequence_locked(self) -> int:
        self._gateway_sequence += 1
        return self._gateway_sequence
