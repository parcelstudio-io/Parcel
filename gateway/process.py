"""CLI entry for the M1-0 gateway process (bench and explicit SDK2 wiring).

This file chooses a :class:`gateway.ports.SportPort`, builds the credential
policy from the launch profile, and serves.  ``--sport fake`` remains the
desktop default.  ``--sport vendor`` is opt-in and fails before importing SDK2
unless the launch provides the complete physical NIC/domain and commissioned
frame/axis mapping.  SDK absence or a missing physical interface is fatal.

Evidence export is deliberately outside the control path: the core writes into
its bounded in-memory ring and never calls out, and a daemon thread here pulls
with :meth:`~gateway.audit.BoundedAuditRingV1.drain` and appends JSONL.  A
blocked or failing disk therefore cannot delay a StopMove — it can only make
the process exit nonzero at the end, which is what
:func:`_evidence_exit_code` reports.
"""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from parcel_robot.bridge.protocol import GatewayBodyKindV1, GatewayHashesV1

from .audit import BoundedAuditRingV1
from .core import GatewayCoreV1
from .credentials import CredentialPolicyV1, single_writer_policy
from .limits import DEFAULT_ACTIVE_REGIME, GovernorLimitsV1, regime
from .ports import (
    UnitreeSdk2SportPortV1,
    UnitreeSportConfigV1,
    UnitreeSportError,
    UnitreeWriterLockV1,
)
from .server import (
    PRIVATE_SOCKET_MODE,
    SHARED_SOCKET_MODE,
    GatewayServerV1,
    validate_socket_access,
)

#: Bench compatibility identities.  They mirror
#: ``parcel_robot.bridge.fake_gateway_process.DEFAULT_FAKE_HASHES`` so the two
#: benches interoperate.  A real deployment reads signed manifests instead.
BENCH_HASHES = GatewayHashesV1(
    config_sha256="a" * 64,
    capability_sha256="b" * 64,
    calibration_sha256="c" * 64,
    firmware_sha256="d" * 64,
)

# ``SO_PEERCRED`` is decoded as signed 32-bit integers in credentials.py.
MAX_PEER_ID = (1 << 31) - 1


@dataclass(frozen=True)
class ClientPrincipalV1:
    """The commissioned local client identity and its socket-access group."""

    uid: int
    gid: int


