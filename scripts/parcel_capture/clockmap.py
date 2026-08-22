"""``ClockMapV1`` — the offset triples that make cross-device time recoverable.

Card PS-C of tranche PS-1 (``scrum/20260813/task_1/README.md``), and the one
card on that board whose output cannot be reconstructed after the session ends.

The defect
----------
``grep -rn 'chrony|ntp|ptp|phc2sys|time.?sync' src/ configs/ deploy/ scripts/``
returns nothing: there is no time discipline anywhere in this project. Meanwhile
``bags/schema.py`` records a ``received_monotonic_ns`` per message and
``default_clocks()`` writes ``recording_monotonic_origin_ns: 0`` — a placeholder
for a number nobody ever measured. ``CLOCK_MONOTONIC`` has a per-machine,
per-boot, arbitrary epoch, so two devices' monotonic stamps have no defined
relationship at all, and a wall-clock stamp on a Jetson with no RTC battery is
worse than useless.

Consequently: **every timestamp we record tomorrow is unusable across devices
unless the offsets are measured live, while both clocks are running.** Six
months from now the bags are still there and the clocks are not. Every other
defect on the board is fixable next week against the bags; this one is not.
``control/models.py:161-173`` reserves ``source_time_s`` "for a later
``ClockMapper`` to fuse" — this module is that thing, built read-only.

What a sample is
----------------
:class:`ClockSample` is one interrogation of one device:

* ``host_monotonic_ns`` — ``t1``, read on the host immediately BEFORE the
  interrogation.
* ``host_realtime_ns`` — the host wall clock, read next to ``t1``.
* ``device_source_ns`` — the device's own clock, as the device reported it.
* ``round_trip_ns`` — ``t4 - t1`` on the same host monotonic clock, where
  ``t4`` is the instant the device's answer was in hand.

The device's reading happened at some instant inside ``[t1, t4]`` and we do not
know where, so the best estimate of the corresponding host instant is the
midpoint ``t1 + round_trip/2`` and it is uncertain by **±round_trip/2**. That
half-width is the irreducible NTP bound, and it is the reason this module never
reports a bare offset. A passive one-way receipt reduces to the same algebra:
give ``host_monotonic_ns`` the earliest host instant the device stamp could
belong to and ``round_trip_ns`` the width of that bracket. There is no default
for ``round_trip_ns``, because a fabricated bracket is a fabricated confidence.

What the fit reports, and why never a bare number
-------------------------------------------------
Per device, per step-free segment: an offset at the segment's minimum-variance
instant, and a drift rate in ppm, **each with an uncertainty split into two
kinds that must not be mixed**:

* ``statistical`` — Student-t 95% from the residual scatter. Shrinks like
  ``1/sqrt(n)``. ``None`` when ``n < 3``, because a two-point line has no
  residuals to bound it and reporting ``0`` there would be a lie.
* ``systematic`` — the worst-case bias the round-trip brackets permit. It does
  **not** shrink with ``n``: if the path is asymmetric, every sample is biased
  the same way, and averaging a million of them removes none of it. The exact
  bound is ``sum(|c_i| * b_i)`` over the OLS weights ``c_i``; at the fit's own
  mean instant that collapses to ``mean(b_i)``, and for the slope it is
  ``sum(|x_i - x_mean| * b_i) / Sxx``. Both are computed exactly.

``total`` is their sum and is ``None`` — not zero, not the statistical part
alone — when either half is unknown. :attr:`Uncertainty.is_bounded` is the
predicate a consumer must check before trusting a conversion, and a map with any
unbounded relation is not :attr:`~ClockMapV1.is_certifiable`.

Steps versus drift
------------------
A device clock that jumps (NTP stepping it, an RTC being set, a counter wrap)
does not drift — it steps, and smoothing a step into a slope corrupts every
timestamp on both sides of it. MEASURED, on this module's own 900 s self-test:
a 500 ms step halfway through moves a single-line fit to 772 ppm against a true
40 ppm, an error four orders of magnitude past the segmented fit's. So the
series is segmented first (binary segmentation, exact O(1) segment fits from
prefix sums) and only then fitted, and a split is declared only when the step
exceeds the combined prediction uncertainty of the two candidate segments —
their statistical parts in quadrature, their systematic bounds added, plus a
one-nanosecond floor, which is the quantum of the sample fields themselves.

Asymmetry
---------
An asymmetric path biases the midpoint estimator by ``(alpha - 0.5) * rtt``,
which is inside the ±rtt/2 bound by construction — so the bound stays honest,
and it WIDENS as round trips inflate. When the round trip varies, the bias is
also directly visible as a slope of residual against bracket (the NTP wedge),
reported as :attr:`ClockSegment.asymmetry_slope`. It is reported and **not
corrected for**: correcting would trade a bounded error for an unbounded
modelling assumption. When the round trip does not vary, a constant asymmetry
is undetectable in principle, and that is written into ``does_not_prove``.

Where the samples come from — CORRECTED by card PS-I
----------------------------------------------------
PS-C assumed every device could be *asked* for its clock. **The Go2 cannot be.**
It exposes no queryable clock and no round-trip primitive, and ``lowstate`` —
the 500 Hz IMU, the highest-timing-value channel on the dog — carries no
timestamp field at all, only ``tick``, a ``uint32`` millisecond counter that
wraps and whose epoch is arbitrary (``capture.channels`` marks it
``SourceClock.WRAPPING_COUNTER``). ``SportModeState.stamp`` is the only real
source-clock anchor the dog emits, and it arrives on a service-gated channel.
So :func:`interrogate` has no Go2 implementation and never will.

What survives is the algebra, which never required an interrogation: a
:class:`ClockSample` is a bracketed correspondence between a host instant and a
device instant, and a **physical sync event** — a tap, a torch flash, a button
press seen simultaneously in two channels — produces exactly that correspondence
with a bracket set by the two channels' sampling. ``syncevents.py`` detects
those events, matches the event trains, and emits the samples this module fits;
:data:`PROBE_REQUIREMENTS` marks per device whether an interrogation exists at
all (:attr:`ProbeRequirement.interrogable`). Everything below — segmentation,
the two-part uncertainty, the step/drift separation, the sidecar binding — is
unchanged and is the reason PS-I feeds this fitter rather than writing a second.

Read-only, and what this module may not do
------------------------------------------
Nothing here opens a device, imports a vendor SDK, publishes, or arms anything.
:data:`PROBE_REQUIREMENTS` names the module each device's clock read needs and
``--check`` reports presence via :func:`importlib.util.find_spec` — a lookup,
never an import. The device read itself is a callable supplied by PS-B/PS-D;
:func:`interrogate` owns only the bracket discipline, because getting the order
of the four clock reads wrong is the classic way to fabricate a clock map.

Invocation on the Orin::

    python3 -m scripts.parcel_capture.clockmap --check
    python3 scripts/parcel_capture/clockmap.py --selftest
    python3 scripts/parcel_capture/clockmap.py --fit clock_samples.jsonl

The module resolves ``src/`` onto ``sys.path`` when it is run as a plain script
from a checkout, so a missing ``PYTHONPATH`` produces a working tool rather than
an import traceback (board rule 4).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise
from pathlib import Path
from time import monotonic_ns, time_ns
from types import MappingProxyType
from typing import Any

try:
    from parcel_robot.capture.channels import CaptureError, SourceDevice
    from parcel_robot.evidence_origin import SYNTHETIC_ORIGINS, EvidenceOrigin
except ImportError:  # pragma: no cover - exercised by a subprocess cell instead
    # Run as a plain script with no PYTHONPATH: the deploy layout is
    # <repo>/scripts/parcel_capture/clockmap.py beside <repo>/src.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from parcel_robot.capture.channels import CaptureError, SourceDevice
    from parcel_robot.evidence_origin import SYNTHETIC_ORIGINS, EvidenceOrigin

#: Wire identifiers. A reader that does not know these strings must refuse the
#: record rather than guess at its shape.
CLOCK_MAP_SCHEMA = "parcel.capture.clockmap.v1"
CLOCK_SAMPLE_SCHEMA = "parcel.capture.clocksample.v1"

#: Everything in this module is a two-sided 95% interval. Stated once, and
#: written into every serialised uncertainty so a reader six months from now
#: does not have to assume.
CONFIDENCE = "two-sided-95"

#: A host realtime reading below 2020-01-01T00:00:00Z is an unset RTC, not a
#: timestamp. Jetsons ship without an RTC battery and boot at the Unix epoch or
#: at their image's build date, so this is the single most likely clock fault of
#: the session — and it is trivially fixable AT the session (``sudo date -s``)
#: and unfixable afterwards. Refused rather than recorded.
REALTIME_EPOCH_FLOOR_NS = 1_577_836_800_000_000_000

#: Shortest segment that can carry a fit. Derived: with ``n < 3`` there is no
#: residual degree of freedom (``dof = n - 2``), so a segment shorter than this
#: cannot bound its own fit, and splitting one off is not evidence of a step.
MIN_SEGMENT_SAMPLES = 3

#: Cap on declared steps per relation. Not a statistical constant: a session
#: whose clocks step more than this is broken in a way a fit should not paper
#: over, and :attr:`ClockRelation.steps_truncated` says the scan stopped.
MAX_STEPS = 8

#: Floor under the step-detection threshold, in nanoseconds. Derived: every
#: clock field on :class:`ClockSample` is an integer nanosecond, so a step below
#: one nanosecond is not representable in the evidence and must not be claimed.
STEP_FLOOR_NS = 1.0

#: Worst-case relative rate error assumed between two uncorrected consumer
#: oscillators. ENGINEERING ASSUMPTION, labelled as such: commodity crystals are
#: specified at ±20–50 ppm, so ±100 ppm between a device pair is a fair worst
#: case. Used only to derive the burst window below; no fit depends on it.
ASSUMED_WORST_CASE_DRIFT_PPM = 100.0

#: Burst window at session start and end. Derived: a burst is treated as a point
#: measurement of the offset, which is defensible only while the drift accrued
#: inside it stays at or below the bracket resolution. At
#: :data:`ASSUMED_WORST_CASE_DRIFT_PPM` a 10 s window accrues 1 ms, i.e. the
#: millisecond class of a DDS/USB round trip.
BURST_WINDOW_NS = 10_000_000_000

#: Samples required inside each burst. Derived: at ``n = 30`` the Student-t 95%
#: factor is 2.045, within 5% of the normal 1.960, so the endpoint estimate is
#: no longer dominated by small-sample penalty.
MIN_BURST_SAMPLES = 30

#: Largest tolerated gap in the ~1 Hz cruise. Derived: three nominal periods
#: means two consecutive probes were lost, and a step inside that gap can no
#: longer be located to better than the gap itself.
MAX_CRUISE_GAP_NS = 3_000_000_000

#: Shortest span over which drift is worth quoting. Derived: drift is resolvable
#: only once it moves the offset past the bracket, so ``span > bracket/drift``;
#: at a 1 ms bracket and a 10 ppm resolution goal that is 100 s, and 300 s gives
#: 3x margin. Short sessions still get a fit — they get one whose uncertainty
#: covers zero, plus a named shortfall.
MIN_SPAN_NS = 300_000_000_000

#: Two-sided 95% Student-t critical values by degrees of freedom, ascending.
#: Standard table. Lookups take the largest listed ``dof`` at or below the
#: requested one, which over-estimates ``t`` (it decreases with ``dof``) and is
#: therefore the conservative direction.
_T95_TABLE: tuple[tuple[int, float], ...] = (
    (1, 12.706),
    (2, 4.303),
    (3, 3.182),
    (4, 2.776),
    (5, 2.571),
    (6, 2.447),
    (7, 2.365),
    (8, 2.306),
    (9, 2.262),
    (10, 2.228),
    (11, 2.201),
    (12, 2.179),
    (13, 2.160),
    (14, 2.145),
    (15, 2.131),
    (16, 2.120),
    (17, 2.110),
    (18, 2.101),
    (19, 2.093),
    (20, 2.086),
    (21, 2.080),
    (22, 2.074),
    (23, 2.069),
    (24, 2.064),
    (25, 2.060),
    (26, 2.056),
    (27, 2.052),
    (28, 2.048),
    (29, 2.045),
    (30, 2.042),
    (40, 2.021),
    (60, 2.000),
    (120, 1.980),
)
_T95_ASYMPTOTE = 1.960

_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")

_NS_PER_S = 1_000_000_000.0

#: Mirrored from ``bags/schema.py`` ``REQUIRED_CLOCK_KEYS`` rather than imported,
#: so this module stays importable without the autonomy package's bag layer.
#: ``test_sidecar_clock_block_mirrors_the_live_bag_schema`` pins the mirror
#: against the live constant, so a schema change reddens the gate instead of
#: leaving this silently false. Precedent: ``commissioning/limits.py``'s
#: ``FOOTPRINT_RADIUS_M`` mirror.
_BAG_REQUIRED_CLOCK_KEYS = frozenset(
    {"source_clock", "recording_monotonic_origin_ns", "note"}
)

DEFAULT_DOES_NOT_PROVE: tuple[str, ...] = (
    (
        "A clock map does not prove any clock is correct. It records how two "
        "clocks differed while both were running, and nothing else."
    ),
    (
        "Offsets are bounded by the interrogation round trip. A path whose "
        "asymmetry AND whose round trip are both constant is indistinguishable "
        "from a symmetric path at a shifted offset; no estimator here sees it."
    ),
    (
        "Drift is fitted over the observed span only. Past the last sample the "
        "only bound is the quoted drift uncertainty, and a clock that steps "
        "after the closing burst leaves no evidence at all."
    ),
    (
        "No absolute time is claimed. With no GNSS discipline and no PTP "
        "grandmaster, the whole session floats against UTC by the host's own "
        "realtime error, which this map cannot measure."
    ),
    (
        "This map does not prove a sample came from the device it names. That "
        "binding is the PS-D attestation's job, by digest."
    ),
)


class ClockRefusalReason(str, Enum):
    """Why a clock record was refused. Every refusal names one of these.

    PS-B and PS-D branch on the reason — an implausible realtime reading is an
    operator action at the session, a non-integer clock field is a broken
    adapter — so the reason is part of the contract, not prose in a message.
    """

    NON_INTEGER_FIELD = "non_integer_field"
    NOT_FINITE = "not_finite"
    NEGATIVE_FIELD = "negative_field"
    IMPLAUSIBLE_REALTIME = "implausible_realtime"
    DEVICE_NOT_TYPED = "device_not_typed"
    ORIGIN_NOT_TYPED = "origin_not_typed"
    ORIGIN_NOT_DECLARED = "origin_not_declared"
    FIXTURE_LABEL_MISSING = "fixture_label_missing"
    FIXTURE_LABEL_FORBIDDEN = "fixture_label_forbidden"
    EMPTY_FIELD = "empty_field"
    MALFORMED_TIMESTAMP = "malformed_timestamp"
    MALFORMED_RECORD = "malformed_record"
    SCHEMA_MISMATCH = "schema_mismatch"
    NO_SAMPLES = "no_samples"
    NON_FINITE_RESULT = "non_finite_result"


class ClockMapError(CaptureError):
    """Base for every refusal raised by this module.

    Subclasses :class:`parcel_robot.capture.channels.CaptureError` so a capture
    process can catch one exception type across the whole stack.
    """


class ClockRefusedError(ClockMapError):
    """A malformed, under-declared, or implausible clock record."""

    def __init__(self, reason: ClockRefusalReason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason


class ClockProbeError(ClockMapError):
    """A device clock read failed. There is no sample, and no sample is made up."""


def _require_ns(value: object, *, field: str) -> int:
    """Integer nanoseconds or a refusal. NaN, inf, None, bool and float all fail.

    A float clock is never rounded here and a missing clock is never defaulted
    to "now": both would put a fabricated number where a measurement belongs.
    """

    if isinstance(value, float) and not math.isfinite(value):
        raise ClockRefusedError(
            ClockRefusalReason.NOT_FINITE,
            f"{field} must be a finite integer nanosecond count, got {value!r}",
        )
    if value is None:
        raise ClockRefusedError(
            ClockRefusalReason.NON_INTEGER_FIELD,
            f"{field} must be an int (nanoseconds), got None — an absent clock is "
            f"a refusal, never a default",
        )
    if isinstance(value, bool) or not isinstance(value, int):
        raise ClockRefusedError(
            ClockRefusalReason.NON_INTEGER_FIELD,
            f"{field} must be an int (nanoseconds), got {type(value).__name__} "
            f"{value!r} — a float clock is never rounded here",
        )
    if value < 0:
        raise ClockRefusedError(
            ClockRefusalReason.NEGATIVE_FIELD, f"{field} must be non-negative, got {value!r}"
        )
    return value


def _require_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClockRefusedError(
            ClockRefusalReason.EMPTY_FIELD,
            f"{field} must be a non-empty string, got {value!r}",
        )
    return value


def _require_keys(record: object, expected: frozenset[str], *, what: str) -> Mapping[str, Any]:
    """Strict in both directions: a missing key and an unexpected key both refuse.

    A format that silently ignores fields it does not understand cannot be read
    back with confidence six months later, which is the entire point of this
    artifact.
    """

    if not isinstance(record, Mapping):
        raise ClockRefusedError(
            ClockRefusalReason.MALFORMED_RECORD,
            f"{what} record must be a mapping, got {type(record).__name__}",
        )
    keys = set(record)
    missing = expected - keys
    unexpected = keys - expected
    if missing or unexpected:
        raise ClockRefusedError(
            ClockRefusalReason.MALFORMED_RECORD,
            f"{what} keys missing={sorted(missing)} unexpected={sorted(unexpected)}",
        )
    return record


def _finite(value: float, *, field: str) -> float:
    """Guard every computed float on its way into a report.

    A NaN reaching :func:`canonical_json` would either raise there or, with the
    stdlib default, emit a bare ``NaN`` token that is not JSON. Refuse at the
    source instead, and name the field.
    """

    if not math.isfinite(value):
        raise ClockRefusedError(
            ClockRefusalReason.NON_FINITE_RESULT,
            f"fit produced a non-finite {field}: {value!r}",
        )
    return value


def _optional_float(value: object, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ClockRefusedError(
            ClockRefusalReason.MALFORMED_RECORD,
            f"{field} must be a number or null, got {type(value).__name__} {value!r}",
        )
    return _finite(float(value), field=field)


def t_critical_95(dof: int) -> float:
    """Two-sided 95% Student-t factor. Public so PS-I quotes the SAME table.

    ``syncevents.py`` estimates a ritual offset as the mean of matched-event
    residuals and needs this factor for its interval. Re-deriving it there would
    let the two halves of the clock story drift apart in the one place a reader
    would never check.
    """

    return _t_critical(dof)


def _t_critical(dof: int) -> float:
    if dof < 1:
        raise ClockRefusedError(
            ClockRefusalReason.NON_FINITE_RESULT,
            f"a Student-t factor needs at least one degree of freedom, got {dof}",
        )
    factor = _T95_ASYMPTOTE
    for listed_dof, listed_t in _T95_TABLE:
        if dof >= listed_dof:
            factor = listed_t
    return factor


# --------------------------------------------------------------------------- #
# Samples
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ClockSample:
    """One interrogation of one device's clock, with its bracket.

    Build these with :func:`interrogate` in a capture process — that is the path
    which reads the four clocks in the only order that makes the bracket mean
    what this module says it means.
    """

    device: SourceDevice
    #: ``t1``: host monotonic, read immediately BEFORE the interrogation.
    host_monotonic_ns: int
    #: Host wall clock, read next to ``t1``.
    host_realtime_ns: int
    #: The device's own clock, exactly as the device reported it. Never
    #: converted, never back-filled from a host clock.
    device_source_ns: int
    #: ``t4 - t1``: the width of the interval that provably contains the instant
    #: at which the device clock read :attr:`device_source_ns`. No default.
    round_trip_ns: int
    #: Width of the interval containing :attr:`host_realtime_ns`, i.e. the gap
    #: between the monotonic reads that straddle it. ``None`` is honest absence
    #: and costs the host relation its systematic bound — the non-permissive
    #: outcome, since an unbounded relation is never certifiable.
    host_pair_bracket_ns: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.device, SourceDevice):
            raise ClockRefusedError(
                ClockRefusalReason.DEVICE_NOT_TYPED,
                f"device must be a SourceDevice member, got "
                f"{type(self.device).__name__} {self.device!r} — a string is not a "
                f"declaration",
            )
        _require_ns(self.host_monotonic_ns, field="host_monotonic_ns")
        _require_ns(self.host_realtime_ns, field="host_realtime_ns")
        _require_ns(self.device_source_ns, field="device_source_ns")
        _require_ns(self.round_trip_ns, field="round_trip_ns")
        if self.host_pair_bracket_ns is not None:
            _require_ns(self.host_pair_bracket_ns, field="host_pair_bracket_ns")
        if self.host_realtime_ns < REALTIME_EPOCH_FLOOR_NS:
            raise ClockRefusedError(
                ClockRefusalReason.IMPLAUSIBLE_REALTIME,
                f"host_realtime_ns {self.host_realtime_ns} predates "
                f"{REALTIME_EPOCH_FLOOR_NS} (2020-01-01Z): the host RTC is unset. "
                f"Set it at the session (`sudo date -s ...`) — a bag stamped with "
                f"an unset RTC cannot be placed in wall time afterwards",
            )

    @property
    def host_mid_ns(self) -> int:
        """Best host-monotonic estimate of the instant the device clock was read."""

        return self.host_monotonic_ns + self.round_trip_ns // 2

    @property
    def bracket_ns(self) -> float:
        """Half-width of the device-offset bracket: ``round_trip / 2``."""

        return self.round_trip_ns / 2.0

    @property
    def offset_ns(self) -> int:
        """``device_source - host_mid``. Positive means the device clock is ahead."""

        return self.device_source_ns - self.host_mid_ns

    @property
    def host_pair_mid_ns(self) -> int:
        """Best host-monotonic estimate of the instant the wall clock was read."""

        if self.host_pair_bracket_ns is None:
            return self.host_monotonic_ns
        return self.host_monotonic_ns + self.host_pair_bracket_ns // 2

    @property
    def host_pair_offset_ns(self) -> int:
        """``host_realtime - host_pair_mid``: the boot epoch, sampled."""

        return self.host_realtime_ns - self.host_pair_mid_ns

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CLOCK_SAMPLE_SCHEMA,
            "device": self.device.value,
            "host_monotonic_ns": self.host_monotonic_ns,
            "host_realtime_ns": self.host_realtime_ns,
            "device_source_ns": self.device_source_ns,
            "round_trip_ns": self.round_trip_ns,
            "host_pair_bracket_ns": self.host_pair_bracket_ns,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> ClockSample:
        _require_keys(record, _SAMPLE_KEYS, what="clock sample")
        if record["schema"] != CLOCK_SAMPLE_SCHEMA:
            raise ClockRefusedError(
                ClockRefusalReason.SCHEMA_MISMATCH,
                f"expected schema {CLOCK_SAMPLE_SCHEMA!r}, got {record['schema']!r}",
            )
        try:
            device = SourceDevice(record["device"])
        except ValueError as exc:
            raise ClockRefusedError(
                ClockRefusalReason.DEVICE_NOT_TYPED, f"undecodable device: {exc}"
            ) from exc
        return cls(
            device=device,
            host_monotonic_ns=record["host_monotonic_ns"],
            host_realtime_ns=record["host_realtime_ns"],
            device_source_ns=record["device_source_ns"],
            round_trip_ns=record["round_trip_ns"],
            host_pair_bracket_ns=record["host_pair_bracket_ns"],
        )


_SAMPLE_KEYS = frozenset(
    {
        "schema",
        "device",
        "host_monotonic_ns",
        "host_realtime_ns",
        "device_source_ns",
        "round_trip_ns",
        "host_pair_bracket_ns",
    }
)


def canonical_json(payload: object) -> str:
    """Deterministic serialisation used for every digest here.

    ``allow_nan=False`` is not decoration: Python's ``json`` emits a bare
    ``NaN`` token by default, which is not JSON, and a clock map no other tool
    can parse is a clock map that does not exist.
    """

    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def sample_digest(samples: Sequence[ClockSample]) -> str:
    """SHA-256 over the canonical form of the raw samples.

    Binds a fit to the inputs it was fitted from: mutate one nanosecond of one
    sample and the map's digest moves, so a re-fit that disagrees with the
    recorded map is provable rather than arguable.
    """

    return hashlib.sha256(
        canonical_json([sample.to_dict() for sample in samples]).encode("utf-8")
    ).hexdigest()


def interrogate(
    device: SourceDevice,
    read_device_clock: Callable[[], int],
    *,
    now_monotonic_ns: Callable[[], int] = monotonic_ns,
    now_realtime_ns: Callable[[], int] = time_ns,
) -> ClockSample:
    """Read the four clocks in the only order that makes the bracket honest.

    ``read_device_clock`` returns the device's own clock in integer nanoseconds
    and is supplied by the caller — this module never opens a device, imports a
    vendor SDK, or publishes anything. If the read raises, that is a failed
    probe: :class:`ClockProbeError` propagates and NO sample is produced. A
    capture loop logs the failure and tries again; it must never substitute a
    host clock for a device clock it could not read.
    """

    if not isinstance(device, SourceDevice):
        raise ClockRefusedError(
            ClockRefusalReason.DEVICE_NOT_TYPED,
            f"device must be a SourceDevice member, got {device!r}",
        )
    start_ns = now_monotonic_ns()
    realtime_ns = now_realtime_ns()
    pair_close_ns = now_monotonic_ns()
    try:
        device_ns = read_device_clock()
    except Exception as exc:  # the device read is foreign code; classify it
        raise ClockProbeError(
            f"{device.value}: device clock read failed ({type(exc).__name__}: {exc}) — "
            f"no sample recorded"
        ) from exc
    end_ns = now_monotonic_ns()
    return ClockSample(
        device=device,
        host_monotonic_ns=start_ns,
        host_realtime_ns=realtime_ns,
        device_source_ns=_require_ns(device_ns, field="device_source_ns"),
        round_trip_ns=max(end_ns - start_ns, 0),
        host_pair_bracket_ns=max(pair_close_ns - start_ns, 0),
    )


def append_sample_jsonl(path: Path | str, sample: ClockSample) -> None:
    """Append one sample, flushed and fsynced.

    The raw samples are the irreplaceable artifact — the fit can always be
    redone, the session cannot. ``bags/recorder.py`` rewrites its manifest after
    every message and never fsyncs; this appends one line and forces it to the
    platter, so a power cut costs at most the line in flight.
    """

    line = canonical_json(sample.to_dict())
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_samples_jsonl(path: Path | str) -> list[ClockSample]:
    """Read a sample log, refusing any malformed line by number.

    A truncated final line (the power-cut case) is a refusal naming the line,
    not a silently shorter map: the operator decides whether to drop it.
    """

    samples: list[ClockSample] = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ClockRefusedError(
                    ClockRefusalReason.MALFORMED_RECORD,
                    f"{path}:{number}: not JSON ({exc})",
                ) from exc
            try:
                samples.append(ClockSample.from_dict(record))
            except ClockRefusedError as exc:
                raise ClockRefusedError(exc.reason, f"{path}:{number}: {exc}") from exc
    return samples


# --------------------------------------------------------------------------- #
# Uncertainty and fits
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Uncertainty:
    """A two-sided 95% half-width, split into the two kinds that do not mix.

    :attr:`statistical` shrinks like ``1/sqrt(n)``; :attr:`systematic` does not
    shrink at all. ``None`` in either half means "not estimable from this
    evidence", and it propagates: :attr:`total` is ``None`` and
    :attr:`is_bounded` is ``False``. Zero is never used to mean unknown.
    """

    unit: str
    systematic: float | None
    statistical: float | None
    confidence: str = CONFIDENCE

    @property
    def total(self) -> float | None:
        if self.systematic is None or self.statistical is None:
            return None
        return self.systematic + self.statistical

    @property
    def is_bounded(self) -> bool:
        return self.total is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "systematic": self.systematic,
            "statistical": self.statistical,
            "total": self.total,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> Uncertainty:
        _require_keys(record, _UNCERTAINTY_KEYS, what="uncertainty")
        built = cls(
            unit=_require_text(record["unit"], field="uncertainty.unit"),
            systematic=_optional_float(record["systematic"], field="systematic"),
            statistical=_optional_float(record["statistical"], field="statistical"),
            confidence=_require_text(record["confidence"], field="uncertainty.confidence"),
        )
        stored_total = _optional_float(record["total"], field="total")
        # Derived answers are never read back from the file (the
        # ``commissioning/record.py`` rule): recompute and refuse a mismatch, so
        # hand-editing a narrower total into a map changes nothing.
        if stored_total != built.total and not (
            stored_total is not None
            and built.total is not None
            and math.isclose(stored_total, built.total, rel_tol=1e-12, abs_tol=1e-9)
        ):
            raise ClockRefusedError(
                ClockRefusalReason.MALFORMED_RECORD,
                f"uncertainty total {stored_total!r} is not the sum of its parts "
                f"({built.total!r})",
            )
        return built


_UNCERTAINTY_KEYS = frozenset({"unit", "systematic", "statistical", "total", "confidence"})


class FitBasis(str, Enum):
    """What kind of evidence a segment's fit rests on."""

    #: ``n >= 3`` with a non-zero span: offset and drift, both bounded.
    OLS = "ols"
    #: ``n == 2``: the line is determined but has no residual to bound it.
    TWO_POINT = "two_point"
    #: Two or more samples, all at one host instant: offset only.
    NO_SPAN = "no_span"
    #: ``n == 1``: an offset and nothing else. Drift is unknown, not zero.
    SINGLE_SAMPLE = "single_sample"


