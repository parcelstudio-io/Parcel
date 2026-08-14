"""Bracketed physical sync events — clock discipline for a robot that has no clock.

Card PS-I of the **corrective** tranche PS-2
(``scrum/20260813/task_1/RISK_ASSESSMENT.md`` §*The clock card needs redesign*).

The defect this replaces
-----------------------
PS-C built ``clockmap.py`` around an interrogation: ask the device for its
clock, bracket the answer by the round trip, fit offset and drift. Measured at
source before this card started::

    ClockSample(device_source_ns=None, ...)
      -> non_integer_field: device_source_ns must be an int (nanoseconds)
    ClockSample(round_trip_ns=None, ...)
      -> non_integer_field: round_trip_ns must be an int (nanoseconds)
    capture.channels: go2.lowstate  source_clock=wrapping_counter  rate=500 Hz

Both fields are mandatory and neither can be produced for the Go2. The dog
exposes **no queryable clock and no round-trip primitive**, and ``lowstate`` —
the 500 Hz IMU, the highest-timing-value channel on the robot — carries **no
timestamp field at all**, only ``tick``: a ``uint32`` millisecond counter that
wraps (~49.7 days) and starts at an arbitrary value. ``SportModeState.stamp`` is
the single device ``TimeSpec`` the dog emits, and it rides a service-gated
channel that can be silent while its publisher exists. **As designed,
``ClockMapV1`` could not be populated for the dog at all.**

The replacement is not software: it is a ritual
-----------------------------------------------
A **physical sync event** is one instant made visible in several sensors at
once, so their timelines can be pinned to each other with no protocol between
them. Four events, chosen because each covers a different failure of the others,
performed as one ~35 s script at session **start and end** (:data:`RITUAL_SCRIPT`):

======================  ======================================================
Event                   Why this one
======================  ======================================================
Controller button       Lands in ``wireless_remote[40]`` *inside* ``lowstate``
                        at 500 Hz **and** on the ``wirelesscontroller`` topic —
                        a cross-check between two paths off one device, which
                        is the only way to see a per-topic transport delay.
10 s still-twist-still  Visible to every IMU and both LiDARs. The only event
                        the point-cloud tools can also use.
3 sharp taps            Sub-sample-sharp in an accelerometer. The
                        highest-precision alignment feature available, and the
                        only one that survives a 500 Hz channel's quantisation.
5 torch flashes,        The only event a camera can see. White **and** 850 nm
gaps 1, 2, 1, 3 s       so the D455's colour and IR streams both catch it.
                        UNEVEN gaps: an even train aliases onto itself under a
                        shifted alignment, and this module refuses an ambiguous
                        match rather than picking one — see
                        :func:`match_trains` and the ambiguity gate in the tests.
======================  ======================================================

**Bracketing is what buys the slope.** One ritual gives an offset. Two, at the
ends of the session, give an offset *and* a drift rate *and* a residual. This is
what the CEAR and M-SEVIQ quadruped-dataset teams do, it costs ten seconds a
side, and it is unrecoverable the moment the robot powers down.

What is honest about the result, and what is not
------------------------------------------------
Every offset here is a **mean of matched-event residuals with a two-part
uncertainty**, reusing :class:`~scripts.parcel_capture.clockmap.Uncertainty`
unchanged:

* ``statistical`` — Student-t 95% from the scatter of the matched events.
  Shrinks like ``1/sqrt(n)``, so a modality that saw 3 of 5 flashes reports a
  **wider** interval than one that saw 5. ``None`` at ``n = 1``: a single event
  has no scatter to bound it and quoting ``0`` there would be a lie.
* ``systematic`` — the detection brackets, which do **not** shrink with ``n``. A
  brightness step seen by a 30 Hz camera is located to ±1 frame no matter how
  many flashes there are, and a fixed pipeline latency biases every event of the
  ritual identically. Plus a **dropout penalty** (:data:`DROPOUT_PENALTY_FACTOR`)
  when the two trains disagree on how many events happened, because a channel
  that lost 2 of 5 events was not healthy during the ritual and nothing in the
  evidence bounds what it did to the 3 it kept.

The fit across rituals is ``clockmap``'s, called through
:func:`~scripts.parcel_capture.clockmap.fit_relation` — segmentation first, then
OLS, so a **step** between two rituals is reported as a step instead of being
smoothed into the drift. Where no events exist there is no evidence, and this
module says so out loud rather than interpolating: see :class:`BlindInterval`.
With only the two bracketing rituals the whole session between them is one blind
interval, and a step inside it is *aliased into the drift*. That is a property
of the ritual design, not a bug, and it is reported on every fit.

Nothing here arms anything
--------------------------
Detectors take arrays of numbers. This module opens no device, imports no vendor
SDK, subscribes to nothing and publishes nothing; the byte-level helper for
``wireless_remote`` unpacks a block that was already recorded. It is stdlib-only
apart from ``parcel_robot.capture``, ``parcel_robot.evidence_origin`` and its
sibling ``clockmap``.

Invocation::

    python3 scripts/parcel_capture/syncevents.py --ritual-card   # the operator sheet
    python3 scripts/parcel_capture/syncevents.py --check         # per-channel clock truth
    python3 scripts/parcel_capture/syncevents.py --selftest      # fit a synthetic session
    python3 scripts/parcel_capture/syncevents.py --fit trains.jsonl \
        --reference-channel go2.lowstate --target-channel d455.color ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise
from pathlib import Path
from typing import Any

# Absolute imports plus this bootstrap, following attest.py/rehearse.py: the
# same file has to work as `python -m scripts.parcel_capture.syncevents` in this
# venv and as `python3 scripts/parcel_capture/syncevents.py` from a bare
# checkout on the Orin, where `parcel_robot` is not installed.
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from parcel_robot.capture.channels import (  # after the deploy-path bootstrap
    CHANNELS_BY_ID,
    CaptureError,
    SourceClock,
    SourceDevice,
)
from parcel_robot.evidence_origin import SYNTHETIC_ORIGINS, EvidenceOrigin
from scripts.parcel_capture.clockmap import (
    CONFIDENCE,
    ClockRelation,
    ClockSample,
    ClockSchedule,
    Uncertainty,
    canonical_json,
    fit_relation,
    sample_digest,
    t_critical_95,
)

#: Wire identifiers. A reader that does not know these strings refuses the
#: record rather than guessing at its shape.
SYNC_EVENT_SCHEMA = "parcel.capture.syncevent.v1"
SYNC_TRAIN_SCHEMA = "parcel.capture.synctrain.v1"
SYNC_FIT_SCHEMA = "parcel.capture.syncfit.v1"

_NS_PER_S = 1_000_000_000.0
_NS_PER_MS = 1_000_000

#: ``LowState.tick`` is ``uint32`` milliseconds. Both the modulus and the fact
#: that the counter's zero is wherever the robot's firmware happened to start
#: are load-bearing: differences are meaningful, absolute values are not.
TICK_MODULUS_MS = 1 << 32
TICK_MODULUS_NS = TICK_MODULUS_MS * _NS_PER_MS

#: Largest forward tick step this module will unwrap across without refusing.
#: Derived: ``lowstate`` is nominally 500 Hz (2 ms), so a one-minute step is
#: 30 000 missed messages — already a catastrophic dropout, and beyond it a
#: "small forward step" and "a wrap plus a small forward step" stop being
#: distinguishable. Refused rather than silently unwrapped.
MAX_TICK_FORWARD_JUMP_MS = 60_000

#: The torch-flash pattern, as gaps in seconds. UNEVEN on purpose: see
#: :func:`match_trains`. Changing these numbers changes what the matcher can
#: disambiguate, so they live here and the operator card prints them.
TORCH_FLASH_GAPS_S: tuple[float, ...] = (1.0, 2.0, 1.0, 3.0)
TORCH_FLASH_COUNT = len(TORCH_FLASH_GAPS_S) + 1
TAP_COUNT = 3
TWIST_SECONDS = 10.0

#: Multiplier on the mean detection bracket charged when the two trains disagree
#: on how many events occurred. ENGINEERING ASSUMPTION, labelled as such: a
#: channel that lost k of n ritual events was not healthy during the ritual, and
#: whatever dropped those events (a full buffer, a stalled thread, a USB retry)
#: could equally have delayed the ones it kept. One bracket width per fully-lost
#: train is the smallest penalty that is not zero, and zero is the one value
#: that is certainly wrong.
DROPOUT_PENALTY_FACTOR = 1.0

#: Gap in the matched-event series beyond which a clock step cannot be
#: distinguished from drift. Derived: it is longer than one ritual
#: (:data:`RITUAL_SPAN_NS`), so a gap this size provably contains no events at
#: all, and an offset discontinuity inside it has no evidence of *when*.
STEP_BLIND_GAP_NS = 120_000_000_000

#: Nominal wall-clock length of one ritual performance, from the operator card.
RITUAL_SPAN_NS = 35_000_000_000

#: Cap on events one detector may return from one ritual. A detector that finds
#: 200 "taps" has a wrong threshold, not a long ritual; refused so a broken
#: threshold cannot quietly become a fit.
MAX_EVENTS_PER_TRAIN = 64

#: The sampling design a *ritual* session must achieve, as a
#: :class:`~scripts.parcel_capture.clockmap.ClockSchedule`. Only two constants
#: change from the interrogation default, and both are derivations, not taste:
#:
#: * ``burst_window_ns`` is one ritual performance plus slack, because a ritual
#:   IS the burst.
#: * ``min_burst_samples`` drops to ``MIN_SEGMENT_SAMPLES`` (3): a ritual
#:   delivers between 3 (the tap triplet, all an IMU-only pair shares) and ~16
#:   matched events, not 30, and 3 is the smallest segment that can bound its
#:   own fit.
#: * ``max_cruise_gap_ns`` is deliberately loose: there is **no cruise** in a
#:   ritual design. The inter-ritual gap is reported as a
#:   :class:`BlindInterval` instead, which names the consequence rather than
#:   emitting a shortfall that would fire on every correctly-run session.
RITUAL_SCHEDULE = ClockSchedule(
    burst_window_ns=RITUAL_SPAN_NS + 25_000_000_000,
    min_burst_samples=3,
    max_cruise_gap_ns=6 * 3600 * 1_000_000_000,
    min_span_ns=300_000_000_000,
)

#: ``wireless_remote`` is a 40-byte block inside ``LowState``. The key bitfield's
#: OFFSET inside that block is **UNVERIFIED** — it is transcribed from community
#: descriptions of Go2 EDUs, not from our unit — so it is a named constant a
#: caller must pass explicitly, never a default buried in a signature. PS-D
#: settles it by pressing one button on the bench and diffing the block.
WIRELESS_REMOTE_LENGTH = 40
WIRELESS_REMOTE_KEY_OFFSET_UNVERIFIED = 2

_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")

DEFAULT_SYNC_DOES_NOT_PROVE: tuple[str, ...] = (
    (
        "A sync ritual does not prove any clock is correct. It pins two "
        "channels' timelines to each other at the instants a physical event was "
        "visible in both, and nothing else."
    ),
    (
        "A CONSTANT pipeline latency is indistinguishable from a clock offset. "
        "Sensor exposure, driver buffering and transport delay that are the same "
        "for every event of the ritual are absorbed into the reported offset; the "
        "brackets bound only the part that varies."
    ),
    (
        "Between two bracketing rituals there is NO evidence. A clock step inside "
        "a blind interval is aliased into the fitted drift, and this module "
        "reports the interval rather than pretending to have looked inside it."
    ),
    (
        "`tick` has an arbitrary epoch. The unwrapped counter orders and spaces "
        "lowstate messages; only a ritual gives it a session-relative zero, and "
        "only across the span the rituals bracket."
    ),
    (
        "The matcher's ambiguity test only excludes the alternative alignments "
        "the OBSERVED events permit. A whole train shifted together — a buffer "
        "that flushed late, a driver that batched a ritual — passes every "
        "alignment check this module can run."
    ),
    (
        "This module does not read point clouds. The still-twist-still exists so "
        "the LiDARs record the same motion for the downstream extrinsic tools; "
        "nothing here measures a LiDAR-to-IMU alignment."
    ),
    (
        "A channel that saw NONE of a ritual's events yields no offset for that "
        "ritual. It never yields zero, and the unmatched ritual is carried in the "
        "record rather than dropped."
    ),
)


class SyncRefusalReason(str, Enum):
    """Why a sync record was refused. Every refusal names one of these.

    A typed reason rather than prose because the callers branch on it: an
    ambiguous match is an operator problem at the session (perform the ritual
    again, further from the other events), a malformed series is a broken
    adapter, and a missing host realtime stamp is a PS-B plumbing bug.
    """

    NON_INTEGER_FIELD = "non_integer_field"
    NOT_FINITE = "not_finite"
    NEGATIVE_FIELD = "negative_field"
    EMPTY_FIELD = "empty_field"
    LENGTH_MISMATCH = "length_mismatch"
    NON_MONOTONIC_TIME = "non_monotonic_time"
    THRESHOLD_NOT_ORDERED = "threshold_not_ordered"
    TOO_MANY_EVENTS = "too_many_events"
    TICK_OUT_OF_RANGE = "tick_out_of_range"
    TICK_JUMP = "tick_jump"
    UNKNOWN_CHANNEL = "unknown_channel"
    DEVICE_MISMATCH = "device_mismatch"
    DOMAIN_MISMATCH = "domain_mismatch"
    NOT_MATCHED = "not_matched"
    AMBIGUOUS_MATCH = "ambiguous_match"
    REFERENCE_NOT_HOST = "reference_not_host"
    MISSING_HOST_REALTIME = "missing_host_realtime"
    NO_RITUALS = "no_rituals"
    NO_MATCHED_EVENTS = "no_matched_events"
    ORIGIN_NOT_DECLARED = "origin_not_declared"
    FIXTURE_LABEL_MISSING = "fixture_label_missing"
    FIXTURE_LABEL_FORBIDDEN = "fixture_label_forbidden"
    MALFORMED_TIMESTAMP = "malformed_timestamp"
    MALFORMED_RECORD = "malformed_record"
    SCHEMA_MISMATCH = "schema_mismatch"
    NON_FINITE_RESULT = "non_finite_result"


class SyncError(CaptureError):
    """Base for every refusal raised here.

    Subclasses ``capture.channels.CaptureError`` so one ``except`` in a capture
    process still covers the whole stack, exactly as ``ClockMapError`` does.
    """


class SyncRefusedError(SyncError):
    """A malformed, ambiguous, under-declared or implausible sync record."""

    def __init__(self, reason: SyncRefusalReason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason


# --------------------------------------------------------------------------- #
# Validators. Unknown is absent; malformed is a refusal; nothing defaults.
# --------------------------------------------------------------------------- #


def _require_ns(value: object, *, field: str, allow_zero: bool = True) -> int:
    """Integer nanoseconds or a refusal. NaN, inf, None, bool and float all fail."""

    if isinstance(value, float) and not math.isfinite(value):
        raise SyncRefusedError(
            SyncRefusalReason.NOT_FINITE,
            f"{field} must be a finite integer nanosecond count, got {value!r}",
        )
    if value is None:
        raise SyncRefusedError(
            SyncRefusalReason.NON_INTEGER_FIELD,
            f"{field} must be an int (nanoseconds), got None — an absent time is a "
            f"refusal, never a default",
        )
    if isinstance(value, bool) or not isinstance(value, int):
        raise SyncRefusedError(
            SyncRefusalReason.NON_INTEGER_FIELD,
            f"{field} must be an int (nanoseconds), got {type(value).__name__} "
            f"{value!r} — a float time is never rounded here",
        )
    if value < 0 or (value == 0 and not allow_zero):
        raise SyncRefusedError(
            SyncRefusalReason.NEGATIVE_FIELD,
            f"{field} must be {'non-negative' if allow_zero else 'positive'}, got {value!r}",
        )
    return value


def _require_finite(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SyncRefusedError(
            SyncRefusalReason.NON_INTEGER_FIELD,
            f"{field} must be a number, got {type(value).__name__} {value!r}",
        )
    if not math.isfinite(float(value)):
        raise SyncRefusedError(
            SyncRefusalReason.NOT_FINITE,
            f"{field} must be finite, got {value!r} — a NaN reaching a fit becomes "
            f"a NaN offset, and a NaN offset is not a refusal anyone notices",
        )
    return float(value)


def _require_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SyncRefusedError(
            SyncRefusalReason.EMPTY_FIELD,
            f"{field} must be a non-empty string, got {value!r}",
        )
    return value


def _require_keys(record: object, expected: frozenset[str], *, what: str) -> Mapping[str, Any]:
    """Strict in both directions: a missing key and an unexpected key both refuse."""

    if not isinstance(record, Mapping):
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD,
            f"{what} record must be a mapping, got {type(record).__name__}",
        )
    keys = set(record)
    missing = expected - keys
    unexpected = keys - expected
    if missing or unexpected:
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD,
            f"{what} keys missing={sorted(missing)} unexpected={sorted(unexpected)}",
        )
    return record


def _require_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD,
            f"{field} must be a bool, got {type(value).__name__} {value!r}",
        )
    return value


def _require_series(
    times_ns: Sequence[int],
    values: Sequence[float],
    *,
    what: str,
    realtimes_ns: Sequence[int] | None = None,
) -> tuple[list[int], list[float], list[int] | None]:
    """A time series a detector may be trusted on, or a refusal naming the index.

    Strictly increasing times, not merely sorted: a duplicated stamp means two
    messages claim one instant, and every bracket this module quotes is derived
    from the spacing between stamps. A reordered or duplicated series would
    produce brackets that are too narrow, which is the one direction an
    uncertainty must never be wrong in.
    """

    if not isinstance(times_ns, Sequence) or not isinstance(values, Sequence):
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD, f"{what}: times and values must be sequences"
        )
    if len(times_ns) != len(values):
        raise SyncRefusedError(
            SyncRefusalReason.LENGTH_MISMATCH,
            f"{what}: {len(times_ns)} times against {len(values)} values",
        )
    if not times_ns:
        raise SyncRefusedError(
            SyncRefusalReason.EMPTY_FIELD,
            f"{what}: an empty series is not a channel that saw nothing — it is a "
            f"channel nobody read. Refused rather than reported as zero events",
        )
    times = [_require_ns(value, field=f"{what}.times[{index}]") for index, value in enumerate(times_ns)]
    for index, (earlier, later) in enumerate(pairwise(times)):
        if later <= earlier:
            raise SyncRefusedError(
                SyncRefusalReason.NON_MONOTONIC_TIME,
                f"{what}: times[{index + 1}]={later} does not follow times[{index}]="
                f"{earlier}; sort and de-duplicate before detection, or the event "
                f"brackets are fiction",
            )
    checked = [_require_finite(value, field=f"{what}.values[{index}]") for index, value in enumerate(values)]
    realtimes: list[int] | None = None
    if realtimes_ns is not None:
        if len(realtimes_ns) != len(times):
            raise SyncRefusedError(
                SyncRefusalReason.LENGTH_MISMATCH,
                f"{what}: {len(realtimes_ns)} realtimes against {len(times)} times",
            )
        realtimes = [
            _require_ns(value, field=f"{what}.realtimes[{index}]")
            for index, value in enumerate(realtimes_ns)
        ]
    return times, checked, realtimes


# --------------------------------------------------------------------------- #
# Events and trains
# --------------------------------------------------------------------------- #


class EventKind(str, Enum):
    """Which ritual feature an event is. Only like matches like.

    The matcher never pairs across kinds, which removes most of the alignment
    search space before any ambiguity test runs: a torch flash cannot be
    mistaken for a tap however the clocks are shifted.
    """

    #: A sharp accelerometer-magnitude impulse: the payload taps.
    ACCEL_SPIKE = "accel_spike"
    #: A gyro-magnitude still<->moving transition: the still-twist-still.
    GYRO_ONSET = "gyro_onset"
    #: An image mean-level transition: a torch flash, white or 850 nm.
    BRIGHTNESS_STEP = "brightness_step"
    #: A controller button state change.
    BUTTON_EDGE = "button_edge"


class TimeDomain(str, Enum):
    """Which clock a train's event times are expressed in.

    Carried per train because the three are not interchangeable and mixing them
    is silent: an offset against a wrapping counter is a *pinning* of an
    arbitrary epoch, an offset against a device TimeSpec is a clock comparison,
    and an offset against host receipt includes the transport.
    """

    #: The recording host's monotonic clock at message receipt. This is the
    #: session timeline, and the only domain a ClockSample may be built against.
    HOST_RECEIPT = "host_receipt"
    #: An absolute device time carried in the payload (a ``TimeSpec``).
    DEVICE_TIMESPEC = "device_timespec"
    #: A wrapping counter, already unwrapped by :func:`unwrap_tick_ms`. Its zero
    #: is arbitrary; only differences mean anything until a ritual pins it.
    UNWRAPPED_COUNTER = "unwrapped_counter"


@dataclass(frozen=True, slots=True)
class SyncEvent:
    """One detected instant, in one channel's own time domain, with its bracket.

    :attr:`bracket_ns` is a **half-width**, never optional and never zero: it is
    the interval the physical event provably lies inside given how the channel
    was sampled. A 30 Hz camera locates a flash to ±16.7 ms and a 500 Hz IMU
    locates a tap to ±2 ms, and no amount of averaging changes either.
    """

    kind: EventKind
    #: True for the leading edge (tap onset, dark->bright, still->moving,
    #: released->pressed). Matching pairs edges of the same polarity, because a
    #: flash's rising and falling edges are two different instants.
    rising: bool
    time_ns: int
    bracket_ns: int
    #: Detector-specific magnitude, kept for QA. Never used in a fit — a strong
    #: spike is not a better-timed spike.
    strength: float | None = None
    #: The host wall clock beside the anchor SAMPLE, when the caller supplied a
    #: realtime series. ``None`` is honest absence and costs the pair its
    #: ClockSample bridge, which is the non-permissive outcome.
    host_realtime_ns: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EventKind):
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD,
                f"kind must be an EventKind member, got {type(self.kind).__name__} "
                f"{self.kind!r} — a string is not a declaration",
            )
        _require_bool(self.rising, field="rising")
        _require_ns(self.time_ns, field="time_ns")
        _require_ns(self.bracket_ns, field="bracket_ns", allow_zero=False)
        if self.strength is not None:
            _require_finite(self.strength, field="strength")
        if self.host_realtime_ns is not None:
            _require_ns(self.host_realtime_ns, field="host_realtime_ns")

    @property
    def key(self) -> tuple[str, bool]:
        """What the matcher is allowed to pair this against."""

        return (self.kind.value, self.rising)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SYNC_EVENT_SCHEMA,
            "kind": self.kind.value,
            "rising": self.rising,
            "time_ns": self.time_ns,
            "bracket_ns": self.bracket_ns,
            "strength": self.strength,
            "host_realtime_ns": self.host_realtime_ns,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> SyncEvent:
        _require_keys(record, _EVENT_KEYS, what="sync event")
        if record["schema"] != SYNC_EVENT_SCHEMA:
            raise SyncRefusedError(
                SyncRefusalReason.SCHEMA_MISMATCH,
                f"expected schema {SYNC_EVENT_SCHEMA!r}, got {record['schema']!r}",
            )
        try:
            kind = EventKind(record["kind"])
        except ValueError as exc:
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD, f"undecodable event kind: {exc}"
            ) from exc
        strength = record["strength"]
        return cls(
            kind=kind,
            rising=_require_bool(record["rising"], field="rising"),
            time_ns=record["time_ns"],
            bracket_ns=record["bracket_ns"],
            strength=None if strength is None else _require_finite(strength, field="strength"),
            host_realtime_ns=record["host_realtime_ns"],
        )


_EVENT_KEYS = frozenset(
    {"schema", "kind", "rising", "time_ns", "bracket_ns", "strength", "host_realtime_ns"}
)


@dataclass(frozen=True, slots=True)
class EventTrain:
    """Every event one channel saw during one ritual, in one time domain.

    The channel id is checked against the PS-A/PS-H matrix and the declared
    device and payload clock are checked against that row. Three silent failures
    die here: a train attributed to a channel nobody is recording; a train
    labelled with the wrong device, which would put two robots' clocks in one
    relation; and a train claiming a device TimeSpec on a channel the matrix says
    has no timestamp at all — which is precisely the fiction that made
    ``ClockMapV1`` unpopulatable for the dog.
    """

    channel_id: str
    device: SourceDevice
    domain: TimeDomain
    detector: str
    ritual: str
    events: tuple[SyncEvent, ...]

    def __post_init__(self) -> None:
        _require_text(self.channel_id, field="channel_id")
        _require_text(self.detector, field="detector")
        _require_text(self.ritual, field="ritual")
        channel = CHANNELS_BY_ID.get(self.channel_id)
        if channel is None:
            raise SyncRefusedError(
                SyncRefusalReason.UNKNOWN_CHANNEL,
                f"{self.channel_id!r} is not in the capture matrix. A ritual event "
                f"on a channel nobody is recording is not evidence — add the row "
                f"first (capture/channels.py) so the bag actually carries it",
            )
        if not isinstance(self.device, SourceDevice):
            raise SyncRefusedError(
                SyncRefusalReason.DEVICE_MISMATCH,
                f"device must be a SourceDevice member, got {self.device!r}",
            )
        if channel.device is not self.device:
            raise SyncRefusedError(
                SyncRefusalReason.DEVICE_MISMATCH,
                f"{self.channel_id} is a {channel.device.value} channel, not "
                f"{self.device.value}",
            )
        if not isinstance(self.domain, TimeDomain):
            raise SyncRefusedError(
                SyncRefusalReason.DOMAIN_MISMATCH,
                f"domain must be a TimeDomain member, got {self.domain!r}",
            )
        if self.domain is TimeDomain.DEVICE_TIMESPEC and not channel.source_clock.is_usable_anchor:
            raise SyncRefusedError(
                SyncRefusalReason.DOMAIN_MISMATCH,
                f"{self.channel_id} declares source_clock="
                f"{channel.source_clock.value}: it carries no device time, so a "
                f"train cannot claim DEVICE_TIMESPEC on it. This is the PS-C "
                f"defect, refused at the type level",
            )
        if (
            self.domain is TimeDomain.UNWRAPPED_COUNTER
            and channel.source_clock is not SourceClock.WRAPPING_COUNTER
        ):
            raise SyncRefusedError(
                SyncRefusalReason.DOMAIN_MISMATCH,
                f"{self.channel_id} declares source_clock="
                f"{channel.source_clock.value}, not a wrapping counter",
            )
        if not isinstance(self.events, tuple) or any(
            not isinstance(event, SyncEvent) for event in self.events
        ):
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD,
                f"{self.channel_id}: events must be a tuple of SyncEvent",
            )
        for index, (earlier, later) in enumerate(pairwise(self.events)):
            if later.time_ns < earlier.time_ns:
                raise SyncRefusedError(
                    SyncRefusalReason.NON_MONOTONIC_TIME,
                    f"{self.channel_id}: event {index + 1} precedes event {index}",
                )

    @property
    def kinds(self) -> frozenset[tuple[str, bool]]:
        return frozenset(event.key for event in self.events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SYNC_TRAIN_SCHEMA,
            "channel_id": self.channel_id,
            "device": self.device.value,
            "domain": self.domain.value,
            "detector": self.detector,
            "ritual": self.ritual,
            "events": [event.to_dict() for event in self.events],
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> EventTrain:
        _require_keys(record, _TRAIN_KEYS, what="event train")
        if record["schema"] != SYNC_TRAIN_SCHEMA:
            raise SyncRefusedError(
                SyncRefusalReason.SCHEMA_MISMATCH,
                f"expected schema {SYNC_TRAIN_SCHEMA!r}, got {record['schema']!r}",
            )
        try:
            device = SourceDevice(record["device"])
            domain = TimeDomain(record["domain"])
        except ValueError as exc:
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD, f"undecodable train enum: {exc}"
            ) from exc
        events = record["events"]
        if not isinstance(events, (list, tuple)):
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD, f"events must be a list, got {events!r}"
            )
        return cls(
            channel_id=str(record["channel_id"]),
            device=device,
            domain=domain,
            detector=str(record["detector"]),
            ritual=str(record["ritual"]),
            events=tuple(SyncEvent.from_dict(item) for item in events),
        )


_TRAIN_KEYS = frozenset(
    {"schema", "channel_id", "device", "domain", "detector", "ritual", "events"}
)


def merge_trains(*trains: EventTrain) -> EventTrain:
    """Fold several detectors' output for ONE channel and domain into one train.

    ``lowstate`` carries the taps (accelerometer) and the button
    (``wireless_remote``) in the same messages, and the matcher wants both: a
    richer pattern is a less ambiguous one. The channel, device, domain and
    ritual must agree — merging across any of them would fabricate a train that
    no single stream ever produced.
    """

    if not trains:
        raise SyncRefusedError(SyncRefusalReason.EMPTY_FIELD, "merge_trains needs a train")
    first = trains[0]
    for train in trains[1:]:
        if (train.channel_id, train.device, train.domain, train.ritual) != (
            first.channel_id,
            first.device,
            first.domain,
            first.ritual,
        ):
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD,
                f"cannot merge {train.channel_id}/{train.domain.value}/{train.ritual} "
                f"into {first.channel_id}/{first.domain.value}/{first.ritual}",
            )
    events = sorted(
        (event for train in trains for event in train.events),
        key=lambda event: (event.time_ns, event.kind.value, event.rising),
    )
    return EventTrain(
        channel_id=first.channel_id,
        device=first.device,
        domain=first.domain,
        detector="+".join(dict.fromkeys(train.detector for train in trains)),
        ritual=first.ritual,
        events=tuple(events),
    )


def append_train_jsonl(path: Path | str, train: EventTrain) -> None:
    """Append one train, flushed and fsynced.

    The detected events are the irreplaceable artifact: the fit can always be
    redone, the ritual cannot. One line, forced to the platter, so a power cut
    costs at most the line in flight — ``clockmap.append_sample_jsonl``'s rule.
    """

    line = canonical_json(train.to_dict())
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_trains_jsonl(path: Path | str) -> list[EventTrain]:
    """Read a train log, refusing any malformed line BY NUMBER."""

    trains: list[EventTrain] = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SyncRefusedError(
                    SyncRefusalReason.MALFORMED_RECORD, f"{path}:{number}: not JSON ({exc})"
                ) from exc
            try:
                trains.append(EventTrain.from_dict(record))
            except SyncRefusedError as exc:
                raise SyncRefusedError(exc.reason, f"{path}:{number}: {exc}") from exc
    return trains


# --------------------------------------------------------------------------- #
# The wrapping counter
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class TickUnwrap:
    """An unwrapped ``LowState.tick`` series and what had to be assumed to get it."""

    #: Monotone milliseconds, rebased on the first sample so the arbitrary
    #: firmware epoch is visible as what it is: gone. Differences are preserved
    #: exactly; absolute values were never meaningful.
    elapsed_ms: tuple[int, ...]
    #: Raw first tick, kept so the record can be re-derived and so a second
    #: session's counter is provably a different one.
    first_tick: int
    wrap_count: int
    duplicate_count: int
    #: Always true. Stated as a field so a consumer must read past it.
    epoch_is_arbitrary: bool = True

    @property
    def elapsed_ns(self) -> tuple[int, ...]:
        return tuple(value * _NS_PER_MS for value in self.elapsed_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_tick": self.first_tick,
            "wrap_count": self.wrap_count,
            "duplicate_count": self.duplicate_count,
            "sample_count": len(self.elapsed_ms),
            "span_ms": (self.elapsed_ms[-1] - self.elapsed_ms[0]) if self.elapsed_ms else 0,
            "epoch_is_arbitrary": self.epoch_is_arbitrary,
        }


def unwrap_tick_ms(
    ticks: Sequence[int], *, max_forward_jump_ms: int = MAX_TICK_FORWARD_JUMP_MS
) -> TickUnwrap:
    """Unwrap ``uint32`` millisecond ticks into a monotone elapsed series.

    ``tick`` wraps every ~49.7 days and **starts wherever the firmware last
    left it**, so a session can begin 200 ms before a wrap and cross it in the
    first second. A consumer that differences raw ticks across that boundary
    gets a 49.7-day jump, which a drift fit would happily turn into a slope.

    The rule is one-sided on purpose: a step is read as a wrap only when the
    wrapped difference is small and the raw difference is enormous. A *small*
    backward step is out-of-order delivery, not a wrap, and is refused rather
    than unwrapped into a 49-day advance. A forward step beyond
    ``max_forward_jump_ms`` is refused too, because past it "a long gap" and "a
    wrap plus a gap" are the same observation.
    """

    if not isinstance(ticks, Sequence) or not ticks:
        raise SyncRefusedError(
            SyncRefusalReason.EMPTY_FIELD, "unwrap_tick_ms needs a non-empty tick series"
        )
    if max_forward_jump_ms <= 0 or max_forward_jump_ms >= TICK_MODULUS_MS // 2:
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD,
            f"max_forward_jump_ms must be in (0, {TICK_MODULUS_MS // 2}), got "
            f"{max_forward_jump_ms}",
        )
    checked: list[int] = []
    for index, value in enumerate(ticks):
        if isinstance(value, bool) or not isinstance(value, int):
            raise SyncRefusedError(
                SyncRefusalReason.NON_INTEGER_FIELD,
                f"tick[{index}] must be an int, got {type(value).__name__} {value!r}",
            )
        if not 0 <= value < TICK_MODULUS_MS:
            raise SyncRefusedError(
                SyncRefusalReason.TICK_OUT_OF_RANGE,
                f"tick[{index}]={value} is outside uint32 [0, {TICK_MODULUS_MS}) — the "
                f"adapter is not reading the field the message definition declares",
            )
        checked.append(value)

    absolute = [checked[0]]
    wraps = 0
    duplicates = 0
    for index, (earlier, later) in enumerate(pairwise(checked), start=1):
        forward = (later - earlier) % TICK_MODULUS_MS
        if forward == 0:
            duplicates += 1
        if forward > max_forward_jump_ms:
            raise SyncRefusedError(
                SyncRefusalReason.TICK_JUMP,
                f"tick[{index}]={later} is {forward} ms after tick[{index - 1}]="
                f"{earlier}, past the {max_forward_jump_ms} ms limit. Either the "
                f"channel stalled for longer than a session can tolerate or the "
                f"messages are out of order; both are refusals, because unwrapping "
                f"this would invent a monotone series that never existed",
            )
        if later < earlier:
            wraps += 1
        absolute.append(absolute[-1] + forward)
    base = absolute[0]
    return TickUnwrap(
        elapsed_ms=tuple(value - base for value in absolute),
        first_tick=checked[0],
        wrap_count=wraps,
        duplicate_count=duplicates,
    )


# --------------------------------------------------------------------------- #
# Detectors. Every threshold is the caller's, declared, never inferred.
# --------------------------------------------------------------------------- #


def magnitudes_from_xyz(samples: Sequence[Sequence[float]]) -> list[float]:
    """``|v|`` per sample. Kept here so every detector sees the same definition."""

    out: list[float] = []
    for index, triple in enumerate(samples):
        if not isinstance(triple, Sequence) or len(triple) != 3:
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD,
                f"sample[{index}] must be a 3-sequence, got {triple!r}",
            )
        x, y, z = (_require_finite(value, field=f"sample[{index}][{axis}]")
                   for axis, value in enumerate(triple))
        out.append(math.sqrt(x * x + y * y + z * z))
    return out


def _cap_events(events: Sequence[SyncEvent], *, detector: str, max_events: int) -> tuple[SyncEvent, ...]:
    if len(events) > max_events:
        raise SyncRefusedError(
            SyncRefusalReason.TOO_MANY_EVENTS,
            f"{detector} found {len(events)} events, over the {max_events} cap. A "
            f"ritual has a known event count; this many means the threshold is "
            f"wrong, and a wrong threshold must not become a fit",
        )
    return tuple(events)


def detect_accel_spikes(
    times_ns: Sequence[int],
    magnitudes: Sequence[float],
    *,
    sample_bracket_ns: int,
    min_prominence: float,
    refractory_ns: int,
    mad_multiple: float = 8.0,
    realtimes_ns: Sequence[int] | None = None,
    max_events: int = MAX_EVENTS_PER_TRAIN,
) -> tuple[SyncEvent, ...]:
    """The three sharp taps: local maxima of ``|a|`` above a robust threshold.

    The threshold is ``median + max(min_prominence, mad_multiple * 1.4826 *
    MAD)`` — the caller's absolute floor **and** a robust scatter term, whichever
    is larger. Taking the max is the fail-closed direction: a quiet channel
    cannot lower the bar below the physical prominence the operator declared, and
    a noisy one raises it above.

    ``sample_bracket_ns`` is the caller's, from the channel's sampling period,
    and it is the bracket every event carries. The parabolic refinement below
    moves the *estimate* inside that bracket and never narrows it: an impulse
    sampled at 500 Hz is located to ±1 sample no matter how good the interpolation
    looks, and pretending otherwise would be the one lie an uncertainty must not
    tell.
    """

    times, values, realtimes = _require_series(
        times_ns, magnitudes, what="accel", realtimes_ns=realtimes_ns
    )
    _require_ns(sample_bracket_ns, field="sample_bracket_ns", allow_zero=False)
    _require_ns(refractory_ns, field="refractory_ns")
    _require_finite(min_prominence, field="min_prominence")
    if min_prominence <= 0.0:
        raise SyncRefusedError(
            SyncRefusalReason.THRESHOLD_NOT_ORDERED,
            f"min_prominence must be positive, got {min_prominence!r} — a "
            f"non-positive prominence makes every sample a tap",
        )
    baseline = statistics.median(values)
    mad = statistics.median([abs(value - baseline) for value in values])
    threshold = baseline + max(min_prominence, mad_multiple * 1.4826 * mad)

    peaks: list[int] = []
    for index, value in enumerate(values):
        if value < threshold:
            continue
        before = values[index - 1] if index > 0 else -math.inf
        after = values[index + 1] if index + 1 < len(values) else -math.inf
        if value >= before and value > after:
            peaks.append(index)
    accepted: list[int] = []
    for index in sorted(peaks, key=lambda i: (-values[i], times[i])):
        if all(abs(times[index] - times[other]) > refractory_ns for other in accepted):
            accepted.append(index)
    accepted.sort()

    events: list[SyncEvent] = []
    for index in accepted:
        time_ns = times[index]
        if 0 < index < len(values) - 1:
            y0, y1, y2 = values[index - 1], values[index], values[index + 1]
            denominator = y0 - 2.0 * y1 + y2
            if denominator < 0.0:
                shift = 0.5 * (y0 - y2) / denominator
                shift = max(-0.5, min(0.5, shift))
                period = (times[index + 1] - times[index - 1]) / 2.0
                time_ns = round(times[index] + shift * period)
        events.append(
            SyncEvent(
                kind=EventKind.ACCEL_SPIKE,
                rising=True,
                time_ns=max(time_ns, 0),
                bracket_ns=sample_bracket_ns,
                strength=values[index] - baseline,
                host_realtime_ns=None if realtimes is None else realtimes[index],
            )
        )
    return _cap_events(events, detector="detect_accel_spikes", max_events=max_events)


def detect_gyro_onsets(
    times_ns: Sequence[int],
    magnitudes: Sequence[float],
    *,
    sample_bracket_ns: int,
    still_threshold: float,
    moving_threshold: float,
    min_still_ns: int,
    realtimes_ns: Sequence[int] | None = None,
    max_events: int = MAX_EVENTS_PER_TRAIN,
) -> tuple[SyncEvent, ...]:
    """The still-twist-still: the two edges of a hand rotation, with the RAMP in
    the bracket.

    A hand twist has no sharp edge, so the honest bracket is not the sampling
    period — it is the width of the ambiguity itself: from the last sample still
    below ``still_threshold`` to the first sample above ``moving_threshold``. The
    estimate is the midpoint of that interval and the bracket is its half-width,
    floored at the sampling period. That is why this event is the ritual's
    *coarse* feature and the taps are its fine one; a fit that had only twists
    would report a correspondingly wide interval, which is the correct outcome.

    A return to still is emitted only once it has been **held** for
    ``min_still_ns``. A series that ends mid-twist emits no closing edge rather
    than an unconfirmed one.
    """

    times, values, realtimes = _require_series(
        times_ns, magnitudes, what="gyro", realtimes_ns=realtimes_ns
    )
    _require_ns(sample_bracket_ns, field="sample_bracket_ns", allow_zero=False)
    _require_ns(min_still_ns, field="min_still_ns")
    _require_finite(still_threshold, field="still_threshold")
    _require_finite(moving_threshold, field="moving_threshold")
    if not still_threshold < moving_threshold:
        raise SyncRefusedError(
            SyncRefusalReason.THRESHOLD_NOT_ORDERED,
            f"still_threshold ({still_threshold}) must be strictly below "
            f"moving_threshold ({moving_threshold}); equal thresholds make the "
            f"onset chatter on noise",
        )

    events: list[SyncEvent] = []
    state: str | None = None
    last_confirmed = 0
    still_since: int | None = None
    for index, value in enumerate(values):
        if value <= still_threshold:
            if state is None:
                state, still_since, last_confirmed = "still", times[index], index
                continue
            if state == "moving":
                held = all(
                    values[probe] <= still_threshold
                    for probe in range(index, len(values))
                    if times[probe] - times[index] <= min_still_ns
                )
                reaches_end = times[-1] - times[index] >= min_still_ns
                if held and reaches_end:
                    lo, hi = times[last_confirmed], times[index]
                    events.append(
                        SyncEvent(
                            kind=EventKind.GYRO_ONSET,
                            rising=False,
                            time_ns=(lo + hi) // 2,
                            bracket_ns=max(sample_bracket_ns, math.ceil((hi - lo) / 2) or 1),
                            strength=value,
                            host_realtime_ns=None if realtimes is None else realtimes[index],
                        )
                    )
                    state, still_since = "still", times[index]
            last_confirmed = index
            if state == "still" and still_since is None:
                still_since = times[index]
        elif value >= moving_threshold:
            if state is None:
                state, last_confirmed = "moving", index
                continue
            if state == "still" and still_since is not None and times[index] - still_since >= min_still_ns:
                lo, hi = times[last_confirmed], times[index]
                events.append(
                    SyncEvent(
                        kind=EventKind.GYRO_ONSET,
                        rising=True,
                        time_ns=(lo + hi) // 2,
                        bracket_ns=max(sample_bracket_ns, math.ceil((hi - lo) / 2) or 1),
                        strength=value,
                        host_realtime_ns=None if realtimes is None else realtimes[index],
                    )
                )
                state, still_since = "moving", None
            last_confirmed = index
        # Samples inside the hysteresis band confirm nothing and deliberately do
        # not move `last_confirmed`: that is what widens the bracket over a slow
        # ramp instead of hiding the ramp.
    return _cap_events(events, detector="detect_gyro_onsets", max_events=max_events)


def detect_brightness_steps(
    times_ns: Sequence[int],
    levels: Sequence[float],
    *,
    low_level: float,
    high_level: float,
    realtimes_ns: Sequence[int] | None = None,
    max_events: int = MAX_EVENTS_PER_TRAIN,
) -> tuple[SyncEvent, ...]:
    """The torch flashes: hysteresis edges on a per-frame mean level.

    The bracket falls out of the frame rate with no assumption at all: the
    transition happened after the last frame confirmed on the old side and by the
    first frame confirmed on the new one, so the estimate is their midpoint and
    the bracket is their half-separation. A frame that lands inside the
    hysteresis band confirms nothing and therefore *widens* the bracket, which is
    exactly right — a half-lit frame is evidence the flash happened near it, not
    evidence of when.

    Works unchanged on the D455 colour stream and on either IR stream, which is
    why the ritual uses a torch that emits white **and** 850 nm.
    """

    times, values, realtimes = _require_series(
        times_ns, levels, what="brightness", realtimes_ns=realtimes_ns
    )
    _require_finite(low_level, field="low_level")
    _require_finite(high_level, field="high_level")
    if not low_level < high_level:
        raise SyncRefusedError(
            SyncRefusalReason.THRESHOLD_NOT_ORDERED,
            f"low_level ({low_level}) must be strictly below high_level "
            f"({high_level}); without a band the detector fires on sensor noise",
        )

    events: list[SyncEvent] = []
    state: str | None = None
    last_confirmed = 0
    for index, value in enumerate(values):
        if value <= low_level:
            new_state = "dark"
        elif value >= high_level:
            new_state = "bright"
        else:
            continue
        if state is None:
            state, last_confirmed = new_state, index
            continue
        if new_state != state:
            lo, hi = times[last_confirmed], times[index]
            events.append(
                SyncEvent(
                    kind=EventKind.BRIGHTNESS_STEP,
                    rising=new_state == "bright",
                    time_ns=(lo + hi) // 2,
                    bracket_ns=max(math.ceil((hi - lo) / 2), 1),
                    strength=value,
                    host_realtime_ns=None if realtimes is None else realtimes[index],
                )
            )
            state = new_state
        last_confirmed = index
    return _cap_events(events, detector="detect_brightness_steps", max_events=max_events)


def detect_button_edges(
    times_ns: Sequence[int],
    pressed: Sequence[bool],
    *,
    min_hold_ns: int,
    realtimes_ns: Sequence[int] | None = None,
    max_events: int = MAX_EVENTS_PER_TRAIN,
) -> tuple[SyncEvent, ...]:
    """The controller press: state edges, debounced by a required hold time.

    An edge counts only once the new state has been **held** for ``min_hold_ns``.
    Contact bounce is a burst of edges microseconds apart and would otherwise
    produce a train of phantom events that the matcher would then have to
    disambiguate. An edge whose hold cannot be confirmed before the series ends
    is not emitted — fail closed; a press at the very end of a ritual is lost
    rather than reported at an unverified instant.

    The same detector runs on the 500 Hz ``wireless_remote[40]`` copy inside
    ``lowstate`` and on the event-driven ``wirelesscontroller`` topic, and the
    disagreement between the two is the only measurement of per-topic transport
    delay this session can make.
    """

    if not isinstance(pressed, Sequence) or not pressed:
        raise SyncRefusedError(
            SyncRefusalReason.EMPTY_FIELD, "button: an empty state series is a refusal"
        )
    for index, value in enumerate(pressed):
        if not isinstance(value, bool):
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD,
                f"button.pressed[{index}] must be a bool, got "
                f"{type(value).__name__} {value!r} — an int is not a button state",
            )
    times, _, realtimes = _require_series(
        times_ns,
        [1.0 if value else 0.0 for value in pressed],
        what="button",
        realtimes_ns=realtimes_ns,
    )
    _require_ns(min_hold_ns, field="min_hold_ns")

    events: list[SyncEvent] = []
    for index in range(1, len(times)):
        if pressed[index] == pressed[index - 1]:
            continue
        held = all(
            pressed[probe] == pressed[index]
            for probe in range(index, len(times))
            if times[probe] - times[index] <= min_hold_ns
        )
        if not held or times[-1] - times[index] < min_hold_ns:
            continue
        lo, hi = times[index - 1], times[index]
        events.append(
            SyncEvent(
                kind=EventKind.BUTTON_EDGE,
                rising=pressed[index],
                time_ns=(lo + hi) // 2,
                bracket_ns=max(math.ceil((hi - lo) / 2), 1),
                strength=None,
                host_realtime_ns=None if realtimes is None else realtimes[index],
            )
        )
    return _cap_events(events, detector="detect_button_edges", max_events=max_events)


def wireless_remote_keys(block: bytes, *, key_offset: int) -> int:
    """The little-endian ``uint16`` key bitfield out of a 40-byte remote block.

    ``key_offset`` has **no default**: the layout of this block is transcribed
    from community descriptions of Go2 EDUs and is UNVERIFIED against our unit
    (:data:`WIRELESS_REMOTE_KEY_OFFSET_UNVERIFIED` records the candidate). PS-D
    settles it on the bench by pressing one button and diffing the block, and
    until then a caller that wants the bits has to say which bytes it believes
    they are in.
    """

    if not isinstance(block, (bytes, bytearray)):
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD,
            f"wireless_remote block must be bytes, got {type(block).__name__}",
        )
    if len(block) != WIRELESS_REMOTE_LENGTH:
        raise SyncRefusedError(
            SyncRefusalReason.LENGTH_MISMATCH,
            f"wireless_remote block must be {WIRELESS_REMOTE_LENGTH} bytes, got "
            f"{len(block)} — a short block means the adapter sliced the wrong field",
        )
    if not 0 <= key_offset <= WIRELESS_REMOTE_LENGTH - 2:
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD,
            f"key_offset {key_offset} does not leave two bytes inside the block",
        )
    return int.from_bytes(bytes(block[key_offset : key_offset + 2]), "little")


def button_series_from_wireless_remote(
    blocks: Sequence[bytes], *, mask: int, key_offset: int
) -> list[bool]:
    """One button's pressed/released series out of a run of remote blocks."""

    if not isinstance(mask, int) or isinstance(mask, bool) or mask <= 0:
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD,
            f"mask must be a positive int bitmask, got {mask!r}",
        )
    return [bool(wireless_remote_keys(block, key_offset=key_offset) & mask) for block in blocks]


