"""PS-E — the budget arithmetic and the synthetic-publisher rehearsal.

Card PS-E of tranche PS-1 (``scrum/20260813/task_1/README.md``). Two things are
under test and they are different in kind.

**The arithmetic** (``scripts/parcel_capture/budget.py``). Every headline number
is re-derived here from first principles — pixels times bytes per pixel times
frames per second — rather than compared against a constant this repo already
believes. A test that asserts ``budget == 131.84`` proves the module has not
changed; a test that asserts ``budget == width*height*3*fps`` proves it is
right. The plan's own anchors (132 MiB/s, 464 GiB/h, 58 MiB/s, 205 GiB/h) are
then checked against the derivation, which is the only direction in which they
mean anything.

**The rehearsal** (``scripts/parcel_capture/rehearse.py``). Faults are seeded
through the real PS-A/B/C/D stack and the sidecar is asked what happened. Each
gate has two halves: the seeded fault is named, **and** every fault that was not
seeded reads absent. The second half is what catches a drop reported as a
truncation, and it is asserted for every plan in this file.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO_ROOT))

from parcel_robot.capture.channels import CHANNELS, CHANNELS_BY_ID, RateKind, UnknownChannelError
from parcel_robot.evidence_origin import EvidenceOrigin
from scripts.parcel_capture import preflight as preflight_module
from scripts.parcel_capture.budget import (
    CANDIDATE_PROFILES,
    GIB,
    MIB,
    MIN_MEASUREMENT_BYTES,
    UNKNOWNS,
    BudgetRefusedError,
    ChannelLoad,
    D455Profile,
    LoadBasis,
    SustainVerdict,
    WriteMeasurement,
    build_budget,
    framing_bytes,
    loads_from_preflight,
    measure_sustained_write,
    parse_profile,
    static_loads,
)
from scripts.parcel_capture.record import SpaceBudget, read_mcap
from scripts.parcel_capture.rehearse import (
    DEFAULT_PLAN_FAULTS,
    FIXTURE_MARKER,
    REHEARSAL_PREFIX,
    STALL_GAP_PERIODS,
    Fault,
    FaultKind,
    RehearsalPlan,
    RehearsalRefusedError,
    Verdict,
    channel_gaps,
    check_expectations,
    classify,
    configured_rates,
    record_take,
    rehearsal_clock_map,
    run_rehearsal,
    summary_path_for,
    timetable,
)
from scripts.parcel_capture.sidecar import SIDECAR_EXTRA_KEY, verify_sidecar

# The profile every rehearsal in this file records at. 848x480@30 with the IR
# pair is the budget document's recommendation, so the rehearsal exercises the
# configuration the session is actually expected to use.
PROFILE = D455Profile(848, 480, 30)

# Short enough that the whole file runs in a couple of seconds, long enough that
# a 1 Hz channel (the vendor voxel map) still delivers a number line worth
# reading.
DURATION_S = 20.0


def plan(label: str, **kwargs: object) -> RehearsalPlan:
    kwargs.setdefault("duration_s", DURATION_S)
    return RehearsalPlan(
        session_label=f"{REHEARSAL_PREFIX}-{label}", profile=PROFILE, **kwargs
    )


@pytest.fixture(scope="module")
def clean_outcome(tmp_path_factory: pytest.TempPathFactory):
    """One clean rehearsal, shared: no fault seeded, everything must read absent."""

    return run_rehearsal(plan("clean"), tmp_path_factory.mktemp("clean"))


@pytest.fixture(scope="module")
def four_fault_outcome(tmp_path_factory: pytest.TempPathFactory):
    """Four faults in ONE bag. The interesting case, because they must not blur.

    A sensor that stopped, a sensor that slowed, a recorder that dropped, and a
    clock that jumped, all in the same twenty seconds. Each has to be named, on
    the right channel, without any of the others being claimed.
    """

    return run_rehearsal(
        plan("faults", faults=DEFAULT_PLAN_FAULTS), tmp_path_factory.mktemp("faults")
    )


@pytest.fixture(scope="module")
def kill_outcome(tmp_path_factory: pytest.TempPathFactory):
    """A real ``SIGKILL`` to a real child process, mid-write."""

    return run_rehearsal(
        plan("kill", faults=(Fault(FaultKind.PROCESS_KILL),)),
        tmp_path_factory.mktemp("kill"),
    )


@pytest.fixture(scope="module")
def exhaustion_outcome(tmp_path_factory: pytest.TempPathFactory):
    """A real kernel refusal to extend the bag, mid-write."""

    return run_rehearsal(
        plan("exhaustion", faults=(Fault(FaultKind.WRITE_EXHAUSTION),)),
        tmp_path_factory.mktemp("exhaustion"),
    )


# ===========================================================================
# GATE 1 — the arithmetic, derived rather than remembered
# ===========================================================================


@pytest.mark.parametrize(
    ("width", "height", "fps", "infrared"),
    [(1280, 720, 30, False), (1280, 720, 30, True), (848, 480, 30, False), (848, 480, 30, True)],
)
def test_the_d455_figure_is_pixels_times_bytes_times_frames(width, height, fps, infrared):
    """Re-derive the camera load from the format names, independently."""

    profile = D455Profile(width, height, fps, infrared=infrared)
    loads = profile.loads()
    expected = width * height * 3 + width * height * 2 + (width * height * 2 if infrared else 0)
    observed = sum(
        load.payload_bytes_per_message
        for key, load in loads.items()
        if key in {"d455.color", "d455.depth", "d455.infra1", "d455.infra2"}
    )
    assert observed == expected
    assert all(
        load.basis is LoadBasis.DERIVED_PIXELS
        for key, load in loads.items()
        if key.startswith("d455.") and key not in {"d455.accel", "d455.gyro"}
    )


def test_the_plans_own_anchors_reproduce_from_the_derivation():
    """``PHYSICAL_SESSION_PLAN.md:69-72``: 132 MiB/s / 464 GiB/h, 58 / 205.

    Checked against the derivation, not against a stored constant. The plan's
    figures are colour+depth only, with no IR pair, no framing and no other
    channel, so that is exactly what is summed here.
    """

    for (width, height), mib, gib in ((1280, 720), 132.0, 464.0), ((848, 480), 58.0, 205.0):
        per_frame = width * height * 3 + width * height * 2
        per_second = per_frame * 30
        assert per_second / MIB == pytest.approx(mib, abs=0.5)
        assert per_second * 3600 / GIB == pytest.approx(gib, abs=1.0)


def test_the_budget_totals_are_the_sum_of_their_rows():
    budget = build_budget(PROFILE, session_duration_s=3600.0)
    assert budget.bytes_per_second == pytest.approx(
        sum(row.bytes_per_second for row in budget.rows)
    )
    assert budget.bytes_per_second == pytest.approx(
        budget.payload_bytes_per_second + budget.framing_bytes_per_second
    )
    assert budget.gib_per_hour == pytest.approx(budget.bytes_per_second * 3600 / GIB)
    assert budget.mib_per_second == pytest.approx(budget.bytes_per_second / MIB)


def test_the_d455_dominates_but_the_front_camera_is_no_longer_a_rounding_error():
    """``CHANNEL_MATRIX.md``'s bandwidth claim, quantified — and corrected.

    The PS-1 matrix said the non-D455 channels "together are a rounding error
    (<2 MiB/s)" and that "the D455 is essentially the entire budget", with the
    corollary that recording everything costs almost nothing beyond the camera
    decision. PS-H's rewrite refutes half of that. The Go2 front camera IS on
    the DDS topic set as JPEG PER FRAME at ~33 Hz (``RISK_ASSESSMENT.md`` row
    1), not the 4 Mb/s H.264 stream this budget assumed, and at a worst case of
    204 KiB/frame it alone costs ~6.6 MiB/s — more than twice every other
    non-D455 channel put together.

    So the claim splits in two, and this cell pins both halves:

    * the D455 is still the dominant term at every candidate profile;
    * "everything else is free" is now TRUE only of the non-camera channels.
      The front camera is a budget DECISION (record 360p only, or take the
      H.264 path at ~0.5 MiB/s instead), not a free extra.
    """

    budget = build_budget(PROFILE, session_duration_s=3600.0)
    assert budget.camera_bytes_per_second / budget.bytes_per_second > 0.80

    front = sum(
        row.bytes_per_second
        for row in budget.rows
        if row.channel_id.startswith("go2.front_camera")
    )
    non_camera = budget.bytes_per_second - budget.camera_bytes_per_second - front

    # Everything that is not a camera: 25 of the 28 channels, ~3.0 MiB/s. The
    # PS-1 "<2 MiB/s" figure is now FALSE even for this set — PS-H added a
    # second point cloud (utlidar/cloud_deskewed) and an Odometry_ with two
    # covariance blocks — but it is still a rounding error against the D455.
    assert 2.0 * MIB < non_camera < 4.0 * MIB
    assert non_camera < budget.camera_bytes_per_second / 10.0

    # The front camera on the corrected DDS path costs more than twice that.
    assert front > 2.0 * non_camera
    assert 6.0 * MIB < front < 8.0 * MIB


def test_framing_is_measured_against_ps_bs_own_writer_not_estimated():
    """35 bytes of record + message header, plus the envelope JSON itself."""

    entry = CHANNELS_BY_ID["go2.lowstate"]
    from parcel_robot.capture.envelope import CaptureEnvelope, canonical_json

    envelope = CaptureEnvelope(
        channel_id=entry.channel_id,
        sequence=0,
        source_timestamp_ns=None,
        host_monotonic_ns=0,
        host_realtime_ns=0,
        frame_id=entry.frame_id,
        origin=EvidenceOrigin.PHYSICAL,
    )
    assert framing_bytes(entry) == 35 + len(canonical_json(envelope).encode("utf-8"))


def test_framing_grows_with_the_sequence_magnitude_and_the_budget_uses_the_end():
    """Message 1,000,000 costs six digits more than message 0."""

    entry = CHANNELS_BY_ID["go2.lowstate"]
    assert framing_bytes(entry, sequence=1_000_000) == framing_bytes(entry, sequence=0) + 6
    hour = build_budget(PROFILE, session_duration_s=3600.0)
    minute = build_budget(PROFILE, session_duration_s=60.0)
    row_hour = next(row for row in hour.rows if row.channel_id == "go2.lowstate")
    row_minute = next(row for row in minute.rows if row.channel_id == "go2.lowstate")
    assert row_hour.framing_bytes_per_message > row_minute.framing_bytes_per_message


def test_framing_dominates_the_smallest_channels():
    """A 32-byte handheld message costs ~10x its own size to record.

    Not a defect — the envelope is what makes the message attributable — but it
    is the reason the budget adds framing per message rather than applying a
    percentage, and it is the lever if the overhead ever has to come back.
    """

    budget = build_budget(PROFILE, session_duration_s=3600.0)
    small = next(row for row in budget.rows if row.channel_id == "go2.wirelesscontroller")
    assert small.framing_bytes_per_message / small.payload_bytes_per_message > 9.0
    assert budget.framing_bytes_per_second / budget.bytes_per_second < 0.02


def test_session_length_is_free_space_over_rate_with_the_margin_removed():
    budget = build_budget(PROFILE, session_duration_s=3600.0)
    free = 1024 * GIB
    expected = free / (1.0 + budget.margin) / budget.bytes_per_second / 3600.0
    assert budget.session_hours(free) == pytest.approx(expected)
    assert budget.session_hours(0) == 0.0


def test_a_budget_feeds_ps_bs_space_budget_and_ps_ds_free_space_gate():
    """The one number that has to reach two other cards, in their own units."""

    budget = build_budget(PROFILE, session_duration_s=600.0)
    space = SpaceBudget(**budget.space_budget_kwargs())
    assert space.required_bytes == pytest.approx(budget.required_bytes(), rel=1e-9)
    assert budget.required_free_gib() * GIB >= budget.required_bytes()
    assert budget.required_free_gib() == math.ceil(budget.required_bytes() / GIB * 10) / 10


# --- fail-closed halves of gate 1 ------------------------------------------


def test_seeded_failure_a_channel_with_no_load_model_is_refused_never_zero(monkeypatch):
    """The fail-closed rule that matters most in a budget.

    A channel silently contributing zero bytes is how a budget under-states a
    session, and an under-stated budget is a truncated bag. Seeded by deleting
    the model for the highest-rate DDS channel from the shipped table.
    """

    import scripts.parcel_capture.budget as budget_module

    model = static_loads()
    del model["go2.lowstate"]
    monkeypatch.setattr(budget_module, "static_loads", lambda: model)
    with pytest.raises(BudgetRefusedError, match="has no load model"):
        budget_module.build_budget(PROFILE)


def test_every_matrix_channel_has_a_model_or_an_explicit_exclusion():
    """Both directions, so a matrix edit cannot quietly leave a channel unbudgeted."""

    budget = build_budget(PROFILE, session_duration_s=3600.0)
    covered = {row.channel_id for row in budget.rows} | set(budget.excluded)
    assert covered == {entry.channel_id for entry in CHANNELS}
    assert "mic.xvf3800" in budget.excluded  # AWAITING_HARDWARE, records nothing today
    with_mic = build_budget(PROFILE, session_duration_s=3600.0, include_awaiting=True)
    assert "mic.xvf3800" in {row.channel_id for row in with_mic.rows}
    assert with_mic.bytes_per_second > budget.bytes_per_second


@pytest.mark.parametrize(
    "kwargs",
    [
        {"messages_per_second": 0.0},
        {"messages_per_second": float("nan")},
        {"messages_per_second": float("inf")},
        {"messages_per_second": True},
        {"messages_per_second": -1.0},
        {"payload_bytes_per_message": 0},
        {"payload_bytes_per_message": -8},
        {"payload_bytes_per_message": 1.5},
        {"payload_bytes_per_message": True},
        {"basis": "derived_pixels"},
        {"derivation": "   "},
        {"channel_id": "go2.not_a_channel"},
    ],
)
def test_seeded_failure_a_malformed_load_is_refused_never_defaulted(kwargs):
    base = {
        "channel_id": "go2.lowstate",
        "messages_per_second": 500.0,
        "payload_bytes_per_message": 1056,
        "basis": LoadBasis.DERIVED_FIELDS,
        "derivation": "field list",
    }
    base.update(kwargs)
    with pytest.raises((BudgetRefusedError, ValueError)):
        ChannelLoad(**base)


@pytest.mark.parametrize(
    "text", ["1920x1080@30", "848x480@45", "1280x720@60", "nonsense", "848x480", "848x480@0"]
)
def test_seeded_failure_an_undeclared_d455_mode_is_refused(text):
    """A mode nobody confirmed is not a mode; a typo cannot become a plan."""

    with pytest.raises(BudgetRefusedError):
        parse_profile(text)


def test_a_declared_mode_parses_and_round_trips():
    profile = parse_profile("848x480@30:CD")
    assert (profile.width, profile.height, profile.fps) == (848, 480, 30)
    assert profile.color and profile.depth and not profile.infrared
    assert "d455.infra1" not in profile.loads()
    # A stream that is off is an exclusion, not a missing model.
    budget = build_budget(profile, session_duration_s=60.0)
    assert "d455.infra1" in budget.excluded


@pytest.mark.parametrize("free", [-1, 1.5, True, "1024"])
def test_seeded_failure_unknown_free_space_is_not_a_long_session(free):
    budget = build_budget(PROFILE, session_duration_s=60.0)
    with pytest.raises(BudgetRefusedError):
        budget.session_hours(free)


def test_seeded_failure_no_write_measurement_is_never_a_pass():
    """``UNMEASURED`` is a third value on purpose. Unknown is not permission."""

    budget = build_budget(PROFILE, session_duration_s=60.0)
    assert budget.sustained_by(None) is SustainVerdict.UNMEASURED
    assert not budget.sustained_by(None).is_pass
    with pytest.raises(BudgetRefusedError):
        budget.sustained_by(3.5e9)  # a bare number is not a measurement


def test_a_measurement_that_did_not_reach_the_disk_is_refused():
    common = {
        "path": "/tmp",
        "host": "test",
        "block_bytes": 4096,
        "fsync_interval_s": 1.0,
        "filesystem": "ext4",
        "note": "",
    }
    with pytest.raises(BudgetRefusedError, match="page-cache"):
        WriteMeasurement(bytes_written=1024, seconds=2.0, fsync_count=1, **common)
    with pytest.raises(BudgetRefusedError, match="too short"):
        WriteMeasurement(
            bytes_written=MIN_MEASUREMENT_BYTES, seconds=0.01, fsync_count=1, **common
        )
    with pytest.raises(BudgetRefusedError, match="no fsync"):
        WriteMeasurement(
            bytes_written=MIN_MEASUREMENT_BYTES, seconds=2.0, fsync_count=0, **common
        )


def test_measure_sustained_write_refuses_a_sample_too_small_to_mean_anything(tmp_path):
    with pytest.raises(BudgetRefusedError, match="refusing to measure"):
        measure_sustained_write(tmp_path, total_bytes=4096)


def test_a_real_sustained_write_measurement_is_taken_and_labelled(tmp_path):
    """Real bytes, really fsynced, really timed, and the probe file removed.

    The measurement grows itself until the timed window clears
    ``MIN_MEASUREMENT_SECONDS`` — a 256 MiB probe on a Gen5 NVMe finishes in a
    tenth of a second and would be a page-cache reading, not a disk one — so
    the write here is as large as this machine's speed makes necessary. Capped
    at 8 GiB so a suite run stays bounded; the status doc's headline figure was
    taken over 32 GiB on the real NVMe.
    """

    import shutil

    if shutil.disk_usage(tmp_path).free < 20 * 1024 * MIB:
        pytest.skip("needs 20 GiB free to grow a write measurement past its time floor")
    measurement = measure_sustained_write(
        tmp_path,
        total_bytes=MIN_MEASUREMENT_BYTES,
        block_bytes=4 * MIB,
        fsync_interval_s=0.25,
        max_total_bytes=8 * 1024 * MIB,
        note="test",
    )
    assert measurement.bytes_written >= MIN_MEASUREMENT_BYTES
    assert measurement.seconds >= 1.0
    assert measurement.bytes_per_second > 0.0
    assert measurement.fsync_count >= 1
    assert measurement.host  # a measurement always names the host it ran on
    assert not list(tmp_path.glob("parcel-capture-writeprobe-*"))
    budget = build_budget(PROFILE, session_duration_s=60.0)
    assert budget.sustained_by(measurement) in (
        SustainVerdict.SUSTAINS,
        SustainVerdict.DOES_NOT_SUSTAIN,
    )


def test_the_unknowns_are_named_and_include_power_and_thermal():
    """The card requires the budget to say what it does not know."""

    assert len(UNKNOWNS) >= 5
    joined = " ".join(UNKNOWNS).lower()
    for token in ("power", "thermal", "wave 4", "free space", "re-measured on the orin"):
        assert token in joined
    assert all(item.strip() for item in UNKNOWNS)


def test_the_decision_table_covers_a_range_and_orders_monotonically():
    budgets = [build_budget(profile, session_duration_s=3600.0) for profile in CANDIDATE_PROFILES]
    rates = {budget.profile.label: budget.gib_per_hour for budget in budgets}
    assert rates["1280x720@30 CDI"] > rates["1280x720@30 CD"] > rates["848x480@30 CD"]
    assert rates["848x480@30 CDI"] > rates["848x480@15 CDI"]
    # The floor of the table is no longer set by the camera. PS-H's front-camera
    # correction (JPEG per frame, not H.264) puts a ~6.6 MiB/s fixed load under
    # every profile, so even 424x240 now costs ~108 GiB/h and the cheapest
    # profile can no longer buy a sub-100 GiB/h session on its own. The span the
    # table has to cover is still a factor of six.
    assert max(rates.values()) / min(rates.values()) > 5.0
    assert min(rates.values()) < 150.0 < max(rates.values())


def test_loads_from_preflight_needs_the_sizes_ps_d_throws_away(clean_outcome):
    """PS-D measures ``payload_bytes`` per receipt and discards it.

    Only ``observed_rate_hz`` survives on the probe, so the size half of the
    measurement has to be supplied by the caller. Asserted here so the finding
    in ``PSE_STATUS.md`` is pinned rather than merely written down: if PS-D
    later keeps the sizes, this test is the one that should change.
    """

    probe = clean_outcome.preflight.by_channel["go2.lowstate"]
    assert probe.messages_received > 0
    assert probe.observed_rate_hz is not None
    assert not hasattr(probe, "payload_bytes")
    assert not hasattr(probe, "mean_payload_bytes")

    measured = loads_from_preflight(clean_outcome.preflight, {"go2.lowstate": 1056.0})
    assert set(measured) == {"go2.lowstate"}
    assert measured["go2.lowstate"].basis is LoadBasis.MEASURED
    # Without a size, the assumption is kept rather than invented away.
    assert loads_from_preflight(clean_outcome.preflight, {}) == {}
    with pytest.raises(BudgetRefusedError):
        loads_from_preflight(clean_outcome.preflight, {"go2.lowstate": 0.0})


# ===========================================================================
# GATE 2 — the rehearsal runs green with no hardware and no ROS
# ===========================================================================


def test_the_clean_rehearsal_is_green_end_to_end(clean_outcome):
    assert clean_outcome.green, clean_outcome.violations
    assert clean_outcome.take is not None
    assert clean_outcome.take.messages_recorded == clean_outcome.take.messages_offered
    assert clean_outcome.take.messages_dropped == 0
    assert clean_outcome.sidecar[SIDECAR_EXTRA_KEY]["termination"]["kind"] == "clean"


def test_the_rehearsal_drives_the_real_stack_and_binds_it_together(clean_outcome):
    """Every card's artifact reaches the sidecar, by digest, in one run."""

    block = clean_outcome.sidecar[SIDECAR_EXTRA_KEY]
    from scripts.parcel_capture.clockmap import clock_map_digest

    assert block["attestation"]["status"] == "present"
    assert block["attestation"]["digest"] == clean_outcome.attestation.digest()
    assert block["clock_map"]["status"] == "present"
    assert block["clock_map"]["digest"] == clock_map_digest(clean_outcome.clock_map)
    assert verify_sidecar(clean_outcome.sidecar, clean_outcome.take.bag_path).ok
    # PS-D reached its GO_RECORD verdict, which it cannot do without PS-E's
    # storage budget (PSD_STATUS.md design call D-3).
    assert clean_outcome.attestation.verdict.value == "go_record"
    assert clean_outcome.attestation.required_free_bytes is not None


