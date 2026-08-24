"""Card PS-D — preflight discovery, fail-closed probes, and ``HardwareAttestationV1``.

Provenance: ``scrum/20260813/task_1/README.md`` §PS-D,
``scrum/20260813/task_1/CHANNEL_MATRIX.md`` (the authoritative 25-row matrix that
PS-A transcribed into 28 channels, rewritten by PS-H against
``scrum/20260813/task_1/RISK_ASSESSMENT.md``), ``PHYSICAL_SESSION_PLAN.md`` (why the tranche
exists) and ``scrum/20260805/task_1/adr/0002-firmware-pin.md`` (why the firmware
gate is a *security* control and not a compatibility check). Precedents followed
here: ``tests/test_capture_envelope.py`` for the paired property/seeded-failure
idiom and the AST pins, and ``tests/test_w0b_commissioning.py`` for the
"derived answers are recomputed, never read back" cells.

Every gate below carries a seeded-failure companion. A cell that only asserts the
fixed behaviour cannot tell you the oracle would have caught the defect — so
where a rule matters, the defective rule is re-implemented in the test (or the
record is hand-forged) and the oracle is shown to reject it.

The one property this file exists to pin: **there is no code path to PRESENT
without an actually-received message, and no path to an ``EvidenceOrigin.PHYSICAL``
claim without one either.**
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path

import pytest

from parcel_robot.capture.channels import CHANNELS, CHANNELS_BY_ID, channel, channel_ids
from parcel_robot.evidence_origin import EvidenceOrigin
from scripts.parcel_capture import attest as attest_mod
from scripts.parcel_capture import preflight as pf
from scripts.parcel_capture.attest import (
    ATTESTATION_SCHEMA,
    DOES_NOT_PROVE,
    FIRMWARE_CVE_CLASS,
    REQUIRED_OBSERVATIONS,
    AttestationRefused,
    ChannelAttestation,
    FirmwarePinRefusal,
    FirmwarePinState,
    HardwareAttestationV1,
    SessionVerdict,
    attest,
    evaluate_firmware_pin,
    parse_firmware_version,
    verify_mapping,
)
from scripts.parcel_capture.preflight import (
    ACCEL_SENSOR_CEILING_MPS2,
    GRAVITY_MPS2,
    GYRO_REST_CEILING_RPS,
    AbsenceReason,
    ChannelClass,
    ChannelPlausibility,
    ChannelProbe,
    EvidenceKind,
    Finding,
    FindingSeverity,
    FootForceSample,
    ImageSample,
    ImuSample,
    ImuStreamKind,
    Observation,
    OperatorObservation,
    PhysicalSample,
    PlausibilityCheck,
    PlausibilityVerdict,
    PointCloudSample,
    PowerSample,
    PreflightReport,
    ProbeContractError,
    ProbeStatus,
    RateAssessment,
    RestPeriod,
    SampleReceipt,
    TransportUnavailableError,
    assess_plausibility,
    classify_channel,
    format_plausibility_block,
    imu_cross_check,
    imu_stream_kind,
    imu_unit_id,
    probe_all_channels,
    probe_builtin_lidar,
    probe_channel,
    probe_jetpack,
    probe_network,
    run_preflight,
    scan_config_scalars,
)

MODULE_PATHS = (Path(pf.__file__), Path(attest_mod.__file__))
REPO = Path(__file__).resolve().parents[1]

#: A CRITICAL, PERIODIC channel with a device-fixed 10 Hz rate — the cleanest
#: subject for the rate cells. Its absence is a session-grade event.
CH_A = "go2.utlidar.cloud"
#: A second CRITICAL channel at 500 Hz, used whenever one channel's outcome must
#: be shown not to contaminate another's.
CH_B = "go2.lowstate"
#: The 1 Hz channel, for the window-too-short cell.
CH_SLOW = "go2.utlidar.voxel_map"
#: EVENT_DRIVEN: silence is normal here and a rate expectation is a category error.
CH_EVENT = "go2.wirelesscontroller"
#: CONFIGURED: the rate is PS-E's budget decision, so there is no nominal.
CH_CONFIGURED = "d455.color"


class FakeClock:
    """A monotonic ns clock the test drives, so no cell sleeps."""

    def __init__(self, start: int = 1_000_000_000) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += int(seconds * 1_000_000_000)


def _stream_reader(
    clock: FakeClock,
    *,
    spacing_s: float,
    count: int,
    then: BaseException | None = None,
    drain_to_s: float | None = None,
    label_as: str | None = None,
    payload_bytes: int = 64,
):
    """A reader that yields ``count`` receipts ``spacing_s`` apart on ``clock``."""

    def reader(entry, window_s: float) -> Iterator[SampleReceipt]:
        for _ in range(count):
            clock.advance(spacing_s)
            yield SampleReceipt(
                channel_id=label_as or entry.channel_id,
                host_monotonic_ns=clock(),
                payload_bytes=payload_bytes,
            )
        if drain_to_s is not None:
            clock.advance(drain_to_s)
        if then is not None:
            raise then

    return reader


def _silent_reader(clock: FakeClock, *, burn_s: float = 0.0):
    def reader(entry, window_s: float) -> Iterator[SampleReceipt]:
        clock.advance(burn_s)
        return
        yield  # pragma: no cover - makes this a generator

    return reader


def _fake_device(**values: str):
    def reader():
        return dict(values)

    return reader


def _raising_device(exc: BaseException):
    def reader():
        raise exc

    return reader


def _fields(obj, **overrides):
    """Field mapping for a ``slots=True`` dataclass, which has no ``__dict__``."""

    values = {f.name: getattr(obj, f.name) for f in fields(obj)}
    values.update(overrides)
    return values


def _probe(
    channel_id: str,
    *,
    messages: int,
    window_s: float = 10.0,
    expected: float | None = None,
    max_gap_ns: int | None = None,
    absence: AbsenceReason | None = None,
) -> ChannelProbe:
    """A probe built directly, for the cells that reason about the derivation."""

    return ChannelProbe(
        channel_id=channel_id,
        messages_received=messages,
        window_s=window_s,
        expected_rate_hz=expected,
        max_gap_ns=max_gap_ns if messages else None,
        evidence="fixture probe",
        absence=absence if messages == 0 else None,
    )


def _full_report(
    *,
    firmware: str | None = None,
    firmware_kind: EvidenceKind = EvidenceKind.MACHINE_READ,
    present_channels: tuple[str, ...] = (),
    findings: tuple[Finding, ...] = (),
    free_bytes: int = 4 * 2**40,
) -> PreflightReport:
    """A complete report over the whole matrix, with the fields the card needs.

    Every required observation is present (as a value or an explicit absence) and
    every matrix channel is probed, so ``attest()`` accepts it. Only the pieces a
    cell cares about are varied.
    """

    observations: list[Observation] = []
    for key in REQUIRED_OBSERVATIONS:
        if key == "robot.firmware_version":
            if firmware is None:
                observations.append(
                    Observation(
                        key=key,
                        value=None,
                        kind=EvidenceKind.ABSENT,
                        evidence="fixture: firmware not read",
                        absence=AbsenceReason.DEPENDENCY_MISSING,
                    )
                )
            else:
                observations.append(
                    Observation(
                        key=key,
                        value=firmware,
                        kind=firmware_kind,
                        evidence=(
                            "read off the unit by operator fixture, photograph P01"
                            if firmware_kind is EvidenceKind.OPERATOR_OBSERVED
                            else "fixture: go2 reader reported firmware"
                        ),
                    )
                )
            continue
        if key == "storage.free_bytes":
            observations.append(
                Observation(
                    key=key,
                    value=free_bytes,
                    kind=EvidenceKind.MACHINE_READ,
                    evidence="fixture disk_usage",
                )
            )
            continue
        observations.append(
            Observation(
                key=key,
                value=None,
                kind=EvidenceKind.ABSENT,
                evidence=f"fixture: {key} not measured",
                absence=AbsenceReason.NOT_ATTEMPTED,
            )
        )

    probes = tuple(
        _probe(
            entry.channel_id,
            messages=100 if entry.channel_id in present_channels else 0,
            expected=None,
            max_gap_ns=0,
            absence=None if entry.channel_id in present_channels else AbsenceReason.TIMEOUT,
        )
        for entry in CHANNELS
    )
    return PreflightReport(
        observations=tuple(observations), channels=probes, findings=findings
    )


def _attest(report: PreflightReport, **kwargs) -> HardwareAttestationV1:
    params = {
        "session_label": "P5-DRY-20260813-01",
        "operator": "fixture",
        "generated_realtime_ns": 1_786_000_000_000_000_000,
    }
    params.update(kwargs)
    return attest(report, **params)


# ---------------------------------------------------------------------------
# GATE 1 — there is no path to PRESENT without a received message
# ---------------------------------------------------------------------------


def test_status_is_derived_and_cannot_be_passed_to_any_constructor() -> None:
    """The structural half of the card's headline gate.

    ``status`` and ``origin`` are properties. If they were fields, a caller could
    write PRESENT/PHYSICAL onto a silent channel, and every other cell in this
    file would be testing a convention rather than a mechanism.
    """

    probe_fields = set(ChannelProbe.__dataclass_fields__)
    assert "status" not in probe_fields
    assert "rate_assessment" not in probe_fields
    assert isinstance(ChannelProbe.status, property)
    assert isinstance(ChannelProbe.rate_assessment, property)

    attestation_fields = set(ChannelAttestation.__dataclass_fields__)
    assert "status" not in attestation_fields
    assert "origin" not in attestation_fields
    assert isinstance(ChannelAttestation.status, property)
    assert isinstance(ChannelAttestation.origin, property)
    assert isinstance(HardwareAttestationV1.verdict, property)


@pytest.mark.parametrize("reason", list(AbsenceReason))
def test_every_absence_reason_yields_absent_and_unknown_origin(reason: AbsenceReason) -> None:
    """Exhaustive over the reason enum: no absence is a special permissive case."""

    probe = _probe(CH_A, messages=0, expected=10.0, absence=reason)
    assert probe.status is ProbeStatus.ABSENT
    assert probe.observed_rate_hz is None
    assert probe.rate_assessment is RateAssessment.NOT_APPLICABLE
    entry = ChannelAttestation.from_probe(probe, channel(CH_A))
    assert entry.status is ProbeStatus.ABSENT
    assert entry.origin is EvidenceOrigin.UNKNOWN


def test_seeded_failure_a_probe_with_no_messages_cannot_be_talked_into_present() -> None:
    """Seeded: the defective rule ("declared LIVE, so call it present").

    The matrix says 16 of 28 channels are LIVE. A preflight that trusted the
    matrix would report them all PRESENT with no hardware attached. The oracle
    here is the derivation itself, so the defective rule is re-implemented and
    shown to disagree with it on every silent channel.
    """

    defective = {
        entry.channel_id: (
            ProbeStatus.PRESENT if entry.presence.value == "live" else ProbeStatus.ABSENT
        )
        for entry in CHANNELS
    }
    probes = probe_all_channels(window_s=0.01, clock=FakeClock())
    honest = {probe.channel_id: probe.status for probe in probes}

    assert set(honest) == set(channel_ids())
    assert set(honest.values()) == {ProbeStatus.ABSENT}
    disagreements = [cid for cid in honest if honest[cid] is not defective[cid]]
    assert len(disagreements) == 16, (
        "the declared-presence rule would have minted 16 phantom channels; "
        f"got {len(disagreements)}"
    )


def test_a_channel_with_no_messages_must_name_a_reason() -> None:
    """Silence without a reason is the permissive default board rule 3 forbids."""

    with pytest.raises(ProbeContractError, match="must name an AbsenceReason"):
        ChannelProbe(
            channel_id=CH_A,
            messages_received=0,
            window_s=10.0,
            expected_rate_hz=10.0,
            max_gap_ns=None,
            evidence="silent but unexplained",
        )
    with pytest.raises(ProbeContractError, match="absence="):
        ChannelProbe(
            channel_id=CH_A,
            messages_received=5,
            window_s=10.0,
            expected_rate_hz=10.0,
            max_gap_ns=0,
            evidence="received but also absent",
            absence=AbsenceReason.TIMEOUT,
        )


def test_present_is_produced_in_exactly_one_place_per_module() -> None:
    """AST pin: the derivation is the only producer of PRESENT / PHYSICAL.

    A second producer is how a fail-closed rule rots — the first one stays
    correct while the new one quietly does not.
    """

    producers: set[tuple[str, str, str]] = set()
    consumers: set[tuple[str, str, str]] = set()
    for path in MODULE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # An occurrence inside a comparison READS the value; anything else
            # (a return, an assignment, a call argument) PRODUCES it.
            compared = {
                id(inner)
                for cmp_node in ast.walk(node)
                if isinstance(cmp_node, ast.Compare)
                for operand in [cmp_node.left, *cmp_node.comparators]
                for inner in ast.walk(operand)
            }
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Attribute)
                    and inner.attr in {"PRESENT", "PHYSICAL"}
                    and isinstance(inner.value, ast.Name)
                    and inner.value.id in {"ProbeStatus", "EvidenceOrigin"}
                ):
                    bucket = consumers if id(inner) in compared else producers
                    bucket.add((path.name, node.name, inner.attr))

    assert producers == {
        ("preflight.py", "status", "PRESENT"),
        ("attest.py", "status", "PRESENT"),
        ("attest.py", "origin", "PHYSICAL"),
    }, f"PRESENT/PHYSICAL produced outside the derivation: {sorted(producers)}"
    # The consumers are comparisons only, which cannot mint anything.
    assert consumers, "the scan found no comparisons at all, so it is not working"
    assert {func for _n, func, _a in consumers} == {
        "format_attestation",
        "physical_channels",
    }, sorted(consumers)


# ---------------------------------------------------------------------------
# GATE 2 — a probe that times out is ABSENT; a probe that raises is ABSENT
# ---------------------------------------------------------------------------


def test_a_silent_window_is_absent_with_timeout() -> None:
    clock = FakeClock()
    probe = probe_channel(
        channel(CH_A), _silent_reader(clock, burn_s=10.0), window_s=10.0,
        expected_rate_hz=10.0, clock=clock,
    )
    assert probe.status is ProbeStatus.ABSENT
    assert probe.absence is AbsenceReason.TIMEOUT
    assert probe.messages_received == 0
    assert "no message in" in probe.evidence


def test_a_reader_that_finishes_early_with_nothing_is_no_message_not_timeout() -> None:
    """Two different absences. A transport that closed is not a sensor that is slow."""

    clock = FakeClock()
    probe = probe_channel(
        channel(CH_A), _silent_reader(clock, burn_s=0.0), window_s=10.0, clock=clock
    )
    assert probe.absence is AbsenceReason.NO_MESSAGE
    assert probe.status is ProbeStatus.ABSENT


@pytest.mark.parametrize(
    ("raised", "expected_reason"),
    [
        (RuntimeError("device fell off the bus"), AbsenceReason.PROBE_RAISED),
        (TimeoutError("select() expired"), AbsenceReason.TIMEOUT),
        (OSError("no such device"), AbsenceReason.PROBE_RAISED),
        (ValueError("decode failed"), AbsenceReason.PROBE_RAISED),
    ],
)
def test_a_probe_that_raises_is_absent_and_its_receipts_are_discarded(
    raised: BaseException, expected_reason: AbsenceReason
) -> None:
    """The card's rule, applied even when the probe had already seen traffic.

    Partial evidence from a failed probe is not evidence — but it is not silently
    gone either: the count is retained so the operator can see what was thrown
    away and decide to re-probe.
    """

    clock = FakeClock()
    probe = probe_channel(
        channel(CH_A),
        _stream_reader(clock, spacing_s=0.1, count=5, then=raised),
        window_s=10.0,
        expected_rate_hz=10.0,
        clock=clock,
    )
    assert probe.status is ProbeStatus.ABSENT
    assert probe.absence is expected_reason
    assert probe.messages_received == 0
    assert probe.receipts_discarded == 5
    assert "DISCARDED" in probe.evidence
    assert type(raised).__name__ in probe.absence_detail


def test_seeded_failure_keeping_the_receipts_of_a_failed_probe_would_mint_presence() -> None:
    """Refutation: the same five receipts, minus the discard rule, read PRESENT.

    This is the whole value of the rule, made visible. The seeded "defective"
    version keeps what it received before the failure; it reports a channel that
    blew up mid-probe as a healthy one.
    """

    clock = FakeClock()
    failed = probe_channel(
        channel(CH_A),
        _stream_reader(clock, spacing_s=0.09, count=10, then=RuntimeError("boom")),
        window_s=1.0,
        expected_rate_hz=10.0,
        clock=clock,
    )
    assert failed.receipts_discarded == 10
    defective = ChannelProbe(
        channel_id=CH_A,
        messages_received=failed.receipts_discarded,
        window_s=1.0,
        expected_rate_hz=10.0,
        max_gap_ns=100_000_000,
        evidence="defective: kept the receipts of a failed probe",
    )
    assert defective.rate_assessment is RateAssessment.NOMINAL
    assert defective.status is ProbeStatus.PRESENT
    assert failed.status is ProbeStatus.ABSENT
    assert ChannelAttestation.from_probe(defective, channel(CH_A)).origin is (
        EvidenceOrigin.PHYSICAL
    )
    assert ChannelAttestation.from_probe(failed, channel(CH_A)).origin is EvidenceOrigin.UNKNOWN


def test_a_transport_refusal_carries_its_reason_and_an_actionable_remedy() -> None:
    clock = FakeClock()

    def reader(entry, window_s):
        raise TransportUnavailableError(
            AbsenceReason.DEPENDENCY_MISSING, "pyrealsense2 absent", "install it on the Orin"
        )

    probe = probe_channel(channel(CH_CONFIGURED), reader, window_s=1.0, clock=clock)
    assert probe.absence is AbsenceReason.DEPENDENCY_MISSING
    assert probe.remedy == "install it on the Orin"


def test_a_reader_factory_that_raises_costs_only_its_own_channel() -> None:
    """One broken adapter must not cost the session its report on the other 21."""

    def factory(entry):
        if entry.channel_id == CH_A:
            raise RuntimeError("adapter import blew up")
        return _silent_reader(FakeClock())

    probes = {p.channel_id: p for p in probe_all_channels(reader_factory=factory, window_s=0.01)}
    assert len(probes) == len(CHANNELS)
    assert probes[CH_A].absence is AbsenceReason.PROBE_RAISED
    assert "adapter import blew up" in probes[CH_A].absence_detail
    assert probes[CH_B].absence is AbsenceReason.NO_MESSAGE


# ---------------------------------------------------------------------------
# GATE 3 — a reader that breaks the probe contract is ABSENT, and says so
# ---------------------------------------------------------------------------


def test_a_receipt_labelled_with_another_channel_is_a_contract_violation() -> None:
    """A probe may not mint presence for a channel it was not probing.

    Named differently from a device error on purpose: this failure means the
    adapter is broken, and an operator who reads "sensor missing" will spend the
    session on the wrong problem.
    """

    clock = FakeClock()
    probe = probe_channel(
        channel(CH_A),
        _stream_reader(clock, spacing_s=0.1, count=3, label_as=CH_B),
        window_s=1.0,
        expected_rate_hz=10.0,
        clock=clock,
    )
    assert probe.status is ProbeStatus.ABSENT
    assert probe.absence is AbsenceReason.PROBE_CONTRACT_VIOLATION
    assert CH_B in probe.absence_detail
    assert "may not mint presence for another channel" in probe.absence_detail


def test_non_receipts_and_backwards_clocks_are_contract_violations() -> None:
    clock = FakeClock()

    def wrong_type(entry, window_s):
        yield {"channel_id": entry.channel_id}

    probe = probe_channel(channel(CH_A), wrong_type, window_s=1.0, clock=clock)
    assert probe.absence is AbsenceReason.PROBE_CONTRACT_VIOLATION
    assert "not a SampleReceipt" in probe.absence_detail

    def backwards(entry, window_s):
        yield SampleReceipt(entry.channel_id, 5_000, payload_bytes=1)
        yield SampleReceipt(entry.channel_id, 4_000, payload_bytes=1)

    probe = probe_channel(channel(CH_A), backwards, window_s=1.0, clock=FakeClock())
    assert probe.absence is AbsenceReason.PROBE_CONTRACT_VIOLATION
    assert "went backwards" in probe.absence_detail


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"payload_bytes": 0}, "not a message"),
        ({"payload_bytes": -1}, "non-negative"),
        ({"host_monotonic_ns": 1.5}, "must be an int"),
        ({"host_monotonic_ns": True}, "must be an int"),
        ({"host_monotonic_ns": -1}, "non-negative"),
        ({"source_timestamp_ns": 1.5}, "must be an int"),
        ({"channel_id": "  "}, "non-empty"),
    ],
)
def test_a_malformed_receipt_is_refused_never_defaulted(kwargs: dict, match: str) -> None:
    base = {
        "channel_id": CH_A,
        "host_monotonic_ns": 1_000,
        "payload_bytes": 64,
    }
    base.update(kwargs)
    with pytest.raises(ProbeContractError, match=match):
        SampleReceipt(**base)


# ---------------------------------------------------------------------------
# GATE 4 — PRESENT / DEGRADED, with the deficit quantified
# ---------------------------------------------------------------------------


def test_a_channel_at_nominal_rate_is_present() -> None:
    clock = FakeClock()
    probe = probe_channel(
        channel(CH_A), _stream_reader(clock, spacing_s=0.1, count=100), window_s=10.0,
        expected_rate_hz=10.0, clock=clock,
    )
    assert probe.status is ProbeStatus.PRESENT
    assert probe.rate_assessment is RateAssessment.NOMINAL
    assert probe.observed_rate_hz == pytest.approx(10.0)
    assert probe.rate_deficit_fraction == pytest.approx(1.0)
    assert ChannelAttestation.from_probe(probe, channel(CH_A)).origin is EvidenceOrigin.PHYSICAL


def test_ninety_percent_of_nominal_is_degraded_with_the_deficit_quantified() -> None:
    """PS-B's card: "a channel delivering 90% of its nominal rate is reported as
    degraded". The floor sits at 0.95 so that 0.90 is strictly inside it."""

    clock = FakeClock()
    probe = probe_channel(
        channel(CH_A), _stream_reader(clock, spacing_s=10.0 / 90.0, count=90), window_s=10.0,
        expected_rate_hz=10.0, clock=clock,
    )
    assert probe.status is ProbeStatus.DEGRADED
    assert probe.rate_assessment is RateAssessment.DEFICIT
    assert probe.rate_deficit_fraction == pytest.approx(0.9, abs=1e-9)
    assert pf.RATE_DEFICIT_FLOOR > 0.90


