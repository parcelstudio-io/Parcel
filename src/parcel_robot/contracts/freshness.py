"""Fail-closed TTL and freshness helpers for V1 evidence contracts.

Adapters record both a source clock and locally observed monotonic time.
Cross-clock mixing is forbidden: callers compare source stamps only to source
stamps, and monotonic stamps only to monotonic stamps. Expired, untransformable,
or clock-jumped samples are rejected — never softened into usable evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Default TTL budgets (monotonic ns). Conservative until measured on-device.
DEFAULT_TRACK_TTL_NS = 500_000_000  # 500 ms
DEFAULT_DETECTION_TTL_NS = 300_000_000  # 300 ms
DEFAULT_SEMANTIC_TTL_NS = 2_000_000_000  # 2 s
DEFAULT_SOCIAL_CUE_TTL_NS = 5_000_000_000  # 5 s
DEFAULT_DIALOGUE_STATE_TTL_NS = 500_000_000  # 500 ms (10 Hz channel)

# Clock-jump thresholds: source advancing while monotonic stalls, or reverse.
_MAX_SOURCE_AHEAD_OF_MONO_RATIO = 10.0
_MIN_MONO_DELTA_NS = 0
_MAX_SOURCE_BACKWARD_JUMP_NS = 0


@dataclass(frozen=True, slots=True)
class FreshnessVerdict:
    """Result of a fail-closed freshness check."""

    accepted: bool
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise TypeError("accepted must be a boolean")
        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string")
        if self.accepted and self.reason:
            raise ValueError("accepted verdict cannot carry a rejection reason")
        if not self.accepted and not self.reason:
            raise ValueError("rejected verdict requires a reason")


def finite_nonneg_ns(value: object, name: str) -> int:
    """Require a finite non-negative integer nanosecond stamp."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer nanosecond stamp")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def age_ns(*, received_monotonic_ns: int, now_monotonic_ns: int) -> int:
    """Age of a sample relative to a monotonic clock. Fail-closed on inversion."""

    received = finite_nonneg_ns(received_monotonic_ns, "received_monotonic_ns")
    now = finite_nonneg_ns(now_monotonic_ns, "now_monotonic_ns")
    if now < received:
        raise ValueError("monotonic clock went backwards relative to received stamp")
    return now - received


def is_expired(*, expires_monotonic_ns: int, now_monotonic_ns: int) -> bool:
    """True when now is at or past the exclusive-or-equal expiry boundary."""

    expires = finite_nonneg_ns(expires_monotonic_ns, "expires_monotonic_ns")
    now = finite_nonneg_ns(now_monotonic_ns, "now_monotonic_ns")
    return now >= expires


def expires_from_ttl(*, received_monotonic_ns: int, ttl_ns: int) -> int:
    """Compute expires_monotonic_ns = received + ttl. TTL must be positive."""

    received = finite_nonneg_ns(received_monotonic_ns, "received_monotonic_ns")
    if isinstance(ttl_ns, bool) or not isinstance(ttl_ns, int) or ttl_ns <= 0:
        raise ValueError("ttl_ns must be a positive integer")
    return received + ttl_ns


def check_freshness(
    *,
    received_monotonic_ns: int,
    expires_monotonic_ns: int,
    now_monotonic_ns: int,
    max_age_ns: int | None = None,
) -> FreshnessVerdict:
    """Fail-closed freshness gate used by every V1 evidence consumer."""

    try:
        age = age_ns(
            received_monotonic_ns=received_monotonic_ns,
            now_monotonic_ns=now_monotonic_ns,
        )
    except (TypeError, ValueError) as exc:
        return FreshnessVerdict(accepted=False, reason=f"invalid_clock:{exc}")

    if is_expired(
        expires_monotonic_ns=expires_monotonic_ns,
        now_monotonic_ns=now_monotonic_ns,
    ):
        return FreshnessVerdict(accepted=False, reason="expired")

    if max_age_ns is not None:
        if isinstance(max_age_ns, bool) or not isinstance(max_age_ns, int) or max_age_ns < 0:
            return FreshnessVerdict(accepted=False, reason="invalid_max_age")
        if age > max_age_ns:
            return FreshnessVerdict(accepted=False, reason="stale")

    return FreshnessVerdict(accepted=True)