def test_no_motion_sdk_is_reachable_and_an_installed_camera_sdk_reaches_no_device():
    """The motion guarantee, re-measured — and re-cut by card ENV-1.

    This was ``test_no_vendor_sdk_is_reachable_and_none_was_installed`` and it
    asserted that seven named modules were all absent. FIVE of the seven still
    are (card ENV-1b corrects the count: ``pyrealsense2`` AND ``cv2`` both
    dropped out, not one of them; the loop below re-asserts those five plus
    ``unilidar_sdk2``, which was never in the original seven), and that is the
    guarantee worth keeping: the modules that can command
    the dog are the ones whose absence from ``.parcel`` means no test run can
    move a robot. ``pyrealsense2`` and ``cv2`` are NOT in that class — they read
    a camera — and P1-A installed both on 2026-08-22 for the desk-camera venue,
    with the board's sanction. Asserting they are absent asserted a fact about
    one afternoon's ``pip list``, not a property of the system.

    So the split is by what the module can DO. The motion SDKs must stay absent.
    A camera SDK may be present, and the invariant that replaces "it is not
    installed" is the one that actually protects the rehearsal: **with the wheel
    installed and no camera attached, the live reader still refuses, by name,
    and still never gets far enough to import it.**
    """

    import importlib.util

    for name in ("rclpy", "cyclonedds", "unitree_sdk2py", "unilidar_sdk2", "mcap", "zstandard"):
        assert importlib.util.find_spec(name) is None, (
            f"{name} can command or decode the dog and must not be installed in .parcel/"
        )

    from scripts.parcel_capture.ingest import DevicePresence, RealSenseIngest

    adapter = RealSenseIngest()
    if importlib.util.find_spec("pyrealsense2") is None:
        # A host that never got P1-A's install: the module arm is the refusal.
        assert not adapter.dependency_report().satisfied
        return

    assert adapter.dependency_report().satisfied
    assert adapter.device_report().presence is DevicePresence.ABSENT, (
        "a camera is attached to this host; the hardwareless arm cannot be measured here"
    )


