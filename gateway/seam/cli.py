"""``parcel-gateway`` — the console entry point named by the systemd unit.

``deploy/orin/services/parcel-gateway.service`` says

    ExecStartPre=/usr/bin/test -x /opt/parcel/bin/parcel-gateway
    ExecStart=/opt/parcel/bin/parcel-gateway --disarmed

and until this module there was no such executable anywhere: ``gateway/
process.py`` is a bench CLI whose two required arguments (``--socket``,
``--audit-log``) the unit does not pass, and no distribution installed
anything into a ``bin/``.  This module is the console script that
``gateway/pyproject.toml`` publishes under exactly that name, and
``tests/test_motion_seam.py`` reads the unit file and proves the agreement
rather than asserting it.

**Where the settings come from, and why.**  A systemd unit configures a
process through the environment, so every argument has an environment default
that matches what the unit actually provides:

===========================  ====================================================
``--socket``                 ``PARCEL_GATEWAY_SOCKET``, else
                             ``$STATE_DIRECTORY/gateway.sock`` — ``StateDirectory
                             =parcel/gateway`` is what makes that directory exist
``--audit-log``              ``PARCEL_GATEWAY_AUDIT_LOG``, else
                             ``$LOGS_DIRECTORY/audit.jsonl`` — from
                             ``LogsDirectory=parcel/gateway``
``--sport``                  ``PARCEL_GATEWAY_SPORT``. **No default.**
``--regime``                 ``PARCEL_GATEWAY_REGIME``, else the slowest regime
``--writer-id``              ``PARCEL_GATEWAY_WRITER_ID``
``--disarmed``               asserts ``PARCEL_ARMED=0``; refuses anything else
===========================  ====================================================

**There is no default sport backend, on purpose.**  The unit's ``ExecStart``
passes only ``--disarmed``; if this CLI defaulted to ``fake`` then installing
the unit on a robot would start a gateway that cheerfully serves a *simulated*
body and reports healthy.  So a backend must be named, and naming ``vendor``
refuses to start with the same reason ``gateway/process.py`` gives: there is no
vendor SDK in this tree.  A gateway with no vendor writer must not exist.

**Readiness is earned.**  ``Type=notify`` means systemd waits for ``READY=1``.
This process sends it only after the listening socket exists with mode
``0600`` **and** one bounded probe of the core lock has come back — see
:mod:`gateway.seam.notify`.  ``WATCHDOG=1`` pings are gated the same way, so a
wedged core stops the pings instead of being papered over by them.

**Arming is not a boot property.**  ``--disarmed`` is an assertion, not a mode:
the core is DISARMED at construction and there is no flag, environment
variable or code path here that can arm it.  The only way this process ever
holds motion authority is a client's explicit acquire transaction over the
socket, and a restart throws that away with the boot epoch.

**Bench honesty.**  This is the one module in :mod:`gateway.seam` that may name
the fake vendor, and it does so by importing ``gateway.process``'s bench
constants — the module already declared bench-only — so the tree still has
exactly one place that knows what a ``FakeSportServiceV1`` is.  A ``fake``
launch is a desktop bench, never a robot.
"""

from __future__ import annotations

import argparse
import os
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..audit import BoundedAuditRingV1
from ..core import GatewayCoreV1
from ..credentials import single_writer_policy
from ..limits import DEFAULT_ACTIVE_REGIME, GovernorLimitsV1, regime
from ..process import BENCH_HASHES, AuditExporterV1
from ..server import GatewayServerV1
from .notify import GatewayLivenessNotifierV1, SdNotifierV1, read_supervision

#: The console script name. Must equal the basename of the unit's ``ExecStart``.
CONSOLE_SCRIPT_NAME = "parcel-gateway"

#: Environment names, all of which a systemd ``EnvironmentFile`` can set.
SOCKET_ENV = "PARCEL_GATEWAY_SOCKET"
AUDIT_LOG_ENV = "PARCEL_GATEWAY_AUDIT_LOG"
SPORT_ENV = "PARCEL_GATEWAY_SPORT"
REGIME_ENV = "PARCEL_GATEWAY_REGIME"
WRITER_ID_ENV = "PARCEL_GATEWAY_WRITER_ID"
ARMED_ENV = "PARCEL_ARMED"