# --------------------------------------------------------------------------- #
# Matching two event trains
# --------------------------------------------------------------------------- #


class MatchStatus(str, Enum):
    """The four outcomes of trying to align two trains. Three of them are UNKNOWN.

    There is no fifth outcome that quietly returns zero, because the whole point
    of this module is that "we could not tell" and "they were aligned" are
    different answers and only one of them is ever a measurement.
    """

    MATCHED = "matched"
    #: One of the trains is empty: nothing to align. Not a zero offset.
    NO_EVENTS = "no_events"
    #: Both trains have events but no alignment pairs any of them.
    NO_MATCH = "no_match"
    #: A well-separated alternative alignment fits at least as well. Refused
    #: rather than guessed — an aliased offset is worse than no offset, because
    #: it is wrong by a whole pattern interval and looks confident.
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class TrainMatch:
    """The alignment between two trains, or the typed reason there isn't one."""

    reference_channel: str
    target_channel: str
    ritual: str
    status: MatchStatus
    #: ``target_time - reference_time``: ONE sign convention, the same one
    #: ``ClockSample.offset_ns`` uses, so positive always means the target clock
    #: is ahead. ``None`` for every non-MATCHED status.
    offset_ns: int | None
    #: ``(reference_index, target_index)`` pairs, in reference order.
    pairs: tuple[tuple[int, int], ...]
    reference_count: int
    target_count: int
    comparable_count: int
    runner_up_offset_ns: int | None
    runner_up_matched: int
    #: True when the events cannot exclude an alternative alignment at all —
    #: too few events for a second alignment to even be tested. The offset is
    #: then bounded only by the caller's prior, and that is said out loud.
    ambiguity_bounded_by_prior: bool
    detail: str

    @property
    def matched_count(self) -> int:
        return len(self.pairs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_channel": self.reference_channel,
            "target_channel": self.target_channel,
            "ritual": self.ritual,
            "status": self.status.value,
            "offset_ns": self.offset_ns,
            "pairs": [list(pair) for pair in self.pairs],
            "reference_count": self.reference_count,
            "target_count": self.target_count,
            "comparable_count": self.comparable_count,
            "runner_up_offset_ns": self.runner_up_offset_ns,
            "runner_up_matched": self.runner_up_matched,
            "ambiguity_bounded_by_prior": self.ambiguity_bounded_by_prior,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> TrainMatch:
        _require_keys(record, _MATCH_KEYS, what="train match")
        try:
            status = MatchStatus(record["status"])
        except ValueError as exc:
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD, f"undecodable match status: {exc}"
            ) from exc
        return cls(
            reference_channel=str(record["reference_channel"]),
            target_channel=str(record["target_channel"]),
            ritual=str(record["ritual"]),
            status=status,
            offset_ns=record["offset_ns"],
            pairs=tuple((int(a), int(b)) for a, b in record["pairs"]),
            reference_count=int(record["reference_count"]),
            target_count=int(record["target_count"]),
            comparable_count=int(record["comparable_count"]),
            runner_up_offset_ns=record["runner_up_offset_ns"],
            runner_up_matched=int(record["runner_up_matched"]),
            ambiguity_bounded_by_prior=_require_bool(
                record["ambiguity_bounded_by_prior"], field="ambiguity_bounded_by_prior"
            ),
            detail=str(record["detail"]),
        )


