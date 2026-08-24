from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from parcel_robot.models import Pose, VelocityCommand
from parcel_robot.motion.router import MotionRouter
from parcel_robot.simulation.ipc import (
    publish_pose,
    publish_stop,
    publish_trajectory,
    publish_velocity,
)

from .catalog import SkillCatalog
from .schema import (
    MAX_POSE_PLAYBACK_S,
    MAX_TRAJECTORY_PLAYBACK_S,
    SkillSpec,
    playback_timing,
)


@dataclass
class ExecutionResult:
    skill_id: str
    kind: str
    message: str
    accepted: bool = True
    requested_speed: float = 1.0
    effective_rate: float = 1.0
    effective_duration_s: float = 0.0


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
            requested_speed = overrides.get("speed", skill.speed)
            rate, duration = playback_timing(
                skill.duration,
                requested_speed,
                maximum_duration_s=MAX_POSE_PLAYBACK_S,
            )
            pose = Pose(skill.id, dict(skill.joints), duration=duration)
            # Stop locomotion before publishing the pose. In the simulator the
            # stop hook restores standing joints, so doing this afterward would
            # immediately overwrite the requested pose.
            if self.motion is not None:
                self.motion.stop()
            if self.on_pose is not None:
                self.on_pose(pose)
            if self.sim_socket is not None:
                publish_pose(pose, self.sim_socket)
            return ExecutionResult(
                skill.id,
                skill.kind,
                f"Pose {skill.id}",
                True,
                requested_speed=float(requested_speed),
                effective_rate=rate,
                effective_duration_s=duration,
            )

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
            requested_speed = overrides.get("speed", skill.speed)
            authored_duration = float(skill.keyframes[-1].t)
            rate, duration = playback_timing(
                authored_duration,
                requested_speed,
                maximum_duration_s=MAX_TRAJECTORY_PLAYBACK_S,
            )
            retimed = replace(
                skill,
                # Timing is baked into the execution copy. Leave its speed at
                # unity so a future backend cannot apply the rate a second time.
                speed=1.0,
                keyframes=tuple(
                    replace(frame, t=float(frame.t) / rate) for frame in skill.keyframes
                ),
            )
            if self.motion is not None:
                self.motion.stop()
            if self.on_trajectory is not None:
                self.on_trajectory(retimed)
            if self.sim_socket is not None:
                publish_trajectory(retimed, self.sim_socket)
            return ExecutionResult(
                skill.id,
                skill.kind,
                f"Trajectory {skill.id}",
                True,
                requested_speed=float(requested_speed),
                effective_rate=rate,
                effective_duration_s=duration,
            )

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