#: systemd's own, from ``StateDirectory=`` / ``LogsDirectory=``.
STATE_DIRECTORY_ENV = "STATE_DIRECTORY"
LOGS_DIRECTORY_ENV = "LOGS_DIRECTORY"

DEFAULT_WRITER_ID = "parcel-runtime"
DEFAULT_SOCKET_NAME = "gateway.sock"
DEFAULT_AUDIT_NAME = "audit.jsonl"

#: How long a bounded liveness probe may take before the ping is withheld.
#: 1.5x the stop budget: a legitimate stop holds the core lock for up to
#: ``stop_timeout_s`` and must not look like a wedge.
PROBE_BUDGET_FACTOR = 1.5


class GatewayLaunchError(SystemExit):
    """A launch profile this process refuses to start from. Exits nonzero."""


@dataclass(frozen=True)
class LaunchSettingsV1:
    socket_path: Path
    audit_log: Path
    sport: str
    regime_name: str
    writer_id: str
    uid: int | None
    ready_timeout_s: float
    disarmed_asserted: bool


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=CONSOLE_SCRIPT_NAME,
        description="Parcel motion gateway — sole vendor writer, lease/TTL/stop latch.",
    )
    parser.add_argument(
        "--disarmed",
        action="store_true",
        help=(
            "assert the boot-disarmed contract: the gateway grants no motion "
            "authority at start and PARCEL_ARMED must be 0 or unset"
        ),
    )
    parser.add_argument("--socket", default=None, help=f"seqpacket path (${SOCKET_ENV})")
    parser.add_argument("--audit-log", default=None, help=f"JSONL export (${AUDIT_LOG_ENV})")
    parser.add_argument(
        "--sport",
        choices=("fake", "vendor"),
        default=None,
        help=f"which body to write to (${SPORT_ENV}); there is no default",
    )
    parser.add_argument("--regime", default=None, help=f"speed regime (${REGIME_ENV})")
    parser.add_argument("--writer-id", default=None, help=f"lease holder (${WRITER_ID_ENV})")
    parser.add_argument("--uid", type=int, default=None, help="uid allowed to hold the lease")
    parser.add_argument(
        "--ready-timeout-s",
        type=float,
        default=10.0,
        help="how long to wait for the listening socket before giving up on READY=1",
    )
    return parser


def _first_directory(raw: str) -> str:
    """systemd may hand several colon-separated directories; the first is ours."""

    return raw.split(":")[0] if raw else ""


def settings_from(
    args: argparse.Namespace,
    environ: dict[str, str],
) -> LaunchSettingsV1:
    """Resolve the launch profile, refusing anything ambiguous or armed."""

    armed = environ.get(ARMED_ENV, "0").strip()
    if armed not in {"", "0"}:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: {ARMED_ENV}={armed!r} — arming is a client "
            "transaction against a running gateway, never a boot property. "
            "Refusing to start."
        )
    sport = args.sport or environ.get(SPORT_ENV, "").strip()
    if not sport:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: no body named. Pass --sport or set "
            f"{SPORT_ENV}. There is deliberately no default: a gateway that "
            "picks its own body could serve a simulated one on a real robot."
        )
    if sport not in {"fake", "vendor"}:
        raise GatewayLaunchError(f"{CONSOLE_SCRIPT_NAME}: unknown sport backend {sport!r}")
    if sport == "vendor":
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: --sport vendor is not implemented — no "
            "vendor SDK is present in this tree and no robot exists yet. "
            "Refusing to start a gateway with no vendor writer."
        )
    socket_raw = args.socket or environ.get(SOCKET_ENV, "").strip()
    if not socket_raw:
        state = _first_directory(environ.get(STATE_DIRECTORY_ENV, ""))
        if not state:
            raise GatewayLaunchError(
                f"{CONSOLE_SCRIPT_NAME}: no socket path. Pass --socket, set "
                f"{SOCKET_ENV}, or run under a unit with StateDirectory="
            )
        socket_raw = str(Path(state) / DEFAULT_SOCKET_NAME)
    audit_raw = args.audit_log or environ.get(AUDIT_LOG_ENV, "").strip()
    if not audit_raw:
        logs = _first_directory(environ.get(LOGS_DIRECTORY_ENV, ""))
        if not logs:
            raise GatewayLaunchError(
                f"{CONSOLE_SCRIPT_NAME}: no audit log path. Pass --audit-log, "
                f"set {AUDIT_LOG_ENV}, or run under a unit with LogsDirectory="
            )
        audit_raw = str(Path(logs) / DEFAULT_AUDIT_NAME)
    regime_name = args.regime or environ.get(REGIME_ENV, "").strip() or DEFAULT_ACTIVE_REGIME
    try:
        regime(regime_name)
    except ValueError as exc:
        raise GatewayLaunchError(f"{CONSOLE_SCRIPT_NAME}: {exc}") from exc
    return LaunchSettingsV1(
        socket_path=Path(socket_raw),
        audit_log=Path(audit_raw),
        sport=sport,
        regime_name=regime_name,
        writer_id=args.writer_id or environ.get(WRITER_ID_ENV, "").strip() or DEFAULT_WRITER_ID,
        uid=args.uid,
        ready_timeout_s=float(args.ready_timeout_s),
        disarmed_asserted=bool(args.disarmed),
    )


