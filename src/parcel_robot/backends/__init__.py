from .base import (
    DynamicAgentTrack,
    LidarObstacle,
    OwnerTrack,
    RobotPose,
    SemanticObjectTrack,
    SemanticRegionTrack,
    SimObservation,
    SimulatorBackend,
)

# ---- CARD HW-2 go2-backend (scrum/20260822/task_40) ------------------------
# The physical `SimulatorBackend`. Importing it here costs a desktop nothing it
# was not already paying: `go2.py` imports no vendor SDK, no mujoco and no
# rclpy at module scope (measured in a fresh interpreter by
# `tests/test_hw2_go2_backend.py`), and the `numpy`/`socket` it does reach were
# already reached by the sibling `.mujoco` and by `parcel_robot.core`. The two
# error types are exported beside it because a caller that catches "this
# backend refuses to move" should not have to import a submodule to name the
# exception.
from .go2 import Go2Backend, Go2BackendError, Go2MotionRefused

# ---- END CARD HW-2 ---------------------------------------------------------
from .mujoco import MujocoSocketBackend

__all__ = [
    "DynamicAgentTrack",
    # ---- CARD HW-2 (task_40) ----
    "Go2Backend",
    "Go2BackendError",
    "Go2MotionRefused",
    # ---- END CARD HW-2 ----
    "LidarObstacle",
    "MujocoSocketBackend",
    "OwnerTrack",
    "RobotPose",
    "SemanticObjectTrack",
    "SemanticRegionTrack",
    "SimObservation",
    "SimulatorBackend",
]
