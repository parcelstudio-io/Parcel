from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parcel_robot.safety import SafetyLimits

from .adapters import BackendVelocityController
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
    """Build a hardware manager without importing Unitree SDK until start().

    The Unitree module is imported lazily inside this function so that
    ``import parcel_robot.control`` never references vendor code.
    """

    from .unitree_sport import (
        UnitreeChannelContext,
        UnitreeSportController,
        UnitreeSportStateSource,
    )

    timing = _timing(config)
    sport = config.get("unitree_sport") or {}
    if not isinstance(sport, dict):
        raise TypeError("control.unitree_sport must be a mapping")
    domain_id = int(sport.get("domain_id", 0))
    interface = str(sport.get("interface", "enp3s0"))
    channel = UnitreeChannelContext(domain_id, interface)
    lateral_sign = int(sport.get("lateral_sign", 1))
    yaw_sign = int(sport.get("yaw_sign", 1))
    if sport.get("enable_lease") is not True:
        raise ValueError("control.unitree_sport.enable_lease must be true for physical control")
    if sport.get("axes_commissioned") is not True:
        raise ValueError(
            "control.unitree_sport.axes_commissioned must be true after sign verification"
        )
    if sport.get("state_frame_commissioned") is not True:
        raise ValueError(
            "control.unitree_sport.state_frame_commissioned must be true after frame verification"
        )
    state_source = UnitreeSportStateSource(
        channel,
        topic=str(sport.get("state_topic", "rt/sportmodestate")),
        velocity_frame=str(sport.get("state_velocity_frame", "odom")),
        lateral_sign=lateral_sign,
        yaw_sign=yaw_sign,
    )
    raw_allowed_modes = sport.get("allowed_modes", [])
    if not isinstance(raw_allowed_modes, list):
        raise TypeError("control.unitree_sport.allowed_modes must be a list")
    if not raw_allowed_modes:
        raise ValueError("control.unitree_sport.allowed_modes must be explicitly commissioned")
    if any(isinstance(mode, bool) or not isinstance(mode, int) for mode in raw_allowed_modes):
        raise TypeError("control.unitree_sport.allowed_modes must contain integers")
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
        enable_lease=True,
        lease_acquire_timeout_s=lease_acquire_timeout_s,
        lateral_sign=lateral_sign,
        yaw_sign=yaw_sign,
        allowed_modes=tuple(raw_allowed_modes),
    )
    return ControlManager(
        controller,
        state_source,
        limits=_limits(config, safety_limits),
        timing=timing,
    )


register_controller_factory("unitree_sport", build_unitree_sport_control_manager)


# ---------------------------------------------------------------------------
# Commissioning-only path (card W0-B).
#
# The four gates above — enable_lease, axes_commissioned, state_frame_
# commissioned, allowed_modes — are exactly the facts a commissioning run
# exists to establish, so the normal builder cannot bootstrap them: it demands
# the conclusion as a precondition. The two builders below are the *measurement*
# path and they are deliberately NOT registered in the controller registry, so
# ``create_control_manager`` can never return one and no configuration string
# can reach them. They return commissioning objects, never a bare
# ``ControlManager``, so there is nothing here for ``RobotRuntime`` to accept.
#
# Nothing above this line changes. The normal gates keep refusing exactly what
# they refused before; ``tests/test_w0b_commissioning.py`` pins all four.
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

    from parcel_robot.commissioning import CommissioningObserver

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

    from parcel_robot.commissioning import (
        CommissioningArming,
        CommissioningJournal,
        CommissioningRefusedError,
        CommissioningSession,
        RefusalReason,
    )

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