def _build_sport(settings: LaunchSettingsV1) -> object:
    """Only ``fake`` can be built here. Belt and braces: ``vendor`` refuses twice."""

    if settings.sport != "fake":
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: refusing to build a {settings.sport!r} body"
        )
    from parcel_robot.bridge.fake_sport import FakeSportServiceV1

    return FakeSportServiceV1()


def _socket_is_listening(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return (metadata.st_mode & 0o777) == 0o600


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = settings_from(args, dict(os.environ))

    sport = _build_sport(settings)
    ring = BoundedAuditRingV1()
    limits = GovernorLimitsV1(regime=regime(settings.regime_name))
    core = GatewayCoreV1(
        sport,
        policy=single_writer_policy(
            required_hashes=BENCH_HASHES,
            writer_id=settings.writer_id,
            uid=settings.uid,
        ),
        limits=limits,
        audit=ring,
    )
    exporter = AuditExporterV1(ring, settings.audit_log)
    supervision = read_supervision()
    notifier = SdNotifierV1(supervision.notify_address)
    liveness = GatewayLivenessNotifierV1(
        notifier,
        # A real probe: both properties take the core ``RLock``, and neither
        # changes anything.  A core that cannot answer is a core that is wedged.
        lambda: (core.stop_sequence, core.latched),
        watchdog_period_s=supervision.watchdog_period_s,
        probe_timeout_s=limits.stop_timeout_s * PROBE_BUDGET_FACTOR,
    )
    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    ring.record(
        "gateway_process_started",
        boot_epoch=core.boot_epoch,
        phase=core.phase.value,
        entry_point=CONSOLE_SCRIPT_NAME,
        transport="unix_sock_seqpacket",
        sport=settings.sport,
        regime=limits.regime.name,
        disarmed_asserted=settings.disarmed_asserted,
        supervised=supervision.supervised,
        pid=os.getpid(),
        started_at_unix_s=time.time(),
    )
    exporter.start()
    announcer = threading.Thread(
        target=_announce_when_ready,
        args=(liveness, settings, core.boot_epoch, stop_event),
        name="parcel-gateway-readiness",
        daemon=True,
    )
    announcer.start()
    try:
        GatewayServerV1(settings.socket_path, core).serve(stop_event)
    finally:
        stop_event.set()
        liveness.stop(status="gateway stopped; body commanded to exact zero")
        exporter.stop()
    return 0 if ring.dropped_records == 0 and exporter.write_errors == 0 else 2


def _announce_when_ready(
    liveness: GatewayLivenessNotifierV1,
    settings: LaunchSettingsV1,
    boot_epoch: str,
    stop_event: threading.Event,
) -> None:
    """READY=1 once the socket is really listening and the core really answers."""

    deadline = time.monotonic() + settings.ready_timeout_s
    while time.monotonic() < deadline and not stop_event.is_set():
        if _socket_is_listening(settings.socket_path) and liveness.announce_ready(
            status=f"disarmed; boot_epoch={boot_epoch}; sport={settings.sport}"
        ):
            liveness.start()
            return
        time.sleep(0.01)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
