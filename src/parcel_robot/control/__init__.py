"""Vendor-neutral locomotion control.

This package intentionally contains no vendor imports at module scope.
Vendor adapters (Unitree Sport, future robots) live in their own modules and
are reached exclusively through the controller registry in ``factory``.
"""

from .adapters import BackendVelocityController
from .base import LocomotionController, RobotStateSource
from .factory import (
    build_backend_control_manager,
    build_unitree_sport_control_manager,
    controller_factory_names,
    create_control_manager,
    register_controller_factory,
)
from .manager import ControlManager, ControlNotReadyError
from .models import (
    ControllerCapabilities,
    ControllerStatus,
    ControlLifecycle,
    ControlLimits,
    ControlTiming,
    FaultReason,
    RobotMotionState,
    TimedVelocitySetpoint,
)
from .state import BufferedRobotStateSource

__all__ = [
    "BackendVelocityController",
    "BufferedRobotStateSource",
    "ControlLifecycle",
    "ControlLimits",
    "ControlManager",
    "ControlNotReadyError",
    "ControlTiming",
    "ControllerCapabilities",
    "ControllerStatus",
    "FaultReason",
    "LocomotionController",
    "RobotMotionState",
    "RobotStateSource",
    "TimedVelocitySetpoint",
    "build_backend_control_manager",
    "build_unitree_sport_control_manager",
    "controller_factory_names",
    "create_control_manager",
    "register_controller_factory",
]
