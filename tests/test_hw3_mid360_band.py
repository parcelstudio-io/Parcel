"""Card HW-3 `mid360-band` — a Livox sweep becomes the scan the runtime reads.

Card `scrum/20260822/task_36/README.md`; rows R1-R9 of its
`PREREGISTRATION.md`; design `scrum/20260822/task_36/DESIGN.md`.

What these tests can and cannot establish, said once so no row overclaims:

* **No Mid-360 exists here.** Every frame below is SYNTHESISED from the field
  table in `parcel_robot/lidar/livox_udp.py`'s docstring, which was
  transcribed from the Livox SDK2 header, the HAP wire table and the vendor
  driver's own decode (URLs in that docstring). A round trip against our own
  builder proves the parser agrees with our reading of the format; only one
  real datagram on box-day (HW-9) can prove the reading itself. So the first
  test here decodes a frame written **byte by byte, by hand** rather than by
  the builder — if the builder and the parser ever drifted together, that test
  is what notices.
* **No network anywhere.** `receive_frames` is exercised against a plain
  object with a `recv`; nothing here opens, binds or reads a socket.
* **The `reactive_safety` row runs the real functions.** No monkeypatch, no
  stub observation, no fake evidence — a real `SimObservation` built from a
  real band scan, through `scan_present`, `scan_evidence_from_observation` and
  `evaluate_input_health`.
"""

from __future__ import annotations

import math
import random
import struct
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.capture.channels import (
    CHANNELS,
    CHANNELS_BY_ID,
    MATRIX_ROW_TITLES,
    MID360_CHANNELS,
    VENUE_CHANNEL_ROWS,
    CaptureError,
    Confidence,
    SourceDevice,
    Transport,
    UnknownChannelError,
    venue_channel,
    venue_channels_for,
)
from parcel_robot.core.input_health import (
    RequiredInput,
    RequiredInputSpec,
    evaluate_input_health,
)
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.lidar import (
    HEADER_SIZE_BYTES,
    IMU_DATA_PORT,
    MAX_POINTS_PER_FRAME,
    POINT_DATA_PORT,
    POINT_SIZE_BYTES,
    BandProfile,
    LivoxDataType,
    LivoxDecodeError,
    LivoxTimeType,
    band_scan,
    build_point_frame,
    nearest_obstacle_from_scan,
    parse_point_frame,
    receive_frames,
    scan_from_frames,
    sequence_report,
    travel_bearing_rad,
)
from parcel_robot.navigation.reactive_safety import (
    scan_evidence_from_observation,
    scan_present,
)
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE
from scripts.parcel_capture.ingest.base import IngestUnavailableError
from scripts.parcel_capture.ingest.l2 import (
    GO2_EDU_PLUS_VENUE,
    LEGACY_ADDON_L2_VENUE,
    RETIREMENT_NOTE,
    L2Ingest,
    refuse_retired_venue,
)
from scripts.parcel_capture.preflight import AbsenceReason

SEED = 20260823


# ---------------------------------------------------------------------------
# R1 — the frame layout, decoded
# ---------------------------------------------------------------------------


def test_a_hand_written_frame_decodes_to_the_documented_fields() -> None:
    """One frame assembled field by field from the offset table, not by us.

    Deliberately does NOT use ``build_point_frame``: a round trip against our
    own serialiser cannot notice the two drifting together. Every byte below
    is written from the table in ``livox_udp``'s docstring — offsets 0, 1, 3,
    5, 7, 9, 10, 11, 12, 24, 28, 36 — so this cell fails the moment the
    parser's idea of the layout moves.
    """

    header = b"".join(
        (
            (0).to_bytes(1, "little"),  # version
            (36 + 2 * 14).to_bytes(2, "little"),  # length
            (500).to_bytes(2, "little"),  # time_interval, 0.1 us units
            (2).to_bytes(2, "little"),  # dot_num
            (7).to_bytes(2, "little"),  # udp_cnt
            (3).to_bytes(1, "little"),  # frame_cnt
            (1).to_bytes(1, "little"),  # data_type = CARTESIAN_HIGH
            (1).to_bytes(1, "little"),  # time_type = gPTP
            bytes(range(12)),  # rsvd[12]
            (0xDEADBEEF).to_bytes(4, "little"),  # crc32
            (1_700_000_000_000_000_000).to_bytes(8, "little"),  # timestamp ns
        )
    )
    assert len(header) == HEADER_SIZE_BYTES
    body = struct.pack("<iiiBB", 2000, -3000, 400, 128, 0x10) + struct.pack(
        "<iiiBB", 12345, 6789, -50, 3, 0
    )
    frame = parse_point_frame(header + body)

    assert frame.version == 0
    assert frame.declared_length == 64
    assert frame.time_interval_ns == 50_000  # 500 * 100
    assert frame.dot_num == 2
    assert frame.udp_cnt == 7
    assert frame.frame_cnt == 3
    assert frame.data_type is LivoxDataType.CARTESIAN_HIGH
    assert frame.time_type == LivoxTimeType.GPTP and frame.synchronised
    assert frame.reserved == bytes(range(12))
    assert frame.crc32 == 0xDEADBEEF
    assert frame.base_timestamp_ns == 1_700_000_000_000_000_000
    assert frame.point_interval_ns == 25_000  # 50_000 ns / 2 points

    points = list(frame.points_m())
    assert points[0] == pytest.approx((2.0, -3.0, 0.4, 128, 0x10, 1_700_000_000_000_000_000))
    assert points[1] == pytest.approx(
        (12.345, 6.789, -0.05, 3, 0, 1_700_000_000_000_025_000)
    )
    # The tag byte is carried and never interpreted: its bit meanings are in
    # none of the sources read.
    assert [tag for *_xyz, _r, tag, _t in points] == [0x10, 0]


