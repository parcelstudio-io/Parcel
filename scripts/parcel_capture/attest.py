#!/usr/bin/env python
"""``HardwareAttestationV1`` — what the rig was, proven, on the day.

Card PS-D of tranche PS-1 (``scrum/20260813/task_1/README.md``).
:mod:`scripts.parcel_capture.preflight` does the looking; this module rules on
what was seen, binds it to a digest, and decides whether the session may
proceed. The one sentence the whole tranche serves — *when the dog powers down,
we hold a dataset that is still trustworthy six months from now* — is only true
if a reader six months from now can tell what hardware produced the bag and what
was never proven at all. This file is that record.

The firmware pin is a SECURITY control
--------------------------------------
``scrum/20260805/task_1/adr/0002-firmware-pin.md:11-13`` treats pre-1.1.13 Go2
firmware as **RCE-capable on the robot LAN** (CVE-2026-27509 / CVE-2026-27510
class), and Unitree DDS on that LAN is unauthenticated by design. Session day
attaches a computer to it. So :data:`FIRMWARE_PIN` is not a compatibility check
that a session can shrug off — a version below it is a refusal to connect, and
the refusal cites the CVE class so nobody has to go looking for why.

Fail closed means the *unread* case refuses too. A firmware version nobody read
off the unit does not prove the pin holds, so it lands in the same place as a
version that is provably too low: :attr:`SessionVerdict.REFUSE_CONNECT`. On a
dev box with no robot attached that is the correct answer, and it is the answer
this module gives.

Derived answers are never read back from the file
-------------------------------------------------
Following ``commissioning/record.py``: :meth:`HardwareAttestationV1.as_dict`
writes ``status``, ``origin`` and ``verdict`` for a human reader, and
:meth:`HardwareAttestationV1.from_mapping` **throws them away** and recomputes
them from the raw counts. Hand-editing ``"origin": "physical"`` into an
attestation file changes nothing, and :func:`verify_mapping` reports the forgery
rather than absorbing it.

That is the mechanism behind the card's hardest requirement: *refuse to emit an
attestation claiming PHYSICAL origin for any channel it did not receive a
message from.* :attr:`ChannelAttestation.origin` is a property whose only route
to :attr:`EvidenceOrigin.PHYSICAL` is ``messages_received >= 1``. There is no
argument, no flag and no config that reaches it another way.

Physical plausibility rides beside origin, never instead of it
--------------------------------------------------------------
Card PS-J (corrective tranche PS-2) adds
:attr:`ChannelAttestation.plausibility_verdict` — a third derived answer under
the same discipline: written for a human, discarded on read, recomputed from the
channel's own recorded checks, and reported by :func:`verify_mapping` when the
file disagrees with itself.

It is deliberately **orthogonal** to status and origin. A channel that emits
-2.17e24 m/s^2 is still PRESENT and still PHYSICAL, because a message really did
arrive from real hardware — what changes is that the attestation now says, in
the header and in the digest, that what arrived is not possible. PS-J's card is
explicit that a failed plausibility check must never silence a recording, so
nothing in this layer can reach :attr:`SessionVerdict.DEGRADE_MMP`: its findings
are capped at MAJOR, which is the "never hidden, decided at the go/no-go" lane.
This layer only ever makes the attestation stricter — it adds a verdict and
findings, and relaxes nothing.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import math
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised only on a checkout without an install
    from parcel_robot.capture.channels import (
        CHANNELS,
        CHANNELS_BY_ID,
        Channel,
        ChannelPresence,
        Criticality,
    )
    from parcel_robot.evidence_origin import EvidenceOrigin
except ImportError:  # pragma: no cover - Orin runs this straight from a checkout
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from parcel_robot.capture.channels import (
        CHANNELS,
        CHANNELS_BY_ID,
        Channel,
        ChannelPresence,
        Criticality,
    )
    from parcel_robot.evidence_origin import EvidenceOrigin

try:  # pragma: no cover - direct `python scripts/parcel_capture/attest.py` path
    from scripts.parcel_capture.preflight import (
        AbsenceReason,
        ChannelPlausibility,
        ChannelProbe,
        EvidenceKind,
        Finding,
        FindingSeverity,
        Observation,
        PlausibilityVerdict,
        PreflightError,
        PreflightReport,
        ProbeStatus,
        RateAssessment,
        build_arg_parser,
        format_plausibility_block,
        format_report,
        operator_observation_from_args,
        parse_rate_overrides,
        rest_period_from_args,
        run_preflight,
    )
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.parcel_capture.preflight import (
        AbsenceReason,
        ChannelPlausibility,
        ChannelProbe,
        EvidenceKind,
        Finding,
        FindingSeverity,
        Observation,
        PlausibilityVerdict,
        PreflightError,
        PreflightReport,
        ProbeStatus,
        RateAssessment,
        build_arg_parser,
        format_plausibility_block,
        format_report,
        operator_observation_from_args,
        parse_rate_overrides,
        rest_period_from_args,
        run_preflight,
    )

#: Wire identifier. PS-B carries the digest of a document with this schema in the
#: ``parcel.bag.v1`` sidecar's ``extra``; a reader that does not know this string
#: must refuse the record rather than guess at its shape.
ATTESTATION_SCHEMA = "parcel.hardware.attestation.v1"

#: ADR 0002's hard pin. Supported EDU firmware is >= V1.1.13.
FIRMWARE_PIN: tuple[int, int, int] = (1, 1, 13)

FIRMWARE_PIN_ADR = "scrum/20260805/task_1/adr/0002-firmware-pin.md:11-13"

#: The CVE class ADR 0002 cites. Quoted in every refusal, because a refusal an
#: operator cannot evaluate is a refusal they will override.
FIRMWARE_CVE_CLASS = ("CVE-2026-27509", "CVE-2026-27510")

#: Every observation an attestation must carry — present or explicitly absent.
#: Completeness is enforced, so a rig cannot avoid the firmware gate by omitting
#: the firmware field, and a reader six months from now can tell the difference
#: between "we did not measure it" and "the field was not in this version".
REQUIRED_OBSERVATIONS: tuple[str, ...] = (
    "host.label",
    "host.python",
    "robot.edition",
    "robot.firmware_version",
    "robot.serial",
    "robot.builtin_lidar_model",
    "robot.builtin_lidar_serial",
    "robot.builtin_lidar_document_verdict",
    "robot.nic",
    "robot.dds_domain",
    "robot.cyclonedds_uri",
    "d455.firmware_version",
    "d455.serial",
    "l2.firmware_version",
    "l2.serial",
    "orin.l4t_release",
    "orin.jetpack_version",
    "orin.board_model",
    "storage.path",
    "storage.free_bytes",
    "storage.total_bytes",
)


class AttestationRefused(RuntimeError):
    """The attestation cannot be built or cannot authorise what was asked."""


class FirmwarePinRefusal(AttestationRefused):
    """Firmware is below the ADR-0002 pin, or was never read. Do not connect."""


class FirmwarePinState(str, Enum):
    """How the firmware version stands against :data:`FIRMWARE_PIN`.

    Only :attr:`MET` is permissive, and it is reachable only from a version
    string that was machine-read off the unit and parsed successfully.
    """

    #: Read off the unit and at or above the pin.
    MET = "met"
    #: Read off the unit and below the pin. A security finding.
    BELOW_PIN = "below_pin"
    #: Nothing was read. Unknown is absent, and absent does not clear a pin.
    UNVERIFIED = "unverified"
    #: Something was read and we refuse to interpret it as a version.
    UNPARSEABLE = "unparseable"

    @property
    def clears_pin(self) -> bool:
        return self is FirmwarePinState.MET


class SessionVerdict(str, Enum):
    """What the session may do. Ordered worst-first by :attr:`rank`.

    These are exactly PS-F's branches (``session/README.md`` §go/no-go), so the
    tool and the run sheet cannot drift apart.
    """

    #: Do not attach a computer to the robot LAN at all. Firmware pin failure.
    REFUSE_CONNECT = "refuse_connect"
    #: Mount, measure, photograph, record nothing. A legitimate outcome that
    #: costs a later session nothing, because it captures what a later session
    #: could not recover.
    DEGRADE_MMP = "degrade_mmp"
    #: Record the full dataset.
    GO_RECORD = "go_record"

    @property
    def rank(self) -> int:
        return _VERDICT_RANK[self]

    @property
    def exit_code(self) -> int:
        return _VERDICT_EXIT[self]


_VERDICT_RANK = {
    SessionVerdict.REFUSE_CONNECT: 0,
    SessionVerdict.DEGRADE_MMP: 1,
    SessionVerdict.GO_RECORD: 2,
}

_VERDICT_EXIT = {
    SessionVerdict.REFUSE_CONNECT: 2,
    SessionVerdict.DEGRADE_MMP: 1,
    SessionVerdict.GO_RECORD: 0,
}


def parse_firmware_version(text: object) -> tuple[int, ...] | None:
    """``"v1.1.13"`` -> ``(1, 1, 13)``, or ``None`` when we refuse to guess.

    Deliberately narrow. A leading ``v``/``V`` and surrounding whitespace are
    tolerated because Unitree prints both forms; anything else — a build suffix,
    a date, a git hash, an empty string — returns ``None`` and lands in
    :attr:`FirmwarePinState.UNPARSEABLE`. A permissive version parser on a
    security gate is a permissive default.
    """

    if not isinstance(text, str):
        return None
    cleaned = text.strip().lstrip("vV").strip()
    if not cleaned:
        return None
    parts = cleaned.split(".")
    if not 2 <= len(parts) <= 4:
        return None
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    return tuple(numbers)


def evaluate_firmware_pin(observation: Observation | None) -> tuple[FirmwarePinState, str]:
    """Rule on the firmware observation. Returns the state and the reason.

    The observation must be a MACHINE_READ: an operator typing a version they
    remember is not a firmware read, and this gate is the one place in the stack
    where that distinction is worth a whole session.
    """

    if observation is None or not observation.is_known:
        detail = (
            "no firmware version was read off the unit"
            if observation is None
            else f"firmware version is ABSENT ({observation.evidence})"
        )
        return FirmwarePinState.UNVERIFIED, detail
    if observation.kind is not EvidenceKind.MACHINE_READ:
        return FirmwarePinState.UNVERIFIED, (
            f"firmware version {observation.value!r} is {observation.kind.value}, not a "
            f"machine read off the unit; the ADR-0002 gate accepts nothing else"
        )
    parsed = parse_firmware_version(observation.value)
    if parsed is None:
        return FirmwarePinState.UNPARSEABLE, (
            f"firmware version {observation.value!r} is not a dotted numeric version; "
            f"preflight refuses to interpret it"
        )
    padded = tuple(parsed) + (0,) * max(0, len(FIRMWARE_PIN) - len(parsed))
    if padded[: len(FIRMWARE_PIN)] < FIRMWARE_PIN:
        return FirmwarePinState.BELOW_PIN, (
            f"firmware {observation.value!r} parses to {parsed} which is BELOW the pin "
            f"{'.'.join(str(n) for n in FIRMWARE_PIN)}"
        )
    return FirmwarePinState.MET, (
        f"firmware {observation.value!r} parses to {parsed}, at or above the pin "
        f"{'.'.join(str(n) for n in FIRMWARE_PIN)}"
    )


def firmware_refusal_message(state: FirmwarePinState, detail: str) -> str:
    """The refusal an operator reads. Cites the CVE class, every time."""

    return (
        f"FIRMWARE PIN NOT CLEARED ({state.value}): {detail}. "
        f"ADR 0002 ({FIRMWARE_PIN_ADR}) pins supported Go2 EDU firmware at "
        f">= {'.'.join(str(n) for n in FIRMWARE_PIN)} and treats pre-pin firmware as "
        f"RCE-CAPABLE on the robot LAN ({' / '.join(FIRMWARE_CVE_CLASS)} class). "
        f"Unitree DDS on that LAN is unauthenticated by design and today's session "
        f"attaches a computer to it. DO NOT ATTACH the Orin or any host to the robot "
        f"LAN. Session branch: DEGRADE-MMP (mount, measure, photograph, record nothing) "
        f"— see scrum/20260813/task_1/session/STAGE0_RUN_SHEET.md §6."
    )


@dataclass(frozen=True, slots=True)
class ChannelAttestation:
    """What one channel proved, and what provenance that earns it.

    :attr:`status` and :attr:`origin` are properties. The constructor has no
    argument that names ``PRESENT`` or ``PHYSICAL``, so an attestation cannot
    claim a physical measurement it did not receive.
    """

    channel_id: str
    criticality: str
    declared_presence: str
    messages_received: int
    window_s: float
    observed_rate_hz: float | None
    expected_rate_hz: float | None
    rate_assessment: str
    evidence: str
    absence: str | None = None
    absence_detail: str = ""
    receipts_discarded: int = 0
    #: PS-J's physical-plausibility ruling, carried into the record and into the
    #: digest. ``None`` means the layer did not run, which
    #: :attr:`plausibility_verdict` reports as UNKNOWN — never as PASS.
    plausibility: ChannelPlausibility | None = None

    def __post_init__(self) -> None:
        # The matrix is the authority on what a channel is and what its absence
        # costs. Copying those two fields into the record is a convenience for a
        # reader; disagreeing with the matrix is a forgery, so it is refused.
        entry = CHANNELS_BY_ID.get(self.channel_id)
        if entry is None:
            raise AttestationRefused(
                f"{self.channel_id!r} is not a channel in the PS-A matrix; an "
                f"attestation may not invent a stream"
            )
        if self.criticality != entry.criticality.value:
            raise AttestationRefused(
                f"{self.channel_id}: matrix says criticality "
                f"{entry.criticality.value!r}, record says {self.criticality!r}"
            )
        if self.declared_presence != entry.presence.value:
            raise AttestationRefused(
                f"{self.channel_id}: matrix says presence {entry.presence.value!r}, "
                f"record says {self.declared_presence!r}"
            )
        if isinstance(self.messages_received, bool) or not isinstance(
            self.messages_received, int
        ):
            raise AttestationRefused(
                f"{self.channel_id}: messages_received must be an int, got "
                f"{self.messages_received!r}"
            )
        if self.messages_received < 0:
            raise AttestationRefused(f"{self.channel_id}: messages_received must be >= 0")
        if self.messages_received == 0 and not self.absence:
            raise AttestationRefused(
                f"{self.channel_id}: a channel with no messages must name why it is absent"
            )
        if self.messages_received > 0 and self.absence:
            raise AttestationRefused(
                f"{self.channel_id}: {self.messages_received} message(s) received but "
                f"absence={self.absence!r}"
            )
        if not self.evidence.strip():
            raise AttestationRefused(f"{self.channel_id}: an attestation must state its evidence")
        if self.plausibility is not None:
            if not isinstance(self.plausibility, ChannelPlausibility):
                raise AttestationRefused(
                    f"{self.channel_id}: plausibility must be a ChannelPlausibility, got "
                    f"{type(self.plausibility).__name__}"
                )
            if self.plausibility.channel_id != self.channel_id:
                raise AttestationRefused(
                    f"{self.channel_id}: carries a plausibility ruling labelled "
                    f"{self.plausibility.channel_id!r} — a channel may not inherit another "
                    f"channel's verdict"
                )

    @classmethod
    def from_probe(cls, probe: ChannelProbe, entry: Channel) -> ChannelAttestation:
        if probe.channel_id != entry.channel_id:
            raise AttestationRefused(
                f"probe {probe.channel_id!r} does not match matrix entry {entry.channel_id!r}"
            )
        return cls(
            channel_id=probe.channel_id,
            criticality=entry.criticality.value,
            declared_presence=entry.presence.value,
            messages_received=probe.messages_received,
            window_s=probe.window_s,
            observed_rate_hz=probe.observed_rate_hz,
            expected_rate_hz=probe.expected_rate_hz,
            rate_assessment=probe.rate_assessment.value,
            evidence=probe.evidence,
            absence=None if probe.absence is None else probe.absence.value,
            absence_detail=probe.absence_detail,
            receipts_discarded=probe.receipts_discarded,
            plausibility=probe.plausibility,
        )

    @property
    def status(self) -> ProbeStatus:
        """Derived from the count and the assessment. Never stored.

        Independent of :attr:`plausibility_verdict` by design: PS-J requires that
        a channel be recorded regardless of its physical verdict, so an
        implausible channel stays PRESENT and stays PHYSICAL. The verdict travels
        beside the status, never in place of it.
        """

        if self.messages_received <= 0:
            return ProbeStatus.ABSENT
        if RateAssessment(self.rate_assessment).is_degraded:
            return ProbeStatus.DEGRADED
        return ProbeStatus.PRESENT

    @property
    def plausibility_verdict(self) -> PlausibilityVerdict:
        """Derived from the stored checks. No ruling at all is UNKNOWN."""

        if self.plausibility is None:
            return PlausibilityVerdict.UNKNOWN
        return self.plausibility.verdict

    @property
    def origin(self) -> EvidenceOrigin:
        """PHYSICAL only for a channel that actually delivered a message.

        ``EvidenceOrigin.UNKNOWN`` is the fail-closed value from card W0-A and it
        is what every silent channel gets. There is no second route to PHYSICAL.
        """

        if self.messages_received <= 0:
            return EvidenceOrigin.UNKNOWN
        return EvidenceOrigin.PHYSICAL

    @property
    def expected_absent(self) -> bool:
        """The matrix already said this one is not here (XVF3800, in the post)."""

        return self.declared_presence == ChannelPresence.AWAITING_HARDWARE.value

    def as_dict(self) -> dict[str, Any]:
        """Includes the derived fields, for a human. They are not read back."""

        return {
            "channel_id": self.channel_id,
            "criticality": self.criticality,
            "declared_presence": self.declared_presence,
            "status": self.status.value,
            "origin": self.origin.value,
            "messages_received": self.messages_received,
            "window_s": self.window_s,
            "observed_rate_hz": self.observed_rate_hz,
            "expected_rate_hz": self.expected_rate_hz,
            "rate_assessment": self.rate_assessment,
            "receipts_discarded": self.receipts_discarded,
            "absence": self.absence,
            "absence_detail": self.absence_detail,
            "evidence": self.evidence,
            "plausibility_verdict": self.plausibility_verdict.value,
            "plausibility": None if self.plausibility is None else self.plausibility.to_dict(),
        }

    @classmethod
    def from_mapping(cls, record: Mapping[str, Any]) -> ChannelAttestation:
        """Decode, DISCARDING ``status``/``origin``/``plausibility_verdict``.

        All three are recomputed from the raw counts and the raw checks, so
        hand-editing ``"plausibility_verdict": "pass"`` onto a channel whose own
        recorded checks say FAIL changes nothing, and :func:`verify_mapping`
        reports the forgery.
        """

        if not isinstance(record, Mapping):
            raise AttestationRefused(
                f"channel record must be a mapping, got {type(record).__name__}"
            )
        try:
            plausibility = record.get("plausibility")
            return cls(
                channel_id=str(record["channel_id"]),
                criticality=str(record["criticality"]),
                declared_presence=str(record["declared_presence"]),
                messages_received=record["messages_received"],
                window_s=float(record["window_s"]),
                observed_rate_hz=_opt_float(record["observed_rate_hz"]),
                expected_rate_hz=_opt_float(record["expected_rate_hz"]),
                rate_assessment=str(record["rate_assessment"]),
                evidence=str(record["evidence"]),
                absence=None if record["absence"] is None else str(record["absence"]),
                absence_detail=str(record["absence_detail"]),
                receipts_discarded=record["receipts_discarded"],
                plausibility=(
                    None if plausibility is None else ChannelPlausibility.from_mapping(plausibility)
                ),
            )
        except KeyError as exc:
            raise AttestationRefused(f"channel record is missing {exc}") from exc
        except PreflightError as exc:
            raise AttestationRefused(f"channel record carries an undecodable ruling: {exc}") from exc


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AttestationRefused(f"expected a number or None, got {value!r}")
    return float(value)


@dataclass(frozen=True, slots=True)
class HardwareAttestationV1:
    """The rig, as proven. Digest-stable, complete, and fail-closed.

    Completeness is a property, not a convention: every key in
    :data:`REQUIRED_OBSERVATIONS` must appear (as a value or as an explicit
    absence) and every channel in the PS-A matrix must appear. An attestation
    cannot dodge the firmware gate by omitting the firmware.
    """

    session_label: str
    generated_realtime_ns: int
    operator: str
    observations: tuple[Observation, ...]
    channels: tuple[ChannelAttestation, ...]
    findings: tuple[Finding, ...] = ()
    #: PS-E's storage budget for the requested session, when one was supplied.
    #: ``None`` means nobody supplied one, which is not permission to record.
    required_free_bytes: int | None = None

    def __post_init__(self) -> None:
        if not self.session_label.strip():
            raise AttestationRefused("an attestation must carry a session label")
        if not self.operator.strip():
            raise AttestationRefused("an attestation must name the operator who ran it")
        if isinstance(self.generated_realtime_ns, bool) or not isinstance(
            self.generated_realtime_ns, int
        ):
            raise AttestationRefused("generated_realtime_ns must be an int (nanoseconds)")
        if self.generated_realtime_ns < 0:
            raise AttestationRefused("generated_realtime_ns must be non-negative")
        keys = [obs.key for obs in self.observations]
        if len(set(keys)) != len(keys):
            raise AttestationRefused(
                f"duplicate observation keys: {sorted({k for k in keys if keys.count(k) > 1})}"
            )
        missing = [key for key in REQUIRED_OBSERVATIONS if key not in set(keys)]
        if missing:
            raise AttestationRefused(
                f"attestation is incomplete: no observation for {missing}. Every required "
                f"key must appear, as a value or as an explicit absence."
            )
        unexpected = sorted(set(keys) - set(REQUIRED_OBSERVATIONS))
        if unexpected:
            raise AttestationRefused(
                f"attestation carries observation keys that are not part of "
                f"{ATTESTATION_SCHEMA}: {unexpected}"
            )
        ids = [entry.channel_id for entry in self.channels]
        if len(set(ids)) != len(ids):
            raise AttestationRefused(
                f"duplicate channel attestations: "
                f"{sorted({i for i in ids if ids.count(i) > 1})}"
            )
        if self.required_free_bytes is not None and (
            isinstance(self.required_free_bytes, bool)
            or not isinstance(self.required_free_bytes, int)
            or self.required_free_bytes < 0
        ):
            raise AttestationRefused("required_free_bytes must be a non-negative int or None")

    # -- derived ----------------------------------------------------------

    @property
    def by_key(self) -> Mapping[str, Observation]:
        return {obs.key: obs for obs in self.observations}

    @property
    def by_channel(self) -> Mapping[str, ChannelAttestation]:
        return {entry.channel_id: entry for entry in self.channels}

    @property
    def firmware(self) -> tuple[FirmwarePinState, str]:
        return evaluate_firmware_pin(self.by_key.get("robot.firmware_version"))

    @property
    def physical_channels(self) -> tuple[str, ...]:
        """Channels this attestation claims a PHYSICAL origin for."""

        return tuple(
            entry.channel_id
            for entry in self.channels
            if entry.origin is EvidenceOrigin.PHYSICAL
        )

    @property
    def plausibility_counts(self) -> Mapping[str, int]:
        """How many channels PASS/FAIL/UNKNOWN the physical rules."""

        counts = {verdict.value: 0 for verdict in PlausibilityVerdict}
        for entry in self.channels:
            counts[entry.plausibility_verdict.value] += 1
        return counts

    @property
    def implausible_channels(self) -> tuple[str, ...]:
        """Channels whose contents are not physically possible.

        Derived from each channel's own recorded checks, so this list cannot be
        shortened by editing the file. These channels are still PRESENT, still
        PHYSICAL and still recorded — the card is explicit that a failed
        plausibility check must never silence a recording. What this list does is
        make it impossible to hold the dataset six months from now without
        knowing which channels were lying on the day.
        """

        return tuple(
            entry.channel_id
            for entry in self.channels
            if entry.plausibility_verdict is PlausibilityVerdict.FAIL
        )

    @property
    def plausibility_evidence(self) -> tuple[str, ...]:
        """Every failed rule and every verdict-free note, flattened for a reader.

        Carries the ``PointCloud2.fields[]`` dumps, which is the one piece of
        evidence on this card that no later session can recover.
        """

        lines: list[str] = []
        for entry in self.channels:
            ruling = entry.plausibility
            if ruling is None:
                continue
            for check in ruling.checks:
                if check.verdict is PlausibilityVerdict.FAIL:
                    lines.append(f"{entry.channel_id} FAIL {check.rule}: {check.detail}")
            for note in ruling.notes:
                lines.append(f"{entry.channel_id} note {note}")
        return tuple(lines)

    @property
    def free_bytes(self) -> int | None:
        obs = self.by_key.get("storage.free_bytes")
        if obs is None or not obs.is_known or not isinstance(obs.value, int):
            return None
        return obs.value

    @property
    def blocking_findings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is FindingSeverity.BLOCKING)

    @property
    def advisories(self) -> tuple[str, ...]:
        """MAJOR findings: they do not block, and they are never hidden either.

        A CRITICAL channel's absence blocks (PS-A: "the session did not achieve
        the thing it exists for"). An IMPORTANT one's does not — but an
        unrecorded channel does not exist, and the owner's directive is *use all
        the sensors possible*, so every one of these is put in front of the
        operator at the go/no-go rather than being scored away. The decision is
        the run sheet's (``session/STAGE0_RUN_SHEET.md`` §6); this is the
        evidence it decides on.
        """

        return tuple(
            f"{finding.code}: {finding.detail}"
            for finding in self.findings
            if finding.severity is FindingSeverity.MAJOR
        )

    @property
    def refusals(self) -> tuple[str, ...]:
        """Reasons the session may not connect to the robot LAN at all."""

        state, detail = self.firmware
        if state.clears_pin:
            return ()
        return (firmware_refusal_message(state, detail),)

    @property
    def degradations(self) -> tuple[str, ...]:
        """Reasons the session may not record, short of a connect refusal."""

        reasons: list[str] = []
        for finding in self.blocking_findings:
            reasons.append(f"{finding.code}: {finding.detail}")
        free = self.free_bytes
        if self.required_free_bytes is None:
            reasons.append(
                "no storage budget was supplied (--required-free-gib): PS-E owns the "
                "bandwidth arithmetic and preflight refuses to invent a threshold it "
                "does not own, so free space is recorded but not cleared"
            )
        elif free is None:
            reasons.append(
                "free disk space could not be measured, so the PS-E budget cannot be cleared"
            )
        elif free < self.required_free_bytes:
            reasons.append(
                f"free space {free} B ({free / 2**30:.1f} GiB) is below the requested "
                f"budget {self.required_free_bytes} B "
                f"({self.required_free_bytes / 2**30:.1f} GiB)"
            )
        return tuple(reasons)

    @property
    def verdict(self) -> SessionVerdict:
        """Worst wins. Derived, so it cannot be hand-edited into a GO."""

        if self.refusals:
            return SessionVerdict.REFUSE_CONNECT
        if self.degradations:
            return SessionVerdict.DEGRADE_MMP
        return SessionVerdict.GO_RECORD

    def raise_for_verdict(self) -> None:
        """Turn a refusal into an exception, for a caller that wants one."""

        refusals = self.refusals
        if refusals:
            raise FirmwarePinRefusal(" | ".join(refusals))
        if self.verdict is not SessionVerdict.GO_RECORD:
            raise AttestationRefused(
                "session may not record: " + " | ".join(self.degradations)
            )

    # -- serialisation ----------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        state, detail = self.firmware
        return {
            "schema": ATTESTATION_SCHEMA,
            "session_label": self.session_label,
            "generated_realtime_ns": self.generated_realtime_ns,
            "operator": self.operator,
            "observations": [obs.to_dict() for obs in self.observations],
            "channels": [entry.as_dict() for entry in self.channels],
            "findings": [finding.to_dict() for finding in self.findings],
            "required_free_bytes": self.required_free_bytes,
            "firmware_pin": {
                "pin": ".".join(str(n) for n in FIRMWARE_PIN),
                "adr": FIRMWARE_PIN_ADR,
                "cve_class": list(FIRMWARE_CVE_CLASS),
                "state": state.value,
                "detail": detail,
            },
            "verdict": self.verdict.value,
            "refusals": list(self.refusals),
            "degradations": list(self.degradations),
            "advisories": list(self.advisories),
            "physical_channels": list(self.physical_channels),
            "plausibility": {
                "counts": dict(self.plausibility_counts),
                "implausible_channels": list(self.implausible_channels),
                "evidence": list(self.plausibility_evidence),
            },
            "does_not_prove": list(DOES_NOT_PROVE),
        }

    def canonical_json(self) -> str:
        """Byte-stable: sorted keys, no whitespace, no NaN token."""

        return json.dumps(
            self.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )

    def digest(self) -> str:
        """SHA-256 over :meth:`canonical_json`. PS-B binds this into the sidecar."""

        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_mapping(cls, record: Mapping[str, Any]) -> HardwareAttestationV1:
        """Decode, recomputing every derived answer from the raw counts."""

        if not isinstance(record, Mapping):
            raise AttestationRefused(
                f"attestation record must be a mapping, got {type(record).__name__}"
            )
        if record.get("schema") != ATTESTATION_SCHEMA:
            raise AttestationRefused(
                f"expected schema {ATTESTATION_SCHEMA!r}, got {record.get('schema')!r}"
            )
        try:
            observations = tuple(
                _observation_from_mapping(item) for item in record["observations"]
            )
            channels = tuple(
                ChannelAttestation.from_mapping(item) for item in record["channels"]
            )
            findings = tuple(
                Finding(
                    code=str(item["code"]),
                    severity=FindingSeverity(item["severity"]),
                    detail=str(item["detail"]),
                )
                for item in record["findings"]
            )
            return cls(
                session_label=str(record["session_label"]),
                generated_realtime_ns=record["generated_realtime_ns"],
                operator=str(record["operator"]),
                observations=observations,
                channels=channels,
                findings=findings,
                required_free_bytes=record["required_free_bytes"],
            )
        except KeyError as exc:
            raise AttestationRefused(f"attestation record is missing {exc}") from exc
        except ValueError as exc:
            raise AttestationRefused(f"attestation record carries an undecodable value: {exc}") from exc


def _observation_from_mapping(record: Mapping[str, Any]) -> Observation:
    if not isinstance(record, Mapping):
        raise AttestationRefused(
            f"observation record must be a mapping, got {type(record).__name__}"
        )
    try:
        absence = record["absence"]
        return Observation(
            key=str(record["key"]),
            value=record["value"],
            kind=EvidenceKind(record["kind"]),
            evidence=str(record["evidence"]),
            absence=None if absence is None else AbsenceReason(absence),
            remedy=str(record.get("remedy", "")),
        )
    except KeyError as exc:
        raise AttestationRefused(f"observation record is missing {exc}") from exc
    except (ValueError, PreflightError) as exc:
        raise AttestationRefused(f"observation record is not decodable: {exc}") from exc


def verify_mapping(record: Mapping[str, Any]) -> tuple[HardwareAttestationV1, tuple[str, ...]]:
    """Decode an attestation file and report every forged derived answer.

    The second element is empty for an untouched file. A non-empty tuple means
    the file on disk claims something its own raw counts do not support — the
    exact shape a hand-edited ``"origin": "physical"`` takes.
    """

    attestation = HardwareAttestationV1.from_mapping(record)
    discrepancies: list[str] = []
    written_channels = {
        str(item.get("channel_id")): item for item in record.get("channels", [])
    }
    for entry in attestation.channels:
        written = written_channels.get(entry.channel_id, {})
        ruling = entry.plausibility
        for name, computed, basis in (
            ("status", entry.status.value, f"{entry.messages_received} message(s) received"),
            ("origin", entry.origin.value, f"{entry.messages_received} message(s) received"),
            (
                "plausibility_verdict",
                entry.plausibility_verdict.value,
                (
                    "no recorded plausibility ruling"
                    if ruling is None
                    else f"its own {len(ruling.checks)} recorded check(s)"
                ),
            ),
        ):
            claimed = written.get(name)
            if claimed is not None and claimed != computed:
                discrepancies.append(
                    f"{entry.channel_id}: file claims {name}={claimed!r} but {basis} "
                    f"recomputes to {computed!r}"
                )
    claimed_verdict = record.get("verdict")
    if claimed_verdict is not None and claimed_verdict != attestation.verdict.value:
        discrepancies.append(
            f"file claims verdict={claimed_verdict!r} but its own contents recompute to "
            f"{attestation.verdict.value!r}"
        )
    claimed_physical = record.get("physical_channels")
    if claimed_physical is not None and list(claimed_physical) != list(
        attestation.physical_channels
    ):
        discrepancies.append(
            f"file claims physical_channels={list(claimed_physical)} but only "
            f"{list(attestation.physical_channels)} received a message"
        )
    claimed_plausibility = record.get("plausibility")
    if isinstance(claimed_plausibility, Mapping):
        claimed_bad = claimed_plausibility.get("implausible_channels")
        if claimed_bad is not None and list(claimed_bad) != list(
            attestation.implausible_channels
        ):
            discrepancies.append(
                f"file claims implausible_channels={list(claimed_bad)} but the recorded "
                f"per-channel checks recompute to "
                f"{list(attestation.implausible_channels)} — deleting a channel from that "
                f"list does not make it plausible"
            )
        claimed_counts = claimed_plausibility.get("counts")
        if claimed_counts is not None and dict(claimed_counts) != dict(
            attestation.plausibility_counts
        ):
            discrepancies.append(
                f"file claims plausibility counts {dict(claimed_counts)} but its own "
                f"channels recompute to {dict(attestation.plausibility_counts)}"
            )
    return attestation, tuple(discrepancies)


#: Non-empty by construction and carried inside every emitted attestation, so
#: the limits travel with the evidence instead of living only in a status doc
#: nobody opens six months from now.
DOES_NOT_PROVE: tuple[str, ...] = (
    (
        "A PRESENT channel proves a message arrived during the probe window. It does "
        "not prove the message carried what the matrix says it carries, that the "
        "sensor was calibrated, or that the channel stayed up for the recording."
    ),
    (
        "The firmware pin state is read through whatever reader was supplied. This "
        "module verifies the version against ADR 0002; it does not verify the robot's "
        "identity, and a compromised unit can report any string it likes."
    ),
    (
        "JetPack is DERIVED from the L4T release through a declared table, and no "
        "flash was performed. ADR 0001's golden image stays unvalidated."
    ),
    (
        "Free disk space is a measurement; whether it is enough is PS-E's arithmetic, "
        "and this attestation clears it only when a budget was supplied."
    ),
    (
        "Mount geometry, clock offsets and recording integrity are PS-F, PS-C and "
        "PS-B respectively. Nothing here speaks to any of them."
    ),
    (
        "A plausibility PASS proves only that the quantities the reader chose to "
        "summarise were inside bounds during the probe window. It is not a calibration, "
        "not an accuracy claim, and says nothing about axis order, sign convention, "
        "handedness, or the frame the numbers are expressed in — an IMU mounted upside "
        "down still reads 9.81 m/s^2 at rest and still PASSES."
    ),
    (
        "A plausibility UNKNOWN is the most common outcome and means only that the "
        "evidence to judge was absent — most often that no rest period was declared or "
        "that the reader supplied no physical measurement. It is never a pass."
    ),
    (
        "The at-rest rules stand on an OPERATOR's claim that the rig was stationary. "
        "Nothing verifies that claim, and a wrong one turns a real motion signal into a "
        "spurious FAIL or hides a real fault behind a plausible one."
    ),
    (
        "The PointCloud2 fields[] dump records what the driver DECLARED. It does not "
        "prove the per-point time values are correct, monotonic, or in the units the "
        "field name implies — only that a field by that name exists."
    ),
    (
        "Foot force is asserted only to vary and to fit int16. It has no published "
        "units, gain or offset, so no absolute contact force is claimed anywhere here."
    ),
)


def attest(
    report: PreflightReport,
    *,
    session_label: str,
    operator: str,
    generated_realtime_ns: int | None = None,
    required_free_bytes: int | None = None,
    channels: Sequence[Channel] = CHANNELS,
) -> HardwareAttestationV1:
    """Build the attestation from a preflight report. Refuses on any mismatch.

    Both directions of channel coverage are checked: a probe for a channel that
    is not in the PS-A matrix is a refusal (it would attest a stream nobody
    enumerated), and a matrix channel with no probe is a refusal (it would let a
    silently skipped sensor disappear from the record).
    """

    if not isinstance(report, PreflightReport):
        raise AttestationRefused(
            f"attest() needs a PreflightReport, got {type(report).__name__}"
        )
    matrix = {entry.channel_id: entry for entry in channels}
    probed = {probe.channel_id for probe in report.channels}
    unknown = sorted(probed - set(matrix))
    if unknown:
        raise AttestationRefused(
            f"preflight probed channels that are not in the PS-A matrix: {unknown}"
        )
    unprobed = sorted(set(matrix) - probed)
    if unprobed:
        raise AttestationRefused(
            f"preflight did not probe every matrix channel; missing {unprobed}. A "
            f"channel absent from the record is the easiest kind of loss to overlook."
        )
    return HardwareAttestationV1(
        session_label=session_label,
        operator=operator,
        generated_realtime_ns=(
            time.time_ns() if generated_realtime_ns is None else generated_realtime_ns
        ),
        observations=tuple(report.observations),
        channels=tuple(
            ChannelAttestation.from_probe(probe, matrix[probe.channel_id])
            for probe in report.channels
        ),
        findings=tuple(report.findings),
        required_free_bytes=required_free_bytes,
    )


def format_attestation(attestation: HardwareAttestationV1) -> str:
    """The summary an operator reads before deciding to plug anything in."""

    state, detail = attestation.firmware
    counts = {status: 0 for status in ProbeStatus}
    for entry in attestation.channels:
        counts[entry.status] += 1
    critical_absent = [
        entry.channel_id
        for entry in attestation.channels
        if entry.criticality == Criticality.CRITICAL.value
        and entry.status is not ProbeStatus.PRESENT
    ]
    lines = [
        "",
        "=" * 78,
        f"HARDWARE ATTESTATION — {ATTESTATION_SCHEMA}",
        f"  session      {attestation.session_label}",
        f"  operator     {attestation.operator}",
        f"  digest       {attestation.digest()}",
        f"  firmware pin {state.value.upper()} — {detail}",
        "  channels     "
        + "  ".join(f"{status.value}={counts[status]}" for status in ProbeStatus),
        (
            f"  PHYSICAL     {len(attestation.physical_channels)} channel(s) earned a "
            f"PHYSICAL origin by delivering a message"
        ),
        "  plausible    "
        + "  ".join(
            f"{name}={count}" for name, count in attestation.plausibility_counts.items()
        )
        + "   (a channel is not healthy because bytes arrive)",
    ]
    if critical_absent:
        lines.append(f"  critical not PRESENT: {', '.join(critical_absent)}")
    if attestation.implausible_channels:
        lines.append(
            f"  IMPLAUSIBLE  {', '.join(attestation.implausible_channels)} — RECORD THEM "
            f"ANYWAY; a suspect channel is still evidence"
        )
    for line in attestation.plausibility_evidence:
        lines.append(f"    {line}")
    lines.append("")
    for refusal in attestation.refusals:
        lines.append(f"  REFUSAL: {refusal}")
    for degradation in attestation.degradations:
        lines.append(f"  DEGRADE: {degradation}")
    for advisory in attestation.advisories:
        lines.append(f"  ADVISORY (does not block, decide at the go/no-go): {advisory}")
    lines.extend(
        [
            "",
            f"VERDICT: {attestation.verdict.value.upper()}",
            _VERDICT_GUIDANCE[attestation.verdict],
            "=" * 78,
        ]
    )
    return "\n".join(lines)


_VERDICT_GUIDANCE = {
    SessionVerdict.REFUSE_CONNECT: (
        "  Do NOT attach the Orin or any host to the robot LAN. Stage-0 run sheet §6, "
        "branch DEGRADE-MMP: mount, measure, photograph, record nothing."
    ),
    SessionVerdict.DEGRADE_MMP: (
        "  Stage-0 run sheet §6, branch DEGRADE-MMP: mount, measure, photograph, record "
        "nothing. A legitimate outcome — it captures exactly what a later session could "
        "not recover. Save this failing attestation; it is the deliverable."
    ),
    SessionVerdict.GO_RECORD: (
        "  Stage-0 run sheet §6, branch GO-RECORD. Record the full dataset and bind this "
        "attestation's digest into the PS-B sidecar."
    ),
}


def main(argv: Sequence[str] | None = None) -> int:
    """Probe, attest, and exit-code the verdict. Never raises a traceback."""

    parser = build_arg_parser(__doc__ or "parcel hardware attestation")
    parser.add_argument(
        "--session-label", default=None,
        help="run id from the Stage-0 run sheet, e.g. P5-DRY-20260813-01",
    )
    parser.add_argument("--attesting-operator", default=None, help="who ran this attestation")
    parser.add_argument(
        "--required-free-gib", type=float, default=None,
        help="PS-E storage budget for the requested session length, GiB",
    )
    parser.add_argument("--out", default=None, help="write the attestation JSON here")
    parser.add_argument(
        "--print-preflight", action="store_true", help="also print the full preflight report"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        rates = parse_rate_overrides(args.rate)
        operator_obs = operator_observation_from_args(args)
        required = _required_free_bytes(args.required_free_gib)
        report = run_preflight(
            window_s=float(args.window),
            configured_rates=rates,
            storage_path=args.storage,
            builtin_lidar_operator=operator_obs,
            rest_period=rest_period_from_args(args),
        )
        attestation = attest(
            report,
            session_label=args.session_label or _default_session_label(),
            operator=args.attesting_operator or _default_operator(),
            required_free_bytes=required,
        )
    except (PreflightError, AttestationRefused) as exc:
        print(f"ATTESTATION REFUSED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - never a traceback on a session morning
        print(f"ATTESTATION REFUSED (unexpected {type(exc).__name__}): {exc}", file=sys.stderr)
        return 2

    if args.print_preflight:
        print(format_report(report))
    else:
        # The per-channel physical verdict belongs in the run header whatever
        # else the operator asked for: it is the half of channel health that
        # receipt counting cannot see.
        print("\n".join(format_plausibility_block(report)))
    print(format_attestation(attestation))
    if args.json:
        print(attestation.canonical_json())
    if args.out:
        try:
            Path(args.out).write_text(
                json.dumps(attestation.as_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"could not write {args.out}: {exc}", file=sys.stderr)
            return 2
        print(f"attestation written to {args.out} (digest {attestation.digest()})")
    return attestation.verdict.exit_code


def _required_free_bytes(gib: float | None) -> int | None:
    if gib is None:
        return None
    if math.isnan(gib) or math.isinf(gib) or gib < 0.0:
        raise AttestationRefused(f"--required-free-gib must be finite and non-negative, got {gib!r}")
    return int(gib * 2**30)


def _default_session_label() -> str:
    return "P5-DRY-" + time.strftime("%Y%m%d-%H%M%SZ", time.gmtime())


def _default_operator() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - a nameless operator is still an operator
        return "unknown-operator"


__all__ = [
    "ATTESTATION_SCHEMA",
    "DOES_NOT_PROVE",
    "FIRMWARE_CVE_CLASS",
    "FIRMWARE_PIN",
    "FIRMWARE_PIN_ADR",
    "REQUIRED_OBSERVATIONS",
    "AttestationRefused",
    "ChannelAttestation",
    "FirmwarePinRefusal",
    "FirmwarePinState",
    "HardwareAttestationV1",
    # Re-exported from preflight so a consumer of the attestation does not need
    # to reach into two modules to read one channel's verdict.
    "PlausibilityVerdict",
    "SessionVerdict",
    "attest",
    "evaluate_firmware_pin",
    "firmware_refusal_message",
    "format_attestation",
    "main",
    "parse_firmware_version",
    "verify_mapping",
]


if __name__ == "__main__":
    raise SystemExit(main())
