"""CLI entry for the N24 test-only fake gateway subprocess."""

from __future__ import annotations

import argparse
import signal
import threading

from .fake_gateway import FakeGatewayCoreV1, FakeGatewayServerV1
from .fake_sport import (
    FakeSportFaultsV1,
    FakeSportServiceV1,
    JsonlEventSink,
    NonBlockingEventSinkV1,
)
from .protocol import GatewayHashesV1

DEFAULT_FAKE_HASHES = GatewayHashesV1(
    config_sha256="a" * 64,
    capability_sha256="b" * 64,
    calibration_sha256="c" * 64,
    firmware_sha256="d" * 64,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True, help="test-only Unix seqpacket path")
    parser.add_argument("--event-log", required=True, help="append-only JSONL evidence path")
    parser.add_argument("--move-delay-s", type=float, default=0.0)
    parser.add_argument("--move-no-reply", action="store_true")
    parser.add_argument("--stale-state-by-s", type=float, default=0.0)
    parser.add_argument("--out-of-order-state", action="store_true")
    parser.add_argument("--stop-move-failure", action="store_true")
    return parser


def _evidence_exit_code(sink: NonBlockingEventSinkV1, *, drained: bool) -> int:
    """Make lost/failed process evidence visible without affecting stop control."""

    clean = drained and sink.sink_errors == 0 and sink.dropped_events == 0
    return 0 if clean else 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    sink = NonBlockingEventSinkV1(JsonlEventSink(args.event_log))
    faults = FakeSportFaultsV1(
        move_delay_s=args.move_delay_s,
        move_no_reply=args.move_no_reply,
        stale_state_by_s=args.stale_state_by_s,
        out_of_order_state=args.out_of_order_state,
        stop_move_failure=args.stop_move_failure,
    )
    sport = FakeSportServiceV1(faults=faults, event_sink=sink)
    core = FakeGatewayCoreV1(
        sport,
        required_hashes=DEFAULT_FAKE_HASHES,
        event_sink=sink,
    )
    sink(
        {
            "event": "gateway_started",
            "boot_epoch": core.boot_epoch,
            "phase": core.phase.value,
            "transport": "unix_sock_seqpacket",
        }
    )
    FakeGatewayServerV1(args.socket, core).serve(stop_event)
    # Shutdown evidence gets a bounded drain. It is never on the stop path,
    # and a stuck disk/sink produces an explicit nonzero process result.
    drained = sink.drain(timeout_s=1.0)
    return _evidence_exit_code(sink, drained=drained)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