def test_seeded_failure_a_burst_then_silence_looks_nominal_by_rate_alone() -> None:
    """The stall detector, and the refutation that motivates it.

    100 messages arrive in the first second of a ten-second window and the channel
    then dies. The average rate is *exactly* nominal, so a rate-only oracle calls
    it PRESENT. The gap detector calls it DEGRADED/STALLED.
    """

    clock = FakeClock()
    probe = probe_channel(
        channel(CH_A),
        _stream_reader(clock, spacing_s=0.01, count=100, drain_to_s=9.0),
        window_s=10.0,
        expected_rate_hz=10.0,
        clock=clock,
    )
    # The rate-only oracle: indistinguishable from a healthy channel.
    assert probe.observed_rate_hz == pytest.approx(10.0)
    assert probe.rate_deficit_fraction == pytest.approx(1.0)
    rate_only_verdict = (
        ProbeStatus.PRESENT
        if pf.RATE_DEFICIT_FLOOR * 10.0 <= probe.observed_rate_hz <= pf.RATE_EXCESS_CEILING * 10.0
        else ProbeStatus.DEGRADED
    )
    assert rate_only_verdict is ProbeStatus.PRESENT
    # The shipped oracle sees the nine-second hole.
    assert probe.rate_assessment is RateAssessment.STALLED
    assert probe.status is ProbeStatus.DEGRADED
    assert probe.max_gap_ns == pytest.approx(9_000_000_000, rel=1e-6)


def test_a_channel_far_above_nominal_is_degraded_because_ps_e_pays_for_it() -> None:
    clock = FakeClock()
    probe = probe_channel(
        channel(CH_A), _stream_reader(clock, spacing_s=1.0 / 30.0, count=300), window_s=10.0,
        expected_rate_hz=10.0, clock=clock,
    )
    assert probe.rate_assessment is RateAssessment.EXCESS
    assert probe.status is ProbeStatus.DEGRADED
    assert probe.rate_deficit_fraction == pytest.approx(3.0, rel=1e-3)


def test_a_window_too_short_to_discriminate_is_unassessed_not_nominal() -> None:
    """One sample in a two-second window cannot distinguish 1 Hz from 0.4 Hz."""

    clock = FakeClock()
    probe = probe_channel(
        channel(CH_SLOW), _stream_reader(clock, spacing_s=1.0, count=2), window_s=2.0,
        expected_rate_hz=1.0, clock=clock,
    )
    assert probe.status is ProbeStatus.PRESENT
    assert probe.rate_assessment is RateAssessment.UNASSESSED_WINDOW_TOO_SHORT
    assert 1.0 * 2.0 < pf.MIN_RATE_SAMPLES


def test_a_configured_channel_with_no_supplied_rate_is_unassessed() -> None:
    """A rate nobody chose is not an expectation (PS-A ``RateKind`` docstring)."""

    assert pf.expected_rate_for(channel(CH_CONFIGURED), {}) is None
    assert pf.expected_rate_for(channel(CH_CONFIGURED), {CH_CONFIGURED: 30.0}) == 30.0
    assert pf.expected_rate_for(channel(CH_A), {}) == 10.0

    clock = FakeClock()
    probe = probe_channel(
        channel(CH_CONFIGURED), _stream_reader(clock, spacing_s=0.1, count=50), window_s=5.0,
        expected_rate_hz=None, clock=clock,
    )
    assert probe.status is ProbeStatus.PRESENT
    assert probe.rate_assessment is RateAssessment.UNASSESSED_NO_EXPECTATION
    assert probe.rate_deficit_fraction is None


def test_a_rate_expectation_on_an_event_driven_channel_is_refused() -> None:
    """Silence on the handheld is normal; a rate would turn it into a fault."""

    with pytest.raises(ProbeContractError, match="EVENT_DRIVEN"):
        pf.expected_rate_for(channel(CH_EVENT), {CH_EVENT: 5.0})
    assert pf.expected_rate_for(channel(CH_EVENT), {}) is None


@pytest.mark.parametrize("bad", [0.0, -1.0, "fast", True, float("nan")])
def test_a_malformed_configured_rate_is_refused_never_defaulted(bad: object) -> None:
    with pytest.raises(ProbeContractError):
        pf.expected_rate_for(channel(CH_CONFIGURED), {CH_CONFIGURED: bad})


def test_a_degraded_critical_channel_is_a_blocking_finding() -> None:
    clock = FakeClock()

    def factory(entry):
        if entry.channel_id == CH_A:
            return _stream_reader(clock, spacing_s=10.0 / 50.0, count=50)
        return _silent_reader(FakeClock())

    report = run_preflight(reader_factory=factory, window_s=10.0, clock=clock)
    degraded = [f for f in report.findings if f.code == "CHANNEL_DEGRADED"]
    assert [f.severity for f in degraded] == [FindingSeverity.BLOCKING]
    assert "observed/expected = 0.500" in degraded[0].detail


# ---------------------------------------------------------------------------
# GATE 5 — the firmware pin is a security control, and it fails closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.1.13", FirmwarePinState.MET),
        ("V1.1.13", FirmwarePinState.MET),
        (" v1.1.14 ", FirmwarePinState.MET),
        ("1.2.0", FirmwarePinState.MET),
        ("2.0.0", FirmwarePinState.MET),
        ("1.1.13.1", FirmwarePinState.MET),
        ("1.1.12", FirmwarePinState.BELOW_PIN),
        ("1.1.9", FirmwarePinState.BELOW_PIN),
        ("1.1", FirmwarePinState.BELOW_PIN),
        ("1.0.99", FirmwarePinState.BELOW_PIN),
        ("0.9.0", FirmwarePinState.BELOW_PIN),
        ("1.1.13-beta", FirmwarePinState.UNPARSEABLE),
        ("latest", FirmwarePinState.UNPARSEABLE),
        ("", FirmwarePinState.UNPARSEABLE),
        ("1", FirmwarePinState.UNPARSEABLE),
    ],
)
def test_firmware_pin_states(version: str, expected: FirmwarePinState) -> None:
    if version == "":
        observation = Observation(
            key="robot.firmware_version",
            value=None,
            kind=EvidenceKind.ABSENT,
            evidence="fixture",
            absence=AbsenceReason.NO_MESSAGE,
        )
        state, _detail = evaluate_firmware_pin(observation)
        assert state is FirmwarePinState.UNVERIFIED
        return
    observation = Observation(
        key="robot.firmware_version",
        value=version,
        kind=EvidenceKind.MACHINE_READ,
        evidence="fixture: go2 reader",
    )
    state, detail = evaluate_firmware_pin(observation)
    assert state is expected, detail


def test_an_unread_firmware_refuses_exactly_like_a_low_one() -> None:
    """Unknown is absent, and absent does not clear a security pin."""

    assert evaluate_firmware_pin(None)[0] is FirmwarePinState.UNVERIFIED
    for state in (FirmwarePinState.UNVERIFIED, FirmwarePinState.BELOW_PIN,
                  FirmwarePinState.UNPARSEABLE):
        assert not state.clears_pin
    assert FirmwarePinState.MET.clears_pin


def test_an_operator_typed_firmware_version_does_not_clear_the_pin() -> None:
    """The gate accepts a machine read off the unit and nothing else."""

    observation = Observation(
        key="robot.firmware_version",
        value="1.1.13",
        kind=EvidenceKind.OPERATOR_OBSERVED,
        evidence="read off the screen by operator Jae, photograph P01",
    )
    state, detail = evaluate_firmware_pin(observation)
    assert state is FirmwarePinState.UNVERIFIED
    assert "not a machine read off the unit" in detail


def test_seeded_failure_a_spoofed_low_firmware_refuses_and_cites_the_cve() -> None:
    """The card's seeded test, end to end through ``run_preflight``.

    A reader is injected that reports 1.1.9 — a version ADR 0002 treats as
    RCE-capable on the unauthenticated robot LAN. The session verdict must be
    REFUSE_CONNECT, the refusal must cite the CVE class, and the exception path
    must raise rather than warn.
    """

    report = run_preflight(
        window_s=0.01,
        robot_reader=_fake_device(
            edition="Go2 EDU", firmware_version="1.1.9", serial="B42-0007"
        ),
        clock=FakeClock(),
    )
    attestation = _attest(report)
    state, _detail = attestation.firmware
    assert state is FirmwarePinState.BELOW_PIN
    assert attestation.verdict is SessionVerdict.REFUSE_CONNECT
    assert attestation.verdict.exit_code == 2

    (refusal,) = attestation.refusals
    for cve in FIRMWARE_CVE_CLASS:
        assert cve in refusal
    assert "RCE-CAPABLE" in refusal
    assert "DO NOT ATTACH" in refusal
    assert "adr/0002-firmware-pin.md" in refusal
    assert "1.1.13" in refusal

    with pytest.raises(FirmwarePinRefusal) as excinfo:
        attestation.raise_for_verdict()
    assert FIRMWARE_CVE_CLASS[0] in str(excinfo.value)

    # The edition and serial were still read and recorded: a refusal is evidence,
    # not an aborted run.
    assert attestation.by_key["robot.edition"].value == "Go2 EDU"
    assert attestation.by_key["robot.serial"].value == "B42-0007"


def test_refutation_the_same_run_at_the_pin_no_longer_refuses_to_connect() -> None:
    """Without this cell the previous one could pass on a tool that always refuses."""

    report = run_preflight(
        window_s=0.01,
        robot_reader=_fake_device(
            edition="Go2 EDU", firmware_version="1.1.13", serial="B42-0007"
        ),
        clock=FakeClock(),
    )
    attestation = _attest(report)
    assert attestation.firmware[0] is FirmwarePinState.MET
    assert attestation.refusals == ()
    assert attestation.verdict is SessionVerdict.DEGRADE_MMP
    assert attestation.verdict.exit_code == 1


def test_a_firmware_reader_that_raises_leaves_the_pin_uncleared() -> None:
    report = run_preflight(
        window_s=0.01,
        robot_reader=_raising_device(RuntimeError("DDS discovery timed out")),
        clock=FakeClock(),
    )
    firmware = report.by_key["robot.firmware_version"]
    assert not firmware.is_known
    assert firmware.absence is AbsenceReason.PROBE_RAISED
    assert _attest(report).verdict is SessionVerdict.REFUSE_CONNECT


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.1.13", (1, 1, 13)),
        ("v1.1.13", (1, 1, 13)),
        ("1.1", (1, 1)),
        ("1.1.13.4", (1, 1, 13, 4)),
        ("1.1.13.4.5", None),
        ("1", None),
        ("1.1.x", None),
        ("-1.1.13", None),
        (None, None),
        (1.113, None),
    ],
)
def test_firmware_version_parsing_refuses_to_guess(text: object, expected) -> None:
    assert parse_firmware_version(text) == expected


# ---------------------------------------------------------------------------
# GATE 6 — the attestation refuses a PHYSICAL claim it cannot back
# ---------------------------------------------------------------------------


def test_physical_origin_requires_a_received_message() -> None:
    present = _probe(CH_A, messages=100, expected=10.0, max_gap_ns=0)
    absent = _probe(CH_B, messages=0, expected=500.0, absence=AbsenceReason.TIMEOUT)
    assert ChannelAttestation.from_probe(present, channel(CH_A)).origin is (
        EvidenceOrigin.PHYSICAL
    )
    assert ChannelAttestation.from_probe(absent, channel(CH_B)).origin is EvidenceOrigin.UNKNOWN


