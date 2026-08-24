"""Mirrored timing/speed limits, with the source of every number.

This package must not import ``parcel_robot.control`` or
``parcel_robot.bridge.timing`` — those pull the product's dependency set into a
process whose whole point is to carry the vendor's instead.  Every constant is
therefore a *mirrored literal* whose source is named in its comment, exactly
the pattern ``bridge/timing.py`` already uses for its ``W0B_*`` block, and
``tests/test_m1_0_gateway.py`` pins each one back to ``ControlTiming``,
``bridge.protocol`` and ``bridge.timing``.  A limit that moves without a new
derivation turns the suite red instead of silently decoupling the two sides.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: ``ControlTiming.control_hz`` (``src/parcel_robot/control/models.py``).
GATEWAY_CONTROL_HZ = 50.0

#: ``ControlTiming.period_s`` == ``1 / control_hz``.  The watchdog's wake-up
#: period; ``bridge/timing.py`` ``PROPOSED_LATENCY_GATES_V1`` budgets 2.0 ms
#: p99 of scheduling jitter against it (a target-compute number, not a desktop
#: one — this bench reports jitter and gates nothing on it).
GATEWAY_WATCHDOG_PERIOD_S = 0.02

#: ``bridge/protocol.py`` ``MAX_LOCAL_TTL_MS`` == ``ControlTiming
#: .command_timeout_s`` * 1000 == ``bridge/timing.py`` ``W0B_MAX_TTL_S`` * 1000.
#: The frozen 0.35 s lease.  A duration crosses the wire; the deadline is
#: derived here, on this process's clock, at receipt.
MAX_LOCAL_TTL_MS = 350

#: ``ControlTiming.state_timeout_s`` — feedback older than this is not
#: evidence, and evidence is what positive authority is made of.
STATE_TIMEOUT_S = 0.25

#: ``ControlTiming.stop_timeout_s`` == ``bridge/timing.py``
#: ``ENVELOPE_STOP_TIMEOUT_S`` == ``configs/robot.yaml`` ``control
#: .stop_timeout_s``.  The budget for witnessing stillness, not a braking
#: measurement.
STOP_TIMEOUT_S = 1.0

#: ``ControlTiming.stop_retry_s``.
STOP_RETRY_S = 0.2

#: ``ControlTiming.stop_settled_samples`` — how many consecutive fresh,
#: advancing, exactly-zero samples make a stationary witness.
STOP_SETTLED_SAMPLES = 2

#: ``ControlTiming.settled_linear_speed_mps`` / ``settled_yaw_speed_rad_s``.
#: These are the *production* discrimination floors.  This gateway does not use
#: them as its stop witness: it requires exact zero (below), which is strictly
#: stronger, and the suite pins that ordering.
SETTLED_LINEAR_MPS = 0.08
SETTLED_YAW_RAD_S = 0.12

#: "Exact zero" as a float comparison.  Same tolerance as
#: ``FakeSportStateV1.stationary``.  Exact zero remains exact zero at the
#: vendor write (HLD §8.8).
EXACT_ZERO = 1e-9

#: How long a submitted vendor write may remain in flight before positive
#: authority is invalidated.  Set to ``STATE_TIMEOUT_S``: a writer that has not
#: returned within one feedback timeout cannot be producing fresh evidence, and
#: GWF-009 (``move_applies_then_never_replies``) is exactly that shape.
VENDOR_WRITE_STALL_S = STATE_TIMEOUT_S

#: Bounded local audit ring (HLD §8.8 "bounded local audit ring and health
#: output").  Records are dropped with accounting, never queued without bound,
#: and the ring is never on the stop path.
AUDIT_RING_CAPACITY = 512

#: ``bridge/timing.py`` ``W0B_MAX_YAW_RAD_S`` — the fastest yaw the
#: commissioning band admits.  It is the yaw cap for **every** regime below:
#: no faster yaw has a source anywhere in the tree today, and the conservative
#: choice is the one that has one.
MAX_YAW_RAD_S = 0.15625


@dataclass(frozen=True)
class SpeedRegimeV1:
    """One commissioned speed regime's hard local caps."""

    name: str
    max_linear_mps: float
    max_yaw_rad_s: float
    source: str

    def __post_init__(self) -> None:
        for name in ("max_linear_mps", "max_yaw_rad_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"regime {name} must be numeric")
            if not math.isfinite(float(value)) or value <= 0.0:
                raise ValueError(f"regime {name} must be finite and positive")
        if not self.name or not self.source:
            raise ValueError("a speed regime needs a name and a source")


#: Mirrors ``bridge/timing.py`` ``ENVELOPE_REGIMES_V1`` speeds, in its order.
REGIMES_V1: tuple[SpeedRegimeV1, ...] = (
    SpeedRegimeV1(
        name="one_axis",
        max_linear_mps=0.05,
        max_yaw_rad_s=MAX_YAW_RAD_S,
        source="bridge/timing.py ENVELOPE_ONE_AXIS_MPS (commissioning/limits.py MAX_LINEAR_MPS)",
    ),
    SpeedRegimeV1(
        name="leashed",
        max_linear_mps=0.15,
        max_yaw_rad_s=MAX_YAW_RAD_S,
        source="bridge/timing.py ENVELOPE_LEASHED_MPS (WAVE3_HW_DESIGN_FABLE.md HW-12)",
    ),
    SpeedRegimeV1(
        name="restricted_free",
        max_linear_mps=0.25,
        max_yaw_rad_s=MAX_YAW_RAD_S,
        source="bridge/timing.py ENVELOPE_RESTRICTED_FREE_MPS (patrol/mission.py cruise_vx)",
    ),
)

#: ``bridge/timing.py`` ``DEFAULT_ACTIVE_REGIME``: until the stopping-envelope
#: row is green with measured numbers, the commissioned regime is the slowest.
DEFAULT_ACTIVE_REGIME = "one_axis"


def regime(name: str) -> SpeedRegimeV1:
    """The regime by name. An unknown name raises rather than defaulting."""

    for candidate in REGIMES_V1:
        if candidate.name == name:
            return candidate
    known = ", ".join(item.name for item in REGIMES_V1)
    raise ValueError(f"unknown speed regime {name!r}; known regimes: {known}")


@dataclass(frozen=True)
class GovernorLimitsV1:
    """Everything the governor and the core are allowed to compare against."""

    regime: SpeedRegimeV1
    max_local_ttl_ms: int = MAX_LOCAL_TTL_MS
    watchdog_period_s: float = GATEWAY_WATCHDOG_PERIOD_S
    state_timeout_s: float = STATE_TIMEOUT_S
    stop_timeout_s: float = STOP_TIMEOUT_S
    stop_retry_s: float = STOP_RETRY_S
    stop_settled_samples: int = STOP_SETTLED_SAMPLES
    vendor_write_stall_s: float = VENDOR_WRITE_STALL_S
    exact_zero: float = EXACT_ZERO

    def __post_init__(self) -> None:
        if not isinstance(self.regime, SpeedRegimeV1):
            raise TypeError("limits.regime must be a SpeedRegimeV1")
        if isinstance(self.max_local_ttl_ms, bool) or not isinstance(self.max_local_ttl_ms, int):
            raise TypeError("max_local_ttl_ms must be an integer")
        if not 1 <= self.max_local_ttl_ms <= MAX_LOCAL_TTL_MS:
            raise ValueError(f"max_local_ttl_ms must be in [1, {MAX_LOCAL_TTL_MS}]")
        if (
            isinstance(self.stop_settled_samples, bool)
            or not isinstance(self.stop_settled_samples, int)
            or self.stop_settled_samples < 1
        ):
            raise ValueError("stop_settled_samples must be a positive integer")
        for name in (
            "watchdog_period_s",
            "state_timeout_s",
            "stop_timeout_s",
            "stop_retry_s",
            "vendor_write_stall_s",
            "exact_zero",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"limits.{name} must be numeric")
            if not math.isfinite(float(value)) or value <= 0.0:
                raise ValueError(f"limits.{name} must be finite and positive")
        if self.exact_zero >= SETTLED_LINEAR_MPS or self.exact_zero >= SETTLED_YAW_RAD_S:
            raise ValueError("the exact-zero witness must be stricter than the settled floors")

    @property
    def max_local_ttl_s(self) -> float:
        return self.max_local_ttl_ms / 1000.0


def default_limits(regime_name: str = DEFAULT_ACTIVE_REGIME) -> GovernorLimitsV1:
    return GovernorLimitsV1(regime=regime(regime_name))