_MATCH_KEYS = frozenset(
    {
        "reference_channel",
        "target_channel",
        "ritual",
        "status",
        "offset_ns",
        "pairs",
        "reference_count",
        "target_count",
        "comparable_count",
        "runner_up_offset_ns",
        "runner_up_matched",
        "ambiguity_bounded_by_prior",
        "detail",
    }
)


def _greedy_pairs(
    reference: Sequence[SyncEvent],
    target: Sequence[SyncEvent],
    candidates: Sequence[tuple[int, int]],
    offset: int,
    extra_tolerance_ns: int,
) -> tuple[tuple[tuple[int, int], ...], float]:
    """One-to-one nearest-residual matching at a fixed offset.

    Greedy on |residual| rather than optimal assignment: with an event train the
    two differ only when two events are closer together than their own brackets,
    and a ritual whose events are that close is one the operator has to redo —
    the ambiguity test below catches it instead of an assignment solver hiding it.
    """

    scored: list[tuple[float, int, int]] = []
    for i, j in candidates:
        residual = abs(target[j].time_ns - reference[i].time_ns - offset)
        window = reference[i].bracket_ns + target[j].bracket_ns + extra_tolerance_ns
        if residual <= window:
            scored.append((residual, i, j))
    scored.sort()
    used_reference: set[int] = set()
    used_target: set[int] = set()
    pairs: list[tuple[int, int]] = []
    cost = 0.0
    for residual, i, j in scored:
        if i in used_reference or j in used_target:
            continue
        used_reference.add(i)
        used_target.add(j)
        pairs.append((i, j))
        cost += residual * residual
    pairs.sort()
    return tuple(pairs), cost


