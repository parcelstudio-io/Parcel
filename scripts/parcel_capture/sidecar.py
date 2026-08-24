"""``parcel.bag.v1`` sidecar for an MCAP capture — card PS-B.

The MCAP file holds the bytes. This module builds the manifest that binds those
bytes into Parcel's evidence world: what was recorded, how completely, from
what hardware, on what clock, and — the part everything else depends on — a
SHA-256 that says these are the same bytes six months from now.

It is a **recovery pass, not an exit path**
-------------------------------------------
The sidecar is produced by reading the bag back off disk, so it exists for a
recording whose process was killed. That is the opposite of
``bags/recorder.py:116``, which rewrites its manifest after every message and
still loses the lot on a crash because it never calls ``fsync``
(``recorder.py:40-41``). Here the hot path writes only MCAP bytes, and the
manifest is derived afterwards from whatever survived.

Truncation is not a dropout, and this module refuses to conflate them
--------------------------------------------------------------------
Four outcomes, each from its own evidence, each separately reported:

============================  =========================================
outcome                       what proves it
============================  =========================================
``TerminationKind.TRUNCATED`` the FRAMING: no ``DataEnd``/``Footer``/
                              terminal magic, or a record whose declared
                              length runs past the end of the file
``TerminationKind.CORRUPT``   bytes all present, decode failed
``ChannelVerdict.DEGRADED``   an INTERIOR hole in one channel's
                              per-channel number line, or a delivered
                              rate outside tolerance
``ChannelVerdict.ABSENT``     that channel delivered nothing at all
============================  =========================================

A truncated bag loses a *suffix* of every channel at once, which leaves no
holes; a dropping sensor leaves *interior* holes under a clean footer. They can
never be inferred from the same signal, which is why a truncated bag cannot
silently read as "the LiDAR was flaky" — the failure mode that would quietly
corrupt every conclusion drawn from the dataset.

Rate assessment is over the RECORDED window
-------------------------------------------
Expected message counts are computed against the span actually present in the
bag, never against the session the operator asked for. Otherwise a bag
truncated at the halfway mark would report every channel at 50% and turn one
truncation into fifteen fake sensor faults.

Fail-closed rules in force (board rule 3)
-----------------------------------------
* ``source="hardware"`` is reachable only from envelopes that actually declare
  :attr:`~parcel_robot.evidence_origin.EvidenceOrigin.PHYSICAL`. A bag with no
  messages cannot claim hardware, whatever the operator declares.
* A bag carrying more than one origin is a refusal, not a majority vote.
* An absent PS-C clock-map digest or PS-D attestation digest is recorded AS
  absent and adds a ``does_not_prove`` line. It is never a placeholder.
* Mount geometry must name its measurement method and its uncertainty. A bare
  triple of numbers is refused — a fabricated extrinsic is unrecoverable once
  the bracket is unbolted, which is precisely why PS-F measures it by hand.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from parcel_robot.bags.schema import (
    SCHEMA_VERSION,
    BagSchemaError,
    default_clocks,
    default_frames,
    make_manifest,
)
from parcel_robot.capture.channels import (
    SUPPORT_ARTIFACTS,
    Channel,
    RateKind,
    SupportNeed,
    camera_info_topic_for,
    certified_optical_channel_ids,
    channel,
)
from parcel_robot.capture.envelope import ENVELOPE_SCHEMA, ChannelSequenceReport
from parcel_robot.evidence_origin import EvidenceOrigin

from .record import (
    MCAP_LIBRARY,
    MESSAGE_ENCODING,
    McapScan,
    ScanTermination,
    read_mcap,
    sha256_file,
)
from .rosbag2 import (
    CHANNEL_BY_TOPIC,
    SUPPORT_BY_TOPIC,
    CameraInfoView,
    CdrDecodeError,
    CountBasis,
    Rosbag2Directory,
    Rosbag2Info,
    Rosbag2Scan,
    TransformView,
    collect_topic_payloads,
    decode_camera_info,
    decode_image_meta,
    decode_tf_message,
    discover_bag,
    read_rosbag2_mcap,
)
from .rosbag2 import ScanTermination as Rosbag2Termination
from .syncevents import SyncFitV1, sidecar_sync_block, sync_fit_digest

#: Wire identifier of the capture block inside the manifest's ``extra``.
SIDECAR_SCHEMA = "parcel.capture.sidecar.v1"

#: ``make_manifest`` merges ``extra`` at the manifest's top level
#: (``schema.py:313``), so the whole capture block lives under one key rather
#: than scattering fifteen names into a namespace the bag schema owns.
SIDECAR_EXTRA_KEY = "capture"

SIDECAR_SUFFIX = ".parcel-bag.json"

#: Relative tolerance on a channel's delivered count before it is called
#: degraded. Two percent: wide enough to absorb the one-message edge effect of
#: a finite window, far tighter than the 10% deficit the board's gate names.
RATE_TOLERANCE = 0.02

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")

_MOUNT_REQUIRED_KEYS = (
    "parent_frame",
    "xyz_m",
    "rpy_rad",
    "method",
    "uncertainty_m",
    "measured_at_utc",
)


class SidecarRefusedError(ValueError):
    """A sidecar that cannot be built honestly is not built at all."""


class BagFormat(str, Enum):
    """Which recorder's format a sidecar describes. Never inferred.

    The two are read by different tools and by different readers in this
    package, and conflating them is the defect PS-G exists to fix: a
    ``parcel-capture`` MCAP declares ``message_encoding``
    ``parcel.capture.envelope.v1+raw`` and is unreadable to GLIM, FAST-LIO2,
    KISS-ICP, Multi-LiCa, ros2_calib and every other tool in the next milestone.
    """

    #: ``record.py``'s self-contained writer. Parcel envelopes, per-channel
    #: sequence numbers, and a reader that lives in this repository.
    PARCEL_MCAP = "parcel_capture_mcap"
    #: ``ros2 bag record -s mcap``. CDR payloads, ``ros2`` profile, readable by
    #: every downstream tool and by :mod:`scripts.parcel_capture.rosbag2`.
    ROSBAG2_MCAP = "rosbag2_mcap"


class RecorderRole(str, Enum):
    """Whether this bag is the copy of record or a second, narrower one."""

    #: The session's data. If this is lost, the session is lost.
    PRIMARY = "primary"
    #: An additional copy of a subset — attestation, clock, low-rate summaries.
    #: Never the sole copy of anything.
    SECONDARY = "secondary"


class ChannelVerdict(str, Enum):
    """What the bag says about one channel. The default is never permissive."""

    #: Messages arrived and the delivered count is inside tolerance.
    PRESENT = "present"
    #: Messages arrived, but a number-line hole, a duplicate, or a rate outside
    #: tolerance says the stream was not what it claimed.
    DEGRADED = "degraded"
    #: Nothing arrived. The fail-closed default.
    ABSENT = "absent"
    #: Messages arrived and no rate expectation exists to judge them against.
    #: Explicitly not PRESENT: unassessed is not passed.
    UNASSESSABLE = "unassessable"


class TerminationKind(str, Enum):
    """How the recording ended, as a statement about the bytes."""

    CLEAN = "clean"
    TRUNCATED = "truncated"
    CORRUPT = "corrupt"
    LATCHED_WRITE_FAILURE = "latched_write_failure"
    #: The framing is complete but the recorder left no account of itself, so
    #: whether it finished cannot be confirmed from the bag.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Termination:
    """How the bag ended, with the evidence that says so."""

    kind: TerminationKind
    detail: str
    evidence: Mapping[str, Any]
    findings: tuple[str, ...]

    @property
    def is_truncation(self) -> bool:
        return self.kind is TerminationKind.TRUNCATED

    @property
    def is_clean(self) -> bool:
        return self.kind is TerminationKind.CLEAN

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "detail": self.detail,
            "evidence": dict(self.evidence),
            "findings": list(self.findings),
        }


@dataclass(frozen=True)
class ChannelObservation:
    """One channel's account: what arrived, what was expected, what is missing."""

    channel_id: str
    human_name: str
    bag_topic: str
    frame_id: str
    message_type: str
    rate_kind: str
    criticality: str
    verdict: ChannelVerdict
    reason: str
    messages: int
    payload_bytes: int
    expected_messages: float | None
    deficit_messages: float | None
    deficit_fraction: float | None
    observed_rate_hz: float | None
    expected_rate_hz: float | None
    sequence: Mapping[str, Any]

    @property
    def is_fault(self) -> bool:
        """Degraded always; absent only where silence is not normal."""

        if self.verdict is ChannelVerdict.DEGRADED:
            return True
        if self.verdict is not ChannelVerdict.ABSENT:
            return False
        return self.rate_kind != RateKind.EVENT_DRIVEN.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "human_name": self.human_name,
            "bag_topic": self.bag_topic,
            "frame_id": self.frame_id,
            "message_type": self.message_type,
            "rate_kind": self.rate_kind,
            "criticality": self.criticality,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "messages": self.messages,
            "payload_bytes": self.payload_bytes,
            "expected_messages": self.expected_messages,
            "deficit_messages": self.deficit_messages,
            "deficit_fraction": self.deficit_fraction,
            "observed_rate_hz": self.observed_rate_hz,
            "expected_rate_hz": self.expected_rate_hz,
            "is_fault": self.is_fault,
            "sequence": dict(self.sequence),
        }


@dataclass(frozen=True)
class SidecarVerification:
    """Result of re-binding a sidecar to the bytes it claims to describe."""

    ok: bool
    failures: tuple[str, ...]
    recorded_sha256: str
    computed_sha256: str
    recorded_bytes: int
    computed_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "failures": list(self.failures),
            "recorded_sha256": self.recorded_sha256,
            "computed_sha256": self.computed_sha256,
            "recorded_bytes": self.recorded_bytes,
            "computed_bytes": self.computed_bytes,
        }


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def classify_termination(scan: McapScan) -> Termination:
    """Turn the scan's framing verdict into the sidecar's termination record.

    The recorder's own close record — written INTO the bag before the footer —
    is the second, independent source here. When it disagrees with the bytes
    that survived, the disagreement is a finding rather than a silent
    reconciliation.
    """

    close = dict(scan.close_metadata) if scan.close_metadata is not None else None
    findings: list[str] = []
    evidence: dict[str, Any] = {
        "scan_termination": scan.termination.value,
        "scan_detail": scan.detail,
        "file_bytes": scan.file_bytes,
        "last_complete_offset": scan.last_complete_offset,
        "trailing_bytes": scan.trailing_bytes,
        "saw_data_end": scan.saw_data_end,
        "saw_footer": scan.saw_footer,
        "saw_terminal_magic": scan.saw_terminal_magic,
        "skipped_records": scan.skipped_records,
        "messages_recovered": scan.message_count,
        "recorder_close_record": close,
    }

    if scan.skipped_records:
        findings.append(
            f"{scan.skipped_records} MCAP record(s) of unhandled spec types were stepped "
            f"over; this bag was written or rewritten by something other than "
            f"{MCAP_LIBRARY!r}"
        )

    declared_written: int | None = None
    if close is not None:
        raw = close.get("messages_written", "")
        try:
            declared_written = int(raw)
        except (TypeError, ValueError):
            findings.append(f"recorder close record carries a non-integer count {raw!r}")
        evidence["recorder_messages_written"] = declared_written
        evidence["recorder_drops"] = _decode_counts(close.get("drops", ""))
        if declared_written is not None and declared_written != scan.message_count:
            findings.append(
                f"the recorder says it wrote {declared_written} message(s); "
                f"{scan.message_count} survive in the bag"
            )

    if scan.termination is ScanTermination.CORRUPT:
        return Termination(TerminationKind.CORRUPT, scan.detail, evidence, tuple(findings))
    if scan.termination is ScanTermination.TRUNCATED:
        return Termination(
            TerminationKind.TRUNCATED,
            scan.detail
            or "the recorder never wrote a footer; the bag ends where the process died",
            evidence,
            tuple(findings),
        )
    if close is None:
        return Termination(
            TerminationKind.UNKNOWN,
            "the framing is complete but the recorder wrote no close record, so whether it "
            "finished on purpose cannot be confirmed from the bag",
            evidence,
            tuple(findings),
        )
    latch = str(close.get("latch_reason", "") or "")
    if latch:
        return Termination(
            TerminationKind.LATCHED_WRITE_FAILURE,
            f"the recorder latched under {latch!r} and closed the bag: "
            f"{close.get('latch_detail', '')}",
            evidence,
            tuple(findings),
        )
    return Termination(
        TerminationKind.CLEAN,
        f"closed by its recorder with reason {close.get('reason', '')!r}",
        evidence,
        tuple(findings),
    )


