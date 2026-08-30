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
``--client-*``               explicit runtime UID/GID, or resolvable
                             ``PARCEL_GATEWAY_CLIENT_USER`` / ``*_GROUP``
``--stop-client-*``          distinct observe/latched-STOP-only UID or user;
                             required for the physical ``vendor`` profile
``--socket-mode``            ``PARCEL_GATEWAY_SOCKET_MODE``; private ``0600``
                             by default, explicit ``0660`` for ``vendor``
``--disarmed``               asserts ``PARCEL_ARMED=0``; refuses anything else
``--*-sha256``               four ``PARCEL_GATEWAY_*_SHA256`` identities;
                             required for ``vendor``, fixed bench values only
                             for ``fake``
``--unitree-*``              ``PARCEL_UNITREE_*`` physical NIC/domain, mode,
                             frame/sign commissioning and bounded I/O settings
===========================  ====================================================

**There is no default sport backend, on purpose.**  The unit's ``ExecStart``
passes only ``--disarmed``; if this CLI defaulted to ``fake`` then installing
the unit on a robot would start a gateway that cheerfully serves a *simulated*
body and reports healthy.  A backend must be named.  ``vendor`` additionally
requires an explicit NIC, DDS domain, mode allowlist and commissioned
frame/axis mapping; only then does the optional SDK2 package get loaded.

**Readiness is earned.**  ``Type=notify`` means systemd waits for ``READY=1``.
This process sends it only after the listening socket exists with its exact
commissioned mode/group **and** one bounded probe of the core lock has come back — see
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
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from parcel_robot.bridge.protocol import GatewayBodyKindV1, GatewayHashesV1

from ..audit import BoundedAuditRingV1
from ..credentials import single_writer_policy, writer_with_stop_only_policy
from ..limits import DEFAULT_ACTIVE_REGIME, GovernorLimitsV1, regime
from ..ports import (
    UnitreeSdk2SportPortV1,
    UnitreeSportConfigV1,
    UnitreeSportError,
    UnitreeWriterLockV1,
)
from ..process import (
    BENCH_HASHES,
    AuditExporterV1,
    _close_core_then_cleanup,
    construct_core_or_close_sport,
    parse_socket_mode,
    resolve_client_principal,
)
from ..server import (
    PRIVATE_SOCKET_MODE,
    SHARED_SOCKET_MODE,
    GatewayServerV1,
    validate_socket_access,
)
from .notify import GatewayLivenessNotifierV1, SdNotifierV1, read_supervision

#: The console script name. Must equal the basename of the unit's ``ExecStart``.
CONSOLE_SCRIPT_NAME = "parcel-gateway"

