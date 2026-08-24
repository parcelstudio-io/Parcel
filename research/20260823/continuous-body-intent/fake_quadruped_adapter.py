"""A second, deliberately UNLIKE body — written against the manifest only.

The portability claim under test is not "the code is generic"; it is "a body
nobody had in mind when the composer was written can be driven from the same
stream with zero product edits".  So this body is different on purpose:

* no posture channel at all (a fixed-height trunk, no Euler-like primitive);
* one neck servo: gaze YAW only, no pitch;
* holonomic velocity, but HOLD must be an explicit frame on the wire — going
  quiet is a fault to this body's watchdog, not a request to stand still;
* its own joint naming and its own rate ceilings, lower than the sim's.

Everything it needs it takes from ``BodyCapabilityManifest`` +
``degrade``. It imports no product code other than the contract itself, and
lives under ``research/`` because it is evidence, not a product body.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from parcel_robot.contracts.body_intent import (
    BodyCapabilityManifest,
    BodyIntentV1,
    degrade,
    dropped_axes,
)

FAKE_QUADRUPED_MANIFEST = BodyCapabilityManifest(
    name="research_fake_quadruped",
    locomotion_velocity=True,
    hold_is_command=True,
    posture_offsets=False,
    gaze_yaw=True,
    gaze_pitch=False,
    gestures=("wag", "perk_ears"),
    max_rates=(("gaze_yaw", 1.5),),
)


@dataclass(frozen=True)
class FakeFrame:
    """One wire frame this body's (imaginary) firmware would accept."""

    kind: str
    values: tuple[float, ...]


@dataclass
class FakeQuadrupedAdapter:
    """Turn the intent stream into this body's frames, and hold its own state.

    ``max_frame_gap_s`` is the body's watchdog: it is the reason
    ``hold_is_command`` is True in the manifest above, and the reason this
    adapter emits a frame on EVERY intent instead of only on change.
    """

    manifest: BodyCapabilityManifest = FAKE_QUADRUPED_MANIFEST
    max_frame_gap_s: float = 0.25
    frames: list[FakeFrame] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    neck_yaw_rad: float = 0.0
    hold_frames: int = 0
    move_frames: int = 0
    watchdog_faults: int = 0
    rate_refusals: int = 0
    _last_frame_at: float | None = None
    _last_slew_at: float | None = None

    def apply(self, intent: BodyIntentV1, *, now_s: float) -> FakeFrame:
        """Consume one intent; always produce exactly one frame."""

        for axis in dropped_axes(intent, self.manifest):
            self.dropped[axis] = self.dropped.get(axis, 0) + 1
        fitted = degrade(intent, self.manifest)

        if self._last_frame_at is not None and now_s - self._last_frame_at > self.max_frame_gap_s:
            # The stream went quiet for longer than this body tolerates. The
            # composer is supposed to make this impossible; count it rather
            # than hide it, because it is the falsifier for "always emitting".
            self.watchdog_faults += 1
        self._last_frame_at = now_s

        self._track_neck(fitted.gaze[0], now_s)
        velocity = fitted.velocity
        if velocity is None:
            self.hold_frames += 1
            frame = FakeFrame("hold", (self.neck_yaw_rad,))
        else:
            self.move_frames += 1
            frame = FakeFrame("move", (*velocity.as_tuple(), self.neck_yaw_rad))
        self.frames.append(frame)
        return frame

    def _track_neck(self, target_rad: float, now_s: float) -> None:
        """Slew the one servo this body has, at the rate its manifest declares.

        The composer's limiter is already gentler than most bodies need; this
        one is slower still, which is exactly the case a manifest exists for.
        A body may always be MORE restrictive than the stream it is given.
        """

        ceiling = self.manifest.rate("gaze_yaw", 1.5) or 1.5
        dt_s = 0.02 if self._last_slew_at is None else max(1e-4, now_s - self._last_slew_at)
        self._last_slew_at = now_s
        error = target_rad - self.neck_yaw_rad
        step = ceiling * dt_s
        if abs(error) > step:
            self.rate_refusals += 1
            self.neck_yaw_rad += step if error > 0.0 else -step
        else:
            self.neck_yaw_rad = target_rad

    def summary(self) -> dict[str, object]:
        return {
            "manifest": self.manifest.name,
            "frames": len(self.frames),
            "hold_frames": self.hold_frames,
            "move_frames": self.move_frames,
            "dropped_axes": dict(self.dropped),
            "watchdog_faults": self.watchdog_faults,
            "rate_refusals": self.rate_refusals,
            "neck_yaw_rad": round(self.neck_yaw_rad, 6),
        }