@dataclass(frozen=True, slots=True)
class FitStats:
    """Sufficient statistics that let a decoded segment still convert a time.

    Serialised with the segment on purpose: the map has to be able to place a
    bag's timestamps six months from now with no access to the samples, the
    fitter, or this process.
    """

    sample_count: int
    #: Integer bases the float arithmetic was rebased against. Wall-clock
    #: nanoseconds exceed float64's exact-integer range (2**53 ≈ 9.0e15), so
    #: every fit runs on offsets relative to these and the exactness is kept.
    x_base_ns: int
    y_base_ns: int
    x_mean_s: float
    sxx_s2: float
    residual_std_ns: float | None
    t_critical: float | None
    #: ``mean(bracket)``: the exact worst-case bracket bias at ``x_mean``.
    bracket_mean_ns: float | None
    #: ``sum(|x_i - x_mean| * bracket_i)``: with ``sxx`` it is the exact
    #: worst-case bracket bias of the slope, and together they bound the bias at
    #: any instant.
    bracket_weighted_ns: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "x_base_ns": self.x_base_ns,
            "y_base_ns": self.y_base_ns,
            "x_mean_s": self.x_mean_s,
            "sxx_s2": self.sxx_s2,
            "residual_std_ns": self.residual_std_ns,
            "t_critical": self.t_critical,
            "bracket_mean_ns": self.bracket_mean_ns,
            "bracket_weighted_ns": self.bracket_weighted_ns,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> FitStats:
        _require_keys(record, _FIT_STATS_KEYS, what="fit stats")
        return cls(
            sample_count=_require_ns(record["sample_count"], field="sample_count"),
            x_base_ns=_require_ns(record["x_base_ns"], field="x_base_ns"),
            y_base_ns=int(record["y_base_ns"]),
            x_mean_s=_finite(float(record["x_mean_s"]), field="x_mean_s"),
            sxx_s2=_finite(float(record["sxx_s2"]), field="sxx_s2"),
            residual_std_ns=_optional_float(record["residual_std_ns"], field="residual_std_ns"),
            t_critical=_optional_float(record["t_critical"], field="t_critical"),
            bracket_mean_ns=_optional_float(record["bracket_mean_ns"], field="bracket_mean_ns"),
            bracket_weighted_ns=_optional_float(
                record["bracket_weighted_ns"], field="bracket_weighted_ns"
            ),
        )