def test_a_full_rehearsal_never_imports_a_vendor_module(tmp_path):
    """Measured in a subprocess, over a whole run, not asserted by scan alone."""

    script = (
        "import sys, json;"
        f"sys.path.insert(0, {str(REPO_ROOT)!r});"
        "from scripts.parcel_capture.rehearse import run_rehearsal, RehearsalPlan, "
        "REHEARSAL_PREFIX;"
        "from scripts.parcel_capture.budget import D455Profile;"
        "run_rehearsal(RehearsalPlan(session_label=REHEARSAL_PREFIX+'-probe',"
        " profile=D455Profile(848,480,30), duration_s=5.0),"
        f" {str(tmp_path)!r});"
        "print(json.dumps([m for m in sys.modules if m.split('.')[0] in "
        "{'rclpy','cyclonedds','unitree_sdk2py','pyrealsense2','cv2','mcap','zstandard'}]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []


def test_the_rehearsal_runs_on_a_bare_interpreter_as_a_plain_script(tmp_path):
    """The deploy invocation the Stage-0 run sheet prescribes (T6), measured.

    ``python3 scripts/parcel_capture/rehearse.py`` with no editable install, no
    ``PYTHONPATH`` and a working directory outside the repo. This is the path
    the Orin will take, and PS-C measured the equivalent for ``clockmap.py``
    (``PSC_STATUS.md`` C10).
    """

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "parcel_capture" / "rehearse.py"),
            "--workdir",
            str(tmp_path),
            "--duration",
            "5",
        ],
        capture_output=True,
        text=True,
        cwd="/",
        env={
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PWD"}
        },
        check=False,
    )
    assert "Traceback" not in result.stdout + result.stderr, result.stderr[-2000:]
    assert result.returncode == 0, result.stderr[-2000:]
    assert "RESULT: GREEN" in result.stdout


