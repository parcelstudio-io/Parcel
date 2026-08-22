"""``python -m parcel_robot.perception_daemon`` — run or probe the daemon.

Two modes and no third:

* default — bind the socket, load the models, serve until SIGINT/SIGTERM.
* ``--probe`` — connect to an already-running daemon, print its health as JSON,
  exit 0 if it answered and 1 if it did not. This is what
  ``scripts/launch_detector_daemon.sh`` uses for readiness, and what an
  operator uses to ask "are my eyes up?" without starting a second copy.

``--preload`` builds the sessions it can BEFORE the socket starts answering, so
the first real frame does not pay a cold ORT session. Off by default because the
contract tests and the ``--probe`` path must not need weights on disk.

**What ``--preload`` actually warms, measured 2026-08-22 and narrower than it
sounds:** the OWLv2 detector session and the SigLIP-2 **text** session. It does
NOT build the SigLIP-2 **vision** session — ``_OnnxSigLIP2Embedder`` resolves
text and vision independently and builds vision lazily inside ``_ensure_vision``
on the first ``embed_image``. So after ``--preload`` the first ``embed_image``
still pays a cold session: **418 ms on this host** (188 ms in Fable's
verification run — it moves with load), against a warm p50 of 3.3 ms.
``health()`` reports ``embedder_loaded: true`` throughout, which is true of the
embedder object and not of the vision session behind it. If that first-call
stall matters on the robot's map-writer path, warm it with one throwaway
``embed_image`` after start — see ``P1A_STATUS.md`` §11 handoff.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from collections.abc import Sequence

from parcel_robot.perception_daemon.client import DaemonClient, DaemonRequestFailed
from parcel_robot.perception_daemon.protocol import DaemonUnavailable, default_socket_path
from parcel_robot.perception_daemon.server import PerceptionDaemon


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m parcel_robot.perception_daemon",
        description="Out-of-process OWLv2 + SigLIP-2 perception daemon (card P1-A).",
    )
    parser.add_argument(
        "--socket",
        default=None,
        help=f"AF_UNIX socket path (default: {default_socket_path()})",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="print a running daemon's health as JSON and exit (0 = answered)",
    )
    parser.add_argument(
        "--shutdown",
        action="store_true",
        help="ask a running daemon to stop, then exit",
    )
    parser.add_argument(
        "--preload",
        action="store_true",
        help=(
            "warm the OWLv2 session and the SigLIP-2 TEXT session before serving. "
            "The SigLIP-2 vision session still loads lazily on the first "
            "embed_image (~0.2-0.4 s); see the module docstring."
        ),
    )
    parser.add_argument(
        "--max-clients", type=int, default=8, help="concurrent connection ceiling"
    )
    parser.add_argument(
        "--log-level", default="INFO", help="Python logging level (default INFO)"
    )
    return parser


def _probe(socket_path: str | None) -> int:
    client = DaemonClient(socket_path)
    try:
        report = client.health()
    except (DaemonUnavailable, DaemonRequestFailed) as exc:
        print(
            json.dumps({"reachable": False, "socket": client.socket_path, "error": str(exc)}),
            file=sys.stderr,
        )
        return 1
    finally:
        client.close()
    print(json.dumps({"reachable": True, **report}, sort_keys=True))
    return 0


def _shutdown(socket_path: str | None) -> int:
    client = DaemonClient(socket_path)
    try:
        client.shutdown()
    except (DaemonUnavailable, DaemonRequestFailed) as exc:
        print(f"perception daemon did not accept shutdown: {exc}", file=sys.stderr)
        return 1
    print("perception daemon stopping")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    if args.probe:
        return _probe(args.socket)
    if args.shutdown:
        return _shutdown(args.socket)

    daemon = PerceptionDaemon(
        args.socket, max_clients=args.max_clients, preload=args.preload
    )
    stopped = threading.Event()

    def _handle(signum: int, _frame: object) -> None:
        logging.getLogger(__name__).info("signal %s — stopping perception daemon", signum)
        stopped.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    daemon.start()
    logging.getLogger(__name__).info(
        "perception daemon listening on %s (preload=%s)", daemon.socket_path, args.preload
    )
    try:
        while not stopped.is_set() and daemon.running:
            stopped.wait(0.5)
    finally:
        daemon.stop()
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
