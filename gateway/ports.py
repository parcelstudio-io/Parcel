"""The vendor-facing port. No vendor SDK is imported here or anywhere in this tree.

The gateway reaches the robot's high-level motion service through a structural
:class:`typing.Protocol` only.  ``parcel_robot.bridge.fake_sport
.FakeSportServiceV1`` satisfies it by shape, so the bench needs no adapter and
no ``isinstance`` check; a real vendor client would satisfy it the same way
inside its own venv.  Nothing in this module knows what is on the other side.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol


class SportStateLike(Protocol):
    """One high-level feedback sample as the vendor reports it."""

    sequence: int
    received_at_monotonic_s: float
    vx_mps: float
    vy_mps: float
    vyaw_rad_s: float
    lease_active: bool


class SportPort(Protocol):
    """The whole vendor surface the gateway is allowed to touch."""

    def acquire_writer(self, writer_id: str) -> bool: ...

    def release_writer(self, writer_id: str | None) -> None: ...

    def move(self, *, writer_id: str, vx_mps: float, vy_mps: float, vyaw_rad_s: float) -> None: ...

    def stop_move(self, *, reason: str) -> bool: ...

    def state(self) -> SportStateLike: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class SportSampleV1:
    """A validated copy of one vendor sample.

    The gateway never holds a live vendor object across a lock boundary: it
    copies the six fields it is allowed to reason about and validates them at
    the copy.  A vendor that returns a bool where a float belongs, a NaN
    velocity, or a non-monotonic receipt stamp fails *here*, closed, instead of
    silently becoming positive authority.
    """

    sequence: int
    received_at_monotonic_s: float
    vx_mps: float
    vy_mps: float
    vyaw_rad_s: float
    lease_active: bool

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("sport sample sequence must be an integer")
        if self.sequence < 0:
            raise ValueError("sport sample sequence must be non-negative")
        for name in ("received_at_monotonic_s", "vx_mps", "vy_mps", "vyaw_rad_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"sport sample {name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"sport sample {name} must be finite")
        if not isinstance(self.lease_active, bool):
            raise TypeError("sport sample lease_active must be a boolean")

    @property
    def max_abs_velocity(self) -> float:
        return max(abs(self.vx_mps), abs(self.vy_mps), abs(self.vyaw_rad_s))


def read_sport_sample(port: SportPort) -> SportSampleV1:
    """Copy and validate one vendor sample. Never returns a partial view."""

    raw = port.state()
    missing = [
        name
        for name in (
            "sequence",
            "received_at_monotonic_s",
            "vx_mps",
            "vy_mps",
            "vyaw_rad_s",
            "lease_active",
        )
        if not hasattr(raw, name)
    ]
    if missing:
        raise TypeError(f"sport state is missing required fields: {sorted(missing)}")
    return SportSampleV1(
        sequence=raw.sequence,
        received_at_monotonic_s=float(raw.received_at_monotonic_s),
        vx_mps=float(raw.vx_mps),
        vy_mps=float(raw.vy_mps),
        vyaw_rad_s=float(raw.vyaw_rad_s),
        lease_active=raw.lease_active,
    )