_FIT_STATS_KEYS = frozenset(
    {
        "sample_count",
        "x_base_ns",
        "y_base_ns",
        "x_mean_s",
        "sxx_s2",
        "residual_std_ns",
        "t_critical",
        "bracket_mean_ns",
        "bracket_weighted_ns",
    }
)


@dataclass(frozen=True, slots=True)
class ClockReading:
    """An offset placed at one host instant, with its uncertainty."""

    host_monotonic_ns: int
    offset_ns: int
    uncertainty: Uncertainty
    segment_index: int
    #: True when the instant lies outside the segment's own sample span, where
    #: the drift uncertainty is the only thing bounding the answer.
    extrapolated: bool
    #: True when the instant falls in the unsampled gap around a detected step,
    #: where the offset is ambiguous by the step magnitude. The magnitude is
    #: added to the systematic term rather than a side chosen.
    at_step_boundary: bool

    @property
    def is_bounded(self) -> bool:
        return self.uncertainty.is_bounded

    def to_dict(self) -> dict[str, Any]:
        return {
            "host_monotonic_ns": self.host_monotonic_ns,
            "offset_ns": self.offset_ns,
            "uncertainty": self.uncertainty.to_dict(),
            "segment_index": self.segment_index,
            "extrapolated": self.extrapolated,
            "at_step_boundary": self.at_step_boundary,
        }


