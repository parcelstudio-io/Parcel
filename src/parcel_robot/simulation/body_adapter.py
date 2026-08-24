"""The MuJoCo body: a ``BodyIntentV1`` adapter that changes nothing.

This is the reference adapter, and its whole job is to be boring.  Given the
intent stream, it reproduces — byte for byte — what the runtime already sends
today: ``backend.expression(joint_offsets)`` on change only (the
``_step_expression`` rule), and ``backend.move(command)`` on change or after a
0.2 s refresh with ``backend.stop()`` once when the velocity lapses (the
``_dispatch_active`` rule).  If this adapter is not byte-identical to today's
path on the locomotion axis, the composer has taken authority it must not
have, and row B7 exists to catch exactly that.

The manifest says what this body can do: everything the expression engine
produces, because ``ExpressiveOffsets`` was written for it.  ``posture roll``
rides along under ``posture_offsets`` and is always zero — the offsets type has
no roll channel, and inventing one here would be inventing motion.
"""

from __future__ import annotations

from dataclasses import dataclass

from parcel_robot.contracts.body_intent import (
    BodyCapabilityManifest,
    BodyIntentV1,
    Velocity,
    degrade,
    dropped_axes,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.motion.body_composer import DEFAULT_LIMITS
from parcel_robot.motion.expression import ExpressiveOffsets, stance_joint_offsets
from parcel_robot.robot_profile import RobotProfile

#: How long a repeated velocity may go unsent before it is refreshed.  The
#: number is ``_dispatch_active``'s, not a new one.
COMMAND_REFRESH_S = 0.2

SIM_BODY_MANIFEST = BodyCapabilityManifest(
    name="mujoco_sim",
    locomotion_velocity=True,
    # The simulator holds by silence *and* accepts an explicit stop; the stop
    # is what today's runtime sends, so this body treats HOLD as a command.
    hold_is_command=True,
    posture_offsets=True,
    gaze_yaw=True,
    gaze_pitch=True,
    gestures=("sit", "bow", "stand", "lie_down", "stretch", "play_bow", "paw_wave"),
    max_rates=DEFAULT_LIMITS.as_max_rates(),
)


@dataclass(frozen=True)
class BodyDispatch:
    """What the adapter did with one intent — the row a harness records."""

    seq: int
    expression_sent: bool
    velocity_sent: bool
    stop_sent: bool
    joint_offsets: dict[str, float]
    command: VelocityCommand | None
    dropped_axes: tuple[str, ...] = ()


class SimulationBodyAdapter:
    """Drive a ``SimulatorBackend`` from the intent stream.

    ``backend`` is duck-typed on purpose (``move`` / ``stop`` / ``expression``)
    so this module keeps no dependency on the backend package and a test can
    hand it a recorder.
    """

    def __init__(
        self,
        backend: object,
        profile: RobotProfile,
        *,
        manifest: BodyCapabilityManifest = SIM_BODY_MANIFEST,
        refresh_s: float = COMMAND_REFRESH_S,
    ) -> None:
        self.backend = backend
        self.profile = profile
        self.manifest = manifest
        self.refresh_s = float(refresh_s)
        self._expression_sent: dict[str, float] | None = None
        self._last_command: VelocityCommand | None = None
        self._last_command_at: float | None = None
        self._was_moving = False
        self.expression_publishes = 0
        self.velocity_publishes = 0
        self.stop_publishes = 0

    def apply(self, intent: BodyIntentV1, *, now_s: float) -> BodyDispatch:
        fitted = degrade(intent, self.manifest)
        joint_offsets = self._expression(fitted)
        expression_sent = joint_offsets is not None
        command, velocity_sent, stop_sent = self._locomotion(fitted, now_s=now_s)
        return BodyDispatch(
            seq=fitted.seq,
            expression_sent=expression_sent,
            velocity_sent=velocity_sent,
            stop_sent=stop_sent,
            joint_offsets=dict(joint_offsets or {}),
            command=command,
            dropped_axes=dropped_axes(intent, self.manifest),
        )

    # -- the two channels --------------------------------------------------
    def _expression(self, intent: BodyIntentV1) -> dict[str, float] | None:
        """Publish the overlay when it changed; return it, or ``None``.

        ``_step_expression``'s exact rule, including the "zero offsets clear
        the overlay with an empty mapping" branch: an empty mapping is how the
        IPC clears a held overlay, and sending it on every idle tick is what
        the change check exists to avoid.
        """

        offsets = ExpressiveOffsets(
            body_height_m=intent.posture[0],
            body_pitch_rad=intent.posture[1],
            head_yaw_rad=intent.gaze[0],
            head_pitch_rad=intent.gaze[1],
        ).clamped()
        joint_offsets = stance_joint_offsets(self.profile, offsets) if not offsets.is_zero else {}
        if joint_offsets == self._expression_sent:
            return None
        self.backend.expression(joint_offsets)  # type: ignore[attr-defined]
        self._expression_sent = joint_offsets
        self.expression_publishes += 1
        return joint_offsets

    def _locomotion(
        self, intent: BodyIntentV1, *, now_s: float
    ) -> tuple[VelocityCommand | None, bool, bool]:
        velocity = intent.velocity
        if velocity is None:
            if self._was_moving:
                self.backend.stop()  # type: ignore[attr-defined]
                self.stop_publishes += 1
                self._was_moving = False
                self._last_command = None
                self._last_command_at = None
                return None, False, True
            return None, False, False

        command = to_velocity_command(velocity)
        stale = self._last_command_at is None or now_s - self._last_command_at >= self.refresh_s
        if command == self._last_command and not stale:
            return command, False, False
        self.backend.move(command)  # type: ignore[attr-defined]
        self.velocity_publishes += 1
        self._last_command = command
        self._last_command_at = now_s
        self._was_moving = any(abs(value) > 1e-6 for value in (command.vx, command.vy, command.vyaw))
        return command, True, False


def to_velocity_command(velocity: Velocity) -> VelocityCommand:
    """The exact, lossless conversion back to the dispatch boundary's type.

    Field-for-field with no arithmetic: this is the line row B7 checks, and it
    is deliberately the only place in the body path where the two velocity
    types meet.
    """

    return VelocityCommand(vx=velocity.vx, vy=velocity.vy, vyaw=velocity.vyaw)