def detect_clock_jump(
    *,
    previous_source_timestamp_ns: int,
    source_timestamp_ns: int,
    previous_received_monotonic_ns: int,
    received_monotonic_ns: int,
) -> FreshnessVerdict:
    """Reject samples that imply an untransformable source/monotonic discontinuity.

    Rules (fail-closed):
    - source timestamp must not go backwards;
    - monotonic received time must not go backwards;
    - source must not advance by more than
      ``_MAX_SOURCE_AHEAD_OF_MONO_RATIO`` × the monotonic delta when both advance.
    """

    try:
        prev_src = finite_nonneg_ns(previous_source_timestamp_ns, "previous_source_timestamp_ns")
        src = finite_nonneg_ns(source_timestamp_ns, "source_timestamp_ns")
        prev_mono = finite_nonneg_ns(
            previous_received_monotonic_ns, "previous_received_monotonic_ns"
        )
        mono = finite_nonneg_ns(received_monotonic_ns, "received_monotonic_ns")
    except (TypeError, ValueError) as exc:
        return FreshnessVerdict(accepted=False, reason=f"invalid_clock:{exc}")

    source_delta = src - prev_src
    mono_delta = mono - prev_mono

    if source_delta < _MAX_SOURCE_BACKWARD_JUMP_NS:
        return FreshnessVerdict(accepted=False, reason="source_clock_backward")
    if mono_delta < _MIN_MONO_DELTA_NS:
        return FreshnessVerdict(accepted=False, reason="monotonic_clock_backward")

    if mono_delta == 0 and source_delta > 0:
        return FreshnessVerdict(accepted=False, reason="source_advanced_without_monotonic")

    if mono_delta > 0 and source_delta > _MAX_SOURCE_AHEAD_OF_MONO_RATIO * mono_delta:
        return FreshnessVerdict(accepted=False, reason="source_clock_jump")

    return FreshnessVerdict(accepted=True)


def require_fresh(
    *,
    received_monotonic_ns: int,
    expires_monotonic_ns: int,
    now_monotonic_ns: int,
    max_age_ns: int | None = None,
) -> None:
    """Raise ValueError unless the sample passes the freshness gate."""

    verdict = check_freshness(
        received_monotonic_ns=received_monotonic_ns,
        expires_monotonic_ns=expires_monotonic_ns,
        now_monotonic_ns=now_monotonic_ns,
        max_age_ns=max_age_ns,
    )
    if not verdict.accepted:
        raise ValueError(f"evidence rejected: {verdict.reason}")


def speed_cap_from_staleness_m_s(
    *,
    pipeline_age_s: float,
    max_displacement_m: float = 0.15,
    absolute_max_m_s: float = 1.5,
) -> float:
    """Cap commanded speed so v·τ stays within a displacement budget (fail-closed).

    At 1.5 m/s and 100 ms staleness, displacement is 15 cm. Non-finite or
    negative age yields a zero cap.
    """

    if (
        not isinstance(pipeline_age_s, (int, float))
        or isinstance(pipeline_age_s, bool)
        or not math.isfinite(pipeline_age_s)
        or pipeline_age_s < 0.0
    ):
        return 0.0
    if (
        not isinstance(max_displacement_m, (int, float))
        or isinstance(max_displacement_m, bool)
        or not math.isfinite(max_displacement_m)
        or max_displacement_m < 0.0
    ):
        return 0.0
    if (
        not isinstance(absolute_max_m_s, (int, float))
        or isinstance(absolute_max_m_s, bool)
        or not math.isfinite(absolute_max_m_s)
        or absolute_max_m_s < 0.0
    ):
        return 0.0
    if pipeline_age_s == 0.0:
        return float(absolute_max_m_s)
    return min(float(absolute_max_m_s), float(max_displacement_m) / float(pipeline_age_s))