def test_record_py_and_sidecar_py_cannot_be_invoked_as_plain_scripts():
    """A composition finding, pinned so it is not lost.

    PS-C's ``clockmap.py`` and PS-D's ``preflight.py``/``attest.py`` bootstrap
    ``src/`` onto ``sys.path`` and run from a bare checkout. PS-B's
    ``record.py`` does not, so the invocation the run sheet names at T4/T5
    ends in a ``ModuleNotFoundError`` traceback rather than the actionable
    refusal board rule 4 requires. Nothing in PS-E's OWNS may fix it; this
    test states the current behaviour so the fix is visible when it lands.
    """

    env = {
        key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PWD"}
    }
    result = subprocess.run(
        [
            "/usr/bin/python3",
            str(REPO_ROOT / "scripts" / "parcel_capture" / "record.py"),
            "--verify",
            "/nonexistent.mcap",
        ],
        capture_output=True,
        text=True,
        cwd="/",
        env=env,
        check=False,
    )
    if result.returncode == 0 and "Traceback" not in result.stderr:
        pytest.skip("record.py gained a sys.path bootstrap; the finding is fixed")
    assert "ModuleNotFoundError" in result.stderr
    assert "parcel_robot" in result.stderr
    # The comparison that makes it a finding rather than an opinion:
    control = subprocess.run(
        [
            "/usr/bin/python3",
            str(REPO_ROOT / "scripts" / "parcel_capture" / "clockmap.py"),
            "--check",
        ],
        capture_output=True,
        text=True,
        cwd="/",
        env=env,
        check=False,
    )
    assert "Traceback" not in control.stderr