def _decode_counts(raw: Any) -> dict[str, int] | None:
    """Decode the recorder's JSON count map, or say it was undecodable."""

    if not isinstance(raw, str) or not raw:
        return None
    try:
        decoded = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(decoded, dict):
        return None
    return {str(key): int(value) for key, value in decoded.items() if isinstance(value, int)}


def reconcile_recorder_account(
    termination: Termination, observations: Mapping[str, ChannelObservation]
) -> dict[str, Any]:
    """Compare what the recorder said it dropped with what the bag shows.

    Two independent statements about the same loss: the recorder's own tally,
    written into the bag before the footer, and the interior holes a reader
    finds in the per-channel number lines. When they disagree, that is a
    finding — never a reconciliation in favour of whichever is smaller.
    """

    declared = termination.evidence.get("recorder_drops")
    observed = {
        key: int(value.sequence["missing_count"])
        for key, value in observations.items()
        if int(value.sequence["missing_count"]) > 0
    }
    findings: list[str] = []
    if declared is None:
        status = "unavailable"
        if observed:
            findings.append(
                f"the bag shows interior sequence holes on {sorted(observed)} but carries no "
                f"recorder drop tally to compare them against"
            )
    else:
        declared_nonzero = {key: value for key, value in declared.items() if value}
        status = "agrees" if declared_nonzero == observed else "disagrees"
        if status == "disagrees":
            findings.append(
                f"the recorder declares drops {declared_nonzero or {}} but the bag's number "
                f"lines show holes {observed or {}}"
            )
    return {
        "declared_drops": declared,
        "observed_sequence_holes": observed,
        "status": status,
        "findings": findings,
    }


def observe_channels(
    scan: McapScan,
    *,
    expected: Sequence[Channel] | None = None,
    configured_rates: Mapping[str, float] | None = None,
    tolerance: float = RATE_TOLERANCE,
) -> dict[str, ChannelObservation]:
    """Per-channel counts, rates, deficits and number-line reports.

    ``expected`` defaults to the channels registered in the bag itself, which
    is the honest expectation set: what the recorder declared it would record,
    read back off the bytes rather than supplied by the caller.
    """

    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
        raise SidecarRefusedError(f"tolerance must be a number, got {tolerance!r}")
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise SidecarRefusedError(f"tolerance must be finite and non-negative, got {tolerance!r}")
    entries = tuple(expected) if expected is not None else scan.channels
    rates = _validated_rates(configured_rates)

    counts = scan.counts()
    payload_bytes: dict[str, int] = {}
    for message in scan.messages:
        key = message.channel.channel_id
        payload_bytes[key] = payload_bytes.get(key, 0) + message.payload_bytes
    reports = scan.ledger().report(expected=[entry.channel_id for entry in entries])
    span_s = _session_span_s(scan)

    observations: dict[str, ChannelObservation] = {}
    for entry in entries:
        observations[entry.channel_id] = _observe_one(
            entry,
            messages=counts.get(entry.channel_id, 0),
            payload_bytes=payload_bytes.get(entry.channel_id, 0),
            report=reports[entry.channel_id],
            span_s=span_s,
            configured_rate=rates.get(entry.channel_id),
            tolerance=tolerance,
        )
    return observations


def _observe_one(
    entry: Channel,
    *,
    messages: int,
    payload_bytes: int,
    report: ChannelSequenceReport,
    span_s: float,
    configured_rate: float | None,
    tolerance: float,
) -> ChannelObservation:
    expected_rate = _expected_rate(entry, configured_rate)
    observed_rate = _round(messages / span_s) if span_s > 0.0 else None
    expected_messages: float | None = None
    deficit: float | None = None
    deficit_fraction: float | None = None

    if expected_rate is not None and span_s > 0.0:
        expected_messages = _round(expected_rate * span_s)
        deficit = _round(expected_messages - messages)

    if messages == 0:
        verdict = ChannelVerdict.ABSENT
        reason = (
            "event_driven_silence: this channel publishes only when something happens, so "
            "no message is not evidence of a fault"
            if entry.rate_kind is RateKind.EVENT_DRIVEN
            else "no_messages: the bag contains nothing from this channel"
        )
    elif report.missing_count > 0:
        verdict = ChannelVerdict.DEGRADED
        reason = (
            f"sequence_gap: {report.missing_count} message(s) were received and never "
            f"written; the holes are interior, which is loss, not truncation"
        )
    elif report.duplicate_count > 0:
        verdict = ChannelVerdict.DEGRADED
        reason = f"duplicate_sequence: {report.duplicate_count} repeated sequence number(s)"
    elif expected_rate is None:
        verdict = ChannelVerdict.UNASSESSABLE
        reason = (
            f"no_rate_expectation: rate_kind={entry.rate_kind.value} and no rate was "
            f"supplied from the capture configuration, so the delivered count was not "
            f"judged"
        )
    elif span_s <= 0.0 or expected_messages is None or deficit is None:
        verdict = ChannelVerdict.UNASSESSABLE
        reason = "window_too_short: the recorded span is zero, so no rate can be assessed"
    else:
        allowance = max(1.0, expected_messages * tolerance)
        if deficit > allowance:
            verdict = ChannelVerdict.DEGRADED
            reason = (
                f"rate_below_expectation: {messages} of {expected_messages:g} expected "
                f"message(s) over {span_s:.3f}s, short by {deficit:g} "
                f"({deficit / expected_messages:.1%})"
            )
        elif -deficit > allowance:
            verdict = ChannelVerdict.DEGRADED
            reason = (
                f"rate_above_expectation: {messages} message(s) against {expected_messages:g} "
                f"expected — the declared nominal rate is wrong, which is a finding about "
                f"the channel matrix, not a pass"
            )
        else:
            verdict = ChannelVerdict.PRESENT
            reason = (
                f"within_tolerance: {messages} of {expected_messages:g} expected message(s) "
                f"over {span_s:.3f}s"
            )

    if expected_messages:
        deficit_fraction = _round((deficit or 0.0) / expected_messages)

    return ChannelObservation(
        channel_id=entry.channel_id,
        human_name=entry.human_name,
        bag_topic=entry.bag_topic,
        frame_id=entry.frame_id,
        message_type=entry.message_type,
        rate_kind=entry.rate_kind.value,
        criticality=entry.criticality.value,
        verdict=verdict,
        reason=reason,
        messages=messages,
        payload_bytes=payload_bytes,
        expected_messages=expected_messages,
        deficit_messages=deficit,
        deficit_fraction=deficit_fraction,
        observed_rate_hz=observed_rate,
        expected_rate_hz=None if expected_rate is None else _round(expected_rate),
        sequence=report.to_dict(),
    )


def _expected_rate(entry: Channel, configured_rate: float | None) -> float | None:
    """A rate expectation exists only where somebody actually chose one."""

    if entry.rate_kind is RateKind.PERIODIC:
        return entry.nominal_rate_hz
    if entry.rate_kind is RateKind.EVENT_DRIVEN:
        return None
    return configured_rate


def _validated_rates(rates: Mapping[str, float] | None) -> dict[str, float]:
    if rates is None:
        return {}
    validated: dict[str, float] = {}
    for key, value in rates.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SidecarRefusedError(
                f"configured rate for {key!r} must be a number, got {value!r}"
            )
        if not math.isfinite(value) or value <= 0.0:
            raise SidecarRefusedError(
                f"configured rate for {key!r} must be finite and positive, got {value!r}"
            )
        validated[str(key)] = float(value)
    return validated


def _session_span_s(scan: McapScan) -> float:
    """Recorded window, from the host monotonic clock shared by all readers."""

    stamps = [message.envelope.host_monotonic_ns for message in scan.messages]
    if len(stamps) < 2:
        return 0.0
    return (max(stamps) - min(stamps)) / 1e9


def _round(value: float) -> float:
    """Six decimal places, so a sidecar digest is stable across machines."""

    return round(float(value), 6)


# --------------------------------------------------------------------------
# Building the manifest
# --------------------------------------------------------------------------

BASE_DOES_NOT_PROVE: tuple[str, ...] = (
    (
        "This sidecar binds an MCAP file by SHA-256; it does not prove that any channel "
        "carried the data its declared message_type claims. PS-D falsifies the matrix "
        "against the unit."
    ),
    (
        "Per-channel sequence holes prove loss between receipt and record. A message lost "
        "in transit before the subscriber callback ran was never sequenced and is "
        "invisible here."
    ),
    (
        "Observed rates are computed over the window actually present in the bag; they say "
        "nothing about intervals during which the recorder was not running."
    ),
    (
        "MCAP publish_time repeats log_time whenever the device supplied no clock; the "
        "authoritative answer is the envelope's explicitly null source_timestamp_ns."
    ),
    (
        "Frame ids name frames; they do not locate them. The transform between them is "
        "unmeasured unless a mount geometry block below says otherwise."
    ),
)


