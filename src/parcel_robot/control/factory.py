from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from parcel_robot.bridge.protocol import GatewayHashesV1
from parcel_robot.bridge.unitree_writer_lock import UnitreeWriterLockV1
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.safety import SafetyLimits

from .adapters import BackendVelocityController
from .base import CommissionedStateSource
from .manager import ControlManager
from .models import ControlLimits, ControlTiming
from .state import BufferedRobotStateSource

# A controller factory builds a fully configured ControlManager for one vendor.
# Registering through this table is the only supported way to add a robot:
# generic code never imports a vendor module, and a new vendor is one new file
# plus one registration call — never an edit to this package.
ControllerFactory = Callable[[dict[str, Any], SafetyLimits], ControlManager]

_CONTROLLER_FACTORIES: dict[str, ControllerFactory] = {}


def register_controller_factory(
    name: str,
    factory: ControllerFactory,
    *,
    replace: bool = False,
) -> None:
    """Register a vendor locomotion factory under a stable name."""

    key = name.strip().lower()
    if not key:
        raise ValueError("controller factory name cannot be empty")
    if not replace and key in _CONTROLLER_FACTORIES:
        raise ValueError(f"controller factory already registered: {key}")
    _CONTROLLER_FACTORIES[key] = factory


def controller_factory_names() -> tuple[str, ...]:
    return tuple(sorted(_CONTROLLER_FACTORIES))


def create_control_manager(
    name: str,
    config: dict[str, Any],
    safety_limits: SafetyLimits,
) -> ControlManager:
    """Build the named vendor's ControlManager through the registry."""

    key = name.strip().lower()
    try:
        factory = _CONTROLLER_FACTORIES[key]
    except KeyError as error:
        raise KeyError(
            f"unknown locomotion controller {name!r}; "
            f"registered: {', '.join(controller_factory_names()) or '(none)'}"
        ) from error
    return factory(config, safety_limits)


def build_backend_control_manager(
    backend: Any,
    config: dict[str, Any],
    safety_limits: SafetyLimits,
) -> tuple[ControlManager, BufferedRobotStateSource]:
    """Vendor-neutral simulator/backends path used by the normal runtime."""

    timing = _timing(config)
    source = BufferedRobotStateSource()
    controller = BackendVelocityController(
        backend,
        refresh_s=float(config.get("command_refresh_s", 0.2)),
    )
    manager = ControlManager(
        controller,
        source,
        limits=_limits(config, safety_limits),
        timing=timing,
    )
    return manager, source


def build_unitree_sport_control_manager(
    config: dict[str, Any],
    safety_limits: SafetyLimits,
) -> ControlManager:
    """Refuse the retired in-process physical writer composition.

    Autonomous Unitree motion has one supported path: the separately
    supervised gateway plus ``motion_gateway_commissioned``. Keeping this
    symbol as a hard refusal gives old configurations and imports a clear
    migration error without leaving a callable SDK bypass.
    """

    del config, safety_limits
    raise RuntimeError(
        "direct unitree_sport control is retired; use motion_gateway_commissioned "
        "through the parcel-gateway sole-writer process"
    )


def build_motion_gateway_disarmed_control_manager(
    config: dict[str, Any],
    safety_limits: SafetyLimits,
) -> ControlManager:
    """Build the product Unix-gateway composition without motion authority.

    This is intentionally suitable only for the first desktop/bench rung.  The
    nested section must say ``mode: disarmed`` exactly, unknown keys fail
    closed, and the resulting controller cannot acquire or command the
    gateway.  ``RobotRuntime`` still requires this manager to be passed through
    its explicit ``control_manager=`` injection seam; configuration alone can
    never select a robot-facing controller.
    """

    from .motion_gateway import build_disarmed_gateway_pair

    gateway = config.get("motion_gateway")
    if not isinstance(gateway, dict):
        raise TypeError("control.motion_gateway must be a mapping")
    allowed = {"mode", "socket_path", "writer_id", "timeout_s"}
    unknown = sorted(set(gateway) - allowed)
    if unknown:
        raise ValueError(f"unknown control.motion_gateway keys: {', '.join(unknown)}")
    if gateway.get("mode") != "disarmed":
        raise ValueError("control.motion_gateway.mode must be exactly 'disarmed'")
    socket_path = gateway.get("socket_path")
    if not isinstance(socket_path, str) or not socket_path.strip():
        raise ValueError("control.motion_gateway.socket_path must be a non-empty string")
    writer_id = gateway.get("writer_id", "parcel-runtime")
    if not isinstance(writer_id, str):
        raise TypeError("control.motion_gateway.writer_id must be a string")
    raw_timeout_s = gateway.get("timeout_s", 2.0)
    if isinstance(raw_timeout_s, bool) or not isinstance(raw_timeout_s, (int, float)):
        raise TypeError("control.motion_gateway.timeout_s must be numeric")
    timeout_s = float(raw_timeout_s)
    timing = _timing(config)
    if timeout_s > timing.io_quiesce_timeout_s:
        raise ValueError(
            "control.motion_gateway.timeout_s cannot exceed control.io_quiesce_timeout_s"
        )
    controller, state_source = build_disarmed_gateway_pair(
        socket_path.strip(),
        writer_id=writer_id,
        timeout_s=timeout_s,
        state_timeout_s=timing.state_timeout_s,
    )
    return ControlManager(
        controller,
        state_source,
        limits=_limits(config, safety_limits),
        timing=timing,
    )


