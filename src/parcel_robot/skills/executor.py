from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from parcel_robot.models import Pose, VelocityCommand
from parcel_robot.motion import MotionRouter
from parcel_robot.sim_ipc import publish_pose, publish_stop, publish_trajectory, publish_velocity

from .catalog import SkillCatalog
from .schema import SkillSpec


@dataclass
class ExecutionResult:
    skill_id: str
    kind: str
    message: str
    accepted: bool = True


class SkillExecutor:
    """Turn a SkillSpec into pose / walk / trajectory / motion side effects."""

    def __init__(
        self,
        catalog: SkillCatalog,
        *,
        motion: MotionRouter | None = None,
        sim_socket: str | None = None,
        on_pose: Callable[[Pose], None] | None = None,
        on_velocity: Callable[[VelocityCommand], None] | None = None,
        on_trajectory: Callable[[SkillSpec], None] | None = None,
        on_stop: Callable[[], None] | None = None,
    ):
        self.catalog = catalog
        self.motion = motion
        self.sim_socket = sim_socket
        self.on_pose = on_pose
        self.on_velocity = on_velocity
        self.on_trajectory = on_trajectory
        self.on_stop = on_stop
        self.selected: str | None = None

    def select(self, skill_id: str) -> SkillSpec:
        skill = self.catalog.get(skill_id)
        self.selected = skill.id
        return skill

    def stop(self) -> ExecutionResult:
        if self.motion is not None:
            self.motion.stop()
        if self.on_stop is not None:
            self.on_stop()
        if self.sim_socket is not None:
            publish_stop(self.sim_socket)
        return ExecutionResult("stop", "stop", "Stopped", True)

    def execute(self, skill_id: str, **overrides: float) -> ExecutionResult:
        skill = self.select(skill_id)
        if skill.kind == "pose":
            pose = Pose(skill.id, dict(skill.joints), duration=skill.duration)
            if self.on_pose is not None:
                self.on_pose(pose)
            if self.sim_socket is not None:
                publish_pose(pose, self.sim_socket)
            if self.motion is not None:
                self.motion.stop()
            return ExecutionResult(skill.id, skill.kind, f"Pose {skill.id}", True)

        if skill.kind in {"velocity", "gait"}:
            command = VelocityCommand(
                vx=float(overrides.get("vx", skill.velocity.vx)),
                vy=float(overrides.get("vy", skill.velocity.vy)),
                vyaw=float(overrides.get("vyaw", skill.velocity.vyaw)),
            )
            if self.motion is not None:
                message = self.motion.walk(command)
            else:
                message = f"Velocity {command}"
            # MotionRouter owns its delivery hook when configured. Calling the
            # same hook twice publishes one skill twice in ROS deployments.
            motion_hook = self.motion.on_command if self.motion is not None else None
            if self.on_velocity is not None and self.on_velocity != motion_hook:
                self.on_velocity(command)
            if self.sim_socket is not None:
                publish_velocity(
                    command,
                    self.sim_socket,
                    gait_style=skill.gait.style if skill.kind == "gait" else None,
                    frequency_hz=skill.gait.frequency_hz if skill.kind == "gait" else None,
                )
            return ExecutionResult(skill.id, skill.kind, message, True)

        if skill.kind == "trajectory":
            if self.motion is not None:
                self.motion.stop()
            if self.on_trajectory is not None:
                self.on_trajectory(skill)
            if self.sim_socket is not None:
                publish_trajectory(skill, self.sim_socket)
            return ExecutionResult(skill.id, skill.kind, f"Trajectory {skill.id}", True)

        if skill.kind == "policy":
            if not skill.rl.policy_path:
                return ExecutionResult(
                    skill.id,
                    skill.kind,
                    f"Policy skill {skill.id} has no policy_path",
                    False,
                )
            return ExecutionResult(
                skill.id,
                skill.kind,
                f"Policy skill {skill.id} armed ({skill.rl.policy_path})",
                True,
            )

        return ExecutionResult(skill.id, skill.kind, f"Unsupported kind {skill.kind}", False)