def build_sidecar(
    *,
    bag_id: str,
    mcap_path: Path | str,
    scan: McapScan | None = None,
    created_at_utc: str | None = None,
    expected_channels: Sequence[Channel] | None = None,
    configured_rates: Mapping[str, float] | None = None,
    attestation_digest: str | None = None,
    clock_map_digest: str | None = None,
    mount_geometry: Mapping[str, Mapping[str, Any]] | None = None,
    mcap_validation: tuple[str, str] | None = None,
    session_notes: Sequence[str] = (),
    extra_does_not_prove: Sequence[str] = (),
    rate_tolerance: float = RATE_TOLERANCE,
) -> dict[str, Any]:
    """Read the bag and emit a validated ``parcel.bag.v1`` manifest.

    Calls ``bags/schema.py:make_manifest`` unmodified — ``source="hardware"``
    (``schema.py:254``), ``source_clock="sensor"`` (``schema.py:130``),
    ``default_frames()`` (``schema.py:113-127``) and the ``extra`` mapping
    (``schema.py:293,311-313``) are all pre-existing surface. This module adds
    no schema of its own to that file and edits nothing in it.
    """

    if not bag_id.strip():
        raise SidecarRefusedError("bag_id must be non-empty")
    path = Path(mcap_path)
    if scan is None:
        scan = read_mcap(path)
    digest, size = sha256_file(path)

    entries = tuple(expected_channels) if expected_channels is not None else scan.channels
    if not entries:
        raise SidecarRefusedError(
            f"{path} registers no channels, so there is nothing to describe; a bag with no "
            f"channel table is a finding, not a manifest"
        )

    termination = classify_termination(scan)
    observations = observe_channels(
        scan,
        expected=entries,
        configured_rates=configured_rates,
        tolerance=rate_tolerance,
    )
    origin_block, source = _origin_block(scan)
    validation = mcap_validation or ("unavailable", "not attempted by this caller")
    mount_block = _mount_geometry_block(mount_geometry)

    capture: dict[str, Any] = {
        "schema": SIDECAR_SCHEMA,
        "envelope_schema": ENVELOPE_SCHEMA,
        # PS-G: which recorder wrote these bytes, and whether they are the copy
        # of record. Stated in the data rather than inferred from the presence
        # of an envelope, because "which bag is authoritative" is the question a
        # reader six months from now will actually have.
        "bag_format": BagFormat.PARCEL_MCAP.value,
        "role": RecorderRole.SECONDARY.value,
        "mcap": {
            "filename": path.name,
            "sha256": digest,
            "bytes": size,
            "message_encoding": MESSAGE_ENCODING,
            "writer": scan.library or MCAP_LIBRARY,
            "profile": scan.profile,
            "reference_reader_validation": {
                "status": validation[0],
                "detail": validation[1],
            },
        },
        "origin": origin_block,
        "termination": termination.to_dict(),
        "recorder_account": reconcile_recorder_account(termination, observations),
        "session": _session_block(scan),
        "channels": {key: value.to_dict() for key, value in sorted(observations.items())},
        "channel_summary": _channel_summary(observations),
        "clock_map": _digest_block(
            clock_map_digest,
            name="PS-C ClockMapV1",
            absent_note=(
                "no clock map is bound to this bag; cross-device timestamps in it are not "
                "recoverable, because received_monotonic_ns has a per-machine arbitrary epoch"
            ),
        ),
        "attestation": _digest_block(
            attestation_digest,
            name="PS-D HardwareAttestationV1",
            absent_note=(
                "no hardware attestation is bound to this bag; the edition, firmware, "
                "serials and per-channel presence of the unit that produced it are unverified"
            ),
        ),
        "mount_geometry": mount_block,
        "session_notes": [str(note) for note in session_notes],
    }

    manifest = make_manifest(
        bag_id=bag_id,
        created_at_utc=created_at_utc or _now_utc(),
        source=source,
        clocks=_clocks_block(scan),
        frames=_frames_block(entries, mount_block),
        topics=[entry.bag_topic for entry in entries],
        does_not_prove=_does_not_prove(
            termination=termination,
            observations=observations,
            capture=capture,
            extra=extra_does_not_prove,
        ),
        message_count=scan.message_count,
        extra={
            SIDECAR_EXTRA_KEY: capture,
            "hardware_claims": source == "hardware",
        },
    )
    return manifest


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _origin_block(scan: McapScan) -> tuple[dict[str, Any], str]:
    """Derive the manifest ``source`` from the envelopes, never from a caller.

    ``"hardware"`` is the authority-bearing value, so it is reachable only from
    messages that are actually in the bag and actually declare ``PHYSICAL``.
    """

    origins = scan.origins()
    if len(origins) > 1:
        raise SidecarRefusedError(
            f"the bag mixes evidence origins {sorted(origin.value for origin in origins)}; a "
            f"manifest cannot describe both a session and a rehearsal, and the mixture is "
            f"itself the finding"
        )
    if not origins:
        return (
            {
                "observed": [],
                "basis": "no_messages",
                "note": (
                    "the bag carries no messages, so it carries no evidence of origin; "
                    "source falls back to 'sim', which claims nothing"
                ),
            },
            "sim",
        )
    origin = next(iter(origins))
    return (
        {
            "observed": [origin.value],
            "basis": "envelopes",
            "note": f"every envelope in the bag declares {origin.value}",
        },
        "hardware" if origin is EvidenceOrigin.PHYSICAL else "sim",
    )


def _session_block(scan: McapScan) -> dict[str, Any]:
    monotonic = [message.envelope.host_monotonic_ns for message in scan.messages]
    realtime = [message.envelope.host_realtime_ns for message in scan.messages]
    sourced = [
        message.envelope.source_timestamp_ns
        for message in scan.messages
        if message.envelope.source_timestamp_ns is not None
    ]
    return {
        "messages": scan.message_count,
        "first_host_monotonic_ns": min(monotonic) if monotonic else None,
        "last_host_monotonic_ns": max(monotonic) if monotonic else None,
        "first_host_realtime_ns": min(realtime) if realtime else None,
        "last_host_realtime_ns": max(realtime) if realtime else None,
        "recorded_span_s": _round(_session_span_s(scan)),
        "messages_with_source_clock": len(sourced),
        "messages_without_source_clock": scan.message_count - len(sourced),
    }


def _channel_summary(observations: Mapping[str, ChannelObservation]) -> dict[str, Any]:
    by_verdict: dict[str, list[str]] = {member.value: [] for member in ChannelVerdict}
    for key, observation in sorted(observations.items()):
        by_verdict[observation.verdict.value].append(key)
    faults = sorted(key for key, value in observations.items() if value.is_fault)
    return {
        "by_verdict": by_verdict,
        "faults": faults,
        "fault_count": len(faults),
        "total_messages": sum(value.messages for value in observations.values()),
        "total_payload_bytes": sum(value.payload_bytes for value in observations.values()),
    }


def _clocks_block(scan: McapScan) -> dict[str, Any]:
    """``default_clocks(source_clock="sensor")`` with a real monotonic origin.

    ``schema.py:134`` hands back ``recording_monotonic_origin_ns: 0``, which is
    exactly the arbitrary-epoch problem the session plan names. Setting it to
    the first sample in the bag makes intra-bag offsets meaningful; making them
    meaningful ACROSS devices still needs PS-C.
    """

    clocks = default_clocks(source_clock="sensor")
    stamps = [message.envelope.host_monotonic_ns for message in scan.messages]
    clocks["recording_monotonic_origin_ns"] = min(stamps) if stamps else 0
    clocks["note"] = (
        f"{clocks['note']} recording_monotonic_origin_ns is this host's monotonic clock at "
        f"the first message in the bag; it has a per-machine arbitrary epoch and is "
        f"comparable across devices only through the PS-C clock map."
    )
    return clocks


def _frames_block(
    entries: Sequence[Channel], mount_block: Mapping[str, Any]
) -> dict[str, Any]:
    frames = default_frames()
    by_id = {entry.channel_id: entry for entry in entries}
    camera = by_id.get("d455.color")
    lidar = by_id.get("go2.utlidar.cloud") or by_id.get("l2.cloud")
    if camera is not None:
        frames["camera_frame"] = camera.frame_id
    if lidar is not None:
        frames["lidar_frame"] = lidar.frame_id
    measured = mount_block.get("status") == "measured"
    frames["ownership_note"] = (
        f"{frames['ownership_note']} Extrinsics between these frames are "
        f"{'recorded in capture.mount_geometry' if measured else 'UNMEASURED'}; this "
        f"repository has no TF implementation, so a frame id here is a label, not a location."
    )
    frames["channel_frames"] = {entry.channel_id: entry.frame_id for entry in entries}
    return frames


def _digest_block(value: str | None, *, name: str, absent_note: str) -> dict[str, Any]:
    """A digest, or a recorded absence. Never a placeholder digest."""

    if value is None:
        return {"artifact": name, "status": "absent", "digest": None, "note": absent_note}
    if not isinstance(value, str) or not _HEX64.match(value):
        raise SidecarRefusedError(
            f"{name} digest must be a 64-character lowercase hex SHA-256, got {value!r} — a "
            f"malformed digest is a refusal, never a recorded absence"
        )
    return {"artifact": name, "status": "present", "digest": value, "note": ""}