def test_seeded_failure_a_hand_forged_physical_origin_is_reported_not_absorbed() -> None:
    """Hand-edit ``"origin": "physical"`` into the file; the reader recomputes.

    This is the exact shape the card's fifth gate names. ``from_mapping`` throws
    away every derived answer and rebuilds it from the raw counts, so the forgery
    changes nothing — and ``verify_mapping`` says so out loud rather than
    silently correcting it.
    """

    attestation = _attest(_full_report(firmware="1.1.13"))
    record = json.loads(json.dumps(attestation.as_dict()))
    assert record["physical_channels"] == []

    forged = json.loads(json.dumps(record))
    target = next(c for c in forged["channels"] if c["channel_id"] == CH_A)
    assert target["messages_received"] == 0
    target["origin"] = EvidenceOrigin.PHYSICAL.value
    target["status"] = ProbeStatus.PRESENT.value
    forged["physical_channels"] = [CH_A]
    forged["verdict"] = SessionVerdict.GO_RECORD.value

    rebuilt, discrepancies = verify_mapping(forged)
    assert rebuilt.by_channel[CH_A].origin is EvidenceOrigin.UNKNOWN
    assert rebuilt.by_channel[CH_A].status is ProbeStatus.ABSENT
    assert rebuilt.physical_channels == ()
    assert rebuilt.verdict is not SessionVerdict.GO_RECORD
    assert len(discrepancies) == 4
    joined = " | ".join(discrepancies)
    assert "file claims origin='physical'" in joined
    assert "file claims status='present'" in joined
    assert "file claims verdict='go_record'" in joined
    assert "only [] received a message" in joined
    # The digest of the rebuilt record differs from the forged bytes, so the
    # forgery cannot ride into the PS-B sidecar under the honest digest either.
    assert rebuilt.digest() == attestation.digest()


def test_an_untouched_attestation_verifies_clean() -> None:
    """Refutation for the cell above: the checker is not simply always unhappy."""

    attestation = _attest(_full_report(firmware="1.1.13", present_channels=(CH_A,)))
    rebuilt, discrepancies = verify_mapping(json.loads(json.dumps(attestation.as_dict())))
    assert discrepancies == ()
    assert rebuilt.digest() == attestation.digest()
    assert rebuilt.physical_channels == (CH_A,)


def test_a_channel_attestation_may_not_disagree_with_the_matrix() -> None:
    """Criticality and declared presence are the matrix's, not the record's."""

    honest = ChannelAttestation.from_probe(
        _probe(CH_A, messages=1, max_gap_ns=0), channel(CH_A)
    )
    with pytest.raises(AttestationRefused, match="matrix says criticality"):
        ChannelAttestation(**_fields(honest, criticality="opportunistic"))
    with pytest.raises(AttestationRefused, match="matrix says presence"):
        ChannelAttestation(**_fields(honest, declared_presence="awaiting_hardware"))
    with pytest.raises(AttestationRefused, match="not a channel in the PS-A matrix"):
        ChannelAttestation(**_fields(honest, channel_id="go2.invented"))


def test_a_channel_attestation_with_no_messages_must_explain_itself() -> None:
    honest = ChannelAttestation.from_probe(
        _probe(CH_A, messages=0, absence=AbsenceReason.TIMEOUT), channel(CH_A)
    )
    with pytest.raises(AttestationRefused, match="must name why it is absent"):
        ChannelAttestation(**_fields(honest, absence=None))


# ---------------------------------------------------------------------------
# GATE 7 — the attestation is complete, covers the matrix, and is digest-stable
# ---------------------------------------------------------------------------


def test_the_attestation_covers_every_matrix_channel_in_both_directions() -> None:
    attestation = _attest(_full_report(firmware="1.1.13"))
    assert set(attestation.by_channel) == set(channel_ids())
    assert len(attestation.channels) == len(CHANNELS) == 28

    report = _full_report(firmware="1.1.13")
    short = PreflightReport(
        observations=report.observations,
        channels=report.channels[:-1],
        findings=report.findings,
    )
    with pytest.raises(AttestationRefused, match="did not probe every matrix channel"):
        _attest(short)


def test_an_incomplete_or_padded_observation_set_is_refused() -> None:
    """A rig cannot dodge the firmware gate by omitting the firmware field."""

    report = _full_report(firmware="1.1.13")
    without_firmware = PreflightReport(
        observations=tuple(
            o for o in report.observations if o.key != "robot.firmware_version"
        ),
        channels=report.channels,
    )
    with pytest.raises(AttestationRefused, match="robot.firmware_version"):
        _attest(without_firmware)

    padded = PreflightReport(
        observations=(
            *report.observations,
            Observation(
                key="robot.vibes",
                value="good",
                kind=EvidenceKind.MACHINE_READ,
                evidence="fixture",
            ),
        ),
        channels=report.channels,
    )
    with pytest.raises(AttestationRefused, match="not part of"):
        _attest(padded)


def test_the_attestation_carries_every_field_the_card_names() -> None:
    """The card's enumeration, checked key by key against the schema."""

    for key in (
        "robot.edition",
        "robot.firmware_version",
        "robot.builtin_lidar_model",
        "robot.serial",
        "robot.builtin_lidar_serial",
        "d455.serial",
        "l2.serial",
        "robot.nic",
        "robot.dds_domain",
        "d455.firmware_version",
        "l2.firmware_version",
        "orin.jetpack_version",
        "storage.free_bytes",
    ):
        assert key in REQUIRED_OBSERVATIONS
    record = _attest(_full_report(firmware="1.1.13")).as_dict()
    assert record["schema"] == ATTESTATION_SCHEMA
    assert {o["key"] for o in record["observations"]} == set(REQUIRED_OBSERVATIONS)
    assert len(record["channels"]) == 28
    assert record["does_not_prove"] == list(DOES_NOT_PROVE)
    assert record["does_not_prove"], "does_not_prove travels with the evidence"
    assert record["firmware_pin"]["pin"] == "1.1.13"
    assert record["firmware_pin"]["cve_class"] == list(FIRMWARE_CVE_CLASS)


def test_the_digest_is_stable_and_every_field_moves_it() -> None:
    base = _attest(_full_report(firmware="1.1.13"))
    assert base.digest() == _attest(_full_report(firmware="1.1.13")).digest()
    assert base.canonical_json() == _attest(_full_report(firmware="1.1.13")).canonical_json()

    variants = {
        "firmware": _attest(_full_report(firmware="1.1.14")),
        "channel_present": _attest(_full_report(firmware="1.1.13", present_channels=(CH_A,))),
        "free_bytes": _attest(_full_report(firmware="1.1.13", free_bytes=1)),
        "finding": _attest(
            _full_report(
                firmware="1.1.13",
                findings=(Finding("X", FindingSeverity.NOTE, "a new finding"),),
            )
        ),
        "session_label": _attest(_full_report(firmware="1.1.13"), session_label="OTHER"),
        "operator": _attest(_full_report(firmware="1.1.13"), operator="someone-else"),
        "stamp": _attest(_full_report(firmware="1.1.13"), generated_realtime_ns=1),
        "budget": _attest(_full_report(firmware="1.1.13"), required_free_bytes=2**40),
    }
    digests = {name: value.digest() for name, value in variants.items()}
    digests["base"] = base.digest()
    assert len(set(digests.values())) == len(digests), digests


def test_the_digest_survives_a_json_round_trip() -> None:
    """PS-B binds this digest into the sidecar, so it must survive the file."""

    attestation = _attest(_full_report(firmware="1.1.13", present_channels=(CH_A, CH_B)))
    rebuilt = HardwareAttestationV1.from_mapping(json.loads(json.dumps(attestation.as_dict())))
    assert rebuilt.digest() == attestation.digest()
    assert rebuilt.canonical_json() == attestation.canonical_json()
    assert len(attestation.digest()) == 64


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: {**r, "schema": "parcel.hardware.attestation.v2"},
        lambda r: {k: v for k, v in r.items() if k != "channels"},
        lambda r: {**r, "observations": [{"key": "x"}]},
        lambda r: {**r, "generated_realtime_ns": -1},
        lambda r: {**r, "session_label": "  "},
        lambda r: {**r, "operator": ""},
        lambda r: {**r, "required_free_bytes": -5},
    ],
)
def test_a_malformed_attestation_record_is_refused_never_defaulted(mutate) -> None:
    record = json.loads(json.dumps(_attest(_full_report(firmware="1.1.13")).as_dict()))
    with pytest.raises(AttestationRefused):
        HardwareAttestationV1.from_mapping(mutate(record))


def test_the_storage_budget_is_ps_e_s_and_preflight_refuses_to_invent_one() -> None:
    """No budget supplied is not permission to record."""

    present = tuple(
        entry.channel_id
        for entry in CHANNELS
        if entry.criticality.value == "critical"
    )
    no_budget = _attest(_full_report(firmware="1.1.13", present_channels=present))
    assert no_budget.verdict is SessionVerdict.DEGRADE_MMP
    assert any("no storage budget was supplied" in d for d in no_budget.degradations)

    too_small = _attest(
        _full_report(firmware="1.1.13", present_channels=present, free_bytes=2**30),
        required_free_bytes=2**40,
    )
    assert too_small.verdict is SessionVerdict.DEGRADE_MMP
    assert any("below the requested budget" in d for d in too_small.degradations)

    cleared = _attest(
        _full_report(firmware="1.1.13", present_channels=present, free_bytes=4 * 2**40),
        required_free_bytes=2**40,
    )
    assert cleared.verdict is SessionVerdict.GO_RECORD
    assert cleared.verdict.exit_code == 0
    cleared.raise_for_verdict()


def test_a_major_finding_does_not_block_but_is_never_hidden() -> None:
    """An IMPORTANT channel's absence does not block; the operator still sees it.

    PS-A ranks criticality and PS-D does not get a second opinion on it, so an
    absent IMPORTANT channel is not a BLOCKING finding. But "an unrecorded
    channel does not exist", so every MAJOR finding is surfaced as an advisory in
    the attestation and in the printed summary, and the go/no-go decides.
    """

    present = tuple(e.channel_id for e in CHANNELS if e.criticality.value == "critical")
    attestation = _attest(
        _full_report(
            firmware="1.1.13",
            present_channels=present,
            free_bytes=4 * 2**40,
            findings=(
                Finding("CHANNEL_ABSENT", FindingSeverity.MAJOR, "go2.front_camera is absent"),
                Finding("NIC_CONFIG_PLACEHOLDER", FindingSeverity.MAJOR, "robot.yaml:128"),
                Finding("BUILTIN_LIDAR_UNRESOLVED", FindingSeverity.NOTE, "still open"),
            ),
        ),
        required_free_bytes=2**40,
    )
    assert attestation.verdict is SessionVerdict.GO_RECORD
    assert attestation.degradations == ()
    assert len(attestation.advisories) == 2
    assert "go2.front_camera" in attestation.advisories[0]
    assert attestation.as_dict()["advisories"] == list(attestation.advisories)
    summary = attest_mod.format_attestation(attestation)
    assert "ADVISORY (does not block, decide at the go/no-go)" in summary
    assert "NIC_CONFIG_PLACEHOLDER" in summary


def test_a_blocking_finding_degrades_but_never_upgrades_the_verdict() -> None:
    """Worst wins: a firmware refusal is not softened by everything else passing."""

    present = tuple(e.channel_id for e in CHANNELS if e.criticality.value == "critical")
    refused = _attest(
        _full_report(firmware="1.1.9", present_channels=present, free_bytes=4 * 2**40),
        required_free_bytes=2**40,
    )
    assert refused.verdict is SessionVerdict.REFUSE_CONNECT
    assert SessionVerdict.REFUSE_CONNECT.rank < SessionVerdict.DEGRADE_MMP.rank
    assert SessionVerdict.DEGRADE_MMP.rank < SessionVerdict.GO_RECORD.rank

    blocked = _attest(
        _full_report(
            firmware="1.1.13",
            present_channels=present,
            free_bytes=4 * 2**40,
            findings=(Finding("CHANNEL_ABSENT", FindingSeverity.BLOCKING, "critical gone"),),
        ),
        required_free_bytes=2**40,
    )
    assert blocked.verdict is SessionVerdict.DEGRADE_MMP
    with pytest.raises(AttestationRefused, match="may not record"):
        blocked.raise_for_verdict()


# ---------------------------------------------------------------------------
# GATE 8 — observations are evidence-typed, and a document is never evidence
# ---------------------------------------------------------------------------


def test_an_absent_observation_may_not_carry_a_value_and_vice_versa() -> None:
    with pytest.raises(ProbeContractError, match="must not carry a value"):
        Observation(
            key="robot.serial", value="X", kind=EvidenceKind.ABSENT,
            evidence="fixture", absence=AbsenceReason.TIMEOUT,
        )
    with pytest.raises(ProbeContractError, match="must name a reason"):
        Observation(key="robot.serial", value=None, kind=EvidenceKind.ABSENT, evidence="f")
    with pytest.raises(ProbeContractError, match="record it as"):
        Observation(key="robot.serial", value=None, kind=EvidenceKind.MACHINE_READ, evidence="f")
    with pytest.raises(ProbeContractError, match="blank string is not a value"):
        Observation(key="robot.serial", value="  ", kind=EvidenceKind.MACHINE_READ, evidence="f")
    with pytest.raises(ProbeContractError, match="bool is not an observation"):
        Observation(key="robot.serial", value=True, kind=EvidenceKind.MACHINE_READ, evidence="f")
    with pytest.raises(ProbeContractError, match="must state its evidence"):
        Observation(key="robot.serial", value="X", kind=EvidenceKind.MACHINE_READ, evidence=" ")


def test_an_operator_observation_must_name_the_operator_and_the_photograph() -> None:
    """An unattributed label reading is not evidence a session can rely on."""

    with pytest.raises(ProbeContractError, match="must name the operator"):
        Observation(
            key="robot.builtin_lidar_model", value="L2",
            kind=EvidenceKind.OPERATOR_OBSERVED, evidence="somebody said so",
        )
    good = OperatorObservation(value="L2", operator="Jae", photo_id="P02").as_observation(
        "robot.builtin_lidar_model"
    )
    assert good.kind is EvidenceKind.OPERATOR_OBSERVED
    assert "P02" in good.evidence and "Jae" in good.evidence

    with pytest.raises(ProbeContractError, match="PHOTO_LIST"):
        OperatorObservation(value="L2", operator="Jae", photo_id="photo-2")
    with pytest.raises(ProbeContractError, match="must be non-empty"):
        OperatorObservation(value="L2", operator=" ", photo_id="P02")


# ---------------------------------------------------------------------------
# GATE 9 — the built-in LiDAR contradiction is resolved empirically
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("read_model", "wrong_document_fragment", "right_document_fragment"),
    [
        ("Unitree L2 (built-in)", "P5_PROCUREMENT_BOM", "unitree product page"),
        ("L1", "unitree product page", "P5_PROCUREMENT_BOM"),
    ],
)
def test_reading_the_model_off_the_unit_names_the_wrong_document(
    read_model: str, wrong_document_fragment: str, right_document_fragment: str
) -> None:
    """The card's requirement: resolve it empirically and record which doc was wrong."""

    observations, findings = probe_builtin_lidar(
        _fake_device(model=read_model, serial="L2-0001")
    )
    by_key = {o.key: o for o in observations}
    assert by_key["robot.builtin_lidar_model"].value == read_model
    verdict = by_key["robot.builtin_lidar_document_verdict"]
    assert verdict.is_known
    assert verdict.kind is EvidenceKind.DERIVED
    assert f"{right_document_fragment}" in verdict.value
    assert "CONFIRMED" in verdict.value and "WRONG" in verdict.value

    wrong = [f for f in findings if f.code == "DOCUMENT_WRONG"]
    assert len(wrong) == 1
    assert wrong_document_fragment in wrong[0].detail
    assert right_document_fragment not in wrong[0].detail


def test_an_unread_lidar_leaves_the_contradiction_open_rather_than_picking_a_side() -> None:
    observations, findings = probe_builtin_lidar()
    by_key = {o.key: o for o in observations}
    assert not by_key["robot.builtin_lidar_model"].is_known
    verdict = by_key["robot.builtin_lidar_document_verdict"]
    assert not verdict.is_known
    assert verdict.absence is AbsenceReason.NO_OPERATOR_OBSERVATION
    assert [f.code for f in findings] == ["BUILTIN_LIDAR_UNRESOLVED"]
    assert "Neither document is evidence" in findings[0].detail
    assert [f.code for f in findings if f.code == "DOCUMENT_WRONG"] == []


def test_an_operator_label_reading_resolves_the_contradiction() -> None:
    observations, findings = probe_builtin_lidar(
        operator=OperatorObservation(value="L2", operator="Jae", photo_id="P02")
    )
    by_key = {o.key: o for o in observations}
    model = by_key["robot.builtin_lidar_model"]
    assert model.value == "L2"
    assert model.kind is EvidenceKind.OPERATOR_OBSERVED
    assert "P02" in model.evidence
    wrong = next(f for f in findings if f.code == "DOCUMENT_WRONG")
    assert "P5_PROCUREMENT_BOM" in wrong.detail


def test_an_unreadable_model_string_does_not_resolve_anything() -> None:
    observations, findings = probe_builtin_lidar(_fake_device(model="???", serial="x"))
    by_key = {o.key: o for o in observations}
    assert by_key["robot.builtin_lidar_model"].value == "???"
    assert by_key["robot.builtin_lidar_document_verdict"].absence is AbsenceReason.UNPARSEABLE
    assert [f.code for f in findings] == ["BUILTIN_LIDAR_UNRESOLVED"]


# ---------------------------------------------------------------------------
# GATE 10 — the config placeholder is detected, never trusted
# ---------------------------------------------------------------------------