@dataclass(frozen=True, slots=True)
class ClockSegment:
    """One step-free stretch of a clock relation, fitted.

    :attr:`offset_ns` is quoted at :attr:`reference_host_monotonic_ns`, which is
    the mean host instant of the segment — the minimum-variance point of an OLS
    line, and the point where the bracket bias bound collapses exactly to
    ``mean(bracket)``. Quoting at an endpoint instead would inflate both halves
    of the uncertainty for no gain.
    """

    index: int
    sample_count: int
    start_host_monotonic_ns: int
    end_host_monotonic_ns: int
    reference_host_monotonic_ns: int
    offset_ns: int
    offset_uncertainty: Uncertainty
    #: Positive means the device clock runs FAST against the host. ``None`` when
    #: the segment cannot support a slope — never ``0.0``, which would claim a
    #: perfectly synchronised pair.
    drift_ppm: float | None
    drift_uncertainty: Uncertainty | None
    basis: FitBasis
    residual_rms_ns: float | None
    residual_max_ns: float | None
    #: Slope of residual against bracket (the NTP wedge). ``2*alpha - 1`` for a
    #: path spending fraction ``alpha`` of the round trip on the request leg, so
    #: 0 is symmetric and ±1 is one-sided. ``None`` when the round trip does not
    #: vary, because then asymmetry is invisible in principle.
    asymmetry_slope: float | None
    asymmetry_detected: bool
    stats: FitStats

    @property
    def span_s(self) -> float:
        return (self.end_host_monotonic_ns - self.start_host_monotonic_ns) / _NS_PER_S

    @property
    def is_bounded(self) -> bool:
        """Both quantities bounded. A segment with unknown drift is not bounded."""

        return (
            self.offset_uncertainty.is_bounded
            and self.drift_uncertainty is not None
            and self.drift_uncertainty.is_bounded
        )

    def offset_at(self, host_monotonic_ns: int) -> ClockReading:
        """The offset at a host instant, with the uncertainty of being there.

        Both terms grow with distance from the fit's mean instant: the
        statistical one as the usual OLS mean-prediction interval, the
        systematic one as ``bracket_mean + |dx| * bracket_weighted / sxx``,
        which is the exact worst-case bracket bias of ``intercept + dx*slope``.
        """

        instant = _require_ns(host_monotonic_ns, field="host_monotonic_ns")
        stats = self.stats
        x = (instant - stats.x_base_ns) / _NS_PER_S
        dx = x - stats.x_mean_s
        slope_ns_s = 0.0 if self.drift_ppm is None else self.drift_ppm * 1000.0
        centre = self.offset_ns + slope_ns_s * dx
        statistical: float | None = None
        if stats.residual_std_ns is not None and stats.t_critical is not None:
            leverage = 1.0 / stats.sample_count
            if stats.sxx_s2 > 0.0:
                leverage += dx * dx / stats.sxx_s2
            statistical = stats.t_critical * stats.residual_std_ns * math.sqrt(leverage)
        systematic: float | None = None
        if stats.bracket_mean_ns is not None:
            systematic = stats.bracket_mean_ns
            if stats.bracket_weighted_ns is not None and stats.sxx_s2 > 0.0:
                systematic += abs(dx) * stats.bracket_weighted_ns / stats.sxx_s2
        if self.drift_ppm is None and instant != self.reference_host_monotonic_ns:
            # No slope was estimable, so nothing bounds the walk away from the
            # one instant that was measured. Say so instead of holding the
            # offset flat and calling it bounded.
            statistical = None
            systematic = None
        return ClockReading(
            host_monotonic_ns=instant,
            offset_ns=round(centre),
            uncertainty=Uncertainty(
                unit="ns",
                systematic=None if systematic is None else _finite(systematic, field="systematic"),
                statistical=(
                    None if statistical is None else _finite(statistical, field="statistical")
                ),
            ),
            segment_index=self.index,
            extrapolated=not (
                self.start_host_monotonic_ns <= instant <= self.end_host_monotonic_ns
            ),
            at_step_boundary=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "sample_count": self.sample_count,
            "start_host_monotonic_ns": self.start_host_monotonic_ns,
            "end_host_monotonic_ns": self.end_host_monotonic_ns,
            "reference_host_monotonic_ns": self.reference_host_monotonic_ns,
            "offset_ns": self.offset_ns,
            "offset_uncertainty": self.offset_uncertainty.to_dict(),
            "drift_ppm": self.drift_ppm,
            "drift_uncertainty": (
                None if self.drift_uncertainty is None else self.drift_uncertainty.to_dict()
            ),
            "basis": self.basis.value,
            "residual_rms_ns": self.residual_rms_ns,
            "residual_max_ns": self.residual_max_ns,
            "asymmetry_slope": self.asymmetry_slope,
            "asymmetry_detected": self.asymmetry_detected,
            "stats": self.stats.to_dict(),
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> ClockSegment:
        _require_keys(record, _SEGMENT_KEYS, what="clock segment")
        try:
            basis = FitBasis(record["basis"])
        except ValueError as exc:
            raise ClockRefusedError(
                ClockRefusalReason.MALFORMED_RECORD, f"undecodable fit basis: {exc}"
            ) from exc
        drift_uncertainty = record["drift_uncertainty"]
        detected = record["asymmetry_detected"]
        if not isinstance(detected, bool):
            raise ClockRefusedError(
                ClockRefusalReason.MALFORMED_RECORD,
                f"asymmetry_detected must be a bool, got {detected!r}",
            )
        return cls(
            index=_require_ns(record["index"], field="index"),
            sample_count=_require_ns(record["sample_count"], field="sample_count"),
            start_host_monotonic_ns=_require_ns(
                record["start_host_monotonic_ns"], field="start_host_monotonic_ns"
            ),
            end_host_monotonic_ns=_require_ns(
                record["end_host_monotonic_ns"], field="end_host_monotonic_ns"
            ),
            reference_host_monotonic_ns=_require_ns(
                record["reference_host_monotonic_ns"], field="reference_host_monotonic_ns"
            ),
            offset_ns=int(record["offset_ns"]),
            offset_uncertainty=Uncertainty.from_dict(record["offset_uncertainty"]),
            drift_ppm=_optional_float(record["drift_ppm"], field="drift_ppm"),
            drift_uncertainty=(
                None if drift_uncertainty is None else Uncertainty.from_dict(drift_uncertainty)
            ),
            basis=basis,
            residual_rms_ns=_optional_float(record["residual_rms_ns"], field="residual_rms_ns"),
            residual_max_ns=_optional_float(record["residual_max_ns"], field="residual_max_ns"),
            asymmetry_slope=_optional_float(record["asymmetry_slope"], field="asymmetry_slope"),
            asymmetry_detected=detected,
            stats=FitStats.from_dict(record["stats"]),
        )


_SEGMENT_KEYS = frozenset(
    {
        "index",
        "sample_count",
        "start_host_monotonic_ns",
        "end_host_monotonic_ns",
        "reference_host_monotonic_ns",
        "offset_ns",
        "offset_uncertainty",
        "drift_ppm",
        "drift_uncertainty",
        "basis",
        "residual_rms_ns",
        "residual_max_ns",
        "asymmetry_slope",
        "asymmetry_detected",
        "stats",
    }
)


@dataclass(frozen=True, slots=True)
class ClockStep:
    """A discontinuity between two adjacent segments — reported, never fitted."""

    at_host_monotonic_ns: int
    magnitude_ns: int
    uncertainty_ns: float
    before_segment: int
    after_segment: int
    #: Width of the unsampled gap the step is located inside. The step happened
    #: somewhere in there and nothing narrows it further.
    gap_ns: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "at_host_monotonic_ns": self.at_host_monotonic_ns,
            "magnitude_ns": self.magnitude_ns,
            "uncertainty_ns": self.uncertainty_ns,
            "before_segment": self.before_segment,
            "after_segment": self.after_segment,
            "gap_ns": self.gap_ns,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> ClockStep:
        _require_keys(record, _STEP_KEYS, what="clock step")
        return cls(
            at_host_monotonic_ns=_require_ns(
                record["at_host_monotonic_ns"], field="at_host_monotonic_ns"
            ),
            magnitude_ns=int(record["magnitude_ns"]),
            uncertainty_ns=_finite(float(record["uncertainty_ns"]), field="uncertainty_ns"),
            before_segment=_require_ns(record["before_segment"], field="before_segment"),
            after_segment=_require_ns(record["after_segment"], field="after_segment"),
            gap_ns=_require_ns(record["gap_ns"], field="gap_ns"),
        )


_STEP_KEYS = frozenset(
    {
        "at_host_monotonic_ns",
        "magnitude_ns",
        "uncertainty_ns",
        "before_segment",
        "after_segment",
        "gap_ns",
    }
)


# --------------------------------------------------------------------------- #
# Schedule
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ClockSchedule:
    """The sampling design a session must actually achieve to be certifiable.

    Both halves earn their place, and the tests measure both claims:

    * **Dense bursts at each end** minimise the drift uncertainty. The slope's
      statistical term is ``t * s / sqrt(sxx)`` and, for a fixed sample budget,
      ``sxx`` is maximised by putting the samples at the two extremes. A burst
      design beats uniform sampling at the same ``n``.
    * **~1 Hz cruise in between** is what makes a step visible. Bursts alone
      have no samples where a mid-session step would show, so a step becomes a
      slope, which is the failure this whole card exists to prevent.
    """

    burst_window_ns: int = BURST_WINDOW_NS
    min_burst_samples: int = MIN_BURST_SAMPLES
    max_cruise_gap_ns: int = MAX_CRUISE_GAP_NS
    min_span_ns: int = MIN_SPAN_NS

    def to_dict(self) -> dict[str, Any]:
        return {
            "burst_window_ns": self.burst_window_ns,
            "min_burst_samples": self.min_burst_samples,
            "max_cruise_gap_ns": self.max_cruise_gap_ns,
            "min_span_ns": self.min_span_ns,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> ClockSchedule:
        _require_keys(record, _SCHEDULE_KEYS, what="clock schedule")
        return cls(
            burst_window_ns=_require_ns(record["burst_window_ns"], field="burst_window_ns"),
            min_burst_samples=_require_ns(record["min_burst_samples"], field="min_burst_samples"),
            max_cruise_gap_ns=_require_ns(record["max_cruise_gap_ns"], field="max_cruise_gap_ns"),
            min_span_ns=_require_ns(record["min_span_ns"], field="min_span_ns"),
        )


_SCHEDULE_KEYS = frozenset(
    {"burst_window_ns", "min_burst_samples", "max_cruise_gap_ns", "min_span_ns"}
)

DEFAULT_SCHEDULE = ClockSchedule()


@dataclass(frozen=True, slots=True)
class ScheduleCoverage:
    """What the samples actually cover — derived from their times, never claimed.

    A prober cannot assert it kept the schedule; the times either show it or
    they do not. :attr:`shortfalls` is empty if and only if
    :attr:`meets_schedule` is true.
    """

    sample_count: int
    span_ns: int
    start_burst_count: int
    end_burst_count: int
    max_gap_ns: int
    meets_schedule: bool
    shortfalls: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "span_ns": self.span_ns,
            "start_burst_count": self.start_burst_count,
            "end_burst_count": self.end_burst_count,
            "max_gap_ns": self.max_gap_ns,
            "meets_schedule": self.meets_schedule,
            "shortfalls": list(self.shortfalls),
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> ScheduleCoverage:
        _require_keys(record, _COVERAGE_KEYS, what="schedule coverage")
        shortfalls = record["shortfalls"]
        if not isinstance(shortfalls, (list, tuple)) or any(
            not isinstance(item, str) for item in shortfalls
        ):
            raise ClockRefusedError(
                ClockRefusalReason.MALFORMED_RECORD,
                f"shortfalls must be a list of strings, got {shortfalls!r}",
            )
        meets = record["meets_schedule"]
        if not isinstance(meets, bool):
            raise ClockRefusedError(
                ClockRefusalReason.MALFORMED_RECORD,
                f"meets_schedule must be a bool, got {meets!r}",
            )
        if meets != (not shortfalls):
            raise ClockRefusedError(
                ClockRefusalReason.MALFORMED_RECORD,
                f"meets_schedule={meets!r} contradicts shortfalls={list(shortfalls)!r}",
            )
        return cls(
            sample_count=_require_ns(record["sample_count"], field="sample_count"),
            span_ns=_require_ns(record["span_ns"], field="span_ns"),
            start_burst_count=_require_ns(record["start_burst_count"], field="start_burst_count"),
            end_burst_count=_require_ns(record["end_burst_count"], field="end_burst_count"),
            max_gap_ns=_require_ns(record["max_gap_ns"], field="max_gap_ns"),
            meets_schedule=meets,
            shortfalls=tuple(shortfalls),
        )


_COVERAGE_KEYS = frozenset(
    {
        "sample_count",
        "span_ns",
        "start_burst_count",
        "end_burst_count",
        "max_gap_ns",
        "meets_schedule",
        "shortfalls",
    }
)


def _coverage(host_times: Sequence[int], schedule: ClockSchedule, label: str) -> ScheduleCoverage:
    ordered = sorted(host_times)
    span = ordered[-1] - ordered[0]
    start_cut = ordered[0] + schedule.burst_window_ns
    end_cut = ordered[-1] - schedule.burst_window_ns
    start_burst = sum(1 for value in ordered if value <= start_cut)
    end_burst = sum(1 for value in ordered if value >= end_cut)
    max_gap = 0
    for earlier, later in pairwise(ordered):
        max_gap = max(max_gap, later - earlier)
    shortfalls: list[str] = []
    if span < schedule.min_span_ns:
        shortfalls.append(
            f"{label}: span {span / _NS_PER_S:.1f}s is under the "
            f"{schedule.min_span_ns / _NS_PER_S:.0f}s needed to resolve drift"
        )
    if start_burst < schedule.min_burst_samples:
        shortfalls.append(
            f"{label}: opening burst has {start_burst} samples, needs "
            f"{schedule.min_burst_samples}"
        )
    if end_burst < schedule.min_burst_samples:
        shortfalls.append(
            f"{label}: closing burst has {end_burst} samples, needs "
            f"{schedule.min_burst_samples} — a map with no closing burst cannot "
            f"bound the drift over the tail of the session"
        )
    if max_gap > schedule.max_cruise_gap_ns:
        shortfalls.append(
            f"{label}: largest gap {max_gap / _NS_PER_S:.1f}s exceeds the "
            f"{schedule.max_cruise_gap_ns / _NS_PER_S:.0f}s cruise limit — a step "
            f"inside it cannot be located"
        )
    return ScheduleCoverage(
        sample_count=len(ordered),
        span_ns=span,
        start_burst_count=start_burst,
        end_burst_count=end_burst,
        max_gap_ns=max_gap,
        meets_schedule=not shortfalls,
        shortfalls=tuple(shortfalls),
    )


# --------------------------------------------------------------------------- #
# The fitter
# --------------------------------------------------------------------------- #


class _Prefix:
    """Cumulative sums so any segment's OLS costs O(1) during the step scan.

    The scan tries every split at every recursion level; recomputing fits from
    scratch would be O(n^2) per level, which at an hour of 1 Hz sampling is
    minutes of Python. These make it O(n).
    """

    __slots__ = ("b", "n", "x", "xx", "xy", "y", "yy")

    def __init__(self, xs: Sequence[float], ys: Sequence[float], bs: Sequence[float]) -> None:
        self.n = len(xs)
        self.x = [0.0]
        self.xx = [0.0]
        self.y = [0.0]
        self.xy = [0.0]
        self.yy = [0.0]
        self.b = [0.0]
        for index in range(self.n):
            x = xs[index]
            y = ys[index]
            self.x.append(self.x[-1] + x)
            self.xx.append(self.xx[-1] + x * x)
            self.y.append(self.y[-1] + y)
            self.xy.append(self.xy[-1] + x * y)
            self.yy.append(self.yy[-1] + y * y)
            self.b.append(self.b[-1] + bs[index])


@dataclass(frozen=True, slots=True)
class _SegmentFit:
    """Fast (prefix-sum) segment fit used only for step scanning."""

    count: int
    x_mean: float
    y_mean: float
    sxx: float
    slope: float
    ssr: float
    bracket_mean: float

    def predict(self, x: float) -> float:
        return self.y_mean + self.slope * (x - self.x_mean)

    def se_mean(self, x: float) -> float | None:
        if self.count < 3:
            return None
        residual_std = math.sqrt(self.ssr / (self.count - 2))
        leverage = 1.0 / self.count
        if self.sxx > 0.0:
            leverage += (x - self.x_mean) ** 2 / self.sxx
        return _t_critical(self.count - 2) * residual_std * math.sqrt(leverage)


def _fast_fit(prefix: _Prefix, start: int, stop: int) -> _SegmentFit:
    count = stop - start
    sum_x = prefix.x[stop] - prefix.x[start]
    sum_xx = prefix.xx[stop] - prefix.xx[start]
    sum_y = prefix.y[stop] - prefix.y[start]
    sum_xy = prefix.xy[stop] - prefix.xy[start]
    sum_yy = prefix.yy[stop] - prefix.yy[start]
    sum_b = prefix.b[stop] - prefix.b[start]
    x_mean = sum_x / count
    y_mean = sum_y / count
    sxx = max(sum_xx - sum_x * sum_x / count, 0.0)
    sxy = sum_xy - sum_x * sum_y / count
    syy = max(sum_yy - sum_y * sum_y / count, 0.0)
    slope = sxy / sxx if sxx > 0.0 else 0.0
    ssr = max(syy - (sxy * sxy / sxx if sxx > 0.0 else 0.0), 0.0)
    return _SegmentFit(
        count=count,
        x_mean=x_mean,
        y_mean=y_mean,
        sxx=sxx,
        slope=slope,
        ssr=ssr,
        bracket_mean=sum_b / count,
    )


def _step_evidence(
    prefix: _Prefix, xs: Sequence[float], start: int, split: int, stop: int
) -> tuple[float, float]:
    """``(magnitude, threshold)`` for a candidate split.

    The threshold adds the two segments' statistical prediction terms in
    quadrature (independent noise) and their systematic bracket bounds
    arithmetically (worst-case biases add), plus the one-nanosecond quantum of
    the sample fields. A split is declared only when the observed discontinuity
    clears all of it.
    """

    before = _fast_fit(prefix, start, split)
    after = _fast_fit(prefix, split, stop)
    boundary = (xs[split - 1] + xs[split]) / 2.0
    magnitude = after.predict(boundary) - before.predict(boundary)
    se_before = before.se_mean(boundary) or 0.0
    se_after = after.se_mean(boundary) or 0.0
    statistical = math.sqrt(se_before * se_before + se_after * se_after)
    systematic = before.bracket_mean + after.bracket_mean
    return magnitude, statistical + systematic + STEP_FLOOR_NS


def _find_splits(
    prefix: _Prefix, xs: Sequence[float], start: int, stop: int, found: list[int]
) -> None:
    """Binary segmentation: split at the most significant discontinuity, recurse."""

    if len(found) >= MAX_STEPS:
        return
    if stop - start < 2 * MIN_SEGMENT_SAMPLES:
        return
    best_split = -1
    best_ratio = 1.0
    for split in range(start + MIN_SEGMENT_SAMPLES, stop - MIN_SEGMENT_SAMPLES + 1):
        magnitude, threshold = _step_evidence(prefix, xs, start, split, stop)
        if threshold <= 0.0:
            continue
        ratio = abs(magnitude) / threshold
        if ratio > best_ratio:
            best_ratio = ratio
            best_split = split
    if best_split < 0:
        return
    found.append(best_split)
    _find_splits(prefix, xs, start, best_split, found)
    _find_splits(prefix, xs, best_split, stop, found)


def _fit_segment(
    index: int,
    host_mids: Sequence[int],
    offsets: Sequence[int],
    brackets: Sequence[float | None],
    start: int,
    stop: int,
) -> ClockSegment:
    """Exact two-pass fit for a final segment.

    The scan's prefix sums are fine for thresholds but can lose most of their
    significant digits to cancellation when the fit is nearly perfect
    (``ssr`` is then a difference of two large, nearly equal numbers). Final
    segments therefore recompute residuals directly, which is O(n) and exact.
    """

    count = stop - start
    x_base = host_mids[start]
    y_base = offsets[start]
    xs = [(host_mids[i] - x_base) / _NS_PER_S for i in range(start, stop)]
    ys = [float(offsets[i] - y_base) for i in range(start, stop)]
    segment_brackets = [brackets[i] for i in range(start, stop)]
    has_bracket = all(value is not None for value in segment_brackets)
    x_mean = sum(xs) / count
    y_mean = sum(ys) / count
    sxx = sum((x - x_mean) ** 2 for x in xs)
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx > 0.0 else 0.0

    bracket_mean: float | None = None
    bracket_weighted: float | None = None
    if has_bracket:
        values = [float(value) for value in segment_brackets if value is not None]
        bracket_mean = sum(values) / count
        bracket_weighted = sum(abs(x - x_mean) * b for x, b in zip(xs, values))

    if count == 1:
        basis = FitBasis.SINGLE_SAMPLE
    elif sxx <= 0.0:
        basis = FitBasis.NO_SPAN
    elif count == 2:
        basis = FitBasis.TWO_POINT
    else:
        basis = FitBasis.OLS

    residuals = [y - (y_mean + slope * (x - x_mean)) for x, y in zip(xs, ys)]
    residual_std: float | None = None
    t_critical: float | None = None
    residual_rms: float | None = None
    residual_max: float | None = None
    if basis is FitBasis.OLS:
        ssr = sum(value * value for value in residuals)
        residual_std = math.sqrt(ssr / (count - 2))
        t_critical = _t_critical(count - 2)
        residual_rms = math.sqrt(ssr / count)
        residual_max = max(abs(value) for value in residuals)

    offset_statistical: float | None = None
    if residual_std is not None and t_critical is not None:
        offset_statistical = t_critical * residual_std / math.sqrt(count)
    offset_uncertainty = Uncertainty(
        unit="ns",
        systematic=bracket_mean,
        statistical=(
            None if offset_statistical is None else _finite(offset_statistical, field="offset")
        ),
    )

    drift_ppm: float | None = None
    drift_uncertainty: Uncertainty | None = None
    if basis in (FitBasis.OLS, FitBasis.TWO_POINT):
        drift_ppm = _finite(slope / 1000.0, field="drift_ppm")
        drift_statistical: float | None = None
        if residual_std is not None and t_critical is not None and sxx > 0.0:
            drift_statistical = t_critical * residual_std / math.sqrt(sxx) / 1000.0
        drift_systematic: float | None = None
        if bracket_weighted is not None and sxx > 0.0:
            drift_systematic = bracket_weighted / sxx / 1000.0
        drift_uncertainty = Uncertainty(
            unit="ppm",
            systematic=(
                None if drift_systematic is None else _finite(drift_systematic, field="drift")
            ),
            statistical=(
                None if drift_statistical is None else _finite(drift_statistical, field="drift")
            ),
        )

    asymmetry_slope: float | None = None
    asymmetry_detected = False
    if has_bracket and basis is FitBasis.OLS:
        values = [float(value) for value in segment_brackets if value is not None]
        bracket_centre = sum(values) / count
        sbb = sum((b - bracket_centre) ** 2 for b in values)
        if sbb > 0.0:
            sbr = sum((b - bracket_centre) * r for b, r in zip(values, residuals))
            # The wedge slope is per unit BRACKET; per unit round trip it halves,
            # so the reported figure is 2*alpha - 1 for a request-leg fraction
            # alpha. Reported, never corrected for.
            asymmetry_slope = _finite(sbr / sbb, field="asymmetry_slope")
            if residual_std is not None and t_critical is not None:
                slope_error = t_critical * residual_std / math.sqrt(sbb)
                asymmetry_detected = abs(asymmetry_slope) > slope_error

    return ClockSegment(
        index=index,
        sample_count=count,
        start_host_monotonic_ns=host_mids[start],
        end_host_monotonic_ns=host_mids[stop - 1],
        reference_host_monotonic_ns=x_base + round(x_mean * _NS_PER_S),
        offset_ns=y_base + round(y_mean),
        offset_uncertainty=offset_uncertainty,
        drift_ppm=drift_ppm,
        drift_uncertainty=drift_uncertainty,
        basis=basis,
        residual_rms_ns=residual_rms,
        residual_max_ns=residual_max,
        asymmetry_slope=asymmetry_slope,
        asymmetry_detected=asymmetry_detected,
        stats=FitStats(
            sample_count=count,
            x_base_ns=x_base,
            y_base_ns=y_base,
            x_mean_s=x_mean,
            sxx_s2=sxx,
            residual_std_ns=residual_std,
            t_critical=t_critical,
            bracket_mean_ns=bracket_mean,
            bracket_weighted_ns=bracket_weighted,
        ),
    )


class RelationKind(str, Enum):
    """Which pair of clocks a relation maps."""

    #: A device's own clock against the recording host's monotonic clock. This
    #: is what makes two devices' stamps comparable.
    DEVICE_TO_HOST_MONOTONIC = "device_source_to_host_monotonic"
    #: The recording host's wall clock against its own monotonic clock. This is
    #: what gives ``received_monotonic_ns`` — whose epoch is arbitrary and
    #: per-boot — a meaning outside this boot.
    HOST_REALTIME_TO_HOST_MONOTONIC = "host_realtime_to_host_monotonic"


@dataclass(frozen=True, slots=True)
class ClockRelation:
    """One clock pair: its segments, its steps, and what the samples covered."""

    kind: RelationKind
    device: SourceDevice | None
    sample_count: int
    first_host_monotonic_ns: int
    last_host_monotonic_ns: int
    segments: tuple[ClockSegment, ...]
    steps: tuple[ClockStep, ...]
    coverage: ScheduleCoverage
    steps_truncated: bool

    @property
    def label(self) -> str:
        return f"{self.device.value}:{self.kind.value}" if self.device else self.kind.value

    @property
    def primary_segment(self) -> ClockSegment:
        """The longest-span segment: the one a summary should quote."""

        return max(self.segments, key=lambda segment: (segment.span_s, segment.sample_count))

    @property
    def is_bounded(self) -> bool:
        return bool(self.segments) and all(segment.is_bounded for segment in self.segments)

    def offset_at(self, host_monotonic_ns: int) -> ClockReading:
        """Place an offset at a host instant, choosing the right segment.

        An instant inside the unsampled gap around a step is ambiguous by the
        step magnitude; rather than silently picking a side, the magnitude is
        added to the systematic term and :attr:`ClockReading.at_step_boundary`
        is set.
        """

        instant = _require_ns(host_monotonic_ns, field="host_monotonic_ns")
        chosen = self.segments[0]
        for segment in self.segments:
            if instant >= segment.start_host_monotonic_ns:
                chosen = segment
        reading = chosen.offset_at(instant)
        for step in self.steps:
            gap_start = step.at_host_monotonic_ns - step.gap_ns // 2
            gap_end = step.at_host_monotonic_ns + step.gap_ns // 2
            if gap_start <= instant <= gap_end:
                systematic = reading.uncertainty.systematic
                widened = None if systematic is None else systematic + abs(step.magnitude_ns) / 2.0
                return ClockReading(
                    host_monotonic_ns=reading.host_monotonic_ns,
                    offset_ns=reading.offset_ns,
                    uncertainty=Uncertainty(
                        unit=reading.uncertainty.unit,
                        systematic=widened,
                        statistical=reading.uncertainty.statistical,
                    ),
                    segment_index=reading.segment_index,
                    extrapolated=reading.extrapolated,
                    at_step_boundary=True,
                )
        return reading

    def target_at(self, host_monotonic_ns: int) -> ClockReading:
        """The TARGET clock's reading at a host instant (device or wall clock)."""

        reading = self.offset_at(host_monotonic_ns)
        return ClockReading(
            host_monotonic_ns=reading.host_monotonic_ns,
            offset_ns=reading.host_monotonic_ns + reading.offset_ns,
            uncertainty=reading.uncertainty,
            segment_index=reading.segment_index,
            extrapolated=reading.extrapolated,
            at_step_boundary=reading.at_step_boundary,
        )

    def host_monotonic_for(self, target_ns: int) -> ClockReading:
        """The inverse: which host instant a device/wall stamp corresponds to.

        This is the direction PS-B needs to place a recorded device stamp on the
        session timeline. Solved in closed form per segment —
        ``target = h + a + b*(h - h_ref)`` gives ``h = (target - a + b*h_ref) /
        (1 + b)`` — with the segment chosen by which one's own span contains the
        answer, falling back to the segment whose target range is nearest.
        """

        target = _require_ns(target_ns, field="target_ns")
        best: ClockReading | None = None
        for segment in self.segments:
            slope = 0.0 if segment.drift_ppm is None else segment.drift_ppm * 1000.0 / _NS_PER_S
            reference = segment.reference_host_monotonic_ns
            intercept = float(segment.offset_ns)
            host = (target - intercept + slope * reference) / (1.0 + slope)
            candidate = segment.offset_at(round(host))
            if not candidate.extrapolated:
                return self.offset_at(candidate.host_monotonic_ns)
            if best is None:
                best = candidate
        if best is None:
            raise ClockRefusedError(
                ClockRefusalReason.NO_SAMPLES, f"{self.label}: relation has no segments"
            )
        return self.offset_at(best.host_monotonic_ns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "device": None if self.device is None else self.device.value,
            "sample_count": self.sample_count,
            "first_host_monotonic_ns": self.first_host_monotonic_ns,
            "last_host_monotonic_ns": self.last_host_monotonic_ns,
            "segments": [segment.to_dict() for segment in self.segments],
            "steps": [step.to_dict() for step in self.steps],
            "coverage": self.coverage.to_dict(),
            "steps_truncated": self.steps_truncated,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> ClockRelation:
        _require_keys(record, _RELATION_KEYS, what="clock relation")
        try:
            kind = RelationKind(record["kind"])
            device = None if record["device"] is None else SourceDevice(record["device"])
        except ValueError as exc:
            raise ClockRefusedError(
                ClockRefusalReason.MALFORMED_RECORD, f"undecodable relation enum: {exc}"
            ) from exc
        truncated = record["steps_truncated"]
        if not isinstance(truncated, bool):
            raise ClockRefusedError(
                ClockRefusalReason.MALFORMED_RECORD,
                f"steps_truncated must be a bool, got {truncated!r}",
            )
        segments = tuple(ClockSegment.from_dict(item) for item in record["segments"])
        if not segments:
            raise ClockRefusedError(
                ClockRefusalReason.NO_SAMPLES, "a relation must carry at least one segment"
            )
        return cls(
            kind=kind,
            device=device,
            sample_count=_require_ns(record["sample_count"], field="sample_count"),
            first_host_monotonic_ns=_require_ns(
                record["first_host_monotonic_ns"], field="first_host_monotonic_ns"
            ),
            last_host_monotonic_ns=_require_ns(
                record["last_host_monotonic_ns"], field="last_host_monotonic_ns"
            ),
            segments=segments,
            steps=tuple(ClockStep.from_dict(item) for item in record["steps"]),
            coverage=ScheduleCoverage.from_dict(record["coverage"]),
            steps_truncated=truncated,
        )


_RELATION_KEYS = frozenset(
    {
        "kind",
        "device",
        "sample_count",
        "first_host_monotonic_ns",
        "last_host_monotonic_ns",
        "segments",
        "steps",
        "coverage",
        "steps_truncated",
    }
)


def _build_relation(
    kind: RelationKind,
    device: SourceDevice | None,
    host_mids: Sequence[int],
    offsets: Sequence[int],
    brackets: Sequence[float | None],
    schedule: ClockSchedule,
    splits: Sequence[int] | None = None,
) -> ClockRelation:
    order = sorted(range(len(host_mids)), key=lambda i: host_mids[i])
    mids = [host_mids[i] for i in order]
    values = [offsets[i] for i in order]
    widths = [brackets[i] for i in order]
    label = f"{device.value}:{kind.value}" if device else kind.value

    x_base = mids[0]
    y_base = values[0]
    xs = [(value - x_base) / _NS_PER_S for value in mids]
    ys = [float(value - y_base) for value in values]
    # An unknown bracket contributes 0 to the step threshold, which makes the
    # scan MORE willing to declare a step. That is the safe direction: an
    # over-declared step splits the fit into two honest segments, while a missed
    # step becomes drift and corrupts every timestamp on both sides of it.
    scan_widths = [0.0 if width is None else width for width in widths]

    if splits is None:
        found: list[int] = []
        prefix = _Prefix(xs, ys, scan_widths)
        _find_splits(prefix, xs, 0, len(xs), found)
    else:
        found = []
        for split in splits:
            if not isinstance(split, int) or isinstance(split, bool):
                raise ClockRefusedError(
                    ClockRefusalReason.MALFORMED_RECORD,
                    f"{label}: split {split!r} is not an int sample index",
                )
            if not MIN_SEGMENT_SAMPLES <= split <= len(mids) - MIN_SEGMENT_SAMPLES:
                raise ClockRefusedError(
                    ClockRefusalReason.MALFORMED_RECORD,
                    f"{label}: split at {split} leaves a segment shorter than "
                    f"{MIN_SEGMENT_SAMPLES} samples, which cannot bound its own fit",
                )
            found.append(split)
    truncated = len(found) >= MAX_STEPS
    boundaries = sorted(found)

    bounds = [0, *boundaries, len(mids)]
    segments = tuple(
        _fit_segment(index, mids, values, widths, start, stop)
        for index, (start, stop) in enumerate(pairwise(bounds))
    )

    steps: list[ClockStep] = []
    for position, split in enumerate(boundaries):
        before = segments[position]
        after = segments[position + 1]
        boundary_ns = (mids[split - 1] + mids[split]) // 2
        before_reading = before.offset_at(boundary_ns)
        after_reading = after.offset_at(boundary_ns)
        magnitude = after_reading.offset_ns - before_reading.offset_ns
        statistical = math.sqrt(
            (before_reading.uncertainty.statistical or 0.0) ** 2
            + (after_reading.uncertainty.statistical or 0.0) ** 2
        )
        systematic = (before_reading.uncertainty.systematic or 0.0) + (
            after_reading.uncertainty.systematic or 0.0
        )
        steps.append(
            ClockStep(
                at_host_monotonic_ns=boundary_ns,
                magnitude_ns=magnitude,
                uncertainty_ns=_finite(statistical + systematic, field="step uncertainty"),
                before_segment=before.index,
                after_segment=after.index,
                gap_ns=mids[split] - mids[split - 1],
            )
        )

    return ClockRelation(
        kind=kind,
        device=device,
        sample_count=len(mids),
        first_host_monotonic_ns=mids[0],
        last_host_monotonic_ns=mids[-1],
        segments=segments,
        steps=tuple(steps),
        coverage=_coverage(mids, schedule, label),
        steps_truncated=truncated,
    )


def fit_relation(
    samples: Sequence[ClockSample],
    *,
    device: SourceDevice,
    schedule: ClockSchedule = DEFAULT_SCHEDULE,
    splits: Sequence[int] | None = None,
) -> ClockRelation:
    """Fit ONE device-to-host relation, without building a whole map.

    Added for card PS-I: a sync ritual produces samples for one channel pair at
    a time, and that pair's offset/drift/steps are the deliverable long before a
    session-wide map exists. Both uncertainty halves and the fit itself are the
    same code the map uses — a second fitter is exactly how two numbers that
    must agree stop agreeing.

    ``splits`` gives the segment boundaries explicitly, as indices into the
    samples **sorted by host instant**, and skips the automatic step scan. It
    exists because that scan is the wrong test for *clustered* evidence, and
    PS-I measured why: with all the samples in two 8 s ritual bursts an hour
    apart, a segment covering one burst has a slope determined only by 8 s of
    data, so extrapolating it to the burst boundary carries ±1304 ms — a real
    500 ms step cannot clear that, while pairs of unconstrained extrapolated
    lines cross each other often enough to declare steps that are not there
    (measured: two declared, one of them 25 ms ± 2511 ms). The right model for
    clustered evidence is a COMMON drift with a per-segment offset, which
    ``syncevents.py`` fits over the per-ritual offsets; the boundaries it
    establishes come back through here. Passing ``splits`` therefore makes the
    segmentation the caller's claim, and the caller must be able to defend it.
    """

    ordered = list(samples)
    if not ordered:
        raise ClockRefusedError(
            ClockRefusalReason.NO_SAMPLES,
            "a relation needs at least one sample — an unmapped pair's offset is "
            "not recoverable and must not be reported as zero",
        )
    for index, sample in enumerate(ordered):
        if not isinstance(sample, ClockSample):
            raise ClockRefusedError(
                ClockRefusalReason.MALFORMED_RECORD,
                f"sample {index} must be a ClockSample, got {type(sample).__name__}",
            )
        if sample.device is not device:
            raise ClockRefusedError(
                ClockRefusalReason.DEVICE_NOT_TYPED,
                f"sample {index} is from {sample.device.value}, not {device.value} — "
                f"mixing devices into one relation would average two clocks",
            )
    return _build_relation(
        RelationKind.DEVICE_TO_HOST_MONOTONIC,
        device,
        [sample.host_mid_ns for sample in ordered],
        [sample.offset_ns for sample in ordered],
        [sample.bracket_ns for sample in ordered],
        schedule,
        splits,
    )


# --------------------------------------------------------------------------- #
# The map
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ClockMapV1:
    """Everything needed to place one session's timestamps against each other.

    Self-sufficient by design: a decoded map converts timestamps with no access
    to the samples, the fitter, or this process, because that is the only form
    of the artifact that survives six months.
    """

    session_id: str
    created_at_utc: str
    host_id: str
    origin: EvidenceOrigin
    fixture_label: str | None
    relations: tuple[ClockRelation, ...]
    schedule: ClockSchedule
    sample_count: int
    sample_digest: str
    does_not_prove: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.session_id, field="session_id")
        _require_text(self.host_id, field="host_id")
        _require_text(self.sample_digest, field="sample_digest")
        if not _ISO_UTC.match(self.created_at_utc or ""):
            raise ClockRefusedError(
                ClockRefusalReason.MALFORMED_TIMESTAMP,
                f"created_at_utc must be ISO-8601 UTC (…Z), got {self.created_at_utc!r}",
            )
        if not isinstance(self.origin, EvidenceOrigin):
            raise ClockRefusedError(
                ClockRefusalReason.ORIGIN_NOT_TYPED,
                f"origin must be an EvidenceOrigin member, got "
                f"{type(self.origin).__name__} {self.origin!r} — a string is not a "
                f"declaration",
            )
        if self.origin is EvidenceOrigin.UNKNOWN:
            raise ClockRefusedError(
                ClockRefusalReason.ORIGIN_NOT_DECLARED,
                "UNKNOWN is not an origin a clock map may be recorded under — "
                "declare PHYSICAL, SIMULATION or REPLAY",
            )
        if self.origin in SYNTHETIC_ORIGINS:
            if not isinstance(self.fixture_label, str) or not self.fixture_label.strip():
                raise ClockRefusedError(
                    ClockRefusalReason.FIXTURE_LABEL_MISSING,
                    f"origin {self.origin.value} requires a non-empty fixture_label — a "
                    f"rehearsal map must be impossible to mistake for a session map",
                )
        elif self.fixture_label is not None:
            raise ClockRefusedError(
                ClockRefusalReason.FIXTURE_LABEL_FORBIDDEN,
                f"origin {self.origin.value} must not carry a fixture_label, got "
                f"{self.fixture_label!r}",
            )
        if not self.relations:
            raise ClockRefusedError(
                ClockRefusalReason.NO_SAMPLES, "a clock map must carry at least one relation"
            )
        if not self.does_not_prove or any(
            not isinstance(item, str) or not item.strip() for item in self.does_not_prove
        ):
            raise ClockRefusedError(
                ClockRefusalReason.EMPTY_FIELD,
                "does_not_prove must be a non-empty tuple of non-empty strings",
            )

    @property
    def devices(self) -> tuple[SourceDevice, ...]:
        return tuple(
            relation.device
            for relation in self.relations
            if relation.kind is RelationKind.DEVICE_TO_HOST_MONOTONIC
            and relation.device is not None
        )

    def relation_for(self, device: SourceDevice) -> ClockRelation:
        for relation in self.relations:
            if (
                relation.kind is RelationKind.DEVICE_TO_HOST_MONOTONIC
                and relation.device is device
            ):
                return relation
        raise ClockRefusedError(
            ClockRefusalReason.NO_SAMPLES,
            f"no clock relation for {getattr(device, 'value', device)!r} — an "
            f"unmapped device's timestamps are not recoverable, and this map does "
            f"not pretend otherwise",
        )

    @property
    def host_relation(self) -> ClockRelation | None:
        for relation in self.relations:
            if relation.kind is RelationKind.HOST_REALTIME_TO_HOST_MONOTONIC:
                return relation
        return None

    @property
    def certification_shortfalls(self) -> tuple[str, ...]:
        """Every reason this map may not be trusted for conversion. Empty = trusted."""

        shortfalls: list[str] = []
        if not self.devices:
            shortfalls.append("no device relation: nothing is mapped to the host clock")
        if self.host_relation is None:
            shortfalls.append(
                "no host realtime relation: the monotonic epoch is arbitrary and "
                "this session cannot be placed in wall time"
            )
        for relation in self.relations:
            if not relation.is_bounded:
                shortfalls.append(f"{relation.label}: fit is not bounded (see basis/uncertainty)")
            shortfalls.extend(relation.coverage.shortfalls)
            if relation.steps_truncated:
                shortfalls.append(
                    f"{relation.label}: step scan hit the {MAX_STEPS}-step cap; the "
                    f"clock is stepping too often to fit"
                )
        return tuple(shortfalls)

    @property
    def is_certifiable(self) -> bool:
        """Fails closed: anything unmeasured, unbounded, or uncovered says no."""

        return not self.certification_shortfalls

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CLOCK_MAP_SCHEMA,
            "session_id": self.session_id,
            "created_at_utc": self.created_at_utc,
            "host_id": self.host_id,
            "origin": self.origin.value,
            "fixture_label": self.fixture_label,
            "relations": [relation.to_dict() for relation in self.relations],
            "schedule": self.schedule.to_dict(),
            "sample_count": self.sample_count,
            "sample_digest": self.sample_digest,
            "is_certifiable": self.is_certifiable,
            "certification_shortfalls": list(self.certification_shortfalls),
            "does_not_prove": list(self.does_not_prove),
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> ClockMapV1:
        """Decode, recomputing every derived answer rather than trusting it.

        ``is_certifiable`` and ``certification_shortfalls`` are written for a
        human reader and thrown away here: hand-editing ``"is_certifiable":
        true`` into a map file changes nothing, because the value is derived
        from the fits on the way back out.
        """

        _require_keys(record, _MAP_KEYS, what="clock map")
        if record["schema"] != CLOCK_MAP_SCHEMA:
            raise ClockRefusedError(
                ClockRefusalReason.SCHEMA_MISMATCH,
                f"expected schema {CLOCK_MAP_SCHEMA!r}, got {record['schema']!r}",
            )
        try:
            origin = EvidenceOrigin(record["origin"])
        except ValueError as exc:
            raise ClockRefusedError(
                ClockRefusalReason.ORIGIN_NOT_TYPED, f"undecodable origin: {exc}"
            ) from exc
        does_not_prove = record["does_not_prove"]
        if not isinstance(does_not_prove, (list, tuple)):
            raise ClockRefusedError(
                ClockRefusalReason.MALFORMED_RECORD,
                f"does_not_prove must be a list of strings, got {does_not_prove!r}",
            )
        return cls(
            session_id=str(record["session_id"]),
            created_at_utc=str(record["created_at_utc"]),
            host_id=str(record["host_id"]),
            origin=origin,
            fixture_label=record["fixture_label"],
            relations=tuple(ClockRelation.from_dict(item) for item in record["relations"]),
            schedule=ClockSchedule.from_dict(record["schedule"]),
            sample_count=_require_ns(record["sample_count"], field="sample_count"),
            sample_digest=str(record["sample_digest"]),
            does_not_prove=tuple(does_not_prove),
        )


_MAP_KEYS = frozenset(
    {
        "schema",
        "session_id",
        "created_at_utc",
        "host_id",
        "origin",
        "fixture_label",
        "relations",
        "schedule",
        "sample_count",
        "sample_digest",
        "is_certifiable",
        "certification_shortfalls",
        "does_not_prove",
    }
)


def clock_map_digest(clock_map: ClockMapV1) -> str:
    """SHA-256 over the canonical map. PS-B binds this into the sidecar."""

    return hashlib.sha256(canonical_json(clock_map.to_dict()).encode("utf-8")).hexdigest()


def build_clock_map(
    samples: Iterable[ClockSample],
    *,
    session_id: str,
    created_at_utc: str,
    host_id: str,
    origin: EvidenceOrigin,
    fixture_label: str | None = None,
    schedule: ClockSchedule = DEFAULT_SCHEDULE,
    does_not_prove: Sequence[str] = DEFAULT_DOES_NOT_PROVE,
) -> ClockMapV1:
    """Fit a clock map from live offset triples.

    One relation per device, plus one for the host's own wall clock against its
    monotonic clock — the pair that gives every ``received_monotonic_ns`` in the
    bags a meaning outside this boot.
    """

    ordered = list(samples)
    for index, sample in enumerate(ordered):
        if not isinstance(sample, ClockSample):
            raise ClockRefusedError(
                ClockRefusalReason.MALFORMED_RECORD,
                f"sample {index} must be a ClockSample, got {type(sample).__name__}",
            )
    if not ordered:
        raise ClockRefusedError(
            ClockRefusalReason.NO_SAMPLES,
            "a clock map needs at least one sample — an unmapped session's "
            "cross-device timestamps are not recoverable, and an empty map must "
            "not be able to claim otherwise",
        )

    by_device: dict[SourceDevice, list[ClockSample]] = {}
    for sample in ordered:
        by_device.setdefault(sample.device, []).append(sample)

    relations: list[ClockRelation] = []
    for device in sorted(by_device, key=lambda item: item.value):
        group = by_device[device]
        relations.append(
            _build_relation(
                RelationKind.DEVICE_TO_HOST_MONOTONIC,
                device,
                [sample.host_mid_ns for sample in group],
                [sample.offset_ns for sample in group],
                [sample.bracket_ns for sample in group],
                schedule,
            )
        )
    relations.append(
        _build_relation(
            RelationKind.HOST_REALTIME_TO_HOST_MONOTONIC,
            None,
            [sample.host_pair_mid_ns for sample in ordered],
            [sample.host_pair_offset_ns for sample in ordered],
            [
                None if sample.host_pair_bracket_ns is None else sample.host_pair_bracket_ns / 2.0
                for sample in ordered
            ],
            schedule,
        )
    )

    return ClockMapV1(
        session_id=session_id,
        created_at_utc=created_at_utc,
        host_id=host_id,
        origin=origin,
        fixture_label=fixture_label,
        relations=tuple(relations),
        schedule=schedule,
        sample_count=len(ordered),
        sample_digest=sample_digest(ordered),
        does_not_prove=tuple(does_not_prove),
    )


def sidecar_clock_block(
    clock_map: ClockMapV1, *, source_clock: str = "sensor"
) -> dict[str, Any]:
    """The ``clocks`` block PS-B hands to ``bags/schema.py:make_manifest``.

    Fills in ``recording_monotonic_origin_ns``, which ``default_clocks()`` leaves
    at ``0`` — the placeholder that makes every recorded monotonic stamp
    meaningless — with the first instant this map actually observed, and carries
    the map's digest so the bag is bound to the fit that can interpret it.
    """

    if source_clock not in {"sim", "sensor", "ros"}:
        raise ClockRefusedError(
            ClockRefusalReason.MALFORMED_RECORD,
            f"unsupported source_clock: {source_clock!r} (bags/schema.py accepts "
            f"'sim', 'sensor', 'ros')",
        )
    origin_ns = min(relation.first_host_monotonic_ns for relation in clock_map.relations)
    block = {
        "source_clock": source_clock,
        "recording_monotonic_origin_ns": origin_ns,
        "note": (
            "Cross-device times are recoverable only through the bound clock map: "
            "host monotonic has a per-boot arbitrary epoch and device clocks are "
            "free-running. Do not compare stamps from two devices without it."
        ),
        "clock_map_schema": CLOCK_MAP_SCHEMA,
        "clock_map_sha256": clock_map_digest(clock_map),
        "clock_map_sample_sha256": clock_map.sample_digest,
        "clock_map_certifiable": clock_map.is_certifiable,
        "clock_map_shortfalls": list(clock_map.certification_shortfalls),
        "clock_map_devices": [device.value for device in clock_map.devices],
    }
    missing = _BAG_REQUIRED_CLOCK_KEYS - set(block)
    if missing:
        raise ClockRefusedError(
            ClockRefusalReason.MALFORMED_RECORD,
            f"clocks block is missing bag-schema keys: {sorted(missing)}",
        )
    return block


# --------------------------------------------------------------------------- #
# Probe requirements, reporting, CLI
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ProbeRequirement:
    """How one device's clock is read, and what that needs to be installed.

    :attr:`modules` are alternatives — any one satisfies the probe. Presence is
    tested with :func:`importlib.util.find_spec`, which is a lookup on the
    import path and never executes the module: this process must not be able to
    load a vendor SDK even by accident.

    Card ENV-1: a module is **not** a device. ``pyrealsense2`` was installed
    into ``.parcel`` on 2026-08-22 for the desk-camera venue, and on the day it
    landed :func:`probe_availability` began reporting the D455 clock probe
    PRESENT on a host with no camera — a false claim in the one report whose
    whole job is to say which offsets this session can still recover.
    :attr:`device_nodes` is the second, independent fact, and it is answered by
    a ``/dev`` census so this module keeps its promise to import no vendor SDK.
    """

    device: SourceDevice
    method: str
    modules: tuple[str, ...]
    note: str
    #: False when the device exposes NO clock that can be asked for a reading —
    #: the offset must then come from PS-I's bracketed physical sync ritual.
    #: Defaults True so a new device must be argued INTO the ritual path rather
    #: than falling into it silently.
    interrogable: bool = True
    #: ``/dev`` glob patterns the hardware creates when it is plugged into THIS
    #: host. Empty means the filesystem cannot answer — a dog on a network makes
    #: no node — and the probe then rests on its modules alone.
    device_nodes: tuple[str, ...] = ()


PROBE_REQUIREMENTS: Mapping[SourceDevice, ProbeRequirement] = MappingProxyType(
    {
        SourceDevice.GO2: ProbeRequirement(
            device=SourceDevice.GO2,
            method=(
                "RITUAL ONLY — no interrogation exists. Sync-event correspondences "
                "from `syncevents.py` (taps/flashes/button in `lowstate` at 500 Hz)"
            ),
            modules=("rclpy", "cyclonedds"),
            note=(
                "CORRECTED by PS-I. The dog exposes no queryable clock and no "
                "round-trip primitive, and `lowstate` has NO timestamp field — only "
                "`tick`, a uint32 ms counter that wraps and starts anywhere, so it "
                "is a wrapping counter with an arbitrary epoch and never an anchor. "
                "`SportModeState.stamp` is the only device TimeSpec the dog emits "
                "and its channel is service-gated. The modules listed here are what "
                "it takes to RECEIVE those messages at all; the offset itself comes "
                "from the bracketed sync ritual"
            ),
            interrogable=False,
        ),
        SourceDevice.D455: ProbeRequirement(
            device=SourceDevice.D455,
            method="frame metadata timestamp plus its timestamp DOMAIN",
            modules=("pyrealsense2",),
            device_nodes=("video*",),
            note=(
                "the domain must be recorded with the value: HARDWARE_CLOCK, "
                "SYSTEM_TIME and GLOBAL_TIME are three different clocks, and in "
                "GLOBAL_TIME librealsense has already applied a host-side mapping "
                "of its own that we would otherwise apply twice"
            ),
        ),
        SourceDevice.L2: ProbeRequirement(
            device=SourceDevice.L2,
            method="cloud/IMU packet stamp over the add-on L2's own transport",
            modules=("unitree_lidar_sdk_pybind",),
            # Verifier correction (Fable, ENV-1): NO device_nodes here. The L2
            # is reached over UDP *or* /dev/ttyACM0 (the note below), so the
            # filesystem cannot attest it — exactly why ``L2Ingest`` declares
            # no node either. Gating on ttyACM* read the L2 ABSENT on the
            # planned Ethernet wiring with its binding present.
            note=(
                "the add-on L2 is `unilidar_sdk2` over UDP or /dev/ttyACM0, NOT the "
                "built-in unit on `utlidar/*`; the python binding's import name is "
                "unconfirmed, so this probe reports ABSENT until PS-D resolves it "
                "against the installed SDK"
            ),
        ),
        SourceDevice.ORIN: ProbeRequirement(
            device=SourceDevice.ORIN,
            method="host clock pair (this IS the recording host)",
            modules=(),
            note=(
                "the Orin needs no SDK: its relation is the host realtime-vs-"
                "monotonic fit every map carries, and it is the one clock we can "
                "correct at the session"
            ),
        ),
    }
)


def device_nodes_present(requirement: ProbeRequirement) -> tuple[str, ...]:
    """The ``/dev`` nodes this device would create, that actually exist here.

    A filesystem lookup, never an import and never a device open — card ENV-1
    added it and :data:`FORBIDDEN_IMPORTS` in ``tests/test_clockmap.py`` still
    forbids this module from touching a vendor SDK.
    """

    found: list[str] = []
    for pattern in requirement.device_nodes:
        found.extend(str(item) for item in Path("/dev").glob(pattern))
    return tuple(sorted(found))


def probe_availability() -> dict[SourceDevice, tuple[bool, tuple[str, ...]]]:
    """Per device: can this host actually run its clock probe, and which modules are here.

    Two independent conditions, both of which must hold. Fail closed on each:

    * some required **module** must be importable — a spec that cannot be found,
      for any reason including a broken install, is absent;
    * every declared **device node** must not be missing — card ENV-1. Installing
      ``pyrealsense2`` does not attach a camera, and before this the wheel alone
      flipped the D455 to PRESENT on a host that has never seen one.

    A device that is not ``interrogable`` (the Go2) is a RITUAL, not a missing
    probe: its modules are what it takes to receive its messages, ``--check``
    prints the ``[ RITUAL]`` line for it, and its offset comes from PS-I's
    bracketed sync ritual regardless of what this function says.

    The returned module tuple is still the honest module census, so a caller can
    tell "the SDK is missing" from "the SDK is here and the camera is not".
    """

    result: dict[SourceDevice, tuple[bool, tuple[str, ...]]] = {}
    for device, requirement in PROBE_REQUIREMENTS.items():
        present: list[str] = []
        for module in requirement.modules:
            try:
                found = importlib.util.find_spec(module) is not None
            except (ImportError, ValueError):
                found = False
            if found:
                present.append(module)
        # Verifier correction (Fable, ENV-1 deviation 4): ``interrogable`` is NOT
        # a condition here. The Go2's modules are what it takes to RECEIVE its
        # messages (its own note says so) and the ``[ RITUAL]`` line in --check
        # already says no probe exists; folding ``interrogable`` into
        # ``satisfied`` made --check exit 2 on every host forever, a fully
        # equipped Orin included.
        satisfied = (not requirement.modules or bool(present)) and (
            not requirement.device_nodes or bool(device_nodes_present(requirement))
        )
        result[device] = (satisfied, tuple(present))
    return result


def _format_uncertainty(
    value: float | None, uncertainty: Uncertainty, unit: str, *, scale: float = 1.0
) -> str:
    """Value and both uncertainty halves in the SAME unit, always.

    ``scale`` divides all three together — quoting a millisecond offset beside a
    nanosecond uncertainty is exactly the kind of unit slip this card exists to
    stop.
    """

    if value is None:
        return f"unknown (no {unit} estimable from this segment)"
    total = uncertainty.total
    if total is None:
        parts = []
        if uncertainty.systematic is None:
            parts.append("systematic")
        if uncertainty.statistical is None:
            parts.append("statistical")
        return f"{value / scale:+.6f} {unit} ± UNBOUNDED ({'+'.join(parts)} unknown)"
    return (
        f"{value / scale:+.6f} ± {total / scale:.6f} {unit} "
        f"(sys {uncertainty.systematic / scale:.6f} + "
        f"stat {uncertainty.statistical / scale:.6f}, {uncertainty.confidence})"
    )


def format_report(clock_map: ClockMapV1) -> str:
    """Operator-readable summary. Every number carries its uncertainty."""

    lines = [
        f"ClockMapV1  session={clock_map.session_id}  host={clock_map.host_id}",
        f"  origin={clock_map.origin.value}"
        + (f"  fixture={clock_map.fixture_label}" if clock_map.fixture_label else "")
        + f"  samples={clock_map.sample_count}",
        f"  digest={clock_map_digest(clock_map)}",
        f"  certifiable={clock_map.is_certifiable}",
    ]
    for relation in clock_map.relations:
        coverage = relation.coverage
        lines.append(
            f"  [{relation.label}] n={relation.sample_count} "
            f"span={coverage.span_ns / _NS_PER_S:.1f}s "
            f"segments={len(relation.segments)} steps={len(relation.steps)}"
        )
        for segment in relation.segments:
            offset_line = _format_uncertainty(
                float(segment.offset_ns), segment.offset_uncertainty, "ms", scale=1e6
            )
            lines.append(
                f"    seg{segment.index} n={segment.sample_count} "
                f"span={segment.span_s:.1f}s basis={segment.basis.value}"
            )
            lines.append(f"      offset@ref {offset_line}")
            if segment.drift_uncertainty is None:
                lines.append("      drift      unknown (segment cannot support a slope)")
            else:
                lines.append(
                    "      drift      "
                    + _format_uncertainty(segment.drift_ppm, segment.drift_uncertainty, "ppm")
                )
            if segment.asymmetry_detected:
                lines.append(
                    f"      ASYMMETRY  wedge slope {segment.asymmetry_slope:+.3f} "
                    f"(path is one-sided; bound kept, no correction applied)"
                )
        for step in relation.steps:
            lines.append(
                f"    STEP at {step.at_host_monotonic_ns} "
                f"{step.magnitude_ns / 1e6:+.3f} ms ± {step.uncertainty_ns / 1e6:.3f} ms "
                f"(located within a {step.gap_ns / _NS_PER_S:.3f}s gap)"
            )
    for shortfall in clock_map.certification_shortfalls:
        lines.append(f"  SHORTFALL {shortfall}")
    for item in clock_map.does_not_prove:
        lines.append(f"  does_not_prove: {item}")
    return "\n".join(lines)


def planned_elapsed_ns(
    *,
    duration_ns: int,
    schedule: ClockSchedule = DEFAULT_SCHEDULE,
    cruise_interval_ns: int = 1_000_000_000,
    burst_interval_ns: int = 100_000_000,
) -> tuple[int, ...]:
    """The card's sampling plan, made executable: bursts at each end, ~1 Hz between.

    Returns elapsed offsets from the first probe. Both halves are load-bearing
    and :class:`ClockSchedule` documents why; ``_coverage`` then checks the
    plan was actually achieved, so a prober that fell behind is caught by the
    times it recorded rather than by its intentions.
    """

    if duration_ns < 2 * schedule.burst_window_ns:
        raise ClockRefusedError(
            ClockRefusalReason.MALFORMED_RECORD,
            f"duration {duration_ns} ns cannot hold two "
            f"{schedule.burst_window_ns} ns bursts",
        )
    if burst_interval_ns <= 0 or cruise_interval_ns <= 0:
        raise ClockRefusedError(
            ClockRefusalReason.MALFORMED_RECORD, "probe intervals must be positive"
        )
    plan: set[int] = set()
    for elapsed in range(0, schedule.burst_window_ns + 1, burst_interval_ns):
        plan.add(elapsed)
    for elapsed in range(
        duration_ns - schedule.burst_window_ns, duration_ns + 1, burst_interval_ns
    ):
        plan.add(elapsed)
    for elapsed in range(0, duration_ns + 1, cruise_interval_ns):
        plan.add(elapsed)
    plan.add(duration_ns)
    return tuple(sorted(plan))


def synthesize_samples(
    *,
    device: SourceDevice,
    start_host_ns: int,
    start_realtime_ns: int,
    elapsed_ns: Sequence[int],
    offset_ns: int,
    drift_ppm: float = 0.0,
    round_trip_ns: int = 2_000_000,
    jitter_ns: int = 0,
    step_at_elapsed_ns: int | None = None,
    step_ns: int = 0,
    request_leg_fraction: float = 0.5,
    host_pair_bracket_ns: int | None = 200,
    seed: int = 0,
) -> list[ClockSample]:
    """Deterministic synthetic offset triples for rehearsal and self-test.

    PS-E drives the whole stack from synthetic publishers; this is the clock
    half of that fixture, and it is the same generator this module's own tests
    use. A map built from these samples MUST carry a synthetic origin and a
    fixture label — :class:`ClockMapV1` refuses otherwise, so a rehearsal map
    cannot be mistaken for a session map even after both are in a bag.

    ``request_leg_fraction`` is the share of the round trip spent before the
    device reads its clock: 0.5 is a symmetric path, and anything else biases
    the midpoint estimator by exactly the amount the bracket is there to bound.
    """

    rng = random.Random(seed)
    samples: list[ClockSample] = []
    for elapsed in elapsed_ns:
        host_ns = start_host_ns + elapsed
        jitter = rng.randint(-jitter_ns, jitter_ns) if jitter_ns else 0
        step = step_ns if step_at_elapsed_ns is not None and elapsed >= step_at_elapsed_ns else 0
        device_ns = (
            host_ns
            + round(request_leg_fraction * round_trip_ns)
            + offset_ns
            + round(elapsed * drift_ppm / 1e6)
            + step
            + jitter
        )
        samples.append(
            ClockSample(
                device=device,
                host_monotonic_ns=host_ns,
                host_realtime_ns=start_realtime_ns + elapsed,
                device_source_ns=device_ns,
                round_trip_ns=round_trip_ns,
                host_pair_bracket_ns=host_pair_bracket_ns,
            )
        )
    return samples


def _selftest_map() -> ClockMapV1:
    """A full-shape rehearsal session: burst / 1 Hz cruise / burst, 40 ppm, one step."""

    duration_ns = 900_000_000_000
    plan = planned_elapsed_ns(duration_ns=duration_ns)
    samples = synthesize_samples(
        device=SourceDevice.GO2,
        start_host_ns=12_000_000_000,
        start_realtime_ns=1_786_000_000_000_000_000,
        elapsed_ns=plan,
        offset_ns=-4_200_000_000,
        drift_ppm=40.0,
        round_trip_ns=2_000_000,
        jitter_ns=50_000,
        step_at_elapsed_ns=duration_ns // 2,
        step_ns=500_000_000,
        seed=20260813,
    )
    return build_clock_map(
        samples,
        session_id="clockmap-selftest",
        created_at_utc="2026-08-13T00:00:00Z",
        host_id="selftest-host",
        origin=EvidenceOrigin.SIMULATION,
        fixture_label="clockmap-selftest",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="clockmap",
        description=(
            "Clock discipline for the physical capture session: record offset "
            "triples live, fit offset and drift with an uncertainty, and report "
            "steps. Read-only — it opens no device and arms nothing."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check",
        action="store_true",
        help="report which device clock probes this host can run, and exit non-zero if any cannot",
    )
    group.add_argument(
        "--selftest",
        action="store_true",
        help="fit a synthetic session (seeded 40 ppm drift and a 500 ms step) and print it",
    )
    group.add_argument("--fit", metavar="SAMPLES.jsonl", help="fit a recorded sample log")
    parser.add_argument("--session-id", default="", help="session id for --fit")
    parser.add_argument("--host-id", default="", help="host id for --fit")
    parser.add_argument("--created-at", default="", help="ISO-8601 UTC stamp for --fit")
    parser.add_argument("--json", action="store_true", help="emit the map as JSON, not a report")
    args = parser.parse_args(argv)

    if args.check:
        availability = probe_availability()
        for device, requirement in PROBE_REQUIREMENTS.items():
            satisfied, present = availability[device]
            state = "PRESENT" if satisfied else "ABSENT"
            modules = ", ".join(requirement.modules) or "(none needed)"
            found = ", ".join(present) or "-"
            if not requirement.interrogable:
                print(
                    f"[ RITUAL] {device.value:<5} has NO queryable clock: its offset "
                    f"comes from the PS-I sync ritual, not from this probe"
                )
            print(f"[{state:>7}] {device.value:<5} {requirement.method}")
            print(f"          needs any of: {modules}   found: {found}")
            if requirement.device_nodes:
                nodes = ", ".join(f"/dev/{pattern}" for pattern in requirement.device_nodes)
                attached = ", ".join(device_nodes_present(requirement)) or "NOTHING"
                print(f"          needs a device at: {nodes}   attached: {attached}")
            print(f"          {requirement.note}")
        missing = [
            device.value for device, (satisfied, _) in availability.items() if not satisfied
        ]
        if missing:
            print(
                "\nREFUSED: no clock probe is possible for: "
                + ", ".join(sorted(missing))
                + "\nThis host cannot record offset triples for those devices. Run this "
                "on the Orin inside the ROS 2 Humble environment that owns the vendor "
                "SDKs. Recording a session without them leaves their timestamps "
                "permanently unrecoverable."
            )
            return 2
        print("\nOK: every declared clock probe has its module available.")
        return 0

    if args.selftest:
        clock_map = _selftest_map()
        print(canonical_json(clock_map.to_dict()) if args.json else format_report(clock_map))
        return 0

    path = Path(args.fit)
    if not path.is_file():
        print(f"REFUSED: no sample log at {path}", file=sys.stderr)
        return 2
    for field_name, value in (
        ("--session-id", args.session_id),
        ("--host-id", args.host_id),
        ("--created-at", args.created_at),
    ):
        if not value.strip():
            print(
                f"REFUSED: {field_name} is required for --fit. A clock map that "
                f"cannot name its session or its host cannot be bound to a bag.",
                file=sys.stderr,
            )
            return 2
    try:
        samples = read_samples_jsonl(path)
        clock_map = build_clock_map(
            samples,
            session_id=args.session_id,
            created_at_utc=args.created_at,
            host_id=args.host_id,
            origin=EvidenceOrigin.PHYSICAL,
        )
    except ClockMapError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(canonical_json(clock_map.to_dict()) if args.json else format_report(clock_map))
    return 0 if clock_map.is_certifiable else 1


__all__ = [
    "ASSUMED_WORST_CASE_DRIFT_PPM",
    "BURST_WINDOW_NS",
    "CLOCK_MAP_SCHEMA",
    "CLOCK_SAMPLE_SCHEMA",
    "CONFIDENCE",
    "DEFAULT_DOES_NOT_PROVE",
    "DEFAULT_SCHEDULE",
    "MAX_CRUISE_GAP_NS",
    "MAX_STEPS",
    "MIN_BURST_SAMPLES",
    "MIN_SEGMENT_SAMPLES",
    "MIN_SPAN_NS",
    "PROBE_REQUIREMENTS",
    "REALTIME_EPOCH_FLOOR_NS",
    "STEP_FLOOR_NS",
    "ClockMapError",
    "ClockMapV1",
    "ClockReading",
    "ClockRefusalReason",
    "ClockRefusedError",
    "ClockRelation",
    "ClockSample",
    "ClockSchedule",
    "ClockSegment",
    "ClockStep",
    "FitBasis",
    "FitStats",
    "ProbeRequirement",
    "RelationKind",
    "ScheduleCoverage",
    "Uncertainty",
    "append_sample_jsonl",
    "build_clock_map",
    "canonical_json",
    "clock_map_digest",
    "device_nodes_present",
    "fit_relation",
    "format_report",
    "interrogate",
    "main",
    "planned_elapsed_ns",
    "probe_availability",
    "read_samples_jsonl",
    "sample_digest",
    "sidecar_clock_block",
    "synthesize_samples",
    "t_critical_95",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry, exercised by subprocess
    raise SystemExit(main())
