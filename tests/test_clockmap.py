"""Card PS-C — clock discipline. Gates for ``scripts/parcel_capture/clockmap.py``.

Every property cell is paired with a seeded-failure companion: the refutation
shows what the property is buying, because "the fit returned 40 ppm" proves
nothing on its own if a broken estimator would have returned it too.

The five card gates and where they live:

* seeded 500 ms step reported as a STEP, not smoothed into drift —
  ``test_a_seeded_500ms_step_is_reported_as_a_step`` plus the refutation
  ``test_seeded_failure_one_line_fit_turns_the_step_into_20x_the_true_drift``
* seeded 40 ppm recovered within a stated tolerance —
  ``test_a_seeded_40_ppm_drift_is_recovered_within_tolerance`` plus the
  interval-coverage cell over 60 independent noise seeds
* NaN/inf/None refused, never defaulted —
  ``test_seeded_failure_every_malformed_clock_field_is_refused``
* asymmetric round trip WIDENS the offset uncertainty —
  ``test_an_asymmetric_round_trip_widens_the_offset_uncertainty`` plus the
  refutation that dropping the systematic term puts the truth OUTSIDE the
  reported interval
* round-trips through the PS-B sidecar ``extra`` by digest —
  ``test_the_map_round_trips_through_the_bag_sidecar_extra_by_digest``
"""

from __future__ import annotations

import ast
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from parcel_robot.bags import schema as bag_schema
from parcel_robot.capture.channels import CaptureError, SourceDevice
from parcel_robot.evidence_origin import EvidenceOrigin
from scripts.parcel_capture.clockmap import (
    CLOCK_MAP_SCHEMA,
    CLOCK_SAMPLE_SCHEMA,
    DEFAULT_SCHEDULE,
    MIN_SEGMENT_SAMPLES,
    PROBE_REQUIREMENTS,
    REALTIME_EPOCH_FLOOR_NS,
    ClockMapError,
    ClockMapV1,
    ClockProbeError,
    ClockRefusalReason,
    ClockRefusedError,
    ClockSample,
    ClockSchedule,
    FitBasis,
    RelationKind,
    Uncertainty,
    append_sample_jsonl,
    build_clock_map,
    canonical_json,
    clock_map_digest,
    fit_relation,
    format_report,
    interrogate,
    planned_elapsed_ns,
    probe_availability,
    read_samples_jsonl,
    sidecar_clock_block,
    synthesize_samples,
    t_critical_95,
)

REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "scripts" / "parcel_capture" / "clockmap.py"

# A plausible session: the host has been up 12 s, the wall clock is mid-2026,
# and the dog's clock sits 4.2 s behind the host with a 2 ms DDS round trip.
START_HOST_NS = 12_000_000_000
START_REALTIME_NS = 1_786_000_000_000_000_000
TRUE_OFFSET_NS = -4_200_000_000
ROUND_TRIP_NS = 2_000_000

# STATED TOLERANCE for the drift gate. Not a fudge factor: it is the drift
# uncertainty this design reports for itself. With a 2 ms round trip over a
# 900 s span the systematic bracket bound alone is ~3 ppm, so a recovery
# claim tighter than that would be a claim the evidence cannot support.
DRIFT_TOLERANCE_PPM = 3.0


def _session(
    *,
    duration_ns: int = 900_000_000_000,
    device: SourceDevice = SourceDevice.GO2,
    drift_ppm: float = 0.0,
    jitter_ns: int = 50_000,
    step_at_elapsed_ns: int | None = None,
    step_ns: int = 0,
    round_trip_ns: int = ROUND_TRIP_NS,
    request_leg_fraction: float = 0.5,
    seed: int = 20260813,
) -> list[ClockSample]:
    return synthesize_samples(
        device=device,
        start_host_ns=START_HOST_NS,
        start_realtime_ns=START_REALTIME_NS,
        elapsed_ns=planned_elapsed_ns(duration_ns=duration_ns),
        offset_ns=TRUE_OFFSET_NS,
        drift_ppm=drift_ppm,
        round_trip_ns=round_trip_ns,
        jitter_ns=jitter_ns,
        step_at_elapsed_ns=step_at_elapsed_ns,
        step_ns=step_ns,
        request_leg_fraction=request_leg_fraction,
        seed=seed,
    )


def _map(samples: list[ClockSample], **kwargs: object) -> ClockMapV1:
    defaults: dict[str, object] = {
        "session_id": "P5-DRY-20260813-clockmap",
        "created_at_utc": "2026-08-13T09:00:00Z",
        "host_id": "orin-nx-01",
        "origin": EvidenceOrigin.SIMULATION,
        "fixture_label": "clockmap-test",
    }
    defaults.update(kwargs)
    return build_clock_map(samples, **defaults)  # type: ignore[arg-type]


def _naive_single_line_ppm(samples: list[ClockSample]) -> float:
    """The estimator this card exists to refuse: one OLS line, no step scan."""

    xs = [(sample.host_mid_ns - samples[0].host_mid_ns) / 1e9 for sample in samples]
    ys = [float(sample.offset_ns - samples[0].offset_ns) for sample in samples]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    sxx = sum((x - x_mean) ** 2 for x in xs)
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    return (sxy / sxx) / 1000.0


def _truth_offset_at(host_mid_ns: int, *, drift_ppm: float) -> float:
    """The offset the fixture actually built, at a host instant."""

    return TRUE_OFFSET_NS + (host_mid_ns - START_HOST_NS) * drift_ppm / 1e6


# --------------------------------------------------------------------------- #
# GATE 1 — a step is a step
# --------------------------------------------------------------------------- #