def test_a_synthesised_sweep_round_trips_every_field_and_every_point() -> None:
    """R1. Builder -> parser -> the same numbers, including the timestamps."""

    raw = [(1000 * index, -250 * index, 300 + index, index % 256, 0) for index in range(64)]
    payload = build_point_frame(
        raw,
        time_interval_raw=640,
        udp_cnt=1234,
        frame_cnt=9,
        base_timestamp_ns=42_000_000_000,
    )
    frame = parse_point_frame(payload)

    assert frame.dot_num == len(raw) == len(frame.raw_points)
    assert frame.raw_points == tuple(raw)
    assert frame.declared_length == len(payload)
    assert frame.point_interval_ns == 640 * 100 // 64
    for index, (x, y, z, reflectivity, tag, stamp) in enumerate(frame.points_m()):
        assert (x, y, z) == pytest.approx(
            (raw[index][0] * 1e-3, raw[index][1] * 1e-3, raw[index][2] * 1e-3)
        )
        assert (reflectivity, tag) == (raw[index][3], raw[index][4])
        assert stamp == frame.timestamp_ns(index) == 42_000_000_000 + index * 1000


def test_the_low_resolution_form_is_centimetres_not_millimetres() -> None:
    """The two Cartesian forms differ only in scale; getting it wrong is a 10x
    range error, which is why the scale is a field and not a literal."""

    payload = build_point_frame(
        [(200, -300, 40, 1, 0)], data_type=LivoxDataType.CARTESIAN_LOW
    )
    frame = parse_point_frame(payload)
    assert frame.xyz_scale_m == 1e-2
    assert len(payload) == HEADER_SIZE_BYTES + POINT_SIZE_BYTES[LivoxDataType.CARTESIAN_LOW]
    assert next(frame.xyz_m()) == pytest.approx((2.0, -3.0, 0.4))


# ---------------------------------------------------------------------------
# R2 — the refusals
# ---------------------------------------------------------------------------


def _valid_frame(**kwargs: object) -> bytes:
    return build_point_frame([(1000, 0, 300, 1, 0), (0, 2000, 400, 2, 0)], **kwargs)  # type: ignore[arg-type]


def test_a_truncated_frame_is_refused_and_never_partially_decoded() -> None:
    payload = _valid_frame()
    with pytest.raises(LivoxDecodeError) as caught:
        parse_point_frame(payload[:-3])
    message = str(caught.value)
    assert "2 points of 14 bytes" in message and str(len(payload)) in message


def test_a_frame_longer_than_its_header_declares_is_refused_too() -> None:
    """Over-long is the same defect as truncated: the header and the wire
    disagree, and decoding the prefix would silently drop points."""

    with pytest.raises(LivoxDecodeError, match="truncated or over-long"):
        parse_point_frame(_valid_frame() + b"\x00\x00")


def test_a_header_shorter_than_thirty_six_bytes_is_refused() -> None:
    with pytest.raises(LivoxDecodeError, match="truncated header"):
        parse_point_frame(_valid_frame()[:20])


@pytest.mark.parametrize(
    ("data_type", "expected"),
    [
        (LivoxDataType.IMU, str(IMU_DATA_PORT)),
        (LivoxDataType.SPHERICAL, "pub_handler.cpp:429-431"),
        (LivoxDataType.DOUBLE_ECHO, "livox_lidar_def.h:174-185"),
    ],
)
def test_a_documented_but_undecodable_data_type_is_refused_by_name(
    data_type: LivoxDataType, expected: str
) -> None:
    """The three ``data_type`` values this card does NOT decode: refused with
    the TRUE reason, never decoded as if they were Cartesian points.

    Verifier finding F3: the first version of these messages said the formats
    were undocumented. They are not — spherical is at ``pub_handler.cpp:429-431``
    (0.01 deg, depth mm) and double echo at ``livox_lidar_def.h:174-185`` +
    ``pub_handler.cpp:469-482``. Refusing is still right (out of scope for
    HW-3), but "we could not read it" and "we chose not to implement it" are
    different facts and only the first would justify a stall on box-day.
    """

    payload = bytearray(_valid_frame())
    payload[10] = int(data_type)
    with pytest.raises(LivoxDecodeError) as caught:
        parse_point_frame(bytes(payload))
    message = str(caught.value)
    assert data_type.name in message and expected in message
    assert "UNCONFIRMED" not in message
    if data_type is not LivoxDataType.IMU:
        assert "DOCUMENTED but NOT DECODED" in message


def test_a_data_type_that_is_in_no_livox_header_is_refused_with_the_known_set() -> None:
    payload = bytearray(_valid_frame())
    payload[10] = 0x7F
    with pytest.raises(LivoxDecodeError) as caught:
        parse_point_frame(bytes(payload))
    assert "0x7f" in str(caught.value) and "CARTESIAN_HIGH" in str(caught.value)


def test_an_unread_protocol_version_is_refused_rather_than_assumed() -> None:
    """The field layout is version-defined. Guessing here does not produce a
    wrong log line, it produces an obstacle that is not there."""

    payload = bytearray(_valid_frame())
    payload[0] = 2
    with pytest.raises(LivoxDecodeError, match="SUPPORTED_PROTOCOL_VERSIONS"):
        parse_point_frame(bytes(payload))


def test_a_zero_or_impossible_point_count_is_refused_before_any_allocation() -> None:
    empty = bytearray(_valid_frame())
    empty[5:7] = (0).to_bytes(2, "little")
    with pytest.raises(LivoxDecodeError, match="dot_num is 0"):
        parse_point_frame(bytes(empty[:HEADER_SIZE_BYTES]))

    huge = bytearray(_valid_frame())
    huge[5:7] = (65535).to_bytes(2, "little")
    with pytest.raises(LivoxDecodeError) as caught:
        parse_point_frame(bytes(huge))
    assert str(MAX_POINTS_PER_FRAME) in str(caught.value)