#: Environment names, all of which a systemd ``EnvironmentFile`` can set.
SOCKET_ENV = "PARCEL_GATEWAY_SOCKET"
AUDIT_LOG_ENV = "PARCEL_GATEWAY_AUDIT_LOG"
SPORT_ENV = "PARCEL_GATEWAY_SPORT"
REGIME_ENV = "PARCEL_GATEWAY_REGIME"
WRITER_ID_ENV = "PARCEL_GATEWAY_WRITER_ID"
CLIENT_UID_ENV = "PARCEL_GATEWAY_CLIENT_UID"
CLIENT_GID_ENV = "PARCEL_GATEWAY_CLIENT_GID"
CLIENT_USER_ENV = "PARCEL_GATEWAY_CLIENT_USER"
CLIENT_GROUP_ENV = "PARCEL_GATEWAY_CLIENT_GROUP"
STOP_CLIENT_UID_ENV = "PARCEL_GATEWAY_STOP_CLIENT_UID"
STOP_CLIENT_USER_ENV = "PARCEL_GATEWAY_STOP_CLIENT_USER"
SOCKET_MODE_ENV = "PARCEL_GATEWAY_SOCKET_MODE"
ARMED_ENV = "PARCEL_ARMED"
CONFIG_SHA256_ENV = "PARCEL_GATEWAY_CONFIG_SHA256"
CAPABILITY_SHA256_ENV = "PARCEL_GATEWAY_CAPABILITY_SHA256"
CALIBRATION_SHA256_ENV = "PARCEL_GATEWAY_CALIBRATION_SHA256"
FIRMWARE_SHA256_ENV = "PARCEL_GATEWAY_FIRMWARE_SHA256"
UNITREE_INTERFACE_ENV = "PARCEL_UNITREE_INTERFACE"
UNITREE_DOMAIN_ID_ENV = "PARCEL_UNITREE_DOMAIN_ID"
UNITREE_ALLOWED_MODES_ENV = "PARCEL_UNITREE_ALLOWED_MODES"
UNITREE_ALLOWED_ERROR_CODES_ENV = "PARCEL_UNITREE_ALLOWED_ERROR_CODES"
UNITREE_STATE_VELOCITY_FRAME_ENV = "PARCEL_UNITREE_STATE_VELOCITY_FRAME"
UNITREE_LATERAL_SIGN_ENV = "PARCEL_UNITREE_LATERAL_SIGN"
UNITREE_YAW_SIGN_ENV = "PARCEL_UNITREE_YAW_SIGN"
UNITREE_AXES_COMMISSIONED_ENV = "PARCEL_UNITREE_AXES_COMMISSIONED"
UNITREE_STATE_FRAME_COMMISSIONED_ENV = "PARCEL_UNITREE_STATE_FRAME_COMMISSIONED"
UNITREE_SPORT_STATE_STAMP_MONOTONIC_COMMISSIONED_ENV = (
    "PARCEL_UNITREE_SPORT_STATE_STAMP_MONOTONIC_COMMISSIONED"
)
UNITREE_BATTERY_SOC_PERCENT_COMMISSIONED_ENV = "PARCEL_UNITREE_BATTERY_SOC_PERCENT_COMMISSIONED"
UNITREE_MINIMUM_BATTERY_SOC_PERCENT_ENV = "PARCEL_UNITREE_MINIMUM_BATTERY_SOC_PERCENT"
UNITREE_LOW_STATE_TICK_MONOTONIC_COMMISSIONED_ENV = (
    "PARCEL_UNITREE_LOW_STATE_TICK_MONOTONIC_COMMISSIONED"
)
UNITREE_STATE_TOPIC_ENV = "PARCEL_UNITREE_STATE_TOPIC"
UNITREE_LOW_STATE_TOPIC_ENV = "PARCEL_UNITREE_LOW_STATE_TOPIC"
UNITREE_RPC_TIMEOUT_ENV = "PARCEL_UNITREE_RPC_TIMEOUT_S"
UNITREE_STARTUP_TIMEOUT_ENV = "PARCEL_UNITREE_STARTUP_TIMEOUT_S"
UNITREE_SUBSCRIBER_QUEUE_DEPTH_ENV = "PARCEL_UNITREE_SUBSCRIBER_QUEUE_DEPTH"

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
    client_uid: int
    client_gid: int
    stop_client_uid: int | None
    socket_mode: int
    socket_gid: int | None
    ready_timeout_s: float
    disarmed_asserted: bool
    required_hashes: GatewayHashesV1
    unitree_config: UnitreeSportConfigV1 | None = None

    @property
    def uid(self) -> int:
        """Compatibility spelling for the credential policy's client UID."""

        return self.client_uid


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
    parser.add_argument(
        "--uid",
        type=int,
        default=None,
        help="legacy alias for --client-uid",
    )
    parser.add_argument("--client-uid", type=int, default=None)
    parser.add_argument("--client-gid", type=int, default=None)
    parser.add_argument("--client-user", default=None)
    parser.add_argument("--client-group", default=None)
    parser.add_argument("--stop-client-uid", type=int, default=None)
    parser.add_argument("--stop-client-user", default=None)
    parser.add_argument("--socket-mode", type=parse_socket_mode, default=None)
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
        help=f"repeatable commissioned mode (${UNITREE_ALLOWED_MODES_ENV}, comma-separated)",
    )
    parser.add_argument(
        "--unitree-allowed-error-code",
        dest="unitree_allowed_error_codes",
        action="append",
        type=int,
        default=None,
        help=(
            "repeatable commissioned SportModeState error code "
            f"(${UNITREE_ALLOWED_ERROR_CODES_ENV}, comma-separated)"
        ),
    )
    parser.add_argument(
        "--unitree-state-velocity-frame",
        choices=("base_link", "odom"),
        default=None,
    )
    parser.add_argument("--unitree-lateral-sign", type=int, choices=(-1, 1), default=None)
    parser.add_argument("--unitree-yaw-sign", type=int, choices=(-1, 1), default=None)
    parser.add_argument("--unitree-axes-commissioned", action="store_true", default=None)
    parser.add_argument("--unitree-state-frame-commissioned", action="store_true", default=None)
    parser.add_argument(
        "--unitree-sport-state-stamp-monotonic-commissioned",
        action="store_true",
        default=None,
    )
    parser.add_argument(
        "--unitree-battery-soc-percent-commissioned",
        action="store_true",
        default=None,
    )
    parser.add_argument("--unitree-minimum-battery-soc-percent", type=int, default=None)
    parser.add_argument(
        "--unitree-low-state-tick-monotonic-commissioned",
        action="store_true",
        default=None,
    )
    parser.add_argument("--unitree-state-topic", default=None)
    parser.add_argument("--unitree-low-state-topic", default=None)
    parser.add_argument("--unitree-rpc-timeout-s", type=float, default=None)
    parser.add_argument("--unitree-startup-timeout-s", type=float, default=None)
    parser.add_argument(
        "--unitree-subscriber-queue-depth",
        type=int,
        choices=(0,),
        default=None,
        help=(
            "must remain 0 so SDK2 invokes the direct callback "
            f"(${UNITREE_SUBSCRIBER_QUEUE_DEPTH_ENV})"
        ),
    )
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