# ===========================================================================
# GATE 3 — every fault named, and no other fault claimed
# ===========================================================================


def test_four_faults_in_one_bag_are_each_named_on_the_right_channel(four_fault_outcome):
    """The headline gate. One take, four faults, four distinct findings."""

    assert four_fault_outcome.green, four_fault_outcome.violations
    result = four_fault_outcome.classification
    assert result[FaultKind.SENSOR_SILENCE].channel_ids == ("go2.utlidar.cloud",)
    assert result[FaultKind.RATE_DEGRADATION].channel_ids == ("go2.sportmodestate",)
    assert result[FaultKind.BACKPRESSURE_LOSS].channel_ids == ("go2.lowstate",)
    assert result[FaultKind.CLOCK_STEP].channel_ids == ("go2",)
    assert result[FaultKind.PROCESS_KILL].verdict is Verdict.ABSENT
    assert result[FaultKind.WRITE_EXHAUSTION].verdict is Verdict.ABSENT


def test_a_backpressure_drop_is_a_hole_and_a_stopped_sensor_is_not(four_fault_outcome):
    """The two senses of 'drop', kept apart by disjoint evidence.

    ``go2.lowstate`` lost messages **after** they were received: PS-A minted
    their sequence numbers, so the number line has interior holes.
    ``go2.utlidar.cloud`` stopped publishing: nothing was ever received, so its
    number line is spotless and only the count betrays it. A capture stack that
    could not tell these apart would send an operator to debug the wrong half
    of the rig.
    """

    channels = four_fault_outcome.sidecar[SIDECAR_EXTRA_KEY]["channels"]
    lost = channels["go2.lowstate"]
    stopped = channels["go2.utlidar.cloud"]

    assert lost["sequence"]["missing_count"] == 500
    assert lost["reason"].startswith("sequence_gap")
    assert lost["verdict"] == "degraded"

    assert stopped["sequence"]["missing_count"] == 0
    assert stopped["sequence"]["duplicate_count"] == 0
    assert stopped["reason"].startswith("rate_below_expectation")
    assert stopped["verdict"] == "degraded"

    # Neither carries the other's language.
    assert "sequence_gap" not in stopped["reason"]
    assert "rate_below_expectation" not in lost["reason"]


def test_a_fault_the_plan_never_seeded_is_a_violation_not_a_pass(four_fault_outcome):
    """The direction that catches a misclassification, asserted directly.

    ``check_expectations`` has two loops and only one of them is exercised by a
    green rehearsal. This cell drives the other: take the real classification of
    a four-fault take and ask what a plan that seeded **nothing** makes of it.
    Every detection must come back as a violation — that is what "a drop is not
    reported as a truncation" means operationally, and without this cell the
    check can be reduced to its first loop and every test still passes (seeded
    failure M9).
    """

    innocent = plan("innocent")
    assert innocent.seeded_kinds() == frozenset()
    violations = check_expectations(innocent, four_fault_outcome.classification)
    detected = {
        kind
        for kind, result in four_fault_outcome.classification.items()
        if result.verdict is Verdict.DETECTED
    }
    assert detected  # the fixture really did produce findings to be flagged
    assert len(violations) == len(detected)
    for kind in detected:
        assert any(
            item.startswith(f"{kind.value}: NOT seeded") for item in violations
        ), f"{kind.value} was reported and not flagged"

    # ...and the same classification against the plan that produced it is clean.
    assert check_expectations(four_fault_outcome.plan, four_fault_outcome.classification) == ()


def test_a_fault_attributed_to_the_wrong_channel_is_a_violation(four_fault_outcome):
    """Right fault, wrong channel, is still a failure of this stack.

    Attributing a drop to the channel that did not suffer it is the exact defect
    ``bags/recorder.py``'s global counter produces, so the rehearsal treats it
    as a red rather than a near-miss.
    """

    misattributed = plan(
        "misattributed",
        faults=(Fault(FaultKind.BACKPRESSURE_LOSS, channel_id="go2.sportmodestate"),),
    )
    violations = check_expectations(misattributed, four_fault_outcome.classification)
    assert any(
        "attributed to ['go2.lowstate']" in item and "backpressure_loss" in item
        for item in violations
    ), violations


def test_a_seeded_fault_the_artifacts_miss_is_a_violation(clean_outcome):
    """The first direction, asserted directly rather than only via a green run."""

    claims_a_fault = plan(
        "claims", faults=(Fault(FaultKind.BACKPRESSURE_LOSS, channel_id="go2.lowstate"),)
    )
    violations = check_expectations(claims_a_fault, clean_outcome.classification)
    assert any(
        item.startswith("backpressure_loss: SEEDED but the artifacts read absent")
        for item in violations
    ), violations