def parse_socket_mode(raw: str) -> int:
    """Parse an access mode as octal and allow only the two shipped contracts."""

    text = raw.strip().lower().removeprefix("0o")
    try:
        mode = int(text, 8)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("socket mode must be octal 0600 or 0660") from exc
    try:
        # Supplying a group is validated after principal resolution.
        validate_socket_access(mode, None if mode == PRIVATE_SOCKET_MODE else 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return mode


def resolve_client_principal(
    *,
    uid: int | None,
    gid: int | None,
    user: str | None,
    group: str | None,
    require_explicit_uid: bool,
    require_explicit_gid: bool,
) -> ClientPrincipalV1:
    """Resolve numeric or NSS client identity, rejecting ambiguity and drift."""

    user = user.strip() if user else None
    group = group.strip() if group else None
    user_entry = None
    group_entry = None
    if user is not None:
        try:
            user_entry = pwd.getpwnam(user)
        except KeyError as exc:
            raise ValueError(f"client user {user!r} does not exist") from exc
        if uid is not None and uid != user_entry.pw_uid:
            raise ValueError(f"client uid {uid} does not match user {user!r} ({user_entry.pw_uid})")
        uid = user_entry.pw_uid
    if group is not None:
        try:
            group_entry = grp.getgrnam(group)
        except KeyError as exc:
            raise ValueError(f"client group {group!r} does not exist") from exc
        if gid is not None and gid != group_entry.gr_gid:
            raise ValueError(
                f"client gid {gid} does not match group {group!r} ({group_entry.gr_gid})"
            )
        gid = group_entry.gr_gid

    if uid is None:
        if require_explicit_uid:
            raise ValueError("an explicit client uid or user is required")
        uid = os.geteuid()
    if gid is None:
        if require_explicit_gid:
            raise ValueError("an explicit client gid or group is required")
        gid = user_entry.pw_gid if user_entry is not None else os.getegid()
    for label, value in (("client uid", uid), ("client gid", gid)):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_PEER_ID:
            raise ValueError(f"{label} must be an integer from 0 through {MAX_PEER_ID}")

    if user_entry is not None and group_entry is not None:
        is_member = user_entry.pw_gid == group_entry.gr_gid or user in group_entry.gr_mem
        if not is_member:
            raise ValueError(f"client user {user!r} is not a member of group {group!r}")
    return ClientPrincipalV1(uid=uid, gid=gid)


def _access_from_args(args: argparse.Namespace) -> tuple[ClientPrincipalV1, int, int | None]:
    """Resolve policy UID plus exact socket mode/ownership before SDK startup."""

    numeric_uid = args.client_uid
    if args.uid is not None:
        if numeric_uid is not None and numeric_uid != args.uid:
            raise SystemExit("gateway.process: --uid and --client-uid disagree")
        numeric_uid = args.uid
    vendor = args.sport == "vendor"
    try:
        principal = resolve_client_principal(
            uid=numeric_uid,
            gid=args.client_gid,
            user=args.client_user,
            group=args.client_group,
            require_explicit_uid=vendor,
            require_explicit_gid=vendor,
        )
        if vendor and args.socket_mode is None:
            raise ValueError("--sport vendor requires explicit --socket-mode 0660")
        socket_mode = args.socket_mode or PRIVATE_SOCKET_MODE
        if vendor and socket_mode != SHARED_SOCKET_MODE:
            raise ValueError("--sport vendor requires --socket-mode 0660")
        if socket_mode == SHARED_SOCKET_MODE and not (
            args.client_gid is not None or args.client_group
        ):
            raise ValueError("--socket-mode 0660 requires an explicit client gid or group")
        socket_gid = principal.gid if socket_mode == SHARED_SOCKET_MODE else None
        validate_socket_access(socket_mode, socket_gid)
    except ValueError as exc:
        profile = "vendor " if vendor else ""
        raise SystemExit(f"gateway.process: invalid {profile}client/socket access: {exc}") from exc
    return principal, socket_mode, socket_gid


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
    parser.add_argument("--config-sha256", default=None)
    parser.add_argument("--capability-sha256", default=None)
    parser.add_argument("--calibration-sha256", default=None)
    parser.add_argument("--firmware-sha256", default=None)
    parser.add_argument("--unitree-interface", default=None)
    parser.add_argument("--unitree-domain-id", type=int, default=None)
    parser.add_argument(
        "--unitree-allowed-mode",
        dest="unitree_allowed_modes",
        action="append",
        type=int,
        default=None,
        help="repeat for every commissioned SportModeState mode",
    )
    parser.add_argument(
        "--unitree-allowed-error-code",
        dest="unitree_allowed_error_codes",
        action="append",
        type=int,
        default=None,
        help="repeat for every commissioned SportModeState error code",
    )
    parser.add_argument(
        "--unitree-state-velocity-frame",
        choices=("base_link", "odom"),
        default=None,
    )
    parser.add_argument("--unitree-lateral-sign", type=int, choices=(-1, 1), default=None)
    parser.add_argument("--unitree-yaw-sign", type=int, choices=(-1, 1), default=None)
    parser.add_argument("--unitree-axes-commissioned", action="store_true")
    parser.add_argument("--unitree-state-frame-commissioned", action="store_true")
    parser.add_argument(
        "--unitree-sport-state-stamp-monotonic-commissioned",
        action="store_true",
    )
    parser.add_argument("--unitree-battery-soc-percent-commissioned", action="store_true")
    parser.add_argument("--unitree-minimum-battery-soc-percent", type=int, default=None)
    parser.add_argument(
        "--unitree-low-state-tick-monotonic-commissioned",
        action="store_true",
    )
    parser.add_argument("--unitree-state-topic", default="rt/sportmodestate")
    parser.add_argument("--unitree-low-state-topic", default="rt/lowstate")
    parser.add_argument("--unitree-rpc-timeout-s", type=float, default=0.2)
    parser.add_argument("--unitree-startup-timeout-s", type=float, default=2.0)
    parser.add_argument(
        "--unitree-subscriber-queue-depth",
        type=int,
        choices=(0,),
        default=0,
        help="must remain 0 so the SDK invokes the bounded direct callback",
    )
    parser.add_argument("--writer-id", default="m1-0-bench-client")
    parser.add_argument("--regime", default=DEFAULT_ACTIVE_REGIME)
    parser.add_argument(
        "--uid",
        type=int,
        default=None,
        help="legacy alias for the uid allowed to hold the lease",
    )
    parser.add_argument("--client-uid", type=int, default=None)
    parser.add_argument("--client-gid", type=int, default=None)
    parser.add_argument("--client-user", default=None)
    parser.add_argument("--client-group", default=None)
    parser.add_argument(
        "--socket-mode",
        type=parse_socket_mode,
        default=None,
        help="0600 (private default) or explicit 0660 with a client gid/group",
    )
    parser.add_argument("--move-delay-s", type=float, default=0.0)
    parser.add_argument("--move-no-reply", action="store_true")
    parser.add_argument("--stale-state-by-s", type=float, default=0.0)
    parser.add_argument("--out-of-order-state", action="store_true")
    parser.add_argument("--stop-move-failure", action="store_true")
    return parser


def _evidence_exit_code(ring: BoundedAuditRingV1, exporter: AuditExporterV1) -> int:
    """Lost evidence is visible in the exit status and nowhere near the stop path."""

    return 0 if ring.dropped_records == 0 and exporter.write_errors == 0 else 2


def construct_core_or_close_sport(
    sport: object,
    *,
    policy: CredentialPolicyV1,
    limits: GovernorLimitsV1,
    audit: BoundedAuditRingV1,
    body_kind: GatewayBodyKindV1 = GatewayBodyKindV1.UNKNOWN,
) -> GatewayCoreV1:
    """Never leak a physical lease when boot-stop construction fails."""

    try:
        return GatewayCoreV1(
            sport,
            policy=policy,
            limits=limits,
            audit=audit,
            body_kind=body_kind,
        )
    except BaseException:
        _close_sport_without_masking(sport)
        raise


def _close_sport_without_masking(sport: object) -> None:
    try:
        sport.close()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - preserve the gateway construction failure
        return


def _close_core_then_cleanup(
    core: object,
    ancillary: tuple[Callable[[], None], ...],
) -> None:
    """Command the body-safe core close before best-effort ancillary cleanup."""

    try:
        core.close()  # type: ignore[attr-defined]
    finally:
        for cleanup in ancillary:
            try:
                cleanup()
            except Exception:  # noqa: BLE001, S112 - preserve body cleanup outcome
                continue


def _required_hashes_from_args(args: argparse.Namespace) -> GatewayHashesV1:
    if args.sport == "fake":
        return BENCH_HASHES
    values = {
        "config_sha256": args.config_sha256,
        "capability_sha256": args.capability_sha256,
        "calibration_sha256": args.calibration_sha256,
        "firmware_sha256": args.firmware_sha256,
    }
    missing = [f"--{name.replace('_', '-')}" for name, value in values.items() if not value]
    if missing:
        raise SystemExit(
            "gateway.process: --sport vendor requires explicit launch compatibility "
            f"hashes; missing {', '.join(missing)}"
        )
    try:
        hashes = GatewayHashesV1(**values)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"gateway.process: invalid launch compatibility hash: {exc}") from exc
    if hashes == BENCH_HASHES:
        raise SystemExit("gateway.process: --sport vendor refuses the fixed BENCH_HASHES identity")
    return hashes