def _environment_int(
    environ: dict[str, str],
    name: str,
    *,
    default: int | None = None,
) -> int | None:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw, 10)
    except ValueError as exc:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: {name} must be a base-10 integer"
        ) from exc


def _environment_float(
    environ: dict[str, str],
    name: str,
    *,
    default: float,
) -> float:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise GatewayLaunchError(f"{CONSOLE_SCRIPT_NAME}: {name} must be numeric") from exc


def _client_access_from(
    args: argparse.Namespace,
    environ: dict[str, str],
    *,
    sport: str,
) -> tuple[int, int, int, int | None]:
    """Resolve the kernel peer UID and the filesystem group-access contract."""

    numeric_uid = args.client_uid
    if numeric_uid is None:
        numeric_uid = _environment_int(environ, CLIENT_UID_ENV)
    if args.uid is not None:
        if numeric_uid is not None and numeric_uid != args.uid:
            raise GatewayLaunchError(
                f"{CONSOLE_SCRIPT_NAME}: --uid and the configured client uid disagree"
            )
        numeric_uid = args.uid
    numeric_gid = args.client_gid
    if numeric_gid is None:
        numeric_gid = _environment_int(environ, CLIENT_GID_ENV)
    user = args.client_user or environ.get(CLIENT_USER_ENV, "").strip() or None
    group = args.client_group or environ.get(CLIENT_GROUP_ENV, "").strip() or None
    vendor = sport == "vendor"
    try:
        principal = resolve_client_principal(
            uid=numeric_uid,
            gid=numeric_gid,
            user=user,
            group=group,
            require_explicit_uid=vendor,
            require_explicit_gid=vendor,
        )
        mode_raw = environ.get(SOCKET_MODE_ENV, "").strip()
        mode_explicit = args.socket_mode is not None or bool(mode_raw)
        if args.socket_mode is not None:
            socket_mode = args.socket_mode
        elif mode_raw:
            socket_mode = parse_socket_mode(mode_raw)
        else:
            socket_mode = PRIVATE_SOCKET_MODE
        if vendor and not mode_explicit:
            raise ValueError(f"{SOCKET_MODE_ENV} (0660) is required")
        if vendor and socket_mode != SHARED_SOCKET_MODE:
            raise ValueError("vendor socket mode must be exactly 0660")
        if socket_mode == SHARED_SOCKET_MODE and numeric_gid is None and group is None:
            raise ValueError("socket mode 0660 requires an explicit client gid or group")
        socket_gid = principal.gid if socket_mode == SHARED_SOCKET_MODE else None
        validate_socket_access(socket_mode, socket_gid)
    except (argparse.ArgumentTypeError, ValueError) as exc:
        profile = "vendor " if vendor else ""
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: invalid {profile}client/socket access: {exc}"
        ) from exc
    return principal.uid, principal.gid, socket_mode, socket_gid