def test_a_missing_classification_is_a_violation():
    """A fault class nobody ruled on is never silently a pass."""

    violations = check_expectations(plan("empty"), {})
    assert len(violations) == len(FaultKind)
    assert all("no classification was produced at all" in item for item in violations)


def test_a_stopped_channel_and_a_slowed_channel_are_told_apart_by_the_gap(
    four_fault_outcome,
):
    """Same verdict word, same evidence in the sidecar, different physical fault.

    Both read ``degraded / rate_below_expectation``. Only the longest silence
    separates them, and only because :func:`channel_gaps` computes it from the
    bag — the sidecar does not carry it.
    """

    gaps = four_fault_outcome.gaps
    channels = four_fault_outcome.sidecar[SIDECAR_EXTRA_KEY]["channels"]
    assert channels["go2.utlidar.cloud"]["reason"].split(":")[0] == (
        channels["go2.sportmodestate"]["reason"].split(":")[0]
    )
    assert gaps["go2.utlidar.cloud"] > STALL_GAP_PERIODS / 10.0
    assert gaps["go2.sportmodestate"] <= STALL_GAP_PERIODS / 50.0
    silence = four_fault_outcome.classification[FaultKind.SENSOR_SILENCE]
    slowed = four_fault_outcome.classification[FaultKind.RATE_DEGRADATION]
    assert "STOPPED" in " ".join(silence.evidence)
    assert "SLOWED" in " ".join(slowed.evidence)


def test_seeded_failure_without_gap_evidence_the_two_are_not_separable(
    four_fault_outcome,
):
    """Withhold the gaps and the classifier refuses to guess.

    ``UNRESOLVED`` rather than a coin flip, and ``check_expectations`` treats an
    unresolved unseeded class as a violation — so 'we could not tell' can never
    pass for 'it did not happen'.
    """

    blind = classify(four_fault_outcome.sidecar, clock_map=four_fault_outcome.clock_map)
    assert blind[FaultKind.SENSOR_SILENCE].verdict is Verdict.UNRESOLVED
    assert blind[FaultKind.RATE_DEGRADATION].verdict is Verdict.UNRESOLVED
    assert blind[FaultKind.BACKPRESSURE_LOSS].verdict is Verdict.DETECTED
    violations = check_expectations(
        plan("blind", faults=(Fault(FaultKind.BACKPRESSURE_LOSS, channel_id="go2.lowstate"),)),
        blind,
    )
    assert any("cannot rule it out" in item for item in violations)


def test_a_seeded_clock_step_is_a_step_and_the_drift_fit_survives_it(four_fault_outcome):
    """PS-C's gate, re-run through the rehearsal's own fixture."""

    step = four_fault_outcome.classification[FaultKind.CLOCK_STEP]
    assert step.verdict is Verdict.DETECTED
    assert step.source == "clock_map"
    stepping = [
        relation
        for relation in four_fault_outcome.clock_map.relations
        if relation.steps
    ]
    assert len(stepping) == 1
    assert stepping[0].device.value == "go2"
    (found,) = stepping[0].steps
    assert found.magnitude_ns == pytest.approx(500_000_000, abs=200_000)
    for segment in stepping[0].segments:
        assert segment.drift_ppm == pytest.approx(40.0, abs=10.0)


def test_no_clock_map_is_unresolved_not_absent():
    """Fail closed: without offset triples a step is invisible, not absent."""

    outcome = classify(
        {SIDECAR_EXTRA_KEY: {"termination": {"kind": "clean"}, "channels": {}}},
        gaps={},
    )
    assert outcome[FaultKind.CLOCK_STEP].verdict is Verdict.UNRESOLVED


def test_sigkill_is_a_truncation_and_costs_no_channel_a_hole(kill_outcome):
    """The most important single classification on the board, end to end.

    The recorder really died — the child's exit status is ``-9`` — and the bag
    it left says *truncated*, not *the LiDAR was flaky*. A truncation removes a
    suffix of one append-only byte stream, so every channel loses its tail and
    **no channel gets a hole**; that is the structural reason these two can
    never be confused.
    """

    assert kill_outcome.green, kill_outcome.violations
    assert "SIGKILL" in " ".join(kill_outcome.notes)
    block = kill_outcome.sidecar[SIDECAR_EXTRA_KEY]
    assert block["termination"]["kind"] == "truncated"
    assert block["termination"]["evidence"]["saw_terminal_magic"] is False
    assert block["termination"]["evidence"]["recorder_close_record"] is None
    assert block["termination"]["evidence"]["messages_recovered"] > 100
    for channel_id, entry in block["channels"].items():
        assert entry["sequence"]["missing_count"] == 0, channel_id
        assert entry["sequence"]["duplicate_count"] == 0, channel_id
        assert "sequence_gap" not in entry["reason"], channel_id
    assert kill_outcome.classification[FaultKind.BACKPRESSURE_LOSS].verdict is Verdict.ABSENT


def test_a_truncated_bag_does_not_manufacture_rate_faults(kill_outcome):
    """Rates are judged over the span that is IN the bag, not the span asked for.

    Without that, a bag cut at the halfway mark would report all twenty-one
    channels at 50% and turn one truncation into twenty-one fabricated sensor
    faults.
    """

    channels = kill_outcome.sidecar[SIDECAR_EXTRA_KEY]["channels"]
    verdicts = {entry["verdict"] for entry in channels.values()}
    assert "degraded" not in verdicts
    assert kill_outcome.classification[FaultKind.SENSOR_SILENCE].verdict is Verdict.ABSENT
    assert kill_outcome.classification[FaultKind.RATE_DEGRADATION].verdict is Verdict.ABSENT


def test_write_exhaustion_latches_the_bytes_survive_and_it_is_not_called_a_drop(
    exhaustion_outcome,
):
    """A real kernel refusal to extend the file, mid-write.

    ``RLIMIT_FSIZE`` gives ``EFBIG`` where a full volume gives ``ENOSPC``; PS-B
    latches the first as ``WRITE_FAILED`` and the second as ``DISK_FULL``, and
    its own seeded test owns that mapping. What this rehearsal adds is the rest
    of the chain: the recorder stops, the bytes already written survive, the
    sidecar does not call it a dropout, and the latch is recoverable.
    """

    assert exhaustion_outcome.green, exhaustion_outcome.violations
    summary = json.loads(
        summary_path_for(exhaustion_outcome.workdir / f"{exhaustion_outcome.plan.session_label}.mcap")
        .read_text(encoding="utf-8")
    )
    assert summary["latch_reason"] in {"write_failed", "disk_full"}
    assert summary["closed_cleanly"] is False
    assert summary["messages_written"] > 0

    block = exhaustion_outcome.sidecar[SIDECAR_EXTRA_KEY]
    assert block["termination"]["kind"] == "truncated"
    assert block["mcap"]["bytes"] > 0
    for entry in block["channels"].values():
        assert entry["sequence"]["missing_count"] == 0
        assert "sequence_gap" not in entry["reason"]
    assert exhaustion_outcome.classification[FaultKind.BACKPRESSURE_LOSS].verdict is Verdict.ABSENT