def _mount_geometry_block(
    geometry: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Validate PS-F's tape-measured extrinsics, or record that there are none.

    Every entry must name how it was measured and how well. A bare triple of
    numbers is refused: the mount extrinsic is the one quantity that becomes
    unrecoverable the moment the bracket is unbolted, so a fabricated one is
    worse than an absent one.
    """

    if geometry is None:
        return {
            "status": "unmeasured",
            "sensors": {},
            "note": (
                "no mount geometry was supplied; sensor extrinsics for this bag are "
                "unmeasured and become unrecoverable once the rig is disassembled (PS-F "
                "mount-geometry sheet)"
            ),
        }
    if not isinstance(geometry, Mapping) or not geometry:
        raise SidecarRefusedError(
            "mount_geometry must be a non-empty mapping of sensor -> measurement, or None"
        )
    sensors: dict[str, Any] = {}
    for sensor, entry in geometry.items():
        if not isinstance(entry, Mapping):
            raise SidecarRefusedError(f"mount geometry for {sensor!r} must be a mapping")
        missing = [key for key in _MOUNT_REQUIRED_KEYS if key not in entry]
        if missing:
            raise SidecarRefusedError(
                f"mount geometry for {sensor!r} is missing {missing}; an extrinsic without "
                f"a stated method and uncertainty is not a measurement"
            )
        parent = entry["parent_frame"]
        if not isinstance(parent, str) or not parent.strip():
            raise SidecarRefusedError(f"mount geometry for {sensor!r} needs a parent_frame")
        method = entry["method"]
        if not isinstance(method, str) or not method.strip():
            raise SidecarRefusedError(
                f"mount geometry for {sensor!r} needs a non-empty method (e.g. 'tape measure')"
            )
        measured_at = entry["measured_at_utc"]
        if not isinstance(measured_at, str) or not _ISO_UTC.match(measured_at):
            raise SidecarRefusedError(
                f"mount geometry for {sensor!r} needs measured_at_utc as ISO-8601 Z, got "
                f"{measured_at!r}"
            )
        uncertainty = _finite(entry["uncertainty_m"], f"{sensor}.uncertainty_m")
        if uncertainty <= 0.0:
            raise SidecarRefusedError(
                f"mount geometry for {sensor!r} needs a positive uncertainty_m; a zero "
                f"uncertainty claims a perfect tape measure"
            )
        sensors[str(sensor)] = {
            "parent_frame": parent,
            "xyz_m": _triple(entry["xyz_m"], f"{sensor}.xyz_m"),
            "rpy_rad": _triple(entry["rpy_rad"], f"{sensor}.rpy_rad"),
            "method": method,
            "uncertainty_m": _round(uncertainty),
            "measured_at_utc": measured_at,
        }
    return {
        "status": "measured",
        "sensors": sensors,
        "note": (
            "hand-measured extrinsics with stated method and uncertainty; they are a "
            "measurement of the rig as assembled, not a calibration"
        ),
    }


def _triple(value: Any, field: str) -> list[float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise SidecarRefusedError(f"{field} must be a 3-element sequence, got {value!r}")
    if len(value) != 3:
        raise SidecarRefusedError(f"{field} must have 3 elements, got {len(value)}")
    return [_round(_finite(item, f"{field}[{index}]")) for index, item in enumerate(value)]


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SidecarRefusedError(f"{field} must be a number, got {type(value).__name__} {value!r}")
    if not math.isfinite(value):
        raise SidecarRefusedError(f"{field} must be finite, got {value!r}")
    return float(value)


def _does_not_prove(
    *,
    termination: Termination,
    observations: Mapping[str, ChannelObservation],
    capture: Mapping[str, Any],
    extra: Sequence[str],
) -> list[str]:
    lines = list(BASE_DOES_NOT_PROVE)
    # Absent for a rosbag2 recording: those bytes were written by the reference
    # rosbag2 MCAP writer, so "our subset writer was never read by the reference
    # implementation" is not a caveat that applies to them.
    mcap_block = capture.get("mcap")
    validation = mcap_block.get("reference_reader_validation") if mcap_block else None
    if validation is not None and validation["status"] != "validated":
        lines.append(
            "The MCAP bytes were written by a self-contained subset writer and have NOT "
            f"been read by the reference mcap implementation ({validation['status']}: "
            f"{validation['detail']})."
        )
    if termination.kind is TerminationKind.TRUNCATED:
        evidence = termination.evidence
        lines.append(
            f"The recording was TRUNCATED at byte {evidence['last_complete_offset']} of "
            f"{evidence['file_bytes']} ({evidence['trailing_bytes']} trailing byte(s) "
            f"discarded). Everything after that instant was never written, and its absence "
            f"is NOT a sensor dropout. How many messages the recorder had already accepted "
            f"and not yet flushed is unknowable from this bag."
        )
    if termination.kind is TerminationKind.CORRUPT:
        lines.append(
            f"The bag is CORRUPT past byte {termination.evidence['last_complete_offset']}: "
            f"{termination.detail}. Messages before that point decoded and are reported; "
            f"nothing is claimed about the rest."
        )
    if termination.kind is TerminationKind.LATCHED_WRITE_FAILURE:
        lines.append(
            f"The recorder latched a write failure and stopped: {termination.detail}. The "
            f"session ended early by refusal, not by plan."
        )
    if termination.kind is TerminationKind.UNKNOWN:
        lines.append(
            "The bag's framing is complete but it carries no recorder close record, so "
            "nothing here confirms the recording ended on purpose."
        )
    for finding in termination.findings:
        lines.append(f"Unreconciled finding: {finding}")
    for finding in capture["recorder_account"]["findings"]:
        lines.append(f"Unreconciled finding: {finding}")
    if capture.get("bag_format") == BagFormat.PARCEL_MCAP.value:
        lines.append(
            "This is the SECONDARY copy. The parcel-capture MCAP format is readable only "
            "by this repository — no downstream SLAM or calibration tool can open it — so "
            "it must never be the sole copy of a channel. The primary recording is "
            "`ros2 bag record -s mcap` (scripts/parcel_capture/rosbag2.py)."
        )
    for key in ("clock_map", "attestation"):
        block = capture[key]
        if block["status"] != "present":
            lines.append(f"{block['artifact']} is absent: {block['note']}.")
    if capture["mount_geometry"]["status"] != "measured":
        lines.append(
            "Sensor mount extrinsics were not measured for this bag; the frames it names "
            "cannot be related to one another, and that is unrecoverable once the rig is "
            "disassembled."
        )
    faults = sorted(key for key, value in observations.items() if value.is_fault)
    if faults:
        lines.append(
            f"{len(faults)} channel(s) are degraded or absent ({', '.join(faults)}); this bag "
            f"does not carry a complete picture of the session for them."
        )
    unassessable = sorted(
        key
        for key, value in observations.items()
        if value.verdict is ChannelVerdict.UNASSESSABLE
    )
    if unassessable:
        lines.append(
            f"{len(unassessable)} channel(s) carry no rate expectation and were not assessed "
            f"({', '.join(unassessable)}); unassessed is not passed."
        )
    for line in extra:
        text = str(line).strip()
        if not text:
            raise SidecarRefusedError("does_not_prove entries must be non-empty strings")
        lines.append(text)
    return lines


# --------------------------------------------------------------------------
# Persistence and verification
# --------------------------------------------------------------------------


def sidecar_path_for(mcap_path: Path | str) -> Path:
    path = Path(mcap_path)
    return path.with_name(path.name + SIDECAR_SUFFIX)


def canonical_sidecar_json(sidecar: Mapping[str, Any]) -> str:
    return json.dumps(
        sidecar, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def sidecar_digest(sidecar: Mapping[str, Any]) -> str:
    """SHA-256 over the canonical sidecar, for PS-C/PS-D to bind back to."""

    return hashlib.sha256(canonical_sidecar_json(sidecar).encode("utf-8")).hexdigest()


def write_sidecar(sidecar: Mapping[str, Any], path: Path | str) -> Path:
    """Write atomically and durably: temp file, fsync, rename, fsync dir.

    The sidecar is the only place the bag's digest lives. A half-written one is
    worse than none, and ``os.replace`` plus two fsyncs is what makes the file
    either wholly old or wholly new across a power cut.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    payload = json.dumps(dict(sidecar), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, target)
    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return target


def read_sidecar(path: Path | str) -> dict[str, Any]:
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SidecarRefusedError(f"cannot read sidecar {path}: {error}") from error
    if not isinstance(record, dict):
        raise SidecarRefusedError(f"sidecar {path} is not a JSON object")
    return record


def verify_sidecar(
    sidecar: Mapping[str, Any], mcap_path: Path | str, *, rescan: bool = False
) -> SidecarVerification:
    """Re-bind a sidecar to bytes. Any doubt is a failure, never an exception.

    This is the gate that makes the digest mean something: change one byte of
    the MCAP and this returns ``ok=False`` naming the mismatch.
    """

    failures: list[str] = []
    recorded_digest = ""
    recorded_bytes = -1
    block: Mapping[str, Any] | None = None

    if sidecar.get("schema_version") != SCHEMA_VERSION:
        failures.append(
            f"manifest schema_version is {sidecar.get('schema_version')!r}, expected "
            f"{SCHEMA_VERSION!r}"
        )
    raw_block = sidecar.get(SIDECAR_EXTRA_KEY)
    if not isinstance(raw_block, Mapping):
        failures.append(f"manifest carries no {SIDECAR_EXTRA_KEY!r} block")
    else:
        block = raw_block
        if block.get("bag_format") == BagFormat.ROSBAG2_MCAP.value:
            # A rosbag2 recording is a DIRECTORY of split files, not one file
            # with one digest. Verifying it through this single-file path would
            # check one split and report the whole take as bound.
            return SidecarVerification(
                ok=False,
                failures=(
                    (
                        "this sidecar describes a rosbag2 recording (a directory of split "
                        "files); verify it with verify_rosbag2_sidecar(), which re-digests "
                        "every file and fails on a file the sidecar does not name"
                    ),
                ),
                recorded_sha256="",
                computed_sha256="",
                recorded_bytes=-1,
                computed_bytes=-1,
            )
        if block.get("schema") != SIDECAR_SCHEMA:
            failures.append(
                f"capture block schema is {block.get('schema')!r}, expected {SIDECAR_SCHEMA!r}"
            )
        mcap_block = block.get("mcap")
        if not isinstance(mcap_block, Mapping):
            failures.append("capture block carries no mcap record")
        else:
            recorded_digest = str(mcap_block.get("sha256", ""))
            raw_bytes = mcap_block.get("bytes")
            recorded_bytes = raw_bytes if isinstance(raw_bytes, int) else -1
            if not _HEX64.match(recorded_digest):
                failures.append(f"recorded sha256 is not a hex digest: {recorded_digest!r}")

    try:
        computed_digest, computed_bytes = sha256_file(mcap_path)
    except OSError as error:
        return SidecarVerification(
            ok=False,
            failures=tuple(failures + [f"cannot read {mcap_path}: {error}"]),
            recorded_sha256=recorded_digest,
            computed_sha256="",
            recorded_bytes=recorded_bytes,
            computed_bytes=-1,
        )

    if recorded_digest and computed_digest != recorded_digest:
        failures.append(
            f"digest mismatch: sidecar records {recorded_digest}, the file hashes to "
            f"{computed_digest}"
        )
    if recorded_bytes >= 0 and computed_bytes != recorded_bytes:
        failures.append(
            f"size mismatch: sidecar records {recorded_bytes} bytes, the file is "
            f"{computed_bytes}"
        )
    if rescan and block is not None:
        failures.extend(_rescan_failures(block, sidecar, mcap_path))

    return SidecarVerification(
        ok=not failures,
        failures=tuple(failures),
        recorded_sha256=recorded_digest,
        computed_sha256=computed_digest,
        recorded_bytes=recorded_bytes,
        computed_bytes=computed_bytes,
    )


def _rescan_failures(
    block: Mapping[str, Any], sidecar: Mapping[str, Any], mcap_path: Path | str
) -> list[str]:
    failures: list[str] = []
    try:
        scan = read_mcap(mcap_path)
    except Exception as error:  # noqa: BLE001 - an unreadable bag is the finding
        return [f"rescan failed: {error}"]
    if scan.message_count != sidecar.get("message_count"):
        failures.append(
            f"message_count mismatch: sidecar records {sidecar.get('message_count')!r}, the "
            f"bag holds {scan.message_count}"
        )
    recorded_kind = block.get("termination", {}).get("kind")
    live_kind = classify_termination(scan).kind.value
    if recorded_kind != live_kind:
        failures.append(
            f"termination mismatch: sidecar records {recorded_kind!r}, the bag now reads "
            f"{live_kind!r}"
        )
    return failures


def verify_sidecar_or_raise(
    sidecar: Mapping[str, Any], mcap_path: Path | str, *, rescan: bool = False
) -> SidecarVerification:
    result = verify_sidecar(sidecar, mcap_path, rescan=rescan)
    if not result.ok:
        raise SidecarRefusedError(
            f"sidecar does not bind {mcap_path}: {'; '.join(result.failures)}"
        )
    return result


def finalize(
    mcap_path: Path | str,
    *,
    bag_id: str,
    sidecar_path: Path | str | None = None,
    **kwargs: Any,
) -> tuple[dict[str, Any], Path]:
    """Build, validate and durably write a sidecar next to its bag.

    The one call an operator makes after a session — including after a session
    that ended in a SIGKILL, which is the case this whole module exists for.
    """

    try:
        sidecar = build_sidecar(bag_id=bag_id, mcap_path=mcap_path, **kwargs)
    except BagSchemaError as error:
        raise SidecarRefusedError(f"manifest rejected by bags/schema.py: {error}") from error
    target = Path(sidecar_path) if sidecar_path is not None else sidecar_path_for(mcap_path)
    return sidecar, write_sidecar(sidecar, target)


# --------------------------------------------------------------------------
# The rosbag2 adapter — card PS-G
# --------------------------------------------------------------------------
#
# Everything above describes a parcel-capture MCAP. This half describes the
# PRIMARY recording, which `ros2 bag record -s mcap` writes and which every
# downstream tool can actually open. The sidecar is the same `parcel.bag.v1`
# manifest, built from a different reader, and it says which reader in
# `capture.bag_format`.
#
# Two things are structurally weaker here than on the Parcel path, and the
# sidecar says both out loud rather than papering over them:
#
#   1. **No per-channel sequence evidence.** PS-A's per-channel counter is
#      minted at receipt by our recorder. rosbag2 does not mint one, so an
#      INTERIOR hole in one channel's number line — the signal that proves a
#      drop and distinguishes it from a truncation — does not exist in a
#      rosbag2 bag. What remains is a count against an expected rate, which
#      detects a sustained deficit and cannot attribute a single lost message.
#      `/events/messages_lost` (when the build publishes it) is the recorder's
#      own account and is recorded as a channel for exactly this reason.
#   2. **Counts may be the writer's claim rather than a walk.** A compressed
#      chunk cannot be walked without zstandard, which is not installed;
#      `capture.rosbag2.count_basis` names which answer is being quoted.


ROSBAG2_DOES_NOT_PROVE: tuple[str, ...] = (
    (
        "rosbag2 mints no per-channel sequence number, so this sidecar cannot prove that a "
        "channel lost an individual message. It detects a sustained rate deficit and a "
        "channel that delivered nothing; a single dropped message between the publisher and "
        "the recorder leaves no hole to find."
    ),
    (
        "Per-topic counts describe what reached the recorder. A message lost on the DDS wire "
        "before the recorder's subscription callback ran was never counted anywhere."
    ),
    (
        "Message payloads are CDR and were not decoded here. This sidecar says a topic "
        "carried N messages of a declared type; it does not say the bytes are that type."
    ),
    (
        "Recorded spans come from MCAP log_time, which is the RECORDER's clock at receipt, "
        "not the sensor's. Cross-device alignment needs the PS-I sync ritual."
    ),
)


@dataclass(frozen=True)
class Rosbag2FileRecord:
    """One MCAP file of a split recording, digested and classified."""

    filename: str
    sha256: str
    bytes: int
    termination: str
    detail: str
    count_basis: str
    profile: str
    library: str
    messages: int
    findings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "termination": self.termination,
            "detail": self.detail,
            "count_basis": self.count_basis,
            "profile": self.profile,
            "library": self.library,
            "messages": self.messages,
            "findings": list(self.findings),
        }


@dataclass(frozen=True)
class Rosbag2Verification:
    """Re-binding a rosbag2 sidecar to the files it claims to describe."""

    ok: bool
    failures: tuple[str, ...]
    files_checked: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "failures": list(self.failures),
            "files_checked": self.files_checked,
        }