def _stop_client_uid_from(
    args: argparse.Namespace,
    environ: dict[str, str],
    *,
    sport: str,
    writer_uid: int,
) -> int | None:
    """Resolve the distinct kernel UID which may observe and latch STOP only."""

    numeric_uid = args.stop_client_uid
    if numeric_uid is None:
        numeric_uid = _environment_int(environ, STOP_CLIENT_UID_ENV)
    user = args.stop_client_user or environ.get(STOP_CLIENT_USER_ENV, "").strip() or None
    if numeric_uid is None and user is None:
        if sport == "vendor":
            raise GatewayLaunchError(
                f"{CONSOLE_SCRIPT_NAME}: vendor requires a distinct "
                f"{STOP_CLIENT_UID_ENV} or {STOP_CLIENT_USER_ENV}"
            )
        return None
    try:
        principal = resolve_client_principal(
            uid=numeric_uid,
            gid=None,
            user=user,
            group=None,
            require_explicit_uid=True,
            require_explicit_gid=False,
        )
    except ValueError as exc:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: invalid stop-only client identity: {exc}"
        ) from exc
    if principal.uid == writer_uid:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: stop-only client uid must differ from runtime uid"
        )
    return principal.uid


def _commissioning_ack(
    cli_value: bool | None,
    environ: dict[str, str],
    name: str,
) -> bool | None:
    if cli_value is True:
        return True
    raw = environ.get(name, "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true"}:
        return True
    if raw in {"0", "false"}:
        return False
    raise GatewayLaunchError(f"{CONSOLE_SCRIPT_NAME}: {name} must be one of 1, 0, true, false")


def _unitree_modes(args: argparse.Namespace, environ: dict[str, str]) -> tuple[int, ...] | None:
    if args.unitree_allowed_modes is not None:
        return tuple(args.unitree_allowed_modes)
    raw = environ.get(UNITREE_ALLOWED_MODES_ENV, "").strip()
    if not raw:
        return None
    parts = [part.strip() for part in raw.split(",")]
    if any(not part for part in parts):
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: {UNITREE_ALLOWED_MODES_ENV} must be a "
            "comma-separated list without empty entries"
        )
    try:
        return tuple(int(part, 10) for part in parts)
    except ValueError as exc:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: {UNITREE_ALLOWED_MODES_ENV} entries must be integers"
        ) from exc


def _unitree_error_codes(
    args: argparse.Namespace,
    environ: dict[str, str],
) -> tuple[int, ...] | None:
    if args.unitree_allowed_error_codes is not None:
        return tuple(args.unitree_allowed_error_codes)
    raw = environ.get(UNITREE_ALLOWED_ERROR_CODES_ENV, "").strip()
    if not raw:
        return None
    parts = [part.strip() for part in raw.split(",")]
    if any(not part for part in parts):
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: {UNITREE_ALLOWED_ERROR_CODES_ENV} must be a "
            "comma-separated list without empty entries"
        )
    try:
        return tuple(int(part, 10) for part in parts)
    except ValueError as exc:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: {UNITREE_ALLOWED_ERROR_CODES_ENV} entries must be integers"
        ) from exc