def test_a_non_bytes_payload_is_refused_by_type() -> None:
    with pytest.raises(LivoxDecodeError, match="a Livox frame is bytes"):
        parse_point_frame([0] * 64)  # type: ignore[arg-type]


def test_the_builder_refuses_the_data_types_the_parser_refuses() -> None:
    """One rule, one place: the serialiser cannot mint a frame the decoder
    would have to guess at."""

    with pytest.raises(LivoxDecodeError, match="NOT DECODED"):
        build_point_frame([(1, 2, 3, 0, 0)], data_type=LivoxDataType.SPHERICAL)


# ---------------------------------------------------------------------------
# R3 — ordering evidence
# ---------------------------------------------------------------------------


def test_udp_cnt_and_timestamp_regressions_are_reported_not_hidden() -> None:
    """R3. Out-of-order arrival is EVIDENCE, and evidence is reported.

    Silently reordering or dropping is how a sweep with a hole in it becomes a
    scan that looks complete — and per-bin coverage is exactly what box-day
    has to measure.
    """

    frames = [
        parse_point_frame(_valid_frame(udp_cnt=count, base_timestamp_ns=stamp))
        for count, stamp in ((10, 1000), (11, 2000), (11, 3000), (20, 4000), (21, 3500))
    ]
    report = sequence_report(frames)
    assert report.frames == 5 and report.points == 10
    assert report.duplicate_udp_cnt == (11,)
    assert report.udp_cnt_gaps == ((11, 20),)
    assert report.timestamp_regressions == ((4000, 3500),)
    assert not report.contiguous

    clean = [
        parse_point_frame(_valid_frame(udp_cnt=count, base_timestamp_ns=1000 + tick * 100))
        for tick, count in enumerate((65534, 65535, 0, 1))
    ]
    # A uint16 counter wrapping is the counter doing its job, not a gap.
    assert sequence_report(clean).udp_cnt_gaps == ()
    assert sequence_report(clean).contiguous


# ---------------------------------------------------------------------------
# R5 (layout) — the band reproduces the sim's scan contract exactly
# ---------------------------------------------------------------------------


def test_band_profile_defaults_match_the_sim_scan_contract() -> None:
    """The five numbers are restated in ``band.py`` (importing ``mujoco_lidar``
    would drag mujoco into an aarch64 ``base`` venv) — so the pin lives here,
    where importing the sim is free."""

    from parcel_robot import mujoco_lidar

    profile = BandProfile()
    assert profile.bins == mujoco_lidar.DEFAULT_SCAN_RAYS == 360
    assert profile.angle_min_rad == -math.pi
    assert profile.range_min_m == mujoco_lidar.DEFAULT_SCAN_RANGE_MIN_M
    assert profile.range_max_m == mujoco_lidar.DEFAULT_SCAN_RANGE_MAX_M

    scan = mujoco_lidar.PlanarScan(
        ranges_m=(1.0, 2.0),
        angle_min_rad=-math.pi,
        angle_increment_rad=2.0 * math.pi / 360,
        range_min_m=profile.range_min_m,
        range_max_m=profile.range_max_m,
    )
    assert profile.angle_increment_rad == scan.angle_increment_rad
    # Counter-clockwise, body-relative, bin 0 at -pi: the same statement the
    # sim makes by ``angle_min + increment * arange(num_rays)``.
    assert profile.bin_bearing_rad(0) == -math.pi
    assert profile.bin_bearing_rad(180) == pytest.approx(0.0)
    assert profile.bin_bearing_rad(359) < math.pi


def test_a_band_scan_carries_the_five_sim_observation_scan_fields() -> None:
    """The seam is a copy, not a conversion: HW-2 splats these five across."""

    scan = band_scan([(2.0, 0.0, 0.3)])
    observation = SimObservation(
        timestamp=1.0,
        robot=RobotPose(),
        owner=OwnerTrack(),
        backend="go2",
        lidar_ranges=scan.ranges_m,
        lidar_angle_min_rad=scan.angle_min_rad,
        lidar_angle_increment_rad=scan.angle_increment_rad,
        lidar_range_min_m=scan.range_min_m,
        lidar_range_max_m=scan.range_max_m,
    )
    assert len(observation.lidar_ranges) == 360
    assert observation.lidar_angle_min_rad == -math.pi
    assert observation.lidar_range_max_m == 30.0


@pytest.mark.parametrize("bearing_index", list(range(0, 720, 7)))
def test_a_wall_at_two_metres_lands_in_the_bin_for_its_bearing(bearing_index: int) -> None:
    """R5. A return at bearing theta is 2.000 m in the bin whose ray is theta."""

    profile = BandProfile()
    bearing = -math.pi + bearing_index * (2.0 * math.pi / 720)
    point = (2.0 * math.cos(bearing), 2.0 * math.sin(bearing), 0.35)
    scan = band_scan([point], profile)

    populated = [index for index, value in enumerate(scan.ranges_m) if not math.isnan(value)]
    assert len(populated) == 1
    index = populated[0]
    assert scan.ranges_m[index] == pytest.approx(2.0, abs=1e-9)
    # The bin it landed in is the NEAREST ray, never more than half a bin away.
    error = abs((profile.bin_bearing_rad(index) - bearing + math.pi) % (2 * math.pi) - math.pi)
    assert error <= profile.angle_increment_rad / 2 + 1e-12


def test_an_empty_bin_is_nan_and_never_the_free_space_sentinel() -> None:
    """The design's one judgment call, pinned.

    ``range_max_m`` means "this ray looked and saw nothing", and one Mid-360
    frame cannot say that about a bin nothing was sampled in — the pattern is
    non-repetitive. NaN is the sim's own word for "clears nothing"
    (``mujoco_lidar.PlanarScan`` docstring), so that is what an empty bin gets.
    """

    scan = band_scan([(2.0, 0.0, 0.3)])
    empty = [value for index, value in enumerate(scan.ranges_m) if index != 180]
    assert all(math.isnan(value) for value in empty)
    assert not any(value == scan.range_max_m for value in scan.ranges_m)
    assert scan.populated_bins == 1