def test_a_seeded_500ms_step_is_reported_as_a_step() -> None:
    duration = 900_000_000_000
    clock_map = _map(
        _session(duration_ns=duration, drift_ppm=40.0, step_at_elapsed_ns=duration // 2,
                 step_ns=500_000_000)
    )
    relation = clock_map.relation_for(SourceDevice.GO2)

    assert len(relation.steps) == 1, "exactly one discontinuity was seeded"
    step = relation.steps[0]
    assert abs(step.magnitude_ns - 500_000_000) < 100_000, step
    # Located inside the sampling gap it happened in, and not claimed narrower.
    assert step.gap_ns > 0
    assert (
        abs(step.at_host_monotonic_ns - (START_HOST_NS + duration // 2)) <= step.gap_ns
    )
    assert len(relation.segments) == 2


def test_the_step_is_not_smoothed_into_either_segments_drift() -> None:
    duration = 900_000_000_000
    clock_map = _map(
        _session(duration_ns=duration, drift_ppm=40.0, step_at_elapsed_ns=duration // 2,
                 step_ns=500_000_000)
    )
    relation = clock_map.relation_for(SourceDevice.GO2)
    for segment in relation.segments:
        assert segment.drift_ppm is not None
        assert abs(segment.drift_ppm - 40.0) < DRIFT_TOLERANCE_PPM, segment


def test_seeded_failure_one_line_fit_turns_the_step_into_20x_the_true_drift() -> None:
    """Refutation: without segmentation the step becomes drift.

    Measured on this fixture: the naive one-line fit reports 772.5 ppm against a
    true 40 ppm — 19x the value, and its error is four orders of magnitude past
    the segmented fit's. That is what "not smoothed into the drift fit" buys.
    """

    duration = 900_000_000_000
    samples = _session(
        duration_ns=duration, drift_ppm=40.0, step_at_elapsed_ns=duration // 2,
        step_ns=500_000_000,
    )
    naive_ppm = _naive_single_line_ppm(samples)
    segmented = _map(samples).relation_for(SourceDevice.GO2).primary_segment.drift_ppm

    assert segmented is not None
    assert abs(segmented - 40.0) < DRIFT_TOLERANCE_PPM
    assert naive_ppm > 500.0, naive_ppm
    assert abs(naive_ppm - 40.0) > 100 * abs(segmented - 40.0)


def test_a_clean_series_produces_no_spurious_step() -> None:
    clock_map = _map(_session(drift_ppm=40.0))
    relation = clock_map.relation_for(SourceDevice.GO2)
    assert relation.steps == ()
    assert len(relation.segments) == 1


def test_a_step_below_the_bracket_is_not_claimed() -> None:
    """A 100 us step under a 2 ms bracket is not evidence; refusing to split is right."""

    duration = 900_000_000_000
    clock_map = _map(
        _session(duration_ns=duration, step_at_elapsed_ns=duration // 2, step_ns=100_000,
                 jitter_ns=50_000)
    )
    relation = clock_map.relation_for(SourceDevice.GO2)
    assert relation.steps == ()


def test_two_steps_are_both_found() -> None:
    duration = 900_000_000_000
    plan = planned_elapsed_ns(duration_ns=duration)
    samples = []
    for elapsed in plan:
        step = 0
        if elapsed >= duration // 3:
            step += 300_000_000
        if elapsed >= 2 * duration // 3:
            step -= 800_000_000
        host_ns = START_HOST_NS + elapsed
        samples.append(
            ClockSample(
                device=SourceDevice.GO2,
                host_monotonic_ns=host_ns,
                host_realtime_ns=START_REALTIME_NS + elapsed,
                device_source_ns=host_ns + ROUND_TRIP_NS // 2 + TRUE_OFFSET_NS + step,
                round_trip_ns=ROUND_TRIP_NS,
                host_pair_bracket_ns=200,
            )
        )
    relation = _map(samples).relation_for(SourceDevice.GO2)
    magnitudes = sorted(step.magnitude_ns for step in relation.steps)
    assert len(magnitudes) == 2, relation.steps
    assert abs(magnitudes[0] - -800_000_000) < 200_000
    assert abs(magnitudes[1] - 300_000_000) < 200_000


# --------------------------------------------------------------------------- #
# GATE 2 — drift with an uncertainty
# --------------------------------------------------------------------------- #


def test_a_seeded_40_ppm_drift_is_recovered_within_tolerance() -> None:
    segment = _map(_session(drift_ppm=40.0)).relation_for(SourceDevice.GO2).primary_segment
    assert segment.basis is FitBasis.OLS
    assert segment.drift_ppm is not None
    assert abs(segment.drift_ppm - 40.0) < DRIFT_TOLERANCE_PPM, segment.drift_ppm
    assert segment.drift_uncertainty is not None
    assert segment.drift_uncertainty.is_bounded


def test_no_estimate_is_ever_a_bare_number() -> None:
    """The card's headline: an offset or a drift without an uncertainty is a failure."""

    clock_map = _map(_session(drift_ppm=40.0))
    for relation in clock_map.relations:
        for segment in relation.segments:
            assert isinstance(segment.offset_uncertainty, Uncertainty)
            assert segment.offset_uncertainty.total is not None
            assert segment.offset_uncertainty.total > 0.0
            assert segment.drift_uncertainty is not None
            assert segment.drift_uncertainty.total is not None
            assert segment.drift_uncertainty.total > 0.0
            assert segment.offset_uncertainty.confidence == "two-sided-95"


def test_the_reported_drift_interval_covers_the_truth_across_60_noise_seeds() -> None:
    """Coverage, not closeness: the interval has to be honest, not merely tight."""

    covered = 0
    trials = 60
    for seed in range(trials):
        segment = (
            _map(_session(drift_ppm=40.0, seed=seed))
            .relation_for(SourceDevice.GO2)
            .primary_segment
        )
        assert segment.drift_ppm is not None
        assert segment.drift_uncertainty is not None
        total = segment.drift_uncertainty.total
        assert total is not None
        if abs(segment.drift_ppm - 40.0) <= total:
            covered += 1
    assert covered == trials, f"{covered}/{trials} intervals covered the true 40 ppm"


def test_the_offset_interval_covers_the_truth() -> None:
    segment = _map(_session(drift_ppm=40.0)).relation_for(SourceDevice.GO2).primary_segment
    truth = _truth_offset_at(segment.reference_host_monotonic_ns, drift_ppm=40.0)
    total = segment.offset_uncertainty.total
    assert total is not None
    assert abs(segment.offset_ns - truth) <= total


def test_the_systematic_term_does_not_shrink_with_more_samples() -> None:
    """The whole point of splitting the uncertainty: averaging cannot remove a bias."""

    sparse = _map(_session(duration_ns=900_000_000_000)).relation_for(SourceDevice.GO2)
    dense = _map(
        synthesize_samples(
            device=SourceDevice.GO2,
            start_host_ns=START_HOST_NS,
            start_realtime_ns=START_REALTIME_NS,
            elapsed_ns=planned_elapsed_ns(
                duration_ns=900_000_000_000, cruise_interval_ns=100_000_000
            ),
            offset_ns=TRUE_OFFSET_NS,
            round_trip_ns=ROUND_TRIP_NS,
            jitter_ns=50_000,
        )
    ).relation_for(SourceDevice.GO2)

    assert dense.sample_count > 5 * sparse.sample_count
    sparse_seg = sparse.primary_segment
    dense_seg = dense.primary_segment
    assert dense_seg.offset_uncertainty.statistical is not None
    assert sparse_seg.offset_uncertainty.statistical is not None
    assert dense_seg.offset_uncertainty.statistical < sparse_seg.offset_uncertainty.statistical
    assert math.isclose(
        dense_seg.offset_uncertainty.systematic or -1.0,
        sparse_seg.offset_uncertainty.systematic or -2.0,
        rel_tol=1e-9,
    )


@pytest.mark.parametrize(
    ("count", "basis", "drift_is_known"),
    [(1, FitBasis.SINGLE_SAMPLE, False), (2, FitBasis.TWO_POINT, True)],
)
def test_a_short_segment_fails_closed_rather_than_claiming_zero_drift(
    count: int, basis: FitBasis, drift_is_known: bool
) -> None:
    samples = [
        ClockSample(
            device=SourceDevice.GO2,
            host_monotonic_ns=START_HOST_NS + index * 1_000_000_000,
            host_realtime_ns=START_REALTIME_NS + index * 1_000_000_000,
            device_source_ns=START_HOST_NS + index * 1_000_000_000 + TRUE_OFFSET_NS,
            round_trip_ns=ROUND_TRIP_NS,
            host_pair_bracket_ns=200,
        )
        for index in range(count)
    ]
    segment = _map(samples).relation_for(SourceDevice.GO2).primary_segment
    assert segment.basis is basis
    assert (segment.drift_ppm is not None) is drift_is_known
    # Either way the segment is NOT bounded: a two-point line has no residual to
    # bound it, and a single sample has no slope at all. Zero is never used to
    # mean unknown — including in the OFFSET's statistical half, which is the
    # one a fit can most plausibly be talked into reporting as 0.0 because the
    # residuals really are all zero.
    assert not segment.is_bounded
    assert segment.stats.residual_std_ns is None
    assert segment.residual_rms_ns is None
    assert segment.offset_uncertainty.statistical is None
    assert segment.offset_uncertainty.total is None
    assert not segment.offset_uncertainty.is_bounded
    assert segment.drift_uncertainty is None or not segment.drift_uncertainty.is_bounded


def test_an_unbounded_relation_makes_the_whole_map_uncertifiable() -> None:
    samples = _session()[:2]
    clock_map = _map(samples)
    assert not clock_map.is_certifiable
    assert any("not bounded" in item for item in clock_map.certification_shortfalls)


# --------------------------------------------------------------------------- #
# GATE 3 — malformed clock fields are refused, never defaulted
# --------------------------------------------------------------------------- #

_CLOCK_FIELDS = (
    "host_monotonic_ns",
    "host_realtime_ns",
    "device_source_ns",
    "round_trip_ns",
    "host_pair_bracket_ns",
)


@pytest.mark.parametrize("field", _CLOCK_FIELDS)
@pytest.mark.parametrize(
    ("bad_value", "reason"),
    [
        (float("nan"), ClockRefusalReason.NOT_FINITE),
        (float("inf"), ClockRefusalReason.NOT_FINITE),
        (float("-inf"), ClockRefusalReason.NOT_FINITE),
        (1.5, ClockRefusalReason.NON_INTEGER_FIELD),
        (True, ClockRefusalReason.NON_INTEGER_FIELD),
        ("1786000000", ClockRefusalReason.NON_INTEGER_FIELD),
        (-1, ClockRefusalReason.NEGATIVE_FIELD),
    ],
)
def test_seeded_failure_every_malformed_clock_field_is_refused(
    field: str, bad_value: object, reason: ClockRefusalReason
) -> None:
    good = {
        "device": SourceDevice.GO2,
        "host_monotonic_ns": START_HOST_NS,
        "host_realtime_ns": START_REALTIME_NS,
        "device_source_ns": START_HOST_NS + TRUE_OFFSET_NS,
        "round_trip_ns": ROUND_TRIP_NS,
        "host_pair_bracket_ns": 200,
    }
    good[field] = bad_value
    with pytest.raises(ClockRefusedError) as excinfo:
        ClockSample(**good)  # type: ignore[arg-type]
    assert excinfo.value.reason is reason
    assert field in str(excinfo.value)


@pytest.mark.parametrize("field", [f for f in _CLOCK_FIELDS if f != "host_pair_bracket_ns"])
def test_seeded_failure_none_in_a_required_clock_field_is_refused(field: str) -> None:
    good: dict[str, object] = {
        "device": SourceDevice.GO2,
        "host_monotonic_ns": START_HOST_NS,
        "host_realtime_ns": START_REALTIME_NS,
        "device_source_ns": START_HOST_NS + TRUE_OFFSET_NS,
        "round_trip_ns": ROUND_TRIP_NS,
    }
    good[field] = None
    with pytest.raises(ClockRefusedError) as excinfo:
        ClockSample(**good)  # type: ignore[arg-type]
    assert excinfo.value.reason is ClockRefusalReason.NON_INTEGER_FIELD
    assert "never a default" in str(excinfo.value)


def test_an_unset_rtc_is_refused_at_the_session_not_recorded() -> None:
    """The Jetson failure mode: no RTC battery, wall clock boots at the epoch."""

    with pytest.raises(ClockRefusedError) as excinfo:
        ClockSample(
            device=SourceDevice.ORIN,
            host_monotonic_ns=START_HOST_NS,
            host_realtime_ns=REALTIME_EPOCH_FLOOR_NS - 1,
            device_source_ns=START_HOST_NS,
            round_trip_ns=1000,
        )
    assert excinfo.value.reason is ClockRefusalReason.IMPLAUSIBLE_REALTIME
    assert "date -s" in str(excinfo.value)


def test_a_device_that_is_not_a_source_device_is_refused() -> None:
    with pytest.raises(ClockRefusedError) as excinfo:
        ClockSample(
            device="go2",  # type: ignore[arg-type]
            host_monotonic_ns=START_HOST_NS,
            host_realtime_ns=START_REALTIME_NS,
            device_source_ns=START_HOST_NS,
            round_trip_ns=1000,
        )
    assert excinfo.value.reason is ClockRefusalReason.DEVICE_NOT_TYPED


def test_an_empty_sample_set_is_refused() -> None:
    with pytest.raises(ClockRefusedError) as excinfo:
        _map([])
    assert excinfo.value.reason is ClockRefusalReason.NO_SAMPLES


def test_a_device_with_no_samples_has_no_relation_and_says_so() -> None:
    clock_map = _map(_session())
    with pytest.raises(ClockRefusedError) as excinfo:
        clock_map.relation_for(SourceDevice.D455)
    assert "not recoverable" in str(excinfo.value)


@pytest.mark.parametrize(
    ("origin", "fixture_label", "reason"),
    [
        (EvidenceOrigin.UNKNOWN, None, ClockRefusalReason.ORIGIN_NOT_DECLARED),
        (EvidenceOrigin.SIMULATION, None, ClockRefusalReason.FIXTURE_LABEL_MISSING),
        (EvidenceOrigin.REPLAY, "   ", ClockRefusalReason.FIXTURE_LABEL_MISSING),
        (EvidenceOrigin.PHYSICAL, "rehearsal", ClockRefusalReason.FIXTURE_LABEL_FORBIDDEN),
        ("physical", None, ClockRefusalReason.ORIGIN_NOT_TYPED),
    ],
)
def test_seeded_failure_origin_declaration_fails_closed(
    origin: object, fixture_label: str | None, reason: ClockRefusalReason
) -> None:
    with pytest.raises(ClockRefusedError) as excinfo:
        _map(_session(), origin=origin, fixture_label=fixture_label)
    assert excinfo.value.reason is reason


def test_a_physical_map_needs_no_fixture_label_and_a_synthetic_one_does() -> None:
    physical = _map(_session(), origin=EvidenceOrigin.PHYSICAL, fixture_label=None)
    assert physical.origin is EvidenceOrigin.PHYSICAL
    synthetic = _map(_session(), origin=EvidenceOrigin.SIMULATION, fixture_label="ps-e-rehearsal")
    assert synthetic.fixture_label == "ps-e-rehearsal"


@pytest.mark.parametrize("stamp", ["", "2026-08-13", "2026-08-13 09:00:00Z", "not-a-time"])
def test_a_malformed_created_at_is_refused(stamp: str) -> None:
    with pytest.raises(ClockRefusedError) as excinfo:
        _map(_session(), created_at_utc=stamp)
    assert excinfo.value.reason is ClockRefusalReason.MALFORMED_TIMESTAMP


def test_a_non_sample_in_the_input_is_refused() -> None:
    with pytest.raises(ClockRefusedError) as excinfo:
        _map([*_session()[:3], {"host_monotonic_ns": 1}])  # type: ignore[list-item]
    assert excinfo.value.reason is ClockRefusalReason.MALFORMED_RECORD


def test_every_refusal_is_catchable_as_one_capture_error() -> None:
    assert issubclass(ClockRefusedError, ClockMapError)
    assert issubclass(ClockProbeError, ClockMapError)
    assert issubclass(ClockMapError, CaptureError)


# --------------------------------------------------------------------------- #
# GATE 4 — asymmetry widens the uncertainty
# --------------------------------------------------------------------------- #


def test_an_asymmetric_round_trip_widens_the_offset_uncertainty() -> None:
    symmetric = (
        _map(_session(round_trip_ns=2_000_000, request_leg_fraction=0.5))
        .relation_for(SourceDevice.GO2)
        .primary_segment
    )
    asymmetric = (
        _map(_session(round_trip_ns=20_000_000, request_leg_fraction=0.95))
        .relation_for(SourceDevice.GO2)
        .primary_segment
    )
    symmetric_total = symmetric.offset_uncertainty.total
    asymmetric_total = asymmetric.offset_uncertainty.total
    assert symmetric_total is not None
    assert asymmetric_total is not None
    assert asymmetric_total > symmetric_total
    # And the widening is in the half that cannot be averaged away.
    assert (asymmetric.offset_uncertainty.systematic or 0) == pytest.approx(10_000_000.0)
    assert (symmetric.offset_uncertainty.systematic or 0) == pytest.approx(1_000_000.0)


def test_the_widened_interval_still_covers_the_truth_and_the_narrow_one_would_not() -> None:
    """Refutation: the systematic term is load-bearing, not decoration.

    Under an asymmetric path the point estimate IS biased — that is unavoidable
    without knowing the split. What the bracket bound buys is that the reported
    interval still contains the truth. Drop it, quote the statistical part
    alone, and the interval confidently excludes the right answer.
    """

    segment = (
        _map(_session(round_trip_ns=20_000_000, request_leg_fraction=0.95))
        .relation_for(SourceDevice.GO2)
        .primary_segment
    )
    truth = _truth_offset_at(segment.reference_host_monotonic_ns, drift_ppm=0.0)
    total = segment.offset_uncertainty.total
    statistical = segment.offset_uncertainty.statistical
    assert total is not None
    assert statistical is not None

    assert abs(segment.offset_ns - truth) <= total, "honest interval covers the truth"
    assert abs(segment.offset_ns - truth) > statistical, (
        "statistics-only interval would have excluded the truth by "
        f"{abs(segment.offset_ns - truth) - statistical:.0f} ns"
    )


def test_a_one_sided_path_is_detected_as_asymmetry_when_the_round_trip_varies() -> None:
    """The NTP wedge: residual against bracket has slope ``2*alpha - 1``."""

    detected: dict[float, tuple[bool, float | None]] = {}
    for fraction in (0.5, 1.0):
        samples = []
        for index, elapsed in enumerate(planned_elapsed_ns(duration_ns=900_000_000_000)):
            round_trip = 2_000_000 if index % 2 else 20_000_000
            host_ns = START_HOST_NS + elapsed
            samples.append(
                ClockSample(
                    device=SourceDevice.GO2,
                    host_monotonic_ns=host_ns,
                    host_realtime_ns=START_REALTIME_NS + elapsed,
                    device_source_ns=(
                        host_ns + round(fraction * round_trip) + TRUE_OFFSET_NS
                    ),
                    round_trip_ns=round_trip,
                    host_pair_bracket_ns=200,
                )
            )
        segment = _map(samples).relation_for(SourceDevice.GO2).primary_segment
        detected[fraction] = (segment.asymmetry_detected, segment.asymmetry_slope)

    assert detected[0.5][0] is False, detected[0.5]
    assert detected[1.0][0] is True, detected[1.0]
    assert detected[1.0][1] == pytest.approx(1.0, abs=0.05)


def test_a_constant_round_trip_leaves_asymmetry_undetectable_and_says_so() -> None:
    segment = (
        _map(_session(round_trip_ns=20_000_000, request_leg_fraction=0.95))
        .relation_for(SourceDevice.GO2)
        .primary_segment
    )
    assert segment.asymmetry_slope is None
    assert segment.asymmetry_detected is False
    assert any("indistinguishable" in item for item in _map(_session()).does_not_prove)


# --------------------------------------------------------------------------- #
# GATE 5 — the PS-B sidecar round trip
# --------------------------------------------------------------------------- #


def test_the_map_round_trips_through_the_bag_sidecar_extra_by_digest() -> None:
    clock_map = _map(_session(drift_ppm=40.0))
    digest = clock_map_digest(clock_map)

    manifest = bag_schema.make_manifest(
        bag_id="P5-DRY-20260813-clockmap",
        created_at_utc="2026-08-13T09:00:00Z",
        source="hardware",
        clocks=sidecar_clock_block(clock_map),
        frames=bag_schema.default_frames(),
        topics=["lidar/scan", "imu/data"],
        does_not_prove=list(clock_map.does_not_prove),
        message_count=0,
        extra={"clock_map": clock_map.to_dict(), "clock_map_sha256": digest},
    )
    bag_schema.validate_manifest(manifest)

    # Survives a real JSON round trip, byte for byte.
    reloaded = json.loads(json.dumps(manifest, sort_keys=True))
    decoded = ClockMapV1.from_dict(reloaded["clock_map"])
    assert clock_map_digest(decoded) == digest
    assert canonical_json(decoded.to_dict()) == canonical_json(clock_map.to_dict())
    assert reloaded["clocks"]["clock_map_sha256"] == digest


def test_the_sidecar_clock_block_fixes_the_zero_origin_placeholder() -> None:
    clock_map = _map(_session())
    block = sidecar_clock_block(clock_map)
    default = bag_schema.default_clocks(source_clock="sensor")
    assert default["recording_monotonic_origin_ns"] == 0
    assert block["recording_monotonic_origin_ns"] > 0
    assert block["recording_monotonic_origin_ns"] == min(
        relation.first_host_monotonic_ns for relation in clock_map.relations
    )


def test_sidecar_clock_block_mirrors_the_live_bag_schema() -> None:
    """Pins the mirrored key set against ``bags/schema.py`` (which PS-C may not edit)."""

    block = sidecar_clock_block(_map(_session()))
    assert bag_schema.REQUIRED_CLOCK_KEYS <= set(block)
    bag_schema.reject_privileged_fields(block, path="clocks")
    with pytest.raises(ClockRefusedError):
        sidecar_clock_block(_map(_session()), source_clock="wall")


def test_seeded_failure_one_mutated_sample_moves_the_map_digest() -> None:
    samples = _session()
    baseline = clock_map_digest(_map(samples))
    tampered = list(samples)
    original = tampered[5]
    tampered[5] = ClockSample(
        device=original.device,
        host_monotonic_ns=original.host_monotonic_ns,
        host_realtime_ns=original.host_realtime_ns,
        device_source_ns=original.device_source_ns + 1,
        round_trip_ns=original.round_trip_ns,
        host_pair_bracket_ns=original.host_pair_bracket_ns,
    )
    mutated_map = _map(tampered)
    assert clock_map_digest(mutated_map) != baseline
    assert mutated_map.sample_digest != _map(samples).sample_digest


@pytest.mark.parametrize(
    "mutation",
    [
        {"session_id": "other"},
        {"host_id": "other"},
        {"created_at_utc": "2026-08-13T09:00:01Z"},
        {"fixture_label": "other"},
        {"sample_digest": "0" * 64},
        {"does_not_prove": ["only one item"]},
    ],
)
def test_seeded_failure_the_digest_binds_every_map_field(mutation: dict[str, object]) -> None:
    clock_map = _map(_session())
    record = clock_map.to_dict()
    record.update(mutation)
    assert clock_map_digest(ClockMapV1.from_dict(record)) != clock_map_digest(clock_map)


def test_the_serialised_map_is_json_safe_and_byte_stable() -> None:
    clock_map = _map(_session(drift_ppm=40.0, step_at_elapsed_ns=450_000_000_000,
                              step_ns=500_000_000))
    once = canonical_json(clock_map.to_dict())
    twice = canonical_json(ClockMapV1.from_dict(json.loads(once)).to_dict())
    assert once == twice
    assert "NaN" not in once
    assert "Infinity" not in once


@pytest.mark.parametrize(
    "drop",
    ["schema", "session_id", "relations", "sample_digest", "does_not_prove"],
)
def test_a_missing_key_is_refused_on_decode(drop: str) -> None:
    record = _map(_session()).to_dict()
    del record[drop]
    with pytest.raises(ClockRefusedError) as excinfo:
        ClockMapV1.from_dict(record)
    assert excinfo.value.reason is ClockRefusalReason.MALFORMED_RECORD


def test_an_unexpected_key_is_refused_on_decode() -> None:
    record = _map(_session()).to_dict()
    record["surprise"] = 1
    with pytest.raises(ClockRefusedError):
        ClockMapV1.from_dict(record)


def test_a_foreign_schema_string_is_refused() -> None:
    record = _map(_session()).to_dict()
    record["schema"] = "parcel.capture.clockmap.v2"
    with pytest.raises(ClockRefusedError) as excinfo:
        ClockMapV1.from_dict(record)
    assert excinfo.value.reason is ClockRefusalReason.SCHEMA_MISMATCH
    assert CLOCK_MAP_SCHEMA == "parcel.capture.clockmap.v1"


# --------------------------------------------------------------------------- #
# Derived answers are recomputed, never trusted
# --------------------------------------------------------------------------- #


def test_hand_editing_is_certifiable_into_a_map_file_changes_nothing() -> None:
    clock_map = _map(_session()[:2])
    record = clock_map.to_dict()
    assert record["is_certifiable"] is False
    record["is_certifiable"] = True
    record["certification_shortfalls"] = []
    decoded = ClockMapV1.from_dict(record)
    assert decoded.is_certifiable is False
    assert decoded.certification_shortfalls


def test_hand_editing_an_uncertainty_total_is_refused() -> None:
    record = _map(_session()).to_dict()
    uncertainty = record["relations"][0]["segments"][0]["offset_uncertainty"]
    uncertainty["total"] = 1.0
    with pytest.raises(ClockRefusedError) as excinfo:
        ClockMapV1.from_dict(record)
    assert "not the sum of its parts" in str(excinfo.value)


def test_hand_editing_meets_schedule_against_its_shortfalls_is_refused() -> None:
    record = _map(_session()).to_dict()
    coverage = record["relations"][0]["coverage"]
    coverage["shortfalls"] = ["invented"]
    with pytest.raises(ClockRefusedError) as excinfo:
        ClockMapV1.from_dict(record)
    assert "contradicts" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# The schedule: both halves earn their place
# --------------------------------------------------------------------------- #


def test_the_planned_schedule_is_the_one_the_coverage_check_certifies() -> None:
    clock_map = _map(_session())
    for relation in clock_map.relations:
        assert relation.coverage.meets_schedule, relation.coverage.shortfalls
        assert relation.coverage.shortfalls == ()
        assert relation.coverage.start_burst_count >= DEFAULT_SCHEDULE.min_burst_samples
        assert relation.coverage.end_burst_count >= DEFAULT_SCHEDULE.min_burst_samples
        assert relation.coverage.max_gap_ns <= DEFAULT_SCHEDULE.max_cruise_gap_ns
    assert clock_map.is_certifiable


def test_end_bursts_beat_uniform_sampling_for_drift_at_equal_sample_count() -> None:
    """Why the card asks for bursts: they maximise ``sxx``, which is the drift lever."""

    duration = 900_000_000_000
    burst = planned_elapsed_ns(duration_ns=duration)
    count = len(burst)
    uniform = tuple(round(index * duration / (count - 1)) for index in range(count))
    assert len(uniform) == count

    def drift_uncertainty(plan: tuple[int, ...]) -> float:
        segment = (
            _map(
                synthesize_samples(
                    device=SourceDevice.GO2,
                    start_host_ns=START_HOST_NS,
                    start_realtime_ns=START_REALTIME_NS,
                    elapsed_ns=plan,
                    offset_ns=TRUE_OFFSET_NS,
                    drift_ppm=40.0,
                    round_trip_ns=ROUND_TRIP_NS,
                    jitter_ns=50_000,
                )
            )
            .relation_for(SourceDevice.GO2)
            .primary_segment
        )
        total = segment.drift_uncertainty.total if segment.drift_uncertainty else None
        assert total is not None
        return total

    assert drift_uncertainty(burst) < drift_uncertainty(uniform)


def test_but_bursts_alone_miss_a_mid_session_step_that_the_cruise_catches() -> None:
    """And why the card also asks for the 1 Hz cruise between them."""

    duration = 900_000_000_000
    window = DEFAULT_SCHEDULE.burst_window_ns
    bursts_only = tuple(
        sorted(
            {*range(0, window + 1, 100_000_000), *range(duration - window, duration + 1,
                                                        100_000_000)}
        )
    )

    def steps_found(plan: tuple[int, ...]) -> int:
        samples = synthesize_samples(
            device=SourceDevice.GO2,
            start_host_ns=START_HOST_NS,
            start_realtime_ns=START_REALTIME_NS,
            elapsed_ns=plan,
            offset_ns=TRUE_OFFSET_NS,
            round_trip_ns=ROUND_TRIP_NS,
            jitter_ns=50_000,
            step_at_elapsed_ns=duration // 2,
            step_ns=500_000_000,
        )
        return len(_map(samples).relation_for(SourceDevice.GO2).steps)

    assert steps_found(bursts_only) == 1
    burst_only_map = _map(
        synthesize_samples(
            device=SourceDevice.GO2,
            start_host_ns=START_HOST_NS,
            start_realtime_ns=START_REALTIME_NS,
            elapsed_ns=bursts_only,
            offset_ns=TRUE_OFFSET_NS,
            round_trip_ns=ROUND_TRIP_NS,
            jitter_ns=50_000,
            step_at_elapsed_ns=duration // 2,
            step_ns=500_000_000,
        )
    )
    # The step is found, but only to within the 880 s hole it happened in — the
    # cruise is what makes it locatable, and the coverage check says so.
    step = burst_only_map.relation_for(SourceDevice.GO2).steps[0]
    assert step.gap_ns > 800_000_000_000
    assert not burst_only_map.is_certifiable
    assert any("cannot be located" in item for item in burst_only_map.certification_shortfalls)


def test_a_missing_closing_burst_is_a_named_shortfall() -> None:
    plan = tuple(e for e in planned_elapsed_ns(duration_ns=900_000_000_000)
                 if e < 890_000_000_000)
    clock_map = _map(
        synthesize_samples(
            device=SourceDevice.GO2,
            start_host_ns=START_HOST_NS,
            start_realtime_ns=START_REALTIME_NS,
            elapsed_ns=plan,
            offset_ns=TRUE_OFFSET_NS,
            round_trip_ns=ROUND_TRIP_NS,
        )
    )
    assert not clock_map.is_certifiable
    assert any("closing burst" in item for item in clock_map.certification_shortfalls)


def test_a_short_session_is_told_it_cannot_resolve_drift() -> None:
    clock_map = _map(_session(duration_ns=60_000_000_000))
    assert not clock_map.is_certifiable
    assert any("resolve drift" in item for item in clock_map.certification_shortfalls)


def test_the_schedule_constants_are_internally_consistent() -> None:
    assert ClockSchedule() == DEFAULT_SCHEDULE
    # min_burst_samples is derived from the Student-t table flattening at 30.
    assert DEFAULT_SCHEDULE.min_burst_samples == 30
    # The burst window must accrue no more than a millisecond at the assumed
    # worst-case drift, which is what makes a burst a point measurement.
    accrued_ns = DEFAULT_SCHEDULE.burst_window_ns * 100.0 / 1e6
    assert accrued_ns <= 1_000_000.0
    assert DEFAULT_SCHEDULE.min_span_ns >= 3 * (1_000_000 / (10.0 / 1e6))


# --------------------------------------------------------------------------- #
# Conversion: what PS-B actually calls
# --------------------------------------------------------------------------- #


def test_the_host_realtime_relation_gives_the_monotonic_epoch_a_meaning() -> None:
    clock_map = _map(_session())
    relation = clock_map.host_relation
    assert relation is not None
    assert relation.kind is RelationKind.HOST_REALTIME_TO_HOST_MONOTONIC
    reading = relation.target_at(START_HOST_NS + 100_000_000_000)
    assert abs(reading.offset_ns - (START_REALTIME_NS + 100_000_000_000)) < 1_000_000
    assert reading.is_bounded


def test_a_map_without_the_host_pair_bracket_is_not_bounded_in_wall_time() -> None:
    """Unknown = absent: no measured pair bracket means no systematic bound."""

    samples = [
        ClockSample(
            device=sample.device,
            host_monotonic_ns=sample.host_monotonic_ns,
            host_realtime_ns=sample.host_realtime_ns,
            device_source_ns=sample.device_source_ns,
            round_trip_ns=sample.round_trip_ns,
            host_pair_bracket_ns=None,
        )
        for sample in _session()
    ]
    clock_map = _map(samples)
    host = clock_map.host_relation
    assert host is not None
    assert not host.is_bounded
    assert host.primary_segment.offset_uncertainty.systematic is None
    assert host.primary_segment.offset_uncertainty.total is None
    assert not clock_map.is_certifiable
    # The device relation is unaffected: its bracket is the round trip.
    assert clock_map.relation_for(SourceDevice.GO2).is_bounded


def test_converting_a_device_stamp_back_to_a_host_instant_round_trips() -> None:
    clock_map = _map(_session(drift_ppm=40.0))
    relation = clock_map.relation_for(SourceDevice.GO2)
    instant = START_HOST_NS + 400_000_000_000
    device_reading = relation.target_at(instant)
    back = relation.host_monotonic_for(device_reading.offset_ns)
    assert abs(back.host_monotonic_ns - instant) < 1000


def test_extrapolating_past_the_last_sample_widens_and_is_flagged() -> None:
    clock_map = _map(_session(drift_ppm=40.0))
    relation = clock_map.relation_for(SourceDevice.GO2)
    inside = relation.offset_at(relation.first_host_monotonic_ns + 450_000_000_000)
    outside = relation.offset_at(relation.last_host_monotonic_ns + 3_600_000_000_000)
    assert not inside.extrapolated
    assert outside.extrapolated
    inside_total = inside.uncertainty.total
    outside_total = outside.uncertainty.total
    assert inside_total is not None
    assert outside_total is not None
    assert outside_total > 10 * inside_total


def test_an_instant_inside_a_step_gap_is_ambiguous_by_the_step() -> None:
    duration = 900_000_000_000
    clock_map = _map(
        _session(duration_ns=duration, step_at_elapsed_ns=duration // 2, step_ns=500_000_000)
    )
    relation = clock_map.relation_for(SourceDevice.GO2)
    step = relation.steps[0]
    at_gap = relation.offset_at(step.at_host_monotonic_ns)
    clear = relation.offset_at(step.at_host_monotonic_ns - 100_000_000_000)
    assert at_gap.at_step_boundary
    assert not clear.at_step_boundary
    assert (at_gap.uncertainty.systematic or 0) > (clear.uncertainty.systematic or 0)


def test_a_multi_device_session_gets_one_relation_per_device() -> None:
    samples = [
        *_session(device=SourceDevice.GO2),
        *_session(device=SourceDevice.D455, drift_ppm=-15.0, seed=7),
        *_session(device=SourceDevice.L2, drift_ppm=80.0, seed=8),
    ]
    clock_map = _map(samples)
    assert clock_map.devices == (SourceDevice.D455, SourceDevice.GO2, SourceDevice.L2)
    assert clock_map.relation_for(SourceDevice.D455).primary_segment.drift_ppm == pytest.approx(
        -15.0, abs=DRIFT_TOLERANCE_PPM
    )
    assert clock_map.relation_for(SourceDevice.L2).primary_segment.drift_ppm == pytest.approx(
        80.0, abs=DRIFT_TOLERANCE_PPM
    )
    # And a single pooled host relation, not one per device.
    host_relations = [
        relation
        for relation in clock_map.relations
        if relation.kind is RelationKind.HOST_REALTIME_TO_HOST_MONOTONIC
    ]
    assert len(host_relations) == 1
    assert host_relations[0].sample_count == len(samples)


# --------------------------------------------------------------------------- #
# The live probe path
# --------------------------------------------------------------------------- #


class _ScriptedClock:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)
        self.calls: list[str] = []

    def monotonic(self) -> int:
        self.calls.append("monotonic")
        return self.values.pop(0)

    def realtime(self) -> int:
        self.calls.append("realtime")
        return START_REALTIME_NS


def test_interrogate_brackets_the_device_read_in_the_only_honest_order() -> None:
    clock = _ScriptedClock([1_000_000_000, 1_000_000_400, 1_002_000_000])
    reads: list[str] = []

    def read_device() -> int:
        reads.append("device")
        clock.calls.append("device")
        return 500_000_000

    sample = interrogate(
        SourceDevice.GO2,
        read_device,
        now_monotonic_ns=clock.monotonic,
        now_realtime_ns=clock.realtime,
    )
    assert clock.calls == ["monotonic", "realtime", "monotonic", "device", "monotonic"]
    assert sample.host_monotonic_ns == 1_000_000_000
    assert sample.round_trip_ns == 2_000_000
    assert sample.host_pair_bracket_ns == 400
    assert sample.host_mid_ns == 1_001_000_000
    assert sample.offset_ns == 500_000_000 - 1_001_000_000
    assert sample.bracket_ns == 1_000_000.0


def test_a_failed_device_read_produces_no_sample_at_all() -> None:
    def broken() -> int:
        raise OSError("device busy")

    with pytest.raises(ClockProbeError) as excinfo:
        interrogate(SourceDevice.D455, broken)
    assert "no sample recorded" in str(excinfo.value)


def test_a_device_read_returning_a_float_is_refused_not_rounded() -> None:
    with pytest.raises(ClockRefusedError) as excinfo:
        interrogate(SourceDevice.D455, lambda: 1.5)  # type: ignore[arg-type,return-value]
    assert excinfo.value.reason is ClockRefusalReason.NON_INTEGER_FIELD


def test_the_sample_log_survives_a_line_at_a_time_and_refuses_a_bad_line(
    tmp_path: Path,
) -> None:
    path = tmp_path / "clock_samples.jsonl"
    samples = _session()[:20]
    for sample in samples:
        append_sample_jsonl(path, sample)
    assert read_samples_jsonl(path) == samples

    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"schema": "parcel.capture.clocksample.v1", "device": "go2"}\n')
    with pytest.raises(ClockRefusedError) as excinfo:
        read_samples_jsonl(path)
    assert f"{path}:21" in str(excinfo.value)

    truncated = tmp_path / "truncated.jsonl"
    truncated.write_text(canonical_json(samples[0].to_dict())[:40], encoding="utf-8")
    with pytest.raises(ClockRefusedError) as excinfo:
        read_samples_jsonl(truncated)
    assert "not JSON" in str(excinfo.value)


def test_the_sample_schema_string_is_pinned() -> None:
    assert CLOCK_SAMPLE_SCHEMA == "parcel.capture.clocksample.v1"
    record = _session()[0].to_dict()
    record["schema"] = "something.else"
    with pytest.raises(ClockRefusedError) as excinfo:
        ClockSample.from_dict(record)
    assert excinfo.value.reason is ClockRefusalReason.SCHEMA_MISMATCH


def test_the_go2_probe_declares_that_no_interrogation_exists() -> None:
    """PS-I correction. The dog has no queryable clock and the record says so.

    The PS-1 text claimed `tick` was a clock read. It is a wrapping counter with
    an arbitrary epoch, and `lowstate` carries no timestamp at all — so there is
    no interrogation to run and `--check` must not imply there is one.
    """

    requirement = PROBE_REQUIREMENTS[SourceDevice.GO2]
    assert requirement.interrogable is False
    assert "RITUAL ONLY" in requirement.method
    assert "syncevents" in requirement.method
    # Every other device still claims an interrogation, so the flag is a
    # statement about the Go2 and not a blanket downgrade.
    for device in (SourceDevice.D455, SourceDevice.L2, SourceDevice.ORIN):
        assert PROBE_REQUIREMENTS[device].interrogable is True


def test_fit_relation_matches_the_map_it_is_carved_out_of() -> None:
    """The public per-pair fitter PS-I feeds: same numbers, no second fitter."""

    samples = _session()
    relation = fit_relation(samples, device=SourceDevice.GO2)
    from_map = _map(samples).relation_for(SourceDevice.GO2)
    assert relation.to_dict() == from_map.to_dict()


def test_explicit_splits_replace_the_scan_and_are_bounds_checked() -> None:
    """PS-I hands in a segmentation established by a stronger test; a split that
    would leave an unfittable segment is refused rather than quietly clamped."""

    duration = 900_000_000_000
    samples = _session(duration_ns=duration, drift_ppm=40.0)
    forced = fit_relation(samples, device=SourceDevice.GO2, splits=[len(samples) // 2])
    assert len(forced.segments) == 2
    assert len(fit_relation(samples, device=SourceDevice.GO2, splits=[]).segments) == 1
    for bad in (0, 1, len(samples), len(samples) - 1, -3):
        with pytest.raises(ClockRefusedError) as excinfo:
            fit_relation(samples, device=SourceDevice.GO2, splits=[bad])
        assert excinfo.value.reason is ClockRefusalReason.MALFORMED_RECORD
    with pytest.raises(ClockRefusedError):
        fit_relation(samples, device=SourceDevice.GO2, splits=[2.5])  # type: ignore[list-item]


def test_fit_relation_refuses_a_mixed_device_batch() -> None:
    mixed = [*_session()[:5], *_session(device=SourceDevice.D455)[:5]]
    with pytest.raises(ClockRefusedError) as excinfo:
        fit_relation(mixed, device=SourceDevice.GO2)
    assert excinfo.value.reason is ClockRefusalReason.DEVICE_NOT_TYPED
    with pytest.raises(ClockRefusedError) as empty:
        fit_relation([], device=SourceDevice.GO2)
    assert empty.value.reason is ClockRefusalReason.NO_SAMPLES


def test_the_public_t_factor_is_the_table_every_estimate_uses() -> None:
    assert t_critical_95(1) == 12.706
    assert t_critical_95(30) == 2.042
    # The lookup takes the largest LISTED dof at or below the request, so a huge
    # sample stops at the 120-dof row rather than reaching the 1.960 asymptote —
    # over-estimating t, which is the conservative direction.
    assert t_critical_95(10_000) == 1.980
    # It decreases with dof and the lookup is conservative in the safe direction.
    assert t_critical_95(4) > t_critical_95(9) > t_critical_95(60)
    with pytest.raises(ClockRefusedError):
        t_critical_95(0)


def test_probe_availability_fails_closed_on_this_hardwareless_dev_box() -> None:
    availability = probe_availability()
    assert set(availability) == set(PROBE_REQUIREMENTS)
    for device in (SourceDevice.GO2, SourceDevice.D455, SourceDevice.L2):
        satisfied, present = availability[device]
        assert satisfied is False, f"{device} claims a probe this box cannot run"
        assert present == ()
    # The Orin needs no SDK: it IS the host.
    assert availability[SourceDevice.ORIN][0] is True


# --------------------------------------------------------------------------- #
# Read-only, leaf, dual-Python, CLI
# --------------------------------------------------------------------------- #

_FORBIDDEN_SYMBOLS = frozenset(
    {
        "create_publisher",
        "Publisher",
        "ControlManager",
        "create_control_manager",
        "set_target",
        "Move",
        "SportClient",
        "MotionSwitcher",
        "acquire_lease",
        "Lease",
        "arm",
    }
)
_FORBIDDEN_IMPORTS = frozenset(
    {
        "rclpy",
        "unitree_sdk2py",
        "pyrealsense2",
        "cyclonedds",
        "cv2",
        "mcap",
        "parcel_robot.runtime",
        "parcel_robot.control",
        "parcel_robot.navigation",
        "parcel_robot.pose",
    }
)


def _identifiers(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
    return found


def _imported_modules(tree: ast.AST) -> set[str]:
    """Every imported module AND its dotted prefixes.

    Without the prefixes ``from unitree_sdk2py.go2.sport.sport_client import
    SportClient`` walks straight past a pin that only knows ``unitree_sdk2py``
    — which is exactly what the seeded-failure cell below caught on the first
    run of this file.
    """

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    found: set[str] = set()
    for name in names:
        parts = name.split(".")
        found.update(".".join(parts[: index + 1]) for index in range(len(parts)))
    return found


def test_no_symbol_in_the_clock_map_can_reach_a_motion_surface() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    assert not (_identifiers(tree) & _FORBIDDEN_SYMBOLS)
    assert not (_imported_modules(tree) & _FORBIDDEN_IMPORTS)
    # No dynamic import either: the vendor SDK names appear ONLY as strings fed
    # to find_spec, which is a path lookup and never executes a module.
    assert "import_module" not in _identifiers(tree)
    assert "__import__" not in _identifiers(tree)


@pytest.mark.parametrize(
    "mutant",
    [
        "import rclpy\n",
        "from unitree_sdk2py.go2.sport.sport_client import SportClient\n",
        "def create_publisher(topic):\n    return topic\n",
        "client = ControlManager()\n",
        "handle = importlib.import_module('unitree_sdk2py')\n",
        "import parcel_robot.runtime\n",
    ],
)
def test_seeded_failure_the_read_only_pin_catches_a_module_that_could_speak(
    mutant: str,
) -> None:
    tree = ast.parse(mutant)
    caught = bool(_identifiers(tree) & _FORBIDDEN_SYMBOLS) or bool(
        _imported_modules(tree) & _FORBIDDEN_IMPORTS
    )
    caught = caught or "import_module" in _identifiers(tree)
    assert caught, f"the pin would not have caught: {mutant!r}"


def test_the_pin_does_not_fire_on_the_legitimate_vendor_sensor_names() -> None:
    """Negative control: a scan that fires on everything proves nothing."""

    benign = ast.parse(
        "modules = ('unitree_lidar_sdk_pybind', 'wirelesscontroller')\n"
        "method = 'read tick off a lowstate message'\n"
    )
    assert not (_identifiers(benign) & _FORBIDDEN_SYMBOLS)
    assert not (_imported_modules(benign) & _FORBIDDEN_IMPORTS)


def test_the_module_parses_as_python_310() -> None:
    """The Orin runs JetPack 6.2.x: Python 3.10. This host has only 3.14."""

    source = MODULE_PATH.read_text(encoding="utf-8")
    ast.parse(source, filename=str(MODULE_PATH), feature_version=(3, 10))
    for post_310 in ("StrEnum", "tomllib", "file_digest", "itertools.batched", "ExceptionGroup"):
        assert post_310 not in source


def test_the_310_parse_check_really_rejects_newer_syntax() -> None:
    """Negative control for the cell above."""

    for mutant in ("type Alias = int\n", "def f[T](x: T) -> T:\n    return x\n"):
        with pytest.raises(SyntaxError):
            ast.parse(mutant, feature_version=(3, 10))
    ast.parse("x = 1\n", feature_version=(3, 10))


def test_the_module_imports_nothing_outside_stdlib_and_parcel_robot() -> None:
    probe = (
        "import sys, json;"
        "before=set(sys.modules);"
        "import scripts.parcel_capture.clockmap;"
        "added=sorted(set(sys.modules)-before);"
        "print(json.dumps([m for m in added if m.split('.',1)[0] "
        "not in sys.stdlib_module_names and not m.startswith('parcel_robot') "
        "and not m.startswith('scripts')]))"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout.strip()) == []


def test_the_cli_refuses_cleanly_with_no_hardware_and_no_traceback() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.parcel_capture.clockmap", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stdout + result.stderr
    assert "REFUSED" in result.stdout
    assert "permanently unrecoverable" in result.stdout


def test_the_cli_runs_as_a_plain_script_with_no_pythonpath() -> None:
    """The Orin invocation: no editable install, no PYTHONPATH, no traceback."""

    result = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--selftest", "--json"],
        cwd="/",
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    decoded = ClockMapV1.from_dict(json.loads(result.stdout))
    assert decoded.origin is EvidenceOrigin.SIMULATION
    assert decoded.fixture_label == "clockmap-selftest"
    assert decoded.is_certifiable


def test_the_cli_refuses_a_fit_that_cannot_name_its_session(tmp_path: Path) -> None:
    path = tmp_path / "samples.jsonl"
    for sample in _session()[:5]:
        append_sample_jsonl(path, sample)
    result = subprocess.run(
        [sys.executable, "-m", "scripts.parcel_capture.clockmap", "--fit", str(path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "REFUSED" in result.stderr
    assert "Traceback" not in result.stderr


def test_the_cli_fits_a_recorded_log_and_reports_uncertifiable_as_exit_1(
    tmp_path: Path,
) -> None:
    path = tmp_path / "samples.jsonl"
    for sample in _session()[:5]:
        append_sample_jsonl(path, sample)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.parcel_capture.clockmap",
            "--fit",
            str(path),
            "--session-id",
            "P5-DRY-20260813-01",
            "--host-id",
            "orin-nx-01",
            "--created-at",
            "2026-08-13T09:00:00Z",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "SHORTFALL" in result.stdout
    assert "Traceback" not in result.stderr


def test_the_report_states_a_unit_and_never_mixes_them() -> None:
    duration = 900_000_000_000
    report = format_report(
        _map(
            _session(duration_ns=duration, drift_ppm=40.0, step_at_elapsed_ns=duration // 2,
                     step_ns=500_000_000)
        )
    )
    assert "ppm" in report
    assert "two-sided-95" in report
    assert "STEP at" in report
    assert "does_not_prove" in report
    # The offset and its uncertainty are both in ms, so the ± is comparable.
    offset_line = next(line for line in report.splitlines() if "offset@ref" in line)
    assert offset_line.count("ms") == 1
    assert "± 1.0" in offset_line


def test_the_map_carries_a_non_empty_does_not_prove() -> None:
    clock_map = _map(_session())
    assert len(clock_map.does_not_prove) >= 5
    with pytest.raises(ClockRefusedError) as excinfo:
        _map(_session(), does_not_prove=())
    assert excinfo.value.reason is ClockRefusalReason.EMPTY_FIELD


def test_min_segment_samples_is_the_smallest_fittable_segment() -> None:
    assert MIN_SEGMENT_SAMPLES == 3
    # dof = n - 2, so n = 3 is the first segment with a residual degree of
    # freedom; the fit basis proves the boundary rather than restating it.
    for count, expected in ((2, FitBasis.TWO_POINT), (3, FitBasis.OLS)):
        samples = [
            ClockSample(
                device=SourceDevice.GO2,
                host_monotonic_ns=START_HOST_NS + index * 1_000_000_000,
                host_realtime_ns=START_REALTIME_NS + index * 1_000_000_000,
                device_source_ns=START_HOST_NS + index * 1_000_000_000 + TRUE_OFFSET_NS,
                round_trip_ns=ROUND_TRIP_NS,
                host_pair_bracket_ns=200,
            )
            for index in range(count)
        ]
        segment = _map(samples).relation_for(SourceDevice.GO2).primary_segment
        assert segment.basis is expected