def _rosbag2_termination(scans: Sequence[Rosbag2Scan]) -> Termination:
    """Classify the recording from the framing of its files.

    A split recording is truncated if its LAST file is: earlier files are closed
    by the split itself. A non-final file that is truncated is a different and
    worse finding — the recorder did not close a file it said it had finished —
    and is reported as such rather than averaged away.
    """

    findings: list[str] = []
    evidence: dict[str, Any] = {
        "files": [scan.path.name for scan in scans],
        "terminations": [scan.termination.value for scan in scans],
        "file_bytes": [scan.file_bytes for scan in scans],
        "last_complete_offset": scans[-1].last_complete_offset if scans else 0,
        "trailing_bytes": sum(scan.trailing_bytes for scan in scans),
        "messages_recovered": sum(scan.message_count for scan in scans),
        "recorder_close_record": None,
    }
    for scan in scans[:-1]:
        if scan.termination is not Rosbag2Termination.CLEAN:
            findings.append(
                f"{scan.path.name} is a non-final split file and is {scan.termination.value}: "
                f"{scan.detail}"
            )
    for scan in scans:
        findings.extend(scan.findings)
    last = scans[-1]
    if last.termination is Rosbag2Termination.CORRUPT:
        return Termination(TerminationKind.CORRUPT, last.detail, evidence, tuple(findings))
    if last.termination is Rosbag2Termination.TRUNCATED:
        return Termination(
            TerminationKind.TRUNCATED,
            last.detail or "the final file ends without a footer; the recorder was killed",
            evidence,
            tuple(findings),
        )
    return Termination(
        TerminationKind.CLEAN,
        f"every file carries a complete MCAP terminal structure ({len(scans)} file(s))",
        evidence,
        tuple(findings),
    )


def _observe_rosbag2_channel(
    entry: Channel,
    *,
    messages: int,
    payload_bytes: int,
    span_s: float,
    configured_rate: float | None,
    tolerance: float,
    basis: str,
) -> ChannelObservation:
    """Count against expectation. No sequence evidence exists — say so."""

    expected_rate = _expected_rate(entry, configured_rate)
    observed_rate = _round(messages / span_s) if span_s > 0.0 else None
    expected_messages: float | None = None
    deficit: float | None = None
    deficit_fraction: float | None = None
    if expected_rate is not None and span_s > 0.0:
        expected_messages = _round(expected_rate * span_s)
        deficit = _round(expected_messages - messages)

    if messages == 0:
        verdict = ChannelVerdict.ABSENT
        reason = (
            "event_driven_silence: this channel publishes only when something happens, so "
            "no message is not evidence of a fault"
            if entry.rate_kind is RateKind.EVENT_DRIVEN
            else "no_messages: the recorder subscribed and nothing arrived on this topic"
        )
    elif expected_rate is None:
        verdict = ChannelVerdict.UNASSESSABLE
        reason = (
            f"no_rate_expectation: rate_kind={entry.rate_kind.value} and no configured rate "
            f"was supplied, so {messages} message(s) were not judged"
        )
    elif expected_messages is None or deficit is None or span_s <= 0.0:
        verdict = ChannelVerdict.UNASSESSABLE
        reason = "window_too_short: the recorded span is zero, so no rate can be assessed"
    else:
        allowance = max(1.0, expected_messages * tolerance)
        if deficit > allowance:
            verdict = ChannelVerdict.DEGRADED
            reason = (
                f"rate_below_expectation: {messages} of {expected_messages:g} expected "
                f"message(s) over {span_s:.3f}s, short by {deficit:g} "
                f"({deficit / expected_messages:.1%})"
            )
        elif -deficit > allowance:
            verdict = ChannelVerdict.DEGRADED
            reason = (
                f"rate_above_expectation: {messages} message(s) against "
                f"{expected_messages:g} expected — the declared nominal rate is wrong, "
                f"which is a finding about the channel matrix, not a pass"
            )
        else:
            verdict = ChannelVerdict.PRESENT
            reason = (
                f"within_tolerance: {messages} of {expected_messages:g} expected message(s) "
                f"over {span_s:.3f}s"
            )
    if expected_messages:
        deficit_fraction = _round((deficit or 0.0) / expected_messages)

    return ChannelObservation(
        channel_id=entry.channel_id,
        human_name=entry.human_name,
        bag_topic=entry.bag_topic,
        frame_id=entry.frame_id,
        message_type=entry.message_type,
        rate_kind=entry.rate_kind.value,
        criticality=entry.criticality.value,
        verdict=verdict,
        reason=reason,
        messages=messages,
        payload_bytes=payload_bytes,
        expected_messages=expected_messages,
        deficit_messages=deficit,
        deficit_fraction=deficit_fraction,
        observed_rate_hz=observed_rate,
        expected_rate_hz=None if expected_rate is None else _round(expected_rate),
        sequence={
            "status": "unavailable",
            "reason": (
                "rosbag2 mints no per-channel sequence number, so an interior hole — the "
                "only proof of an individual dropped message — cannot exist in this bag"
            ),
            "count_basis": basis,
        },
    )


# --------------------------------------------------------------------------
# The GO-RECORD gate — card S-1 (scrum/20260814/task_1/REVISED_BOARD.md)
# --------------------------------------------------------------------------
#
# The verified P0: four optical streams recorded, no camera_info, no /tf, no
# /tf_static. This gate is what makes that state unable to certify. A bag
# CANNOT finalize GO-RECORD when:
#
#   (a) an active optical stream lacks a matching CameraInfo — matching means
#       the SAME width/height and the same delivery rate as the recorded
#       stream, both read out of the bag's own bytes, never declared;
#   (b) sensor transforms are absent or ambiguous — a frame with two competing
#       parents, or two competing declarations of one extrinsic, is ambiguous;
#   (c) the transient-local /tf_static published before record start was
#       neither captured in the bag nor bound as a machine-readable
#       static-transform snapshot;
#   (d) the run claims recoverable cross-device time without a certifiable
#       sync fit bound by digest (the PS-I fit, wired here rather than proven
#       only in isolation).
#
# Refusal here does not suppress the sidecar: the sidecar is a recovery pass
# and always records what happened, including a REFUSED certification with its
# reasons. What refusal forbids is the CLAIM: ``finalize_rosbag2`` with
# ``require_go_record=True`` raises instead of writing a certified manifest.

#: Wire identifier of a static-transform snapshot taken before record start.
STATIC_TF_SNAPSHOT_SCHEMA = "parcel.capture.static_tf_snapshot.v1"

_SNAPSHOT_REQUIRED_KEYS = ("schema", "captured_at_utc", "source", "transforms")

#: Two declarations of one parent->child extrinsic that differ by more than
#: this are COMPETING declarations, which is ambiguity, which is a refusal.
_TRANSFORM_EPSILON = 1e-9

#: How far a CameraInfo topic's delivered count may drift from its image
#: stream's before the pair no longer shares a rate profile. Wider than the
#: channel-rate tolerance on purpose: the driver publishes CameraInfo per
#: frame, but the two subscriptions start at slightly different instants.
CAMERA_INFO_RATE_TOLERANCE = 0.10

#: Below this many images the rate leg cannot certify anything: a single
#: missing CameraInfo is already outside the tolerance, so a bag this short is
#: recorded as a finding rather than being waved through by a rounding floor.
#: Derived from the tolerance, never a second hand-set number (FX-2 F3).
CAMERA_INFO_RATE_MIN_MESSAGES = round(1.0 / CAMERA_INFO_RATE_TOLERANCE)

#: Payloads to pull per topic when reading calibration and transforms back out
#: of the bag. Transforms need many (one TFMessage per publisher); an image
#: needs one message for the profile; calibration keeps the whole collected
#: window so a CameraInfo that changes after the first message is seen at all
#: (FX-2 F4 — and see :func:`calibration_digest_of` for what that does NOT
#: cover).
_TF_STATIC_PAYLOADS = 64
_OPTICAL_PAYLOADS = 4
_CALIBRATION_PAYLOADS = 64


class GoRecordRefusedError(SidecarRefusedError):
    """A run asked for GO-RECORD certification and the bag cannot carry it."""


@dataclass(frozen=True)
class GoRecordAssessment:
    """The certification verdict, with every refusal named and its evidence."""

    certified: bool
    refusals: tuple[str, ...]
    findings: tuple[str, ...]
    streams: Mapping[str, Any]
    transforms: Mapping[str, Any]
    calibration_sha256: str | None
    snapshot_sha256: str | None
    sync: Mapping[str, Any]

    @property
    def status(self) -> str:
        return "GO-RECORD" if self.certified else "REFUSED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "certified": self.certified,
            "refusals": list(self.refusals),
            "findings": list(self.findings),
            "streams": {key: dict(value) for key, value in sorted(self.streams.items())},
            "transforms": dict(self.transforms),
            "calibration_sha256": self.calibration_sha256,
            "snapshot_sha256": self.snapshot_sha256,
            "sync": dict(self.sync),
        }


def validate_static_transform_snapshot(
    snapshot: Mapping[str, Any],
) -> tuple[TransformView, ...]:
    """A machine-readable snapshot, or a refusal. Prose is not a snapshot.

    The snapshot exists for the transient-local gap: ``/tf_static`` is
    published once and latched, so a recorder started after the publisher may
    never receive it. Capturing it BEFORE record start (``ros2 topic echo``
    into a file, or the driver's own declaration) and binding it here is the
    only honest substitute — and only if it is strict enough to be used
    downstream without a human interpreting it.
    """

    if not isinstance(snapshot, Mapping):
        raise SidecarRefusedError(
            f"a static-transform snapshot must be a mapping, got "
            f"{type(snapshot).__name__}"
        )
    missing = [key for key in _SNAPSHOT_REQUIRED_KEYS if key not in snapshot]
    if missing:
        raise SidecarRefusedError(
            f"static-transform snapshot is missing {missing}; a snapshot without "
            f"provenance is indistinguishable from a guess"
        )
    if snapshot["schema"] != STATIC_TF_SNAPSHOT_SCHEMA:
        raise SidecarRefusedError(
            f"static-transform snapshot schema is {snapshot['schema']!r}, expected "
            f"{STATIC_TF_SNAPSHOT_SCHEMA!r}"
        )
    captured_at = snapshot["captured_at_utc"]
    if not isinstance(captured_at, str) or not _ISO_UTC.match(captured_at):
        raise SidecarRefusedError(
            f"snapshot captured_at_utc must be ISO-8601 Z, got {captured_at!r}"
        )
    source = snapshot["source"]
    if not isinstance(source, str) or not source.strip():
        raise SidecarRefusedError(
            "snapshot source must say how the transforms were obtained (e.g. the "
            "`ros2 topic echo /tf_static` invocation run before record start)"
        )
    raw = snapshot["transforms"]
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise SidecarRefusedError(
            "snapshot transforms must be a non-empty sequence; an empty snapshot "
            "snapshots nothing and must not satisfy the tf_static gate"
        )
    out: list[TransformView] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, Mapping):
            raise SidecarRefusedError(f"snapshot transform [{index}] must be a mapping")
        for key in ("parent_frame", "child_frame"):
            value = entry.get(key)
            if not isinstance(value, str) or not value.strip():
                raise SidecarRefusedError(
                    f"snapshot transform [{index}] needs a non-empty {key}"
                )
        translation = _triple(entry.get("translation_m"), f"snapshot[{index}].translation_m")
        rotation = entry.get("rotation_xyzw")
        if isinstance(rotation, (str, bytes)) or not isinstance(rotation, (list, tuple)) or len(rotation) != 4:
            raise SidecarRefusedError(
                f"snapshot transform [{index}] needs rotation_xyzw as 4 numbers"
            )
        quat = tuple(
            _finite(item, f"snapshot[{index}].rotation_xyzw[{position}]")
            for position, item in enumerate(rotation)
        )
        norm = math.sqrt(math.fsum(item * item for item in quat))
        if abs(norm - 1.0) > 1e-6:
            raise SidecarRefusedError(
                f"snapshot transform [{index}] rotation has norm {norm:.9f}; a "
                f"non-unit quaternion is not an orientation and must not enter the "
                f"transform record"
            )
        out.append(
            TransformView(
                parent_frame=str(entry["parent_frame"]),
                child_frame=str(entry["child_frame"]),
                translation_m=(translation[0], translation[1], translation[2]),
                rotation_xyzw=(quat[0], quat[1], quat[2], quat[3]),
            )
        )
    return tuple(out)


