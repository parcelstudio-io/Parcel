"""``CaptureEnvelope`` — the per-message header of a physical capture, with a
sequence counter that is PER CHANNEL.

Card PS-A (``scrum/20260813/task_1/README.md``). This module is the fix for one
named defect, so it is worth stating the defect precisely.

The defect
----------
``bags/recorder.py`` keeps ONE counter for the whole bag. ``record()`` stamps
``sequence=self._sequence`` (line 98) and then increments it only AFTER the
line is written (line 114). Two consequences, and the second is the worse one:

1. **Write-assigned.** A message that is never written never advances the
   counter, so it leaves no hole. A bag missing three ``lidar/scan`` messages
   is byte-for-byte indistinguishable from a bag whose LiDAR published three
   fewer times. The evidence of the loss is destroyed by the scheme that was
   supposed to record it.
2. **Global.** Even if the counter were minted at receipt — a strictly stronger
   scheme — one counter shared across topics can say "N messages were lost" but
   never "channel A lost them". Two different sessions ("A dropped 3" versus
   "B dropped 3") produce the identical global gap.

The fix, and its exact limit
----------------------------
:class:`ChannelSequenceBook` mints ``sequence`` **per channel, at receipt** —
in the subscriber callback, before anything can fail — and
:class:`ChannelSequenceLedger` reads those numbers back off the written record.
A message received and not written therefore leaves a hole in exactly one
channel's number line, and the hole names the channel.

What this does NOT detect, stated here because a capture stack that overclaims
is worse than one that underclaims: a message lost **in transit**, before the
subscriber callback ran, was never sequenced by us and is invisible to this
scheme. Detecting that needs a PRODUCER-side counter — ``lowstate``'s ``tick``,
a ROS header stamp — cross-checked against ours. That cross-check is PS-B's,
and this module deliberately does not pretend to do it.

Fail-closed rules in force here (board rule 3)
----------------------------------------------
* An unrecognised ``channel_id`` is a refusal, never a new stream.
* Clocks are integer nanoseconds. A float, a bool, a NaN, an inf or a negative
  is a refusal — never coerced, never defaulted to "now".
* ``origin`` defaults to :attr:`EvidenceOrigin.UNKNOWN`, and
  :meth:`ChannelSequenceBook.stamp` — the only constructor a capture process is
  meant to call — refuses ``UNKNOWN`` outright. A datum that declares nothing
  must never be able to pass for a physical measurement (card W0-A, board D-3).
* A synthetic origin must name its fixture. PS-E drives this same stack from
  synthetic publishers, so a rehearsal envelope has to be impossible to mistake
  for a session envelope even after both are in a bag six months from now.
* ``frame_id`` must equal the frame the channel declares. A silent frame swap
  is unrecoverable once the rig is unbolted.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from parcel_robot.evidence_origin import SYNTHETIC_ORIGINS, EvidenceOrigin

from .channels import CaptureError, Channel, channel

#: Wire identifier for the serialised form. PS-B stores these inside MCAP and
#: the ``parcel.bag.v1`` sidecar; a reader that does not know this string must
#: refuse the record rather than guess at its shape.
ENVELOPE_SCHEMA = "parcel.capture.envelope.v1"

#: Fail-closed default for :attr:`CaptureEnvelope.calibration_ref`. It claims
#: nothing. Mirrors ``bags/schema.py:make_envelope``'s ``"uncalibrated"`` so a
#: consumer of either path reads the same word for the same absence.
UNCALIBRATED = "uncalibrated"

#: Upper bound on how many individual missing sequence numbers one channel's
#: ledger will hold. The missing COUNT stays exact past this bound; only the
#: enumeration is truncated, and :attr:`ChannelSequenceReport.missing_truncated`
#: says so. Chosen so a plausible burst loss is fully enumerated and a
#: catastrophic one cannot exhaust the Orin's memory mid-session.
MISSING_TRACKING_CAP = 100_000

_ENVELOPE_KEYS = frozenset(
    {
        "schema",
        "channel_id",
        "sequence",
        "source_timestamp_ns",
        "host_monotonic_ns",
        "host_realtime_ns",
        "frame_id",
        "origin",
        "fixture_label",
        "calibration_ref",
        "health",
    }
)


class RefusalReason(str, Enum):
    """Why an envelope was refused. Every refusal names one of these.

    PS-B branches on the reason (a frame mismatch is a mounting finding; a
    non-integer clock is a broken adapter), so the reason is part of the
    contract rather than prose inside a message string.
    """

    NON_INTEGER_FIELD = "non_integer_field"
    NEGATIVE_FIELD = "negative_field"
    FRAME_MISMATCH = "frame_mismatch"
    ORIGIN_NOT_DECLARED = "origin_not_declared"
    ORIGIN_NOT_TYPED = "origin_not_typed"
    FIXTURE_LABEL_MISSING = "fixture_label_missing"
    FIXTURE_LABEL_FORBIDDEN = "fixture_label_forbidden"
    EMPTY_CALIBRATION_REF = "empty_calibration_ref"
    HEALTH_NOT_TYPED = "health_not_typed"
    SCHEMA_MISMATCH = "schema_mismatch"
    MALFORMED_RECORD = "malformed_record"


class CaptureRefusedError(CaptureError):
    """A malformed or under-declared envelope. Carries its
    :class:`RefusalReason` so a caller can classify without parsing text."""

    def __init__(self, reason: RefusalReason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason


class ChannelHealth(str, Enum):
    """Per-message health assertion made by the channel's reader.

    :attr:`UNKNOWN` is the default and is NOT a permissive value: a consumer
    must treat it as "this reader asserted nothing", which is the same standing
    as a fault for any purpose that needs the datum to be good.
    """

    #: Nothing was asserted about this message. The fail-closed default.
    UNKNOWN = "unknown"
    #: The reader observed the channel inside its expected behaviour.
    NOMINAL = "nominal"
    #: Received, but outside expectation (late, off-rate, partial).
    DEGRADED = "degraded"
    #: Received and known bad (decode error, device-reported fault).
    FAULT = "fault"

    @property
    def is_asserted_good(self) -> bool:
        """True only for :attr:`NOMINAL`. Unknown never counts as good."""

        return self is ChannelHealth.NOMINAL


def _require_int(value: object, *, field: str, allow_none: bool = False) -> int | None:
    """Integer nanoseconds or a refusal. Bools and floats are not integers."""

    if value is None:
        if allow_none:
            return None
        raise CaptureRefusedError(
            RefusalReason.NON_INTEGER_FIELD, f"{field} must be an int, got None"
        )
    if isinstance(value, bool) or not isinstance(value, int):
        raise CaptureRefusedError(
            RefusalReason.NON_INTEGER_FIELD,
            f"{field} must be an int (nanoseconds), got {type(value).__name__} "
            f"{value!r} — a float clock is never rounded here",
        )
    if value < 0:
        raise CaptureRefusedError(
            RefusalReason.NEGATIVE_FIELD, f"{field} must be non-negative, got {value!r}"
        )
    return value


@dataclass(frozen=True, slots=True)
class CaptureEnvelope:
    """One message's provenance header.

    Construct through :meth:`ChannelSequenceBook.stamp` in a capture process —
    that is the path which mints the per-channel sequence and refuses an
    undeclared origin. Direct construction exists for decoding and for tests.
    """

    channel_id: str
    #: Per-channel counter, minted at RECEIPT. Never global, never write-time.
    sequence: int
    #: The device's own clock, when the device gives one. ``None`` is honest
    #: absence — it is not filled in from the host clock, because a host
    #: timestamp wearing a device's name is how a clock map gets fabricated.
    source_timestamp_ns: int | None
    host_monotonic_ns: int
    host_realtime_ns: int
    frame_id: str
    origin: EvidenceOrigin = EvidenceOrigin.UNKNOWN
    #: Names the fixture for a synthetic origin; forbidden for a physical one.
    fixture_label: str | None = None
    calibration_ref: str = UNCALIBRATED
    health: ChannelHealth = ChannelHealth.UNKNOWN

    def __post_init__(self) -> None:
        entry = channel(self.channel_id)
        _require_int(self.sequence, field="sequence")
        _require_int(self.host_monotonic_ns, field="host_monotonic_ns")
        _require_int(self.host_realtime_ns, field="host_realtime_ns")
        _require_int(
            self.source_timestamp_ns, field="source_timestamp_ns", allow_none=True
        )
        if self.frame_id != entry.frame_id:
            raise CaptureRefusedError(
                RefusalReason.FRAME_MISMATCH,
                f"{self.channel_id} declares frame {entry.frame_id!r}, envelope "
                f"carries {self.frame_id!r}",
            )
        if not isinstance(self.origin, EvidenceOrigin):
            raise CaptureRefusedError(
                RefusalReason.ORIGIN_NOT_TYPED,
                f"origin must be an EvidenceOrigin member, got "
                f"{type(self.origin).__name__} {self.origin!r} — a string is not a "
                f"declaration",
            )
        if not isinstance(self.health, ChannelHealth):
            raise CaptureRefusedError(
                RefusalReason.HEALTH_NOT_TYPED,
                f"health must be a ChannelHealth member, got {self.health!r}",
            )
        if self.origin in SYNTHETIC_ORIGINS:
            if not isinstance(self.fixture_label, str) or not self.fixture_label.strip():
                raise CaptureRefusedError(
                    RefusalReason.FIXTURE_LABEL_MISSING,
                    f"origin {self.origin.value} requires a non-empty fixture_label "
                    f"naming the fixture, got {self.fixture_label!r}",
                )
        elif self.fixture_label is not None:
            raise CaptureRefusedError(
                RefusalReason.FIXTURE_LABEL_FORBIDDEN,
                f"origin {self.origin.value} must not carry a fixture_label, got "
                f"{self.fixture_label!r}",
            )
        if not isinstance(self.calibration_ref, str) or not self.calibration_ref.strip():
            raise CaptureRefusedError(
                RefusalReason.EMPTY_CALIBRATION_REF,
                f"calibration_ref must be a non-empty string, got "
                f"{self.calibration_ref!r}",
            )

    @property
    def channel(self) -> Channel:
        """The matrix row this envelope belongs to."""

        return channel(self.channel_id)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-safe dict. Enums become their ``str`` values, nothing else."""

        return {
            "schema": ENVELOPE_SCHEMA,
            "channel_id": self.channel_id,
            "sequence": self.sequence,
            "source_timestamp_ns": self.source_timestamp_ns,
            "host_monotonic_ns": self.host_monotonic_ns,
            "host_realtime_ns": self.host_realtime_ns,
            "frame_id": self.frame_id,
            "origin": self.origin.value,
            "fixture_label": self.fixture_label,
            "calibration_ref": self.calibration_ref,
            "health": self.health.value,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> CaptureEnvelope:
        """Decode, refusing anything that is not exactly this schema.

        Strict in both directions: a missing key and an unexpected key are both
        refusals. A capture format that silently ignores fields it does not
        understand cannot be read back with confidence six months later.
        """

        if not isinstance(record, Mapping):
            raise CaptureRefusedError(
                RefusalReason.MALFORMED_RECORD,
                f"envelope record must be a mapping, got {type(record).__name__}",
            )
        keys = set(record)
        missing = _ENVELOPE_KEYS - keys
        unexpected = keys - _ENVELOPE_KEYS
        if missing or unexpected:
            raise CaptureRefusedError(
                RefusalReason.MALFORMED_RECORD,
                f"envelope keys missing={sorted(missing)} unexpected={sorted(unexpected)}",
            )
        if record["schema"] != ENVELOPE_SCHEMA:
            raise CaptureRefusedError(
                RefusalReason.SCHEMA_MISMATCH,
                f"expected schema {ENVELOPE_SCHEMA!r}, got {record['schema']!r}",
            )
        try:
            origin = EvidenceOrigin(record["origin"])
            health = ChannelHealth(record["health"])
        except ValueError as exc:
            raise CaptureRefusedError(
                RefusalReason.MALFORMED_RECORD, f"undecodable enum value: {exc}"
            ) from exc
        return cls(
            channel_id=str(record["channel_id"]),
            sequence=record["sequence"],
            source_timestamp_ns=record["source_timestamp_ns"],
            host_monotonic_ns=record["host_monotonic_ns"],
            host_realtime_ns=record["host_realtime_ns"],
            frame_id=str(record["frame_id"]),
            origin=origin,
            fixture_label=record["fixture_label"],
            calibration_ref=str(record["calibration_ref"]),
            health=health,
        )


def canonical_json(envelope: CaptureEnvelope) -> str:
    """Byte-stable serialisation: sorted keys, no whitespace, no NaN.

    ``allow_nan=False`` is not decoration. Python's ``json`` emits a bare
    ``NaN`` token by default, which is not JSON, and a bag full of it is a bag
    no other tool can read.
    """

    return json.dumps(
        envelope.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def envelope_digest(envelope: CaptureEnvelope) -> str:
    """SHA-256 over :func:`canonical_json`, for PS-B/PS-C digest binding."""

    return hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()


class ChannelSequenceBook:
    """Mints the per-channel sequence, at receipt.

    One book per capture process. Call :meth:`stamp` from the channel's reader
    the moment a message arrives — before decoding, before queueing, before
    writing. Everything that can fail after this point then leaves a hole with
    the channel's name on it.
    """

    __slots__ = ("_next",)

    def __init__(self) -> None:
        self._next: dict[str, int] = {}

    def next_sequence(self, channel_id: str) -> int:
        """Reserve and return the next sequence number for one channel."""

        entry = channel(channel_id)
        issued = self._next.get(entry.channel_id, 0)
        self._next[entry.channel_id] = issued + 1
        return issued

    def issued(self, channel_id: str) -> int:
        """How many numbers this book has minted for a channel."""

        return self._next.get(channel(channel_id).channel_id, 0)

    def stamp(
        self,
        channel_id: str,
        *,
        host_monotonic_ns: int,
        host_realtime_ns: int,
        origin: EvidenceOrigin,
        source_timestamp_ns: int | None = None,
        fixture_label: str | None = None,
        calibration_ref: str = UNCALIBRATED,
        health: ChannelHealth = ChannelHealth.UNKNOWN,
    ) -> CaptureEnvelope:
        """Build an envelope for a received message.

        This is the physical-channel constructor the card names: ``origin`` has
        no default and :attr:`EvidenceOrigin.UNKNOWN` is refused, so a reader
        that declares nothing cannot record anything. ``frame_id`` is taken from
        the matrix rather than accepted from the caller — there is no argument
        here that can put the wrong frame on a message.
        """

        entry = channel(channel_id)
        if not isinstance(origin, EvidenceOrigin):
            raise CaptureRefusedError(
                RefusalReason.ORIGIN_NOT_TYPED,
                f"origin must be an EvidenceOrigin member, got {origin!r}",
            )
        if origin is EvidenceOrigin.UNKNOWN:
            raise CaptureRefusedError(
                RefusalReason.ORIGIN_NOT_DECLARED,
                f"{entry.channel_id}: UNKNOWN is not an origin a capture may record "
                f"under — declare PHYSICAL, SIMULATION or REPLAY",
            )
        return CaptureEnvelope(
            channel_id=entry.channel_id,
            sequence=self.next_sequence(entry.channel_id),
            source_timestamp_ns=source_timestamp_ns,
            host_monotonic_ns=host_monotonic_ns,
            host_realtime_ns=host_realtime_ns,
            frame_id=entry.frame_id,
            origin=origin,
            fixture_label=fixture_label,
            calibration_ref=calibration_ref,
            health=health,
        )


@dataclass(frozen=True, slots=True)
class ChannelSequenceReport:
    """What one channel's number line says happened to it."""

    channel_id: str
    #: Envelopes observed, duplicates included.
    received: int
    first_sequence: int | None
    last_sequence: int | None
    #: Sequence numbers that were minted and never seen, enumerated up to
    #: :data:`MISSING_TRACKING_CAP`.
    missing: tuple[int, ...]
    #: Exact, even when :attr:`missing` is truncated.
    missing_count: int
    missing_truncated: bool
    #: Numbers seen more than once (excluding late arrivals that filled a
    #: known hole, which are counted as :attr:`out_of_order` instead).
    #: Enumerated up to :data:`MISSING_TRACKING_CAP`; ``len(duplicated) <
    #: duplicate_count`` means the enumeration was truncated.
    duplicated: tuple[int, ...]
    #: Exact, even when :attr:`duplicated` is truncated.
    duplicate_count: int
    out_of_order: int

    @property
    def has_gap(self) -> bool:
        return self.missing_count > 0

    @property
    def is_clean(self) -> bool:
        return not self.has_gap and self.duplicate_count == 0 and self.out_of_order == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "received": self.received,
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
            "missing": list(self.missing),
            "missing_count": self.missing_count,
            "missing_truncated": self.missing_truncated,
            "duplicated": list(self.duplicated),
            "duplicate_count": self.duplicate_count,
            "out_of_order": self.out_of_order,
        }


class _ChannelTally:
    """Streaming per-channel bookkeeping. Memory is bounded by actual loss."""

    __slots__ = (
        "_duplicate_count",
        "_duplicated",
        "_expected_next",
        "_first",
        "_last",
        "_out_of_order",
        "_pending",
        "_received",
        "_untracked_missing",
    )

    def __init__(self) -> None:
        self._received = 0
        self._first: int | None = None
        self._last: int | None = None
        self._expected_next = 0
        self._pending: set[int] = set()
        self._untracked_missing = 0
        self._duplicated: list[int] = []
        self._duplicate_count = 0
        self._out_of_order = 0

    def observe(self, sequence: int) -> None:
        self._received += 1
        if self._first is None or self._last is None:
            self._first = sequence
            self._last = sequence
            self._expected_next = sequence + 1
            return
        self._last = max(self._last, sequence)
        if sequence >= self._expected_next:
            gap = sequence - self._expected_next
            if gap:
                # Bounded by construction: a jump of a billion must not build a
                # billion-element set on a robot with 8 GiB of RAM.
                room = max(MISSING_TRACKING_CAP - len(self._pending), 0)
                tracked = min(gap, room)
                self._pending.update(
                    range(self._expected_next, self._expected_next + tracked)
                )
                self._untracked_missing += gap - tracked
            self._expected_next = sequence + 1
        elif sequence in self._pending:
            # A late arrival that filled a known hole: out of order, not lost.
            self._pending.discard(sequence)
            self._out_of_order += 1
        else:
            self._duplicate_count += 1
            if len(self._duplicated) < MISSING_TRACKING_CAP:
                self._duplicated.append(sequence)

    def report(self, channel_id: str) -> ChannelSequenceReport:
        missing = tuple(sorted(self._pending))
        return ChannelSequenceReport(
            channel_id=channel_id,
            received=self._received,
            first_sequence=self._first,
            last_sequence=self._last,
            missing=missing,
            missing_count=len(missing) + self._untracked_missing,
            missing_truncated=self._untracked_missing > 0,
            duplicated=tuple(self._duplicated),
            duplicate_count=self._duplicate_count,
            out_of_order=self._out_of_order,
        )


class ChannelSequenceLedger:
    """Reads per-channel number lines back off a written record.

    Feed it the envelopes that made it to disk. Every hole it reports belongs
    to exactly one channel, which is the entire difference between this and the
    single global counter in ``bags/recorder.py``.
    """

    __slots__ = ("_tallies",)

    def __init__(self) -> None:
        self._tallies: dict[str, _ChannelTally] = {}

    def observe(self, envelope: CaptureEnvelope) -> None:
        if not isinstance(envelope, CaptureEnvelope):
            raise CaptureRefusedError(
                RefusalReason.MALFORMED_RECORD,
                f"ledger observes CaptureEnvelope, got {type(envelope).__name__}",
            )
        tally = self._tallies.get(envelope.channel_id)
        if tally is None:
            tally = _ChannelTally()
            self._tallies[envelope.channel_id] = tally
        tally.observe(envelope.sequence)

    def observe_all(self, envelopes: Iterable[CaptureEnvelope]) -> None:
        for envelope in envelopes:
            self.observe(envelope)

    def report(
        self, *, expected: Iterable[str] | None = None
    ) -> dict[str, ChannelSequenceReport]:
        """Per-channel reports, keyed by channel id.

        Pass ``expected`` to make silence visible: a channel that was expected
        and delivered nothing appears with ``received=0`` instead of being
        absent from the table. A channel missing from a report is the easiest
        kind of loss to overlook, so the caller is given the means not to.
        """

        keys = set(self._tallies)
        if expected is not None:
            keys |= {channel(channel_id).channel_id for channel_id in expected}
        reports: dict[str, ChannelSequenceReport] = {}
        for channel_id in sorted(keys):
            tally = self._tallies.get(channel_id) or _ChannelTally()
            reports[channel_id] = tally.report(channel_id)
        return reports

    def to_dict(self, *, expected: Iterable[str] | None = None) -> dict[str, Any]:
        return {
            channel_id: report.to_dict()
            for channel_id, report in self.report(expected=expected).items()
        }


__all__ = [
    "ENVELOPE_SCHEMA",
    "MISSING_TRACKING_CAP",
    "UNCALIBRATED",
    "CaptureEnvelope",
    "CaptureRefusedError",
    "ChannelHealth",
    "ChannelSequenceBook",
    "ChannelSequenceLedger",
    "ChannelSequenceReport",
    "RefusalReason",
    "canonical_json",
    "envelope_digest",
]
