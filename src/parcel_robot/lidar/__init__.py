"""Livox Mid-360 -> the scan the runtime already consumes. Card HW-3.

Two pure modules and one socket adapter:

* :mod:`~parcel_robot.lidar.livox_udp` — ``bytes -> LivoxPointFrame``, decoded
  against the Livox SDK2 frame layout (URLs and the UNCONFIRMED fields are in
  that module's docstring). It refuses rather than guesses.
* :mod:`~parcel_robot.lidar.band` — points -> a planar height band above
  ``base_link`` -> the exact angular layout of
  ``backends/base.py:SimObservation.lidar_ranges``.

**The seam HW-2's ``backends/go2.py:Go2Backend`` calls** is these two symbols
and nothing else. Note the branch: ``BandScan.ranges_m == ()`` means the sweep
measured too little to be a scan (a drained-nothing tick, a cable out, the
wrong NIC, the unit off), and the ``SimObservation`` must then carry the
"no calibrated scan" value so ``reactive_safety`` HOLDs instead of reading
zero measurements as clear space. **Never copy an empty ``BandScan`` across as
if it were a scan.**::

    from parcel_robot.lidar import nearest_obstacle_from_scan, scan_from_frames

    scan = scan_from_frames(drained_frames, self._band_profile)
    fix = nearest_obstacle_from_scan(
        scan, self._band_profile, travel_bearing=travel_bearing_rad(vx, vy)
    )
    if not scan.ranges_m:
        # Not a scan. Publish the absence: scan_present() is False, the core
        # health join reports SCAN missing, translation HOLDs. scan.points_seen
        # / .populated_bins still carry the coverage evidence for the log.
        return SimObservation(..., lidar_ranges=(), nearest_obstacle_m=None)
    return SimObservation(
        ...,
        nearest_obstacle_m=(fix.clearance_m if fix else None),
        nearest_obstacle_bearing_rad=(fix.bearing_rad if fix else None),
        lidar_ranges=scan.ranges_m,
        lidar_angle_min_rad=scan.angle_min_rad,
        lidar_angle_increment_rad=scan.angle_increment_rad,
        lidar_range_min_m=scan.range_min_m,
        lidar_range_max_m=scan.range_max_m,
    )

Nothing in this package imports mujoco, numpy, rclpy, a Livox SDK, or a socket
module: it is the same code on the desktop and on the Orin's CPython 3.10 /
aarch64 (design §5.1), and every test runs offline against synthesised frames.
"""

from __future__ import annotations

from .band import (
    BAND_TUNING_STEP,
    IDENTITY_EXTRINSIC,
    BandProfile,
    BandScan,
    ObstacleFix,
    band_scan,
    nearest_obstacle_from_scan,
    scan_from_frames,
    travel_bearing_rad,
)
from .livox_udp import (
    CMD_DATA_PORT,
    HEADER_SIZE_BYTES,
    HOST_POINT_DATA_PORT,
    IMU_DATA_PORT,
    LIDAR_SAMPLE_HOST_IP,
    LOG_DATA_PORT,
    MAX_POINTS_PER_FRAME,
    POINT_DATA_PORT,
    POINT_SIZE_BYTES,
    PUSH_MSG_PORT,
    SUPPORTED_PROTOCOL_VERSIONS,
    FrameSequenceReport,
    LivoxDataType,
    LivoxDecodeError,
    LivoxPointFrame,
    LivoxTimeType,
    build_point_frame,
    parse_point_frame,
    receive_frames,
    sequence_report,
)

__all__ = [
    "BAND_TUNING_STEP",
    "CMD_DATA_PORT",
    "HEADER_SIZE_BYTES",
    "HOST_POINT_DATA_PORT",
    "IDENTITY_EXTRINSIC",
    "IMU_DATA_PORT",
    "LIDAR_SAMPLE_HOST_IP",
    "LOG_DATA_PORT",
    "MAX_POINTS_PER_FRAME",
    "POINT_DATA_PORT",
    "POINT_SIZE_BYTES",
    "PUSH_MSG_PORT",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "BandProfile",
    "BandScan",
    "FrameSequenceReport",
    "LivoxDataType",
    "LivoxDecodeError",
    "LivoxPointFrame",
    "LivoxTimeType",
    "ObstacleFix",
    "band_scan",
    "build_point_frame",
    "nearest_obstacle_from_scan",
    "parse_point_frame",
    "receive_frames",
    "scan_from_frames",
    "sequence_report",
    "travel_bearing_rad",
]