def static_transform_snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    """SHA-256 over the canonical snapshot JSON, for the sidecar to bind."""

    canonical = json.dumps(
        _jsonable(snapshot), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def calibration_digest_of(
    views: Mapping[str, Sequence[CameraInfoView]],
) -> str:
    """SHA-256 over the canonical decoded calibration set, per camera_info topic.

    What this covers, exactly (corrected in FX-2 F4, where the previous wording
    claimed more than the code did):

    * Every DISTINCT decoded calibration seen in the collected window for each
      topic, in first-seen order — not merely the first message. A stream that
      re-publishes different intrinsics inside that window moves the digest and
      is reported as drift by :func:`assess_go_record`.
    * The decoded CALIBRATION CONTENT, not the raw bytes. Two payloads that
      differ only in their header stamp or in CDR padding decode to the same
      :class:`CameraInfoView` and hash the same, by design: the digest names
      the calibration, and every raw byte of the bag is already covered by the
      per-file ``sha256`` the sidecar records and ``verify_rosbag2_sidecar``
      recomputes.
    * NOT a calibration that first changes after the collected window
      (``_CALIBRATION_PAYLOADS`` per split file). That window is bounded on
      purpose — extending it to the whole bag costs a second full parse of a
      take that is ~100 GiB — and the gap is named rather than papered over.
    """

    canonical = json.dumps(
        {
            topic: [view.to_dict() for view in sequence]
            for topic, sequence in sorted(views.items())
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _calibration_difference(first: CameraInfoView, second: CameraInfoView) -> str:
    """Name the calibration fields that moved, so the finding is actionable."""

    left, right = first.to_dict(), second.to_dict()
    moved = [key for key in sorted(left) if left[key] != right[key]]
    return "changed field(s): " + ", ".join(moved) if moved else "identical fields"


def _distinct_calibrations(
    payloads: Sequence[bytes], topic: str, failures: list[str]
) -> list[CameraInfoView]:
    """Every distinct decoded CameraInfo in ``payloads``, in first-seen order.

    Identical calibrations collapse to one entry — the normal case is a driver
    republishing the same intrinsics per frame — so the digest stays a name for
    the calibration and grows only when the calibration itself changes.
    """

    seen: list[CameraInfoView] = []
    for payload in payloads:
        try:
            view = decode_camera_info(payload)
        except CdrDecodeError as error:
            failures.append(f"{topic}: CameraInfo no longer decodes: {error}")
            return seen
        if view not in seen:
            seen.append(view)
    return seen


def _collect_support_payloads(
    files: Sequence[Path],
    optical_topics: Mapping[str, str],
) -> tuple[dict[str, list[bytes]], list[str]]:
    """Image/CameraInfo/tf_static payloads across every split file."""

    wanted: list[str] = ["/tf_static"]
    info_topics = set()
    for image_topic, info_topic in optical_topics.items():
        wanted.extend((image_topic, info_topic))
        info_topics.add(info_topic)
    merged: dict[str, list[bytes]] = {topic: [] for topic in wanted}
    findings: list[str] = []
    per_call = max(_TF_STATIC_PAYLOADS, _CALIBRATION_PAYLOADS, _OPTICAL_PAYLOADS)
    for path in files:
        per_file, file_findings = collect_topic_payloads(
            path, wanted, max_per_topic=per_call
        )
        findings.extend(f"{path.name}: {item}" for item in file_findings)
        for topic, payloads in per_file.items():
            if topic == "/tf_static":
                ceiling = _TF_STATIC_PAYLOADS
            elif topic in info_topics:
                # Keep the whole collected window rather than one message: the
                # extra retention is free (these payloads were already read),
                # and it is what lets a mid-window calibration change be seen.
                ceiling = _CALIBRATION_PAYLOADS
            else:
                ceiling = _OPTICAL_PAYLOADS
            for payload in payloads:
                if len(merged[topic]) < ceiling:
                    merged[topic].append(payload)
    return merged, findings


def assess_go_record(
    bag_dir: Path | str,
    *,
    counts: Mapping[str, int],
    files: Sequence[Path] | None = None,
    static_transform_snapshot: Mapping[str, Any] | None = None,
    sync_fit: SyncFitV1 | None = None,
    claims_recoverable_time: bool = False,
    camera_info_rate_tolerance: float = CAMERA_INFO_RATE_TOLERANCE,
) -> GoRecordAssessment:
    """Judge one recorded bag against the GO-RECORD completeness gate.

    Every input to the verdict is either read out of the bag's bytes (image
    profiles, CameraInfo, /tf_static) or bound by digest (the snapshot, the
    sync fit). ``counts`` is the per-topic count map the caller already built
    from the scans; a topic absent from it is a topic that recorded nothing.
    """

    if files is None:
        files = discover_bag(bag_dir).files
    refusals: list[str] = []
    findings: list[str] = []

    # -- which certified-optical streams are ACTIVE in this bag ------------
    topic_by_channel = {value: key for key, value in CHANNEL_BY_TOPIC.items()}
    optical_topics: dict[str, str] = {}
    active_channels: list[str] = []
    for channel_id in certified_optical_channel_ids():
        image_topic = topic_by_channel.get(channel_id)
        if image_topic is None:  # pragma: no cover - table invariant
            raise SidecarRefusedError(
                f"certified optical channel {channel_id} has no recorded topic"
            )
        if counts.get(image_topic, 0) > 0:
            optical_topics[image_topic] = camera_info_topic_for(image_topic)
            active_channels.append(channel_id)
    if not active_channels:
        findings.append(
            "no active certified-optical stream in this bag; the camera-calibration "
            "legs of GO-RECORD are vacuous here and certify nothing about optics"
        )

    payloads, payload_findings = _collect_support_payloads(files, optical_topics)
    findings.extend(payload_findings)

    # -- (a) matching CameraInfo per active optical stream ------------------
    streams: dict[str, dict[str, Any]] = {}
    calibration_views: dict[str, list[CameraInfoView]] = {}
    for image_topic, info_topic in sorted(optical_topics.items()):
        record: dict[str, Any] = {
            "camera_info_topic": info_topic,
            "image_messages": counts.get(image_topic, 0),
            "camera_info_messages": counts.get(info_topic, 0),
        }
        streams[image_topic] = record
        if counts.get(info_topic, 0) <= 0:
            refusals.append(
                f"active optical stream {image_topic} recorded "
                f"{counts.get(image_topic, 0)} image(s) with NO CameraInfo on "
                f"{info_topic}; without intrinsics and a distortion model this "
                f"stream cannot feed camera SLAM or camera-LiDAR fusion, and no "
                f"post-session effort can recover them"
            )
            continue
        image_meta = _decode_first(
            payloads.get(image_topic, ()), decode_image_meta, image_topic, refusals
        )
        info_view = _decode_first(
            payloads.get(info_topic, ()), decode_camera_info, info_topic, refusals
        )
        if image_meta is None or info_view is None:
            continue
        record["image_profile"] = image_meta.to_dict()
        record["camera_info_profile"] = {
            "width": info_view.width,
            "height": info_view.height,
            "distortion_model": info_view.distortion_model,
            "frame_id": info_view.frame_id,
        }
        if (image_meta.width, image_meta.height) != (info_view.width, info_view.height):
            refusals.append(
                f"{image_topic} records a {image_meta.width}x{image_meta.height} "
                f"stream but {info_topic} carries a "
                f"{info_view.width}x{info_view.height} calibration; a mismatched "
                f"profile is a calibration for a stream that was not recorded"
            )
            continue
        image_count = counts.get(image_topic, 0)
        info_count = counts.get(info_topic, 0)
        # PROPORTIONAL, with no floor. The old `max(1.0, ...)` floor only ever
        # applied where it was wrong — below CAMERA_INFO_RATE_MIN_MESSAGES
        # images — and there it certified deficits of 50% and more (FX-2 F3:
        # 2 images / 1 CameraInfo reached GO-RECORD). At larger counts the
        # proportional allowance already exceeds 1.0, so nothing that used to
        # pass on the strength of the tolerance stops passing.
        allowance = image_count * camera_info_rate_tolerance
        if abs(image_count - info_count) > allowance:
            refusals.append(
                f"{info_topic} delivered {info_count} CameraInfo message(s) against "
                f"{image_count} image(s) on {image_topic}; outside the "
                f"{camera_info_rate_tolerance:.0%} rate profile, so the calibration "
                f"stream did not track the image stream it claims to describe"
            )
            continue
        if image_count < CAMERA_INFO_RATE_MIN_MESSAGES:
            findings.append(
                f"{image_topic} recorded only {image_count} image(s): below "
                f"{CAMERA_INFO_RATE_MIN_MESSAGES} a single missing CameraInfo is "
                f"already outside the {camera_info_rate_tolerance:.0%} rate profile, "
                f"so this leg passing says the two counts match, not that the "
                f"calibration stream was observed to track a real take"
            )
        drift = _distinct_calibrations(payloads.get(info_topic, ()), info_topic, refusals)
        if len(drift) > 1:
            findings.append(
                f"{info_topic} published {len(drift)} DIFFERENT calibrations inside "
                f"the first {_CALIBRATION_PAYLOADS} message(s) of each split file "
                f"({_calibration_difference(drift[0], drift[1])}); every one of them "
                f"is bound into the calibration digest, and a take whose intrinsics "
                f"move mid-stream cannot be rectified with any single one of them"
            )
        calibration_views[info_topic] = drift or [info_view]

    # -- (b)/(c) sensor transforms -----------------------------------------
    bag_tf_static = counts.get("/tf_static", 0)
    transform_sources: dict[str, tuple[TransformView, ...]] = {}
    decoded_static: list[TransformView] = []
    for payload in payloads.get("/tf_static", ()):
        try:
            decoded_static.extend(decode_tf_message(payload))
        except CdrDecodeError as error:
            refusals.append(f"/tf_static payload did not decode: {error}")
    if decoded_static:
        transform_sources["bag:/tf_static"] = tuple(decoded_static)
    snapshot_digest: str | None = None
    if static_transform_snapshot is not None:
        transform_sources["snapshot"] = validate_static_transform_snapshot(
            static_transform_snapshot
        )
        snapshot_digest = static_transform_snapshot_digest(static_transform_snapshot)

    parents_by_child: dict[str, dict[str, tuple[TransformView, str]]] = {}
    for source, views in transform_sources.items():
        for view in views:
            slot = parents_by_child.setdefault(view.child_frame, {})
            existing = slot.get(view.parent_frame)
            if existing is None:
                slot[view.parent_frame] = (view, source)
            else:
                previous, previous_source = existing
                if _transforms_disagree(previous, view):
                    refusals.append(
                        f"two competing declarations of {view.parent_frame}->"
                        f"{view.child_frame} (from {previous_source} and {source}) "
                        f"disagree; an extrinsic with two values is ambiguous, and "
                        f"choosing one silently would poison every fusion result"
                    )
    for child, slots in sorted(parents_by_child.items()):
        if len(slots) > 1:
            refusals.append(
                f"frame {child!r} has {len(slots)} competing parents "
                f"({', '.join(sorted(slots))}); the transform tree is ambiguous "
                f"and no consumer may resolve the tie silently"
            )

    if active_channels:
        if bag_tf_static <= 0 and static_transform_snapshot is None:
            refusals.append(
                "transient-local /tf_static was neither captured in the bag "
                f"({bag_tf_static} message(s)) nor bound as a static-transform "
                "snapshot taken before record start; the bag's frames are labels "
                "with no geometry"
            )
        else:
            for image_topic in sorted(optical_topics):
                frame = _stream_frame(streams.get(image_topic, {}))
                if frame is None:
                    continue  # already refused above for this stream
                if frame not in parents_by_child:
                    refusals.append(
                        f"sensor transform absent: optical frame {frame!r} "
                        f"({image_topic}) has no parent in /tf_static or the "
                        f"snapshot; the stream cannot be placed on the rig"
                    )
    elif bag_tf_static <= 0 and static_transform_snapshot is None:
        findings.append(
            "no /tf_static in the bag and no snapshot bound; nothing relates this "
            "bag's frames to one another (finding, not a refusal: no optical "
            "stream is active to certify)"
        )

    # -- calibration digest -------------------------------------------------
    calibration_sha256 = (
        calibration_digest_of(calibration_views) if calibration_views else None
    )

    # -- (d) sync binding ---------------------------------------------------
    if sync_fit is None:
        sync_block: dict[str, Any] = {
            "status": "absent",
            "certifiable": False,
            "note": (
                "no sync fit is bound to this bag; cross-device time is not "
                "recoverable from it alone (PS-I)"
            ),
        }
        if claims_recoverable_time:
            refusals.append(
                "the run claims recoverable cross-device time but no sync fit is "
                "bound to the sidecar; a claim without the digest-bound evidence "
                "must not certify"
            )
    else:
        sync_block = {"status": "present", **sidecar_sync_block(sync_fit)}
        if claims_recoverable_time and not sync_fit.is_certifiable:
            refusals.append(
                "the run claims recoverable cross-device time but the bound sync "
                f"fit is not certifiable: {'; '.join(sync_fit.shortfalls)}"
            )

    transforms_block = {
        "bag_tf_static_messages": bag_tf_static,
        "bag_tf_messages": counts.get("/tf", 0),
        "sources": {
            source: [view.to_dict() for view in views]
            for source, views in sorted(transform_sources.items())
        },
        "snapshot_bound": static_transform_snapshot is not None,
    }

    return GoRecordAssessment(
        certified=not refusals,
        refusals=tuple(refusals),
        findings=tuple(findings),
        streams=streams,
        transforms=transforms_block,
        calibration_sha256=calibration_sha256,
        snapshot_sha256=snapshot_digest,
        sync=sync_block,
    )


def _decode_first(payloads: Sequence[bytes], decoder, topic: str, refusals: list[str]):
    """First decodable payload, or a refusal recorded. Unreadable ≠ passed."""

    if not payloads:
        refusals.append(
            f"{topic} recorded messages but not one payload could be read back out "
            f"of the bag's bytes (compressed chunks or damage); a profile that "
            f"cannot be read cannot be certified"
        )
        return None
    try:
        return decoder(payloads[0])
    except CdrDecodeError as error:
        refusals.append(f"{topic} payload did not decode: {error}")
        return None


def _stream_frame(record: Mapping[str, Any]) -> str | None:
    info = record.get("camera_info_profile")
    if isinstance(info, Mapping) and info.get("frame_id"):
        return str(info["frame_id"])
    image = record.get("image_profile")
    if isinstance(image, Mapping) and image.get("frame_id"):
        return str(image["frame_id"])
    return None


def _transforms_disagree(first: TransformView, second: TransformView) -> bool:
    deltas = [
        abs(a - b) for a, b in zip(first.translation_m, second.translation_m)
    ] + [abs(a - b) for a, b in zip(first.rotation_xyzw, second.rotation_xyzw)]
    return max(deltas) > _TRANSFORM_EPSILON


def verify_calibration_digest(
    sidecar: Mapping[str, Any], bag_dir: Path | str
) -> tuple[bool, tuple[str, ...]]:
    """Re-derive the calibration digest from the bag and compare.

    Re-derivation walks the SAME window :func:`assess_go_record` bound — up to
    ``_CALIBRATION_PAYLOADS`` CameraInfo per split file, deduplicated to the
    distinct decoded calibrations — so any CameraInfo in that window whose
    decoded content changed re-derives to a different digest and the mismatch
    names itself. What it does not re-derive is stated on
    :func:`calibration_digest_of`: raw bytes that decode identically, and a
    calibration that first changes past the window. A sidecar with no recorded
    digest fails: absence of the binding is not a passing state of the binding.
    """

    failures: list[str] = []
    block = sidecar.get(SIDECAR_EXTRA_KEY)
    go_block = block.get("go_record") if isinstance(block, Mapping) else None
    if not isinstance(go_block, Mapping):
        return False, ("sidecar carries no capture.go_record block to verify",)
    recorded = go_block.get("calibration_sha256")
    if not isinstance(recorded, str) or not _HEX64.match(recorded):
        return False, (
            (
                f"sidecar records no calibration digest (got {recorded!r}); an "
                f"absent binding cannot verify"
            ),
        )
    streams = go_block.get("streams")
    info_topics = sorted(
        str(value.get("camera_info_topic"))
        for value in (streams or {}).values()
        if isinstance(value, Mapping) and value.get("camera_info_topic")
    )
    if not info_topics:
        return False, ("sidecar go_record names no camera_info topics to re-derive from",)
    files = discover_bag(bag_dir).files
    payloads: dict[str, list[bytes]] = {topic: [] for topic in info_topics}
    for path in files:
        extracted, _findings = collect_topic_payloads(
            path, info_topics, max_per_topic=_CALIBRATION_PAYLOADS
        )
        for topic, blobs in extracted.items():
            for blob in blobs:
                if len(payloads[topic]) < _CALIBRATION_PAYLOADS:
                    payloads[topic].append(blob)
    views: dict[str, list[CameraInfoView]] = {}
    for topic in info_topics:
        decoded = _distinct_calibrations(payloads[topic], topic, failures)
        if decoded:
            views[topic] = decoded
    if failures:
        return False, tuple(failures)
    if set(views) != set(info_topics):
        missing = sorted(set(info_topics) - set(views))
        return False, (
            (
                f"camera_info payload(s) for {missing} are no longer extractable "
                f"from the bag"
            ),
        )
    computed = calibration_digest_of(views)
    if computed != recorded:
        return False, (
            (
                f"calibration digest mismatch: sidecar records {recorded}, the "
                f"bag's decoded calibration set hashes to {computed}"
            ),
        )
    return True, ()


def verify_sync_fit_binding(
    sidecar: Mapping[str, Any], fit: SyncFitV1
) -> tuple[bool, tuple[str, ...]]:
    """Is this fit provably the one the sidecar bound? Digest decides."""

    block = sidecar.get(SIDECAR_EXTRA_KEY)
    sync_block = block.get("sync") if isinstance(block, Mapping) else None
    if not isinstance(sync_block, Mapping) or sync_block.get("status") != "present":
        return False, (
            (
                "sidecar binds no sync fit; a fit supplied after the fact is not "
                "the session's fit until a digest says so"
            ),
        )
    recorded = sync_block.get("sync_fit_sha256")
    computed = sync_fit_digest(fit)
    if recorded != computed:
        return False, (
            (
                f"sync fit digest mismatch: sidecar records {recorded}, the "
                f"supplied fit hashes to {computed}"
            ),
        )
    return True, ()


def build_rosbag2_sidecar(
    *,
    bag_id: str,
    bag_dir: Path | str,
    bag_info: Rosbag2Info | None = None,
    created_at_utc: str | None = None,
    configured_rates: Mapping[str, float] | None = None,
    attestation_digest: str | None = None,
    clock_map_digest: str | None = None,
    mount_geometry: Mapping[str, Mapping[str, Any]] | None = None,
    session_notes: Sequence[str] = (),
    extra_does_not_prove: Sequence[str] = (),
    rate_tolerance: float = RATE_TOLERANCE,
    origin: EvidenceOrigin = EvidenceOrigin.PHYSICAL,
    static_transform_snapshot: Mapping[str, Any] | None = None,
    sync_fit: SyncFitV1 | None = None,
    claims_recoverable_time: bool = False,
) -> dict[str, Any]:
    """Build a ``parcel.bag.v1`` sidecar for a rosbag2 MCAP recording.

    This is the adapter the tranche exists for. It reads a rosbag2 directory —
    ``metadata.yaml`` plus one MCAP file per split — digests **every** file,
    classifies the framing, maps each ROS topic back to its PS-A/PS-H channel,
    and takes per-channel counts from ``ros2 bag info`` when the caller supplies
    it, falling back to the stdlib walk when it does not. Which basis was used is
    recorded per file and in the channel records; it is never left implicit.

    ``origin`` is a caller declaration here and not derived, because rosbag2
    envelopes carry no ``EvidenceOrigin`` — that is a Parcel concept. The default
    is ``PHYSICAL`` because ``ros2 bag record`` cannot run without a live graph,
    and a rehearsal must pass ``SIMULATED`` explicitly. The manifest's ``source``
    follows the declaration, and ``capture.origin.basis`` says it was declared
    rather than observed, so nobody can mistake it for evidence.
    """

    if not bag_id.strip():
        raise SidecarRefusedError("bag_id must be non-empty")
    if not isinstance(origin, EvidenceOrigin) or origin is EvidenceOrigin.UNKNOWN:
        raise SidecarRefusedError(
            f"origin must be a declared EvidenceOrigin, got {origin!r} — a recording that "
            f"declares nothing must never pass for a physical measurement"
        )
    if (
        sync_fit is not None
        and origin is EvidenceOrigin.PHYSICAL
        and sync_fit.origin is not EvidenceOrigin.PHYSICAL
    ):
        raise SidecarRefusedError(
            f"a bag declared PHYSICAL cannot bind a sync fit of origin "
            f"{sync_fit.origin.value!r}; a rehearsal fit stamped into a session "
            f"sidecar would certify recoverable time the session never measured"
        )
    directory: Rosbag2Directory = discover_bag(bag_dir)
    scans = [read_rosbag2_mcap(path) for path in directory.files]
    files: list[Rosbag2FileRecord] = []
    walked_counts: dict[str, int] = {}
    payload_bytes: dict[str, int] = {}
    bases: set[str] = set()
    first_ns: int | None = None
    last_ns: int | None = None
    topics_seen: dict[str, str] = {}

    for scan in scans:
        digest, size = sha256_file(scan.path)
        files.append(
            Rosbag2FileRecord(
                filename=scan.path.name,
                sha256=digest,
                bytes=size,
                termination=scan.termination.value,
                detail=scan.detail,
                count_basis=scan.count_basis.value,
                profile=scan.profile,
                library=scan.library,
                messages=scan.message_count,
                findings=scan.findings,
            )
        )
        bases.add(scan.count_basis.value)
        for topic, count in scan.counts.items():
            walked_counts[topic] = walked_counts.get(topic, 0) + count
        for topic, size_bytes in scan.message_bytes.items():
            payload_bytes[topic] = payload_bytes.get(topic, 0) + size_bytes
        for item in scan.channels:
            topics_seen[item.topic] = item.schema_name
        if scan.first_log_time_ns is not None:
            first_ns = scan.first_log_time_ns if first_ns is None else min(first_ns, scan.first_log_time_ns)
        if scan.last_log_time_ns is not None:
            last_ns = scan.last_log_time_ns if last_ns is None else max(last_ns, scan.last_log_time_ns)

    if not any(scan.is_rosbag2 for scan in scans):
        raise SidecarRefusedError(
            f"no file in {directory.path} carries the {ROS2_PROFILE_NAME!r} MCAP profile; "
            f"this is not a rosbag2 recording and describing it as one would be a lie in "
            f"the one document that outlives the session"
        )

    findings: list[str] = list(directory.findings)
    counts = dict(walked_counts)
    basis = CountBasis.WALKED.value if bases == {CountBasis.WALKED.value} else "mixed:" + ",".join(
        sorted(bases)
    )
    if bag_info is not None:
        basis = "ros2_bag_info"
        for topic, count in bag_info.counts.items():
            if topic in walked_counts and walked_counts[topic] != count:
                findings.append(
                    f"`ros2 bag info` reports {count} message(s) on {topic} and the stdlib "
                    f"walk found {walked_counts[topic]}; the sidecar quotes ros2 bag info "
                    f"and records the disagreement rather than choosing quietly"
                )
        counts = dict(bag_info.counts)
        for topic, walked in walked_counts.items():
            counts.setdefault(topic, walked)

    span_s = 0.0 if first_ns is None or last_ns is None else max(0.0, (last_ns - first_ns) / 1e9)
    if bag_info is not None and bag_info.duration_s:
        span_s = float(bag_info.duration_s)

    rates = _validated_rates(configured_rates)
    observations: dict[str, ChannelObservation] = {}
    unmapped: dict[str, int] = {}
    support_counts: dict[str, dict[str, Any]] = {}
    for topic, count in sorted(counts.items()):
        support_id = SUPPORT_BY_TOPIC.get(topic)
        if support_id is not None:
            # A support topic is not a payload channel: it gets no sequence
            # space, no rate verdict, and never lands in "unmapped" — the
            # GO-RECORD block below is where its adequacy is judged.
            support_counts[topic] = {"support_id": support_id, "messages": count}
            continue
        channel_id = CHANNEL_BY_TOPIC.get(topic)
        if channel_id is None:
            unmapped[topic] = count
            continue
        entry = channel(channel_id)
        observations[channel_id] = _observe_rosbag2_channel(
            entry,
            messages=count,
            payload_bytes=payload_bytes.get(topic, 0),
            span_s=span_s,
            configured_rate=rates.get(channel_id),
            tolerance=rate_tolerance,
            basis=basis,
        )
    if not observations:
        raise SidecarRefusedError(
            f"{directory.path} carries no topic that maps to a channel of the matrix "
            f"(saw {sorted(counts)}); a bag with no known channel is a finding, not a "
            f"manifest"
        )

    termination = _rosbag2_termination(scans)
    termination = Termination(
        termination.kind,
        termination.detail,
        termination.evidence,
        (*termination.findings, *findings),
    )
    mount_block = _mount_geometry_block(mount_geometry)
    entries = tuple(observation_entry(key) for key in sorted(observations))

    go_record = assess_go_record(
        directory.path,
        counts=counts,
        files=directory.files,
        static_transform_snapshot=static_transform_snapshot,
        sync_fit=sync_fit,
        claims_recoverable_time=claims_recoverable_time,
    )

    capture: dict[str, Any] = {
        "schema": SIDECAR_SCHEMA,
        "envelope_schema": ENVELOPE_SCHEMA,
        "bag_format": BagFormat.ROSBAG2_MCAP.value,
        "role": RecorderRole.PRIMARY.value,
        "rosbag2": {
            "directory": str(directory.path),
            "metadata_yaml": None if directory.metadata_path is None else directory.metadata_path.name,
            "files": [item.to_dict() for item in files],
            "file_count": len(files),
            "total_bytes": sum(item.bytes for item in files),
            "count_basis": basis,
            "bag_info": None if bag_info is None else bag_info.to_dict(),
            "topics_recorded": sorted(topics_seen),
            "topic_schemas": dict(sorted(topics_seen.items())),
            "unmapped_topics": dict(sorted(unmapped.items())),
            "support_topics": dict(sorted(support_counts.items())),
            "storage_id": "mcap",
        },
        "go_record": go_record.to_dict(),
        "sync": dict(go_record.sync),
        "origin": {
            "observed": [origin.value],
            "basis": "declared_by_caller",
            "note": (
                "rosbag2 carries no EvidenceOrigin field; this value was declared by the "
                "caller, not read out of the bag. The PS-D attestation is what binds this "
                "recording to a unit."
            ),
        },
        "termination": termination.to_dict(),
        "recorder_account": {
            "declared_drops": None,
            "observed_sequence_holes": {},
            "status": "unavailable",
            "findings": [
                (
                    "rosbag2 mints no per-channel sequence number, so there is no number "
                    "line to find holes in; /events/messages_lost is the recorder's own "
                    "account and is recorded as a topic when the build publishes it"
                )
            ],
        },
        "session": {
            "messages": sum(counts.values()),
            "first_log_time_ns": first_ns,
            "last_log_time_ns": last_ns,
            "recorded_span_s": _round(span_s),
            "first_host_monotonic_ns": None,
            "last_host_monotonic_ns": None,
            "note": (
                "log_time is the recorder's clock at receipt. It is not a device clock and "
                "is comparable across devices only through the PS-I sync ritual."
            ),
        },
        "channels": {key: value.to_dict() for key, value in sorted(observations.items())},
        "channel_summary": _channel_summary(observations),
        "clock_map": _digest_block(
            clock_map_digest,
            name="PS-C ClockMapV1",
            absent_note=(
                "no clock map is bound to this bag; cross-device timestamps in it are not "
                "recoverable, because log_time is the recorder host's clock alone"
            ),
        ),
        "attestation": _digest_block(
            attestation_digest,
            name="PS-D HardwareAttestationV1",
            absent_note=(
                "no hardware attestation is bound to this bag; the edition, firmware, "
                "serials and per-channel presence of the unit that produced it are unverified"
            ),
        ),
        "mount_geometry": mount_block,
        "session_notes": [str(note) for note in session_notes],
    }

    does_not_prove = _does_not_prove(
        termination=termination,
        observations=observations,
        capture=capture,
        extra=[*ROSBAG2_DOES_NOT_PROVE, *extra_does_not_prove],
    )
    if not go_record.certified:
        does_not_prove.append(
            f"GO-RECORD REFUSED ({len(go_record.refusals)} reason(s)): "
            + " | ".join(go_record.refusals)
        )
    for artifact in SUPPORT_ARTIFACTS:
        if artifact.need is not SupportNeed.UNAVAILABLE_DOCUMENTED:
            continue
        affected = sorted(set(artifact.supports_channel_ids) & set(observations))
        if affected:
            does_not_prove.append(
                f"{artifact.human_name}: no publisher for this support artifact "
                f"exists, so stream(s) {', '.join(affected)} are recorded as "
                f"imagery only, never as a calibrated sensor."
            )
    if unmapped:
        does_not_prove.append(
            f"{len(unmapped)} recorded topic(s) map to no channel of the matrix "
            f"({', '.join(sorted(unmapped))}); they are counted in capture.rosbag2."
            f"unmapped_topics and are not described as channels."
        )
    if basis != "ros2_bag_info":
        does_not_prove.append(
            "Per-channel counts were taken from a standard-library walk of the MCAP "
            "records, not from `ros2 bag info`. The recorder's own tool was not consulted."
        )

    return make_manifest(
        bag_id=bag_id,
        created_at_utc=created_at_utc or _now_utc(),
        source="hardware" if origin is EvidenceOrigin.PHYSICAL else "sim",
        clocks=_rosbag2_clocks(first_ns),
        frames=_frames_block(entries, mount_block),
        topics=[entry.bag_topic for entry in entries],
        does_not_prove=does_not_prove,
        message_count=sum(counts.values()),
        extra={
            SIDECAR_EXTRA_KEY: capture,
            "hardware_claims": origin is EvidenceOrigin.PHYSICAL,
        },
    )


#: The MCAP profile rosbag2 stamps. Imported by name so the refusal message and
#: the reader cannot drift apart.
ROS2_PROFILE_NAME = "ros2"


def observation_entry(channel_id: str) -> Channel:
    return channel(channel_id)


def _rosbag2_clocks(first_ns: int | None) -> dict[str, Any]:
    """``source_clock="ros"`` — the value ``bags/schema.py:130`` already accepts.

    Not ``"sensor"``: the timestamps in a rosbag2 bag are ROS receive times on
    the recorder host, and calling them sensor time is the single easiest way to
    make every later alignment quietly wrong.
    """

    clocks = default_clocks(source_clock="ros")
    clocks["recording_monotonic_origin_ns"] = int(first_ns or 0)
    clocks["note"] = (
        f"{clocks['note']} recording_monotonic_origin_ns is the first MCAP log_time in the "
        f"recording — the RECORDER's clock at receipt, not any device's. Cross-device "
        f"alignment requires the PS-I sync ritual."
    )
    return clocks


def verify_rosbag2_sidecar(
    sidecar: Mapping[str, Any], bag_dir: Path | str
) -> Rosbag2Verification:
    """Re-bind a rosbag2 sidecar to its files. Any doubt is a failure.

    Every file the sidecar names is re-digested. A file that has moved, changed
    by one byte, or gained a sibling the sidecar does not name is a failure — a
    split recording where only some files are checked is not verified.
    """

    failures: list[str] = []
    block = sidecar.get(SIDECAR_EXTRA_KEY)
    if not isinstance(block, Mapping):
        return Rosbag2Verification(False, (f"manifest carries no {SIDECAR_EXTRA_KEY!r} block",), 0)
    if block.get("bag_format") != BagFormat.ROSBAG2_MCAP.value:
        return Rosbag2Verification(
            False,
            (
                (
                    f"capture.bag_format is {block.get('bag_format')!r}, not "
                    f"{BagFormat.ROSBAG2_MCAP.value!r}; use verify_sidecar() for a "
                    f"parcel-capture bag"
                ),
            ),
            0,
        )
    if sidecar.get("schema_version") != SCHEMA_VERSION:
        failures.append(
            f"manifest schema_version is {sidecar.get('schema_version')!r}, expected "
            f"{SCHEMA_VERSION!r}"
        )
    rosbag2_block = block.get("rosbag2")
    if not isinstance(rosbag2_block, Mapping):
        return Rosbag2Verification(False, (*failures, "no capture.rosbag2 record"), 0)
    recorded = rosbag2_block.get("files")
    if not isinstance(recorded, list) or not recorded:
        return Rosbag2Verification(
            False, (*failures, "capture.rosbag2.files is empty"), 0
        )

    root = Path(bag_dir)
    checked = 0
    for item in recorded:
        if not isinstance(item, Mapping):
            failures.append(f"file record is not a mapping: {item!r}")
            continue
        name = str(item.get("filename", ""))
        target = root / name
        try:
            digest, size = sha256_file(target)
        except OSError as error:
            failures.append(f"cannot read {target}: {error}")
            continue
        checked += 1
        if digest != item.get("sha256"):
            failures.append(
                f"digest mismatch on {name}: sidecar records {item.get('sha256')}, the file "
                f"hashes to {digest}"
            )
        if size != item.get("bytes"):
            failures.append(
                f"size mismatch on {name}: sidecar records {item.get('bytes')} bytes, the "
                f"file is {size}"
            )
    named = {str(item.get("filename", "")) for item in recorded if isinstance(item, Mapping)}
    on_disk = {path.name for path in root.glob("*.mcap")} if root.is_dir() else set()
    extra = sorted(on_disk - named)
    if extra:
        failures.append(
            f"{root} holds MCAP file(s) the sidecar does not name: {extra}; a split "
            f"recording is not verified while part of it is undescribed"
        )
    return Rosbag2Verification(not failures, tuple(failures), checked)


def verify_rosbag2_sidecar_or_raise(
    sidecar: Mapping[str, Any], bag_dir: Path | str
) -> Rosbag2Verification:
    result = verify_rosbag2_sidecar(sidecar, bag_dir)
    if not result.ok:
        raise SidecarRefusedError(
            f"sidecar does not bind {bag_dir}: {'; '.join(result.failures)}"
        )
    return result


def rosbag2_sidecar_path_for(bag_dir: Path | str) -> Path:
    """Beside the bag directory, not inside it: a file inside would change the
    directory a later ``ros2 bag`` command reads, and a sidecar must never be
    able to affect the thing it describes."""

    root = Path(bag_dir)
    return root.with_name(root.name + SIDECAR_SUFFIX)


def finalize_rosbag2(
    bag_dir: Path | str,
    *,
    bag_id: str,
    sidecar_path: Path | str | None = None,
    require_go_record: bool = False,
    **kwargs: Any,
) -> tuple[dict[str, Any], Path]:
    """Build, validate and durably write a sidecar for the primary recording.

    The one call an operator makes after a take — including after a take that
    ended in a flat battery, which is the case this whole module exists for.
    A recovery sidecar is always written and records the GO-RECORD verdict
    honestly, refusals included. ``require_go_record=True`` is the session
    path: when the gate refuses, NOTHING is written and the refusal reasons
    are raised — a certified manifest for an uncertifiable bag must not exist
    on disk even transiently.
    """

    try:
        sidecar = build_rosbag2_sidecar(bag_id=bag_id, bag_dir=bag_dir, **kwargs)
    except BagSchemaError as error:
        raise SidecarRefusedError(f"manifest rejected by bags/schema.py: {error}") from error
    if require_go_record:
        go_block = sidecar[SIDECAR_EXTRA_KEY]["go_record"]
        if not go_block["certified"]:
            raise GoRecordRefusedError(
                f"bag {bag_dir} cannot finalize GO-RECORD "
                f"({len(go_block['refusals'])} refusal(s)): "
                + " | ".join(go_block["refusals"])
            )
    target = Path(sidecar_path) if sidecar_path is not None else rosbag2_sidecar_path_for(bag_dir)
    return sidecar, write_sidecar(sidecar, target)