def test_the_shipped_config_placeholder_is_detected_and_the_nic_is_not_trusted() -> None:
    """``configs/robot.yaml:128`` still says "replace with the dedicated robot
    Ethernet NIC". A preflight that trusted it would attest a NIC nobody chose."""

    scalars = {s.path: s for s in scan_config_scalars()}
    placeholder = scalars["control.unitree_sport.interface"]
    assert placeholder.lineno == 128
    assert placeholder.value == "enp3s0"
    assert "replace with" in placeholder.comment
    assert placeholder.looks_like_placeholder

    observations, findings = probe_network(net_class_dir="/nonexistent-net-class")
    by_key = {o.key: o for o in observations}
    assert not by_key["robot.nic"].is_known
    codes = [f.code for f in findings]
    assert "NIC_CONFIG_PLACEHOLDER" in codes
    detail = next(f for f in findings if f.code == "NIC_CONFIG_PLACEHOLDER").detail
    assert "configs/robot.yaml:128" in detail
    assert "does not trust it" in detail


def test_the_simulator_loopback_can_never_be_promoted_into_the_robot_nic() -> None:
    """The scan fails closed: a mis-scan loses a NIC, it never invents one."""

    scalars = {s.path: s for s in scan_config_scalars()}
    assert scalars["wifi_cards.simulator.interface"].value == "lo"
    assert "wifi_cards.simulator.interface" not in pf.ROBOT_NIC_CONFIG_PATHS
    observations, _findings = probe_network(net_class_dir="/nonexistent-net-class")
    assert {o.key: o.value for o in observations}["robot.nic"] != "lo"


def test_a_real_nic_that_exists_is_reported_and_a_missing_one_is_not(tmp_path: Path) -> None:
    config = tmp_path / "robot.yaml"
    config.write_text(
        "control:\n"
        "  unitree_sport:\n"
        "    interface: eth9\n"
        "    domain_id: 7\n"
        "wifi_cards:\n"
        "  robot:\n"
        "    interface: eth9\n"
        "    ros_domain_id: 7\n",
        encoding="utf-8",
    )
    net = tmp_path / "net"
    (net / "eth9").mkdir(parents=True)
    observations, findings = probe_network(
        config_path=config, net_class_dir=net, environ={"ROS_DOMAIN_ID": "7"}
    )
    by_key = {o.key: o for o in observations}
    assert by_key["robot.nic"].value == "eth9"
    assert by_key["robot.nic"].kind is EvidenceKind.MACHINE_READ
    assert by_key["robot.dds_domain"].value == 7
    assert [f.code for f in findings] == []

    # Seeded: the same config on a host where the NIC does not exist. This is
    # exactly what control/unitree_sport.py:50-53 hard-fails on.
    observations, _ = probe_network(
        config_path=config, net_class_dir=tmp_path / "empty", environ={"ROS_DOMAIN_ID": "7"}
    )
    nic = {o.key: o for o in observations}["robot.nic"]
    assert not nic.is_known
    assert nic.absence is AbsenceReason.DEVICE_NODE_MISSING
    assert "unitree_sport.py:50-53" in nic.remedy


def test_two_disagreeing_nic_declarations_are_trusted_neither(tmp_path: Path) -> None:
    config = tmp_path / "robot.yaml"
    config.write_text(
        "control:\n  unitree_sport:\n    interface: eth0\n"
        "wifi_cards:\n  robot:\n    interface: eth1\n",
        encoding="utf-8",
    )
    observations, findings = probe_network(config_path=config, net_class_dir=tmp_path, environ={})
    nic = {o.key: o for o in observations}["robot.nic"]
    assert not nic.is_known
    assert nic.absence is AbsenceReason.CONFIG_AMBIGUOUS
    assert "NIC_CONFIG_DISAGREEMENT" in [f.code for f in findings]


def test_the_dds_domain_the_process_would_actually_join(tmp_path: Path) -> None:
    """``ROS_DOMAIN_ID`` is what a participant really uses; a config that
    disagrees is a trap, so the disagreement refuses instead of preferring one."""

    config = tmp_path / "robot.yaml"
    config.write_text(
        "control:\n  unitree_sport:\n    interface: eth0\n    domain_id: 0\n", encoding="utf-8"
    )
    agreeing = {
        o.key: o
        for o in probe_network(
            config_path=config, net_class_dir=tmp_path, environ={"ROS_DOMAIN_ID": "0"}
        )[0]
    }
    assert agreeing["robot.dds_domain"].value == 0

    disagreeing = {
        o.key: o
        for o in probe_network(
            config_path=config, net_class_dir=tmp_path, environ={"ROS_DOMAIN_ID": "42"}
        )[0]
    }
    assert not disagreeing["robot.dds_domain"].is_known
    assert disagreeing["robot.dds_domain"].absence is AbsenceReason.CONFIG_AMBIGUOUS

    # A non-numeric ROS_DOMAIN_ID is UNPARSEABLE rather than a disagreement: a
    # participant cannot join a domain that is not a number, so ruling it
    # "ambiguous" would understate a broken environment.
    garbage = {
        o.key: o
        for o in probe_network(
            config_path=config, net_class_dir=tmp_path, environ={"ROS_DOMAIN_ID": "0x1f"}
        )[0]
    }
    assert garbage["robot.dds_domain"].absence is AbsenceReason.UNPARSEABLE
    assert "0x1f" in garbage["robot.dds_domain"].evidence

    unset = {
        o.key: o
        for o in probe_network(
            config_path=tmp_path / "missing.yaml", net_class_dir=tmp_path, environ={}
        )[0]
    }
    assert unset["robot.dds_domain"].absence is AbsenceReason.NOT_ATTEMPTED


# ---------------------------------------------------------------------------
# GATE 11 — JetPack is derived through a declared table and refuses to guess
# ---------------------------------------------------------------------------


def test_jetpack_is_derived_from_l4t_and_an_unknown_release_is_absent(tmp_path: Path) -> None:
    known = tmp_path / "nv_tegra_release"
    known.write_text(
        "# R36 (release), REVISION: 4.3, GCID: 38968081, BOARD: generic, EABI: aarch64\n",
        encoding="utf-8",
    )
    model = tmp_path / "model"
    model.write_bytes(b"NVIDIA Jetson Orin NX Engineering Reference Developer Kit\x00")
    by_key = {
        o.key: o for o in probe_jetpack(tegra_release=known, device_tree_model=model)
    }
    assert by_key["orin.l4t_release"].value == "L4T R36.4.3"
    assert by_key["orin.l4t_release"].kind is EvidenceKind.MACHINE_READ
    assert by_key["orin.jetpack_version"].value == "JetPack 6.2"
    assert by_key["orin.jetpack_version"].kind is EvidenceKind.DERIVED
    assert "declared mapping, not a measurement" in by_key["orin.jetpack_version"].evidence
    assert "Orin NX" in by_key["orin.board_model"].value
    assert "\x00" not in by_key["orin.board_model"].value

    unknown = tmp_path / "future"
    unknown.write_text("# R99 (release), REVISION: 9.9, GCID: 1\n", encoding="utf-8")
    by_key = {o.key: o for o in probe_jetpack(tegra_release=unknown, device_tree_model=model)}
    assert by_key["orin.l4t_release"].value == "L4T R99.9.9"
    assert not by_key["orin.jetpack_version"].is_known
    assert "refusing to guess" in by_key["orin.jetpack_version"].evidence


def test_a_non_jetson_host_reports_absent_rather_than_failing(tmp_path: Path) -> None:
    by_key = {
        o.key: o
        for o in probe_jetpack(
            tegra_release=tmp_path / "nope", device_tree_model=tmp_path / "nope2"
        )
    }
    for key in ("orin.l4t_release", "orin.jetpack_version", "orin.board_model"):
        assert not by_key[key].is_known
        assert by_key[key].absence is AbsenceReason.NOT_A_JETSON

    unparseable = tmp_path / "garbled"
    unparseable.write_text("something else entirely\n", encoding="utf-8")
    by_key = {
        o.key: o
        for o in probe_jetpack(tegra_release=unparseable, device_tree_model=tmp_path / "nope")
    }
    assert by_key["orin.l4t_release"].absence is AbsenceReason.UNPARSEABLE
    assert by_key["orin.jetpack_version"].absence is AbsenceReason.UNPARSEABLE


# ---------------------------------------------------------------------------
# GATE 12 — a useful, honest, traceback-free run on this dev box
# ---------------------------------------------------------------------------


def test_preflight_runs_to_a_complete_absent_report_with_no_hardware() -> None:
    """The card's fourth gate, on the box it was written on."""

    report = run_preflight(window_s=0.01, clock=FakeClock())
    assert len(report.channels) == len(CHANNELS) == 28
    assert set(report.by_channel) == set(channel_ids())
    assert {p.status for p in report.channels} == {ProbeStatus.ABSENT}
    assert all(p.absence is not None for p in report.channels)
    assert all(p.evidence.strip() for p in report.channels)
    # Every required observation is present in the record, as a value or an
    # explicit absence — nothing is simply missing.
    assert set(REQUIRED_OBSERVATIONS) <= set(report.by_key)
    assert report.by_key["storage.free_bytes"].is_known
    assert [f.severity for f in report.findings] == sorted(
        (f.severity for f in report.findings), key=lambda s: s.rank
    )
    assert any(f.severity is FindingSeverity.BLOCKING for f in report.findings)