def _unitree_config_from(
    args: argparse.Namespace,
    environ: dict[str, str],
) -> UnitreeSportConfigV1:
    interface = args.unitree_interface
    if interface is None:
        interface = environ.get(UNITREE_INTERFACE_ENV, "").strip() or None
    domain_id = args.unitree_domain_id
    if domain_id is None:
        domain_id = _environment_int(environ, UNITREE_DOMAIN_ID_ENV)
    allowed_modes = _unitree_modes(args, environ)
    allowed_error_codes = _unitree_error_codes(args, environ)
    velocity_frame = args.unitree_state_velocity_frame
    if velocity_frame is None:
        velocity_frame = environ.get(UNITREE_STATE_VELOCITY_FRAME_ENV, "").strip() or None
    lateral_sign = args.unitree_lateral_sign
    if lateral_sign is None:
        lateral_sign = _environment_int(environ, UNITREE_LATERAL_SIGN_ENV)
    yaw_sign = args.unitree_yaw_sign
    if yaw_sign is None:
        yaw_sign = _environment_int(environ, UNITREE_YAW_SIGN_ENV)
    axes_commissioned = _commissioning_ack(
        args.unitree_axes_commissioned, environ, UNITREE_AXES_COMMISSIONED_ENV
    )
    state_frame_commissioned = _commissioning_ack(
        args.unitree_state_frame_commissioned,
        environ,
        UNITREE_STATE_FRAME_COMMISSIONED_ENV,
    )
    sport_state_stamp_monotonic_commissioned = _commissioning_ack(
        args.unitree_sport_state_stamp_monotonic_commissioned,
        environ,
        UNITREE_SPORT_STATE_STAMP_MONOTONIC_COMMISSIONED_ENV,
    )
    battery_soc_percent_commissioned = _commissioning_ack(
        args.unitree_battery_soc_percent_commissioned,
        environ,
        UNITREE_BATTERY_SOC_PERCENT_COMMISSIONED_ENV,
    )
    minimum_battery_soc_percent = args.unitree_minimum_battery_soc_percent
    if minimum_battery_soc_percent is None:
        minimum_battery_soc_percent = _environment_int(
            environ,
            UNITREE_MINIMUM_BATTERY_SOC_PERCENT_ENV,
        )
    low_state_tick_monotonic_commissioned = _commissioning_ack(
        args.unitree_low_state_tick_monotonic_commissioned,
        environ,
        UNITREE_LOW_STATE_TICK_MONOTONIC_COMMISSIONED_ENV,
    )
    required = {
        UNITREE_INTERFACE_ENV: interface,
        UNITREE_DOMAIN_ID_ENV: domain_id,
        UNITREE_ALLOWED_MODES_ENV: allowed_modes,
        UNITREE_ALLOWED_ERROR_CODES_ENV: allowed_error_codes,
        UNITREE_STATE_VELOCITY_FRAME_ENV: velocity_frame,
        UNITREE_LATERAL_SIGN_ENV: lateral_sign,
        UNITREE_YAW_SIGN_ENV: yaw_sign,
        UNITREE_AXES_COMMISSIONED_ENV: axes_commissioned is True,
        UNITREE_STATE_FRAME_COMMISSIONED_ENV: state_frame_commissioned is True,
        UNITREE_SPORT_STATE_STAMP_MONOTONIC_COMMISSIONED_ENV: (
            sport_state_stamp_monotonic_commissioned is True
        ),
        UNITREE_BATTERY_SOC_PERCENT_COMMISSIONED_ENV: (battery_soc_percent_commissioned is True),
        UNITREE_MINIMUM_BATTERY_SOC_PERCENT_ENV: minimum_battery_soc_percent,
        UNITREE_LOW_STATE_TICK_MONOTONIC_COMMISSIONED_ENV: (
            low_state_tick_monotonic_commissioned is True
        ),
    }
    missing = [name for name, value in required.items() if value is None or value is False]
    if missing:
        # Preserve the old refusal's searchable phrase for the shipped unit,
        # but make the condition precise: a fully explicit profile proceeds.
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: vendor is not implemented by an implicit launch "
            "profile; explicit Unitree commissioning configuration is required; "
            f"missing or false: {', '.join(missing)}"
        )
    state_topic = (
        args.unitree_state_topic
        or environ.get(UNITREE_STATE_TOPIC_ENV, "").strip()
        or "rt/sportmodestate"
    )
    low_state_topic = (
        args.unitree_low_state_topic
        or environ.get(UNITREE_LOW_STATE_TOPIC_ENV, "").strip()
        or "rt/lowstate"
    )
    rpc_timeout_s = (
        args.unitree_rpc_timeout_s
        if args.unitree_rpc_timeout_s is not None
        else _environment_float(environ, UNITREE_RPC_TIMEOUT_ENV, default=0.2)
    )
    startup_timeout_s = (
        args.unitree_startup_timeout_s
        if args.unitree_startup_timeout_s is not None
        else _environment_float(environ, UNITREE_STARTUP_TIMEOUT_ENV, default=2.0)
    )
    queue_depth = args.unitree_subscriber_queue_depth
    if queue_depth is None:
        queue_depth = _environment_int(environ, UNITREE_SUBSCRIBER_QUEUE_DEPTH_ENV, default=0)
    if queue_depth != 0:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: {UNITREE_SUBSCRIBER_QUEUE_DEPTH_ENV} must be exactly 0"
        )
    try:
        return UnitreeSportConfigV1(
            interface=interface,
            domain_id=domain_id,
            allowed_modes=allowed_modes,
            allowed_error_codes=allowed_error_codes,
            state_velocity_frame=velocity_frame,
            lateral_sign=lateral_sign,
            yaw_sign=yaw_sign,
            axes_commissioned=axes_commissioned,
            state_frame_commissioned=state_frame_commissioned,
            sport_state_stamp_monotonic_commissioned=(sport_state_stamp_monotonic_commissioned),
            battery_soc_percent_commissioned=battery_soc_percent_commissioned,
            minimum_battery_soc_percent=minimum_battery_soc_percent,
            low_state_tick_monotonic_commissioned=(low_state_tick_monotonic_commissioned),
            state_topic=state_topic,
            low_state_topic=low_state_topic,
            rpc_timeout_s=rpc_timeout_s,
            startup_timeout_s=startup_timeout_s,
            subscriber_queue_depth=queue_depth,
        )
    except (TypeError, ValueError) as exc:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: invalid Unitree vendor configuration: {exc}"
        ) from exc


