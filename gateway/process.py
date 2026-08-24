"""CLI entry for the M1-0 gateway process (bench wiring).

On the robot this file's job is to choose a :class:`gateway.ports.SportPort`
implementation, build the credential policy from the launch profile, and serve.
Today the only port it can choose is ``--sport fake``, backed by
``parcel_robot.bridge.fake_sport``: this is the **one** module in the package
that reaches past ``parcel_robot.bridge.protocol``, and it is bench-only.
``--sport vendor`` exits nonzero with a named reason rather than importing
anything, because no vendor SDK is present, no robot exists yet, and a gateway
that silently starts without a vendor writer is worse than one that refuses.

Evidence export is deliberately outside the control path: the core writes into
its bounded in-memory ring and never calls out, and a daemon thread here pulls
with :meth:`~gateway.audit.BoundedAuditRingV1.drain` and appends JSONL.  A
blocked or failing disk therefore cannot delay a StopMove — it can only make
the process exit nonzero at the end, which is what
:func:`_evidence_exit_code` reports.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
import time
from pathlib import Path

from parcel_robot.bridge.protocol import GatewayHashesV1

from .audit import BoundedAuditRingV1
from .core import GatewayCoreV1
from .credentials import single_writer_policy
from .limits import DEFAULT_ACTIVE_REGIME, GovernorLimitsV1, regime
from .server import GatewayServerV1

#: Bench compatibility identities.  They mirror
#: ``parcel_robot.bridge.fake_gateway_process.DEFAULT_FAKE_HASHES`` so the two
#: benches interoperate.  A real deployment reads signed manifests instead.
BENCH_HASHES = GatewayHashesV1(
    config_sha256="a" * 64,
    capability_sha256="b" * 64,
    calibration_sha256="c" * 64,
    firmware_sha256="d" * 64,
)


class AuditExporterV1:
    """Pulls the bounded ring onto disk from its own daemon thread."""

    def __init__(self, ring: BoundedAuditRingV1, path: str | Path, *, period_s: float = 0.05):
        self._ring = ring
        self._path = Path(path)
        self._period_s = period_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._write_errors = 0

    @property
    def write_errors(self) -> int:
        return self._write_errors

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="m1-0-gateway-audit-exporter", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self.flush()

    def flush(self) -> None:
        records = self._ring.drain()
        if not records:
            return
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                for record in records:
                    handle.write(
                        json.dumps(record.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"
                    )
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            self._write_errors += 1

    def _run(self) -> None:
        while not self._stop.wait(self._period_s):
            self.flush()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True, help="bounded local seqpacket path")
    parser.add_argument("--audit-log", required=True, help="append-only JSONL audit export")
    parser.add_argument(
        "--vendor-log",
        default=None,
        help="bench only: append-only JSONL of the fake vendor's own events",
    )
    parser.add_argument("--sport", choices=("fake", "vendor"), default="fake")
    parser.add_argument("--writer-id", default="m1-0-bench-client")
    parser.add_argument("--regime", default=DEFAULT_ACTIVE_REGIME)
    parser.add_argument("--uid", type=int, default=None, help="uid allowed to hold the lease")
    parser.add_argument("--move-delay-s", type=float, default=0.0)
    parser.add_argument("--move-no-reply", action="store_true")
    parser.add_argument("--stale-state-by-s", type=float, default=0.0)
    parser.add_argument("--out-of-order-state", action="store_true")
    parser.add_argument("--stop-move-failure", action="store_true")
    return parser


def _evidence_exit_code(ring: BoundedAuditRingV1, exporter: AuditExporterV1) -> int:
    """Lost evidence is visible in the exit status and nowhere near the stop path."""

    return 0 if ring.dropped_records == 0 and exporter.write_errors == 0 else 2


def _build_sport(args: argparse.Namespace) -> object:
    if args.sport != "fake":
        raise SystemExit(
            "gateway.process: --sport vendor is not implemented — no vendor SDK is "
            "present in this tree and no robot exists yet (M1-0 is a bench card). "
            "Refusing to start a gateway with no vendor writer."
        )
    from parcel_robot.bridge.fake_sport import (
        FakeSportFaultsV1,
        FakeSportServiceV1,
        JsonlEventSink,
        NonBlockingEventSinkV1,
    )

    faults = FakeSportFaultsV1(
        move_delay_s=args.move_delay_s,
        move_no_reply=args.move_no_reply,
        stale_state_by_s=args.stale_state_by_s,
        out_of_order_state=args.out_of_order_state,
        stop_move_failure=args.stop_move_failure,
    )
    vendor_sink = (
        NonBlockingEventSinkV1(JsonlEventSink(args.vendor_log))
        if args.vendor_log is not None
        else None
    )
    return FakeSportServiceV1(faults=faults, event_sink=vendor_sink)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    sport = _build_sport(args)
    ring = BoundedAuditRingV1()
    limits = GovernorLimitsV1(regime=regime(args.regime))
    core = GatewayCoreV1(
        sport,
        policy=single_writer_policy(
            required_hashes=BENCH_HASHES,
            writer_id=args.writer_id,
            uid=args.uid,
        ),
        limits=limits,
        audit=ring,
    )
    exporter = AuditExporterV1(ring, args.audit_log)
    ring.record(
        "gateway_process_started",
        boot_epoch=core.boot_epoch,
        phase=core.phase.value,
        transport="unix_sock_seqpacket",
        sport=args.sport,
        regime=limits.regime.name,
        pid=os.getpid(),
        started_at_unix_s=time.time(),
    )
    exporter.start()
    try:
        GatewayServerV1(args.socket, core).serve(stop_event)
    finally:
        exporter.stop()
    return _evidence_exit_code(ring, exporter)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