def match_trains(
    reference: EventTrain,
    target: EventTrain,
    *,
    extra_tolerance_ns: int = 0,
    max_skew_ns: int | None = None,
) -> TrainMatch:
    """Align two trains by their event pattern, or say which kind of no.

    Every candidate offset is a difference between one reference event and one
    same-kind target event — the alignment is *of the pattern*, so nothing here
    assumes the two clocks are anywhere near each other, which matters because
    ``lowstate.tick`` starts at an arbitrary value that can be weeks away from
    the host clock. The best alignment is the one matching the most events, ties
    broken by squared residual.

    **Ambiguity is a refusal, not a tie-break.** The best alignment is compared
    against the best *well-separated* alternative; if the alternative matches as
    many events, the status is :attr:`MatchStatus.AMBIGUOUS` and there is no
    offset. This is what the uneven flash gaps (1, 2, 1, 3 s) are for: an evenly
    spaced train aliases onto itself under a one-interval shift and cannot be
    resolved from the events alone, and this module would rather report that than
    be confidently one second wrong.
    """

    if reference.ritual != target.ritual:
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD,
            f"trains are from different rituals: {reference.ritual!r} vs "
            f"{target.ritual!r} — matching across rituals would fold the drift "
            f"between them into the offset",
        )
    if reference.channel_id == target.channel_id and reference.domain is target.domain:
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD,
            f"{reference.channel_id}: a train cannot be matched against itself in "
            f"the same time domain",
        )
    _require_ns(extra_tolerance_ns, field="extra_tolerance_ns")
    if max_skew_ns is not None:
        _require_ns(max_skew_ns, field="max_skew_ns", allow_zero=False)

    shared = reference.kinds & target.kinds
    ref_events = reference.events
    tgt_events = target.events
    comparable_reference = [index for index, event in enumerate(ref_events) if event.key in shared]
    comparable_target = [index for index, event in enumerate(tgt_events) if event.key in shared]
    comparable = max(len(comparable_reference), len(comparable_target))

    def _blank(status: MatchStatus, detail: str) -> TrainMatch:
        return TrainMatch(
            reference_channel=reference.channel_id,
            target_channel=target.channel_id,
            ritual=reference.ritual,
            status=status,
            offset_ns=None,
            pairs=(),
            reference_count=len(ref_events),
            target_count=len(tgt_events),
            comparable_count=comparable,
            runner_up_offset_ns=None,
            runner_up_matched=0,
            ambiguity_bounded_by_prior=False,
            detail=detail,
        )

    if not ref_events or not tgt_events:
        return _blank(
            MatchStatus.NO_EVENTS,
            f"{reference.channel_id} has {len(ref_events)} events and "
            f"{target.channel_id} has {len(tgt_events)}: no alignment exists, and "
            f"the offset is UNKNOWN — not zero",
        )
    if not shared:
        return _blank(
            MatchStatus.NO_MATCH,
            f"no event kind is present in both trains ({sorted(reference.kinds)} vs "
            f"{sorted(target.kinds)}): the two channels saw different halves of the "
            f"ritual and cannot be aligned to each other",
        )

    pair_candidates = [
        (i, j)
        for i in comparable_reference
        for j in comparable_target
        if ref_events[i].key == tgt_events[j].key
    ]
    offsets: list[int] = []
    for i, j in pair_candidates:
        offset = tgt_events[j].time_ns - ref_events[i].time_ns
        if max_skew_ns is None or abs(offset) <= max_skew_ns:
            offsets.append(offset)
    if not offsets:
        return _blank(
            MatchStatus.NO_MATCH,
            f"no candidate offset survives the {max_skew_ns} ns skew prior",
        )

    scores: dict[int, tuple[int, float, tuple[tuple[int, int], ...]]] = {}
    for offset in sorted(set(offsets)):
        pairs, cost = _greedy_pairs(ref_events, tgt_events, pair_candidates, offset, extra_tolerance_ns)
        scores[offset] = (len(pairs), cost, pairs)
    best_offset = min(scores, key=lambda o: (-scores[o][0], scores[o][1], abs(o)))
    best_count, _, best_pairs = scores[best_offset]
    if best_count == 0:
        return _blank(
            MatchStatus.NO_MATCH,
            "no alignment pairs a single event within the two channels' brackets",
        )

    # One refinement pass: the mean residual of the matched pairs is a better
    # centre than whichever single pair generated the candidate.
    refined = round(statistics.fmean(
        tgt_events[j].time_ns - ref_events[i].time_ns for i, j in best_pairs
    ))
    refined_pairs, refined_cost = _greedy_pairs(
        ref_events, tgt_events, pair_candidates, refined, extra_tolerance_ns
    )
    if (len(refined_pairs), -refined_cost) >= (best_count, -scores[best_offset][1]):
        best_offset, best_pairs, best_count = refined, refined_pairs, len(refined_pairs)
        scores[refined] = (len(refined_pairs), refined_cost, refined_pairs)

    separation = 2 * max(
        ref_events[i].bracket_ns + tgt_events[j].bracket_ns + extra_tolerance_ns
        for i, j in pair_candidates
    )
    rivals = [
        (count, offset)
        for offset, (count, _, _) in scores.items()
        if abs(offset - best_offset) > separation
    ]
    if not rivals:
        return TrainMatch(
            reference_channel=reference.channel_id,
            target_channel=target.channel_id,
            ritual=reference.ritual,
            status=MatchStatus.MATCHED,
            offset_ns=best_offset,
            pairs=best_pairs,
            reference_count=len(ref_events),
            target_count=len(tgt_events),
            comparable_count=comparable,
            runner_up_offset_ns=None,
            runner_up_matched=0,
            ambiguity_bounded_by_prior=True,
            detail=(
                f"matched {best_count}/{comparable}; too few events for a separated "
                f"alternative alignment to be tested, so the offset is unique only "
                f"within the caller's skew prior"
            ),
        )
    runner_up_count, runner_up_offset = max(rivals)
    if runner_up_count >= best_count:
        return _blank(
            MatchStatus.AMBIGUOUS,
            f"alignment at {best_offset} ns matches {best_count} events and a "
            f"separated alternative at {runner_up_offset} ns matches "
            f"{runner_up_count}: the event pattern does not distinguish them. "
            f"Redo the ritual with the uneven flash gaps "
            f"{TORCH_FLASH_GAPS_S} — an evenly spaced train aliases onto itself",
        )
    return TrainMatch(
        reference_channel=reference.channel_id,
        target_channel=target.channel_id,
        ritual=reference.ritual,
        status=MatchStatus.MATCHED,
        offset_ns=best_offset,
        pairs=best_pairs,
        reference_count=len(ref_events),
        target_count=len(tgt_events),
        comparable_count=comparable,
        runner_up_offset_ns=runner_up_offset,
        runner_up_matched=runner_up_count,
        ambiguity_bounded_by_prior=False,
        detail=(
            f"matched {best_count}/{comparable}; best separated alternative matches "
            f"{runner_up_count}"
        ),
    )


# --------------------------------------------------------------------------- #
# One ritual's offset for one channel pair
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PairOffset:
    """One ritual, one channel pair: the offset, quoted at an instant, bounded."""

    ritual: str
    reference_channel: str
    target_channel: str
    #: Reference-domain instant the offset is quoted at: the mean of the matched
    #: reference-event times, which is where a mean estimator's variance is
    #: smallest and where the bracket bound collapses to the mean bracket.
    epoch_ns: int
    offset_ns: int
    uncertainty: Uncertainty
    matched_count: int
    expected_count: int
    residual_rms_ns: float | None
    dropout_penalty_ns: float
    caveats: tuple[str, ...]

    @property
    def is_bounded(self) -> bool:
        return self.uncertainty.is_bounded

    def to_dict(self) -> dict[str, Any]:
        return {
            "ritual": self.ritual,
            "reference_channel": self.reference_channel,
            "target_channel": self.target_channel,
            "epoch_ns": self.epoch_ns,
            "offset_ns": self.offset_ns,
            "uncertainty": self.uncertainty.to_dict(),
            "matched_count": self.matched_count,
            "expected_count": self.expected_count,
            "residual_rms_ns": self.residual_rms_ns,
            "dropout_penalty_ns": self.dropout_penalty_ns,
            "caveats": list(self.caveats),
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> PairOffset:
        _require_keys(record, _PAIR_OFFSET_KEYS, what="pair offset")
        caveats = record["caveats"]
        if not isinstance(caveats, (list, tuple)):
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD, f"caveats must be a list, got {caveats!r}"
            )
        residual = record["residual_rms_ns"]
        return cls(
            ritual=str(record["ritual"]),
            reference_channel=str(record["reference_channel"]),
            target_channel=str(record["target_channel"]),
            epoch_ns=_require_ns(record["epoch_ns"], field="epoch_ns"),
            offset_ns=int(record["offset_ns"]),
            uncertainty=Uncertainty.from_dict(record["uncertainty"]),
            matched_count=_require_ns(record["matched_count"], field="matched_count"),
            expected_count=_require_ns(record["expected_count"], field="expected_count"),
            residual_rms_ns=(
                None if residual is None else _require_finite(residual, field="residual_rms_ns")
            ),
            dropout_penalty_ns=_require_finite(
                record["dropout_penalty_ns"], field="dropout_penalty_ns"
            ),
            caveats=tuple(str(item) for item in caveats),
        )


_PAIR_OFFSET_KEYS = frozenset(
    {
        "ritual",
        "reference_channel",
        "target_channel",
        "epoch_ns",
        "offset_ns",
        "uncertainty",
        "matched_count",
        "expected_count",
        "residual_rms_ns",
        "dropout_penalty_ns",
        "caveats",
    }
)


