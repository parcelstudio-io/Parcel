"""Card PS-I — bracketed physical sync events. Gates for ``syncevents.py``.

Every property cell is paired with a seeded-failure companion: the refutation
shows what the property is buying, because "the fit returned 40 ppm" proves
nothing on its own if a broken estimator would have returned it too.

The card's four seeded gates and where they live:

* 500 ms step detected AS A STEP, not smoothed into the drift fit —
  ``test_a_seeded_500ms_step_between_rituals_is_reported_as_a_step`` plus the
  refutation ``test_seeded_failure_a_single_line_fit_turns_the_step_into_drift``
  and the honesty cell ``test_two_brackets_alone_cannot_locate_a_step_and_say_so``
* 40 ppm drift recovered within a stated tolerance —
  ``test_a_seeded_40_ppm_drift_is_recovered_within_a_stated_tolerance`` plus
  ``test_the_drift_interval_covers_the_truth_across_seeds`` and the scaling law
  ``test_the_drift_resolution_is_bracket_over_half_span``
* a modality that misses 2 of 5 flashes still yields an offset, WIDER —
  ``test_missing_two_of_five_flashes_widens_the_uncertainty``
* no matched events yields UNKNOWN, never a fabricated zero —
  ``test_a_ritual_with_no_matched_events_is_unknown_never_zero``

Plus the three things the card said to KEEP from PS-C: fail-closed refusals on
every clock field, uncertainty that widens rather than narrows, and a sidecar
round-trip by digest.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from parcel_robot.bags import schema as bag_schema
from parcel_robot.capture.channels import CaptureError, SourceDevice
from parcel_robot.evidence_origin import EvidenceOrigin
from scripts.parcel_capture.clockmap import (
    ClockRefusedError,
    ClockSample,
    Uncertainty,
    canonical_json,
)
from scripts.parcel_capture.syncevents import (
    DEFAULT_SYNC_DOES_NOT_PROVE,
    MAX_EVENTS_PER_TRAIN,
    RITUAL_SCRIPT,
    SELFTEST_COUNTER_START_NS,
    SELFTEST_HOST_START_NS,
    SYNC_EVENT_SCHEMA,
    SYNC_FIT_SCHEMA,
    SYNC_TRAIN_SCHEMA,
    TICK_MODULUS_MS,
    TORCH_FLASH_COUNT,
    TORCH_FLASH_GAPS_S,
    WIRELESS_REMOTE_KEY_OFFSET_UNVERIFIED,
    WIRELESS_REMOTE_LENGTH,
    EventKind,
    EventTrain,
    MatchStatus,
    Ritual,
    SyncError,
    SyncEvent,
    SyncFitV1,
    SyncRefusalReason,
    SyncRefusedError,
    TimeDomain,
    append_train_jsonl,
    build_selftest_fit,
    build_sync_fit,
    button_series_from_wireless_remote,
    detect_accel_spikes,
    detect_brightness_steps,
    detect_button_edges,
    detect_gyro_onsets,
    estimate_pair_offset,
    events_digest,
    format_report,
    format_ritual_card,
    magnitudes_from_xyz,
    match_trains,
    merge_trains,
    pair_clock_samples,
    read_trains_jsonl,
    selftest_rituals,
    sidecar_sync_block,
    sync_fit_digest,
    synthesize_lowstate_ritual,
    synthesize_ritual_series,
    unwrap_tick_ms,
    wireless_remote_keys,
)

REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "scripts" / "parcel_capture" / "syncevents.py"

TRUE_DRIFT_PPM = 40.0
TRUE_OFFSET_NS = SELFTEST_COUNTER_START_NS - SELFTEST_HOST_START_NS
#: Stated tolerance for the drift gate, DERIVED not chosen: the systematic floor
#: of a bracketed design is ``bracket / half-span`` (see
#: ``test_the_drift_resolution_is_bracket_over_half_span``), which for a 4 ms
#: combined bracket over a 3600 s session is 2.2 ppm. 4 ppm is that plus margin
#: for the estimator's own error.
DRIFT_TOLERANCE_PPM = 4.0


def _fit(**kwargs: object) -> SyncFitV1:
    return build_selftest_fit(**kwargs)


# --------------------------------------------------------------------------- #
# The defect this card exists to fix, pinned at source
# --------------------------------------------------------------------------- #


def test_the_dog_still_cannot_be_interrogated_and_the_matrix_says_so() -> None:
    """The PS-C mechanism is impossible for the Go2. Pinned, not remembered."""

    from parcel_robot.capture.channels import CHANNELS_BY_ID
    from scripts.parcel_capture.clockmap import PROBE_REQUIREMENTS

    lowstate = CHANNELS_BY_ID["go2.lowstate"]
    assert lowstate.nominal_rate_hz == 500.0
    assert lowstate.source_clock.value == "wrapping_counter"
    assert lowstate.source_clock.is_usable_anchor is False
    assert PROBE_REQUIREMENTS[SourceDevice.GO2].interrogable is False
    # And both mandatory ClockSample clock fields still refuse None, which is
    # why an interrogation-shaped sample can never be built for this channel.
    for field in ("device_source_ns", "round_trip_ns"):
        kwargs = {
            "device": SourceDevice.GO2,
            "host_monotonic_ns": 1_000_000,
            "host_realtime_ns": 1_786_000_000_000_000_000,
            "device_source_ns": 1_000_000,
            "round_trip_ns": 2_000_000,
        }
        kwargs[field] = None
        with pytest.raises(ClockRefusedError):
            ClockSample(**kwargs)  # type: ignore[arg-type]


def test_a_train_cannot_claim_a_device_clock_the_matrix_denies() -> None:
    """The fiction that made ClockMapV1 unpopulatable, refused at the type level."""

    with pytest.raises(SyncRefusedError) as excinfo:
        EventTrain(
            channel_id="go2.lowstate",
            device=SourceDevice.GO2,
            domain=TimeDomain.DEVICE_TIMESPEC,
            detector="detect_accel_spikes",
            ritual="SYNC-OPEN",
            events=(),
        )
    assert excinfo.value.reason is SyncRefusalReason.DOMAIN_MISMATCH
    # The same channel in the domain it really has is accepted.
    EventTrain(
        channel_id="go2.lowstate",
        device=SourceDevice.GO2,
        domain=TimeDomain.UNWRAPPED_COUNTER,
        detector="detect_accel_spikes",
        ritual="SYNC-OPEN",
        events=(),
    )


def test_a_train_on_a_channel_nobody_records_is_refused() -> None:
    with pytest.raises(SyncRefusedError) as excinfo:
        EventTrain(
            channel_id="go2.imaginary",
            device=SourceDevice.GO2,
            domain=TimeDomain.HOST_RECEIPT,
            detector="d",
            ritual="R",
            events=(),
        )
    assert excinfo.value.reason is SyncRefusalReason.UNKNOWN_CHANNEL


def test_a_train_labelled_with_the_wrong_device_is_refused() -> None:
    with pytest.raises(SyncRefusedError) as excinfo:
        EventTrain(
            channel_id="go2.lowstate",
            device=SourceDevice.D455,
            domain=TimeDomain.HOST_RECEIPT,
            detector="d",
            ritual="R",
            events=(),
        )
    assert excinfo.value.reason is SyncRefusalReason.DEVICE_MISMATCH


# --------------------------------------------------------------------------- #
# GATE 1 — a step is a step, not drift
# --------------------------------------------------------------------------- #


#: Four rituals — SYNC-OPEN, two mid-session (the run sheet asks for one at
#: every battery swap) and SYNC-CLOSE. Four is not decoration: a step model has
#: three parameters, so localising a step to a GAP needs a fourth offset to
#: leave a residual degree of freedom. Three rituals detect the step and cannot
#: place it, which the honesty cell below asserts.
_FOUR = ("SYNC-OPEN", "SYNC-SWAP-1", "SYNC-SWAP-2", "SYNC-CLOSE")


def test_a_seeded_500ms_step_between_rituals_is_reported_as_a_step() -> None:
    fit = build_selftest_fit(labels=_FOUR, step_ns=500_000_000, step_from_ritual=3)
    assert len(fit.steps) == 1, format_report(fit)
    step = fit.steps[0]
    assert abs(step.magnitude_ns - 500_000_000) < 5_000_000
    assert step.uncertainty_ns < 20_000_000
    assert abs(step.magnitude_ns) > step.uncertainty_ns
    # Located to the right gap...
    assert step.localizable is True
    assert (step.before_ritual, step.after_ritual) == ("SYNC-SWAP-2", "SYNC-CLOSE")
    # ...and NOT smoothed into the drift: the relation is segmented there, and
    # the drift of the segment that carries the session is still the truth.
    assert len(fit.relation.segments) == 2
    drift = fit.drift_ppm
    assert drift is not None
    assert abs(drift - TRUE_DRIFT_PPM) <= DRIFT_TOLERANCE_PPM, format_report(fit)


def test_a_step_in_a_middle_gap_is_placed_in_that_gap() -> None:
    fit = build_selftest_fit(labels=_FOUR, step_ns=500_000_000, step_from_ritual=2)
    step = fit.steps[0]
    assert (step.before_ritual, step.after_ritual) == ("SYNC-SWAP-1", "SYNC-SWAP-2")
    assert abs(step.magnitude_ns - 500_000_000) < 5_000_000


def test_seeded_failure_a_single_line_fit_turns_the_step_into_drift() -> None:
    """The refutation: without the step model the same data lies about the drift."""

    fit = build_selftest_fit(labels=_FOUR, step_ns=500_000_000, step_from_ritual=3)
    xs = [offset.epoch_ns / 1e9 for offset in fit.ritual_offsets]
    ys = [float(offset.offset_ns) for offset in fit.ritual_offsets]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    sxx = sum((x - x_mean) ** 2 for x in xs)
    naive_ppm = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / sxx / 1000.0
    stepped = fit.drift_ppm
    assert stepped is not None
    assert abs(naive_ppm - TRUE_DRIFT_PPM) > 10 * abs(stepped - TRUE_DRIFT_PPM), (
        f"naive={naive_ppm} stepped={stepped}"
    )
    assert naive_ppm > 100.0, "the seeded step really would have become drift"


def test_three_rituals_detect_the_step_but_refuse_to_locate_it() -> None:
    """The honest limit: three offsets fit a three-parameter step model exactly,
    so every gap explains them equally well and none may be named."""

    fit = build_selftest_fit(
        labels=("SYNC-OPEN", "SYNC-MID", "SYNC-CLOSE"),
        step_ns=500_000_000,
        step_from_ritual=2,
    )
    assert len(fit.steps) == 1
    step = fit.steps[0]
    assert abs(step.magnitude_ns - 500_000_000) < 5_000_000  # the SIZE is known
    assert step.localizable is False  # the PLACE is not
    assert step.after_ritual is None
    assert step.gap_ns is None
    assert "battery swap" in step.detail
    # An unplaceable step cannot be segmented out, so the drift stays aliased and
    # the fit says it is not certifiable rather than quoting the aliased number.
    assert len(fit.relation.segments) == 1
    assert fit.is_certifiable is False
    assert any("not identifiable" in item for item in fit.shortfalls)


def test_two_brackets_alone_cannot_locate_a_step_and_say_so() -> None:
    """The honest limit of a bracketed design, asserted rather than hoped for.

    With events only at the two ends, a step between them is indistinguishable
    from drift IN PRINCIPLE. The module must not claim a step it cannot see, and
    must name the interval it could not look inside.
    """

    fit = _fit(step_ns=500_000_000, step_from_ritual=1)
    assert fit.steps == ()
    assert len(fit.blind_intervals) == 1
    assert fit.blind_intervals[0].duration_ns > 3_000_000_000_000
    assert any("aliased into the drift" in caveat for caveat in fit.caveats)
    # And the aliasing is real: 500 ms over 3600 s is ~139 ppm on top of 40.
    drift = fit.drift_ppm
    assert drift is not None
    assert abs(drift - (TRUE_DRIFT_PPM + 500_000_000 / 3_600_000_000_000 * 1e6)) < 5.0


def test_a_clean_session_produces_no_spurious_step() -> None:
    """Negative control: a detector that fires on everything proves nothing."""

    for labels in (_FOUR, ("SYNC-OPEN", "SYNC-MID", "SYNC-CLOSE")):
        clean = build_selftest_fit(labels=labels)
        assert clean.steps == (), clean.step_test_detail
        assert len(clean.relation.segments) == 1
        assert clean.is_certifiable
    assert _fit().steps == ()


# --------------------------------------------------------------------------- #
# GATE 2 — drift, with a stated tolerance
# --------------------------------------------------------------------------- #


def test_a_seeded_40_ppm_drift_is_recovered_within_a_stated_tolerance() -> None:
    fit = _fit()
    drift = fit.drift_ppm
    assert drift is not None
    assert abs(drift - TRUE_DRIFT_PPM) <= DRIFT_TOLERANCE_PPM, format_report(fit)
    segment = fit.primary_segment
    assert segment.drift_uncertainty is not None
    total = segment.drift_uncertainty.total
    assert total is not None and total > 0.0
    assert abs(drift - TRUE_DRIFT_PPM) <= total, "the interval must cover the truth"


def test_no_estimate_is_ever_a_bare_number() -> None:
    fit = _fit()
    for offset in fit.ritual_offsets:
        assert offset.uncertainty.is_bounded
        assert offset.uncertainty.systematic is not None and offset.uncertainty.systematic > 0
        assert offset.uncertainty.statistical is not None
        assert offset.uncertainty.confidence == "two-sided-95"
    segment = fit.primary_segment
    assert segment.offset_uncertainty.is_bounded
    assert segment.drift_uncertainty is not None and segment.drift_uncertainty.is_bounded


@pytest.mark.parametrize("seed_span", [1_800_000_000_000, 3_600_000_000_000, 7_200_000_000_000])
def test_the_drift_interval_covers_the_truth_across_seeds(seed_span: int) -> None:
    fit = _fit(session_span_ns=seed_span)
    segment = fit.primary_segment
    assert segment.drift_ppm is not None and segment.drift_uncertainty is not None
    total = segment.drift_uncertainty.total
    assert total is not None
    assert abs(segment.drift_ppm - TRUE_DRIFT_PPM) <= total


def test_the_drift_resolution_is_bracket_over_half_span() -> None:
    """The scaling law that sets the tolerance above, measured rather than argued.

    The systematic half of the drift uncertainty is ``bracket / half-span`` and
    therefore does NOT shrink with more ritual events — only with a longer
    session or a faster channel. Doubling the span must roughly halve it.
    """

    short = _fit(session_span_ns=1_800_000_000_000).primary_segment.drift_uncertainty
    long = _fit(session_span_ns=3_600_000_000_000).primary_segment.drift_uncertainty
    assert short is not None and long is not None
    assert short.systematic is not None and long.systematic is not None
    ratio = short.systematic / long.systematic
    assert 1.8 < ratio < 2.2, f"expected ~2x, got {ratio}"


def test_a_single_ritual_yields_an_offset_but_names_its_missing_bracket() -> None:
    fit = _fit(labels=("SYNC-OPEN",))
    assert fit.ritual_count == 1
    assert fit.is_certifiable is False
    assert any("no second bracket" in item for item in fit.shortfalls)
    assert any("under the" in item for item in fit.shortfalls)


# --------------------------------------------------------------------------- #
# GATE 3 — a partial modality still yields an offset, WIDER
# --------------------------------------------------------------------------- #


def _flash_train(
    *,
    channel_id: str,
    device: SourceDevice,
    ritual: str,
    keep: tuple[int, ...],
    offset_ns: int = 0,
    seed: int = 3,
) -> EventTrain:
    base = 40_000_000_000
    flashes = [
        base + int(sum(TORCH_FLASH_GAPS_S[:n]) * 1e9)
        for n in range(TORCH_FLASH_COUNT)
        if n in keep
    ]
    times, values, realtimes = synthesize_ritual_series(
        kind=EventKind.BRIGHTNESS_STEP,
        event_times_ns=flashes,
        start_ns=base - 2_000_000_000,
        end_ns=base + 12_000_000_000,
        rate_hz=30.0,
        channel_offset_ns=offset_ns,
        feature_width_ns=300_000_000,
        baseline=10.0,
        amplitude=180.0,
        noise=2.0,
        time_jitter_ns=2_000_000,
        seed=seed,
        host_realtime_base_ns=1_786_000_000_000_000_000,
    )
    return EventTrain(
        channel_id=channel_id,
        device=device,
        domain=TimeDomain.HOST_RECEIPT,
        detector="detect_brightness_steps",
        ritual=ritual,
        events=detect_brightness_steps(
            times, values, low_level=40.0, high_level=120.0, realtimes_ns=realtimes
        ),
    )


def test_missing_two_of_five_flashes_widens_the_uncertainty() -> None:
    reference = _flash_train(
        channel_id="d455.color", device=SourceDevice.D455, ritual="SYNC-OPEN", keep=(0, 1, 2, 3, 4)
    )
    full = _flash_train(
        channel_id="go2.front_camera",
        device=SourceDevice.GO2,
        ritual="SYNC-OPEN",
        keep=(0, 1, 2, 3, 4),
        offset_ns=17_000_000,
        seed=9,
    )
    partial = _flash_train(
        channel_id="go2.front_camera",
        device=SourceDevice.GO2,
        ritual="SYNC-OPEN",
        keep=(0, 2, 4),
        offset_ns=17_000_000,
        seed=9,
    )
    full_match = match_trains(reference, full)
    partial_match = match_trains(reference, partial)
    assert full_match.status is MatchStatus.MATCHED
    assert partial_match.status is MatchStatus.MATCHED, partial_match.detail

    full_offset = estimate_pair_offset(full_match, reference, full)
    partial_offset = estimate_pair_offset(partial_match, reference, partial)

    # 1. An offset IS still produced from what matched.
    assert partial_offset.matched_count == 6  # three flashes, rising + falling
    assert partial_offset.expected_count == 10
    assert abs(partial_offset.offset_ns - 17_000_000) < 40_000_000

    # 2. It is WIDER, in both halves and in total.
    assert partial_offset.uncertainty.total > full_offset.uncertainty.total
    assert partial_offset.uncertainty.systematic > full_offset.uncertainty.systematic
    # Both halves widen: fewer samples inflate the Student-t interval, and the
    # dropout penalty inflates the bracket bound. Neither alone carries the gate.
    assert partial_offset.uncertainty.statistical > full_offset.uncertainty.statistical
    assert full_offset.uncertainty.statistical > 0.0
    assert partial_offset.dropout_penalty_ns > 0.0
    assert full_offset.dropout_penalty_ns == 0.0

    # 3. The reason is on the record, not inferred by the reader.
    assert any("were not matched" in caveat for caveat in partial_offset.caveats)

    # 4. And the widening reaches the ClockSample brackets, so a downstream fit
    #    inherits it rather than re-deriving a narrower one. (Shown on the
    #    lowstate pair, because two host-stamped camera streams deliberately
    #    cannot produce ClockSamples at all — see the transport-delay cell.)
    host, counter = synthesize_lowstate_ritual(
        ritual="SYNC-OPEN",
        host_start_ns=SELFTEST_HOST_START_NS,
        host_realtime_start_ns=1_786_000_000_000_000_000,
        counter_start_ns=SELFTEST_COUNTER_START_NS,
        jitter_ns=200_000,
        seed=4,
    )
    lowstate_match = match_trains(host, counter)
    wide = pair_clock_samples(
        lowstate_match, host, counter, host_pair_bracket_ns=200,
        dropout_penalty_ns=partial_offset.dropout_penalty_ns,
    )
    narrow = pair_clock_samples(
        lowstate_match, host, counter, host_pair_bracket_ns=200, dropout_penalty_ns=0.0
    )
    assert min(a.bracket_ns - b.bracket_ns for a, b in zip(wide, narrow)) > 0


def test_seeded_failure_dropping_the_penalty_would_hide_the_dropout() -> None:
    """The refutation: without the dropout term the two answers are indistinguishable."""

    reference = _flash_train(
        channel_id="d455.color", device=SourceDevice.D455, ritual="SYNC-OPEN", keep=(0, 1, 2, 3, 4)
    )
    partial = _flash_train(
        channel_id="go2.front_camera",
        device=SourceDevice.GO2,
        ritual="SYNC-OPEN",
        keep=(0, 2, 4),
        offset_ns=17_000_000,
        seed=9,
    )
    offset = estimate_pair_offset(match_trains(reference, partial), reference, partial)
    without_penalty = Uncertainty(
        unit="ns",
        systematic=offset.uncertainty.systematic - offset.dropout_penalty_ns,
        statistical=offset.uncertainty.statistical,
    )
    assert without_penalty.total < offset.uncertainty.total
    assert offset.dropout_penalty_ns > 1_000_000, "a penalty under a ms would be decorative"


def test_a_modality_that_saw_only_one_event_reports_an_unbounded_offset() -> None:
    reference = _flash_train(
        channel_id="d455.color", device=SourceDevice.D455, ritual="SYNC-OPEN", keep=(0, 1, 2, 3, 4)
    )
    one = _flash_train(
        channel_id="go2.front_camera",
        device=SourceDevice.GO2,
        ritual="SYNC-OPEN",
        keep=(3,),
        offset_ns=17_000_000,
        seed=9,
    )
    match = match_trains(one, reference)  # one event against many: cannot be placed
    assert match.status is MatchStatus.AMBIGUOUS
    assert match.offset_ns is None


# --------------------------------------------------------------------------- #
# GATE 4 — no matched events is UNKNOWN, never zero
# --------------------------------------------------------------------------- #


def _tap_only_train(channel_id: str, device: SourceDevice, ritual: str) -> EventTrain:
    return EventTrain(
        channel_id=channel_id,
        device=device,
        domain=TimeDomain.HOST_RECEIPT,
        detector="detect_accel_spikes",
        ritual=ritual,
        events=(
            SyncEvent(kind=EventKind.ACCEL_SPIKE, rising=True, time_ns=10_000_000_000,
                      bracket_ns=2_000_000, host_realtime_ns=1_786_000_000_000_000_000),
            SyncEvent(kind=EventKind.ACCEL_SPIKE, rising=True, time_ns=10_800_000_000,
                      bracket_ns=2_000_000, host_realtime_ns=1_786_000_000_800_000_000),
        ),
    )


def test_a_ritual_with_no_matched_events_is_unknown_never_zero() -> None:
    """The camera saw only flashes, the IMU only taps: no alignment exists."""

    imu = _tap_only_train("go2.lowstate", SourceDevice.GO2, "SYNC-OPEN")
    camera = _flash_train(
        channel_id="d455.color", device=SourceDevice.D455, ritual="SYNC-OPEN", keep=(0, 1, 2, 3, 4)
    )
    match = match_trains(imu, camera)
    assert match.status is MatchStatus.NO_MATCH
    assert match.offset_ns is None
    assert match.pairs == ()
    # Estimating anyway is a refusal, not a zero.
    with pytest.raises(SyncRefusedError) as excinfo:
        estimate_pair_offset(match, imu, camera)
    assert excinfo.value.reason is SyncRefusalReason.NOT_MATCHED
    # And the whole fit refuses rather than producing a fit around zero.
    with pytest.raises(SyncRefusedError) as build_error:
        build_sync_fit(
            [Ritual(label="SYNC-OPEN", trains=(imu, camera))],
            reference_channel="go2.lowstate",
            target_channel="d455.color",
            session_id="s",
            created_at_utc="2026-08-13T00:00:00Z",
            host_id="h",
            origin=EvidenceOrigin.SIMULATION,
            fixture_label="f",
            host_pair_bracket_ns=200,
        )
    assert build_error.value.reason is SyncRefusalReason.NO_MATCHED_EVENTS
    assert "not zero" in str(build_error.value)


def test_an_empty_train_is_no_events_not_a_zero_offset() -> None:
    empty = EventTrain(
        channel_id="d455.color",
        device=SourceDevice.D455,
        domain=TimeDomain.HOST_RECEIPT,
        detector="detect_brightness_steps",
        ritual="SYNC-OPEN",
        events=(),
    )
    imu = _tap_only_train("go2.lowstate", SourceDevice.GO2, "SYNC-OPEN")
    match = match_trains(imu, empty)
    assert match.status is MatchStatus.NO_EVENTS
    assert match.offset_ns is None
    assert "not zero" in match.detail


def test_a_fit_carries_the_ritual_that_produced_nothing_rather_than_dropping_it() -> None:
    good = selftest_rituals(labels=("SYNC-OPEN", "SYNC-CLOSE"))
    empty_counter = EventTrain(
        channel_id="go2.lowstate",
        device=SourceDevice.GO2,
        domain=TimeDomain.UNWRAPPED_COUNTER,
        detector="detect_accel_spikes",
        ritual="SYNC-CLOSE",
        events=(),
    )
    host_train = good[1].train("go2.lowstate", domain=TimeDomain.HOST_RECEIPT)
    assert host_train is not None
    damaged = [good[0], Ritual(label="SYNC-CLOSE", trains=(host_train, empty_counter))]
    fit = build_sync_fit(
        damaged,
        reference_channel="go2.lowstate",
        target_channel="go2.lowstate",
        reference_domain=TimeDomain.HOST_RECEIPT,
        target_domain=TimeDomain.UNWRAPPED_COUNTER,
        session_id="s",
        created_at_utc="2026-08-13T00:00:00Z",
        host_id="h",
        origin=EvidenceOrigin.SIMULATION,
        fixture_label="f",
        host_pair_bracket_ns=200,
    )
    assert fit.ritual_count == 1
    assert [item.ritual for item in fit.unresolved] == ["SYNC-CLOSE"]
    assert fit.unresolved[0].status is MatchStatus.NO_EVENTS
    assert fit.is_certifiable is False
    assert any("SYNC-CLOSE" in item for item in fit.shortfalls)


# --------------------------------------------------------------------------- #
# Ambiguity — why the flash gaps are uneven
# --------------------------------------------------------------------------- #


def _even_train(channel_id: str, device: SourceDevice, times: tuple[int, ...]) -> EventTrain:
    return EventTrain(
        channel_id=channel_id,
        device=device,
        domain=TimeDomain.HOST_RECEIPT,
        detector="detect_accel_spikes",
        ritual="SYNC-OPEN",
        events=tuple(
            SyncEvent(kind=EventKind.ACCEL_SPIKE, rising=True, time_ns=value,
                      bracket_ns=2_000_000, host_realtime_ns=1_786_000_000_000_000_000)
            for value in times
        ),
    )


def test_an_evenly_spaced_partial_train_is_refused_as_ambiguous() -> None:
    """An even train aliases onto itself. The module says so instead of guessing."""

    reference = _even_train(
        "go2.lowstate", SourceDevice.GO2,
        (10_000_000_000, 11_000_000_000, 12_000_000_000),
    )
    target = _even_train(
        "d455.accel", SourceDevice.D455, (10_000_000_000, 11_000_000_000)
    )
    match = match_trains(reference, target)
    assert match.status is MatchStatus.AMBIGUOUS
    assert match.offset_ns is None
    assert "aliases onto itself" in match.detail


def test_the_uneven_flash_pattern_resolves_where_the_even_one_cannot() -> None:
    """The positive control for the cell above: same event count, uneven gaps."""

    gaps = [int(sum(TORCH_FLASH_GAPS_S[:n]) * 1e9) for n in range(TORCH_FLASH_COUNT)]
    reference = _even_train(
        "go2.lowstate", SourceDevice.GO2, tuple(10_000_000_000 + gap for gap in gaps)
    )
    target = _even_train(
        "d455.accel",
        SourceDevice.D455,
        tuple(10_000_000_000 + gaps[index] for index in (0, 2, 4)),
    )
    match = match_trains(reference, target)
    assert match.status is MatchStatus.MATCHED
    assert match.matched_count == 3
    assert match.runner_up_matched < 3
    assert abs(match.offset_ns) <= 1_000


def test_too_few_events_to_test_an_alternative_is_said_out_loud() -> None:
    reference = _even_train("go2.lowstate", SourceDevice.GO2, (10_000_000_000,))
    target = _even_train("d455.accel", SourceDevice.D455, (10_004_000_000,))
    match = match_trains(reference, target)
    assert match.status is MatchStatus.MATCHED
    assert match.ambiguity_bounded_by_prior is True
    offset = estimate_pair_offset(match, reference, target)
    assert offset.uncertainty.is_bounded is False, "n=1 has no scatter to bound it"
    assert any("skew prior" in caveat for caveat in offset.caveats)


# --------------------------------------------------------------------------- #
# The wrapping counter
# --------------------------------------------------------------------------- #


def test_a_tick_wrap_is_unwrapped_and_counted() -> None:
    ticks = [TICK_MODULUS_MS - 6, TICK_MODULUS_MS - 4, TICK_MODULUS_MS - 2, 0, 2, 4]
    unwrap = unwrap_tick_ms(ticks)
    assert unwrap.wrap_count == 1
    assert unwrap.elapsed_ms == (0, 2, 4, 6, 8, 10)
    assert unwrap.first_tick == TICK_MODULUS_MS - 6
    assert unwrap.epoch_is_arbitrary is True


def test_seeded_failure_naive_differencing_across_the_wrap_yields_49_days() -> None:
    """The refutation: what the fit would have swallowed without the unwrap."""

    naive = 0 - (TICK_MODULUS_MS - 2)
    assert naive < 0 and abs(naive) / 86_400_000 > 49.0
    assert unwrap_tick_ms([TICK_MODULUS_MS - 2, 0]).elapsed_ms == (0, 2)


def test_the_counter_epoch_is_arbitrary_and_the_series_is_rebased() -> None:
    early = unwrap_tick_ms([17, 19, 21])
    late = unwrap_tick_ms([4_000_000_017, 4_000_000_019, 4_000_000_021])
    assert early.elapsed_ms == late.elapsed_ms == (0, 2, 4)
    assert early.first_tick != late.first_tick


@pytest.mark.parametrize(
    "ticks,reason",
    [
        ([0, TICK_MODULUS_MS], SyncRefusalReason.TICK_OUT_OF_RANGE),
        ([0, -1], SyncRefusalReason.TICK_OUT_OF_RANGE),
        ([0, 90_000], SyncRefusalReason.TICK_JUMP),
        ([100, 40], SyncRefusalReason.TICK_JUMP),
        ([0, 1.5], SyncRefusalReason.NON_INTEGER_FIELD),
        ([], SyncRefusalReason.EMPTY_FIELD),
    ],
)
def test_seeded_failure_a_bad_tick_series_is_refused_not_unwrapped(
    ticks: list[object], reason: SyncRefusalReason
) -> None:
    with pytest.raises(SyncRefusedError) as excinfo:
        unwrap_tick_ms(ticks)  # type: ignore[arg-type]
    assert excinfo.value.reason is reason


def test_a_small_backward_step_is_reordering_and_is_refused_not_wrapped() -> None:
    """A 60 ms backward step is out-of-order delivery. Unwrapping it would invent
    a 49.7-day advance out of a reordered pair."""

    with pytest.raises(SyncRefusedError) as excinfo:
        unwrap_tick_ms([1_000_000, 999_940])
    assert excinfo.value.reason is SyncRefusalReason.TICK_JUMP


# --------------------------------------------------------------------------- #
# Detectors
# --------------------------------------------------------------------------- #


def test_the_accel_detector_finds_exactly_the_seeded_taps() -> None:
    taps = (500_000_000, 1_300_000_000, 2_800_000_000)
    times, values, _ = synthesize_ritual_series(
        kind=EventKind.ACCEL_SPIKE,
        event_times_ns=taps,
        start_ns=0,
        end_ns=4_000_000_000,
        rate_hz=500.0,
        feature_width_ns=6_000_000,
        baseline=9.81,
        amplitude=4.0,
        noise=0.02,
        seed=5,
    )
    events = detect_accel_spikes(
        times, values, sample_bracket_ns=2_000_000, min_prominence=1.0,
        refractory_ns=200_000_000,
    )
    assert len(events) == len(taps)
    for event, truth in zip(events, taps):
        assert abs(event.time_ns - truth) <= event.bracket_ns
        assert event.bracket_ns == 2_000_000


def test_the_brightness_detector_brackets_the_flash_by_the_frame_interval() -> None:
    flash = 1_000_000_000
    times, values, _ = synthesize_ritual_series(
        kind=EventKind.BRIGHTNESS_STEP,
        event_times_ns=[flash],
        start_ns=0,
        end_ns=3_000_000_000,
        rate_hz=30.0,
        feature_width_ns=300_000_000,
        baseline=10.0,
        amplitude=180.0,
        noise=1.0,
        seed=2,
    )
    events = detect_brightness_steps(times, values, low_level=40.0, high_level=120.0)
    assert [event.rising for event in events] == [True, False]
    rise = events[0]
    assert abs(rise.time_ns - flash) <= rise.bracket_ns
    # ~1 frame at 30 Hz: the honest bound, not a sub-millisecond fiction.
    assert 15_000_000 <= rise.bracket_ns <= 20_000_000


def test_a_half_lit_frame_widens_the_bracket_rather_than_being_guessed_at() -> None:
    times = [0, 33_000_000, 66_000_000, 99_000_000]
    confident = detect_brightness_steps(times, [10.0, 10.0, 200.0, 200.0],
                                        low_level=40.0, high_level=120.0)
    hesitant = detect_brightness_steps(times, [10.0, 10.0, 80.0, 200.0],
                                       low_level=40.0, high_level=120.0)
    assert hesitant[0].bracket_ns > confident[0].bracket_ns


def test_the_gyro_detector_puts_the_ramp_in_the_bracket() -> None:
    times = [index * 5_000_000 for index in range(400)]
    values = []
    for index in range(400):
        elapsed = index * 5_000_000
        if elapsed < 500_000_000:
            values.append(0.01)
        elif elapsed < 700_000_000:
            values.append(0.01 + 2.0 * (elapsed - 500_000_000) / 200_000_000)
        elif elapsed < 1_400_000_000:
            values.append(2.0)
        else:
            values.append(0.01)
    events = detect_gyro_onsets(
        times, values, sample_bracket_ns=5_000_000, still_threshold=0.05,
        moving_threshold=1.0, min_still_ns=200_000_000,
    )
    assert [event.rising for event in events] == [True, False]
    rise = events[0]
    # The ramp is ~100 ms wide from still-exit to moving-entry: the bracket has
    # to cover it, and it must be far wider than the 5 ms sample period.
    assert rise.bracket_ns > 20_000_000
    assert abs(rise.time_ns - 550_000_000) <= rise.bracket_ns


def test_the_button_detector_debounces_and_refuses_an_unconfirmed_edge() -> None:
    times = [index * 2_000_000 for index in range(1000)]
    pressed = [False] * 1000
    for index in range(250, 500):
        pressed[index] = True
    bounced = list(pressed)
    bounced[249] = True  # a single-sample contact bounce, 2 ms wide
    bounced[248] = False
    events = detect_button_edges(times, bounced, min_hold_ns=100_000_000)
    assert [event.rising for event in events] == [True, False]
    assert abs(events[0].time_ns - 249 * 2_000_000) <= 4_000_000
    # An edge at the very end cannot be confirmed and is not emitted.
    tail = [False] * 999 + [True]
    assert detect_button_edges(times, tail, min_hold_ns=100_000_000) == ()


@pytest.mark.parametrize(
    "call,reason",
    [
        (lambda: detect_accel_spikes([1, 2], [float("nan"), 1.0], sample_bracket_ns=1,
                                     min_prominence=1.0, refractory_ns=0),
         SyncRefusalReason.NOT_FINITE),
        (lambda: detect_accel_spikes([1, 2], [1.0, float("inf")], sample_bracket_ns=1,
                                     min_prominence=1.0, refractory_ns=0),
         SyncRefusalReason.NOT_FINITE),
        (lambda: detect_accel_spikes([1, 2], [1.0, None], sample_bracket_ns=1,
                                     min_prominence=1.0, refractory_ns=0),
         SyncRefusalReason.NON_INTEGER_FIELD),
        (lambda: detect_accel_spikes([2, 1], [1.0, 2.0], sample_bracket_ns=1,
                                     min_prominence=1.0, refractory_ns=0),
         SyncRefusalReason.NON_MONOTONIC_TIME),
        (lambda: detect_accel_spikes([1, 1], [1.0, 2.0], sample_bracket_ns=1,
                                     min_prominence=1.0, refractory_ns=0),
         SyncRefusalReason.NON_MONOTONIC_TIME),
        (lambda: detect_accel_spikes([1, 2, 3], [1.0, 2.0], sample_bracket_ns=1,
                                     min_prominence=1.0, refractory_ns=0),
         SyncRefusalReason.LENGTH_MISMATCH),
        (lambda: detect_accel_spikes([], [], sample_bracket_ns=1, min_prominence=1.0,
                                     refractory_ns=0),
         SyncRefusalReason.EMPTY_FIELD),
        (lambda: detect_accel_spikes([1, 2], [1.0, 2.0], sample_bracket_ns=0,
                                     min_prominence=1.0, refractory_ns=0),
         SyncRefusalReason.NEGATIVE_FIELD),
        (lambda: detect_accel_spikes([1, 2], [1.0, 2.0], sample_bracket_ns=1,
                                     min_prominence=0.0, refractory_ns=0),
         SyncRefusalReason.THRESHOLD_NOT_ORDERED),
        (lambda: detect_brightness_steps([1, 2], [1.0, 2.0], low_level=5.0, high_level=5.0),
         SyncRefusalReason.THRESHOLD_NOT_ORDERED),
        (lambda: detect_gyro_onsets([1, 2], [1.0, 2.0], sample_bracket_ns=1,
                                    still_threshold=2.0, moving_threshold=1.0, min_still_ns=0),
         SyncRefusalReason.THRESHOLD_NOT_ORDERED),
        (lambda: detect_button_edges([1, 2], [0, 1], min_hold_ns=0),
         SyncRefusalReason.MALFORMED_RECORD),
    ],
)
def test_seeded_failure_every_malformed_detector_input_is_refused(
    call, reason: SyncRefusalReason
) -> None:
    with pytest.raises(SyncRefusedError) as excinfo:
        call()
    assert excinfo.value.reason is reason


def test_a_runaway_threshold_is_refused_rather_than_becoming_a_fit() -> None:
    times = [index * 2_000_000 for index in range(2000)]
    values = [9.81 + (5.0 if index % 20 == 0 else 0.0) for index in range(2000)]
    with pytest.raises(SyncRefusedError) as excinfo:
        detect_accel_spikes(
            times, values, sample_bracket_ns=2_000_000, min_prominence=1.0, refractory_ns=0
        )
    assert excinfo.value.reason is SyncRefusalReason.TOO_MANY_EVENTS
    assert str(MAX_EVENTS_PER_TRAIN) in str(excinfo.value)


def test_the_robust_threshold_suppresses_a_channel_that_is_all_spike() -> None:
    """Negative control for the cell above: an alternating series is not 250 taps.

    The declared prominence is a FLOOR, not the threshold; the robust scatter
    term raises the bar on a noisy channel, so a channel oscillating at half its
    sample rate yields no events rather than a train of phantom ones.
    """

    times = [index * 2_000_000 for index in range(500)]
    values = [9.81 + (5.0 if index % 2 else 0.0) for index in range(500)]
    assert detect_accel_spikes(
        times, values, sample_bracket_ns=2_000_000, min_prominence=1.0, refractory_ns=0
    ) == ()


def test_magnitudes_from_xyz_refuses_a_malformed_sample() -> None:
    assert magnitudes_from_xyz([(3.0, 4.0, 0.0)]) == [5.0]
    with pytest.raises(SyncRefusedError):
        magnitudes_from_xyz([(1.0, 2.0)])
    with pytest.raises(SyncRefusedError):
        magnitudes_from_xyz([(1.0, 2.0, float("nan"))])


def test_the_wireless_remote_helper_refuses_a_short_block_and_has_no_default_offset() -> None:
    block = bytes([0, 0, 0b0000_0010, 0]) + bytes(WIRELESS_REMOTE_LENGTH - 4)
    assert wireless_remote_keys(block, key_offset=WIRELESS_REMOTE_KEY_OFFSET_UNVERIFIED) == 2
    assert button_series_from_wireless_remote(
        [block, bytes(WIRELESS_REMOTE_LENGTH)], mask=2,
        key_offset=WIRELESS_REMOTE_KEY_OFFSET_UNVERIFIED,
    ) == [True, False]
    with pytest.raises(SyncRefusedError) as excinfo:
        wireless_remote_keys(bytes(8), key_offset=2)
    assert excinfo.value.reason is SyncRefusalReason.LENGTH_MISMATCH
    with pytest.raises(TypeError):
        wireless_remote_keys(block)  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# The ClockSample bridge
# --------------------------------------------------------------------------- #


def test_one_matched_pair_becomes_one_bracketed_clock_sample() -> None:
    host, counter = synthesize_lowstate_ritual(
        ritual="SYNC-OPEN",
        host_start_ns=SELFTEST_HOST_START_NS,
        host_realtime_start_ns=1_786_000_000_000_000_000,
        counter_start_ns=SELFTEST_COUNTER_START_NS,
        jitter_ns=200_000,
        seed=4,
    )
    match = match_trains(host, counter)
    samples = pair_clock_samples(match, host, counter, host_pair_bracket_ns=200)
    assert len(samples) == match.matched_count == 5
    for sample in samples:
        assert sample.device is SourceDevice.GO2
        assert sample.round_trip_ns == 2 * sample.bracket_ns
        # Two 1 ms button brackets at the narrow end, two 2 ms accel brackets at
        # the wide end. Nothing is ever narrower than the sampling permits.
        assert sample.bracket_ns >= 1_900_000
    assert max(sample.bracket_ns for sample in samples) >= 4_000_000
    # host_mid is the reference event instant, exactly.
    for (i, _), sample in zip(match.pairs, samples):
        assert sample.host_mid_ns == host.events[i].time_ns


def test_the_bridge_refuses_a_reference_that_is_not_the_host_clock() -> None:
    host, counter = synthesize_lowstate_ritual(
        ritual="SYNC-OPEN",
        host_start_ns=SELFTEST_HOST_START_NS,
        host_realtime_start_ns=1_786_000_000_000_000_000,
        counter_start_ns=SELFTEST_COUNTER_START_NS,
    )
    match = match_trains(counter, host)
    with pytest.raises(SyncRefusedError) as excinfo:
        pair_clock_samples(match, counter, host, host_pair_bracket_ns=200)
    assert excinfo.value.reason is SyncRefusalReason.REFERENCE_NOT_HOST


def test_two_host_stamped_channels_give_a_transport_delay_not_a_clock_relation() -> None:
    """The wireless_remote / wirelesscontroller cross-check, typed correctly."""

    remote = _tap_only_train("go2.lowstate", SourceDevice.GO2, "SYNC-OPEN")
    topic = EventTrain(
        channel_id="go2.wirelesscontroller",
        device=SourceDevice.GO2,
        domain=TimeDomain.HOST_RECEIPT,
        detector="detect_button_edges",
        ritual="SYNC-OPEN",
        events=tuple(
            SyncEvent(kind=EventKind.ACCEL_SPIKE, rising=True,
                      time_ns=event.time_ns + 3_000_000, bracket_ns=2_000_000,
                      host_realtime_ns=1_786_000_000_000_000_000)
            for event in remote.events
        ),
    )
    match = match_trains(remote, topic)
    offset = estimate_pair_offset(match, remote, topic)
    assert abs(offset.offset_ns - 3_000_000) < 1_000_000  # the delay IS measured
    with pytest.raises(SyncRefusedError) as excinfo:
        pair_clock_samples(match, remote, topic, host_pair_bracket_ns=200)
    assert excinfo.value.reason is SyncRefusalReason.DOMAIN_MISMATCH
    assert "TRANSPORT DELAY" in str(excinfo.value)


def test_a_reference_event_without_a_host_realtime_stamp_is_refused() -> None:
    reference = EventTrain(
        channel_id="go2.lowstate",
        device=SourceDevice.GO2,
        domain=TimeDomain.HOST_RECEIPT,
        detector="d",
        ritual="R",
        events=(
            SyncEvent(kind=EventKind.ACCEL_SPIKE, rising=True, time_ns=10_000_000_000,
                      bracket_ns=2_000_000),
        ),
    )
    target = EventTrain(
        channel_id="go2.lowstate",
        device=SourceDevice.GO2,
        domain=TimeDomain.UNWRAPPED_COUNTER,
        detector="d",
        ritual="R",
        events=(
            SyncEvent(kind=EventKind.ACCEL_SPIKE, rising=True, time_ns=20_000_000_000,
                      bracket_ns=2_000_000),
        ),
    )
    match = match_trains(reference, target)
    with pytest.raises(SyncRefusedError) as excinfo:
        pair_clock_samples(match, reference, target, host_pair_bracket_ns=200)
    assert excinfo.value.reason is SyncRefusalReason.MISSING_HOST_REALTIME


# --------------------------------------------------------------------------- #
# Serialisation, digests, the sidecar
# --------------------------------------------------------------------------- #


def test_the_fit_round_trips_through_the_bag_sidecar_extra_by_digest() -> None:
    fit = _fit()
    block = sidecar_sync_block(fit)
    manifest = bag_schema.make_manifest(
        bag_id="P5-DRY-20260813-01",
        created_at_utc=fit.created_at_utc,
        source="hardware",
        clocks={
            "source_clock": "sensor",
            "recording_monotonic_origin_ns": fit.relation.first_host_monotonic_ns,
            "note": "sync-ritual clock discipline; see sync_fit_sha256",
        },
        extra=block,
    )
    payload = json.loads(json.dumps(manifest))
    assert payload["sync_fit_sha256"] == sync_fit_digest(fit)
    assert payload["sync_offset_uncertainty_ns"] is not None
    decoded = SyncFitV1.from_dict(json.loads(canonical_json(fit.to_dict())))
    assert sync_fit_digest(decoded) == payload["sync_fit_sha256"]
    assert decoded.to_dict() == fit.to_dict()


def test_seeded_failure_one_moved_event_moves_the_digest() -> None:
    fit = _fit()
    rituals = selftest_rituals()
    train = rituals[0].train("go2.lowstate", domain=TimeDomain.UNWRAPPED_COUNTER)
    assert train is not None
    nudged = EventTrain(
        channel_id=train.channel_id,
        device=train.device,
        domain=train.domain,
        detector=train.detector,
        ritual=train.ritual,
        events=tuple(
            SyncEvent(
                kind=event.kind,
                rising=event.rising,
                time_ns=event.time_ns + (1 if index == 0 else 0),
                bracket_ns=event.bracket_ns,
                strength=event.strength,
                host_realtime_ns=event.host_realtime_ns,
            )
            for index, event in enumerate(train.events)
        ),
    )
    assert events_digest([train]) != events_digest([nudged])
    assert sync_fit_digest(fit) == sync_fit_digest(_fit()), "the digest must be stable"


def test_hand_editing_is_certifiable_into_a_fit_file_changes_nothing() -> None:
    fit = _fit(labels=("SYNC-OPEN",))
    record = json.loads(canonical_json(fit.to_dict()))
    assert record["is_certifiable"] is False
    record["is_certifiable"] = True
    record["shortfalls"] = []
    decoded = SyncFitV1.from_dict(record)
    assert decoded.is_certifiable is False
    assert decoded.shortfalls


@pytest.mark.parametrize("drop", sorted({"schema", "relation", "ritual_offsets", "does_not_prove"}))
def test_a_missing_key_is_refused_on_decode(drop: str) -> None:
    record = json.loads(canonical_json(_fit().to_dict()))
    record.pop(drop)
    with pytest.raises(SyncRefusedError) as excinfo:
        SyncFitV1.from_dict(record)
    assert excinfo.value.reason is SyncRefusalReason.MALFORMED_RECORD


def test_an_unexpected_key_is_refused_on_decode() -> None:
    record = json.loads(canonical_json(_fit().to_dict()))
    record["extra_field"] = 1
    with pytest.raises(SyncRefusedError):
        SyncFitV1.from_dict(record)


def test_a_foreign_schema_string_is_refused() -> None:
    assert SYNC_FIT_SCHEMA == "parcel.capture.syncfit.v1"
    assert SYNC_EVENT_SCHEMA == "parcel.capture.syncevent.v1"
    assert SYNC_TRAIN_SCHEMA == "parcel.capture.synctrain.v1"
    record = json.loads(canonical_json(_fit().to_dict()))
    record["schema"] = "something.else"
    with pytest.raises(SyncRefusedError) as excinfo:
        SyncFitV1.from_dict(record)
    assert excinfo.value.reason is SyncRefusalReason.SCHEMA_MISMATCH


def test_the_serialised_fit_is_json_safe_and_byte_stable() -> None:
    fit = _fit()
    once = canonical_json(fit.to_dict())
    assert once == canonical_json(SyncFitV1.from_dict(json.loads(once)).to_dict())
    assert "NaN" not in once and "Infinity" not in once


def test_the_train_log_survives_a_line_at_a_time_and_refuses_a_bad_line(
    tmp_path: Path,
) -> None:
    path = tmp_path / "trains.jsonl"
    rituals = selftest_rituals()
    for ritual in rituals:
        for train in ritual.trains:
            append_train_jsonl(path, train)
    assert len(read_trains_jsonl(path)) == 4
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"schema": "parcel.capture.synctrain.v1"\n')
    with pytest.raises(SyncRefusedError) as excinfo:
        read_trains_jsonl(path)
    assert ":5:" in str(excinfo.value)


def test_a_synthetic_fit_must_be_labelled_and_a_physical_one_must_not_be() -> None:
    with pytest.raises(SyncRefusedError) as excinfo:
        build_selftest_fit(fixture_label=None)  # type: ignore[call-arg]
    assert excinfo.value.reason is SyncRefusalReason.FIXTURE_LABEL_MISSING
    record = json.loads(canonical_json(_fit().to_dict()))
    record["origin"] = EvidenceOrigin.PHYSICAL.value
    with pytest.raises(SyncRefusedError) as forbidden:
        SyncFitV1.from_dict(record)
    assert forbidden.value.reason is SyncRefusalReason.FIXTURE_LABEL_FORBIDDEN
    record["origin"] = EvidenceOrigin.UNKNOWN.value
    record["fixture_label"] = None
    with pytest.raises(SyncRefusedError) as unknown:
        SyncFitV1.from_dict(record)
    assert unknown.value.reason is SyncRefusalReason.ORIGIN_NOT_DECLARED


def test_the_fit_carries_a_non_empty_does_not_prove() -> None:
    fit = _fit()
    assert len(fit.does_not_prove) >= 5
    assert fit.does_not_prove == DEFAULT_SYNC_DOES_NOT_PROVE
    with pytest.raises(SyncRefusedError) as excinfo:
        build_selftest_fit(does_not_prove=())  # type: ignore[call-arg]
    assert excinfo.value.reason is SyncRefusalReason.EMPTY_FIELD


def test_every_refusal_is_catchable_as_one_capture_error() -> None:
    assert issubclass(SyncRefusedError, SyncError)
    assert issubclass(SyncError, CaptureError)
    with pytest.raises(CaptureError):
        unwrap_tick_ms([])


# --------------------------------------------------------------------------- #
# Structure, the operator card, and the report
# --------------------------------------------------------------------------- #


def test_the_ritual_card_names_every_event_and_its_uneven_gaps() -> None:
    card = format_ritual_card()
    assert TORCH_FLASH_COUNT == 5
    assert TORCH_FLASH_GAPS_S == (1.0, 2.0, 1.0, 3.0)
    for step in RITUAL_SCRIPT:
        assert step.name in card
        assert step.why in card
    assert "SYNC-OPEN" in card and "SYNC-CLOSE" in card
    assert "1, 2, 1, 3 s" in card
    assert "850 nm" in card
    assert "The two ends are required" in card
    assert "EVERY BATTERY SWAP" in card
    assert "FOUR can place it" in card
    # Every channel the card names is one we actually record.
    from parcel_robot.capture.channels import CHANNELS_BY_ID

    for step in RITUAL_SCRIPT:
        for channel_id in step.channels:
            assert channel_id in CHANNELS_BY_ID


def test_the_report_states_a_unit_and_never_mixes_them() -> None:
    report = format_report(_fit())
    assert "two-sided-95" in report
    assert "ppm" in report
    assert "does_not_prove" in report
    assert "CAVEAT" in report
    offset_line = next(line for line in report.splitlines() if "FIT offset@ref" in line)
    assert offset_line.count("ms") == 2  # the value and its uncertainty, same unit


def test_merge_trains_refuses_to_merge_across_a_channel_or_domain() -> None:
    rituals = selftest_rituals()
    host = rituals[0].train("go2.lowstate", domain=TimeDomain.HOST_RECEIPT)
    counter = rituals[0].train("go2.lowstate", domain=TimeDomain.UNWRAPPED_COUNTER)
    assert host is not None and counter is not None
    assert "+" in host.detector
    with pytest.raises(SyncRefusedError):
        merge_trains(host, counter)


def test_a_channel_present_in_two_domains_must_be_named_not_guessed() -> None:
    ritual = selftest_rituals()[0]
    with pytest.raises(SyncRefusedError) as excinfo:
        ritual.train("go2.lowstate")
    assert excinfo.value.reason is SyncRefusalReason.DOMAIN_MISMATCH


def test_matching_across_two_rituals_is_refused() -> None:
    rituals = selftest_rituals()
    a = rituals[0].train("go2.lowstate", domain=TimeDomain.HOST_RECEIPT)
    b = rituals[1].train("go2.lowstate", domain=TimeDomain.UNWRAPPED_COUNTER)
    assert a is not None and b is not None
    with pytest.raises(SyncRefusedError):
        match_trains(a, b)


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


def test_no_symbol_in_the_sync_module_can_reach_a_motion_surface() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    assert not (_identifiers(tree) & _FORBIDDEN_SYMBOLS)
    assert not (_imported_modules(tree) & _FORBIDDEN_IMPORTS)
    assert "import_module" not in _identifiers(tree)
    assert "__import__" not in _identifiers(tree)


@pytest.mark.parametrize(
    "mutant",
    [
        "import rclpy\n",
        "from unitree_sdk2py.go2.sport.sport_client import SportClient\n",
        "def create_publisher(topic):\n    return topic\n",
        "client = ControlManager()\n",
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
    assert caught, f"the pin would not have caught: {mutant!r}"


def test_the_pin_does_not_fire_on_the_legitimate_sensor_names() -> None:
    """Negative control: a scan that fires on everything proves nothing."""

    benign = ast.parse(
        "channels = ('go2.lowstate', 'wireless_remote', 'wirelesscontroller')\n"
        "note = 'the torch flash is seen by d455.color and d455.infra1'\n"
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
        "import scripts.parcel_capture.syncevents;"
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


def test_the_cli_prints_the_ritual_card_with_no_hardware_and_no_traceback() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.parcel_capture.syncevents", "--ritual-card"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stdout + result.stderr
    assert "SYNC RITUAL" in result.stdout


def test_the_cli_check_reports_the_defect_this_card_exists_for() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.parcel_capture.syncevents", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "NO timestamp field" in result.stdout
    assert "go2.lowstate" in result.stdout


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
    decoded = SyncFitV1.from_dict(json.loads(result.stdout))
    assert decoded.origin is EvidenceOrigin.SIMULATION
    assert decoded.fixture_label == "syncevents-selftest"
    assert decoded.is_certifiable


def test_the_cli_refuses_a_fit_that_cannot_name_its_channels(tmp_path: Path) -> None:
    path = tmp_path / "trains.jsonl"
    for train in selftest_rituals()[0].trains:
        append_train_jsonl(path, train)
    result = subprocess.run(
        [sys.executable, "-m", "scripts.parcel_capture.syncevents", "--fit", str(path)],
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
    path = tmp_path / "trains.jsonl"
    for train in selftest_rituals()[0].trains:  # one ritual only: no second bracket
        append_train_jsonl(path, train)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.parcel_capture.syncevents",
            "--fit",
            str(path),
            "--reference-channel",
            "go2.lowstate",
            "--target-channel",
            "go2.lowstate",
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
    assert result.returncode in (1, 2), result.stdout + result.stderr
    assert "Traceback" not in result.stderr