register_controller_factory(
    "motion_gateway_disarmed",
    build_motion_gateway_disarmed_control_manager,
)


@dataclass(frozen=True, slots=True)
class _CommissionedGatewaySettings:
    socket_path: str
    writer_id: str
    commissioning_record_id: str
    expected_hashes: GatewayHashesV1
    timeout_s: float
    local_ttl_ms: int
    timing: ControlTiming


def _commissioned_gateway_settings(config: dict[str, Any]) -> _CommissionedGatewaySettings:
    gateway = config.get("motion_gateway")
    if not isinstance(gateway, dict):
        raise TypeError("control.motion_gateway must be a mapping")
    allowed = {
        "mode",
        "socket_path",
        "writer_id",
        "timeout_s",
        "local_ttl_ms",
        "session_epoch",
        "expected_hashes",
    }
    unknown = sorted(set(gateway) - allowed)
    if unknown:
        raise ValueError(f"unknown control.motion_gateway keys: {', '.join(unknown)}")
    if gateway.get("mode") != "commissioned":
        raise ValueError("control.motion_gateway.mode must be exactly 'commissioned'")
    socket_path = gateway.get("socket_path")
    if not isinstance(socket_path, str) or not socket_path.strip():
        raise ValueError("control.motion_gateway.socket_path must be a non-empty string")
    writer_id = gateway.get("writer_id", "parcel-runtime")
    if not isinstance(writer_id, str):
        raise TypeError("control.motion_gateway.writer_id must be a string")
    record_id = gateway.get("session_epoch")
    if not isinstance(record_id, str) or not record_id.strip():
        raise ValueError(
            "control.motion_gateway.session_epoch must be an explicit non-empty "
            "commissioning record ID"
        )
    record_id = record_id.strip()
    if len(record_id) > 80:
        raise ValueError("control.motion_gateway.session_epoch cannot exceed 80 characters")
    expected_hashes = _commissioned_gateway_hashes(gateway.get("expected_hashes"))
    raw_timeout_s = gateway.get("timeout_s", 2.0)
    if isinstance(raw_timeout_s, bool) or not isinstance(raw_timeout_s, (int, float)):
        raise TypeError("control.motion_gateway.timeout_s must be numeric")
    raw_local_ttl_ms = gateway.get("local_ttl_ms", 350)
    if isinstance(raw_local_ttl_ms, bool) or not isinstance(raw_local_ttl_ms, int):
        raise TypeError("control.motion_gateway.local_ttl_ms must be an integer")
    timing = _timing(config)
    timeout_s = float(raw_timeout_s)
    if timeout_s > timing.io_quiesce_timeout_s:
        raise ValueError(
            "control.motion_gateway.timeout_s cannot exceed control.io_quiesce_timeout_s"
        )
    return _CommissionedGatewaySettings(
        socket_path.strip(),
        writer_id,
        record_id,
        expected_hashes,
        timeout_s,
        raw_local_ttl_ms,
        timing,
    )


def _commissioned_gateway_hashes(value: object) -> GatewayHashesV1:
    if not isinstance(value, dict):
        raise TypeError("control.motion_gateway.expected_hashes must be a mapping")
    fields = {
        "config_sha256",
        "capability_sha256",
        "calibration_sha256",
        "firmware_sha256",
    }
    if set(value) != fields:
        raise ValueError(
            "control.motion_gateway.expected_hashes must contain exactly "
            + ", ".join(sorted(fields))
        )
    expected_hashes = GatewayHashesV1(**{name: value[name] for name in fields})
    bench_hashes = GatewayHashesV1(
        config_sha256="a" * 64,
        capability_sha256="b" * 64,
        calibration_sha256="c" * 64,
        firmware_sha256="d" * 64,
    )
    if expected_hashes == bench_hashes:
        raise ValueError(
            "control.motion_gateway.expected_hashes refuses the fixed BENCH_HASHES identity"
        )
    return expected_hashes