def _build_sport(
    args: argparse.Namespace,
    *,
    writer_authority: UnitreeWriterLockV1 | None = None,
) -> object:
    if args.sport == "vendor":
        # Validate authority identity before SDK construction can acquire the
        # physical lease. ``main`` retains the same value for its policy.
        _required_hashes_from_args(args)
        required = {
            "--unitree-interface": args.unitree_interface,
            "--unitree-domain-id": args.unitree_domain_id,
            "--unitree-allowed-mode": args.unitree_allowed_modes,
            "--unitree-allowed-error-code": args.unitree_allowed_error_codes,
            "--unitree-state-velocity-frame": args.unitree_state_velocity_frame,
            "--unitree-lateral-sign": args.unitree_lateral_sign,
            "--unitree-yaw-sign": args.unitree_yaw_sign,
        }
        missing = [name for name, value in required.items() if value is None]
        if not args.unitree_axes_commissioned:
            missing.append("--unitree-axes-commissioned")
        if not args.unitree_state_frame_commissioned:
            missing.append("--unitree-state-frame-commissioned")
        if not args.unitree_sport_state_stamp_monotonic_commissioned:
            missing.append("--unitree-sport-state-stamp-monotonic-commissioned")
        if not args.unitree_battery_soc_percent_commissioned:
            missing.append("--unitree-battery-soc-percent-commissioned")
        if args.unitree_minimum_battery_soc_percent is None:
            missing.append("--unitree-minimum-battery-soc-percent")
        if not args.unitree_low_state_tick_monotonic_commissioned:
            missing.append("--unitree-low-state-tick-monotonic-commissioned")
        if missing:
            raise SystemExit(
                "gateway.process: --sport vendor requires explicit commissioned "
                f"Unitree configuration; missing {', '.join(missing)}"
            )
        try:
            config = UnitreeSportConfigV1(
                interface=args.unitree_interface,
                domain_id=args.unitree_domain_id,
                allowed_modes=tuple(args.unitree_allowed_modes),
                allowed_error_codes=tuple(args.unitree_allowed_error_codes),
                state_velocity_frame=args.unitree_state_velocity_frame,
                lateral_sign=args.unitree_lateral_sign,
                yaw_sign=args.unitree_yaw_sign,
                axes_commissioned=args.unitree_axes_commissioned,
                state_frame_commissioned=args.unitree_state_frame_commissioned,
                sport_state_stamp_monotonic_commissioned=(
                    args.unitree_sport_state_stamp_monotonic_commissioned
                ),
                battery_soc_percent_commissioned=(args.unitree_battery_soc_percent_commissioned),
                minimum_battery_soc_percent=args.unitree_minimum_battery_soc_percent,
                low_state_tick_monotonic_commissioned=(
                    args.unitree_low_state_tick_monotonic_commissioned
                ),
                state_topic=args.unitree_state_topic,
                low_state_topic=args.unitree_low_state_topic,
                rpc_timeout_s=args.unitree_rpc_timeout_s,
                startup_timeout_s=args.unitree_startup_timeout_s,
                subscriber_queue_depth=args.unitree_subscriber_queue_depth,
            )
            return UnitreeSdk2SportPortV1(config, _writer_authority=writer_authority)
        except (TypeError, ValueError, UnitreeSportError) as exc:
            raise SystemExit(f"gateway.process: Unitree vendor startup refused: {exc}") from exc
    if args.sport != "fake":
        raise SystemExit(f"gateway.process: unknown sport backend {args.sport!r}")
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

    writer_lock = UnitreeWriterLockV1(required=args.sport == "vendor")
    try:
        writer_lock.acquire()
    except (OSError, RuntimeError) as exc:
        raise SystemExit(
            f"gateway.process: {args.sport} writer authority unavailable: {exc}"
        ) from None
    try:
        return _run_with_writer_authority(args, stop_event, writer_lock=writer_lock)
    finally:
        writer_lock.close()