def estimate_pair_offset(
    match: TrainMatch,
    reference: EventTrain,
    target: EventTrain,
    *,
    expected_count: int | None = None,
) -> PairOffset:
    """Turn a matched train pair into an offset with a two-part uncertainty.

    ``systematic`` is ``mean(reference bracket) + mean(target bracket) +
    dropout penalty``. None of it shrinks with ``n``: the brackets are a
    quantisation bound and a fixed pipeline latency biases every event of the
    ritual identically, so averaging a thousand taps removes none of it. This is
    ``clockmap``'s round-trip-bracket argument in its passive form.

    ``statistical`` is the Student-t 95% interval on the mean of the matched
    residuals, which *does* shrink like ``1/sqrt(n)`` — so a modality that
    matched 3 of 5 flashes reports a strictly wider interval than one that
    matched all 5, twice over: fewer samples and a dropout penalty.

    ``n == 1`` leaves ``statistical`` at ``None`` and the whole interval
    unbounded, because a single event has no scatter to bound it.
    """

    if match.status is not MatchStatus.MATCHED or match.offset_ns is None:
        raise SyncRefusedError(
            SyncRefusalReason.NOT_MATCHED,
            f"{match.ritual}/{match.target_channel}: status is "
            f"{match.status.value} — there is no offset to estimate, and UNKNOWN "
            f"must not be turned into a number here",
        )
    if match.reference_channel != reference.channel_id or match.target_channel != target.channel_id:
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD,
            "the match does not describe these two trains",
        )
    residuals = [
        float(target.events[j].time_ns - reference.events[i].time_ns) for i, j in match.pairs
    ]
    count = len(residuals)
    centre = statistics.fmean(residuals)
    epoch = round(statistics.fmean(reference.events[i].time_ns for i, _ in match.pairs))
    reference_bracket = statistics.fmean(reference.events[i].bracket_ns for i, _ in match.pairs)
    target_bracket = statistics.fmean(target.events[j].bracket_ns for _, j in match.pairs)

    expected = match.comparable_count if expected_count is None else expected_count
    _require_ns(expected, field="expected_count", allow_zero=False)
    expected = max(expected, count)
    lost = expected - count
    penalty = (
        DROPOUT_PENALTY_FACTOR * (lost / expected) * (reference_bracket + target_bracket)
        if lost
        else 0.0
    )

    statistical: float | None = None
    residual_rms: float | None = None
    if count >= 2:
        spread = statistics.stdev(residuals)
        statistical = t_critical_95(count - 1) * spread / math.sqrt(count)
        residual_rms = math.sqrt(statistics.fmean((value - centre) ** 2 for value in residuals))

    caveats: list[str] = []
    if lost:
        caveats.append(
            f"{lost} of {expected} comparable events were not matched; the "
            f"systematic term carries a {penalty / 1e6:.3f} ms dropout penalty "
            f"because a channel that lost events was not healthy during the ritual"
        )
    if count == 1:
        caveats.append(
            "a single matched event has no scatter: the statistical term is "
            "UNKNOWN and the offset is not bounded"
        )
    if match.ambiguity_bounded_by_prior:
        caveats.append(
            "too few events to test a separated alternative alignment: uniqueness "
            "rests on the caller's skew prior, not on the evidence"
        )
    if reference.domain is TimeDomain.UNWRAPPED_COUNTER or target.domain is TimeDomain.UNWRAPPED_COUNTER:
        caveats.append(
            "one side is a wrapping counter with an arbitrary epoch: this offset "
            "PINS that epoch and is not a comparison of two absolute clocks"
        )

    for value, field in ((centre, "offset"), (penalty, "dropout penalty")):
        if not math.isfinite(value):
            raise SyncRefusedError(
                SyncRefusalReason.NON_FINITE_RESULT, f"non-finite {field}: {value!r}"
            )
    return PairOffset(
        ritual=match.ritual,
        reference_channel=reference.channel_id,
        target_channel=target.channel_id,
        epoch_ns=epoch,
        offset_ns=round(centre),
        uncertainty=Uncertainty(
            unit="ns",
            systematic=reference_bracket + target_bracket + penalty,
            statistical=statistical,
        ),
        matched_count=count,
        expected_count=expected,
        residual_rms_ns=residual_rms,
        dropout_penalty_ns=penalty,
        caveats=tuple(caveats),
    )


# --------------------------------------------------------------------------- #
# The bridge into ClockSample
# --------------------------------------------------------------------------- #


def pair_clock_samples(
    match: TrainMatch,
    reference: EventTrain,
    target: EventTrain,
    *,
    host_pair_bracket_ns: int | None,
    dropout_penalty_ns: float = 0.0,
) -> list[ClockSample]:
    """One matched event pair -> one :class:`ClockSample`. This is the whole fix.

    ``ClockSample``'s algebra never needed an interrogation, only a bracketed
    correspondence: give it the earliest host instant the device stamp could
    belong to and the width of that bracket, and ``offset = device - host_mid``
    with ``±round_trip/2`` comes out right. So::

        round_trip_ns      = 2 * (ref_bracket + tgt_bracket + dropout_penalty)
        host_monotonic_ns  = reference_event - (that half-width)
        device_source_ns   = target_event
        => host_mid_ns = reference_event, offset_ns = target - reference

    The reference train **must** be in :attr:`TimeDomain.HOST_RECEIPT`: the
    resulting relation is ``DEVICE_TO_HOST_MONOTONIC`` and building it against a
    device-domain reference would put a lie in the enum. Cross-device offsets are
    obtained by composing two host-anchored relations, which is also the only
    form that can be placed in wall time.

    ``host_pair_bracket_ns`` has no default. It is the width of the host's own
    monotonic/realtime read, and inventing one would fabricate the confidence of
    the wall-clock half of the map.
    """

    if match.status is not MatchStatus.MATCHED:
        raise SyncRefusedError(
            SyncRefusalReason.NOT_MATCHED,
            f"{match.ritual}/{match.target_channel}: {match.status.value} — no "
            f"samples are produced from an unmatched ritual",
        )
    if reference.domain is not TimeDomain.HOST_RECEIPT:
        raise SyncRefusedError(
            SyncRefusalReason.REFERENCE_NOT_HOST,
            f"the reference train is in the {reference.domain.value} domain. A "
            f"ClockSample relates a device clock to the HOST monotonic clock; "
            f"anchor to a host-receipt train and compose if you want a "
            f"device-to-device offset",
        )
    if target.domain is TimeDomain.HOST_RECEIPT:
        raise SyncRefusedError(
            SyncRefusalReason.DOMAIN_MISMATCH,
            f"{target.channel_id} is also in the host-receipt domain: the offset "
            f"between two host-stamped channels is a TRANSPORT DELAY, not a clock "
            f"relation, and calling it device-to-host would put a lie in the enum. "
            f"estimate_pair_offset still measures it — that pairing is exactly how "
            f"the wireless_remote/wirelesscontroller cross-check works",
        )
    if host_pair_bracket_ns is not None:
        _require_ns(host_pair_bracket_ns, field="host_pair_bracket_ns")
    penalty = math.ceil(_require_finite(dropout_penalty_ns, field="dropout_penalty_ns"))
    if penalty < 0:
        raise SyncRefusedError(
            SyncRefusalReason.NEGATIVE_FIELD, "dropout_penalty_ns must be non-negative"
        )

    samples: list[ClockSample] = []
    for i, j in match.pairs:
        ref_event = reference.events[i]
        tgt_event = target.events[j]
        if ref_event.host_realtime_ns is None:
            raise SyncRefusedError(
                SyncRefusalReason.MISSING_HOST_REALTIME,
                f"{reference.channel_id} event {i} carries no host_realtime_ns. "
                f"Every CaptureEnvelope stamps one; pass the realtime series into "
                f"the detector. Without it this session cannot be placed in wall "
                f"time, and that is not recoverable afterwards",
            )
        half = ref_event.bracket_ns + tgt_event.bracket_ns + penalty
        host_monotonic = ref_event.time_ns - half
        if host_monotonic < 0:
            raise SyncRefusedError(
                SyncRefusalReason.NEGATIVE_FIELD,
                f"{reference.channel_id} event {i} at {ref_event.time_ns} ns is "
                f"closer to the monotonic origin than its own {half} ns bracket",
            )
        samples.append(
            ClockSample(
                device=target.device,
                host_monotonic_ns=host_monotonic,
                host_realtime_ns=ref_event.host_realtime_ns,
                device_source_ns=tgt_event.time_ns,
                round_trip_ns=2 * half,
                host_pair_bracket_ns=host_pair_bracket_ns,
            )
        )
    return samples


# --------------------------------------------------------------------------- #
# The bracketed fit
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class BlindInterval:
    """A stretch with no matched events, where a step cannot be told from drift.

    First-class output, not a footnote. A bracketed ritual design ALWAYS has one
    of these — the whole session between the two rituals — and a reader who does
    not know that will read the fitted drift as if it were watched the whole way.
    """

    start_host_monotonic_ns: int
    end_host_monotonic_ns: int

    @property
    def duration_ns(self) -> int:
        return self.end_host_monotonic_ns - self.start_host_monotonic_ns

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_host_monotonic_ns": self.start_host_monotonic_ns,
            "end_host_monotonic_ns": self.end_host_monotonic_ns,
            "duration_ns": self.duration_ns,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> BlindInterval:
        _require_keys(record, _BLIND_KEYS, what="blind interval")
        built = cls(
            start_host_monotonic_ns=_require_ns(
                record["start_host_monotonic_ns"], field="start_host_monotonic_ns"
            ),
            end_host_monotonic_ns=_require_ns(
                record["end_host_monotonic_ns"], field="end_host_monotonic_ns"
            ),
        )
        if int(record["duration_ns"]) != built.duration_ns:
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD,
                f"duration_ns {record['duration_ns']!r} is not the interval's own width",
            )
        return built


_BLIND_KEYS = frozenset(
    {"start_host_monotonic_ns", "end_host_monotonic_ns", "duration_ns"}
)


@dataclass(frozen=True, slots=True)
class SyncStep:
    """A clock discontinuity between two rituals, tested under a COMMON drift.

    Not the same test as ``clockmap``'s segment scan, and PS-I measured why that
    one cannot be used here: with the evidence in two 8 s bursts an hour apart,
    a segment covering one burst has a slope determined by 8 s of data, and
    extrapolating it to the burst boundary carries ±1304 ms — a real 500 ms step
    cannot clear that, while unconstrained extrapolated lines cross often enough
    to declare steps that never happened.

    The model here says what a clock step actually is: **the offset jumps, the
    rate does not**. One drift for the whole session, one extra intercept from
    the break onward, fitted by weighted least squares over the per-ritual
    offsets with their own uncertainties as the weights. That assumption is
    declared, not hidden: a clock whose RATE changed at the same instant is
    reported here as a step of the wrong size.
    """

    magnitude_ns: int
    uncertainty_ns: float
    before_ritual: str
    #: ``None`` when the step is real but its gap is not identifiable — which is
    #: the honest verdict at exactly three rituals, where "a +S step in the
    #: second gap" and "a -S step in the first gap at a different drift" fit the
    #: three offsets equally well.
    after_ritual: str | None
    localizable: bool
    gap_ns: int | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "magnitude_ns": self.magnitude_ns,
            "uncertainty_ns": self.uncertainty_ns,
            "before_ritual": self.before_ritual,
            "after_ritual": self.after_ritual,
            "localizable": self.localizable,
            "gap_ns": self.gap_ns,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> SyncStep:
        _require_keys(record, _SYNC_STEP_KEYS, what="sync step")
        return cls(
            magnitude_ns=int(record["magnitude_ns"]),
            uncertainty_ns=_require_finite(record["uncertainty_ns"], field="uncertainty_ns"),
            before_ritual=str(record["before_ritual"]),
            after_ritual=(
                None if record["after_ritual"] is None else str(record["after_ritual"])
            ),
            localizable=_require_bool(record["localizable"], field="localizable"),
            gap_ns=None if record["gap_ns"] is None else _require_ns(
                record["gap_ns"], field="gap_ns"
            ),
            detail=str(record["detail"]),
        )