def build_motion_gateway_commissioned_control_manager(
    config: dict[str, Any],
    safety_limits: SafetyLimits,
) -> ControlManager:
    """Build the explicit-arm, commissioned Unix-gateway composition.

    Registration gives an operator a deliberate construction seam; it does not
    alter the normal runtime's simulator selection or inject this manager into
    ``RobotRuntime``.  Physical provenance requires both an explicit nonempty
    commissioning record ID and independently configured compatibility hashes.
    A distinct producer-session epoch is minted for every manager construction.
    Connecting and starting remain passive; authority exists only after the
    returned controller's explicit ``arm()`` transaction succeeds.
    """

    from .motion_gateway import build_commissioned_gateway_pair

    settings = _commissioned_gateway_settings(config)
    producer_session_epoch = f"motion-gateway-{uuid4().hex}"
    controller, raw_state_source = build_commissioned_gateway_pair(
        settings.socket_path,
        writer_id=settings.writer_id,
        session_epoch=producer_session_epoch,
        expected_hashes=settings.expected_hashes,
        commissioning_record_id=settings.commissioning_record_id,
        timeout_s=settings.timeout_s,
        state_timeout_s=settings.timing.state_timeout_s,
        local_ttl_ms=settings.local_ttl_ms,
    )
    state_source = CommissionedStateSource(
        raw_state_source,
        origin=EvidenceOrigin.PHYSICAL,
        session_epoch=producer_session_epoch,
    )
    return ControlManager(
        controller,
        state_source,
        limits=_limits(config, safety_limits),
        timing=settings.timing,
    )


register_controller_factory(
    "motion_gateway_commissioned",
    build_motion_gateway_commissioned_control_manager,
)


# ---------------------------------------------------------------------------
# Commissioning-only path (card W0-B).
#
# The retired in-process runtime builder above always refuses. The two builders
# below are the supervised *measurement* path and are deliberately NOT
# registered in the controller registry, so ``create_control_manager`` cannot
# return one and no runtime configuration string can reach them. The armed
# builder produces a commissioning object, never a bare ``ControlManager``;
# real SDK activation additionally requires the same fixed writer authority as
# the gateway.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitreeCommissioningSeams:
    """Bounded vendor injection points, defaulting to the real transport.

    These are the seams the vendor classes already expose
    (``UnitreeChannelContext(initializer=...)``,
    ``UnitreeSportController(client_factory=...)``,
    ``UnitreeSportStateSource(subscriber_factory=..., message_type=...)``).
    Passing ``None`` — the default — means the real Unitree SDK, so a test that
    forgets to inject cannot silently reach hardware; it fails on the missing
    NIC or the missing SDK import, as it does today.
    """

    channel_initializer: Callable[[int, str], Any] | None = None
    client_factory: Callable[..., Any] | None = None
    subscriber_factory: Callable[[str, Any], Any] | None = None
    message_type: Any = None


def build_unitree_sport_observer(
    config: dict[str, Any],
    *,
    seams: UnitreeCommissioningSeams | None = None,
) -> Any:
    """Read-only commissioning observer: a state source and no controller.

    This is the first commissioning phase. It claims no lease, constructs no
    controller, and has no method that writes to the robot — so the modes,
    rates, and resting feedback can be established before anything is armed.
    Returns a ``parcel_robot.commissioning.CommissioningObserver``.
    """

    from parcel_robot.commissioning.session import CommissioningObserver

    sport = _sport_section(config)
    seams = seams or UnitreeCommissioningSeams()
    channel = _commissioning_channel(sport, seams)
    state_source = _commissioning_state_source(sport, channel, seams)
    return CommissioningObserver(
        state_source,
        declared_velocity_frame=str(sport.get("state_velocity_frame", "odom")),
    )