def _required_hashes_from(
    args: argparse.Namespace,
    environ: dict[str, str],
    *,
    sport: str,
) -> GatewayHashesV1:
    if sport == "fake":
        return BENCH_HASHES
    sources = (
        ("config_sha256", "config_sha256", CONFIG_SHA256_ENV),
        ("capability_sha256", "capability_sha256", CAPABILITY_SHA256_ENV),
        ("calibration_sha256", "calibration_sha256", CALIBRATION_SHA256_ENV),
        ("firmware_sha256", "firmware_sha256", FIRMWARE_SHA256_ENV),
    )
    values = {}
    missing = []
    for field, argument, environment_name in sources:
        value = getattr(args, argument) or environ.get(environment_name, "").strip()
        if not value:
            missing.append(environment_name)
        values[field] = value
    if missing:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: vendor requires explicit launch compatibility hashes; "
            f"missing {', '.join(missing)}"
        )
    try:
        hashes = GatewayHashesV1(**values)
    except (TypeError, ValueError) as exc:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: invalid launch compatibility hash: {exc}"
        ) from exc
    if hashes == BENCH_HASHES:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: vendor refuses the fixed BENCH_HASHES identity"
        )
    return hashes


def settings_from(
    args: argparse.Namespace,
    environ: dict[str, str],
) -> LaunchSettingsV1:
    """Resolve the launch profile, refusing anything ambiguous or armed."""

    if not bool(args.disarmed):
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: --disarmed is a required boot assertion; "
            "refusing to construct vendor or fake I/O without it"
        )
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
    client_uid, client_gid, socket_mode, socket_gid = _client_access_from(
        args,
        environ,
        sport=sport,
    )
    stop_client_uid = _stop_client_uid_from(
        args,
        environ,
        sport=sport,
        writer_uid=client_uid,
    )
    unitree_config = _unitree_config_from(args, environ) if sport == "vendor" else None
    required_hashes = _required_hashes_from(args, environ, sport=sport)
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
        client_uid=client_uid,
        client_gid=client_gid,
        stop_client_uid=stop_client_uid,
        socket_mode=socket_mode,
        socket_gid=socket_gid,
        ready_timeout_s=float(args.ready_timeout_s),
        disarmed_asserted=bool(args.disarmed),
        required_hashes=required_hashes,
        unitree_config=unitree_config,
    )


def _build_sport(
    settings: LaunchSettingsV1,
    *,
    writer_authority: UnitreeWriterLockV1 | None = None,
) -> object:
    """Construct exactly the named body; SDK2 remains lazy on the fake path."""

    if settings.sport == "fake":
        from parcel_robot.bridge.fake_sport import FakeSportServiceV1

        return FakeSportServiceV1()
    if settings.sport != "vendor" or settings.unitree_config is None:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: refusing to build a {settings.sport!r} body "
            "without resolved physical configuration"
        )
    if settings.required_hashes == BENCH_HASHES:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: vendor refuses the fixed BENCH_HASHES identity"
        )
    try:
        return UnitreeSdk2SportPortV1(
            settings.unitree_config,
            _writer_authority=writer_authority,
        )
    except (TypeError, ValueError, UnitreeSportError) as exc:
        raise GatewayLaunchError(
            f"{CONSOLE_SCRIPT_NAME}: Unitree vendor startup refused: {exc}"
        ) from exc


