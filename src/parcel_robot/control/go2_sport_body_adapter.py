"""The Go2 Sport body — the SHAPE of an adapter, and nothing that can move.

`docs/MOTION.md` and `docs/EMBODIED_EXPRESSION.md` both say the same thing in
different words: nothing may reach a physical Go2 until a human has
commissioned the mode table, the velocity frame, the axis signs, and each
controller-owned action separately.  This module respects that literally.  It
declares the Go2's capability manifest, it can build the exact sequence of
Sport calls one ``BodyIntentV1`` maps onto — and every method on the adapter
refuses.  There is no SDK import in this file, at module scope or inside a
method, so importing it can neither start DDS nor take a lease.

What the manifest says about this body, and why each flag is what it is:

* ``locomotion_velocity`` — ``SportClient.Move(vx, vy, vyaw)``, the same SE(2)
  contract ``TimedVelocitySetpoint`` already carries.
* ``hold_is_command`` — ``StopMove``.  On this body a hold is emphatically a
  command: Sport keeps walking on the last ``Move`` until told otherwise, so
  "stop sending" is the one thing that must never mean "stand still".
* ``posture_offsets`` — a carefully bounded ``Euler`` is the *candidate*
  (`EMBODIED_EXPRESSION.md` §"Physical Go2 implementation"), and it carries
  pitch and roll only.  Body height is a separate uncommissioned primitive, so
  the composer's ``dz`` is dropped rather than pretended.  The manifest cannot
  express "two of three posture axes", which is a real finding for row B8: see
  ``POSTURE_AXES_SUPPORTED``.
* ``gaze_yaw`` / ``gaze_pitch`` — both ``False``.  A Go2 has no neck.  The
  head channels are telemetry on this body and the adapter must drop them, not
  turn them into a body twist: that would be inventing motion, in the precise
  sense :func:`~parcel_robot.contracts.body_intent.degrade` forbids.
"""

from __future__ import annotations

from dataclasses import dataclass

from parcel_robot.contracts.body_intent import (
    BodyCapabilityManifest,
    BodyIntentV1,
    degrade,
)

#: Sport primitives this adapter would use, named in ``docs/EMBODIED_EXPRESSION.md``.
SPORT_MOVE = "Move"
SPORT_STOP_MOVE = "StopMove"
SPORT_EULER = "Euler"

#: Which posture axes an ``Euler`` call could carry, in the composer's order
#: ``(dz, pitch, roll)``.  ``dz`` is False because body height is a different,
#: separately uncommissioned primitive — the manifest's single
#: ``posture_offsets`` flag cannot say so, so it is said here.
POSTURE_AXES_SUPPORTED = (False, True, True)

GO2_SPORT_MANIFEST = BodyCapabilityManifest(
    name="unitree_go2_sport",
    locomotion_velocity=True,
    hold_is_command=True,
    posture_offsets=True,
    gaze_yaw=False,
    gaze_pitch=False,
    gestures=(
        "Hello",
        "Sit",
        "RiseSit",
        "Stretch",
        "BalanceStand",
        "StandUp",
        "RecoveryStand",
    ),
    max_rates=(),
)


class Go2SportNotCommissionedError(RuntimeError):
    """Raised by every method here.  Commissioning is a human procedure."""


@dataclass(frozen=True)
class SportCall:
    """One controller-owned Sport call, as data.  Nothing executes it."""

    method: str
    args: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.method not in {SPORT_MOVE, SPORT_STOP_MOVE, SPORT_EULER}:
            raise ValueError(f"unsupported Sport primitive: {self.method!r}")


def sport_calls_for(
    intent: BodyIntentV1,
    manifest: BodyCapabilityManifest = GO2_SPORT_MANIFEST,
) -> tuple[SportCall, ...]:
    """The call sequence ``intent`` maps onto — a shape for review, not a plan.

    Pure: it builds tuples.  It opens no transport, imports no SDK, and is not
    a method on the adapter precisely so that "every adapter method refuses"
    stays literally true.  Reviewing this function is how a human sees what
    commissioning would be signing off on.
    """

    fitted = degrade(intent, manifest)
    calls: list[SportCall] = []
    velocity = fitted.velocity
    if velocity is None:
        calls.append(SportCall(SPORT_STOP_MOVE))
    else:
        calls.append(SportCall(SPORT_MOVE, velocity.as_tuple()))
    if manifest.posture_offsets:
        _dz, pitch, roll = fitted.posture
        # Euler(roll, pitch, yaw): body yaw is NOT ours to write — Move owns
        # heading — so it is always zero here, and dz has no Euler axis at all.
        if pitch != 0.0 or roll != 0.0:
            calls.append(SportCall(SPORT_EULER, (roll, pitch, 0.0)))
    return tuple(calls)


class Go2SportBodyAdapter:
    """A stub that holds the shape of the physical body adapter and refuses.

    It exists so the milestone design can be reviewed against a real interface
    rather than a paragraph, and so the day the native sole-writer gateway
    lands there is one obvious file to fill in — with the commissioning
    evidence listed in ``docs/EMBODIED_EXPRESSION.md`` attached to the change,
    not a flag flipped.
    """

    #: Every gate in ``docs/MOTION.md`` that must be true first.  All false.
    REQUIRED_COMMISSIONING = (
        "axes_commissioned",
        "state_frame_commissioned",
        "allowed_modes",
        "euler_envelope_commissioned",
        "native_sole_writer_gateway",
    )

    def __init__(self, *, manifest: BodyCapabilityManifest = GO2_SPORT_MANIFEST) -> None:
        self.manifest = manifest
        self.commissioned = False

    def activate(self) -> None:
        self._refuse("activate")

    def apply(self, intent: BodyIntentV1, *, now_s: float) -> None:
        self._refuse("apply")

    def hold(self) -> None:
        self._refuse("hold")

    def stop(self, reason: str = "") -> None:
        self._refuse("stop")

    def emergency_stop(self) -> None:
        self._refuse("emergency_stop")

    def close(self) -> None:
        self._refuse("close")

    def _refuse(self, method: str) -> None:
        raise Go2SportNotCommissionedError(
            f"Go2SportBodyAdapter.{method} is a stub: no Sport action may be sent until "
            f"{', '.join(self.REQUIRED_COMMISSIONING)} are all satisfied on the exact robot "
            "and firmware (docs/MOTION.md, docs/EMBODIED_EXPRESSION.md). "
            "Read sport_calls_for() for the intended call shape."
        )