_SYNC_STEP_KEYS = frozenset(
    {
        "magnitude_ns",
        "uncertainty_ns",
        "before_ritual",
        "after_ritual",
        "localizable",
        "gap_ns",
        "detail",
    }
)


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting on a small dense system.

    Three parameters at most, so a dependency for this would be absurd; a
    singular system returns ``None`` and the caller reports "not testable"
    rather than dividing by a pivot it did not check.
    """

    size = len(rhs)
    augmented = [row[:] + [rhs[index]] for index, row in enumerate(matrix)]
    # RELATIVE singularity test. An absolute floor is a scaling bug waiting to
    # happen: these weights are 1/uncertainty^2 in nanoseconds, i.e. ~1e-13, and
    # an absolute 1e-12 pivot floor declared every well-posed system singular.
    scale = max((abs(value) for row in matrix for value in row), default=0.0)
    floor = 1e-12 * scale if scale > 0.0 else 0.0
    for column in range(size):
        pivot_row = max(range(column, size), key=lambda r: abs(augmented[r][column]))
        if abs(augmented[pivot_row][column]) <= floor:
            return None
        augmented[column], augmented[pivot_row] = augmented[pivot_row], augmented[column]
        pivot = augmented[column][column]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column] / pivot
            for col in range(column, size + 1):
                augmented[row][col] -= factor * augmented[column][col]
    return [augmented[index][size] / augmented[index][index] for index in range(size)]


def _weighted_fit(
    epochs_s: Sequence[float],
    values_ns: Sequence[float],
    weights: Sequence[float],
    break_index: int | None,
) -> tuple[list[float], float, float] | None:
    """WLS for ``offset = a + drift*t (+ step from break_index on)``.

    Returns ``(parameters, weighted RSS, variance of the step term)``. The step
    variance comes from the parameter covariance ``(X'WX)^-1``, i.e. from the
    per-ritual uncertainties themselves, NOT from the residual scatter: with
    three rituals the model fits exactly and residual-scaled errors would be
    zero, which would claim certainty the three points cannot deliver.
    """

    columns = 3 if break_index is not None else 2
    rows: list[list[float]] = []
    for index, epoch in enumerate(epochs_s):
        row = [1.0, epoch]
        if break_index is not None:
            row.append(1.0 if index >= break_index else 0.0)
        rows.append(row)
    normal = [[0.0] * columns for _ in range(columns)]
    rhs = [0.0] * columns
    for row, value, weight in zip(rows, values_ns, weights):
        for i in range(columns):
            rhs[i] += weight * row[i] * value
            for j in range(columns):
                normal[i][j] += weight * row[i] * row[j]
    parameters = _solve([row[:] for row in normal], rhs)
    if parameters is None:
        return None
    rss = 0.0
    for row, value, weight in zip(rows, values_ns, weights):
        residual = value - sum(p * c for p, c in zip(parameters, row))
        rss += weight * residual * residual
    variance = 0.0
    if break_index is not None:
        unit = [0.0, 0.0, 1.0]
        covariance_column = _solve([row[:] for row in normal], unit)
        if covariance_column is None:
            return None
        variance = covariance_column[2]
    return parameters, rss, variance


def detect_ritual_step(offsets: Sequence[PairOffset]) -> tuple[SyncStep | None, int | None, str]:
    """Test the per-ritual offsets for ONE clock step under a common drift.

    Returns ``(step, break_index, detail)``. ``break_index`` is the ritual the
    step precedes, and is ``None`` whenever the step cannot be attributed to a
    gap — which is the correct answer at three rituals and the reason the run
    sheet asks for a ritual at every battery swap rather than only at the ends.

    Fails closed everywhere: fewer than three rituals, an unbounded ritual
    offset, or a singular system all yield no step and a reason, never a step of
    zero and never a silent pass.
    """

    if len(offsets) < 3:
        return None, None, (
            f"{len(offsets)} ritual(s): a step is not testable. Two offsets fit "
            f"any line exactly, so a step between them is indistinguishable from "
            f"drift in principle"
        )
    totals = [item.uncertainty.total for item in offsets]
    if any(total is None or total <= 0.0 for total in totals):
        return None, None, (
            "a ritual offset has no bounded uncertainty, so nothing weights the "
            "step test; no step is claimed"
        )
    ordered = sorted(range(len(offsets)), key=lambda i: offsets[i].epoch_ns)
    base = offsets[ordered[0]].epoch_ns
    raw_epochs = [(offsets[i].epoch_ns - base) / _NS_PER_S for i in ordered]
    centre = statistics.fmean(raw_epochs)
    # Centred times and unit-scale weights: the same subspace, so the step
    # coefficient is unchanged, but the normal equations stay conditioned.
    epochs = [value - centre for value in raw_epochs]
    values = [float(offsets[i].offset_ns) for i in ordered]
    uncertainties = [float(totals[i]) for i in ordered]  # type: ignore[arg-type]
    unit = max(uncertainties)
    weights = [(unit / value) ** 2 for value in uncertainties]

    flat = _weighted_fit(epochs, values, weights, None)
    if flat is None:
        return None, None, "the no-step model is singular; no step is claimed"
    parameters, _, _ = flat
    worst = max(
        abs(value - (parameters[0] + parameters[1] * epoch)) / uncertainty
        for epoch, value, uncertainty in zip(epochs, values, uncertainties)
    )
    if worst <= 1.0:
        return None, None, (
            f"a single drifting line explains every ritual offset to within its "
            f"own uncertainty (worst {worst:.2f} of 1.0): no step"
        )

    best: tuple[float, int, float, float] | None = None
    for break_index in range(1, len(offsets)):
        fitted = _weighted_fit(epochs, values, weights, break_index)
        if fitted is None:
            continue
        params, rss, variance = fitted
        if variance <= 0.0:
            continue
        # `variance` came back in units of the unit weight, so the half-width is
        # sqrt(variance) * unit — the same 95% basis the ritual offsets carry.
        candidate = (rss, break_index, params[2], math.sqrt(variance) * unit)
        if best is None or candidate[0] < best[0] - 1e-9:
            best = candidate
    if best is None:
        return None, None, "every step model is singular; no step is claimed"
    rss, break_index, magnitude, half_width = best
    if abs(magnitude) <= half_width:
        return None, None, (
            f"the best step model puts the jump at {magnitude / 1e6:.3f} ms "
            f"± {half_width / 1e6:.3f} ms, which does not clear its own "
            f"uncertainty: no step"
        )
    # At three rituals every break fits exactly, so the gap is not identifiable:
    # the same three offsets are produced by a +S step in one gap and a -S step
    # in the other at a different drift. Report the step, refuse the location.
    ties = 0
    for candidate in range(1, len(offsets)):
        fitted = _weighted_fit(epochs, values, weights, candidate)
        if fitted is not None and abs(fitted[1] - rss) <= 1e-6 * max(rss, 1.0):
            ties += 1
    # Localisation needs a residual degree of freedom: with three rituals the
    # step model has three parameters and fits ANY three offsets exactly, so
    # every gap is an equally good explanation and only floating-point noise
    # would separate them. That is a structural fact, not a tolerance to tune.
    localizable = len(offsets) >= 4 and ties == 1
    before = offsets[ordered[break_index - 1]]
    after = offsets[ordered[break_index]]
    step = SyncStep(
        magnitude_ns=round(magnitude),
        uncertainty_ns=half_width,
        before_ritual=before.ritual,
        after_ritual=after.ritual if localizable else None,
        localizable=localizable,
        gap_ns=(after.epoch_ns - before.epoch_ns) if localizable else None,
        detail=(
            f"common-drift fit puts a {magnitude / 1e6:+.3f} ms ± "
            f"{half_width / 1e6:.3f} ms jump "
            + (
                f"in the gap {before.ritual} -> {after.ritual}"
                if localizable
                else "in a gap the offsets cannot identify (a step model over "
                "three rituals fits any three offsets exactly, so every gap "
                "explains them equally well); perform the ritual again "
                "mid-session — at every battery swap — to localise it"
            )
        ),
    )
    return step, (break_index if localizable else None), step.detail


@dataclass(frozen=True, slots=True)
class UnresolvedRitual:
    """A ritual that produced no offset for this pair, carried rather than dropped.

    "This modality saw nothing" is a finding about the session. Deleting the row
    would leave a fit that silently rests on one bracket while looking like it
    rests on two.
    """

    ritual: str
    status: MatchStatus
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"ritual": self.ritual, "status": self.status.value, "detail": self.detail}

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> UnresolvedRitual:
        _require_keys(record, frozenset({"ritual", "status", "detail"}), what="unresolved ritual")
        try:
            status = MatchStatus(record["status"])
        except ValueError as exc:
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD, f"undecodable status: {exc}"
            ) from exc
        return cls(ritual=str(record["ritual"]), status=status, detail=str(record["detail"]))


@dataclass(frozen=True, slots=True)
class Ritual:
    """One performance of the sync script: every train any channel produced."""

    label: str
    trains: tuple[EventTrain, ...]

    def __post_init__(self) -> None:
        _require_text(self.label, field="ritual.label")
        seen: set[tuple[str, str]] = set()
        for train in self.trains:
            if not isinstance(train, EventTrain):
                raise SyncRefusedError(
                    SyncRefusalReason.MALFORMED_RECORD,
                    f"{self.label}: trains must be EventTrain, got {type(train).__name__}",
                )
            if train.ritual != self.label:
                raise SyncRefusedError(
                    SyncRefusalReason.MALFORMED_RECORD,
                    f"train {train.channel_id} is labelled ritual {train.ritual!r} "
                    f"but sits in {self.label!r}",
                )
            key = (train.channel_id, train.domain.value)
            if key in seen:
                raise SyncRefusedError(
                    SyncRefusalReason.MALFORMED_RECORD,
                    f"{self.label}: two trains for {train.channel_id} in the "
                    f"{train.domain.value} domain",
                )
            seen.add(key)

    def train(self, channel_id: str, *, domain: TimeDomain | None = None) -> EventTrain | None:
        """The one train for a channel, or ``None``. Ambiguity is a refusal.

        A channel can legitimately appear twice — ``go2.lowstate`` in host-receipt
        time *and* in its own unwrapped counter is the pair that pins the dog's
        tick to the session — so picking "the first one" would silently choose a
        time domain on the caller's behalf. Not here.
        """

        found = [
            train
            for train in self.trains
            if train.channel_id == channel_id and (domain is None or train.domain is domain)
        ]
        if len(found) > 1:
            raise SyncRefusedError(
                SyncRefusalReason.DOMAIN_MISMATCH,
                f"{self.label}: {channel_id} has trains in "
                f"{sorted(train.domain.value for train in found)} — name the domain, "
                f"do not let the lookup pick one",
            )
        return found[0] if found else None


@dataclass(frozen=True, slots=True)
class SyncFitV1:
    """A channel pair's offset and drift across the bracketing rituals.

    Self-sufficient by design, like ``ClockMapV1``: a decoded fit still carries
    the per-ritual offsets, the relation that converts a timestamp, the blind
    intervals, the rituals that produced nothing, and what none of it proves.
    """

    session_id: str
    created_at_utc: str
    host_id: str
    origin: EvidenceOrigin
    fixture_label: str | None
    reference_channel: str
    target_channel: str
    device: SourceDevice
    reference_domain: TimeDomain
    target_domain: TimeDomain
    ritual_offsets: tuple[PairOffset, ...]
    unresolved: tuple[UnresolvedRitual, ...]
    ritual_steps: tuple[SyncStep, ...]
    step_test_detail: str
    relation: ClockRelation
    blind_intervals: tuple[BlindInterval, ...]
    matched_event_count: int
    events_digest: str
    sample_digest: str
    does_not_prove: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.session_id, field="session_id")
        _require_text(self.host_id, field="host_id")
        _require_text(self.events_digest, field="events_digest")
        _require_text(self.sample_digest, field="sample_digest")
        if not _ISO_UTC.match(self.created_at_utc or ""):
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_TIMESTAMP,
                f"created_at_utc must be ISO-8601 UTC (…Z), got {self.created_at_utc!r}",
            )
        if not isinstance(self.origin, EvidenceOrigin) or self.origin is EvidenceOrigin.UNKNOWN:
            raise SyncRefusedError(
                SyncRefusalReason.ORIGIN_NOT_DECLARED,
                f"origin must be a declared EvidenceOrigin, got {self.origin!r} — "
                f"UNKNOWN is not an origin a sync fit may be recorded under",
            )
        if self.origin in SYNTHETIC_ORIGINS:
            if not isinstance(self.fixture_label, str) or not self.fixture_label.strip():
                raise SyncRefusedError(
                    SyncRefusalReason.FIXTURE_LABEL_MISSING,
                    f"origin {self.origin.value} requires a fixture_label — a "
                    f"rehearsal fit must be impossible to mistake for a session fit",
                )
        elif self.fixture_label is not None:
            raise SyncRefusedError(
                SyncRefusalReason.FIXTURE_LABEL_FORBIDDEN,
                f"origin {self.origin.value} must not carry a fixture_label",
            )
        if not self.ritual_offsets:
            raise SyncRefusedError(
                SyncRefusalReason.NO_MATCHED_EVENTS,
                "a sync fit needs at least one ritual that actually matched — a fit "
                "with none would be a fabricated zero offset",
            )
        if not self.does_not_prove or any(
            not isinstance(item, str) or not item.strip() for item in self.does_not_prove
        ):
            raise SyncRefusedError(
                SyncRefusalReason.EMPTY_FIELD,
                "does_not_prove must be a non-empty tuple of non-empty strings",
            )

    @property
    def ritual_count(self) -> int:
        return len(self.ritual_offsets)

    @property
    def span_ns(self) -> int:
        return (
            self.relation.last_host_monotonic_ns - self.relation.first_host_monotonic_ns
        )

    @property
    def primary_segment(self) -> Any:
        return self.relation.primary_segment

    @property
    def offset_ns(self) -> int:
        return self.primary_segment.offset_ns

    @property
    def drift_ppm(self) -> float | None:
        return self.primary_segment.drift_ppm

    @property
    def steps(self) -> tuple[SyncStep, ...]:
        """The ritual-level steps. ``relation.steps`` is empty by construction:
        this fit hands ``fit_relation`` its segmentation rather than letting the
        sample-level scan run on clustered evidence it cannot judge."""

        return self.ritual_steps

    @property
    def shortfalls(self) -> tuple[str, ...]:
        """Every reason this fit may not be trusted to convert a timestamp."""

        out: list[str] = []
        if self.ritual_count < 2:
            out.append(
                f"only {self.ritual_count} ritual matched: there is no second "
                f"bracket, so the drift is fitted inside one ritual window and is "
                f"not a session drift"
            )
        if self.span_ns < RITUAL_SCHEDULE.min_span_ns:
            out.append(
                f"span {self.span_ns / _NS_PER_S:.1f}s is under the "
                f"{RITUAL_SCHEDULE.min_span_ns / _NS_PER_S:.0f}s needed to resolve drift"
            )
        if not self.relation.is_bounded:
            out.append(
                f"{self.relation.label}: the fit is not bounded (see basis and "
                f"uncertainty) — a bare offset is not a measurement"
            )
        for item in self.unresolved:
            out.append(
                f"ritual {item.ritual}: {item.status.value} — no offset from this "
                f"bracket ({item.detail})"
            )
        for offset in self.ritual_offsets:
            if not offset.is_bounded:
                out.append(f"ritual {offset.ritual}: offset has no bounded uncertainty")
        for step in self.ritual_steps:
            if not step.localizable:
                out.append(
                    f"a {step.magnitude_ns / 1e6:+.3f} ms step is present but its "
                    f"gap is not identifiable: {step.detail}"
                )
        if len(self.relation.segments) > 1:
            out.append(
                f"the relation is split into {len(self.relation.segments)} segments "
                f"by a detected step: the drift after the last step rests on the "
                f"rituals that follow it, and there may be only one"
            )
        return tuple(out)

    @property
    def is_certifiable(self) -> bool:
        """Fails closed: one bracket, an unbounded fit or a lost ritual all say no."""

        return not self.shortfalls

    @property
    def caveats(self) -> tuple[str, ...]:
        """Always-true statements about a ritual design. Not shortfalls: a
        correctly-run bracketed session has every one of these."""

        out = [
            f"{interval.duration_ns / _NS_PER_S:.1f}s blind interval "
            f"[{interval.start_host_monotonic_ns}, {interval.end_host_monotonic_ns}]: "
            f"no matched events, so a clock step inside it is aliased into the drift"
            for interval in self.blind_intervals
        ]
        for offset in self.ritual_offsets:
            out.extend(f"ritual {offset.ritual}: {item}" for item in offset.caveats)
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SYNC_FIT_SCHEMA,
            "session_id": self.session_id,
            "created_at_utc": self.created_at_utc,
            "host_id": self.host_id,
            "origin": self.origin.value,
            "fixture_label": self.fixture_label,
            "reference_channel": self.reference_channel,
            "target_channel": self.target_channel,
            "device": self.device.value,
            "reference_domain": self.reference_domain.value,
            "target_domain": self.target_domain.value,
            "ritual_offsets": [item.to_dict() for item in self.ritual_offsets],
            "unresolved": [item.to_dict() for item in self.unresolved],
            "ritual_steps": [item.to_dict() for item in self.ritual_steps],
            "step_test_detail": self.step_test_detail,
            "relation": self.relation.to_dict(),
            "blind_intervals": [item.to_dict() for item in self.blind_intervals],
            "matched_event_count": self.matched_event_count,
            "events_digest": self.events_digest,
            "sample_digest": self.sample_digest,
            "is_certifiable": self.is_certifiable,
            "shortfalls": list(self.shortfalls),
            "caveats": list(self.caveats),
            "does_not_prove": list(self.does_not_prove),
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> SyncFitV1:
        """Decode, recomputing every derived answer rather than trusting it.

        ``is_certifiable``, ``shortfalls`` and ``caveats`` are written for a human
        and thrown away here: hand-editing ``"is_certifiable": true`` into a fit
        file changes nothing, because the value is re-derived on the way out.
        """

        _require_keys(record, _FIT_KEYS, what="sync fit")
        if record["schema"] != SYNC_FIT_SCHEMA:
            raise SyncRefusedError(
                SyncRefusalReason.SCHEMA_MISMATCH,
                f"expected schema {SYNC_FIT_SCHEMA!r}, got {record['schema']!r}",
            )
        try:
            origin = EvidenceOrigin(record["origin"])
            device = SourceDevice(record["device"])
            reference_domain = TimeDomain(record["reference_domain"])
            target_domain = TimeDomain(record["target_domain"])
        except ValueError as exc:
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD, f"undecodable sync-fit enum: {exc}"
            ) from exc
        does_not_prove = record["does_not_prove"]
        if not isinstance(does_not_prove, (list, tuple)):
            raise SyncRefusedError(
                SyncRefusalReason.MALFORMED_RECORD,
                f"does_not_prove must be a list of strings, got {does_not_prove!r}",
            )
        return cls(
            session_id=str(record["session_id"]),
            created_at_utc=str(record["created_at_utc"]),
            host_id=str(record["host_id"]),
            origin=origin,
            fixture_label=record["fixture_label"],
            reference_channel=str(record["reference_channel"]),
            target_channel=str(record["target_channel"]),
            device=device,
            reference_domain=reference_domain,
            target_domain=target_domain,
            ritual_offsets=tuple(PairOffset.from_dict(item) for item in record["ritual_offsets"]),
            unresolved=tuple(UnresolvedRitual.from_dict(item) for item in record["unresolved"]),
            ritual_steps=tuple(SyncStep.from_dict(item) for item in record["ritual_steps"]),
            step_test_detail=str(record["step_test_detail"]),
            relation=ClockRelation.from_dict(record["relation"]),
            blind_intervals=tuple(
                BlindInterval.from_dict(item) for item in record["blind_intervals"]
            ),
            matched_event_count=_require_ns(
                record["matched_event_count"], field="matched_event_count"
            ),
            events_digest=str(record["events_digest"]),
            sample_digest=str(record["sample_digest"]),
            does_not_prove=tuple(str(item) for item in does_not_prove),
        )


_FIT_KEYS = frozenset(
    {
        "schema",
        "session_id",
        "created_at_utc",
        "host_id",
        "origin",
        "fixture_label",
        "reference_channel",
        "target_channel",
        "device",
        "reference_domain",
        "target_domain",
        "ritual_offsets",
        "unresolved",
        "ritual_steps",
        "step_test_detail",
        "relation",
        "blind_intervals",
        "matched_event_count",
        "events_digest",
        "sample_digest",
        "is_certifiable",
        "shortfalls",
        "caveats",
        "does_not_prove",
    }
)


def sync_fit_digest(fit: SyncFitV1) -> str:
    """SHA-256 over the canonical fit. PS-B binds this into the sidecar ``extra``."""

    return hashlib.sha256(canonical_json(fit.to_dict()).encode("utf-8")).hexdigest()


def events_digest(trains: Sequence[EventTrain]) -> str:
    """SHA-256 over the canonical detected events.

    Binds a fit to the events it was fitted from: move one detected event by one
    nanosecond and the digest moves, so a re-fit that disagrees with the recorded
    one is provable rather than arguable.
    """

    return hashlib.sha256(
        canonical_json([train.to_dict() for train in trains]).encode("utf-8")
    ).hexdigest()


def _blind_intervals(
    samples: Sequence[ClockSample], *, gap_ns: int = STEP_BLIND_GAP_NS
) -> tuple[BlindInterval, ...]:
    mids = sorted(sample.host_mid_ns for sample in samples)
    return tuple(
        BlindInterval(start_host_monotonic_ns=earlier, end_host_monotonic_ns=later)
        for earlier, later in pairwise(mids)
        if later - earlier > gap_ns
    )


def build_sync_fit(
    rituals: Sequence[Ritual],
    *,
    reference_channel: str,
    target_channel: str,
    session_id: str,
    created_at_utc: str,
    host_id: str,
    origin: EvidenceOrigin,
    host_pair_bracket_ns: int | None,
    fixture_label: str | None = None,
    reference_domain: TimeDomain = TimeDomain.HOST_RECEIPT,
    target_domain: TimeDomain | None = None,
    extra_tolerance_ns: int = 0,
    max_skew_ns: int | None = None,
    schedule: ClockSchedule = RITUAL_SCHEDULE,
    does_not_prove: Sequence[str] = DEFAULT_SYNC_DOES_NOT_PROVE,
) -> SyncFitV1:
    """Detect -> match -> estimate -> fit, across every ritual of one session.

    Each matched event becomes one :class:`ClockSample`, so the segmented fit
    that ``clockmap`` already proves under step, drift and asymmetry does the
    arithmetic. A ritual that matched nothing is recorded as
    :class:`UnresolvedRitual` and contributes no samples; if **no** ritual
    matched, this refuses rather than returning an offset of zero.
    """

    if not rituals:
        raise SyncRefusedError(
            SyncRefusalReason.NO_RITUALS,
            "a sync fit needs at least one ritual. A session with no sync ritual "
            "has no cross-device timing evidence at all, and none can be made "
            "after the robot powers down",
        )
    labels = [ritual.label for ritual in rituals]
    if len(set(labels)) != len(labels):
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD, f"duplicate ritual labels: {labels}"
        )

    offsets: list[PairOffset] = []
    unresolved: list[UnresolvedRitual] = []
    samples: list[ClockSample] = []
    per_ritual_samples: list[list[ClockSample]] = []
    used_trains: list[EventTrain] = []
    device: SourceDevice | None = None
    resolved_target_domain: TimeDomain | None = target_domain

    for ritual in rituals:
        reference = ritual.train(reference_channel, domain=reference_domain)
        target = ritual.train(target_channel, domain=target_domain)
        if reference is None or target is None:
            missing = [
                name
                for name, train in ((reference_channel, reference), (target_channel, target))
                if train is None
            ]
            unresolved.append(
                UnresolvedRitual(
                    ritual=ritual.label,
                    status=MatchStatus.NO_EVENTS,
                    detail=f"no train for {', '.join(missing)} in this ritual",
                )
            )
            continue
        if device is not None and target.device is not device:
            raise SyncRefusedError(
                SyncRefusalReason.DEVICE_MISMATCH,
                f"{target_channel} is {target.device.value} in {ritual.label} and "
                f"{device.value} elsewhere",
            )
        device = target.device
        if resolved_target_domain is None:
            resolved_target_domain = target.domain
        elif target.domain is not resolved_target_domain:
            raise SyncRefusedError(
                SyncRefusalReason.DOMAIN_MISMATCH,
                f"{target_channel} changes time domain between rituals: "
                f"{resolved_target_domain.value} then {target.domain.value}",
            )
        match = match_trains(
            reference, target, extra_tolerance_ns=extra_tolerance_ns, max_skew_ns=max_skew_ns
        )
        if match.status is not MatchStatus.MATCHED:
            unresolved.append(
                UnresolvedRitual(ritual=ritual.label, status=match.status, detail=match.detail)
            )
            continue
        pair_offset = estimate_pair_offset(match, reference, target)
        offsets.append(pair_offset)
        produced = pair_clock_samples(
            match,
            reference,
            target,
            host_pair_bracket_ns=host_pair_bracket_ns,
            dropout_penalty_ns=pair_offset.dropout_penalty_ns,
        )
        samples.extend(produced)
        per_ritual_samples.append(produced)
        used_trains.extend((reference, target))

    if not offsets or device is None or resolved_target_domain is None:
        raise SyncRefusedError(
            SyncRefusalReason.NO_MATCHED_EVENTS,
            f"no ritual matched {reference_channel} against {target_channel} "
            f"({len(unresolved)} unresolved: "
            f"{'; '.join(item.detail for item in unresolved) or 'none attempted'}). "
            f"The offset is UNKNOWN. It is not zero, and this refuses rather than "
            f"let a downstream default make it zero",
        )

    # The step test runs over the per-ritual OFFSETS under a common drift, and
    # its verdict — not the sample-level scan — sets the segmentation.
    step, break_index, step_detail = detect_ritual_step(offsets)
    splits: list[int] | None = None
    if break_index is not None:
        order = sorted(range(len(offsets)), key=lambda i: offsets[i].epoch_ns)
        splits = [sum(len(per_ritual_samples[i]) for i in order[:break_index])]
    relation = fit_relation(samples, device=device, schedule=schedule, splits=splits or [])
    return SyncFitV1(
        session_id=session_id,
        created_at_utc=created_at_utc,
        host_id=host_id,
        origin=origin,
        fixture_label=fixture_label,
        reference_channel=reference_channel,
        target_channel=target_channel,
        device=device,
        reference_domain=reference_domain,
        target_domain=resolved_target_domain,
        ritual_offsets=tuple(offsets),
        unresolved=tuple(unresolved),
        ritual_steps=() if step is None else (step,),
        step_test_detail=step_detail,
        relation=relation,
        blind_intervals=_blind_intervals(samples),
        matched_event_count=len(samples),
        events_digest=events_digest(used_trains),
        sample_digest=sample_digest(samples),
        does_not_prove=tuple(does_not_prove),
    )


def sidecar_sync_block(fit: SyncFitV1) -> dict[str, Any]:
    """The block PS-B folds into ``bags/schema.py:make_manifest``'s ``extra``.

    Carries the digest, not the fit: the bag is bound to the evidence that can
    interpret its timestamps, and a fit that disagrees with the recorded digest
    is provably not the one the session produced.
    """

    segment = fit.primary_segment
    return {
        "sync_fit_schema": SYNC_FIT_SCHEMA,
        "sync_fit_sha256": sync_fit_digest(fit),
        "sync_events_sha256": fit.events_digest,
        "sync_samples_sha256": fit.sample_digest,
        "sync_reference_channel": fit.reference_channel,
        "sync_target_channel": fit.target_channel,
        "sync_reference_domain": fit.reference_domain.value,
        "sync_target_domain": fit.target_domain.value,
        "sync_ritual_count": fit.ritual_count,
        "sync_matched_events": fit.matched_event_count,
        "sync_offset_ns": segment.offset_ns,
        "sync_offset_uncertainty_ns": segment.offset_uncertainty.total,
        "sync_drift_ppm": segment.drift_ppm,
        "sync_drift_uncertainty_ppm": (
            None if segment.drift_uncertainty is None else segment.drift_uncertainty.total
        ),
        "sync_confidence": CONFIDENCE,
        "sync_step_count": len(fit.steps),
        "sync_steps": [step.to_dict() for step in fit.steps],
        "sync_step_test": fit.step_test_detail,
        "sync_blind_interval_ns": [item.duration_ns for item in fit.blind_intervals],
        "sync_certifiable": fit.is_certifiable,
        "sync_shortfalls": list(fit.shortfalls),
        "sync_caveats": list(fit.caveats),
        "sync_does_not_prove": list(fit.does_not_prove),
    }


# --------------------------------------------------------------------------- #
# The operator card
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RitualStep:
    """One step of the sync script, with what it buys and what sees it."""

    order: int
    name: str
    seconds: float
    action: str
    expected_events: int
    channels: tuple[str, ...]
    why: str


RITUAL_SCRIPT: tuple[RitualStep, ...] = (
    RitualStep(
        order=1,
        name="BUTTON",
        seconds=3.0,
        action="Press and release one controller button, deliberately, twice.",
        expected_events=4,
        channels=("go2.lowstate", "go2.wirelesscontroller"),
        why=(
            "lands in wireless_remote[40] INSIDE lowstate at 500 Hz and on the "
            "event-driven wirelesscontroller topic. The disagreement between the "
            "two is the only measurement of per-topic transport delay the session "
            "can make, and it is free"
        ),
    ),
    RitualStep(
        order=2,
        name="TAPS",
        seconds=4.0,
        action=(
            "Three sharp taps on the payload plate with a hard object, roughly 1 s "
            "apart. Sharp, not heavy: a knock, not a push. Do NOT try to space them "
            "evenly — an uneven train is the one the matcher can disambiguate."
        ),
        expected_events=TAP_COUNT,
        channels=("go2.lowstate", "d455.accel", "l2.imu", "go2.utlidar.imu"),
        why=(
            "an impulse is the only feature that is sharp against a 500 Hz sample "
            "period. This is the ritual's precision anchor; everything else is "
            "coarser"
        ),
    ),
    RitualStep(
        order=3,
        name="TWIST",
        seconds=TWIST_SECONDS,
        action=(
            "Hold the rig off the ground. Still 2 s, then rotate smoothly about "
            "all three axes for 6 s, then still 2 s."
        ),
        expected_events=2,
        channels=("go2.lowstate", "d455.gyro", "l2.imu", "l2.cloud", "go2.utlidar.cloud"),
        why=(
            "the only event both LiDARs can also see. Excites all three gyro axes, "
            "which is what the downstream IMU-to-LiDAR extrinsic tools need; this "
            "module only times its two edges"
        ),
    ),
    RitualStep(
        order=4,
        name="FLASHES",
        seconds=8.0,
        action=(
            f"Point the torch at the D455 and flash {TORCH_FLASH_COUNT} times with "
            f"gaps of {', '.join(f'{gap:g}' for gap in TORCH_FLASH_GAPS_S)} s. "
            f"White AND 850 nm. Count out loud."
        ),
        expected_events=2 * TORCH_FLASH_COUNT,
        channels=("d455.color", "d455.infra1", "d455.infra2", "go2.front_camera"),
        why=(
            "the only event a camera can see. The gaps are UNEVEN on purpose: an "
            "evenly spaced train aliases onto itself under a one-interval shift and "
            "the matcher refuses it as ambiguous rather than being confidently one "
            "second wrong"
        ),
    ),
)

RITUAL_TOTAL_SECONDS = sum(step.seconds for step in RITUAL_SCRIPT)


def format_ritual_card() -> str:
    """The sheet the operator holds. Printed by ``--ritual-card``."""

    lines = [
        "SYNC RITUAL — perform at session START (SYNC-OPEN) and END (SYNC-CLOSE),",
        "              and AGAIN AT EVERY BATTERY SWAP or long pause.",
        f"  {RITUAL_TOTAL_SECONDS:.0f} s per performance. The two ends are required.",
        "  One performance gives an OFFSET. Two give an offset, a DRIFT RATE and a",
        "  RESIDUAL. THREE detect a clock step but cannot say which gap it happened",
        (f"  in; FOUR can place it. That is why a mid-session repeat is worth its "
        f"{RITUAL_TOTAL_SECONDS:.0f} s"),
        "  — measured, not asserted: a step model has three parameters, so",
        "  three offsets fit it exactly and leave nothing over to locate it with.",
        "  Skipping the closing one is unrecoverable: the clocks are gone",
        "  the moment the robot powers down.",
        "  Recording must already be running. Nothing is armed; the robot does not",
        "  move under its own power for any step of this.",
        "",
    ]
    for step in RITUAL_SCRIPT:
        lines.append(f"  {step.order}. {step.name}  (~{step.seconds:g} s, {step.expected_events} events)")
        lines.append(f"     DO:  {step.action}")
        lines.append(f"     SEEN BY: {', '.join(step.channels)}")
        lines.append(f"     WHY: {step.why}")
        lines.append("")
    lines.extend(
        [
            "  RECORD ON THE RUN SHEET: wall-clock time of each performance, which",
            "  steps were actually done, and anything that went wrong. A ritual that",
            "  a modality missed still yields an offset from what matched, with a",
            "  wider uncertainty — but only if we know it happened.",
        ]
    )
    return "\n".join(lines)


def format_report(fit: SyncFitV1) -> str:
    """Operator-readable summary. Every number carries its uncertainty."""

    segment = fit.primary_segment
    offset_total = segment.offset_uncertainty.total
    lines = [
        f"SyncFitV1  session={fit.session_id}  host={fit.host_id}",
        (f"  {fit.reference_channel} [{fit.reference_domain.value}] -> "
        f"{fit.target_channel} [{fit.target_domain.value}]  device={fit.device.value}"),
        f"  origin={fit.origin.value}"
        + (f"  fixture={fit.fixture_label}" if fit.fixture_label else "")
        + f"  rituals={fit.ritual_count}  matched_events={fit.matched_event_count}",
        f"  digest={sync_fit_digest(fit)}",
        f"  certifiable={fit.is_certifiable}",
    ]
    for offset in fit.ritual_offsets:
        total = offset.uncertainty.total
        bound = (
            "± UNBOUNDED (statistical unknown)"
            if total is None
            else f"± {total / 1e6:.3f} ms (sys {offset.uncertainty.systematic / 1e6:.3f} + "
            f"stat {offset.uncertainty.statistical / 1e6:.3f}, {offset.uncertainty.confidence})"
        )
        lines.append(
            f"  [{offset.ritual}] offset {offset.offset_ns / 1e6:+.3f} ms {bound} "
            f"from {offset.matched_count}/{offset.expected_count} events"
        )
    lines.append(
        f"  FIT offset@ref {segment.offset_ns / 1e6:+.3f} ms "
        + ("± UNBOUNDED" if offset_total is None else f"± {offset_total / 1e6:.3f} ms")
        + f"  basis={segment.basis.value}"
    )
    if segment.drift_ppm is None or segment.drift_uncertainty is None:
        lines.append("  FIT drift      unknown (this fit cannot support a slope)")
    else:
        drift_total = segment.drift_uncertainty.total
        lines.append(
            f"  FIT drift      {segment.drift_ppm:+.3f} ppm "
            + ("± UNBOUNDED" if drift_total is None else f"± {drift_total:.3f} ppm")
            + f" ({CONFIDENCE})"
        )
    for step in fit.steps:
        where = (
            f"between {step.before_ritual} and {step.after_ritual}"
            if step.localizable
            else "gap NOT identifiable"
        )
        lines.append(
            f"  STEP {step.magnitude_ns / 1e6:+.3f} ms ± "
            f"{step.uncertainty_ns / 1e6:.3f} ms ({where})"
        )
    lines.append(f"  step test: {fit.step_test_detail}")
    for item in fit.unresolved:
        lines.append(f"  UNRESOLVED {item.ritual}: {item.status.value} — {item.detail}")
    for item in fit.shortfalls:
        lines.append(f"  SHORTFALL {item}")
    for item in fit.caveats:
        lines.append(f"  CAVEAT {item}")
    for item in fit.does_not_prove:
        lines.append(f"  does_not_prove: {item}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Deterministic fixtures: the rehearsal half, and this module's own self-test
# --------------------------------------------------------------------------- #


def synthesize_ritual_series(
    *,
    kind: EventKind,
    event_times_ns: Sequence[int],
    start_ns: int,
    end_ns: int,
    rate_hz: float,
    channel_offset_ns: int = 0,
    drift_ppm: float = 0.0,
    feature_width_ns: int = 6_000_000,
    baseline: float = 0.0,
    amplitude: float = 1.0,
    noise: float = 0.0,
    time_jitter_ns: int = 0,
    seed: int = 0,
    host_realtime_base_ns: int | None = None,
) -> tuple[list[int], list[float], list[int] | None]:
    """A sampled signal in ONE channel's own clock, from events in session time.

    The channel's clock runs at its own rate: a sample stamped ``c`` in the
    channel domain happened at session time ``t = (c - offset - t0*drift) /
    (1 + drift)``. Generating the samples on the channel's grid and evaluating
    the physics at the corresponding session instant is what makes the fixture
    exercise the DETECTORS rather than just the estimator — the quantisation,
    the sub-sample refinement and the bracket all come out of it honestly.

    ``time_jitter_ns`` perturbs the channel's own sample instants — USB
    scheduling, a driver's queue, a frame that waited. Without it a synthetic
    pair lands on the same grid every time and the residual scatter is
    identically zero, which would let a fixture flatter the statistical half of
    every uncertainty this module reports. Bounded to half a period so the
    series stays strictly increasing.

    Deterministic: same arguments, same bytes. Used by ``--selftest``, by the
    tests, and available to PS-E's rehearsal.
    """

    if rate_hz <= 0 or not math.isfinite(rate_hz):
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD, f"rate_hz must be positive, got {rate_hz!r}"
        )
    if end_ns <= start_ns:
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD, "end_ns must follow start_ns"
        )
    period_ns = round(_NS_PER_S / rate_hz)
    slope = drift_ppm / 1e6
    state = (seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF

    def _draw() -> float:
        nonlocal state
        state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        return (state >> 33) / float(1 << 31) - 1.0

    def _noise() -> float:
        return _draw() * noise

    if time_jitter_ns < 0 or 2 * time_jitter_ns >= period_ns:
        raise SyncRefusedError(
            SyncRefusalReason.MALFORMED_RECORD,
            f"time_jitter_ns must be in [0, {period_ns // 2}) so the sample times "
            f"stay strictly increasing, got {time_jitter_ns}",
        )

    times: list[int] = []
    values: list[float] = []
    realtimes: list[int] | None = [] if host_realtime_base_ns is not None else None
    session_ns = start_ns
    while session_ns <= end_ns:
        channel_ns = session_ns + channel_offset_ns + round((session_ns - start_ns) * slope)
        if time_jitter_ns:
            channel_ns += round(_draw() * time_jitter_ns)
        value = baseline
        for event_ns in event_times_ns:
            delta = session_ns - event_ns
            if kind is EventKind.ACCEL_SPIKE:
                if abs(delta) <= feature_width_ns:
                    value += amplitude * (1.0 - abs(delta) / feature_width_ns)
            else:
                if 0 <= delta < feature_width_ns:
                    value += amplitude
        times.append(channel_ns)
        values.append(value + _noise())
        if realtimes is not None:
            realtimes.append(host_realtime_base_ns + (session_ns - start_ns))
        session_ns += period_ns
    return times, values, realtimes


#: Tap offsets inside a ritual, in nanoseconds from its start. UNEVEN, like the
#: flashes and for the same reason: a human tapping evenly would hand the matcher
#: a train that aliases onto itself.
SELFTEST_TAP_OFFSETS_NS: tuple[int, ...] = (500_000_000, 1_300_000_000, 2_800_000_000)
SELFTEST_BUTTON_PRESS_NS = 5_000_000_000
SELFTEST_BUTTON_RELEASE_NS = 5_600_000_000
SELFTEST_RITUAL_NS = 8_000_000_000


def synthesize_lowstate_ritual(
    *,
    ritual: str,
    host_start_ns: int,
    host_realtime_start_ns: int,
    counter_start_ns: int,
    transport_latency_ns: int = 1_500_000,
    drift_ppm: float = 0.0,
    step_ns: int = 0,
    rate_hz: float = 500.0,
    jitter_ns: int = 0,
    tap_offsets_ns: Sequence[int] = SELFTEST_TAP_OFFSETS_NS,
    duration_ns: int = SELFTEST_RITUAL_NS,
    seed: int = 0,
) -> tuple[EventTrain, EventTrain]:
    """The flagship pair: ``go2.lowstate`` in host-receipt time and in its own tick.

    One stream of 500 Hz messages, two timestamps each. The **counter** stamp is
    the unwrapped ``tick`` (arbitrary epoch, no absolute meaning); the **host**
    stamp is when that same message was received, i.e.
    ``counter + offset + drift + per-message jitter``. The taps and the button are
    evaluated at the message's own instant, so both trains detect the same
    physical events through their own quantisation — which is what makes this a
    test of the detectors and not only of the estimator.

    This is the pair the whole card exists for: it is the only way the dog's
    500 Hz IMU channel — which carries **no timestamp at all** — gets placed on
    the session timeline.
    """

    period_ns = round(_NS_PER_S / rate_hz)
    state = (seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF

    def _jitter() -> int:
        nonlocal state
        if not jitter_ns:
            return 0
        state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        return (state >> 33) % (2 * jitter_ns + 1) - jitter_ns

    counter_times: list[int] = []
    host_times: list[int] = []
    host_realtimes: list[int] = []
    accel: list[float] = []
    pressed: list[bool] = []
    width_ns = 6_000_000
    elapsed = 0
    while elapsed <= duration_ns:
        # `elapsed` is DEVICE elapsed. The counter grid is exact; the host sees
        # the same message a transport latency later, on a clock running
        # drift_ppm slower than the device's, plus per-message jitter.
        counter_ns = counter_start_ns + elapsed
        host_ns = (
            host_start_ns
            + elapsed
            - round(elapsed * drift_ppm / 1e6)
            + transport_latency_ns
            - step_ns
            + _jitter()
        )
        magnitude = 9.81
        for tap_ns in tap_offsets_ns:
            delta = elapsed - tap_ns
            if abs(delta) <= width_ns:
                magnitude += 4.0 * (1.0 - abs(delta) / width_ns)
        counter_times.append(counter_ns)
        host_times.append(host_ns)
        host_realtimes.append(host_realtime_start_ns + elapsed)
        accel.append(magnitude)
        pressed.append(SELFTEST_BUTTON_PRESS_NS <= elapsed < SELFTEST_BUTTON_RELEASE_NS)
        elapsed += period_ns

    host_accel = accel
    tap_args = {
        "sample_bracket_ns": period_ns,
        "min_prominence": 1.0,
        "refractory_ns": 200_000_000,
    }
    host_train = merge_trains(
        EventTrain(
            channel_id="go2.lowstate",
            device=SourceDevice.GO2,
            domain=TimeDomain.HOST_RECEIPT,
            detector="detect_accel_spikes",
            ritual=ritual,
            events=detect_accel_spikes(
                host_times, host_accel, realtimes_ns=host_realtimes, **tap_args
            ),
        ),
        EventTrain(
            channel_id="go2.lowstate",
            device=SourceDevice.GO2,
            domain=TimeDomain.HOST_RECEIPT,
            detector="detect_button_edges",
            ritual=ritual,
            events=detect_button_edges(
                host_times, pressed, min_hold_ns=100_000_000, realtimes_ns=host_realtimes
            ),
        ),
    )
    counter_train = merge_trains(
        EventTrain(
            channel_id="go2.lowstate",
            device=SourceDevice.GO2,
            domain=TimeDomain.UNWRAPPED_COUNTER,
            detector="detect_accel_spikes",
            ritual=ritual,
            events=detect_accel_spikes(counter_times, accel, **tap_args),
        ),
        EventTrain(
            channel_id="go2.lowstate",
            device=SourceDevice.GO2,
            domain=TimeDomain.UNWRAPPED_COUNTER,
            detector="detect_button_edges",
            ritual=ritual,
            events=detect_button_edges(counter_times, pressed, min_hold_ns=100_000_000),
        ),
    )
    return host_train, counter_train


#: Host monotonic and wall clock at the opening ritual of the synthetic session.
SELFTEST_HOST_START_NS = 12_000_000_000
SELFTEST_REALTIME_START_NS = 1_786_000_000_000_000_000
#: Where the dog's unwrapped counter happens to be when we start. Non-zero on
#: purpose: the epoch is arbitrary and nothing may assume it is near the host's.
SELFTEST_COUNTER_START_NS = 4_000_000_000_000
#: Device-to-host offset the fixture seeds, i.e. the truth the fit must recover.
SELFTEST_OFFSET_NS = SELFTEST_HOST_START_NS - SELFTEST_COUNTER_START_NS


def selftest_rituals(
    *,
    labels: Sequence[str] = ("SYNC-OPEN", "SYNC-CLOSE"),
    session_span_ns: int = 3_600_000_000_000,
    drift_ppm: float = 40.0,
    jitter_ns: int = 200_000,
    step_ns: int = 0,
    step_from_ritual: int | None = None,
    transport_latency_ns: int = 1_500_000,
) -> list[Ritual]:
    """Bracketed synthetic session: one ritual per label, evenly spaced.

    Deterministic — same arguments, same bytes — and it is the same generator the
    tests and ``--selftest`` use, so a gate cannot pass against a fixture the
    tool never runs.
    """

    if len(labels) < 1:
        raise SyncRefusedError(SyncRefusalReason.NO_RITUALS, "at least one ritual label")
    spacing = session_span_ns // max(len(labels) - 1, 1)
    rituals: list[Ritual] = []
    for index, label in enumerate(labels):
        elapsed = index * spacing
        applied_step = (
            step_ns if step_from_ritual is not None and index >= step_from_ritual else 0
        )
        host_train, counter_train = synthesize_lowstate_ritual(
            ritual=label,
            host_start_ns=SELFTEST_HOST_START_NS + elapsed,
            host_realtime_start_ns=SELFTEST_REALTIME_START_NS + elapsed,
            # The device counter has run AHEAD by drift * elapsed by the time the
            # later rituals happen: that accumulated difference is the slope the
            # bracketing is there to measure.
            counter_start_ns=(
                SELFTEST_COUNTER_START_NS + elapsed + round(elapsed * drift_ppm / 1e6)
            ),
            transport_latency_ns=transport_latency_ns,
            drift_ppm=drift_ppm,
            step_ns=applied_step,
            jitter_ns=jitter_ns,
            seed=17 + index,
        )
        rituals.append(Ritual(label=label, trains=(host_train, counter_train)))
    return rituals


def build_selftest_fit(
    *,
    origin: EvidenceOrigin = EvidenceOrigin.SIMULATION,
    fixture_label: str | None = "syncevents-selftest",
    does_not_prove: Sequence[str] = DEFAULT_SYNC_DOES_NOT_PROVE,
    **kwargs: Any,
) -> SyncFitV1:
    """``selftest_rituals`` fitted, with the synthetic origin its own class demands."""

    return build_sync_fit(
        selftest_rituals(**kwargs),
        origin=origin,
        fixture_label=fixture_label,
        does_not_prove=does_not_prove,
        reference_channel="go2.lowstate",
        target_channel="go2.lowstate",
        reference_domain=TimeDomain.HOST_RECEIPT,
        target_domain=TimeDomain.UNWRAPPED_COUNTER,
        session_id="syncevents-selftest",
        created_at_utc="2026-08-13T00:00:00Z",
        host_id="selftest-host",
        host_pair_bracket_ns=200,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _check_report() -> str:
    lines = [
        "Per-channel clock truth, read off the capture matrix (capture/channels.py).",
        "A channel with no device time can ONLY be aligned by the sync ritual.",
        "",
    ]
    ritual_only = 0
    for channel_id in sorted(CHANNELS_BY_ID):
        channel = CHANNELS_BY_ID[channel_id]
        anchor = channel.source_clock.is_usable_anchor
        if not anchor:
            ritual_only += 1
        lines.append(
            f"  [{'ANCHOR' if anchor else 'RITUAL':>6}] {channel_id:<28} "
            f"source_clock={channel.source_clock.value}"
        )
    lines.extend(
        [
            "",
            (f"{ritual_only} of {len(CHANNELS_BY_ID)} channels carry no usable device "
            f"clock and depend entirely on the ritual."),
            ("go2.lowstate — the 500 Hz IMU, the highest-timing-value channel on the "
            "dog — is one of them: it has NO timestamp field, only a wrapping tick."),
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="syncevents",
        description=(
            "Bracketed physical sync events: detect them per modality, match the "
            "event trains, and fit offset + drift with an uncertainty. Read-only — "
            "it opens no device and arms nothing."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--ritual-card", action="store_true", help="print the operator sheet for the session"
    )
    group.add_argument(
        "--check",
        action="store_true",
        help="report which channels carry a device clock and which need the ritual",
    )
    group.add_argument(
        "--selftest",
        action="store_true",
        help="fit a synthetic bracketed session (seeded 40 ppm) and print it",
    )
    group.add_argument("--fit", metavar="TRAINS.jsonl", help="fit a recorded event-train log")
    parser.add_argument("--reference-channel", default="", help="host-receipt reference channel")
    parser.add_argument("--target-channel", default="", help="channel to place against it")
    parser.add_argument("--session-id", default="", help="session id for --fit")
    parser.add_argument("--host-id", default="", help="host id for --fit")
    parser.add_argument("--created-at", default="", help="ISO-8601 UTC stamp for --fit")
    parser.add_argument(
        "--host-pair-bracket-ns",
        type=int,
        default=None,
        help="width of the host monotonic/realtime read; omit to record it as UNKNOWN",
    )
    parser.add_argument("--json", action="store_true", help="emit the fit as JSON, not a report")
    args = parser.parse_args(argv)

    if args.ritual_card:
        print(format_ritual_card())
        return 0
    if args.check:
        print(_check_report())
        return 0
    if args.selftest:
        fit = build_selftest_fit()
        print(canonical_json(fit.to_dict()) if args.json else format_report(fit))
        return 0

    path = Path(args.fit)
    if not path.is_file():
        print(f"REFUSED: no train log at {path}", file=sys.stderr)
        return 2
    for name, value in (
        ("--reference-channel", args.reference_channel),
        ("--target-channel", args.target_channel),
        ("--session-id", args.session_id),
        ("--host-id", args.host_id),
        ("--created-at", args.created_at),
    ):
        if not value.strip():
            print(
                f"REFUSED: {name} is required for --fit. A sync fit that cannot "
                f"name its channels, its session or its host cannot be bound to a bag.",
                file=sys.stderr,
            )
            return 2
    try:
        trains = read_trains_jsonl(path)
        by_label: dict[str, list[EventTrain]] = {}
        for train in trains:
            by_label.setdefault(train.ritual, []).append(train)
        rituals = [
            Ritual(label=label, trains=tuple(by_label[label])) for label in sorted(by_label)
        ]
        fit = build_sync_fit(
            rituals,
            reference_channel=args.reference_channel,
            target_channel=args.target_channel,
            session_id=args.session_id,
            created_at_utc=args.created_at,
            host_id=args.host_id,
            origin=EvidenceOrigin.PHYSICAL,
            host_pair_bracket_ns=args.host_pair_bracket_ns,
        )
    except SyncError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except CaptureError as exc:  # a clockmap refusal reaching the surface
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(canonical_json(fit.to_dict()) if args.json else format_report(fit))
    return 0 if fit.is_certifiable else 1


__all__ = [
    "DEFAULT_SYNC_DOES_NOT_PROVE",
    "DROPOUT_PENALTY_FACTOR",
    "MAX_EVENTS_PER_TRAIN",
    "MAX_TICK_FORWARD_JUMP_MS",
    "RITUAL_SCHEDULE",
    "RITUAL_SCRIPT",
    "RITUAL_TOTAL_SECONDS",
    "STEP_BLIND_GAP_NS",
    "SYNC_EVENT_SCHEMA",
    "SYNC_FIT_SCHEMA",
    "SYNC_TRAIN_SCHEMA",
    "TAP_COUNT",
    "TICK_MODULUS_MS",
    "TORCH_FLASH_COUNT",
    "TORCH_FLASH_GAPS_S",
    "TWIST_SECONDS",
    "WIRELESS_REMOTE_KEY_OFFSET_UNVERIFIED",
    "WIRELESS_REMOTE_LENGTH",
    "BlindInterval",
    "EventKind",
    "EventTrain",
    "MatchStatus",
    "PairOffset",
    "Ritual",
    "RitualStep",
    "SyncError",
    "SyncEvent",
    "SyncFitV1",
    "SyncRefusalReason",
    "SyncRefusedError",
    "SyncStep",
    "TickUnwrap",
    "TimeDomain",
    "TrainMatch",
    "UnresolvedRitual",
    "append_train_jsonl",
    "build_selftest_fit",
    "build_sync_fit",
    "button_series_from_wireless_remote",
    "detect_accel_spikes",
    "detect_brightness_steps",
    "detect_button_edges",
    "detect_gyro_onsets",
    "detect_ritual_step",
    "estimate_pair_offset",
    "events_digest",
    "format_report",
    "format_ritual_card",
    "magnitudes_from_xyz",
    "main",
    "match_trains",
    "merge_trains",
    "pair_clock_samples",
    "read_trains_jsonl",
    "selftest_rituals",
    "sidecar_sync_block",
    "sync_fit_digest",
    "synthesize_lowstate_ritual",
    "synthesize_ritual_series",
    "unwrap_tick_ms",
    "wireless_remote_keys",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry, exercised by subprocess
    raise SystemExit(main())