def test_the_dev_box_absences_each_name_a_remedy_and_never_suggest_arming(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A refusal an operator cannot act on is a refusal they will work around —
    and the one workaround this project must never take is installing the vendor
    SDK into ``.parcel/``, so the remedy says so."""

    report = run_preflight(window_s=0.01, clock=FakeClock())
    dds_probe = report.by_channel[CH_A]
    assert dds_probe.absence is AbsenceReason.DEPENDENCY_MISSING
    assert "Do NOT pip install the vendor SDK into .parcel/" in dds_probe.remedy
    assert "unitree_sdk2py" in dds_probe.absence_detail

    text = pf.format_report(report)
    assert "Traceback" not in text
    assert "PRESENT" not in text.split("CHANNELS")[1].split("FINDINGS")[0].replace(
        "critical", ""
    ).replace("present=0", "")
    assert "absent=28" in text


def test_preflight_main_exits_non_zero_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = pf.main(["--window", "0.01"])
    captured = capsys.readouterr()
    assert code == 1
    assert "Traceback" not in captured.out + captured.err
    assert "PARCEL CAPTURE PREFLIGHT" in captured.out
    assert "NOT READY" in captured.err


def test_attest_main_exits_two_and_refuses_to_connect_without_a_robot(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out = tmp_path / "attestation.json"
    code = attest_mod.main(
        ["--window", "0.01", "--session-label", "P5-DRY-TEST", "--attesting-operator",
         "fixture", "--out", str(out)]
    )
    captured = capsys.readouterr()
    assert code == 2, captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err
    assert "VERDICT: REFUSE_CONNECT" in captured.out
    for cve in FIRMWARE_CVE_CLASS:
        assert cve in captured.out

    record = json.loads(out.read_text(encoding="utf-8"))
    rebuilt, discrepancies = verify_mapping(record)
    assert discrepancies == ()
    assert rebuilt.verdict is SessionVerdict.REFUSE_CONNECT
    assert rebuilt.physical_channels == ()
    assert all(c["origin"] == EvidenceOrigin.UNKNOWN.value for c in record["channels"])


@pytest.mark.parametrize(
    "argv",
    [
        ["--rate", "no-equals-sign"],
        ["--rate", "d455.color=fast"],
        ["--rate", "d455.color=-3"],
        ["--builtin-lidar-model", "L2"],
        ["--builtin-lidar-model", "L2", "--operator", "Jae"],
        ["--builtin-lidar-model", "L2", "--operator", "Jae", "--photo", "nonsense"],
    ],
)
def test_malformed_cli_input_is_a_refusal_never_a_traceback(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = pf.main([*argv, "--window", "0.01"])
    captured = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in captured.out + captured.err
    assert "PREFLIGHT REFUSED" in captured.err


# ---------------------------------------------------------------------------
# GATE 13 — nothing here arms anything, and nothing imports a vendor SDK
# ---------------------------------------------------------------------------


_FORBIDDEN_SYMBOLS = frozenset(
    {
        "create_publisher",
        "Publisher",
        "ControlManager",
        "create_control_manager",
        "set_target",
        "acquire_lease",
        "release_lease",
        "MotionClient",
        "SportClient",
        "publish",
    }
)


def test_no_symbol_in_either_module_can_reach_a_motion_surface() -> None:
    """Read-only by import graph and by symbol, as PS-A's package is.

    The negative control matters: ``wirelesscontroller`` and ``unilidar_sdk2``
    are legitimate vendor *sensor* names and the scan must not fire on them.
    """

    for path in MODULE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in _FORBIDDEN_SYMBOLS, f"{path.name}: {node.id}"
            if isinstance(node, ast.Attribute):
                assert node.attr not in _FORBIDDEN_SYMBOLS, f"{path.name}: .{node.attr}"
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                assert node.name not in _FORBIDDEN_SYMBOLS, f"{path.name}: def {node.name}"
    # Negative control: the scan is not simply vacuous on vendor vocabulary.
    control = ast.parse("wirelesscontroller = unilidar_sdk2 = utlidar_cloud = 1\n")
    for node in ast.walk(control):
        if isinstance(node, ast.Name):
            assert node.id not in _FORBIDDEN_SYMBOLS


def test_neither_module_imports_a_vendor_sdk_or_the_runtime() -> None:
    """The strongest motion guarantee is that the SDK is absent; keep it absent."""

    forbidden_roots = {
        "rclpy",
        "cyclonedds",
        "unitree_sdk2py",
        "unitree_lidar_sdk",
        "unilidar_sdk2",
        "pyrealsense2",
    }
    for path in MODULE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".")[0]}
            else:
                continue
            assert not roots & forbidden_roots, f"{path.name} imports {roots & forbidden_roots}"
            assert "runtime" not in roots
            assert "navigation" not in roots


def test_a_full_preflight_run_never_imports_a_vendor_sdk() -> None:
    """Measured in a subprocess, not reasoned about: run the whole thing and look.

    Card ENV-1 kept this property WORD FOR WORD and made the code earn it
    again. ``pyrealsense2`` has been installed in ``.parcel`` since 2026-08-22
    (P1-A, for the desk-camera venue), and on the day it landed this assertion
    went red with ``VENDOR ['pyrealsense2', 'pyrealsense2.pyrealsense2']``: the
    D455 probe reached ``importlib.import_module`` because its only gate was
    "is the module importable", which had just become yes.

    The property is a good one and it survives, because presence is two facts.
    ``RealSenseIngest`` now checks the ``/dev`` census — a filesystem lookup,
    no import — BEFORE it imports, so a box with the wheel and no camera
    refuses ``device_node_missing`` without the SDK ever entering
    ``sys.modules``. The second half of this test pins the reason, so the
    property can never again be satisfied by the probe simply not running.

    Card ENV-1b: the reason it pins depends on the venv. ``.parcel`` carries
    P1-A's wheel; a venv built from ``pip install .[dev]`` does not, because the
    ``dev`` extra cannot declare ``pyrealsense2`` (no aarch64 wheel — it would
    break the install on the Orin). So the module arm is asserted instead of
    skipped: without the wheel every D455 row must read ``dependency_missing``
    naming ``pyrealsense2``, and ``VENDOR []`` — the property itself — holds
    unbranched in both venvs.
    """

    import importlib.util

    wheel_installed = importlib.util.find_spec("pyrealsense2") is not None

    script = (
        f"import sys;"
        f"sys.path.insert(0, {str(REPO)!r});"
        f"from scripts.parcel_capture.attest import main;"
        f"code = main(['--window', '0.01']);"
        f"vendor = sorted(m for m in sys.modules"
        f" if m.split('.')[0] in {{'rclpy','cyclonedds','unitree_sdk2py','pyrealsense2',"
        f"'unitree_lidar_sdk','unilidar_sdk2','mcap'}});"
        f"print('EXIT', code);"
        f"print('VENDOR', vendor)"
    )
    proc = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    assert "EXIT 2" in proc.stdout
    assert "VENDOR []" in proc.stdout

    # The D455 rows must be ABSENT for a NAMED reason, actionable — not ABSENT
    # because a probe crashed. Before card ENV-1 they read "probe_raised —
    # RuntimeError: stop() cannot be called before start()", which names the
    # wrong call, no device, and no remedy.
    #
    # Card ENV-1b: ALL SIX rows, not four. The product emits accel and gyro too
    # (they are `motion` streams, a different branch of `stream_selection`), and
    # pinning four of six left the two that take the other branch unguarded.
    for channel_id in (
        "d455.color",
        "d455.depth",
        "d455.infra1",
        "d455.infra2",
        "d455.accel",
        "d455.gyro",
    ):
        line = next(
            (
                item
                for item in proc.stdout.splitlines()
                if f"CHANNEL_ABSENT: {channel_id} " in item
            ),
            None,
        )
        assert line is not None, f"{channel_id} produced no absence finding at all"
        assert "probe_raised" not in line, line
        if wheel_installed:
            assert "device_node_missing" in line, line
            assert "/dev/video*" in line, line
            assert "USB 3 (BLUE)" in line, line
        else:
            # A fresh `.[dev]` venv stops one gate earlier, and says so by name.
            assert "dependency_missing" in line, line
            assert "pyrealsense2" in line, line

    # The dog's rows still say dependency_missing: that SDK really is absent,
    # and collapsing the two reasons would cost a session-day of debugging.
    dog = next(
        item
        for item in proc.stdout.splitlines()
        if "CHANNEL_ABSENT: go2.lowstate " in item
    )
    assert "dependency_missing" in dog and "rclpy" in dog


def test_the_channel_enumeration_is_ps_a_s_and_this_card_keeps_no_second_list() -> None:
    """A second list is how a channel silently stops being recorded."""

    probes = probe_all_channels(window_s=0.01, clock=FakeClock())
    assert tuple(p.channel_id for p in probes) == channel_ids()

    known_ids = set(CHANNELS_BY_ID)
    for path in MODULE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                assert node.value not in known_ids, (
                    f"{path.name} hard-codes channel id {node.value!r}; the enumeration "
                    f"lives in parcel_robot.capture.CHANNELS"
                )


# ===========================================================================
# Card PS-J (corrective tranche PS-2) — physical plausibility
#
# The defect: preflight ruled a channel PRESENT purely on receipt count.
# `grep -n "9.81|plausib|gravity|magnitude" preflight.py attest.py` returned
# NOTHING before this card, so `utlidar/imu` emitting -2.17e24 m/s^2 — two
# independent unfixed field reports of exactly that — was attested HEALTHY.
#
# Every gate below has a seeded failure, and the headline one uses the 1e24
# value verbatim.
# ===========================================================================

#: The channel with two independent unfixed field reports of ~-2.17e24 m/s^2.
CH_IMU = "go2.utlidar.imu"
#: One message carrying an IMU, a battery and four foot-force counts.
CH_LOWSTATE = "go2.lowstate"
#: The D455's BMI055, split by pyrealsense2 into two motion streams.
CH_ACCEL = "d455.accel"
CH_GYRO = "d455.gyro"
#: The add-on L2's own IMU, a fourth independent witness.
CH_L2_IMU = "l2.imu"
#: A colour frame, for the decode/degeneracy rules.
CH_CAMERA = "d455.color"

#: The value from the field reports, verbatim.
FIELD_REPORT_ACCEL_MPS2 = -2.17e24

REST = RestPeriod(attested_by="fixture-operator", note="dog on the bench, hands off")


def _measured_reader(clock: FakeClock, *, count: int, spacing_s: float, make):
    """A reader that yields receipts carrying physical measurements."""

    def reader(entry, window_s: float) -> Iterator[SampleReceipt]:
        for index in range(count):
            clock.advance(spacing_s)
            yield SampleReceipt(
                channel_id=entry.channel_id,
                host_monotonic_ns=clock(),
                payload_bytes=64,
                measurements=make(index),
            )

    return reader


def _measure(
    channel_id: str,
    make,
    *,
    count: int = 20,
    spacing_s: float = 0.01,
    window_s: float = 10.0,
    rest: RestPeriod | None = None,
) -> ChannelProbe:
    """Probe one channel with a reader that measures, and return the probe."""

    clock = FakeClock()
    return probe_channel(
        channel(channel_id),
        _measured_reader(clock, count=count, spacing_s=spacing_s, make=make),
        window_s=window_s,
        clock=clock,
        rest=rest,
    )


def _imu(accel=None, gyro=None):
    return lambda index: (ImuSample(accel_mps2=accel, gyro_rps=gyro),)


def _rule(probe: ChannelProbe, rule: str) -> PlausibilityCheck:
    ruling = probe.plausibility
    assert ruling is not None, f"{probe.channel_id}: no plausibility ruling at all"
    found = ruling.check(rule)
    assert found is not None, f"{rule} not among {[c.rule for c in ruling.checks]}"
    return found


def _report_with(
    *probes: ChannelProbe, rest: RestPeriod | None = None, **kwargs
) -> PreflightReport:
    """A complete matrix report with specific probes substituted in."""

    base = _full_report(**kwargs)
    replacements = {probe.channel_id: probe for probe in probes}
    return PreflightReport(
        observations=base.observations,
        channels=tuple(replacements.get(p.channel_id, p) for p in base.channels),
        findings=base.findings,
        rest=rest,
    )


def _receipt_count_health(probe: ChannelProbe) -> str:
    """TODAY'S ORACLE, re-implemented: health from the receipt count alone.

    This is what shipped before PS-J. It is kept in the test so the refutation
    is a measurement rather than an assertion about history.
    """

    return "HEALTHY" if probe.messages_received > 0 else "ABSENT"


# ---------------------------------------------------------------------------
# GATE 14 — the 1e24 accelerometer, verbatim
# ---------------------------------------------------------------------------


def test_seeded_failure_the_1e24_accelerometer_is_caught_and_the_old_oracle_misses_it() -> None:
    """The card's headline case, with the field-reported value verbatim.

    Two things are proved at once: the new layer FAILs it, and the oracle that
    shipped yesterday — receipt count — calls the identical probe HEALTHY.
    """

    probe = _measure(CH_IMU, _imu(accel=(FIELD_REPORT_ACCEL_MPS2, 0.13, 9.79), gyro=(0.0, 0.0, 0.0)))

    # The refutation: yesterday's oracle sees nothing wrong.
    assert _receipt_count_health(probe) == "HEALTHY"
    assert probe.messages_received == 20

    # The new oracle does.
    assert probe.plausibility_verdict is PlausibilityVerdict.FAIL
    check = _rule(probe, "imu.accel_within_sensor_range")
    assert check.verdict is PlausibilityVerdict.FAIL
    assert "2.17e+24" in check.detail
    assert str(ACCEL_SENSOR_CEILING_MPS2) in check.detail


def test_the_implausible_channel_is_still_present_physical_and_recorded() -> None:
    """A failed plausibility check must never silence a recording.

    The card is explicit that a suspect channel is still evidence. So the FAIL
    changes the verdict *attached* to the channel and nothing about whether it is
    recorded: status stays PRESENT, origin stays PHYSICAL, and the session
    verdict is not degraded by it.
    """

    probe = _measure(CH_IMU, _imu(accel=(FIELD_REPORT_ACCEL_MPS2, 0.0, 0.0)))
    assert probe.status is ProbeStatus.PRESENT
    entry = ChannelAttestation.from_probe(probe, channel(CH_IMU))
    assert entry.origin is EvidenceOrigin.PHYSICAL
    assert entry.status is ProbeStatus.PRESENT
    assert entry.plausibility_verdict is PlausibilityVerdict.FAIL

    present = tuple(e.channel_id for e in CHANNELS if e.criticality.value == "critical")
    attestation = _attest(
        _report_with(
            probe,
            firmware="1.1.13",
            present_channels=present,
            free_bytes=4 * 2**40,
            findings=pf._plausibility_findings((probe,), CHANNELS),
        ),
        required_free_bytes=2**40,
    )
    assert attestation.verdict is SessionVerdict.GO_RECORD, attestation.degradations
    assert attestation.implausible_channels == (CH_IMU,)
    assert any("CHANNEL_IMPLAUSIBLE" in advisory for advisory in attestation.advisories)


def test_no_plausibility_finding_may_ever_be_blocking() -> None:
    """BLOCKING is the *record nothing* lane, and this layer may not reach it."""

    seeds = (
        _measure(CH_IMU, _imu(accel=(FIELD_REPORT_ACCEL_MPS2, 0.0, 0.0))),
        _measure(
            CH_A,
            lambda i: (PointCloudSample(point_count=0, field_names=("x", "y", "z")),),
        ),
        _measure(
            CH_CAMERA,
            lambda i: (
                ImageSample(
                    width=848,
                    height=480,
                    decoded=True,
                    min_level=0.0,
                    max_level=0.0,
                    mean_level=0.0,
                    zero_fraction=1.0,
                    saturated_fraction=0.0,
                ),
            ),
        ),
    )
    findings = pf._plausibility_findings(seeds, CHANNELS)
    assert findings, "the seeds really did produce findings"
    assert all(f.severity is not FindingSeverity.BLOCKING for f in findings), [
        (f.code, f.severity.value) for f in findings
    ]
    assert {f.code for f in findings} >= {"CHANNEL_IMPLAUSIBLE"}


# ---------------------------------------------------------------------------
# GATE 15 — the IMU rules, and the four independent units
# ---------------------------------------------------------------------------


def test_an_imu_at_rest_within_the_band_passes() -> None:
    probe = _measure(
        CH_IMU, _imu(accel=(0.02, -0.05, 9.80), gyro=(0.001, -0.002, 0.0)), rest=REST
    )
    assert probe.plausibility_verdict is PlausibilityVerdict.PASS
    assert _rule(probe, "imu.accel_magnitude_at_rest").verdict is PlausibilityVerdict.PASS
    assert _rule(probe, "imu.gyro_magnitude_at_rest").verdict is PlausibilityVerdict.PASS
    assert "fixture-operator" in _rule(probe, "imu.accel_magnitude_at_rest").detail


@pytest.mark.parametrize(
    ("accel", "rule"),
    [
        ((0.0, 0.0, 7.0), "imu.accel_magnitude_at_rest"),
        ((0.0, 0.0, 12.5), "imu.accel_magnitude_at_rest"),
        ((0.0, 0.0, 0.0), "imu.accel_magnitude_at_rest"),
        ((float("nan"), 0.0, 9.81), "imu.accel_finite"),
        ((float("inf"), 0.0, 9.81), "imu.accel_finite"),
        ((FIELD_REPORT_ACCEL_MPS2, 0.0, 0.0), "imu.accel_within_sensor_range"),
    ],
)
def test_seeded_failure_each_bad_accelerometer_is_caught_by_its_own_rule(accel, rule) -> None:
    probe = _measure(CH_IMU, _imu(accel=accel, gyro=(0.0, 0.0, 0.0)), rest=REST)
    assert _rule(probe, rule).verdict is PlausibilityVerdict.FAIL
    assert probe.plausibility_verdict is PlausibilityVerdict.FAIL


@pytest.mark.parametrize(
    ("gyro", "rule"),
    [
        ((0.0, 0.0, 0.4), "imu.gyro_magnitude_at_rest"),
        ((float("nan"), 0.0, 0.0), "imu.gyro_finite"),
        ((1e9, 0.0, 0.0), "imu.gyro_within_sensor_range"),
    ],
)
def test_seeded_failure_each_bad_gyroscope_is_caught_by_its_own_rule(gyro, rule) -> None:
    probe = _measure(CH_IMU, _imu(accel=(0.0, 0.0, 9.81), gyro=gyro), rest=REST)
    assert _rule(probe, rule).verdict is PlausibilityVerdict.FAIL
    assert probe.plausibility_verdict is PlausibilityVerdict.FAIL


def test_the_gravity_band_is_the_cards_band_and_not_a_looser_one() -> None:
    """A band nobody can point at is a band that drifts. Pin the numbers."""

    assert GRAVITY_MPS2 == pytest.approx(9.80665)
    assert pf.ACCEL_REST_TOLERANCE_MPS2 == 1.0
    assert GYRO_REST_CEILING_RPS == 0.05
    inside = _measure(CH_IMU, _imu(accel=(0.0, 0.0, GRAVITY_MPS2 + 0.99)), rest=REST)
    outside = _measure(CH_IMU, _imu(accel=(0.0, 0.0, GRAVITY_MPS2 + 1.01)), rest=REST)
    assert _rule(inside, "imu.accel_magnitude_at_rest").verdict is PlausibilityVerdict.PASS
    assert _rule(outside, "imu.accel_magnitude_at_rest").verdict is PlausibilityVerdict.FAIL


def test_without_a_declared_rest_period_the_rest_rules_are_unknown_never_pass() -> None:
    """UNKNOWN when we cannot judge — and a perfect reading does not buy a PASS."""

    probe = _measure(CH_IMU, _imu(accel=(0.0, 0.0, 9.81), gyro=(0.0, 0.0, 0.0)))
    assert _rule(probe, "imu.accel_magnitude_at_rest").verdict is PlausibilityVerdict.UNKNOWN
    assert _rule(probe, "imu.gyro_magnitude_at_rest").verdict is PlausibilityVerdict.UNKNOWN
    assert "--at-rest" in _rule(probe, "imu.accel_magnitude_at_rest").detail
    assert probe.plausibility_verdict is PlausibilityVerdict.UNKNOWN
    # ...while the rest-INDEPENDENT rules still ran and still passed.
    assert _rule(probe, "imu.accel_finite").verdict is PlausibilityVerdict.PASS
    assert _rule(probe, "imu.accel_within_sensor_range").verdict is PlausibilityVerdict.PASS


def test_the_1e24_case_is_caught_without_any_rest_period_at_all() -> None:
    """The sensor-range rule is what makes the field-report case catchable in
    any take. If it needed a rest period, a moving take would hide it."""

    probe = _measure(CH_IMU, _imu(accel=(FIELD_REPORT_ACCEL_MPS2, 0.0, 0.0)))
    assert probe.plausibility.check("imu.accel_magnitude_at_rest").verdict is (
        PlausibilityVerdict.UNKNOWN
    )
    assert _rule(probe, "imu.accel_within_sensor_range").verdict is PlausibilityVerdict.FAIL
    assert probe.plausibility_verdict is PlausibilityVerdict.FAIL


def test_a_split_motion_stream_is_not_penalised_for_its_missing_half() -> None:
    """pyrealsense2 delivers accel and gyro separately; a full IMU is one stream."""

    assert imu_stream_kind(channel(CH_ACCEL)) is ImuStreamKind.ACCEL_ONLY
    assert imu_stream_kind(channel(CH_GYRO)) is ImuStreamKind.GYRO_ONLY
    assert imu_stream_kind(channel(CH_IMU)) is ImuStreamKind.FULL

    accel_only = _measure(CH_ACCEL, _imu(accel=(0.0, 0.0, 9.81)), rest=REST)
    assert accel_only.plausibility.check("imu.gyro_present") is None
    assert accel_only.plausibility_verdict is PlausibilityVerdict.PASS

    # A FULL stream that omits its gyro is UNKNOWN, not PASS: that is a reader
    # dropping half an IMU, and it must not read as health.
    half = _measure(CH_IMU, _imu(accel=(0.0, 0.0, 9.81)), rest=REST)
    assert _rule(half, "imu.gyro_present").verdict is PlausibilityVerdict.UNKNOWN
    assert half.plausibility_verdict is PlausibilityVerdict.UNKNOWN


def test_the_matrix_really_does_carry_four_independent_imu_units() -> None:
    """Four IMUs, derived from (device, frame_id) rather than counted by hand.

    The grouping is the load-bearing part: the ``lf/`` mirror is the SAME body
    IMU and must not become a fifth witness, and the D455's two motion streams
    are one unit and must not become two.
    """

    imu_channels = [e for e in CHANNELS if ChannelClass.IMU in classify_channel(e)]
    units = {imu_unit_id(e) for e in imu_channels}
    assert len(units) == 4, sorted(units)
    assert imu_unit_id(channel(CH_ACCEL)) == imu_unit_id(channel(CH_GYRO))
    assert imu_unit_id(channel(CH_LOWSTATE)) != imu_unit_id(channel(CH_IMU))
    mirrors = [e for e in CHANNELS if e.channel_id.startswith("go2.lf.")]
    for mirror in mirrors:
        if ChannelClass.IMU in classify_channel(mirror):
            assert imu_unit_id(mirror) == imu_unit_id(channel(CH_LOWSTATE))


def _four_imu_probes(utlidar_accel) -> tuple[ChannelProbe, ...]:
    good = (0.0, 0.0, 9.81)
    return (
        _measure(CH_LOWSTATE, _imu(accel=good, gyro=(0.0, 0.0, 0.0)), rest=REST),
        _measure(CH_IMU, _imu(accel=utlidar_accel, gyro=(0.0, 0.0, 0.0)), rest=REST),
        _measure(CH_L2_IMU, _imu(accel=good, gyro=(0.0, 0.0, 0.0)), rest=REST),
        _measure(CH_ACCEL, _imu(accel=good), rest=REST),
    )


def test_seeded_failure_three_imus_at_gravity_and_one_at_1e24_names_the_outlier() -> None:
    """The cross-check the card asks for: the units are each other's oracle."""

    cross = imu_cross_check(
        _four_imu_probes((FIELD_REPORT_ACCEL_MPS2, 0.0, 0.0)), CHANNELS, rest=REST
    )
    assert cross.verdict is PlausibilityVerdict.FAIL
    assert cross.units_enumerated == 4
    assert len(cross.unit_means) == 4
    (finding,) = cross.findings
    assert finding.code == "IMU_CROSS_CHECK_DISAGREEMENT"
    assert finding.severity is FindingSeverity.MAJOR
    assert imu_unit_id(channel(CH_IMU)) in finding.detail
    assert "Furthest from the median" in finding.detail


def test_refutation_four_agreeing_imus_produce_no_cross_check_finding() -> None:
    cross = imu_cross_check(_four_imu_probes((0.0, 0.0, 9.79)), CHANNELS, rest=REST)
    assert cross.verdict is PlausibilityVerdict.PASS
    assert cross.findings == ()


@pytest.mark.parametrize(
    ("rest", "probes_factory"),
    [
        (None, lambda: _four_imu_probes((0.0, 0.0, 9.81))),
        (REST, lambda: _four_imu_probes((0.0, 0.0, 9.81))[:1]),
    ],
)
def test_the_cross_check_reports_unknown_rather_than_agreement_it_cannot_see(
    rest, probes_factory
) -> None:
    cross = imu_cross_check(probes_factory(), CHANNELS, rest=rest)
    assert cross.verdict is PlausibilityVerdict.UNKNOWN
    assert cross.findings[0].code == "IMU_CROSS_CHECK_UNAVAILABLE"
    assert cross.findings[0].severity is FindingSeverity.NOTE


# ---------------------------------------------------------------------------
# GATE 16 — point clouds, and the fields[] dump that no later session recovers
# ---------------------------------------------------------------------------


def _cloud(**overrides):
    params = {
        "point_count": 20000,
        "field_names": ("x", "y", "z", "intensity", "ring", "time"),
        "nonfinite_points": 0,
        "ranges_m": tuple(0.5 + 0.01 * n for n in range(50)),
    }
    params.update(overrides)
    return lambda index: (PointCloudSample(**params),)


def test_a_deskewable_cloud_with_a_sane_range_distribution_passes() -> None:
    probe = _measure(CH_A, _cloud())
    assert probe.plausibility_verdict is PlausibilityVerdict.PASS
    assert probe.plausibility.point_cloud_fields == ("x", "y", "z", "intensity", "ring", "time")
    assert any("fields[]" in note for note in probe.plausibility.notes)


@pytest.mark.parametrize(
    ("overrides", "rule"),
    [
        ({"point_count": 0}, "point_cloud.point_count"),
        ({"nonfinite_points": 12}, "point_cloud.coordinates_finite"),
        ({"ranges_m": (1.0,) * 50}, "point_cloud.range_distribution"),
        ({"ranges_m": (0.5, 1.0, 42000.0)}, "point_cloud.range_distribution"),
        ({"ranges_m": (0.5, -3.0, 2.0)}, "point_cloud.range_distribution"),
        ({"ranges_m": (0.5, float("nan"), 2.0)}, "point_cloud.range_distribution"),
        ({"field_names": ("x", "y", "z")}, "point_cloud.per_point_time_field"),
        ({"field_names": ("x", "y", "z", "time")}, "point_cloud.ring_field"),
        ({"field_names": ()}, "point_cloud.per_point_time_field"),
    ],
)
def test_seeded_failure_each_bad_cloud_is_caught_by_its_own_rule(overrides, rule) -> None:
    probe = _measure(CH_A, _cloud(**overrides))
    assert _rule(probe, rule).verdict is PlausibilityVerdict.FAIL
    assert probe.plausibility_verdict is PlausibilityVerdict.FAIL


def test_a_cloud_with_no_per_point_time_dumps_its_fields_prominently() -> None:
    """The one finding on this card that a later session cannot recover."""

    probe = _measure(CH_A, _cloud(field_names=("x", "y", "z", "intensity")))
    (finding,) = [
        f
        for f in pf._plausibility_findings((probe,), CHANNELS)
        if f.code == "POINTCLOUD_NO_DESKEW_FIELDS"
    ]
    assert finding.severity is FindingSeverity.MAJOR
    assert "['x', 'y', 'z', 'intensity']" in finding.detail
    assert "deskew" in finding.detail.lower() or "motion-compensate" in finding.detail
    assert "only discoverable while the rig is powered" in finding.detail
    # ...and it does not stop the cloud being recorded.
    assert probe.status is ProbeStatus.PRESENT


def test_a_fields_layout_that_changes_mid_window_is_a_failure() -> None:
    clock = FakeClock()

    def make(index):
        names = ("x", "y", "z", "ring", "time") if index else ("x", "y", "z")
        return (PointCloudSample(point_count=10, field_names=names, ranges_m=(1.0, 2.0)),)

    probe = probe_channel(
        channel(CH_A),
        _measured_reader(clock, count=4, spacing_s=0.01, make=make),
        window_s=10.0,
        clock=clock,
    )
    assert _rule(probe, "point_cloud.field_layout_stable").verdict is PlausibilityVerdict.FAIL


def test_a_cloud_with_no_sampled_ranges_is_unknown_not_pass() -> None:
    probe = _measure(CH_A, _cloud(ranges_m=()))
    assert _rule(probe, "point_cloud.range_distribution").verdict is PlausibilityVerdict.UNKNOWN
    assert probe.plausibility_verdict is PlausibilityVerdict.UNKNOWN


# ---------------------------------------------------------------------------
# GATE 17 — battery and power
# ---------------------------------------------------------------------------


def _power(**overrides):
    cells = tuple([3.85] * 15)
    params = {"power_v": round(3.85 * 15, 3), "cell_volts": cells, "power_a": -2.4}
    params.update(overrides)
    return lambda index: (PowerSample(**params),)


def test_a_healthy_pack_passes_and_the_cell_sum_agrees_with_power_v() -> None:
    probe = _measure(CH_LOWSTATE, _power())
    assert _rule(probe, "power.pack_voltage_range").verdict is PlausibilityVerdict.PASS
    assert _rule(probe, "power.cell_voltage_range").verdict is PlausibilityVerdict.PASS
    assert _rule(probe, "power.cell_sum_consistent").verdict is PlausibilityVerdict.PASS


@pytest.mark.parametrize(
    ("overrides", "rule"),
    [
        ({"power_v": 0.0}, "power.pack_voltage_range"),
        ({"power_v": -57.75}, "power.pack_voltage_range"),
        ({"power_v": 1e6}, "power.pack_voltage_range"),
        ({"power_v": float("nan")}, "power.pack_voltage_range"),
        ({"cell_volts": tuple([3850.0] * 15), "power_v": 57.75}, "power.cell_voltage_range"),
        ({"cell_volts": tuple([1.2] * 15), "power_v": 18.0}, "power.cell_voltage_range"),
        ({"power_v": 40.0}, "power.cell_sum_consistent"),
    ],
)
def test_seeded_failure_each_bad_power_reading_is_caught_by_its_own_rule(
    overrides, rule
) -> None:
    probe = _measure(CH_LOWSTATE, _power(**overrides))
    assert _rule(probe, rule).verdict is PlausibilityVerdict.FAIL
    assert probe.plausibility_verdict is PlausibilityVerdict.FAIL


def test_a_pack_with_no_cell_array_cannot_be_cross_checked_and_says_so() -> None:
    """BmsState carries no voltage field, so without cell_vol there is nothing
    to check power_v against — and that is UNKNOWN, not PASS."""

    probe = _measure(CH_LOWSTATE, _power(cell_volts=()))
    assert _rule(probe, "power.cell_sum_consistent").verdict is PlausibilityVerdict.UNKNOWN
    assert _rule(probe, "power.cell_voltage_range").verdict is PlausibilityVerdict.UNKNOWN
    assert _rule(probe, "power.pack_voltage_range").verdict is PlausibilityVerdict.PASS


def test_a_millivolt_cell_array_is_refused_rather_than_silently_scaled() -> None:
    probe = _measure(CH_LOWSTATE, _power(cell_volts=tuple([3850.0] * 15), power_v=57.75))
    detail = _rule(probe, "power.cell_voltage_range").detail
    assert "millivolts" in detail
    assert "refuses to guess units" in detail


# ---------------------------------------------------------------------------
# GATE 18 — foot force: four channels that move, and no absolute claim
# ---------------------------------------------------------------------------


def _foot(counts_for, est=True):
    def make(index):
        counts = counts_for(index)
        return (
            FootForceSample(
                counts=counts,
                counts_est=tuple(c + 3 for c in counts) if est else None,
            ),
        )

    return make


def test_four_feet_that_vary_pass_and_no_absolute_force_is_asserted() -> None:
    """Large but varying counts PASS. That is the point: the counts have no
    published units, gain or offset, so no absolute value can be asserted."""

    probe = _measure(CH_LOWSTATE, _foot(lambda i: (30000 - i, 29000 + i, 100 + i, 5 + i)))
    assert _rule(probe, "foot_force.four_channels").verdict is PlausibilityVerdict.PASS
    assert _rule(probe, "foot_force.varies").verdict is PlausibilityVerdict.PASS
    assert _rule(probe, "foot_force.int16_container").verdict is PlausibilityVerdict.PASS
    assert "NO units, gain or offset" in _rule(probe, "foot_force.int16_container").detail


def test_seeded_failure_a_stuck_foot_is_caught_and_named() -> None:
    probe = _measure(CH_LOWSTATE, _foot(lambda i: (10 + i, 20, 30 + i, 40 + i)))
    check = _rule(probe, "foot_force.varies")
    assert check.verdict is PlausibilityVerdict.FAIL
    assert "[1]" in check.detail
    assert "stuck" in check.detail


def test_seeded_failure_all_four_feet_stuck_is_caught() -> None:
    probe = _measure(CH_LOWSTATE, _foot(lambda i: (0, 0, 0, 0)))
    check = _rule(probe, "foot_force.varies")
    assert check.verdict is PlausibilityVerdict.FAIL
    assert "[0, 1, 2, 3]" in check.detail


def test_seeded_failure_a_three_element_foot_array_is_caught() -> None:
    probe = _measure(CH_LOWSTATE, _foot(lambda i: (1 + i, 2 + i, 3 + i)))
    assert _rule(probe, "foot_force.four_channels").verdict is PlausibilityVerdict.FAIL


def test_seeded_failure_a_count_outside_int16_is_a_decode_error() -> None:
    probe = _measure(CH_LOWSTATE, _foot(lambda i: (40000 + i, 1 + i, 2 + i, 3 + i)))
    check = _rule(probe, "foot_force.int16_container")
    assert check.verdict is PlausibilityVerdict.FAIL
    assert "container check, not a force claim" in check.detail


def test_too_few_samples_cannot_distinguish_a_stuck_sensor_from_a_slow_one() -> None:
    probe = _measure(CH_LOWSTATE, _foot(lambda i: (0, 0, 0, 0)), count=3)
    assert _rule(probe, "foot_force.varies").verdict is PlausibilityVerdict.UNKNOWN


def test_the_foot_force_estimator_difference_is_recorded_as_evidence_not_a_verdict() -> None:
    with_est = _measure(CH_LOWSTATE, _foot(lambda i: (10 + i, 20 + i, 30 + i, 40 + i)))
    assert any("foot_force_est" in note for note in with_est.plausibility.notes)
    without = _measure(
        CH_LOWSTATE, _foot(lambda i: (10 + i, 20 + i, 30 + i, 40 + i), est=False)
    )
    assert any("was not supplied" in note for note in without.plausibility.notes)


# ---------------------------------------------------------------------------
# GATE 19 — cameras
# ---------------------------------------------------------------------------


def _image(**overrides):
    params = {
        "width": 848,
        "height": 480,
        "decoded": True,
        "min_level": 3.0,
        "max_level": 251.0,
        "mean_level": 104.2,
        "zero_fraction": 0.004,
        "saturated_fraction": 0.002,
    }
    params.update(overrides)
    return lambda index: (ImageSample(**params),)


def test_a_frame_that_decodes_and_has_content_passes() -> None:
    probe = _measure(CH_CAMERA, _image())
    assert probe.plausibility_verdict is PlausibilityVerdict.PASS


@pytest.mark.parametrize(
    ("overrides", "rule"),
    [
        ({"decoded": False}, "camera.frame_decodes"),
        ({"width": 0}, "camera.frame_decodes"),
        ({"mean_level": float("nan")}, "camera.frame_decodes"),
        ({"zero_fraction": 1.0, "min_level": 0.0, "max_level": 0.0}, "camera.non_degenerate"),
        ({"saturated_fraction": 0.999}, "camera.non_degenerate"),
        ({"min_level": 128.0, "max_level": 128.0}, "camera.non_degenerate"),
    ],
)
def test_seeded_failure_each_bad_frame_is_caught_by_its_own_rule(overrides, rule) -> None:
    probe = _measure(CH_CAMERA, _image(**overrides))
    assert _rule(probe, rule).verdict is PlausibilityVerdict.FAIL
    assert probe.plausibility_verdict is PlausibilityVerdict.FAIL


def test_a_lens_cap_still_delivers_bytes_and_the_old_oracle_called_it_healthy() -> None:
    probe = _measure(
        CH_CAMERA,
        _image(zero_fraction=1.0, min_level=0.0, max_level=0.0, mean_level=0.0),
    )
    assert _receipt_count_health(probe) == "HEALTHY"
    assert probe.plausibility_verdict is PlausibilityVerdict.FAIL
    assert "lens cap" in _rule(probe, "camera.non_degenerate").detail


# ---------------------------------------------------------------------------
# GATE 20 — the layer is fail-closed everywhere, exactly like presence is
# ---------------------------------------------------------------------------


def test_the_verdict_is_derived_and_cannot_be_passed_to_any_constructor() -> None:
    """Structural, as with ``status``/``origin``: PASS must be earned."""

    assert "verdict" not in set(ChannelPlausibility.__dataclass_fields__)
    assert isinstance(ChannelPlausibility.verdict, property)
    assert "plausibility_verdict" not in set(ChannelProbe.__dataclass_fields__)
    assert isinstance(ChannelProbe.plausibility_verdict, property)
    assert "plausibility_verdict" not in set(ChannelAttestation.__dataclass_fields__)
    assert isinstance(ChannelAttestation.plausibility_verdict, property)


def test_one_unknown_check_beside_many_passes_is_still_unknown() -> None:
    """UNKNOWN never decays into PASS, however much else went right."""

    ruling = ChannelPlausibility(
        channel_id=CH_IMU,
        checks=(
            PlausibilityCheck("a", PlausibilityVerdict.PASS, "fine"),
            PlausibilityCheck("b", PlausibilityVerdict.PASS, "fine"),
            PlausibilityCheck("c", PlausibilityVerdict.UNKNOWN, "cannot judge"),
        ),
    )
    assert ruling.verdict is PlausibilityVerdict.UNKNOWN
    worse = ChannelPlausibility(
        channel_id=CH_IMU,
        checks=ruling.checks + (PlausibilityCheck("d", PlausibilityVerdict.FAIL, "no"),),
    )
    assert worse.verdict is PlausibilityVerdict.FAIL
    assert ChannelPlausibility(channel_id=CH_IMU).verdict is PlausibilityVerdict.UNKNOWN


def test_an_absent_channel_is_unknown_and_a_channel_with_no_rule_says_so() -> None:
    absent = _probe(CH_IMU, messages=0, absence=AbsenceReason.TIMEOUT)
    assert absent.plausibility_verdict is PlausibilityVerdict.UNKNOWN

    probes = probe_all_channels(window_s=0.01, clock=FakeClock())
    for probe in probes:
        assert probe.plausibility_verdict is PlausibilityVerdict.UNKNOWN
        assert probe.plausibility is not None
        assert probe.plausibility.check("channel.no_message_received") is not None

    unruled = assess_plausibility(channel(CH_EVENT), ())
    assert unruled.verdict is PlausibilityVerdict.UNKNOWN
    assert unruled.check("channel.no_rule_defined") is not None


def test_a_reader_that_measures_nothing_leaves_the_channel_unknown() -> None:
    """Bytes without a measurement is exactly the state the card refuses to
    call health, and it is the state every reader in this build is in."""

    clock = FakeClock()
    probe = probe_channel(
        channel(CH_IMU),
        _stream_reader(clock, spacing_s=0.01, count=25),
        window_s=10.0,
        clock=clock,
    )
    assert probe.status is ProbeStatus.PRESENT
    assert probe.plausibility_verdict is PlausibilityVerdict.UNKNOWN
    assert _rule(probe, "imu.no_measurement").verdict is PlausibilityVerdict.UNKNOWN
    findings = pf._plausibility_findings((probe,), CHANNELS)
    assert [f.code for f in findings] == ["PLAUSIBILITY_NOT_ASSESSED"]
    assert findings[0].severity is FindingSeverity.NOTE


def test_seeded_failure_an_assessor_that_raises_is_unknown_and_costs_no_messages() -> None:
    """A bug in this layer must not convert a live channel into an absence."""

    def exploding(entry, receipts, *, rest=None):
        raise ZeroDivisionError("seeded assessor defect")

    clock = FakeClock()
    original = pf.assess_plausibility
    pf.assess_plausibility = exploding
    try:
        probe = probe_channel(
            channel(CH_IMU),
            _measured_reader(
                clock, count=5, spacing_s=0.01, make=_imu(accel=(0.0, 0.0, 9.81))
            ),
            window_s=10.0,
            clock=clock,
        )
    finally:
        pf.assess_plausibility = original
    assert probe.status is ProbeStatus.PRESENT
    assert probe.messages_received == 5
    assert probe.plausibility_verdict is PlausibilityVerdict.UNKNOWN
    assert "ZeroDivisionError" in _rule(probe, "channel.assessor_raised").detail
    codes = {f.code for f in pf._plausibility_findings((probe,), CHANNELS)}
    assert "PLAUSIBILITY_ASSESSOR_FAILED" in codes


@pytest.mark.parametrize(
    "measurements",
    [
        [ImuSample(accel_mps2=(0.0, 0.0, 9.81))],
        ("not a sample",),
        (object(),),
    ],
)
def test_a_receipt_may_only_carry_typed_physical_samples(measurements) -> None:
    with pytest.raises(ProbeContractError):
        SampleReceipt(
            channel_id=CH_IMU,
            host_monotonic_ns=1,
            payload_bytes=8,
            measurements=measurements,
        )


@pytest.mark.parametrize(
    "make",
    [
        lambda: ImuSample(),
        lambda: ImuSample(accel_mps2=(1.0, 2.0)),
        lambda: ImuSample(accel_mps2=(1.0, 2.0, "3")),
        lambda: ImuSample(gyro_rps=(True, 0.0, 0.0)),
        lambda: PointCloudSample(point_count=-1, field_names=("x",)),
        lambda: PointCloudSample(point_count=1, field_names=("x", "")),
        lambda: PointCloudSample(point_count=1, field_names=["x"]),
        lambda: PowerSample(power_v="57"),
        lambda: FootForceSample(counts=(1, 2, 3, 4.5)),
        lambda: ImageSample(
            width=1, height=1, decoded=True, min_level=0.0, max_level=1.0,
            mean_level=0.5, zero_fraction=1.5, saturated_fraction=0.0,
        ),
    ],
)
def test_a_malformed_physical_sample_is_a_refusal_never_a_default(make) -> None:
    with pytest.raises(ProbeContractError):
        make()


def test_every_physical_sample_type_shares_the_base_the_receipt_gate_checks() -> None:
    """``SampleReceipt`` accepts measurements by base class, so the base must hold.

    A sample type that forgot to inherit ``PhysicalSample`` would be rejected at
    the receipt, turning a working reader into an unexplained ABSENT channel.
    """

    for sample_type in (ImuSample, PointCloudSample, PowerSample, FootForceSample, ImageSample):
        assert issubclass(sample_type, PhysicalSample), sample_type
    assert set(pf._CLASS_SAMPLE_TYPE) == set(ChannelClass)
    assert not issubclass(SampleReceipt, PhysicalSample)


def test_a_non_finite_statistic_is_never_stored_as_a_number() -> None:
    """``canonical_json`` forbids NaN, so a NaN mean would make the whole
    attestation unserialisable. It is reported in words instead."""

    with pytest.raises(ProbeContractError):
        ChannelPlausibility(channel_id=CH_IMU, accel_magnitude_mean_mps2=float("nan"))
    probe = _measure(CH_IMU, _imu(accel=(float("nan"), 0.0, 0.0)), rest=REST)
    assert probe.plausibility.accel_magnitude_mean_mps2 is None
    assert probe.plausibility_verdict is PlausibilityVerdict.FAIL


def test_the_plausibility_layer_never_moves_a_probe_status() -> None:
    """The one property that keeps a suspect channel recorded."""

    good = _measure(CH_IMU, _imu(accel=(0.0, 0.0, 9.81), gyro=(0.0, 0.0, 0.0)), rest=REST)
    bad = _measure(CH_IMU, _imu(accel=(FIELD_REPORT_ACCEL_MPS2, 0.0, 0.0)), rest=REST)
    assert good.status is bad.status is ProbeStatus.PRESENT
    assert good.plausibility_verdict is PlausibilityVerdict.PASS
    assert bad.plausibility_verdict is PlausibilityVerdict.FAIL
    assert good.messages_received == bad.messages_received


def test_every_live_matrix_channel_gets_a_class_or_an_explicit_none() -> None:
    """Coverage of the rewritten matrix, in both directions."""

    classified = {e.channel_id: classify_channel(e) for e in CHANNELS}
    assert ChannelClass.IMU in classified[CH_IMU]
    assert set(classified[CH_LOWSTATE]) == {
        ChannelClass.IMU,
        ChannelClass.POWER,
        ChannelClass.FOOT_FORCE,
    }
    assert classified[CH_A] == (ChannelClass.POINT_CLOUD,)
    assert classified[CH_CAMERA] == (ChannelClass.CAMERA,)
    assert classified[CH_EVENT] == ()
    for entry in CHANNELS:
        assert isinstance(classified[entry.channel_id], tuple)


# ---------------------------------------------------------------------------
# GATE 21 — the verdict rides in the attestation, in the digest, forgery-proof
# ---------------------------------------------------------------------------


def _implausible_attestation():
    probe = _measure(CH_IMU, _imu(accel=(FIELD_REPORT_ACCEL_MPS2, 0.0, 0.0)))
    return probe, _attest(_report_with(probe, firmware="1.1.13"))


def test_the_attestation_carries_the_verdict_and_the_evidence() -> None:
    probe, attestation = _implausible_attestation()
    assert probe.plausibility_verdict is PlausibilityVerdict.FAIL
    record = attestation.as_dict()
    entry = next(c for c in record["channels"] if c["channel_id"] == CH_IMU)
    assert entry["plausibility_verdict"] == "fail"
    assert entry["plausibility"]["checks"]
    assert record["plausibility"]["implausible_channels"] == [CH_IMU]
    assert record["plausibility"]["counts"]["fail"] == 1
    assert any("2.17e+24" in line for line in record["plausibility"]["evidence"])
    assert any("plausibility" in line.lower() for line in record["does_not_prove"])


def test_seeded_failure_a_hand_forged_plausibility_pass_is_reported_not_absorbed() -> None:
    """Exactly the ``origin: physical`` forgery, one field over."""

    _, attestation = _implausible_attestation()
    record = json.loads(json.dumps(attestation.as_dict()))
    for entry in record["channels"]:
        if entry["channel_id"] == CH_IMU:
            entry["plausibility_verdict"] = "pass"
    record["plausibility"]["implausible_channels"] = []
    record["plausibility"]["counts"] = {"pass": 28, "fail": 0, "unknown": 0}

    rebuilt, discrepancies = verify_mapping(record)
    assert rebuilt.by_channel[CH_IMU].plausibility_verdict is PlausibilityVerdict.FAIL
    assert rebuilt.implausible_channels == (CH_IMU,)
    assert any("plausibility_verdict" in text for text in discrepancies)
    assert any("implausible_channels" in text for text in discrepancies)
    assert any("counts" in text for text in discrepancies)


def test_refutation_an_untouched_attestation_with_a_verdict_verifies_clean() -> None:
    _, attestation = _implausible_attestation()
    record = json.loads(json.dumps(attestation.as_dict()))
    rebuilt, discrepancies = verify_mapping(record)
    assert discrepancies == ()
    assert rebuilt.digest() == attestation.digest()


def test_the_verdict_moves_the_digest_and_survives_a_round_trip() -> None:
    good = _measure(CH_IMU, _imu(accel=(0.0, 0.0, 9.81), gyro=(0.0, 0.0, 0.0)), rest=REST)
    bad = _measure(CH_IMU, _imu(accel=(FIELD_REPORT_ACCEL_MPS2, 0.0, 0.0)), rest=REST)
    a = _attest(_report_with(good, firmware="1.1.13"))
    b = _attest(_report_with(bad, firmware="1.1.13"))
    assert a.digest() != b.digest()
    rebuilt = HardwareAttestationV1.from_mapping(json.loads(json.dumps(b.as_dict())))
    assert rebuilt.digest() == b.digest()
    assert rebuilt.canonical_json() == b.canonical_json()


def test_a_channel_may_not_inherit_another_channels_verdict() -> None:
    probe = _measure(CH_IMU, _imu(accel=(0.0, 0.0, 9.81)))
    honest = ChannelAttestation.from_probe(probe, channel(CH_IMU))
    assert honest.plausibility is not None
    with pytest.raises(AttestationRefused, match="another channel's verdict"):
        ChannelAttestation(
            **_fields(
                honest,
                plausibility=ChannelPlausibility(channel_id=CH_A, checks=honest.plausibility.checks),
            )
        )


def test_an_undecodable_ruling_in_a_record_is_refused_never_defaulted() -> None:
    _, attestation = _implausible_attestation()
    record = json.loads(json.dumps(attestation.as_dict()))
    for entry in record["channels"]:
        if entry["channel_id"] == CH_IMU:
            entry["plausibility"]["checks"][0]["verdict"] = "probably_fine"
    with pytest.raises(AttestationRefused):
        HardwareAttestationV1.from_mapping(record)


# ---------------------------------------------------------------------------
# GATE 22 — the verdict is printed into the run header, for every channel
# ---------------------------------------------------------------------------


def test_the_run_header_prints_a_verdict_for_every_channel() -> None:
    probe = _measure(CH_A, _cloud(field_names=("x", "y", "z")))
    report = _report_with(probe, firmware="1.1.13")
    text = "\n".join(format_plausibility_block(report))
    assert "PHYSICAL PLAUSIBILITY" in text
    assert "a channel is not healthy because bytes arrive" in text
    for entry in CHANNELS:
        assert entry.channel_id in text
    assert "NO per-point time field" in text
    assert "rest period: NOT DECLARED" in text
    assert "IMU cross-check" in text

    full = pf.format_report(report)
    assert "plausibility=FAIL" in full
    assert "PHYSICAL PLAUSIBILITY" in full


def test_the_attestation_header_names_the_implausible_channels_and_the_fields() -> None:
    probe = _measure(CH_A, _cloud(field_names=("x", "y", "z")))
    attestation = _attest(_report_with(probe, firmware="1.1.13"))
    text = attest_mod.format_attestation(attestation)
    assert "plausible    pass=" in text
    assert "IMPLAUSIBLE" in text
    assert "RECORD THEM ANYWAY" in text
    assert "PointCloud2 fields[]" in text
    assert "a channel is not healthy because bytes arrive" in text


def test_the_rest_attestation_is_named_in_the_header_when_one_is_given() -> None:
    probe = _measure(CH_IMU, _imu(accel=(0.0, 0.0, 9.81), gyro=(0.0, 0.0, 0.0)), rest=REST)
    report = _report_with(probe, rest=REST, firmware="1.1.13")
    text = "\n".join(format_plausibility_block(report))
    assert "fixture-operator" in text
    assert "dog on the bench" in text


def test_an_unattributed_rest_claim_is_refused() -> None:
    parser = pf.build_arg_parser("test")
    with pytest.raises(ProbeContractError, match="unattributed rest claim"):
        pf.rest_period_from_args(parser.parse_args(["--at-rest-note", "it was still"]))
    assert pf.rest_period_from_args(parser.parse_args([])) is None
    rest = pf.rest_period_from_args(parser.parse_args(["--at-rest", "jae"]))
    assert rest is not None and rest.attested_by == "jae"
    with pytest.raises(ProbeContractError):
        RestPeriod(attested_by="   ")


def test_the_cli_accepts_at_rest_without_a_traceback(capsys) -> None:
    code = pf.main(["--window", "0.01", "--at-rest", "jae", "--at-rest-note", "bench"])
    out = capsys.readouterr()
    assert code == 1
    assert "Traceback" not in out.err
    assert "PHYSICAL PLAUSIBILITY" in out.out
    assert "operator jae attests the rig was at rest" in out.out


# ---------------------------------------------------------------------------
# GATE 26 — PS-N finding 1: preflight can actually reach a channel
# ---------------------------------------------------------------------------
#
# The ingest fix landed on the recorder half and never on this one.
# ``run_preflight`` defaulted to ``unavailable_reader_factory``, ``main()``
# passed no factory at all, and the refusal an operator would read said "supply
# one via --reader-module" — a flag that did not exist in ``build_arg_parser``
# or anywhere else. So the tool whose entire job is to prove channels are live
# before the session could not reach a single channel even on a correctly
# configured Orin, and the message it printed pointed at nothing.
#
# Three properties, each with the pre-fix behaviour named:
#   1. the defaults and main() reach the live adapters (they reached the
#      refusal factory);
#   2. every flag any refusal names is a real flag (--reader-module was not);
#   3. --reader-module resolves a factory or refuses, never falls back.


class _RecordingRunPreflight:
    """Captures the kwargs ``main()`` hands to ``run_preflight``."""

    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.kwargs: dict = {}

    def __call__(self, **kwargs):
        self.kwargs = dict(kwargs)
        return self.delegate(**kwargs)


def test_main_with_default_args_reaches_the_live_ingest_factory(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The defect, stated as the assertion that would have caught it.

    Pre-fix, ``main()`` called ``run_preflight`` with no ``reader_factory`` at
    all, so this cell fails on ``KeyError: 'reader_factory'`` before it can even
    compare identities — and had it defaulted, the identity would have been
    ``unavailable_reader_factory``.
    """

    spy = _RecordingRunPreflight(pf.run_preflight)
    monkeypatch.setattr(pf, "run_preflight", spy)
    code = pf.main(["--window", "0.01"])
    assert code == 1  # no hardware here: blocking absences, but a complete report
    assert "reader_factory" in spy.kwargs, "main() named no factory at all"
    assert spy.kwargs["reader_factory"] is pf.default_reader_factory
    assert spy.kwargs["reader_factory"] is not pf.unavailable_reader_factory
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err


def test_the_two_probe_entry_points_default_to_the_live_factory() -> None:
    """A default that cannot reach hardware is the same defect one layer down."""

    for func in (pf.run_preflight, pf.probe_all_channels):
        default = func.__kwdefaults__["reader_factory"]
        assert default is pf.default_reader_factory, func.__name__
        assert default is not pf.unavailable_reader_factory, func.__name__


def test_the_default_factory_reaches_the_real_adapter_when_its_dependency_is_there(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fix, proven by driving a channel to PRESENT through the DEFAULT path.

    ``rclpy`` is absent here and the board forbids installing it, so the
    dependency report is the one thing that has to be stood in for. Everything
    downstream of it — ``adapter_for``, the adapter's own ``read``/contract
    checks, ``channel_reader_factory``'s receipt bridge, ``probe_channel`` — is
    the real code on the real seam.

    Pre-fix this cell fails at ``pf.default_reader_factory``: the function did
    not exist, and the default was a factory that refuses for every transport.
    """

    from scripts.parcel_capture.ingest import DdsIngest, IngestFrame, PayloadKind
    from scripts.parcel_capture.ingest.base import DependencyReport

    entry = channel(CH_B)

    monkeypatch.setattr(
        DdsIngest,
        "dependency_report",
        classmethod(
            lambda cls: DependencyReport(
                adapter="dds", satisfied=True, present=("rclpy",), missing=(), remedy=""
            )
        ),
    )

    def fake_read_frames(self, target, window_s):
        for index in range(3):
            yield IngestFrame(
                channel_id=target.channel_id,
                host_monotonic_ns=1_000_000_000 + index * 2_000_000,
                host_realtime_ns=1_700_000_000_000_000_000 + index * 2_000_000,
                payload=b'{"synthetic":true}',
                payload_kind=PayloadKind.DERIVED_SUMMARY,
                detail="stood-in rclpy read",
            )

    monkeypatch.setattr(DdsIngest, "read_frames", fake_read_frames)

    reader = pf.default_reader_factory(entry)
    receipts = list(reader(entry, 0.01))
    assert [r.channel_id for r in receipts] == [CH_B] * 3

    probe = probe_channel(entry, reader, window_s=0.01, expected_rate_hz=None)
    assert probe.status is ProbeStatus.PRESENT
    assert probe.messages_received == 3


def test_the_default_factory_keeps_the_transport_remedy_for_channels_no_adapter_serves() -> None:
    """The fallback is not a downgrade: it is the more actionable of the two.

    ``tegrastats`` and the ZED-F9P have no ingest adapter and never will on this
    card, and "tegrastats is not on PATH, this host is not a Jetson" beats any
    census the adapter registry could produce.
    """

    reader = pf.default_reader_factory(channel("orin.tegrastats"))
    with pytest.raises(TransportUnavailableError) as caught:
        list(reader(channel("orin.tegrastats"), 0.01))
    assert caught.value.reason is AbsenceReason.TOOL_MISSING
    assert "tegrastats" in caught.value.remedy

    reader = pf.default_reader_factory(channel("gnss.zed_f9p"))
    with pytest.raises(TransportUnavailableError) as caught:
        list(reader(channel("gnss.zed_f9p"), 0.01))
    assert caught.value.reason is AbsenceReason.DEVICE_NODE_MISSING


def test_the_default_factory_falls_back_when_the_dependency_is_missing_here() -> None:
    """On this box every DDS channel is still ABSENT, with the vendor-SDK warning.

    The fix must not cost the dev-box refusal its content: the reason an
    operator must never `pip install unitree_sdk2py` into ``.parcel/`` is
    carried on this path and nowhere else.
    """

    entry = channel(CH_A)
    reader = pf.default_reader_factory(entry)
    with pytest.raises(TransportUnavailableError) as caught:
        list(reader(entry, 0.01))
    assert caught.value.reason is AbsenceReason.DEPENDENCY_MISSING
    assert "Do NOT pip install the vendor SDK into .parcel/" in caught.value.remedy


_FLAG_PATTERN = __import__("re").compile(r"--[a-z][a-z0-9-]+")


def test_every_flag_a_preflight_refusal_names_is_a_real_flag() -> None:
    """The half of the defect that pointed the operator at nothing.

    Scans every refusal string a full dev-box run can produce — each probe's
    absence detail and remedy, every finding, and the whole formatted report —
    for anything shaped like a CLI flag, and requires argparse to know it.

    Pre-fix this fails on ``mic.xvf3800``: its remedy read "supply one via
    --reader-module", and ``--reader-module`` was in no parser in the tree.
    """

    parser = pf.add_reader_arguments(pf.build_arg_parser("scan"))
    known = {
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--")
    }
    assert "--reader-module" in known and "--reader" in known

    report = run_preflight(window_s=0.01, clock=FakeClock())
    haystack = [pf.format_report(report)]
    for probe in report.channels:
        haystack.extend([probe.evidence, probe.absence_detail or "", probe.remedy or ""])
    for finding in report.findings:
        haystack.append(finding.detail)

    # A channel's ``address`` is a FOREIGN command line — ``tegrastats --interval
    # <ms>`` — and its flags belong to that tool, not to this CLI. Subtracted
    # explicitly, and the subtraction is itself checked so it cannot become the
    # hole: it may not contain any flag this module's own refusals name.
    foreign = {flag for entry in CHANNELS for flag in _FLAG_PATTERN.findall(entry.address)}
    assert "--interval" in foreign, "the foreign-flag exclusion is not exercised"
    assert "--reader-module" not in foreign and "--reader" not in foreign

    named = {flag for text in haystack for flag in _FLAG_PATTERN.findall(text)}
    assert named, "the scan found no flags at all — it cannot have caught the defect"
    assert "--at-rest" in named, "the scan is not reaching the refusal text it must"
    unknown = sorted(named - known - foreign)
    assert unknown == [], f"refusals name flags that do not exist: {unknown}"


def test_seeded_failure_the_flag_scan_catches_a_reintroduced_phantom_flag() -> None:
    """The refutation: plant the original wording back and the scan must fire."""

    parser = pf.add_reader_arguments(pf.build_arg_parser("scan"))
    known = {
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--")
    }
    planted = "supply one via --reader-modules or the reader_factory argument"
    named = set(_FLAG_PATTERN.findall(planted))
    assert named == {"--reader-modules"}
    assert sorted(named - known) == ["--reader-modules"]


def test_the_reader_flags_parse_and_select_what_they_say(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = pf.add_reader_arguments(pf.build_arg_parser("x"))

    args = parser.parse_args([])
    assert args.reader == "auto" and args.reader_module is None
    assert pf.reader_factory_from_args(args) is pf.default_reader_factory

    args = parser.parse_args(["--reader", "none"])
    assert pf.reader_factory_from_args(args) is pf.unavailable_reader_factory

    args = parser.parse_args(["--reader-module", "scripts.parcel_capture.preflight:default_reader_factory"])
    assert pf.reader_factory_from_args(args) is pf.default_reader_factory

    # A namespace built by the shared parser alone — attest's — still resolves.
    bare = pf.build_arg_parser("y").parse_args([])
    assert pf.reader_factory_from_args(bare) is pf.default_reader_factory

    # The two flags are mutually exclusive, and argparse says so without a traceback.
    with pytest.raises(SystemExit):
        parser.parse_args(["--reader", "none", "--reader-module", "a:b"])


@pytest.mark.parametrize(
    ("spec", "fragment"),
    [
        ("no_colon_here", "expected MODULE:FACTORY"),
        ("a:b:c", "expected MODULE:FACTORY"),
        (":factory", "both the module and the factory name"),
        ("module:", "both the module and the factory name"),
        ("scripts.parcel_capture.no_such_module:f", "is not importable"),
        ("scripts.parcel_capture.preflight:no_such_attribute", "has no attribute"),
        ("scripts.parcel_capture.preflight:PREFLIGHT_SCHEMA", "is not callable"),
    ],
)
def test_a_reader_module_spec_that_does_not_resolve_is_a_refusal_never_a_default(
    spec: str, fragment: str
) -> None:
    """Fail closed in every direction. A silent revert to "no reader" after being
    told to use one is the same defect wearing a different hat."""

    with pytest.raises(ProbeContractError) as caught:
        pf.load_reader_factory(spec)
    assert fragment in str(caught.value)


def test_main_refuses_a_bad_reader_module_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = pf.main(["--window", "0.01", "--reader-module", "nope.nope:factory"])
    captured = capsys.readouterr()
    assert code == 2
    assert "PREFLIGHT REFUSED" in captured.err
    assert "Traceback" not in captured.err
    assert "--reader-module" in captured.err


def test_the_reader_module_flag_actually_drives_the_probe_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Parsing a flag is not honouring it. This drives ``main()`` through a
    factory named on the command line and reads the channel back out of the JSON
    report as PRESENT."""

    module = tmp_path / "ps_n_reader_probe.py"
    module.write_text(
        "from scripts.parcel_capture.ingest import FakeIngest, channel_reader_factory\n"
        "from scripts.parcel_capture.preflight import unavailable_reader_factory\n"
        "\n"
        "TARGET = 'go2.lowstate'\n"
        "_adapter = FakeIngest(channel_ids=[TARGET])\n"
        "_bridge = channel_reader_factory(_adapter)\n"
        "\n"
        "def factory(entry):\n"
        "    if entry.channel_id == TARGET:\n"
        "        return _bridge(entry)\n"
        "    return unavailable_reader_factory(entry)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    code = pf.main(
        ["--window", "0.05", "--json", "--reader-module", "ps_n_reader_probe:factory"]
    )
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    payload = json.loads(captured.out[captured.out.index("{") :])
    by_id = {item["channel_id"]: item for item in payload["channels"]}
    assert by_id["go2.lowstate"]["status"] == "present"
    assert by_id["go2.lowstate"]["messages_received"] > 0
    # ...and nothing else was fabricated by the override.
    assert by_id[CH_A]["status"] == "absent"
    assert code == 1  # other critical channels are still absent, as they must be


# ---------------------------------------------------------------------------
# GATE 27 — PS-N finding 2: SportModeState's samples reach a rule
# ---------------------------------------------------------------------------


def test_sport_mode_state_has_imu_and_foot_force_rules_and_its_samples_are_assessed() -> None:
    """The finding, and the number that showed it: ``samples_assessed == 0``.

    ``go2.sportmodestate`` is CRITICAL, its live decoder emits an ``ImuSample``
    and a ``FootForceSample`` per message, and ``classify_channel`` returned
    ``()`` — so the plausibility layer discarded every measurement the channel
    produced and reported ``channel.no_rule_defined``. Pre-fix, both the class
    assertion and ``samples_assessed >= 1`` fail.
    """

    entry = channel("go2.sportmodestate")
    assert set(classify_channel(entry)) == {ChannelClass.IMU, ChannelClass.FOOT_FORCE}

    receipts = tuple(
        SampleReceipt(
            channel_id=entry.channel_id,
            host_monotonic_ns=1_000_000_000 + index * 20_000_000,
            payload_bytes=256,
            measurements=(
                ImuSample(accel_mps2=(0.01, -0.02, 9.81), gyro_rps=(0.001, 0.0, -0.001)),
                # All four vary: ``foot_force.varies`` FAILS a foot whose count
                # never moves, which is the rule doing its job, not this cell's
                # subject.
                FootForceSample(
                    counts=(12 + index, 14 + index, 11 - index, 13 + 2 * index)
                ),
            ),
        )
        # Twelve, not eight: ``foot_force.varies`` needs FOOT_FORCE_MIN_SAMPLES
        # (10) before it will tell a stuck sensor from a slow one, and below
        # that it reports UNKNOWN rather than PASS — which is the fail-closed
        # behaviour, and would have masked this cell's real subject.
        for index in range(12)
    )
    ruling = assess_plausibility(entry, receipts, rest=REST)
    assert ruling.samples_assessed == 24
    assert ruling.verdict is PlausibilityVerdict.PASS
    assert set(ruling.classes) == {"imu", "foot_force"}
    assert not any(check.rule == "channel.no_rule_defined" for check in ruling.checks)


def test_the_lf_sport_mode_state_mirror_gets_the_same_rules() -> None:
    assert set(classify_channel(channel("go2.lf.sportmodestate"))) == {
        ChannelClass.IMU,
        ChannelClass.FOOT_FORCE,
    }


def test_sport_mode_states_imu_is_the_body_imu_and_not_a_fifth_witness() -> None:
    """The trap the naive fix walks into.

    ``SportModeState.imu_state`` IS the body IMU — the same physical sensor
    ``LowState`` carries — but the matrix row's ``frame_id`` is ``odom``,
    because that is the frame of the pose it reports. Grouping on the row's own
    frame would have minted a fifth "independent witness" out of the fourth one,
    and a cross-check that compares a sensor against itself agrees for the wrong
    reason.
    """

    assert imu_unit_id(channel("go2.sportmodestate")) == imu_unit_id(channel(CH_LOWSTATE))
    assert imu_unit_id(channel("go2.lf.sportmodestate")) == imu_unit_id(channel(CH_LOWSTATE))
    imu_channels = [e for e in CHANNELS if ChannelClass.IMU in classify_channel(e)]
    assert len({imu_unit_id(e) for e in imu_channels}) == 4

    # ...and the naive grouping really would have produced five.
    naive = {f"{e.device.value}:{e.frame_id}" for e in imu_channels}
    assert len(naive) == 5


def test_the_m_entry_point_does_not_load_this_module_twice(tmp_path: Path) -> None:
    """A defect my own fix introduced, and the assertion that catches it.

    ``python -m scripts.parcel_capture.preflight`` runs the file as ``__main__``.
    The ingest package then imports ``..preflight`` by name and gets a SECOND
    module object whose ``SampleReceipt`` is a different class from the one
    ``probe_channel`` type-checks against. Before the alias at the bottom of
    ``preflight.py``, the run below printed

        ABSENT go2.sportmodestate ... why: probe_contract_violation —
        reader yielded SampleReceipt, not a SampleReceipt

    for every channel a live reader served. On the Orin, with rclpy sourced and
    the dog publishing, that is all 23 served channels reading ABSENT for a
    reason that names our own code. Run through the real ``-m`` entry point in a
    subprocess, because that is the only place the defect exists.
    """

    module = tmp_path / "ps_n_dash_m_probe.py"
    module.write_text(
        "from scripts.parcel_capture.ingest import FakeIngest, channel_reader_factory\n"
        "from scripts.parcel_capture.preflight import unavailable_reader_factory\n"
        "TARGET = 'go2.sportmodestate'\n"
        "_bridge = channel_reader_factory(FakeIngest(channel_ids=[TARGET]))\n"
        "def factory(entry):\n"
        "    return _bridge(entry) if entry.channel_id == TARGET else "
        "unavailable_reader_factory(entry)\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable, "-B", "-m", "scripts.parcel_capture.preflight",
            "--window", "0.2", "--json",
            "--reader-module", "ps_n_dash_m_probe:factory",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "PYTHONPATH": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    assert "Traceback" not in proc.stderr, proc.stderr
    assert "probe_contract_violation" not in proc.stdout
    payload = json.loads(proc.stdout[proc.stdout.index("{") :])
    probe = next(
        item for item in payload["channels"] if item["channel_id"] == "go2.sportmodestate"
    )
    assert probe["status"] == "present", probe
    assert probe["messages_received"] > 0
    # ...and the rules the same channel gained in GATE 27 are visible in the
    # report the operator actually reads.
    assert set(probe["plausibility"]["classes"]) == {"imu", "foot_force"}
    assert probe["plausibility"]["samples_assessed"] > 0


# ---------------------------------------------------------------------------
# S-1 — support-artifact reconciliation (scrum/20260814/task_1)
# ---------------------------------------------------------------------------
#
# The verified P0: four optical streams on the plan, no camera_info, no /tf,
# no /tf_static. The plan now carries the support topics; these cells pin the
# RUN-TIME reconciliation against the observed graph — the same fail-closed
# semantics sensor channels get. Unknown is ABSENT; a REQUIRED support topic
# absent or type-mismatched at run time is a refusal, never a default.

_S1_FULL_GRAPH = """\
/camera/camera/color/image_raw [sensor_msgs/msg/Image]
/camera/camera/color/camera_info [sensor_msgs/msg/CameraInfo]
/camera/camera/depth/camera_info [sensor_msgs/msg/CameraInfo]
/camera/camera/infra1/camera_info [sensor_msgs/msg/CameraInfo]
/camera/camera/infra2/camera_info [sensor_msgs/msg/CameraInfo]
/tf [tf2_msgs/msg/TFMessage]
/tf_static [tf2_msgs/msg/TFMessage]
"""


def test_a_graph_carrying_every_support_topic_reconciles_clean() -> None:
    result = pf.reconcile_support_topics(_S1_FULL_GRAPH)
    assert result.ok
    assert len(result.checks) == 6  # four camera_info + /tf + /tf_static
    assert all(
        check.status is pf.SupportTopicStatus.PRESENT for check in result.checks
    )
    assert result.to_dict()["schema"] == "parcel.capture.support_reconciliation.v1"


def test_a_missing_required_camera_info_topic_is_a_refusal() -> None:
    """The P0 replayed through the new gate: the graph is exactly yesterday's
    plan (images, no camera_info) and reconciliation must refuse."""

    graph = "/camera/camera/color/image_raw [sensor_msgs/msg/Image]\n/tf_static [tf2_msgs/msg/TFMessage]\n"
    result = pf.reconcile_support_topics(graph)
    assert not result.ok
    absent = {
        check.topic: check
        for check in result.checks
        if check.status is pf.SupportTopicStatus.ABSENT
    }
    # All four camera_info topics are absent, every one a refusal.
    for topic in (
        "/camera/camera/color/camera_info",
        "/camera/camera/depth/camera_info",
        "/camera/camera/infra1/camera_info",
        "/camera/camera/infra2/camera_info",
    ):
        assert absent[topic].refusal, topic
    with pytest.raises(pf.PreflightError, match="reconciliation refused"):
        pf.reconcile_support_topics_or_raise(graph)


def test_absent_tf_is_a_finding_but_absent_tf_static_is_a_refusal() -> None:
    """/tf is recorded-opportunistic: a stationary rig with no odometry
    publisher legitimately has none. /tf_static is where the sensor mounting
    extrinsics live, and the pre-record snapshot is CAPTURED FROM that topic —
    a graph with no /tf_static publisher has nothing to snapshot either."""

    no_tf = _S1_FULL_GRAPH.replace("/tf [tf2_msgs/msg/TFMessage]\n", "")
    result = pf.reconcile_support_topics(no_tf)
    assert result.ok
    assert any("/tf is not on the observed graph" in item for item in result.findings)

    no_tf_static = _S1_FULL_GRAPH.replace("/tf_static [tf2_msgs/msg/TFMessage]\n", "")
    result2 = pf.reconcile_support_topics(no_tf_static)
    assert not result2.ok
    assert any("/tf_static" in item for item in result2.refusals)


def test_seeded_failure_a_type_mismatch_refuses_regardless_of_need() -> None:
    """A support topic present under the wrong type is affirmative evidence of
    misconfiguration — worse than absence, and never less than one. Even the
    opportunistic /tf refuses on it."""

    mismatched = _S1_FULL_GRAPH.replace(
        "/tf [tf2_msgs/msg/TFMessage]", "/tf [std_msgs/msg/String]"
    )
    result = pf.reconcile_support_topics(mismatched)
    assert not result.ok
    check = next(item for item in result.checks if item.topic == "/tf")
    assert check.status is pf.SupportTopicStatus.TYPE_MISMATCH
    assert check.refusal
    assert "std_msgs/msg/String" in check.detail


def test_seeded_failure_an_unparseable_topic_list_line_is_a_refusal() -> None:
    """A skipped line could be exactly the support topic whose absence would
    refuse the run; parse failure must never impersonate topic-missing."""

    with pytest.raises(pf.PreflightError, match="unparseable"):
        pf.parse_topic_list("/tf_static tf2_msgs/msg/TFMessage")  # no brackets
    with pytest.raises(pf.PreflightError, match="unparseable"):
        pf.reconcile_support_topics(_S1_FULL_GRAPH + "garbage line\n")


def test_unknown_is_absent_for_a_mapping_input_too() -> None:
    graph = {"/tf_static": ("tf2_msgs/msg/TFMessage",)}
    result = pf.reconcile_support_topics(graph)
    assert not result.ok  # the four camera_info topics are absent
    by_topic = {check.topic: check for check in result.checks}
    assert by_topic["/tf_static"].status is pf.SupportTopicStatus.PRESENT
    assert by_topic["/tf"].status is pf.SupportTopicStatus.ABSENT
    assert not by_topic["/tf"].refusal


def test_a_topic_advertising_two_types_passes_only_if_ours_is_among_them() -> None:
    doubled = _S1_FULL_GRAPH.replace(
        "/tf_static [tf2_msgs/msg/TFMessage]",
        "/tf_static [tf2_msgs/msg/TFMessage, std_msgs/msg/String]",
    )
    result = pf.reconcile_support_topics(doubled)
    check = next(item for item in result.checks if item.topic == "/tf_static")
    assert check.status is pf.SupportTopicStatus.PRESENT
    assert len(check.observed_types) == 2


def test_seeded_failure_a_payload_topic_is_not_a_support_row() -> None:
    """The reconciliation contract takes SUPPORT_TOPICS rows only; handing it
    a payload topic must refuse, not silently reconcile the wrong class."""

    from scripts.parcel_capture.rosbag2 import DRIVER_TOPICS

    with pytest.raises(pf.PreflightError, match="not a support topic"):
        pf.reconcile_support_topics(
            _S1_FULL_GRAPH, support_topics=[DRIVER_TOPICS[0]]
        )