def _policy_from_settings(settings: LaunchSettingsV1):
    """Bind the local writer to this launch's real compatibility identity."""

    if settings.stop_client_uid is not None:
        return writer_with_stop_only_policy(
            required_hashes=settings.required_hashes,
            writer_id=settings.writer_id,
            writer_uid=settings.client_uid,
            stop_uid=settings.stop_client_uid,
        )
    return single_writer_policy(
        required_hashes=settings.required_hashes,
        writer_id=settings.writer_id,
        uid=settings.client_uid,
    )


def _socket_is_listening(
    path: Path,
    expected_mode: int = PRIVATE_SOCKET_MODE,
    expected_gid: int | None = None,
) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return (
        stat.S_ISSOCK(metadata.st_mode)
        and (metadata.st_mode & 0o777) == expected_mode
        and (expected_gid is None or metadata.st_gid == expected_gid)
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = settings_from(args, dict(os.environ))

    writer_lock = UnitreeWriterLockV1(required=settings.sport == "vendor")
    try:
        writer_lock.acquire()
    except (OSError, RuntimeError) as exc:
        raise SystemExit(
            f"{CONSOLE_SCRIPT_NAME}: {settings.sport} writer authority unavailable: {exc}"
        ) from None
    try:
        return _run_with_writer_authority(settings, writer_lock=writer_lock)
    finally:
        writer_lock.close()


def _run_with_writer_authority(
    settings: LaunchSettingsV1,
    *,
    writer_lock: UnitreeWriterLockV1,
) -> int:
    """Construct and serve the body only while the fixed writer lock is held."""

    ring = BoundedAuditRingV1()
    limits = GovernorLimitsV1(regime=regime(settings.regime_name))
    policy = _policy_from_settings(settings)
    sport = _build_sport(settings, writer_authority=writer_lock)
    core = construct_core_or_close_sport(
        sport,
        policy=policy,
        limits=limits,
        audit=ring,
        body_kind=(
            GatewayBodyKindV1.UNITREE_SDK2 if settings.sport == "vendor" else GatewayBodyKindV1.FAKE
        ),
    )
    exporter = AuditExporterV1(ring, settings.audit_log)
    stop_event = threading.Event()
    server_opened = threading.Event()
    liveness: GatewayLivenessNotifierV1 | None = None

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    try:
        supervision = read_supervision()
        notifier = SdNotifierV1(supervision.notify_address)
        liveness = GatewayLivenessNotifierV1(
            notifier,
            # A real probe: both properties take the core ``RLock``, and neither
            # changes anything. A core that cannot answer is a core that is wedged.
            lambda: (core.stop_sequence, core.latched),
            watchdog_period_s=supervision.watchdog_period_s,
            probe_timeout_s=limits.stop_timeout_s * PROBE_BUDGET_FACTOR,
        )
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
            args=(liveness, settings, core.boot_epoch, stop_event, server_opened),
            name="parcel-gateway-readiness",
            daemon=True,
        )
        announcer.start()
        GatewayServerV1(
            settings.socket_path,
            core,
            socket_mode=settings.socket_mode,
            socket_gid=settings.socket_gid,
        ).serve(stop_event, opened_event=server_opened)
    finally:
        stop_event.set()
        ancillary: list[Callable[[], None]] = [exporter.stop]
        if liveness is not None:
            ancillary.insert(
                0,
                lambda: liveness.stop(status="gateway stopped; final stop attempted"),
            )
        _close_core_then_cleanup(core, tuple(ancillary))
    return 0 if ring.dropped_records == 0 and exporter.write_errors == 0 else 2


def _announce_when_ready(
    liveness: GatewayLivenessNotifierV1,
    settings: LaunchSettingsV1,
    boot_epoch: str,
    stop_event: threading.Event,
    server_opened: threading.Event,
) -> None:
    """READY=1 once the socket is really listening and the core really answers."""

    deadline = time.monotonic() + settings.ready_timeout_s
    while time.monotonic() < deadline and not stop_event.is_set():
        # Path metadata alone is not ownership evidence: a stale listener from
        # an earlier process can exist before this process reaches bind(). The
        # serving thread sets this only after its own listener is live.
        if not server_opened.is_set():
            server_opened.wait(timeout=0.01)
            continue
        if _socket_is_listening(
            settings.socket_path,
            settings.socket_mode,
            settings.socket_gid,
        ) and liveness.announce_ready(
            status=f"disarmed; boot_epoch={boot_epoch}; sport={settings.sport}"
        ):
            liveness.start()
            return
        time.sleep(0.01)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