def test_the_nearer_return_in_a_bin_wins_because_a_ray_stops_at_the_first_surface() -> None:
    scan = band_scan([(5.0, 0.0, 0.2), (2.0, 0.0, 0.5), (9.0, 0.0, 0.11)])
    assert scan.ranges_m[180] == pytest.approx(2.0)
    assert scan.points_in_band == 3 and scan.populated_bins == 1


# ---------------------------------------------------------------------------
# C1 (correction pass) — a silent sensor is the ABSENCE of a scan
# ---------------------------------------------------------------------------


def test_a_silent_sensor_is_no_scan_not_a_clear_one() -> None:
    """Verifier finding F1 (HOLD), reproduced end to end through the REAL
    safety gate.

    ``scan_from_frames([])`` is exactly what ``Go2Backend`` emits on a tick
    that drained no frames: cable out, wrong NIC, unit off. It used to return
    360 x NaN, and ``reactive_safety.scan_present`` is
    ``bool(observation.lidar_ranges)`` — so zero measurements read as "a scan
    is present", ``nearest_obstacle_m`` was ``None``, and
    ``apply_reactive_safety`` let 0.3 m/s through as "clear". In the sim this
    state cannot arise (the raycaster fills no-hit rays with ``range_max``), so
    the band was introducing a state the safety layer had never been shown.

    An empty sweep now emits ``()`` — the ``SimObservation`` value for "no
    calibrated scan" — and the gate stops the robot.
    """

    from parcel_robot.models import VelocityCommand
    from parcel_robot.navigation.reactive_safety import (
        ReactiveSafetyPolicy,
        apply_reactive_safety,
    )

    scan = scan_from_frames([])
    assert scan.ranges_m == ()
    assert scan.points_seen == 0 and scan.points_in_band == 0 and scan.populated_bins == 0
    assert nearest_obstacle_from_scan(scan) is None

    silent = SimObservation(
        timestamp=1234.5,
        robot=RobotPose(),
        owner=OwnerTrack(),
        backend="go2",
        lidar_ranges=scan.ranges_m,
        lidar_angle_min_rad=scan.angle_min_rad,
        lidar_angle_increment_rad=scan.angle_increment_rad,
        lidar_range_min_m=scan.range_min_m,
        lidar_range_max_m=scan.range_max_m,
    )
    assert scan_present(silent) is False
    assert scan_evidence_from_observation(silent) is None

    policy = ReactiveSafetyPolicy()
    command, reason = apply_reactive_safety(
        VelocityCommand(vx=0.3, vy=0.0, vyaw=0.0),
        silent,
        policy=policy,
        now=silent.timestamp,
    )
    assert (command.vx, command.vy) == (0.0, 0.0)
    assert reason == "stopped"

    # The counterfactual the finding is about, kept as a live assertion: had
    # the band published the all-NaN tuple, the SAME observation would have
    # authorised translation on zero measurements.
    pretending = replace(silent, lidar_ranges=tuple([math.nan] * 360))
    assert scan_present(pretending) is True
    unsafe, unsafe_reason = apply_reactive_safety(
        VelocityCommand(vx=0.3, vy=0.0, vyaw=0.0),
        pretending,
        policy=policy,
        now=silent.timestamp,
    )
    assert (unsafe.vx, unsafe_reason) == (0.3, "clear")


def test_min_populated_bins_is_a_profile_parameter_tuned_at_b11() -> None:
    """The threshold between "a sparse scan" and "not a scan" is a venue
    number, not a constant: ``1`` is only the floor that makes an empty sweep
    impossible to mistake for clear space."""

    points = [(2.0, 0.0, 0.3)]
    assert len(band_scan(points, BandProfile()).ranges_m) == 360

    strict = BandProfile(min_populated_bins=2)
    scan = band_scan(points, strict)
    assert scan.ranges_m == ()
    # Coverage evidence survives the gate: box-day needs the number even on a
    # sweep that did not qualify as a scan.
    assert scan.points_seen == 1 and scan.points_in_band == 1 and scan.populated_bins == 1

    for invalid in (0, -1, 361):
        with pytest.raises(ValueError):
            BandProfile(min_populated_bins=invalid)
    with pytest.raises(TypeError):
        BandProfile(min_populated_bins=1.5)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# C2 (correction pass) — ABSOLUTE direction pins, not self-referential ones
# ---------------------------------------------------------------------------
#
# Verifier finding F2: every layout assertion derived its expected bin from
# ``profile.bin_bearing_rad``, so a consistent clockwise mirror — which tells
# ``reactive_safety`` that an obstacle in the travel corridor is behind it —
# passed 144/144, and moving ``angle_min`` to 0.0 passed all 103 wall cells.
# The four indices below are LITERALS. They are also re-derived from the sim's
# own formula in the test underneath, so the two can never drift apart.


@pytest.mark.parametrize(
    ("point", "index", "bearing_rad"),
    [
        ((2.0, 0.0, 0.3), 180, 0.0),  # dead ahead
        ((0.0, 2.0, 0.3), 270, math.pi / 2),  # to the LEFT
        ((0.0, -2.0, 0.3), 90, -math.pi / 2),  # to the RIGHT
        ((-2.0, 0.0, 0.3), 0, -math.pi),  # behind
    ],
)
def test_a_wall_lands_in_the_absolute_bin_the_sim_would_use(
    point: tuple[float, float, float], index: int, bearing_rad: float
) -> None:
    """Literal indices. A mirrored or rotated layout cannot pass this."""

    scan = band_scan([point])
    assert scan.ranges_m[index] == pytest.approx(2.0, abs=1e-9)
    populated = [i for i, value in enumerate(scan.ranges_m) if not math.isnan(value)]
    assert populated == [index]

    fix = nearest_obstacle_from_scan(scan)
    assert fix is not None
    assert fix.bin_index == index
    assert fix.bearing_rad == pytest.approx(bearing_rad, abs=1e-12)