def build_unitree_sport_commissioning_session(
    config: dict[str, Any],
    safety_limits: SafetyLimits,
    *,
    arming: Any,
    journal_path: Path | str,
    session_id: str | None = None,
    seams: UnitreeCommissioningSeams | None = None,
    writer_authority: UnitreeWriterLockV1 | None = None,
) -> Any:
    """Build the armed, one-axis commissioning session (card W0-B).

    Unlike :func:`build_unitree_sport_control_manager` this does **not** require
    ``axes_commissioned`` / ``state_frame_commissioned`` / ``allowed_modes`` in
    configuration — it is what produces them. In their place it requires an
    explicit :class:`~parcel_robot.commissioning.CommissioningArming` token
    carrying an operator, a robot serial, every safety acknowledgement, and the
    modes the read-only observation phase actually saw.

    Three deliberate overrides of configuration:

    * **Axis signs are forced to identity.** A configured ``lateral_sign`` /
      ``yaw_sign`` is an uncommissioned claim; applying it to the numbers being
      written down would make the record self-confirming.
    * **Allowed modes come from the arming token**, never from configuration,
      so a commissioning step can only run in a mode a human just observed.
    * **Limits and timing are clamped, never relaxed**: the speed caps drop to
      the commissioning band, the command TTL to at most the production TTL, and
      the settled-speed thresholds below the whole band — ``configs/robot.yaml``
      calls 0.08 m/s "settled", which is above every speed this path can
      command, so an unclamped stop confirmation would be satisfied by a robot
      that never stopped.

    Returns a ``parcel_robot.commissioning.CommissioningSession``: not a
    ``ControlManager``, not registered anywhere, and not something the
    autonomous runtime can consume.
    """

    from parcel_robot.commissioning.limits import (
        CommissioningArming,
        CommissioningRefusedError,
        RefusalReason,
    )
    from parcel_robot.commissioning.session import CommissioningJournal, CommissioningSession

    from .unitree_sport import UnitreeSportController

    if not isinstance(arming, CommissioningArming):
        raise CommissioningRefusedError(
            RefusalReason.NOT_ARMED,
            "commissioning requires an explicit CommissioningArming token",
        )
    if not arming.observed_modes:
        raise CommissioningRefusedError(
            RefusalReason.MODES_NOT_OBSERVED,
            "arm with the modes the read-only observation phase saw",
        )
    arming.assert_valid(time.monotonic())

    sport = _sport_section(config)
    seams = seams or UnitreeCommissioningSeams()
    # Narrow the token's band to this manager's LIVE timing so the derivations
    # hold on the real configuration: a step never outlasts the stop budget, and
    # a command lease never outlasts the configured command timeout. Narrowing
    # only; `CommissioningLimits` refuses any widening.
    base_timing = _timing(config)
    band = dataclasses.replace(
        arming.limits,
        max_duration_s=min(arming.limits.max_duration_s, float(base_timing.stop_timeout_s)),
        max_ttl_s=min(arming.limits.max_ttl_s, float(base_timing.command_timeout_s)),
    )
    timing = _commissioning_timing(config, band)
    # The journal opens FIRST, before any vendor object exists. A journal that
    # was already used - or that a previous process abandoned mid-session -
    # refuses or latches here, while nothing has been constructed to stop.
    journal = CommissioningJournal.begin(
        journal_path,
        session_id=session_id or f"{arming.robot_serial}-{int(arming.armed_at)}",
    )
    channel = _commissioning_channel(sport, seams)
    state_source = _commissioning_state_source(sport, channel, seams)

    rpc_timeout_s = float(sport.get("rpc_timeout_s", 0.2))
    if rpc_timeout_s > min(timing.stop_retry_s, timing.stop_timeout_s):
        raise ValueError("Unitree rpc_timeout_s cannot exceed the stop retry/confirmation deadline")
    lease_acquire_timeout_s = float(sport.get("lease_acquire_timeout_s", 2.0))
    if lease_acquire_timeout_s > timing.io_quiesce_timeout_s:
        raise ValueError(
            "Unitree lease_acquire_timeout_s cannot exceed control.io_quiesce_timeout_s"
        )
    controller = UnitreeSportController(
        channel,
        rpc_timeout_s=rpc_timeout_s,
        refresh_s=float(sport.get("command_refresh_s", 0.1)),
        # The Sport lease makes this process the sole writer for the duration of
        # the session; commissioning is precisely when that must be true.
        enable_lease=True,
        lease_acquire_timeout_s=lease_acquire_timeout_s,
        lateral_sign=1,
        yaw_sign=1,
        allowed_modes=tuple(arming.observed_modes),
        client_factory=seams.client_factory,
        writer_authority=writer_authority,
    )
    manager = ControlManager(
        controller,
        state_source,
        limits=_commissioning_limits(config, safety_limits, band),
        timing=timing,
    )
    return CommissioningSession(
        manager,
        arming=arming,
        journal=journal,
        declared_velocity_frame=str(sport.get("state_velocity_frame", "odom")),
        limits=band,
    )