def test_the_finding_that_a_full_volume_hides_its_own_latch(exhaustion_outcome):
    """A truncation does not name its cause, and the bag cannot say why it ended.

    ``close()`` writes the recorder's account INTO the bag before the footer —
    but on a volume that will not take another byte, that write fails too. So a
    genuinely exhausted volume and a ``SIGKILL`` leave byte-identical evidence:
    no ``DataEnd``, no ``Footer``, no close record. The only discriminator is
    the summary this module writes beside the bag, and on a truly full
    filesystem even that may fail. Pinned here because it changes what the
    Stage-0 sheet has to record.
    """

    exhausted = exhaustion_outcome.sidecar[SIDECAR_EXTRA_KEY]["termination"]
    assert exhausted["kind"] == "truncated"
    assert exhausted["evidence"]["recorder_close_record"] is None

    # From the bag alone the two are the same verdict...
    from_bag_only = classify(exhaustion_outcome.sidecar, gaps=exhaustion_outcome.gaps)
    assert from_bag_only[FaultKind.PROCESS_KILL].verdict is Verdict.DETECTED
    assert from_bag_only[FaultKind.WRITE_EXHAUSTION].verdict is Verdict.ABSENT

    # ...and only the out-of-band summary separates them.
    assert exhaustion_outcome.classification[FaultKind.WRITE_EXHAUSTION].source == "out_of_band"
    assert exhaustion_outcome.classification[FaultKind.PROCESS_KILL].verdict is Verdict.ABSENT


def test_the_recorder_refuses_to_start_when_the_budget_does_not_fit(tmp_path):
    """The budget's other job: stopping a take that cannot finish.

    A profile whose take needs more room than the volume has must be refused
    before a byte is written, not discovered at 80% of the way through.
    """

    budget = build_budget(D455Profile(1280, 720, 30), session_duration_s=86_400.0)
    free = os.statvfs(tmp_path)
    assert budget.required_bytes() > free.f_bavail * free.f_frsize
    from scripts.parcel_capture.record import CaptureRecorder, RecorderRefusedError

    with pytest.raises(RecorderRefusedError, match="refusing to start"):
        CaptureRecorder(
            tmp_path / "too-big.mcap",
            bag_id=f"{REHEARSAL_PREFIX}-toobig",
            channels=[CHANNELS_BY_ID["go2.lowstate"]],
            origin=EvidenceOrigin.SIMULATION,
            fixture_label=f"{REHEARSAL_PREFIX}-toobig",
            budget=SpaceBudget(**budget.space_budget_kwargs()),
        )
    assert not (tmp_path / "too-big.mcap").exists()


# ===========================================================================
# GATE 4 — a rehearsal artifact can never pass for a session artifact
# ===========================================================================


def test_every_rehearsal_envelope_declares_simulation_and_names_its_fixture(clean_outcome):
    scan = read_mcap(clean_outcome.take.bag_path)
    assert scan.origins() == frozenset({EvidenceOrigin.SIMULATION})
    for message in scan.messages[:200]:
        assert message.envelope.fixture_label == clean_outcome.plan.session_label
    assert clean_outcome.sidecar["source"] == "sim"
    assert clean_outcome.sidecar["hardware_claims"] is False


def test_a_session_label_without_the_rehearsal_prefix_is_refused():
    with pytest.raises(RehearsalRefusedError, match="must start with"):
        RehearsalPlan(session_label="P5-DRY-20260813-01", profile=PROFILE)


def test_the_sidecar_says_what_the_rehearsal_does_not_prove(clean_outcome):
    joined = " ".join(clean_outcome.sidecar["does_not_prove"]).lower()
    assert "synthetic" in joined
    assert "no sensor" in joined
    assert "virtual" in joined


def test_the_finding_that_a_synthetic_attestation_still_claims_physical(clean_outcome):
    """PS-D has no notion of a synthetic reader, and this is what that costs.

    ``ChannelAttestation.origin`` is derived from ``messages_received >= 1``
    alone, so an attestation built from fixtures declares
    ``EvidenceOrigin.PHYSICAL`` for twenty-one channels no sensor produced. The
    only markers are the session label and the fixture string this module puts
    in every receipt's ``detail``. Pinned as a finding, not a pass: if PS-D
    gains a typed origin for a probe, this test is the one that changes.
    """

    physical = clean_outcome.attestation.physical_channels
    assert len(physical) >= 20
    assert clean_outcome.attestation.session_label.startswith(REHEARSAL_PREFIX)
    for entry in clean_outcome.attestation.channels:
        if entry.messages_received > 0:
            assert entry.origin is EvidenceOrigin.PHYSICAL  # the finding
            assert FIXTURE_MARKER in entry.evidence  # the only mitigation available


# ===========================================================================
# GATE 5 — the publishers themselves are honest
# ===========================================================================


def test_the_timetable_is_deterministic_and_matches_the_budgets_rates():
    first = list(timetable(plan("determinism")))
    second = list(timetable(plan("determinism")))
    assert [(m.channel_id, m.elapsed_ns, m.payload) for m in first] == [
        (m.channel_id, m.elapsed_ns, m.payload) for m in second
    ]
    budget = build_budget(PROFILE, session_duration_s=DURATION_S)
    counts: dict[str, int] = {}
    for message in first:
        counts[message.channel_id] = counts.get(message.channel_id, 0) + 1
    for row in budget.rows:
        assert counts[row.channel_id] == pytest.approx(
            row.messages_per_second * DURATION_S, rel=0.02
        )


def test_the_timetable_is_ordered_by_receipt_instant():
    stamps = [message.elapsed_ns for message in timetable(plan("ordering"))]
    assert stamps == sorted(stamps)


def test_a_fault_that_cannot_name_its_channel_is_refused():
    with pytest.raises(RehearsalRefusedError, match="must name the channel"):
        Fault(FaultKind.SENSOR_SILENCE)
    with pytest.raises(RehearsalRefusedError, match="not a per-channel fault"):
        Fault(FaultKind.CLOCK_STEP, channel_id="go2.lowstate")
    with pytest.raises(UnknownChannelError):
        Fault(FaultKind.SENSOR_SILENCE, channel_id="go2.not_a_channel")