def test_those_absolute_indices_are_the_sims_own_ray_order() -> None:
    """Re-derived from ``mujoco_lidar.raycast_planar_scan``'s own formula.

    ``angle_min = -math.pi``; ``body_angles = angle_min + angle_increment *
    np.arange(num_rays)`` with ``angle_increment = 2*pi/num_rays`` and
    ``num_rays = DEFAULT_SCAN_RAYS`` (``mujoco_lidar.py``, the CCW body-relative
    scan). So the ray that looks along body bearing ``b`` is
    ``(b + pi) / increment``.
    """

    from parcel_robot import mujoco_lidar

    rays = mujoco_lidar.DEFAULT_SCAN_RAYS
    increment = 2.0 * math.pi / rays

    def sim_ray_index(bearing: float) -> int:
        return round((bearing - (-math.pi)) / increment) % rays

    assert (
        sim_ray_index(0.0),
        sim_ray_index(math.pi / 2),
        sim_ray_index(-math.pi / 2),
        sim_ray_index(-math.pi),
    ) == (180, 270, 90, 0)
    assert sim_ray_index(math.pi) == 0  # +pi and -pi are the same ray


def test_the_scan_runs_counter_clockwise_the_way_the_sim_does() -> None:
    """Index up is bearing up. A clockwise scan puts a left-hand obstacle on
    the right, which is a steering error, not a labelling one.

    Both indices are LITERALS for the same reason as the four cardinals above:
    ``atan2(0.2, 2.0) = 0.09967 rad`` -> ``(0.09967 + pi) / (2*pi/360) + 0.5``
    -> bin 186, and its mirror -> bin 174. Comparing the two returns to each
    other instead would pass under a consistent mirror, which is the hole the
    verifier walked through.
    """

    left_only = [
        i for i, value in enumerate(band_scan([(2.0, 0.2, 0.3)]).ranges_m)
        if not math.isnan(value)
    ]
    right_only = [
        i for i, value in enumerate(band_scan([(2.0, -0.2, 0.3)]).ranges_m)
        if not math.isnan(value)
    ]
    assert left_only == [186]  # +y is ahead-and-LEFT: above the 180 centre
    assert right_only == [174]  # -y is ahead-and-RIGHT: below it

    assert nearest_obstacle_from_scan(band_scan([(2.0, 0.2, 0.3)])).bearing_rad > 0.0
    assert nearest_obstacle_from_scan(band_scan([(2.0, -0.2, 0.3)])).bearing_rad < 0.0


# ---------------------------------------------------------------------------
# C3 (correction pass) — the third documented timestamp discipline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("time_type", "synchronised"),
    [(0, False), (1, True), (2, True), (7, False)],
)
def test_gps_is_a_synchronised_clock_and_an_unknown_time_type_is_not(
    time_type: int, synchronised: bool
) -> None:
    """``comm.h:96-98``: ``kTimestampTypeNoSync=0``,
    ``kTimestampTypeGptpOrPtp=1``, ``kTimestampTypeGps=2``. The enum claimed to
    be the documented set and was missing GPS (verifier F3), so a GPS-synced
    stamp read as unsynchronised. An unknown value is still not synced:
    unknown is absent, never assumed."""

    frame = parse_point_frame(_valid_frame(time_type=time_type))
    assert frame.time_type == time_type
    assert frame.synchronised is synchronised


# ---------------------------------------------------------------------------
# R4 — band properties
# ---------------------------------------------------------------------------


def test_no_point_outside_the_band_can_influence_any_bin() -> None:
    """R4. Randomised, seed 20260823: 200 trials x 2000 points."""

    rng = random.Random(SEED)
    profile = BandProfile()
    for _trial in range(200):
        inside: list[tuple[float, float, float]] = []
        outside: list[tuple[float, float, float]] = []
        for _point in range(2000):
            bearing = rng.uniform(-math.pi, math.pi)
            distance = rng.uniform(0.2, 25.0)
            xy = (distance * math.cos(bearing), distance * math.sin(bearing))
            if rng.random() < 0.5:
                inside.append((*xy, rng.uniform(profile.z_lo_m, profile.z_hi_m)))
            else:
                below = rng.random() < 0.5
                z = rng.uniform(-3.0, profile.z_lo_m - 1e-6) if below else rng.uniform(
                    profile.z_hi_m + 1e-6, 6.0
                )
                outside.append((*xy, z))
        only_inside = band_scan(inside, profile)
        with_outside = band_scan(inside + outside, profile)
        assert with_outside.ranges_m == only_inside.ranges_m
        assert with_outside.points_in_band == only_inside.points_in_band == len(inside)
        assert band_scan(outside, profile).populated_bins == 0


def test_the_band_bounds_are_profile_parameters_and_a_wider_band_sees_more() -> None:
    """`z_lo_m`/`z_hi_m` are tuned at B11; they are not constants."""

    points = [(3.0, 0.0, height / 100.0) for height in range(0, 200, 5)]
    narrow = band_scan(points, BandProfile())
    wide = band_scan(points, BandProfile(z_lo_m=0.0, z_hi_m=2.0))
    assert wide.points_in_band > narrow.points_in_band > 0


def test_the_extrinsic_moves_the_band_because_the_mount_is_not_the_origin() -> None:
    """A sensor 0.4 m above ``base_link`` sees the band 0.4 m lower in its own
    frame. The transform is UNCONFIRMED until B11, which is precisely why it
    is an injected 4x4 and not a constant."""

    lifted = BandProfile(
        extrinsic=(
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.4),
            (0.0, 0.0, 0.0, 1.0),
        )
    )
    sensor_point = (2.0, 0.0, -0.1)  # 0.3 m above base_link once lifted
    assert band_scan([sensor_point], BandProfile()).populated_bins == 0
    assert band_scan([sensor_point], lifted).populated_bins == 1