def _sport_section(config: dict[str, Any]) -> dict[str, Any]:
    sport = config.get("unitree_sport") or {}
    if not isinstance(sport, dict):
        raise TypeError("control.unitree_sport must be a mapping")
    return sport


def _commissioning_channel(sport: dict[str, Any], seams: UnitreeCommissioningSeams) -> Any:
    from .unitree_sport import UnitreeChannelContext

    return UnitreeChannelContext(
        int(sport.get("domain_id", 0)),
        str(sport.get("interface", "enp3s0")),
        initializer=seams.channel_initializer,
    )


def _commissioning_state_source(
    sport: dict[str, Any],
    channel: Any,
    seams: UnitreeCommissioningSeams,
) -> Any:
    from .unitree_sport import UnitreeSportStateSource

    return UnitreeSportStateSource(
        channel,
        topic=str(sport.get("state_topic", "rt/sportmodestate")),
        subscriber_factory=seams.subscriber_factory,
        message_type=seams.message_type,
        velocity_frame=str(sport.get("state_velocity_frame", "odom")),
        # Identity: an uncommissioned sign must not be applied to the feedback a
        # commissioning record is about to quote.
        lateral_sign=1,
        yaw_sign=1,
    )


def _commissioning_timing(config: dict[str, Any], band: Any) -> ControlTiming:
    base = _timing(config)
    return ControlTiming(
        control_hz=base.control_hz,
        command_timeout_s=min(base.command_timeout_s, band.max_ttl_s),
        state_timeout_s=base.state_timeout_s,
        startup_timeout_s=base.startup_timeout_s,
        stop_timeout_s=base.stop_timeout_s,
        stop_retry_s=base.stop_retry_s,
        io_quiesce_timeout_s=base.io_quiesce_timeout_s,
        stop_settled_samples=base.stop_settled_samples,
        settled_linear_speed_mps=min(base.settled_linear_speed_mps, band.settled_linear_mps),
        settled_yaw_speed_rad_s=min(base.settled_yaw_speed_rad_s, band.settled_yaw_rad_s),
    )


def _commissioning_limits(
    config: dict[str, Any],
    safety_limits: SafetyLimits,
    band: Any,
) -> ControlLimits:
    base = _limits(config, safety_limits)
    return ControlLimits(
        max_vx=min(base.max_vx, band.max_linear_mps),
        max_vy=min(base.max_vy, band.max_linear_mps),
        max_vyaw=min(base.max_vyaw, band.max_yaw_rad_s),
        max_tilt_rad=base.max_tilt_rad,
    )


def _timing(config: dict[str, Any]) -> ControlTiming:
    stop_settled_samples = config.get("stop_settled_samples", 2)
    if isinstance(stop_settled_samples, bool) or not isinstance(stop_settled_samples, int):
        raise TypeError("control.stop_settled_samples must be an integer")
    return ControlTiming(
        control_hz=float(config.get("control_hz", 50.0)),
        command_timeout_s=float(config.get("command_timeout_s", 0.35)),
        state_timeout_s=float(config.get("state_timeout_s", 0.25)),
        startup_timeout_s=float(config.get("startup_timeout_s", 2.0)),
        stop_timeout_s=float(config.get("stop_timeout_s", 1.0)),
        stop_retry_s=float(config.get("stop_retry_s", 0.2)),
        io_quiesce_timeout_s=float(config.get("io_quiesce_timeout_s", 2.5)),
        stop_settled_samples=stop_settled_samples,
        settled_linear_speed_mps=float(config.get("settled_linear_speed_mps", 0.08)),
        settled_yaw_speed_rad_s=float(config.get("settled_yaw_speed_rad_s", 0.12)),
    )


def _limits(config: dict[str, Any], fallback: SafetyLimits) -> ControlLimits:
    return ControlLimits(
        max_vx=float(config.get("max_vx", fallback.max_vx)),
        max_vy=float(config.get("max_vy", fallback.max_vy)),
        max_vyaw=float(config.get("max_vyaw", fallback.max_vyaw)),
        max_tilt_rad=float(config.get("max_tilt_rad", 0.75)),
    )