def _run_with_writer_authority(
    args: argparse.Namespace,
    stop_event: threading.Event,
    *,
    writer_lock: UnitreeWriterLockV1,
) -> int:
    """Build the SDK/core only while device-wide writer authority is held."""

    # Resolve every local policy input before SDK construction can acquire the
    # physical lease.
    principal, socket_mode, socket_gid = _access_from_args(args)
    required_hashes = _required_hashes_from_args(args)
    limits = GovernorLimitsV1(regime=regime(args.regime))
    policy = single_writer_policy(
        required_hashes=required_hashes,
        writer_id=args.writer_id,
        uid=principal.uid,
    )
    ring = BoundedAuditRingV1()
    sport = _build_sport(args, writer_authority=writer_lock)
    core = construct_core_or_close_sport(
        sport,
        policy=policy,
        limits=limits,
        audit=ring,
        body_kind=(
            GatewayBodyKindV1.UNITREE_SDK2 if args.sport == "vendor" else GatewayBodyKindV1.FAKE
        ),
    )
    exporter = AuditExporterV1(ring, args.audit_log)
    try:
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
        GatewayServerV1(
            args.socket,
            core,
            socket_mode=socket_mode,
            socket_gid=socket_gid,
        ).serve(stop_event)
    finally:
        # GatewayServer closes the core on the normal path. This idempotent
        # fallback also covers socket-open/readiness setup failures before
        # serve's own try/finally becomes active. Body stop remains first;
        # evidence cleanup cannot delay or mask it.
        _close_core_then_cleanup(core, (exporter.stop,))
    return _evidence_exit_code(ring, exporter)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