@pytest.mark.parametrize(
    "profile_kwargs",
    [
        {"z_lo_m": 0.6, "z_hi_m": 0.1},
        {"bins": 1},
        {"range_min_m": 5.0, "range_max_m": 1.0},
        {"extrinsic": ((1.0, 0.0, 0.0, 0.0),) * 4},
        {"z_hi_m": float("nan")},
        {"corridor_half_angle_rad": 0.0},
    ],
)
def test_an_incoherent_band_profile_is_refused_at_construction(
    profile_kwargs: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        BandProfile(**profile_kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# R7 — ``nearest_obstacle_m`` is the SIMULATOR's derivation, not a new one
# ---------------------------------------------------------------------------


def test_nearest_obstacle_is_clearance_from_the_footprint_not_range() -> None:
    """``mujoco_lidar.planar_geom_surface_hit``: ``max(0, distance - radius)``."""

    scan = band_scan([(3.0, 0.0, 0.3)])
    fix = nearest_obstacle_from_scan(scan)
    assert fix is not None
    assert fix.clearance_m == pytest.approx(3.0 - DEFAULT_ROBOT_PROFILE.footprint_radius_m)
    assert fix.bearing_rad == pytest.approx(0.0)
    # Inside the footprint clamps at zero, exactly as the sim clamps.
    inside = band_scan([(0.1, 0.0, 0.3)])
    assert nearest_obstacle_from_scan(inside).clearance_m == 0.0
    assert nearest_obstacle_from_scan(band_scan([])) is None


def test_nearest_obstacle_matches_the_simulators_own_selection() -> None:
    """R7. Differential against the REAL ``sim.select_relevant_obstacle``.

    Imported inside the test because ``parcel_robot.sim`` pulls in mujoco and
    numpy, which is exactly why ``band.py`` reimplements the rule instead of
    importing it — and exactly why the rule needs pinning to the original.
    """

    from parcel_robot.models import VelocityCommand
    from parcel_robot.sim import select_relevant_obstacle

    rng = random.Random(SEED)
    profile = BandProfile()
    radius = profile.footprint_radius_m
    for _trial in range(500):
        points = [
            (
                (distance := rng.uniform(0.4, 20.0)) * math.cos(bearing := rng.uniform(-math.pi, math.pi)),
                distance * math.sin(bearing),
                rng.uniform(profile.z_lo_m, profile.z_hi_m),
            )
            for _point in range(rng.randint(1, 25))
        ]
        scan = band_scan(points, profile)
        candidates = [
            {
                "id": f"bin-{index}",
                "distance_m": max(0.0, value - radius),
                "bearing_rad": profile.bin_bearing_rad(index),
            }
            for index, value in enumerate(scan.ranges_m)
            if not math.isnan(value)
        ]
        if not candidates:
            continue
        for vx, vy in ((0.0, 0.0), (0.3, 0.0), (-0.2, 0.15), (0.0, 0.25)):
            command = VelocityCommand(vx=vx, vy=vy)
            expected = select_relevant_obstacle(list(candidates), command)
            fix = nearest_obstacle_from_scan(
                scan, profile, travel_bearing=travel_bearing_rad(vx, vy)
            )
            assert fix is not None and expected is not None
            assert fix.clearance_m == pytest.approx(expected["distance_m"], abs=1e-12)
            assert fix.bearing_rad == pytest.approx(expected["bearing_rad"], abs=1e-12)


def test_the_travel_bearing_helper_is_the_simulators_translating_test() -> None:
    """``sim.py:67-69``: ``hypot(vx, vy) > 1e-6``, bearing ``atan2(vy, vx)``."""

    assert travel_bearing_rad(0.0, 0.0) is None
    assert travel_bearing_rad(1e-7, 0.0) is None
    assert travel_bearing_rad(0.0, 2.0) == pytest.approx(math.pi / 2)
    assert travel_bearing_rad(float("nan"), 0.0) is None


def test_a_closer_obstacle_behind_never_masks_one_in_the_travel_corridor() -> None:
    """The defect ``select_relevant_obstacle`` exists for, on band output."""

    profile = BandProfile()
    scan = band_scan([(-1.0, 0.0, 0.3), (4.0, 0.0, 0.3)], profile)
    ahead = nearest_obstacle_from_scan(scan, profile, travel_bearing=0.0)
    assert ahead is not None and ahead.bearing_rad == pytest.approx(0.0)
    stationary = nearest_obstacle_from_scan(scan, profile, travel_bearing=None)
    assert stationary is not None and abs(stationary.bearing_rad) == pytest.approx(math.pi)


# ---------------------------------------------------------------------------
# R6 — through the real reactive-safety functions
# ---------------------------------------------------------------------------


def _observation_from_band(points: list[tuple[float, float, float]]) -> SimObservation:
    scan = scan_from_frames(
        [
            parse_point_frame(
                build_point_frame(
                    [
                        (round(x * 1000), round(y * 1000), round(z * 1000), 100, 0)
                        for x, y, z in points
                    ]
                )
            )
        ]
    )
    fix = nearest_obstacle_from_scan(scan)
    return SimObservation(
        timestamp=1234.5,
        robot=RobotPose(x=1.0, y=2.0, yaw=0.3),
        owner=OwnerTrack(),
        nearest_obstacle_m=(fix.clearance_m if fix is not None else None),
        nearest_obstacle_bearing_rad=(fix.bearing_rad if fix is not None else None),
        backend="go2",
        lidar_ranges=scan.ranges_m,
        lidar_angle_min_rad=scan.angle_min_rad,
        lidar_angle_increment_rad=scan.angle_increment_rad,
        lidar_range_min_m=scan.range_min_m,
        lidar_range_max_m=scan.range_max_m,
    )


def test_scan_present_is_true_on_a_band_observation_through_the_real_function() -> None:
    """R6, first half. No monkeypatch: the real ``scan_present``, on a real
    ``SimObservation`` built from a real decoded frame."""

    observation = _observation_from_band([(2.0, 0.0, 0.3), (0.0, -3.0, 0.5)])
    assert scan_present(observation) is True
    assert len(observation.lidar_ranges) == 360
    assert observation.nearest_obstacle_m is not None

    # And an empty sweep is honestly empty: no lidar_obstacles, no ranges, no
    # nearest — ``scan_present`` says False rather than inventing a channel.
    empty = SimObservation(timestamp=1.0, robot=RobotPose(), owner=OwnerTrack(), backend="go2")
    assert scan_present(empty) is False


def test_the_real_evidence_rule_labels_a_sim_observation_a_labelled_fixture() -> None:
    """R6, second half — and the card's one unsatisfiable sentence, recorded.

    The card asks that ``scan_evidence_from_observation`` "labels it physical
    when ``backend='go2'``". It cannot, and that is not a defect here: card
    W0-A / board decision D-1 made ``core/input_health.py:evidence_origin``
    return ``EvidenceOrigin.SIMULATION`` for EVERY sample carried on a
    ``SimObservation``, because authority comes from the CARRIER TYPE and
    "there is no string ... that reaches ``EvidenceOrigin.PHYSICAL`` from here
    or from anywhere else". Design §4 row S1's "``evidence_origin ==
    physical``" is therefore a HW-2 obligation to publish the scan through
    ``control/base.py:CommissionedStateSource(origin=EvidenceOrigin.PHYSICAL)``,
    not something a band scan can mint.

    What IS true and load-bearing is asserted instead: the band's evidence is a
    LABELLED fixture, and the health join ALLOWS translation on it under
    ``reactive_safety``'s own SCAN spec.
    """

    observation = _observation_from_band([(2.0, 0.0, 0.3)])
    evidence = scan_evidence_from_observation(observation)
    assert evidence is not None
    assert evidence.origin is EvidenceOrigin.SIMULATION
    assert evidence.origin is not EvidenceOrigin.PHYSICAL
    assert evidence.fixture_label == "go2"
    assert evidence.frame_id == "base_link"
    assert evidence.captured_at == observation.timestamp
    assert evidence.payload_valid is True

    verdict = evaluate_input_health(
        {RequiredInput.SCAN: evidence},
        now=observation.timestamp + 0.05,
        requirements={
            RequiredInput.SCAN: RequiredInputSpec(
                frame_id="base_link", max_age_s=0.25, sim_fixture_allowed=True
            )
        },
    )
    assert verdict.translation_allowed is True

    # No scan at all is None, not an unlabelled sample that could latch.
    assert (
        scan_evidence_from_observation(
            SimObservation(timestamp=1.0, robot=RobotPose(), owner=OwnerTrack(), backend="go2")
        )
        is None
    )


# ---------------------------------------------------------------------------
# R8 — performance, RECORDED not gated
# ---------------------------------------------------------------------------


def test_one_twenty_thousand_point_sweep_becomes_ranges_in_well_under_a_tick() -> None:
    """R8. The number goes in ``HW3_STATUS.md``; the Orin's is box-day.

    The ceiling asserted here is deliberately loose (the card's expectation is
    < 20 ms on this desktop): a wall-clock assertion on a shared 192-core box
    is a flake, and this row exists to record a number, not to gate a build.
    """

    rng = random.Random(SEED)
    payloads = []
    for count in range(209):
        points = []
        for _point in range(96):
            bearing = rng.uniform(-math.pi, math.pi)
            distance = rng.uniform(0.5, 20.0)
            points.append(
                (
                    round(distance * math.cos(bearing) * 1000),
                    round(distance * math.sin(bearing) * 1000),
                    round(rng.uniform(-0.3, 2.0) * 1000),
                    rng.randrange(256),
                    0,
                )
            )
        payloads.append(build_point_frame(points, udp_cnt=count))

    start = time.perf_counter()
    frames = [parse_point_frame(payload) for payload in payloads]
    scan = scan_from_frames(frames)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert scan.points_seen == 209 * 96 >= 20_000
    assert scan.populated_bins > 0
    print(f"\nHW-3 R8: {scan.points_seen} points -> ranges in {elapsed_ms:.2f} ms")
    assert elapsed_ms < 1000.0


# ---------------------------------------------------------------------------
# The socket adapter, and the purity that lets everything above run offline
# ---------------------------------------------------------------------------


class _FakeDatagramSocket:
    """A ``recv`` and nothing else. No socket module is imported anywhere."""

    def __init__(self, datagrams: list[bytes]) -> None:
        self._datagrams = list(datagrams)
        self.calls = 0

    def recv(self, _size: int) -> bytes:
        self.calls += 1
        return self._datagrams.pop(0)


def test_receive_frames_reads_a_socket_it_did_not_create_and_can_skip_a_bad_one() -> None:
    good = _valid_frame(udp_cnt=1)
    corrupt = bytearray(_valid_frame(udp_cnt=2))
    corrupt[10] = 0x7F
    sock = _FakeDatagramSocket([good, bytes(corrupt), _valid_frame(udp_cnt=3)])

    refusals: list[LivoxDecodeError] = []
    frames = list(receive_frames(sock, max_frames=2, on_refusal=refusals.append))
    assert [frame.udp_cnt for frame in frames] == [1, 3]
    assert len(refusals) == 1 and "0x7f" in str(refusals[0])

    # Without a callback the refusal propagates: a reader that silently eats
    # corrupt datagrams cannot report coverage.
    strict = _FakeDatagramSocket([bytes(corrupt)])
    with pytest.raises(LivoxDecodeError):
        list(receive_frames(strict, max_frames=1))


def test_the_lidar_package_imports_with_no_numpy_no_mujoco_and_no_socket() -> None:
    """The aarch64 ``base`` extra pin (design §5.1), measured not asserted.

    A subprocess imports the package and reports ``sys.modules``. numpy and
    mujoco are both installed here, so an accidental import would go unnoticed
    on this desktop and fail on the Orin, in the capture venv, on a session
    morning.
    """

    probe = (
        "import sys, json;"
        "import parcel_robot.lidar as pkg;"
        "print(json.dumps(sorted(name for name in sys.modules"
        " if name.split('.')[0] in {'numpy', 'mujoco', 'socket', 'rclpy', 'torch'})))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=True,
    )
    assert result.stdout.strip().endswith("[]"), result.stdout


def test_the_documented_ports_are_the_mid360_ports() -> None:
    """Transcribed from ``mid360_config.json``; the runtime reader binds the
    host side (+1), and which NIC it binds is UNKNOWN until the box (Q-wire)."""

    from parcel_robot.lidar import (
        CMD_DATA_PORT,
        HOST_POINT_DATA_PORT,
        LIDAR_SAMPLE_HOST_IP,
        LOG_DATA_PORT,
        PUSH_MSG_PORT,
    )

    assert (CMD_DATA_PORT, PUSH_MSG_PORT, POINT_DATA_PORT, IMU_DATA_PORT, LOG_DATA_PORT) == (
        56100,
        56200,
        56300,
        56400,
        56500,
    )
    assert HOST_POINT_DATA_PORT == 56301
    assert LIDAR_SAMPLE_HOST_IP == "192.168.1.5"


# ---------------------------------------------------------------------------
# The capture table: a new device, rows beside the matrix, and the L2 retirement
# ---------------------------------------------------------------------------


def test_the_mid360_rows_live_beside_the_payload_matrix_and_never_inside_it() -> None:
    """``CHANNEL_MATRIX.md`` is immutable (20260813) and describes a rig the
    owner did not buy. Growing table A is a document change first — a handoff,
    recorded in ``HW3_STATUS.md`` — so these rows sit beside the 28 exactly as
    card S-1's support artifacts do."""

    assert len(CHANNELS) == 28
    assert len(MATRIX_ROW_TITLES) == 25
    assert len(MID360_CHANNELS) == VENUE_CHANNEL_ROWS == 2
    for entry in MID360_CHANNELS:
        assert entry.channel_id not in CHANNELS_BY_ID
        assert entry.device is SourceDevice.MID360
        assert entry.venue == "go2_edu_plus"
        # No matrix row is claimed, because there is none to claim.
        assert not hasattr(entry, "matrix_row")
        # Presence is a prior and the prior is honest: no hardware is on hand.
        assert entry.presence.value == "awaiting_hardware"
        assert entry.confidence is Confidence.UNVERIFIED

    cloud = venue_channel("mid360.cloud")
    assert cloud.transport is Transport.DDS
    assert cloud.wire_address == "rt/livox/lidar"
    assert cloud.bag_topic == "mid360/cloud" and cloud.is_spatial
    # The payload clock is UNVERIFIED on purpose: time_type decides it.
    assert not cloud.carries_a_time_anchor
    assert venue_channels_for("go2_edu_plus") == MID360_CHANNELS
    assert venue_channels_for("nowhere") == ()
    with pytest.raises(UnknownChannelError):
        venue_channel("go2.lowstate")


def test_a_venue_row_that_lies_about_its_wire_name_is_refused() -> None:
    """The silent failure this rule exists for: a raw-DDS reader on the
    unmangled name receives zero messages and no error."""

    from parcel_robot.capture.channels import VenueChannel

    fields = {
        "channel_id": "mid360.test",
        "human_name": "test",
        "device": SourceDevice.MID360,
        "transport": Transport.DDS,
        "address": "livox/lidar",
        "wire_address": "livox/lidar",
        "message_type": "x",
        "rate_kind": venue_channel("mid360.cloud").rate_kind,
        "nominal_rate_hz": None,
        "source_clock": venue_channel("mid360.cloud").source_clock,
        "frame_id": "livox_frame",
        "criticality": venue_channel("mid360.cloud").criticality,
        "presence": venue_channel("mid360.cloud").presence,
        "confidence": Confidence.UNVERIFIED,
        "venue": "go2_edu_plus",
        "note": "x",
    }
    with pytest.raises(CaptureError, match="wire_address must be"):
        VenueChannel(**fields)  # type: ignore[arg-type]
    with pytest.raises(CaptureError, match="non-empty"):
        VenueChannel(**{**fields, "wire_address": "rt/livox/lidar", "note": "  "})  # type: ignore[arg-type]


def test_the_add_on_l2_adapter_refuses_the_edu_plus_venue_and_points_at_hw3() -> None:
    """The retirement, through the real adapter.

    The file, the class and ``SourceDevice.L2`` all stay — bags recorded on the
    old rig join on ``l2.cloud``. What cannot happen any more is pointing this
    adapter at the rig the owner actually bought.
    """

    with pytest.raises(IngestUnavailableError) as caught:
        L2Ingest(venue=GO2_EDU_PLUS_VENUE)
    assert caught.value.reason is AbsenceReason.NOT_ATTEMPTED
    assert "parcel_robot.lidar" in caught.value.remedy
    assert "do not build unilidar_sdk2" in caught.value.remedy.lower()
    assert "task_36" in str(caught.value)

    with pytest.raises(IngestUnavailableError):
        refuse_retired_venue(GO2_EDU_PLUS_VENUE)
    assert refuse_retired_venue(LEGACY_ADDON_L2_VENUE) is None

    # The old rig still works exactly as it did, and every report this adapter
    # emits now carries the pointer.
    legacy = L2Ingest()
    assert legacy.venue == LEGACY_ADDON_L2_VENUE
    assert legacy.endpoint == "udp://192.168.1.2"
    assert RETIREMENT_NOTE in L2Ingest.notes
    assert "rt/utlidar/*" in RETIREMENT_NOTE