def test_two_faults_of_one_kind_are_refused_because_attribution_would_blur():
    with pytest.raises(RehearsalRefusedError, match="one fault of each kind"):
        RehearsalPlan(
            session_label=f"{REHEARSAL_PREFIX}-double",
            profile=PROFILE,
            faults=(
                Fault(FaultKind.SENSOR_SILENCE, channel_id="go2.lowstate"),
                Fault(FaultKind.SENSOR_SILENCE, channel_id="go2.sportmodestate"),
            ),
        )
    with pytest.raises(RehearsalRefusedError, match="can only end once"):
        RehearsalPlan(
            session_label=f"{REHEARSAL_PREFIX}-twodeaths",
            profile=PROFILE,
            faults=(Fault(FaultKind.PROCESS_KILL), Fault(FaultKind.WRITE_EXHAUSTION)),
        )


def test_the_stall_threshold_matches_preflights():
    """PS-D and PS-E must not disagree about what counts as a stall."""

    assert STALL_GAP_PERIODS == preflight_module.MAX_GAP_PERIODS


def test_configured_rates_skip_the_event_driven_channel():
    """PS-D refuses an override there: it would turn normal silence into a fault."""

    budget = build_budget(PROFILE, session_duration_s=60.0)
    rates = configured_rates(budget)
    assert "go2.wirelesscontroller" not in rates
    assert CHANNELS_BY_ID["go2.wirelesscontroller"].rate_kind is RateKind.EVENT_DRIVEN
    assert rates["l2.cloud"] == 20.0
    for channel_id in rates:
        assert CHANNELS_BY_ID[channel_id].rate_kind is not RateKind.EVENT_DRIVEN


def test_the_plan_round_trips_through_json(tmp_path):
    """The child process receives its plan this way; a lossy trip is a wrong take."""

    original = plan("roundtrip", faults=DEFAULT_PLAN_FAULTS)
    restored = RehearsalPlan.from_dict(json.loads(json.dumps(original.to_dict())))
    assert restored.to_dict() == original.to_dict()
    assert [m.channel_id for m in timetable(restored)] == [
        m.channel_id for m in timetable(original)
    ]


@pytest.mark.parametrize(
    "record",
    [
        {},
        {"session_label": "nope", "profile": "848x480@30", "duration_s": 1, "payload_scale": 1},
        {
            "session_label": f"{REHEARSAL_PREFIX}-x",
            "profile": "9999x9999@30",
            "duration_s": 1,
            "payload_scale": 1,
        },
        {
            "session_label": f"{REHEARSAL_PREFIX}-x",
            "profile": "848x480@30",
            "duration_s": 0,
            "payload_scale": 1,
        },
        {
            "session_label": f"{REHEARSAL_PREFIX}-x",
            "profile": "848x480@30",
            "duration_s": 1,
            "payload_scale": 2,
        },
    ],
)
def test_seeded_failure_a_malformed_plan_is_refused(record):
    with pytest.raises(RehearsalRefusedError):
        RehearsalPlan.from_dict(record)


def test_a_clock_map_spans_the_session_not_the_take():
    """PS-C will not certify a fit under its minimum span; the take is shorter.

    Concrete consequence for the run sheet: the clock prober runs across the
    whole session, and short takes inherit its map rather than owning one.
    """

    from scripts.parcel_capture.clockmap import MIN_SPAN_NS

    short = plan("shortclock", duration_s=20.0)
    assert short.clock_span_ns >= MIN_SPAN_NS
    clock_map = rehearsal_clock_map(short)
    assert clock_map.is_certifiable
    assert clock_map.origin is EvidenceOrigin.SIMULATION
    assert clock_map.fixture_label == short.session_label


def test_a_classification_never_sees_the_plan(four_fault_outcome):
    """The classifier's only inputs are artifacts. Asserted by signature."""

    import inspect

    parameters = set(inspect.signature(classify).parameters)
    assert parameters == {"sidecar", "clock_map", "gaps", "recorder_summary"}
    assert "plan" not in parameters


def test_classify_refuses_a_document_that_is_not_a_capture_manifest():
    with pytest.raises(RehearsalRefusedError, match="not a parcel-capture manifest"):
        classify({"schema_version": "parcel.bag.v1"})


def test_channel_gaps_brackets_by_the_session_not_the_channel(four_fault_outcome):
    """The bug this rehearsal found in its own classifier, pinned.

    A channel that dies half-way through has evenly-spaced messages right up to
    the moment it stops, so an interior-only gap measure calls it *slow*. Only
    bracketing against the bag's own span shows the silence.
    """

    gaps = channel_gaps(four_fault_outcome.take.bag_path)
    scan = read_mcap(four_fault_outcome.take.bag_path)
    stamps = [
        message.envelope.host_monotonic_ns
        for message in scan.messages
        if message.channel.channel_id == "go2.utlidar.cloud"
    ]
    interior = max(later - earlier for earlier, later in itertools.pairwise(stamps))
    assert interior / 1e9 < 0.2  # evenly spaced right up to the moment it stopped
    assert gaps["go2.utlidar.cloud"] > 9.0  # ...and silent for half the take


def test_a_take_writes_its_recorder_summary_beside_the_bag(tmp_path):
    """The mitigation for a latch that cannot reach the bag."""

    take = record_take(plan("summary"), tmp_path / "summary.mcap")
    assert take.summary_path is not None
    assert take.summary_write_error == ""
    written = json.loads(take.summary_path.read_text(encoding="utf-8"))
    assert written["messages_written"] == take.messages_recorded
    assert written["latch_reason"] is None
    assert written["closed_cleanly"] is True


def test_payload_scale_changes_bytes_and_nothing_else(tmp_path):
    """A scaled rehearsal must classify identically to a full-size one."""

    small = record_take(plan("scale-small", payload_scale=1 / 4096), tmp_path / "small.mcap")
    large = record_take(plan("scale-large", payload_scale=1 / 256), tmp_path / "large.mcap")
    assert small.messages_recorded == large.messages_recorded
    assert large.bag_path.stat().st_size > small.bag_path.stat().st_size
    assert read_mcap(small.bag_path).counts() == read_mcap(large.bag_path).counts()


def test_the_budget_is_written_into_every_rehearsal_sidecar(clean_outcome):
    """So a bag can be read six months from now without this repo at this commit."""

    notes = " ".join(clean_outcome.sidecar[SIDECAR_EXTRA_KEY]["session_notes"])
    assert "PS-E budget for this profile" in notes
    assert "payload scale" in notes
    assert "rehearsal plan" in notes
    assert "PS-C clocks block" in notes  # certifiability, which build_sidecar drops
