#!/usr/bin/env python
"""Preflight discovery — probe every channel in the PS-A matrix, prove nothing else.

Card PS-D of tranche PS-1 (``scrum/20260813/task_1/README.md``). This module
answers exactly one question, per channel and per device: *did a message
actually arrive, and what is the evidence?* :mod:`scripts.parcel_capture.attest`
turns those answers into a ``HardwareAttestationV1`` and rules on the firmware
pin; this file does the looking.

The spine: unknown is absent
----------------------------
Board rule 3, applied without exception. There is **no constructor argument**
anywhere in this module that can name :attr:`ProbeStatus.PRESENT`.
:attr:`ChannelProbe.status` is a derived property whose first branch is
``messages_received <= 0 -> ABSENT``, so presence is a *consequence* of a
received message rather than a claim a caller can make. Everything else follows
from that:

* a probe that times out is ABSENT (:attr:`AbsenceReason.TIMEOUT`);
* a probe that raises is ABSENT (:attr:`AbsenceReason.PROBE_RAISED`), and the
  receipts it had already yielded are **discarded**, because partial evidence
  from a failed probe is not evidence — the count is retained in
  :attr:`ChannelProbe.receipts_discarded` so the operator sees what was thrown
  away rather than having it vanish;
* a probe whose reader breaks its own contract — a receipt labelled with the
  wrong channel, a zero-byte "message", a clock that runs backwards — is ABSENT
  with :attr:`AbsenceReason.PROBE_CONTRACT_VIOLATION`, which is deliberately a
  *different* word from a device error so a broken adapter is never mistaken for
  a missing sensor;
* a missing dependency, a missing device node, a missing tool are three
  different absences and each names its own remedy.

A channel is not healthy because bytes arrive
--------------------------------------------
Card PS-J (corrective tranche PS-2) adds the second question. Receipt counting
answers *did a message arrive*; it cannot answer *is what arrived possible*. The
concrete case: ``utlidar/imu`` has two independent unfixed field reports of
emitting ~-2.17e24 m/s^2, and a receipt-count probe attests that as healthy.

So every channel now also carries a :class:`PlausibilityVerdict` —
``PASS``/``FAIL``/``UNKNOWN`` — derived from rules selected by
:func:`classify_channel` off the matrix's declared message type. Three
properties are load-bearing and each is pinned by a test:

* **UNKNOWN is not a soft PASS.** No rest period observed, no measurement
  supplied, too few samples: all UNKNOWN, and UNKNOWN never decays into PASS.
* **The verdict never silences a recording.** :attr:`ChannelProbe.status` is
  computed without reference to plausibility, and plausibility findings are
  capped at MAJOR so they can never drive the *record nothing* branch. A suspect
  channel is still evidence; it is recorded with its verdict attached.
* **This layer only ever makes the attestation stricter.** It adds findings and
  a verdict; it removes no refusal and relaxes no existing rule.

The four IMUs (dog body, built-in LiDAR, add-on L2, D455) are grouped by
``(device, frame_id)`` in :func:`imu_unit_id` and cross-checked against each
other at rest by :func:`imu_cross_check`: three units at 9.81 and one at 1e24
identifies the broken unit with no calibration and no second session.

Two Pythons, and two facts: the module and the device
-----------------------------------------------------
This tree may assume Python 3.10 + Humble because it runs on the Orin; it is
*developed* on a box with **no device of any kind attached** — no dog, no
camera, no LiDAR. Whether that box also carries a vendor SDK is a *separate*
question, and cards ENV-1/ENV-1b exist because collapsing the two produced a
false READY: ``pyrealsense2`` was installed into ``.parcel`` on 2026-08-22 for
the desk-camera venue, and every D455 probe promptly reported itself satisfied
on a host that has never had a camera plugged into it. (A venv built from
``pip install .[dev]`` carries no such wheel, because the project declares it in
the ``camera-realsense`` extra rather than in ``dev`` — so both states are
supported and neither is assumed. Card TRUTH-1: the reason written here used to
be an aarch64 claim, and that claim was never measured and is false. Measured
2026-08-22, re-measured 2026-08-23: pyrealsense2 2.58.3.10794 ships 13 files and
publishes ``manylinux2014_aarch64`` for cp39/cp310/cp312, which includes
JetPack 6's CPython 3.10. The narrow true statement is that every OTHER aarch64
interpreter — 3.8 on a JetPack 5.1.1 dock included — needs a source build.)

So the default reader for every transport is a reader that **refuses with a
remedy naming which half is missing**: the module is not on the import path
(``importlib.util.find_spec``, never an import) or the device is not attached (a
``/dev`` glob census, never an open). ``pip install`` and *plug the cable in*
are different instructions and an operator handed the wrong one loses a session
morning. For the motion SDKs the refusal additionally forbids the fix that would
break board rule 1: do not ``pip install`` ``unitree_sdk2py`` into ``.parcel/``.
Its absence from that venv is the strongest motion guarantee the project
currently has (``PHYSICAL_SESSION_PLAN.md``), and a preflight tool is not worth
spending it. A *camera* SDK cannot command anything and is not part of that
guarantee.

Running this file on a bare dev box is therefore a supported, first-class
outcome: every channel ABSENT, every absence explained and attributed to the
module or to the device, exit non-zero, no traceback.

One list of channels
--------------------
The channel enumeration is :data:`parcel_robot.capture.CHANNELS` — PS-A's
transcription of ``CHANNEL_MATRIX.md``. This module keeps **no second list**. It
reads ``rate_kind``/``nominal_rate_hz``/``criticality``/``presence`` off that
table and treats every one of them as a *declared expectation to be falsified*,
never as authority: a channel the table calls ``LIVE`` is still ABSENT until a
message arrives.

What a probe here does not do
-----------------------------
It does not record. It creates no publisher, no ``ControlManager``, no lease and
no motion client, and it holds no writable handle to the robot: a reader yields
:class:`SampleReceipt` metadata (size and timestamps), not payloads. Recording is
PS-B's; clock discipline is PS-C's; the bandwidth budget is PS-E's, and this
module refuses to invent the disk number it does not own.
"""

from __future__ import annotations

import argparse
import importlib
import itertools
import json
import math
import os
import platform
import re
import shutil
import socket
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised only on a checkout without an install
    from parcel_robot.capture.channels import (
        CHANNELS,
        Channel,
        ChannelPresence,
        Criticality,
        RateKind,
    )
except ImportError:  # pragma: no cover - Orin runs this straight from a checkout
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from parcel_robot.capture.channels import (
        CHANNELS,
        Channel,
        ChannelPresence,
        Criticality,
        RateKind,
    )

#: Wire identifier of the preflight report. A reader that does not know this
#: string must refuse the record rather than guess at its shape.
PREFLIGHT_SCHEMA = "parcel.capture.preflight.v1"

#: Repo root, resolved from this file rather than from the working directory:
#: preflight is run from an operator's shell at 08:00 on a session morning and
#: must not depend on where they happened to be standing.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The config file whose network block this module reads *textually*. See
#: :func:`probe_network` for why a YAML parse is the wrong tool here.
ROBOT_CONFIG = REPO_ROOT / "configs" / "robot.yaml"

#: Default observation window. Long enough that the slowest PERIODIC channel in
#: the matrix (``utlidar/voxel_map_compressed``, ~1 Hz) clears
#: :data:`MIN_RATE_SAMPLES`; short enough to run the whole matrix while a dog
#: stands on a bench.
DEFAULT_WINDOW_S = 12.0

#: Below this fraction of the expected rate a channel is DEGRADED, not PRESENT.
#: Derived, not chosen: the PS-B card requires that "a channel delivering 90% of
#: its nominal rate is reported as degraded", so the floor must sit strictly
#: above 0.90. 0.95 leaves 5% for scheduler jitter over a >=10 s window.
RATE_DEFICIT_FLOOR = 0.95

#: Above this multiple of the expected rate a channel is DEGRADED too. A stream
#: at 3x nominal is a misconfiguration and it is PS-E's storage budget that pays
#: for it, so it is a finding rather than a pleasant surprise.
RATE_EXCESS_CEILING = 1.5

#: A silence longer than this many expected periods is a stall. Without it, a
#: channel that delivers its whole burst in the first 200 ms and then dies scores
#: a nominal average rate over the window and passes as PRESENT.
MAX_GAP_PERIODS = 5.0

#: Fewest messages a window must be able to contain before an observed rate is
#: allowed to mean anything. One sample in a 2 s window cannot distinguish 1 Hz
#: from 0.4 Hz, so the honest answer is UNASSESSED, not NOMINAL.
MIN_RATE_SAMPLES = 10.0

# ---------------------------------------------------------------------------
# Physical-plausibility bounds
# ---------------------------------------------------------------------------
#
# Card PS-J (tranche PS-2). Receipt counting rules a channel PRESENT the moment
# bytes arrive, and **a channel is not healthy because bytes arrive**:
# ``utlidar/imu`` has two independent unfixed field reports of emitting
# ~-2.17e24 m/s^2, which a receipt-count probe attests as healthy. Every
# constant below is a bound on the PHYSICAL WORLD or on a sensor's own full
# scale, cited where it comes from, and none of them is a tuning knob a
# session may relax to make a channel look better.

#: Standard gravity (CODATA/ISO 80000). A rigidly-mounted IMU at rest measures
#: the reaction to it, so ``|accel|`` at rest is this, not zero.
GRAVITY_MPS2 = 9.80665

#: Half-width of the at-rest ``|accel|`` acceptance band, in m/s^2. The PS-2
#: corrective card sets it at 9.81 +/- 1.0: wide enough for bias, scale error
#: and a hand on the bench, far narrower than any broken-driver value.
ACCEL_REST_TOLERANCE_MPS2 = 1.0

#: At-rest ``|gyro|`` ceiling, rad/s. 0.05 rad/s is ~2.9 deg/s — above MEMS
#: noise plus bias, below any real motion.
GYRO_REST_CEILING_RPS = 0.05

#: No accelerometer on this rig can *report* beyond its own full scale. The
#: D455's BMI055 tops out at +/-16 g = 156.9 m/s^2 and the Go2/L2 units are of
#: the same class; 200 m/s^2 leaves headroom over every one of them. A value
#: past this is not a measurement of the world, it is a broken decode — and it
#: is judged WITHOUT needing a rest period, which is what makes the 1e24 case
#: catchable in any take.
ACCEL_SENSOR_CEILING_MPS2 = 200.0

#: Same argument for rate gyros: +/-2000 deg/s = 34.9 rad/s full scale, so 40.
GYRO_SENSOR_CEILING_RPS = 40.0

#: Largest spread in mean ``|accel|`` tolerated ACROSS the independent IMU
#: units at rest before they are reported as disagreeing. Twice the
#: single-unit band: two units may each sit at opposite edges of it honestly.
IMU_CROSS_CHECK_TOLERANCE_MPS2 = 2.0

#: Longest range a point in either LiDAR's cloud may carry, metres. Both units
#: are short-range (L2 is specified in the tens of metres); 200 m is a bound on
#: absurdity, not a spec assertion, and exists to catch a unit-scale error
#: (mm reported as m) and a garbage decode.
POINT_RANGE_CEILING_M = 200.0

#: Per-point field names that let an LIO package deskew a cloud. A PointCloud2
#: without one of these cannot be motion-compensated by GLIM, FAST-LIO2,
#: Point-LIO or KISS-ICP, and that is discoverable ONLY while the rig is
#: powered — it is the reason the fields[] list is dumped verbatim.
DESKEW_TIME_FIELD_NAMES: frozenset[str] = frozenset(
    {"t", "ts", "time", "timestamp", "time_stamp", "offset_time", "time_offset",
     "point_time", "relative_time", "timestamp_ns"}
)

#: Per-point field names that identify the laser a point came from. Ring-based
#: LIO packages (LIO-SAM class) require one; time-based deskew does not.
DESKEW_RING_FIELD_NAMES: frozenset[str] = frozenset(
    {"ring", "line", "laser_id", "lasernumber", "laser_number", "scan_id", "row"}
)

#: Absolute per-cell bounds for a Li-ion cell, volts. 2.5 V is below any
#: sane cutoff and 4.35 V above any sane full charge, so a value outside this
#: is a decode or a units error (the classic: millivolts reported as volts).
CELL_VOLTAGE_MIN_V = 2.5
CELL_VOLTAGE_MAX_V = 4.35

#: Nothing on this rig runs above 100 V. Bounds ``power_v`` even when the cell
#: array is absent, so garbage is still caught without asserting a pack model.
PACK_VOLTAGE_CEILING_V = 100.0

#: ``sum(cell_vol)`` versus ``power_v``: the two must agree. Research item 6 —
#: ``BmsState`` has no voltage field, so pack voltage is either the cell sum or
#: ``LowState.power_v``, and if those two disagree one of them is wrong.
PACK_CONSISTENCY_TOLERANCE_V = 1.0
PACK_CONSISTENCY_TOLERANCE_FRACTION = 0.02

#: Feet on a quadruped. ``foot_force[4]`` and ``foot_force_est[4]`` both.
FOOT_FORCE_CHANNELS = 4

#: An ``int16`` raw count. Research item 7: foot force has NO published units,
#: gain or offset — it is an air-pressure contact proxy — so this bounds the
#: CONTAINER, and no rule here asserts an absolute force.
FOOT_FORCE_COUNT_MIN = -32768
FOOT_FORCE_COUNT_MAX = 32767

#: Fewest samples before "these four counts do not vary" means anything. Below
#: this the honest answer is UNKNOWN: a stuck sensor and a slow one look alike.
FOOT_FORCE_MIN_SAMPLES = 10

#: A frame at or above this fraction of all-zero (or all-saturated) pixels is
#: degenerate: a lens cap, a dead exposure, a depth frame with no returns.
IMAGE_DEGENERATE_FRACTION = 0.98

#: L4T release string -> JetPack version. A DECLARED table, falsifiable like
#: everything else here: an L4T release absent from it yields an ABSENT JetPack
#: observation while the raw release string is still recorded verbatim. Guessing
#: a JetPack version from an unknown L4T is exactly the permissive default that
#: board rule 3 forbids.
L4T_TO_JETPACK: Mapping[str, str] = {
    "36.3.0": "JetPack 6.0 (GA)",
    "36.4.0": "JetPack 6.1",
    "36.4.3": "JetPack 6.2",
    "36.4.4": "JetPack 6.2.1",
}

#: The two documents that disagree about the built-in LiDAR, and what each one
#: claims. Neither is evidence; both are defendants. PS-D resolves the question
#: by reading the unit and then records which document was wrong.
BUILTIN_LIDAR_CLAIMS: Mapping[str, str] = {
    "unitree product page (cited in CHANNEL_MATRIX.md:78-80)": "L2",
    "scrum/20260805/task_1/P5_PROCUREMENT_BOM.md optional item A (:35 at base "
    "406f9d6, :75 after the 2026-08-13 banner)": "L1",
}

#: Dotted config paths that are allowed to name the robot's Ethernet NIC. Exact
#: strings, so a mis-scan of the config (see :func:`probe_network`) can only ever
#: fail to find a NIC — never promote ``wifi_cards.simulator.interface`` (``lo``)
#: into one.
ROBOT_NIC_CONFIG_PATHS = (
    "control.unitree_sport.interface",
    "wifi_cards.robot.interface",
)

#: Dotted config paths carrying a DDS domain id.
DDS_DOMAIN_CONFIG_PATHS = (
    "control.unitree_sport.domain_id",
    "wifi_cards.robot.ros_domain_id",
)

#: Substrings that mark a config value as a placeholder rather than a setting.
#: ``configs/robot.yaml:128`` carries "replace with the dedicated robot Ethernet
#: NIC" and has done since P0; a preflight that trusted it would attest a NIC
#: nobody chose.
PLACEHOLDER_MARKERS = ("replace with", "todo", "fixme", "placeholder", "example", "<")


class PreflightError(RuntimeError):
    """Base for every refusal raised by this module."""


class ProbeContractError(PreflightError):
    """A reader broke the probe contract. Distinct from a device error.

    Raised by the driver's own validation, never by a device. A channel whose
    reader mislabels a receipt is ABSENT like any other failure — but it is
    ABSENT for a reason that names a software defect, so nobody spends the
    session hunting a sensor that was fine.
    """


class TransportUnavailableError(PreflightError):
    """A transport cannot be reached at all, with an actionable remedy.

    Carries the remedy as :attr:`remedy` so the report can print it verbatim.
    Every remedy in this module is one an operator can act on in the room, and
    none of them is "install the vendor SDK into ``.parcel/``".
    """

    def __init__(self, reason: AbsenceReason, detail: str, remedy: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail
        self.remedy = remedy


class ProbeStatus(str, Enum):
    """Per-channel outcome. Never a constructor argument — always derived."""

    #: A message was received and the channel met every expectation we could
    #: assess. The only value that requires evidence.
    PRESENT = "present"
    #: A message was received and something about it was outside expectation.
    DEGRADED = "degraded"
    #: No message was received. The fail-closed value, and the default outcome
    #: of every failure mode this module knows about.
    ABSENT = "absent"


class AbsenceReason(str, Enum):
    """Why nothing arrived. Every ABSENT carries exactly one of these.

    The distinctions are load-bearing: ``DEPENDENCY_MISSING`` is a laptop
    problem, ``DEVICE_NODE_MISSING`` is a cable, ``TIMEOUT`` is a sensor or a
    network, and ``PROBE_CONTRACT_VIOLATION`` is our own bug. Collapsing them
    into "absent" would cost a session-day of debugging.
    """

    #: The Python module the transport needs is not importable here.
    DEPENDENCY_MISSING = "dependency_missing"
    #: The device file the transport addresses does not exist.
    DEVICE_NODE_MISSING = "device_node_missing"
    #: The platform tool the transport shells out to is not on PATH.
    TOOL_MISSING = "tool_missing"
    #: The observation window elapsed with nothing received.
    TIMEOUT = "timeout"
    #: The reader finished early having yielded nothing.
    NO_MESSAGE = "no_message"
    #: The probe raised. Any exception invalidates the whole probe.
    PROBE_RAISED = "probe_raised"
    #: The reader violated the probe contract. A software defect, not a sensor.
    PROBE_CONTRACT_VIOLATION = "probe_contract_violation"
    #: Not probed at all. Never produced by a probe that ran.
    NOT_ATTEMPTED = "not_attempted"
    #: The value exists only as a config placeholder, so it is not a value.
    CONFIG_PLACEHOLDER = "config_placeholder"
    #: Two config paths disagree, so neither is trusted.
    CONFIG_AMBIGUOUS = "config_ambiguous"
    #: This host is not a Jetson; the Orin-only file or tool is absent.
    NOT_A_JETSON = "not_a_jetson"
    #: A machine read produced something we refuse to interpret.
    UNPARSEABLE = "unparseable"
    #: No operator typed the label in, and no machine path exists for it.
    NO_OPERATOR_OBSERVATION = "no_operator_observation"


class RateAssessment(str, Enum):
    """What the observed rate says, or why it says nothing."""

    #: No message arrived; there is no rate to assess.
    NOT_APPLICABLE = "not_applicable"
    #: The channel is event-driven. Silence is normal and a rate is meaningless.
    EVENT_DRIVEN = "event_driven"
    #: Nobody supplied an expected rate (a CONFIGURED or UNKNOWN rate_kind with
    #: no capture configuration behind it). Unassessable, never nominal.
    UNASSESSED_NO_EXPECTATION = "unassessed_no_expectation"
    #: The window could not hold :data:`MIN_RATE_SAMPLES` messages even at the
    #: expected rate, so the estimate cannot discriminate.
    UNASSESSED_WINDOW_TOO_SHORT = "unassessed_window_too_short"
    NOMINAL = "nominal"
    #: Observed below :data:`RATE_DEFICIT_FLOOR` of expected.
    DEFICIT = "deficit"
    #: Observed above :data:`RATE_EXCESS_CEILING` of expected.
    EXCESS = "excess"
    #: Average rate looked fine but the stream went quiet for longer than
    #: :data:`MAX_GAP_PERIODS` expected periods.
    STALLED = "stalled"

    @property
    def is_degraded(self) -> bool:
        return self in _DEGRADED_ASSESSMENTS


_DEGRADED_ASSESSMENTS = frozenset(
    {RateAssessment.DEFICIT, RateAssessment.EXCESS, RateAssessment.STALLED}
)


class EvidenceKind(str, Enum):
    """How we came to know an observation. A document is not on this list.

    ``P5_PROCUREMENT_BOM.md`` says the built-in LiDAR is an L1 and Unitree says
    it is an L2; the session exists partly to settle that. So a value read out of
    a repository document can never become an observation here — documents appear
    only as claims to be checked against a machine read or an operator's eyes.
    """

    #: This process read it off the device or the host.
    MACHINE_READ = "machine_read"
    #: A human read it off a label and typed it in, naming themselves and the
    #: photograph that backs it (``session/PHOTO_LIST.md``).
    OPERATOR_OBSERVED = "operator_observed"
    #: Computed from other observations by a stated rule.
    DERIVED = "derived"
    #: Not known. The fail-closed value.
    ABSENT = "absent"


class FindingSeverity(str, Enum):
    """How much a finding costs. Ordered worst-first by :attr:`rank`."""

    #: Proceeding is unsafe or dishonest. PS-F's DEGRADE-MMP branch or worse.
    BLOCKING = "blocking"
    #: The session can proceed but the dataset or the record is poorer for it.
    MAJOR = "major"
    #: Worth writing down; costs nothing today.
    NOTE = "note"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {
    FindingSeverity.BLOCKING: 0,
    FindingSeverity.MAJOR: 1,
    FindingSeverity.NOTE: 2,
}


def _require_int(value: object, *, field_name: str, allow_none: bool = False) -> int | None:
    """Integer or a refusal. Bools and floats are not integers.

    Same rule as ``capture/envelope.py``: a float clock is never rounded, because
    a rounded clock is a clock nobody can reconstruct six months later.
    """

    if value is None:
        if allow_none:
            return None
        raise ProbeContractError(f"{field_name} must be an int, got None")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProbeContractError(
            f"{field_name} must be an int, got {type(value).__name__} {value!r}"
        )
    if value < 0:
        raise ProbeContractError(f"{field_name} must be non-negative, got {value!r}")
    return value


# ---------------------------------------------------------------------------
# Physical plausibility — a channel is not healthy because bytes arrive
# ---------------------------------------------------------------------------


class PlausibilityVerdict(str, Enum):
    """Is what arrived physically possible? Three answers and no fourth.

    :attr:`UNKNOWN` is **not** a soft PASS and never decays into one. It is the
    answer whenever the rule exists but the evidence to evaluate it does not —
    no rest period was observed, no measurement was supplied, the window held
    too few samples. Board rule 3 applies to this layer exactly as it applies to
    presence: the permissive value is never the default.
    """

    #: Every rule that could be evaluated was evaluated, and all of them held.
    PASS = "pass"
    #: At least one rule was evaluated and the numbers are not physical.
    FAIL = "fail"
    #: We cannot judge. The fail-closed value.
    UNKNOWN = "unknown"

    @property
    def rank(self) -> int:
        """Worst-first, so an aggregate can be a ``min`` over its parts."""

        return _PLAUSIBILITY_RANK[self]


_PLAUSIBILITY_RANK = {
    PlausibilityVerdict.FAIL: 0,
    PlausibilityVerdict.UNKNOWN: 1,
    PlausibilityVerdict.PASS: 2,
}


class ChannelClass(str, Enum):
    """What kind of physical thing a channel carries, for rule selection.

    A channel may carry several: ``LowState`` is one message with an IMU, a
    battery and four foot-force counts inside it, and each gets its own rules.
    """

    IMU = "imu"
    POINT_CLOUD = "point_cloud"
    POWER = "power"
    FOOT_FORCE = "foot_force"
    CAMERA = "camera"


class ImuStreamKind(str, Enum):
    """Whether a stream carries a whole IMU or one half of one.

    ``pyrealsense2`` delivers the D455's BMI055 as two motion streams at two
    rates, so an accel-only stream missing a gyro vector is correct rather than
    defective — while a *full* IMU stream missing one is not, and is UNKNOWN.
    """

    FULL = "full"
    ACCEL_ONLY = "accel_only"
    GYRO_ONLY = "gyro_only"


#: Token that marks a Unitree ``LowState`` message type. Research item 6/7:
#: this one message carries the body IMU, ``power_v``/``power_a``, the BMS cell
#: array and both foot-force arrays, so it earns three rule sets.
_LOWSTATE_TYPE_TOKEN = "lowstate"
#: Token that marks a Unitree ``SportModeState`` message type. It carries an
#: ``imu_state`` and a ``foot_force[4]`` array, and ``ingest/dds.py``'s
#: ``decode_sport_mode_state`` emits an ``ImuSample`` and a ``FootForceSample``
#: for every message — which this function returned ``()`` for, so the dog's
#: only real clock anchor and its only non-LiDAR proximity channel had every
#: measurement it produced silently discarded by the plausibility layer. It gets
#: no POWER rules: ``SportModeState`` carries no ``power_v``/``BmsState``, and a
#: rule with no measurement behind it would park a CRITICAL channel at UNKNOWN
#: for the whole session.
_SPORTMODESTATE_TYPE_TOKEN = "sportmodestate"
#: Token that marks a point cloud message type, after lowercasing.
_POINT_CLOUD_TYPE_TOKEN = "pointcloud"
#: A message-type path segment starting with this is an IMU stream.
_IMU_SEGMENT_PREFIX = "imu"
_ACCEL_SEGMENT_PREFIX = "accel"
_GYRO_SEGMENT_PREFIX = "gyro"
#: Message-type prefixes that mark a decodable frame.
_IMAGE_TYPE_PREFIXES = ("image/", "video/")
#: ...and tokens that mark one anywhere in the type. Research item 1 corrected
#: the front camera to ``Go2FrontVideoData_`` (JPEG per frame on a DDS topic),
#: which carries no ``image/`` prefix — a prefix-only rule would have silently
#: dropped the dog's only wide-angle camera out of the plausibility layer.
_IMAGE_TYPE_TOKENS = ("video", "image")

_TYPE_SEGMENT = re.compile(r"[/.]+")


def _type_segments(entry: Channel) -> list[str]:
    return [seg for seg in _TYPE_SEGMENT.split(entry.message_type.strip().lower()) if seg]


def classify_channel(entry: Channel) -> tuple[ChannelClass, ...]:
    """Which rule sets apply, derived from the matrix's DECLARED message type.

    Derived, never listed. This module keeps no second enumeration of channels
    (``test_the_channel_enumeration_is_ps_a_s_and_this_card_keeps_no_second_list``)
    and it must keep none of channel *classes* either: PS-A's matrix is being
    rewritten in this same tranche to add eight missed channels, and a
    hand-maintained id list would silently stop covering them. So the class
    comes off ``message_type``, which is itself a declared expectation the
    session exists to falsify.

    An unrecognised type yields ``()``. Fail closed: no rules means the channel
    is UNKNOWN, never PASS.
    """

    text = entry.message_type.strip().lower()
    segments = _type_segments(entry)
    if _LOWSTATE_TYPE_TOKEN in text:
        return (ChannelClass.IMU, ChannelClass.POWER, ChannelClass.FOOT_FORCE)
    if _SPORTMODESTATE_TYPE_TOKEN in text:
        return (ChannelClass.IMU, ChannelClass.FOOT_FORCE)
    if any(seg.startswith(_IMU_SEGMENT_PREFIX) for seg in segments):
        return (ChannelClass.IMU,)
    if _POINT_CLOUD_TYPE_TOKEN in text:
        return (ChannelClass.POINT_CLOUD,)
    if text.startswith(_IMAGE_TYPE_PREFIXES) or any(
        token in text for token in _IMAGE_TYPE_TOKENS
    ):
        return (ChannelClass.CAMERA,)
    return ()


def imu_stream_kind(entry: Channel) -> ImuStreamKind:
    """FULL unless the declared type names one half of a split motion stream."""

    segments = _type_segments(entry)
    if any(seg.startswith(_ACCEL_SEGMENT_PREFIX) for seg in segments):
        return ImuStreamKind.ACCEL_ONLY
    if any(seg.startswith(_GYRO_SEGMENT_PREFIX) for seg in segments):
        return ImuStreamKind.GYRO_ONLY
    return ImuStreamKind.FULL


def imu_unit_id(entry: Channel, channels: Sequence[Channel] = CHANNELS) -> str:
    """Which physical IMU a stream comes off: ``<device>:<imu frame>``.

    There are FOUR independent IMUs on this rig — the dog's body IMU inside
    ``LowState``, the built-in LiDAR's, the add-on L2's, and the D455's BMI055 —
    and at rest they are a cross-check on each other. Grouping by
    ``(device, frame)`` is what makes that cross-check right rather than
    arithmetically convenient: the low-frequency ``lf/`` mirror is the *same*
    body IMU downsampled and must not be counted as a fifth witness, while the
    D455's accel and gyro streams are two halves of *one* unit and must be
    counted as one. Both fall out of the frame, and neither falls out of the
    channel id.

    ``SportModeState`` is the case where the channel's frame is **not** the
    IMU's. Its ``frame_id`` is ``odom`` because that is the frame of the pose it
    reports, but the ``imu_state`` inside it is the dog's body IMU — the same
    physical sensor ``LowState`` carries. Taking the row's frame verbatim would
    have minted a fifth "independent witness" out of the fourth one, and a
    cross-check that compares a sensor against itself agrees for the wrong
    reason. The body-IMU frame is looked up from the matrix's own ``LowState``
    rows on the same device rather than written down here, so it stays a
    consequence of PS-A's table; if the table ever stops naming exactly one such
    frame, the row's own frame is used and the extra unit shows up in the report
    rather than being papered over.
    """

    frame = entry.frame_id
    if _SPORTMODESTATE_TYPE_TOKEN in entry.message_type.strip().lower():
        body_frames = {
            other.frame_id
            for other in channels
            if other.device is entry.device
            and _LOWSTATE_TYPE_TOKEN in other.message_type.strip().lower()
        }
        if len(body_frames) == 1:
            frame = body_frames.pop()
    return f"{entry.device.value}:{frame}"


class PhysicalSample:
    """Base for the small typed summaries a reader may attach to a receipt.

    Still not the payload. A reader yields *what a physical quantity was*, in SI
    units where units exist, so this layer can rule on whether it is possible —
    it does not yield the message. Recording content remains PS-B's.

    Non-finite components are deliberately ACCEPTED by these constructors. A NaN
    accelerometer is a measurement of a broken sensor and the rules must be able
    to report it as FAIL; a constructor that refused it would convert a
    diagnosable channel into an unexplained absence.
    """

    __slots__ = ()


def _require_real(value: object, *, field_name: str) -> float:
    """A real number, NaN and inf included. Bools are not numbers."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProbeContractError(
            f"{field_name} must be a real number, got {type(value).__name__} {value!r}"
        )
    return float(value)


def _require_vec3(value: object, *, field_name: str) -> tuple[float, float, float]:
    if not isinstance(value, tuple) or len(value) != 3:
        raise ProbeContractError(
            f"{field_name} must be a 3-tuple of numbers (x, y, z), got {value!r}"
        )
    parts = tuple(
        _require_real(comp, field_name=f"{field_name}[{index}]")
        for index, comp in enumerate(value)
    )
    return (parts[0], parts[1], parts[2])


@dataclass(frozen=True, slots=True)
class ImuSample(PhysicalSample):
    """One IMU reading, in SI units, as the reader decoded it.

    Either vector may be ``None`` — that is how a split accel-only or gyro-only
    stream is expressed — but not both: a sample with neither is a reader that
    yielded nothing while claiming to have measured something.
    """

    accel_mps2: tuple[float, float, float] | None = None
    gyro_rps: tuple[float, float, float] | None = None

    def __post_init__(self) -> None:
        if self.accel_mps2 is None and self.gyro_rps is None:
            raise ProbeContractError(
                "an ImuSample must carry an accelerometer or a gyroscope vector"
            )
        if self.accel_mps2 is not None:
            object.__setattr__(
                self, "accel_mps2", _require_vec3(self.accel_mps2, field_name="accel_mps2")
            )
        if self.gyro_rps is not None:
            object.__setattr__(
                self, "gyro_rps", _require_vec3(self.gyro_rps, field_name="gyro_rps")
            )

    @property
    def accel_magnitude_mps2(self) -> float | None:
        """``math.hypot`` rather than ``sqrt(sum of squares)``: it does not
        overflow on the very large components this rule exists to catch."""

        return None if self.accel_mps2 is None else math.hypot(*self.accel_mps2)

    @property
    def gyro_magnitude_rps(self) -> float | None:
        return None if self.gyro_rps is None else math.hypot(*self.gyro_rps)


@dataclass(frozen=True, slots=True)
class PointCloudSample(PhysicalSample):
    """One cloud, summarised: how many points, what fields, what ranges.

    ``field_names`` is the ``PointCloud2.fields[]`` list VERBATIM and in wire
    order. An empty tuple means the message declared no fields, which is itself
    the finding — a reader that forgets to populate it produces a FAIL, and a
    false FAIL on a session morning is recoverable while a false PASS is not.

    ``ranges_m`` is a *sample* of per-point ranges, already reduced by the
    reader. Preflight does not hold a cloud.
    """

    point_count: int
    field_names: tuple[str, ...]
    nonfinite_points: int = 0
    ranges_m: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _require_int(self.point_count, field_name="point_count")
        _require_int(self.nonfinite_points, field_name="nonfinite_points")
        if not isinstance(self.field_names, tuple) or any(
            not isinstance(name, str) or not name.strip() for name in self.field_names
        ):
            raise ProbeContractError(
                f"field_names must be a tuple of non-empty PointCloud2 field names, "
                f"got {self.field_names!r}"
            )
        if not isinstance(self.ranges_m, tuple):
            raise ProbeContractError(f"ranges_m must be a tuple, got {self.ranges_m!r}")
        object.__setattr__(
            self,
            "ranges_m",
            tuple(
                _require_real(value, field_name=f"ranges_m[{index}]")
                for index, value in enumerate(self.ranges_m)
            ),
        )


@dataclass(frozen=True, slots=True)
class PowerSample(PhysicalSample):
    """Pack voltage and the cell array behind it, volts.

    Research item 6: ``BmsState`` carries **no** voltage field. Pack voltage is
    either ``sum(cell_vol[15])`` or ``LowState.power_v``, which is exactly why
    both are recorded here and checked against each other.

    Units are VOLTS. A driver that reports millivolts must be converted by the
    adapter; this layer refuses to guess units and the per-cell bound catches
    the mistake rather than silently scaling it away.
    """

    power_v: float
    cell_volts: tuple[float, ...] = ()
    power_a: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "power_v", _require_real(self.power_v, field_name="power_v"))
        if not isinstance(self.cell_volts, tuple):
            raise ProbeContractError(f"cell_volts must be a tuple, got {self.cell_volts!r}")
        object.__setattr__(
            self,
            "cell_volts",
            tuple(
                _require_real(value, field_name=f"cell_volts[{index}]")
                for index, value in enumerate(self.cell_volts)
            ),
        )
        if self.power_a is not None:
            object.__setattr__(
                self, "power_a", _require_real(self.power_a, field_name="power_a")
            )

    @property
    def cell_sum_v(self) -> float | None:
        return None if not self.cell_volts else math.fsum(self.cell_volts)


@dataclass(frozen=True, slots=True)
class FootForceSample(PhysicalSample):
    """The four foot-force counts, and the estimator's four, as RAW int16.

    Research item 7, CONFIRMED: these are ``int16`` raw counts from an
    air-pressure contact proxy with **no published units, gain or offset**. So
    no rule in this module asserts an absolute value for them — the only
    assertions available are that there are four of them, that they fit their
    container, and that they move.

    ``counts_est`` is ``foot_force_est[4]``, recorded because the difference
    between the two arrays is free evidence about which one is sensed.
    """

    counts: tuple[int, ...]
    counts_est: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        for name in ("counts", "counts_est"):
            values = getattr(self, name)
            if values is None:
                continue
            if not isinstance(values, tuple):
                raise ProbeContractError(f"{name} must be a tuple, got {values!r}")
            for index, value in enumerate(values):
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ProbeContractError(
                        f"{name}[{index}] must be an int raw count, got "
                        f"{type(value).__name__} {value!r}"
                    )


@dataclass(frozen=True, slots=True)
class ImageSample(PhysicalSample):
    """One frame, summarised by the reader. Never the pixels.

    ``zero_fraction`` and ``saturated_fraction`` are the reader's own count of
    pixels at the bottom and top of the frame's representable range, so the same
    rule serves an 8-bit colour frame and a 16-bit depth frame without this
    module knowing either one's bit depth.
    """

    width: int
    height: int
    decoded: bool
    min_level: float
    max_level: float
    mean_level: float
    zero_fraction: float
    saturated_fraction: float

    def __post_init__(self) -> None:
        _require_int(self.width, field_name="width")
        _require_int(self.height, field_name="height")
        if not isinstance(self.decoded, bool):
            raise ProbeContractError(f"decoded must be a bool, got {self.decoded!r}")
        for name in ("min_level", "max_level", "mean_level"):
            object.__setattr__(self, name, _require_real(getattr(self, name), field_name=name))
        for name in ("zero_fraction", "saturated_fraction"):
            value = _require_real(getattr(self, name), field_name=name)
            if not 0.0 <= value <= 1.0:
                raise ProbeContractError(f"{name} must be within [0, 1], got {value!r}")
            object.__setattr__(self, name, value)

    @property
    def is_degenerate(self) -> bool:
        """All-black, all-saturated, or one flat level across the whole frame."""

        return (
            self.zero_fraction >= IMAGE_DEGENERATE_FRACTION
            or self.saturated_fraction >= IMAGE_DEGENERATE_FRACTION
            or self.max_level == self.min_level
        )


#: Which sample type carries which class's evidence.
_CLASS_SAMPLE_TYPE: Mapping[ChannelClass, type] = {
    ChannelClass.IMU: ImuSample,
    ChannelClass.POINT_CLOUD: PointCloudSample,
    ChannelClass.POWER: PowerSample,
    ChannelClass.FOOT_FORCE: FootForceSample,
    ChannelClass.CAMERA: ImageSample,
}


@dataclass(frozen=True, slots=True)
class RestPeriod:
    """An operator's attestation that the rig was stationary for the window.

    "At rest" cannot be read off a wire — it is a claim about the room, so it is
    an operator observation with a name attached, exactly like the LiDAR label
    reading. Absent this, the rest-dependent rules are UNKNOWN and stay UNKNOWN;
    there is no code path that infers rest from the data it is about to judge.
    """

    attested_by: str
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.attested_by, str) or not self.attested_by.strip():
            raise ProbeContractError(
                "a rest period must name the operator attesting the rig was stationary"
            )

    @property
    def evidence(self) -> str:
        text = f"operator {self.attested_by.strip()} attests the rig was at rest"
        return f"{text} ({self.note.strip()})" if self.note.strip() else text


@dataclass(frozen=True, slots=True)
class PlausibilityCheck:
    """One rule, its verdict, and the numbers it ruled on."""

    rule: str
    verdict: PlausibilityVerdict
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.verdict, PlausibilityVerdict):
            raise ProbeContractError(
                f"{self.rule}: verdict must be a PlausibilityVerdict, got {self.verdict!r}"
            )
        if not self.rule.strip() or not self.detail.strip():
            raise ProbeContractError("a plausibility check must carry a rule id and a detail")

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "verdict": self.verdict.value, "detail": self.detail}

    @classmethod
    def from_mapping(cls, record: Mapping[str, Any]) -> PlausibilityCheck:
        if not isinstance(record, Mapping):
            raise ProbeContractError(
                f"a plausibility check record must be a mapping, got {type(record).__name__}"
            )
        try:
            return cls(
                rule=str(record["rule"]),
                verdict=PlausibilityVerdict(record["verdict"]),
                detail=str(record["detail"]),
            )
        except KeyError as exc:
            raise ProbeContractError(f"plausibility check record is missing {exc}") from exc


@dataclass(frozen=True, slots=True)
class ChannelPlausibility:
    """Every rule run against one channel, and what they add up to.

    :attr:`verdict` is a **property**. As with :attr:`ChannelProbe.status`, there
    is no constructor argument that names PASS: a pass is a consequence of every
    evaluated rule holding and at least one having been evaluable.
    """

    channel_id: str
    #: :class:`ChannelClass` values whose rules were selected for this channel.
    classes: tuple[str, ...] = ()
    #: How many physical samples the rules actually ruled on.
    samples_assessed: int = 0
    checks: tuple[PlausibilityCheck, ...] = ()
    #: Evidence that carries no verdict — the fields[] dump, the foot-force
    #: estimator delta. Printed, never scored.
    notes: tuple[str, ...] = ()
    #: ``PointCloud2.fields[]`` verbatim, in wire order. The single most
    #: session-critical thing on this card that is unrecoverable after powerdown.
    point_cloud_fields: tuple[str, ...] = ()
    #: Which physical IMU this stream belongs to, for the four-unit cross-check.
    imu_unit_id: str | None = None
    #: Mean ``|accel|`` over the window, m/s^2 — the cross-check's input. ``None``
    #: when no accel was measured OR when the mean is not finite (a non-finite
    #: statistic would make the attestation unserialisable; the check detail
    #: still says so in words).
    accel_magnitude_mean_mps2: float | None = None
    #: Largest ``|gyro|`` over the window, rad/s. Same finiteness rule.
    gyro_magnitude_max_rps: float | None = None

    def __post_init__(self) -> None:
        _require_int(self.samples_assessed, field_name="samples_assessed")
        for name in ("accel_magnitude_mean_mps2", "gyro_magnitude_max_rps"):
            value = getattr(self, name)
            if value is None:
                continue
            number = _require_real(value, field_name=name)
            if not math.isfinite(number):
                raise ProbeContractError(
                    f"{self.channel_id}: {name} must be finite or None — a non-finite "
                    f"statistic is reported in the check detail, never stored as a number"
                )
            object.__setattr__(self, name, number)

    @property
    def verdict(self) -> PlausibilityVerdict:
        """Worst wins, and no checks at all is UNKNOWN rather than PASS."""

        if not self.checks:
            return PlausibilityVerdict.UNKNOWN
        return min((check.verdict for check in self.checks), key=lambda v: v.rank)

    @property
    def failed_rules(self) -> tuple[str, ...]:
        return tuple(
            check.rule for check in self.checks if check.verdict is PlausibilityVerdict.FAIL
        )

    @property
    def unknown_rules(self) -> tuple[str, ...]:
        return tuple(
            check.rule for check in self.checks if check.verdict is PlausibilityVerdict.UNKNOWN
        )

    def check(self, rule: str) -> PlausibilityCheck | None:
        for item in self.checks:
            if item.rule == rule:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "verdict": self.verdict.value,
            "classes": list(self.classes),
            "samples_assessed": self.samples_assessed,
            "checks": [check.to_dict() for check in self.checks],
            "notes": list(self.notes),
            "point_cloud_fields": list(self.point_cloud_fields),
            "imu_unit_id": self.imu_unit_id,
            "accel_magnitude_mean_mps2": self.accel_magnitude_mean_mps2,
            "gyro_magnitude_max_rps": self.gyro_magnitude_max_rps,
        }

    @classmethod
    def from_mapping(cls, record: Mapping[str, Any]) -> ChannelPlausibility:
        """Decode, DISCARDING ``verdict`` and recomputing it from the checks."""

        if not isinstance(record, Mapping):
            raise ProbeContractError(
                f"a plausibility record must be a mapping, got {type(record).__name__}"
            )
        try:
            return cls(
                channel_id=str(record["channel_id"]),
                classes=tuple(str(item) for item in record["classes"]),
                samples_assessed=record["samples_assessed"],
                checks=tuple(
                    PlausibilityCheck.from_mapping(item) for item in record["checks"]
                ),
                notes=tuple(str(item) for item in record["notes"]),
                point_cloud_fields=tuple(str(item) for item in record["point_cloud_fields"]),
                imu_unit_id=(
                    None if record["imu_unit_id"] is None else str(record["imu_unit_id"])
                ),
                accel_magnitude_mean_mps2=record["accel_magnitude_mean_mps2"],
                gyro_magnitude_max_rps=record["gyro_magnitude_max_rps"],
            )
        except KeyError as exc:
            raise ProbeContractError(f"plausibility record is missing {exc}") from exc


def _unjudgeable(channel_id: str, rule: str, detail: str) -> ChannelPlausibility:
    return ChannelPlausibility(
        channel_id=channel_id,
        checks=(PlausibilityCheck(rule, PlausibilityVerdict.UNKNOWN, detail),),
    )


@dataclass(frozen=True, slots=True)
class SampleReceipt:
    """Metadata for one message that actually arrived.

    Deliberately not the payload: preflight proves arrival, PS-B records content.
    ``payload_bytes`` must be positive — a zero-byte message is not a message,
    and a transport that reports one is reporting its own failure.

    ``measurements`` is the PS-J addition: zero or more :class:`PhysicalSample`
    summaries the reader extracted while the message was in its hands. Empty is
    the honest default and produces UNKNOWN, never PASS — a build whose readers
    supply no physical summary has not proved any channel plausible.
    """

    channel_id: str
    host_monotonic_ns: int
    payload_bytes: int
    source_timestamp_ns: int | None = None
    detail: str = ""
    measurements: tuple[PhysicalSample, ...] = ()

    def __post_init__(self) -> None:
        _require_int(self.host_monotonic_ns, field_name="host_monotonic_ns")
        _require_int(self.source_timestamp_ns, field_name="source_timestamp_ns", allow_none=True)
        _require_int(self.payload_bytes, field_name="payload_bytes")
        if not isinstance(self.measurements, tuple) or any(
            not isinstance(item, PhysicalSample) for item in self.measurements
        ):
            raise ProbeContractError(
                f"{self.channel_id}: measurements must be a tuple of PhysicalSample, got "
                f"{self.measurements!r}"
            )
        if self.payload_bytes <= 0:
            raise ProbeContractError(
                f"{self.channel_id}: payload_bytes must be positive, got "
                f"{self.payload_bytes!r} — a zero-byte message is not a message"
            )
        if not isinstance(self.channel_id, str) or not self.channel_id.strip():
            raise ProbeContractError(f"receipt channel_id must be a non-empty string, got {self.channel_id!r}")


def _percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile. No interpolation, no dependency."""

    ordered = sorted(values)
    index = round(fraction * (len(ordered) - 1))
    return ordered[min(len(ordered) - 1, max(0, index))]


def _assess_imu(
    entry: Channel, samples: Sequence[ImuSample], rest: RestPeriod | None
) -> tuple[list[PlausibilityCheck], float | None, float | None]:
    """The four-IMU rules. Two of them do not need a rest period, and that is
    the point: the ~-2.17e24 m/s^2 report is a *sensor-range* violation, so it
    is caught in any take, not only in a declared rest take."""

    kind = imu_stream_kind(entry)
    checks: list[PlausibilityCheck] = []
    accel_mean: float | None = None
    gyro_max: float | None = None

    if kind is not ImuStreamKind.GYRO_ONLY:
        vectors = [sample.accel_mps2 for sample in samples if sample.accel_mps2 is not None]
        if not vectors:
            checks.append(
                PlausibilityCheck(
                    "imu.accel_present",
                    PlausibilityVerdict.UNKNOWN,
                    f"declared stream kind {kind.value} should carry an accelerometer, but "
                    f"no accel vector appeared in any of {len(samples)} sample(s); no "
                    f"accelerometer rule could be evaluated",
                )
            )
        else:
            checks.extend(_assess_vector_rules(
                vectors,
                prefix="imu.accel",
                unit="m/s^2",
                sensor_ceiling=ACCEL_SENSOR_CEILING_MPS2,
                sensor_basis="BMI055-class full scale is +/-16 g = 156.9 m/s^2",
            ))
            magnitudes = [math.hypot(*vector) for vector in vectors]
            finite = [value for value in magnitudes if math.isfinite(value)]
            mean = math.fsum(finite) / len(finite) if finite else None
            accel_mean = mean if mean is not None and math.isfinite(mean) else None
            checks.append(_assess_accel_at_rest(magnitudes, finite, mean, rest))

    if kind is not ImuStreamKind.ACCEL_ONLY:
        vectors = [sample.gyro_rps for sample in samples if sample.gyro_rps is not None]
        if not vectors:
            checks.append(
                PlausibilityCheck(
                    "imu.gyro_present",
                    PlausibilityVerdict.UNKNOWN,
                    f"declared stream kind {kind.value} should carry a gyroscope, but no "
                    f"gyro vector appeared in any of {len(samples)} sample(s); no "
                    f"gyroscope rule could be evaluated",
                )
            )
        else:
            checks.extend(_assess_vector_rules(
                vectors,
                prefix="imu.gyro",
                unit="rad/s",
                sensor_ceiling=GYRO_SENSOR_CEILING_RPS,
                sensor_basis="+/-2000 deg/s full scale is 34.9 rad/s",
            ))
            magnitudes = [math.hypot(*vector) for vector in vectors]
            finite = [value for value in magnitudes if math.isfinite(value)]
            worst = max(finite) if finite else None
            gyro_max = worst if worst is not None and math.isfinite(worst) else None
            checks.append(_assess_gyro_at_rest(magnitudes, finite, worst, rest))

    return checks, accel_mean, gyro_max


def _assess_vector_rules(
    vectors: Sequence[tuple[float, float, float]],
    *,
    prefix: str,
    unit: str,
    sensor_ceiling: float,
    sensor_basis: str,
) -> list[PlausibilityCheck]:
    """Finiteness and full-scale, the two rest-independent rules."""

    components = [component for vector in vectors for component in vector]
    nonfinite = [value for value in components if not math.isfinite(value)]
    finite = [value for value in components if math.isfinite(value)]
    checks = [
        PlausibilityCheck(
            f"{prefix}_finite",
            PlausibilityVerdict.FAIL if nonfinite else PlausibilityVerdict.PASS,
            (
                f"{len(nonfinite)} of {len(components)} components are not finite "
                f"(first {nonfinite[0]!r}) — a NaN/inf axis is a broken decode, not a "
                f"measurement"
                if nonfinite
                else f"all {len(components)} components over {len(vectors)} sample(s) are finite"
            ),
        )
    ]
    if not finite:
        checks.append(
            PlausibilityCheck(
                f"{prefix}_within_sensor_range",
                PlausibilityVerdict.UNKNOWN,
                f"no finite component to compare against the {sensor_ceiling} {unit} "
                f"full-scale bound",
            )
        )
        return checks
    worst = max(finite, key=abs)
    checks.append(
        PlausibilityCheck(
            f"{prefix}_within_sensor_range",
            PlausibilityVerdict.FAIL
            if abs(worst) > sensor_ceiling
            else PlausibilityVerdict.PASS,
            (
                f"largest component {worst!r} {unit} exceeds the {sensor_ceiling} {unit} "
                f"bound ({sensor_basis}); nothing physical reads this, so the channel is "
                f"emitting garbage — record it, do not trust it"
                if abs(worst) > sensor_ceiling
                else f"largest component {abs(worst):.4g} {unit} is within the "
                f"{sensor_ceiling} {unit} bound ({sensor_basis})"
            ),
        )
    )
    return checks


def _assess_accel_at_rest(
    magnitudes: Sequence[float],
    finite: Sequence[float],
    mean: float | None,
    rest: RestPeriod | None,
) -> PlausibilityCheck:
    rule = "imu.accel_magnitude_at_rest"
    if rest is None:
        return PlausibilityCheck(
            rule,
            PlausibilityVerdict.UNKNOWN,
            f"no rest period was observed or declared (--at-rest OPERATOR), and the "
            f"{GRAVITY_MPS2} +/- {ACCEL_REST_TOLERANCE_MPS2} m/s^2 band only means "
            f"anything at rest; UNKNOWN, never PASS",
        )
    if not finite or mean is None or not math.isfinite(mean):
        return PlausibilityCheck(
            rule,
            PlausibilityVerdict.UNKNOWN,
            f"{rest.evidence}, but {len(magnitudes) - len(finite)} of "
            f"{len(magnitudes)} magnitudes are not finite so no mean can be formed",
        )
    deviation = abs(mean - GRAVITY_MPS2)
    detail = (
        f"{rest.evidence}; mean |accel| {mean:.6g} m/s^2 over {len(finite)} sample(s) "
        f"(min {min(finite):.6g}, max {max(finite):.6g}), deviation {deviation:.6g} from "
        f"{GRAVITY_MPS2} against a +/-{ACCEL_REST_TOLERANCE_MPS2} band"
    )
    return PlausibilityCheck(
        rule,
        PlausibilityVerdict.FAIL
        if deviation > ACCEL_REST_TOLERANCE_MPS2
        else PlausibilityVerdict.PASS,
        detail,
    )


def _assess_gyro_at_rest(
    magnitudes: Sequence[float],
    finite: Sequence[float],
    worst: float | None,
    rest: RestPeriod | None,
) -> PlausibilityCheck:
    rule = "imu.gyro_magnitude_at_rest"
    if rest is None:
        return PlausibilityCheck(
            rule,
            PlausibilityVerdict.UNKNOWN,
            f"no rest period was observed or declared (--at-rest OPERATOR), and the "
            f"|gyro| < {GYRO_REST_CEILING_RPS} rad/s ceiling only means anything at "
            f"rest; UNKNOWN, never PASS",
        )
    if not finite or worst is None or not math.isfinite(worst):
        return PlausibilityCheck(
            rule,
            PlausibilityVerdict.UNKNOWN,
            f"{rest.evidence}, but {len(magnitudes) - len(finite)} of "
            f"{len(magnitudes)} magnitudes are not finite so no maximum can be formed",
        )
    return PlausibilityCheck(
        rule,
        PlausibilityVerdict.FAIL if worst >= GYRO_REST_CEILING_RPS else PlausibilityVerdict.PASS,
        f"{rest.evidence}; largest |gyro| {worst:.6g} rad/s over {len(finite)} sample(s) "
        f"against a {GYRO_REST_CEILING_RPS} rad/s at-rest ceiling",
    )


def _assess_point_cloud(
    samples: Sequence[PointCloudSample],
) -> tuple[list[PlausibilityCheck], list[str], tuple[str, ...]]:
    """Point count, finiteness, range distribution — and the fields[] dump.

    The fields[] list is the one thing on this card that cannot be recovered
    after powerdown: if there is no per-point time field, no LIO package can
    deskew the cloud, and we would learn that weeks later with the dog packed
    away. So it is dumped verbatim, in wire order, into the notes and into the
    attestation.
    """

    checks: list[PlausibilityCheck] = []
    notes: list[str] = []
    fields = samples[0].field_names
    layouts = {sample.field_names for sample in samples}

    counts = [sample.point_count for sample in samples]
    empty = [count for count in counts if count <= 0]
    checks.append(
        PlausibilityCheck(
            "point_cloud.point_count",
            PlausibilityVerdict.FAIL if empty else PlausibilityVerdict.PASS,
            (
                f"{len(empty)} of {len(counts)} cloud(s) carry no points — a cloud with "
                f"zero points is a publishing sensor with nothing to say"
                if empty
                else f"{len(counts)} cloud(s), {min(counts)}-{max(counts)} points each"
            ),
        )
    )

    nonfinite = sum(sample.nonfinite_points for sample in samples)
    total = sum(counts)
    checks.append(
        PlausibilityCheck(
            "point_cloud.coordinates_finite",
            PlausibilityVerdict.FAIL if nonfinite else PlausibilityVerdict.PASS,
            (
                f"{nonfinite} of {total} point(s) carry a non-finite coordinate"
                if nonfinite
                else f"all {total} point(s) carry finite coordinates"
            ),
        )
    )

    ranges = [value for sample in samples for value in sample.ranges_m]
    if not ranges:
        checks.append(
            PlausibilityCheck(
                "point_cloud.range_distribution",
                PlausibilityVerdict.UNKNOWN,
                f"the reader sampled no per-point ranges from {len(samples)} cloud(s), so "
                f"the distribution cannot be judged",
            )
        )
    else:
        finite = [value for value in ranges if math.isfinite(value)]
        problems: list[str] = []
        if len(finite) != len(ranges):
            problems.append(f"{len(ranges) - len(finite)} of {len(ranges)} ranges non-finite")
        if not finite:
            problems.append("no finite range at all")
        else:
            low, high = min(finite), max(finite)
            if low < 0.0:
                problems.append(f"minimum range {low:.6g} m is negative")
            if high > POINT_RANGE_CEILING_M:
                problems.append(
                    f"maximum range {high!r} m exceeds the {POINT_RANGE_CEILING_M} m bound "
                    f"(a unit-scale error reports mm as m)"
                )
            if low == high:
                problems.append(
                    f"every sampled range is exactly {low:.6g} m — a degenerate cloud, not a scene"
                )
        detail = (
            "; ".join(problems)
            if problems
            else (
                f"{len(finite)} sampled range(s): p05 {_percentile(finite, 0.05):.3f} m, "
                f"p50 {_percentile(finite, 0.50):.3f} m, p95 {_percentile(finite, 0.95):.3f} m"
            )
        )
        checks.append(
            PlausibilityCheck(
                "point_cloud.range_distribution",
                PlausibilityVerdict.FAIL if problems else PlausibilityVerdict.PASS,
                detail,
            )
        )

    notes.append(
        "PointCloud2 fields[] (verbatim, wire order): "
        + (", ".join(fields) if fields else "(the message declared NO fields)")
    )
    checks.append(
        PlausibilityCheck(
            "point_cloud.field_layout_stable",
            PlausibilityVerdict.FAIL if len(layouts) > 1 else PlausibilityVerdict.PASS,
            (
                f"the fields[] layout changed inside the window: {sorted(layouts)}"
                if len(layouts) > 1
                else f"one stable fields[] layout across {len(samples)} cloud(s)"
            ),
        )
    )
    lowered = {name.strip().lower() for name in fields}
    has_time = bool(lowered & DESKEW_TIME_FIELD_NAMES)
    has_ring = bool(lowered & DESKEW_RING_FIELD_NAMES)
    checks.append(
        PlausibilityCheck(
            "point_cloud.per_point_time_field",
            PlausibilityVerdict.PASS if has_time else PlausibilityVerdict.FAIL,
            (
                f"per-point time field present in fields[] = {list(fields)}"
                if has_time
                else f"NO per-point time field in fields[] = {list(fields)}; none of "
                f"{sorted(DESKEW_TIME_FIELD_NAMES)} is present, so GLIM / FAST-LIO2 / "
                f"Point-LIO / KISS-ICP cannot motion-compensate this cloud. This is "
                f"discoverable ONLY while the rig is powered."
            ),
        )
    )
    checks.append(
        PlausibilityCheck(
            "point_cloud.ring_field",
            PlausibilityVerdict.PASS if has_ring else PlausibilityVerdict.FAIL,
            (
                f"ring/line field present in fields[] = {list(fields)}"
                if has_ring
                else f"NO ring/line field in fields[] = {list(fields)}; none of "
                f"{sorted(DESKEW_RING_FIELD_NAMES)} is present, so ring-indexed packages "
                f"(LIO-SAM class) cannot use this cloud"
                + (
                    " — time-based deskew is still available"
                    if has_time
                    else " and no time field is present either"
                )
            ),
        )
    )
    return checks, notes, fields


def _assess_power(samples: Sequence[PowerSample]) -> list[PlausibilityCheck]:
    """``power_v`` sane, cells sane, and the two consistent with each other."""

    checks: list[PlausibilityCheck] = []
    volts = [sample.power_v for sample in samples]
    bad = [
        value
        for value in volts
        if not math.isfinite(value) or value <= 0.0 or value > PACK_VOLTAGE_CEILING_V
    ]
    checks.append(
        PlausibilityCheck(
            "power.pack_voltage_range",
            PlausibilityVerdict.FAIL if bad else PlausibilityVerdict.PASS,
            (
                f"{len(bad)} of {len(volts)} power_v reading(s) are not a pack voltage "
                f"(first {bad[0]!r} V, bound 0 < V <= {PACK_VOLTAGE_CEILING_V})"
                if bad
                else f"power_v {min(volts):.3f}-{max(volts):.3f} V over {len(volts)} "
                f"sample(s), within 0 < V <= {PACK_VOLTAGE_CEILING_V}"
            ),
        )
    )

    with_cells = [sample for sample in samples if sample.cell_volts]
    if not with_cells:
        for rule in ("power.cell_voltage_range", "power.cell_sum_consistent"):
            checks.append(
                PlausibilityCheck(
                    rule,
                    PlausibilityVerdict.UNKNOWN,
                    f"no cell_vol array in any of {len(samples)} sample(s); BmsState "
                    f"carries no voltage field, so without the cell array there is "
                    f"nothing to cross-check power_v against",
                )
            )
        return checks

    cells = [value for sample in with_cells for value in sample.cell_volts]
    out_of_band = [
        value
        for value in cells
        if not math.isfinite(value)
        or not CELL_VOLTAGE_MIN_V <= value <= CELL_VOLTAGE_MAX_V
    ]
    checks.append(
        PlausibilityCheck(
            "power.cell_voltage_range",
            PlausibilityVerdict.FAIL if out_of_band else PlausibilityVerdict.PASS,
            (
                f"{len(out_of_band)} of {len(cells)} cell voltage(s) outside "
                f"[{CELL_VOLTAGE_MIN_V}, {CELL_VOLTAGE_MAX_V}] V (first {out_of_band[0]!r}) "
                f"— if the driver reports millivolts the ADAPTER must convert; this layer "
                f"refuses to guess units"
                if out_of_band
                else f"{len(cells)} cell voltage(s) within "
                f"[{CELL_VOLTAGE_MIN_V}, {CELL_VOLTAGE_MAX_V}] V"
            ),
        )
    )

    worst_delta = 0.0
    worst_detail = ""
    inconsistent = False
    judged = 0
    for sample in with_cells:
        total = sample.cell_sum_v
        if total is None or not math.isfinite(total) or not math.isfinite(sample.power_v):
            continue
        judged += 1
        delta = abs(total - sample.power_v)
        tolerance = max(
            PACK_CONSISTENCY_TOLERANCE_V, PACK_CONSISTENCY_TOLERANCE_FRACTION * abs(total)
        )
        if delta > tolerance:
            inconsistent = True
        if delta >= worst_delta:
            worst_delta = delta
            worst_detail = (
                f"sum(cell_vol[{len(sample.cell_volts)}]) = {total:.3f} V vs power_v = "
                f"{sample.power_v:.3f} V, |delta| {delta:.3f} V against a "
                f"{tolerance:.3f} V tolerance"
            )
    if not judged:
        checks.append(
            PlausibilityCheck(
                "power.cell_sum_consistent",
                PlausibilityVerdict.UNKNOWN,
                "no sample carries both a finite cell sum and a finite power_v",
            )
        )
    else:
        checks.append(
            PlausibilityCheck(
                "power.cell_sum_consistent",
                PlausibilityVerdict.FAIL if inconsistent else PlausibilityVerdict.PASS,
                (f"INCONSISTENT: {worst_detail}" if inconsistent else f"worst case {worst_detail}")
                + f" ({judged} sample(s) judged)",
            )
        )
    return checks


def _assess_foot_force(
    samples: Sequence[FootForceSample],
) -> tuple[list[PlausibilityCheck], list[str]]:
    """Four channels, an int16 container, and movement. Nothing absolute.

    Deliberately asserts no force. Research item 7: the counts have no published
    units, gain or offset, so an absolute assertion here would be a number we
    invented — and inventing one is how a plausibility layer starts lying.
    """

    checks: list[PlausibilityCheck] = []
    notes: list[str] = []
    widths = {len(sample.counts) for sample in samples}
    checks.append(
        PlausibilityCheck(
            "foot_force.four_channels",
            PlausibilityVerdict.PASS
            if widths == {FOOT_FORCE_CHANNELS}
            else PlausibilityVerdict.FAIL,
            (
                f"all {len(samples)} sample(s) carry {FOOT_FORCE_CHANNELS} foot-force counts"
                if widths == {FOOT_FORCE_CHANNELS}
                else f"foot-force array width(s) {sorted(widths)}, expected "
                f"{FOOT_FORCE_CHANNELS} (a quadruped has four feet)"
            ),
        )
    )
    counts = [value for sample in samples for value in sample.counts]
    outside = [
        value for value in counts if not FOOT_FORCE_COUNT_MIN <= value <= FOOT_FORCE_COUNT_MAX
    ]
    checks.append(
        PlausibilityCheck(
            "foot_force.int16_container",
            PlausibilityVerdict.FAIL if outside else PlausibilityVerdict.PASS,
            (
                f"{len(outside)} count(s) outside int16 [{FOOT_FORCE_COUNT_MIN}, "
                f"{FOOT_FORCE_COUNT_MAX}] (first {outside[0]!r}) — a container check, "
                f"not a force claim; the decode is wrong"
                if outside
                else f"{len(counts)} count(s) fit int16 [{FOOT_FORCE_COUNT_MIN}, "
                f"{FOOT_FORCE_COUNT_MAX}]; NO units, gain or offset are published for "
                f"them, so no absolute value is asserted"
            ),
        )
    )

    width = min(widths, default=0)
    if len(samples) < FOOT_FORCE_MIN_SAMPLES or width <= 0:
        checks.append(
            PlausibilityCheck(
                "foot_force.varies",
                PlausibilityVerdict.UNKNOWN,
                f"{len(samples)} sample(s) is below the {FOOT_FORCE_MIN_SAMPLES} needed to "
                f"tell a stuck sensor from a slow one",
            )
        )
    else:
        distinct = [
            {sample.counts[index] for sample in samples} for index in range(width)
        ]
        stuck = [index for index, values in enumerate(distinct) if len(values) <= 1]
        checks.append(
            PlausibilityCheck(
                "foot_force.varies",
                PlausibilityVerdict.FAIL if stuck else PlausibilityVerdict.PASS,
                (
                    f"foot(feet) {stuck} report a single unchanging count across "
                    f"{len(samples)} sample(s) — stuck, not quiet"
                    if stuck
                    else f"all {width} feet vary across {len(samples)} sample(s): "
                    f"{[len(values) for values in distinct]} distinct value(s) each"
                ),
            )
        )

    with_est = [
        sample
        for sample in samples
        if sample.counts_est is not None and len(sample.counts_est) == len(sample.counts)
    ]
    if with_est:
        deltas = [
            abs(raw - est)
            for sample in with_est
            for raw, est in zip(sample.counts, sample.counts_est or ())
        ]
        notes.append(
            f"foot_force vs foot_force_est over {len(with_est)} sample(s): mean |delta| "
            f"{math.fsum(deltas) / len(deltas):.1f} counts, max {max(deltas)} — recorded as "
            f"free evidence about which array is sensed, asserted as nothing"
        )
    else:
        notes.append(
            "foot_force_est[4] was not supplied; the raw-vs-estimated difference "
            "(research item 7) is unavailable for this take"
        )
    return checks, notes


def _assess_camera(samples: Sequence[ImageSample]) -> list[PlausibilityCheck]:
    """It decoded, and it is not a lens cap."""

    broken = [
        sample
        for sample in samples
        if not sample.decoded
        or sample.width <= 0
        or sample.height <= 0
        or not math.isfinite(sample.min_level)
        or not math.isfinite(sample.max_level)
        or not math.isfinite(sample.mean_level)
    ]
    checks = [
        PlausibilityCheck(
            "camera.frame_decodes",
            PlausibilityVerdict.FAIL if broken else PlausibilityVerdict.PASS,
            (
                f"{len(broken)} of {len(samples)} frame(s) did not decode into a "
                f"judgeable image (first {broken[0].width}x{broken[0].height}, "
                f"decoded={broken[0].decoded})"
                if broken
                else f"{len(samples)} frame(s) decoded, "
                f"{samples[0].width}x{samples[0].height}"
            ),
        )
    ]
    degenerate = [sample for sample in samples if sample.is_degenerate]
    checks.append(
        PlausibilityCheck(
            "camera.non_degenerate",
            PlausibilityVerdict.FAIL if degenerate else PlausibilityVerdict.PASS,
            (
                f"{len(degenerate)} of {len(samples)} frame(s) are degenerate — first has "
                f"zero_fraction {degenerate[0].zero_fraction:.4f}, saturated_fraction "
                f"{degenerate[0].saturated_fraction:.4f}, levels "
                f"{degenerate[0].min_level:.6g}..{degenerate[0].max_level:.6g}. A lens cap, "
                f"a dead exposure, or a depth frame with no returns still delivers bytes"
                if degenerate
                else f"{len(samples)} frame(s) non-degenerate (worst zero_fraction "
                f"{max(s.zero_fraction for s in samples):.4f}, worst saturated_fraction "
                f"{max(s.saturated_fraction for s in samples):.4f})"
            ),
        )
    )
    return checks


def assess_plausibility(
    entry: Channel,
    receipts: Sequence[SampleReceipt],
    *,
    rest: RestPeriod | None = None,
) -> ChannelPlausibility:
    """Rule on whether what arrived on this channel is physically possible.

    Never raises for a data reason and never changes :class:`ProbeStatus`. A
    channel that fails here is still PRESENT, still recorded, and still carries a
    ``PHYSICAL`` origin — the card is explicit that a suspect channel is evidence
    and that a failed plausibility check must never silence a recording. What
    changes is that the attestation now says so.
    """

    classes = classify_channel(entry)
    if not classes:
        return _unjudgeable(
            entry.channel_id,
            "channel.no_rule_defined",
            f"no physical-plausibility rule exists for declared message type "
            f"{entry.message_type!r}; nothing here is asserted about this channel",
        )

    checks: list[PlausibilityCheck] = []
    notes: list[str] = []
    fields: tuple[str, ...] = ()
    accel_mean: float | None = None
    gyro_max: float | None = None
    unit: str | None = None
    assessed = 0

    for channel_class in classes:
        sample_type = _CLASS_SAMPLE_TYPE[channel_class]
        samples = [
            measurement
            for receipt in receipts
            for measurement in receipt.measurements
            if isinstance(measurement, sample_type)
        ]
        if not samples:
            checks.append(
                PlausibilityCheck(
                    f"{channel_class.value}.no_measurement",
                    PlausibilityVerdict.UNKNOWN,
                    f"the reader supplied no {channel_class.value} measurement on any of "
                    f"{len(receipts)} receipt(s); arrival is not health, so this stays "
                    f"UNKNOWN rather than becoming PASS",
                )
            )
            continue
        assessed += len(samples)
        if channel_class is ChannelClass.IMU:
            unit = imu_unit_id(entry)
            imu_checks, accel_mean, gyro_max = _assess_imu(entry, samples, rest)
            checks.extend(imu_checks)
        elif channel_class is ChannelClass.POINT_CLOUD:
            cloud_checks, cloud_notes, fields = _assess_point_cloud(samples)
            checks.extend(cloud_checks)
            notes.extend(cloud_notes)
        elif channel_class is ChannelClass.POWER:
            checks.extend(_assess_power(samples))
        elif channel_class is ChannelClass.FOOT_FORCE:
            foot_checks, foot_notes = _assess_foot_force(samples)
            checks.extend(foot_checks)
            notes.extend(foot_notes)
        else:
            checks.extend(_assess_camera(samples))

    return ChannelPlausibility(
        channel_id=entry.channel_id,
        classes=tuple(item.value for item in classes),
        samples_assessed=assessed,
        checks=tuple(checks),
        notes=tuple(notes),
        point_cloud_fields=fields,
        imu_unit_id=unit,
        accel_magnitude_mean_mps2=accel_mean,
        gyro_magnitude_max_rps=gyro_max,
    )


#: A reader is called with the channel and the window it may use, and yields one
#: :class:`SampleReceipt` per message actually received. It must stop by itself
#: at the deadline; the driver enforces the deadline between yields regardless.
ChannelReader = Callable[[Channel, float], Iterable[SampleReceipt]]
ChannelReaderFactory = Callable[[Channel], ChannelReader]


@dataclass(frozen=True, slots=True)
class ChannelProbe:
    """What one channel's probe observed.

    :attr:`status` and :attr:`rate_assessment` are **properties**, not fields.
    There is no argument to this constructor that names PRESENT, so presence
    cannot be asserted — only earned by ``messages_received >= 1``.
    """

    channel_id: str
    #: Messages actually received and accepted. The only route to PRESENT.
    messages_received: int
    #: The window the probe was allowed, in seconds. The rate denominator.
    window_s: float
    #: Expected rate for this window, or ``None`` when nobody supplied one.
    expected_rate_hz: float | None
    #: Longest silence inside the window, including the lead-in from window
    #: start to the first receipt and the tail from the last receipt to the
    #: deadline. ``None`` when nothing arrived.
    max_gap_ns: int | None
    #: What this probe saw, in words, for a human reading the report.
    evidence: str
    #: Required when nothing was received, forbidden when something was.
    absence: AbsenceReason | None = None
    #: What the failure said, verbatim where possible.
    absence_detail: str = ""
    #: What an operator can do about it. Empty when nothing is wrong.
    remedy: str = ""
    #: Receipts thrown away because the probe failed after yielding them. Kept
    #: so discarded evidence is visible rather than silently gone.
    receipts_discarded: int = 0
    first_receipt_ns: int | None = None
    last_receipt_ns: int | None = None
    #: PS-J's ruling on whether what arrived is physically possible. ``None``
    #: means the plausibility layer did not run for this probe at all, which
    #: :attr:`plausibility_verdict` reports as UNKNOWN — never as PASS.
    plausibility: ChannelPlausibility | None = None

    def __post_init__(self) -> None:
        _require_int(self.messages_received, field_name="messages_received")
        _require_int(self.receipts_discarded, field_name="receipts_discarded")
        _require_int(self.max_gap_ns, field_name="max_gap_ns", allow_none=True)
        _require_int(self.first_receipt_ns, field_name="first_receipt_ns", allow_none=True)
        _require_int(self.last_receipt_ns, field_name="last_receipt_ns", allow_none=True)
        if not isinstance(self.window_s, float) or not self.window_s > 0.0:
            raise ProbeContractError(
                f"{self.channel_id}: window_s must be a positive float, got {self.window_s!r}"
            )
        if self.expected_rate_hz is not None and (
            not isinstance(self.expected_rate_hz, float) or not self.expected_rate_hz > 0.0
        ):
            raise ProbeContractError(
                f"{self.channel_id}: expected_rate_hz must be a positive float or None, "
                f"got {self.expected_rate_hz!r}"
            )
        if not self.evidence.strip():
            raise ProbeContractError(f"{self.channel_id}: a probe must state its evidence")
        if self.messages_received == 0 and self.absence is None:
            raise ProbeContractError(
                f"{self.channel_id}: a probe that received nothing must name an "
                f"AbsenceReason — silence without a reason is the permissive default "
                f"board rule 3 forbids"
            )
        if self.messages_received > 0 and self.absence is not None:
            raise ProbeContractError(
                f"{self.channel_id}: {self.messages_received} message(s) received but "
                f"absence={self.absence.value!r}"
            )

    @property
    def observed_rate_hz(self) -> float | None:
        """Messages per second over the whole window, or ``None`` if silent."""

        if self.messages_received <= 0:
            return None
        return self.messages_received / self.window_s

    @property
    def rate_assessment(self) -> RateAssessment:
        """Derived. Never stored, so it cannot be hand-edited into NOMINAL."""

        if self.messages_received <= 0:
            return RateAssessment.NOT_APPLICABLE
        expected = self.expected_rate_hz
        if expected is None:
            return RateAssessment.UNASSESSED_NO_EXPECTATION
        if expected * self.window_s < MIN_RATE_SAMPLES:
            return RateAssessment.UNASSESSED_WINDOW_TOO_SHORT
        if self.max_gap_ns is not None and self.max_gap_ns > (
            MAX_GAP_PERIODS / expected
        ) * 1_000_000_000:
            return RateAssessment.STALLED
        observed = self.messages_received / self.window_s
        if observed < RATE_DEFICIT_FLOOR * expected:
            return RateAssessment.DEFICIT
        if observed > RATE_EXCESS_CEILING * expected:
            return RateAssessment.EXCESS
        return RateAssessment.NOMINAL

    @property
    def status(self) -> ProbeStatus:
        """The single place in this codebase that can produce PRESENT.

        Deliberately **independent of** :attr:`plausibility_verdict`. PS-J's card
        is explicit: a channel is recorded regardless of its plausibility verdict,
        because a suspect channel is still evidence and a failed physical check
        must never silence a recording. Presence answers *did a message arrive*;
        plausibility answers *is what arrived possible*; conflating them would
        either hide a broken sensor or throw away its data.
        """

        if self.messages_received <= 0:
            return ProbeStatus.ABSENT
        if self.rate_assessment.is_degraded:
            return ProbeStatus.DEGRADED
        return ProbeStatus.PRESENT

    @property
    def plausibility_verdict(self) -> PlausibilityVerdict:
        """Derived, and UNKNOWN when the layer did not run. Never PASS by default."""

        if self.plausibility is None:
            return PlausibilityVerdict.UNKNOWN
        return self.plausibility.verdict

    @property
    def rate_deficit_fraction(self) -> float | None:
        """Observed over expected, so a deficit is quantified rather than named."""

        observed = self.observed_rate_hz
        if observed is None or self.expected_rate_hz is None:
            return None
        return observed / self.expected_rate_hz

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "status": self.status.value,
            "messages_received": self.messages_received,
            "window_s": self.window_s,
            "observed_rate_hz": self.observed_rate_hz,
            "expected_rate_hz": self.expected_rate_hz,
            "rate_assessment": self.rate_assessment.value,
            "rate_fraction": self.rate_deficit_fraction,
            "max_gap_ns": self.max_gap_ns,
            "first_receipt_ns": self.first_receipt_ns,
            "last_receipt_ns": self.last_receipt_ns,
            "receipts_discarded": self.receipts_discarded,
            "absence": None if self.absence is None else self.absence.value,
            "absence_detail": self.absence_detail,
            "remedy": self.remedy,
            "evidence": self.evidence,
            "plausibility_verdict": self.plausibility_verdict.value,
            "plausibility": None if self.plausibility is None else self.plausibility.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Observation:
    """One attested fact about the rig, or the honest absence of one.

    ``value is None`` iff ``kind is ABSENT`` iff ``absence is not None`` — all
    three enforced, so an absence can never be recorded as a blank value that a
    later reader mistakes for a measurement.
    """

    key: str
    value: str | int | None
    kind: EvidenceKind
    #: How we know. For OPERATOR_OBSERVED this must name the operator and the
    #: photograph id from ``session/PHOTO_LIST.md``.
    evidence: str
    absence: AbsenceReason | None = None
    remedy: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceKind):
            raise ProbeContractError(f"{self.key}: kind must be an EvidenceKind, got {self.kind!r}")
        if isinstance(self.value, bool):
            raise ProbeContractError(f"{self.key}: a bool is not an observation value")
        if not self.evidence.strip():
            raise ProbeContractError(f"{self.key}: an observation must state its evidence")
        if self.kind is EvidenceKind.ABSENT:
            if self.value is not None:
                raise ProbeContractError(
                    f"{self.key}: an ABSENT observation must not carry a value, got {self.value!r}"
                )
            if self.absence is None:
                raise ProbeContractError(f"{self.key}: an ABSENT observation must name a reason")
            return
        if self.value is None:
            raise ProbeContractError(
                f"{self.key}: kind={self.kind.value} carries no value — record it as "
                f"ABSENT with a reason instead of as a blank"
            )
        if isinstance(self.value, str) and not self.value.strip():
            raise ProbeContractError(f"{self.key}: a blank string is not a value")
        if self.absence is not None:
            raise ProbeContractError(
                f"{self.key}: kind={self.kind.value} must not carry absence="
                f"{self.absence.value!r}"
            )
        if self.kind is EvidenceKind.OPERATOR_OBSERVED and not _names_operator_and_photo(
            self.evidence
        ):
            raise ProbeContractError(
                f"{self.key}: an OPERATOR_OBSERVED value must name the operator and the "
                f"photograph backing it (session/PHOTO_LIST.md id, e.g. 'P02'), got "
                f"{self.evidence!r}"
            )

    @property
    def is_known(self) -> bool:
        return self.kind is not EvidenceKind.ABSENT

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "kind": self.kind.value,
            "evidence": self.evidence,
            "absence": None if self.absence is None else self.absence.value,
            "remedy": self.remedy,
        }


_PHOTO_ID = re.compile(r"\bP\d{2}\b")


def _names_operator_and_photo(evidence: str) -> bool:
    """An operator observation must be attributable to a person and a photo."""

    return bool(_PHOTO_ID.search(evidence)) and "operator" in evidence.lower()


@dataclass(frozen=True, slots=True)
class OperatorObservation:
    """A value a human read off a label, with who read it and which photo."""

    value: str
    operator: str
    photo_id: str

    def __post_init__(self) -> None:
        for name in ("value", "operator", "photo_id"):
            text = getattr(self, name)
            if not isinstance(text, str) or not text.strip():
                raise ProbeContractError(f"operator observation {name} must be non-empty")
        if not _PHOTO_ID.fullmatch(self.photo_id.strip()):
            raise ProbeContractError(
                f"photo_id must be a session/PHOTO_LIST.md id like 'P02', got {self.photo_id!r}"
            )

    def as_observation(self, key: str) -> Observation:
        return Observation(
            key=key,
            value=self.value.strip(),
            kind=EvidenceKind.OPERATOR_OBSERVED,
            evidence=(
                f"read off the unit by operator {self.operator.strip()}, photograph "
                f"{self.photo_id.strip()} (session/PHOTO_LIST.md)"
            ),
        )


@dataclass(frozen=True, slots=True)
class Finding:
    """Something the operator needs to know, ranked."""

    code: str
    severity: FindingSeverity
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.severity, FindingSeverity):
            raise ProbeContractError(f"{self.code}: severity must be a FindingSeverity")
        if not self.code.strip() or not self.detail.strip():
            raise ProbeContractError("a finding must carry a code and a detail")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity.value, "detail": self.detail}


# ---------------------------------------------------------------------------
# The probe driver
# ---------------------------------------------------------------------------


def probe_channel(
    entry: Channel,
    reader: ChannelReader,
    *,
    window_s: float = DEFAULT_WINDOW_S,
    expected_rate_hz: float | None = None,
    clock: Callable[[], int] = time.monotonic_ns,
    rest: RestPeriod | None = None,
) -> ChannelProbe:
    """Run one channel's reader for a bounded window and rule on what arrived.

    Every failure mode ends in ABSENT. The reader may raise, hang past its
    deadline between yields, yield nothing, or yield garbage; none of those can
    produce a PRESENT, because PRESENT is derived from a positive receipt count
    and every failure path discards receipts.

    The deadline is enforced *between* yields. A reader that blocks inside a C
    call past its deadline is not interruptible from here — see the status doc's
    ``does_not_prove``; the mitigation is that each real reader is constructed
    with its own transport-level timeout.
    """

    if not isinstance(window_s, float) or not window_s > 0.0:
        raise ProbeContractError(f"{entry.channel_id}: window_s must be a positive float")
    started = clock()
    deadline = started + int(window_s * 1_000_000_000)
    receipts: list[SampleReceipt] = []
    absence: AbsenceReason | None = None
    detail = ""
    remedy = ""
    stream: Iterator[SampleReceipt] | None = None
    try:
        stream = iter(reader(entry, window_s))
        while clock() < deadline:
            try:
                receipt = next(stream)
            except StopIteration:
                break
            _validate_receipt(entry, receipt, receipts)
            receipts.append(receipt)
    except TransportUnavailableError as exc:
        absence, detail, remedy = exc.reason, exc.detail, exc.remedy
    except ProbeContractError as exc:
        absence, detail = AbsenceReason.PROBE_CONTRACT_VIOLATION, str(exc)
        remedy = (
            "the reader for this channel is defective, not the sensor; fix the "
            "adapter and re-probe before trusting any channel it serves"
        )
    except TimeoutError as exc:
        absence, detail = AbsenceReason.TIMEOUT, f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - a probe that raises is ABSENT, always
        absence, detail = AbsenceReason.PROBE_RAISED, f"{type(exc).__name__}: {exc}"
    finally:
        _close_quietly(stream)

    elapsed_ns = max(clock() - started, 0)
    if absence is not None:
        # Partial evidence from a failed probe is not evidence. The count is
        # kept so the operator sees what was thrown away.
        return ChannelProbe(
            channel_id=entry.channel_id,
            messages_received=0,
            window_s=window_s,
            expected_rate_hz=expected_rate_hz,
            max_gap_ns=None,
            evidence=(
                f"probe failed after {elapsed_ns / 1e9:.2f} s of a {window_s:.2f} s window "
                f"on {entry.transport.value} {entry.address!r}"
                + (
                    f"; {len(receipts)} already-yielded receipt(s) DISCARDED — partial "
                    f"evidence from a failed probe is not evidence"
                    if receipts
                    else "; nothing had been received"
                )
            ),
            absence=absence,
            absence_detail=detail,
            remedy=remedy,
            receipts_discarded=len(receipts),
            plausibility=_unjudgeable(
                entry.channel_id,
                "channel.no_message_received",
                f"the probe failed ({absence.value}) and its receipts were discarded, so "
                f"there is nothing to rule on",
            ),
        )
    if not receipts:
        timed_out = elapsed_ns >= int(window_s * 1_000_000_000)
        return ChannelProbe(
            channel_id=entry.channel_id,
            messages_received=0,
            window_s=window_s,
            expected_rate_hz=expected_rate_hz,
            max_gap_ns=None,
            evidence=(
                f"no message in {elapsed_ns / 1e9:.2f} s of a {window_s:.2f} s window on "
                f"{entry.transport.value} {entry.address!r}"
            ),
            absence=AbsenceReason.TIMEOUT if timed_out else AbsenceReason.NO_MESSAGE,
            absence_detail=(
                "window elapsed with nothing received"
                if timed_out
                else "reader finished early having yielded nothing"
            ),
            plausibility=_unjudgeable(
                entry.channel_id,
                "channel.no_message_received",
                "no message arrived, so there is nothing to rule on",
            ),
        )

    stamps = [receipt.host_monotonic_ns for receipt in receipts]
    boundaries = [started, *stamps, min(deadline, started + elapsed_ns)]
    max_gap = max(
        (later - earlier for earlier, later in itertools.pairwise(boundaries)),
        default=0,
    )
    return ChannelProbe(
        channel_id=entry.channel_id,
        messages_received=len(receipts),
        window_s=window_s,
        expected_rate_hz=expected_rate_hz,
        max_gap_ns=max(max_gap, 0),
        evidence=(
            f"{len(receipts)} message(s) received on {entry.transport.value} "
            f"{entry.address!r}; first {receipts[0].payload_bytes} B"
            + (f" ({receipts[0].detail})" if receipts[0].detail else "")
        ),
        first_receipt_ns=stamps[0],
        last_receipt_ns=stamps[-1],
        plausibility=_safe_assess(entry, receipts, rest),
    )


def _safe_assess(
    entry: Channel, receipts: Sequence[SampleReceipt], rest: RestPeriod | None
) -> ChannelPlausibility:
    """Assess, and turn any defect in the assessor itself into UNKNOWN.

    The plausibility layer may make the attestation stricter; it may not make a
    probe fail. A bug here — or a reader handing back a sample the rules cannot
    digest — must not convert a channel that really did deliver messages into an
    absence, and must not produce a traceback on a session morning.
    """

    try:
        return assess_plausibility(entry, receipts, rest=rest)
    except Exception as exc:  # noqa: BLE001 - an assessor that raises judges nothing
        return _unjudgeable(
            entry.channel_id,
            "channel.assessor_raised",
            f"the plausibility assessor raised {type(exc).__name__}: {exc}. The channel's "
            f"messages and status are unaffected; only the ruling is missing",
        )


def _validate_receipt(
    entry: Channel, receipt: object, accepted: Sequence[SampleReceipt]
) -> None:
    """Refuse anything that is not a receipt for THIS channel, in order."""

    if not isinstance(receipt, SampleReceipt):
        raise ProbeContractError(
            f"{entry.channel_id}: reader yielded {type(receipt).__name__}, not a SampleReceipt"
        )
    if receipt.channel_id != entry.channel_id:
        raise ProbeContractError(
            f"{entry.channel_id}: reader yielded a receipt labelled "
            f"{receipt.channel_id!r} — a probe may not mint presence for another channel"
        )
    if accepted and receipt.host_monotonic_ns < accepted[-1].host_monotonic_ns:
        raise ProbeContractError(
            f"{entry.channel_id}: host_monotonic_ns went backwards "
            f"({accepted[-1].host_monotonic_ns} then {receipt.host_monotonic_ns})"
        )


def _close_quietly(stream: object) -> None:
    close = getattr(stream, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:  # noqa: BLE001 - a failing teardown must not mask the verdict
        return


# ---------------------------------------------------------------------------
# Default readers — every one of them refuses, with a remedy
# ---------------------------------------------------------------------------


def _module_present(name: str) -> bool:
    """Is this module importable here? A raise counts as absent."""

    try:
        import importlib.util

        return importlib.util.find_spec(name) is not None
    except Exception:  # noqa: BLE001 - a probe that raises is ABSENT
        return False


_VENDOR_SDK_WARNING = (
    "Do NOT pip install the vendor SDK into .parcel/: its absence from that venv "
    "is this project's strongest motion guarantee (PHYSICAL_SESSION_PLAN.md, board "
    "rule 1). Run preflight from the Orin's ROS 2 Humble environment instead."
)

#: Transport -> (modules that could serve it, remedy). Any one module suffices.
_TRANSPORT_MODULES: Mapping[str, tuple[tuple[str, ...], str]] = {
    "dds": (
        ("rclpy", "unitree_sdk2py", "cyclonedds"),
        (
            "source the Orin's Humble overlay (unitree_ros2) or activate the vendor "
            f"SDK environment, then re-run. {_VENDOR_SDK_WARNING}"
        ),
    ),
    "unilidar_sdk2": (
        ("unitree_lidar_sdk", "unilidar_sdk2"),
        (
            "build unilidar_sdk2 on the Orin and put its Python binding on PYTHONPATH; "
            "the add-on L2 does not appear on the robot's DDS."
        ),
    ),
    "vendor_video": (
        ("unitree_sdk2py",),
        (
            "the Go2 front camera is not on the DDS topic set; it needs the vendor "
            f"VideoClient / WebRTC path. {_VENDOR_SDK_WARNING}"
        ),
    ),
    # Card TRUTH-1 (SDK-REM-1): the D455 is the one transport here whose SDK is
    # a plain pip wheel — on BOTH hosts. The four remedies around it name the
    # Orin because those SDKs are vendor builds that exist nowhere else; this
    # one names the Orin only to say that pip works there too. Measured
    # 2026-08-22 from this box; the Orin NX (Go2 EDU PLUS, ordered 2026-08-22)
    # is not on hand, so its half is a wheel that EXISTS, not one that has run.
    "realsense": (
        ("pyrealsense2",),
        (
            "on this dev box run `.parcel/bin/pip install -e '.[camera-realsense]'` — "
            "already installed here, 2.58.3.10794 cp314, measured 2026-08-22; on the "
            "Orin NX run `pip install pyrealsense2` in the DEPLOY venv, never into "
            ".parcel/, IF the dock boots a JetPack 6.x (CPython 3.10) — the cp310 "
            "manylinux2014_aarch64 wheel exists for that release, untried on the "
            "unit. On a JetPack 5.1.1 dock (CPython 3.8) that release publishes no "
            "aarch64 wheel and this is a source build. Which JetPack the unit ships "
            "with is UNCONFIRMED. Then check the D455 is on a USB3 (blue) port: a "
            "USB2 cable silently halves the available streams."
        ),
    ),
    "vendor_uwb": (
        ("unitree_sdk2py",),
        f"the UWB fob is a vendor path with no public protocol. {_VENDOR_SDK_WARNING}",
    ),
    "usb_audio": (
        ("sounddevice", "pyaudio"),
        "the XVF3800 is in the post (BLOCKED.md B3); expect ABSENT today.",
    ),
}

#: Transports addressed by a device file rather than a module.
_TRANSPORT_DEVICE_GLOBS: Mapping[str, tuple[str, str]] = {
    "serial": ("/dev/ttyACM*", "plug the ZED-F9P in and confirm it enumerates as a CDC-ACM device"),
}


#: How a refusal names the CLI escape hatch. Kept in one place because the
#: message MUST name only flags that exist: as shipped, this module told the
#: operator to "supply one via --reader-module" and no such flag was ever added
#: to :func:`build_arg_parser` — a refusal an operator cannot act on is worse
#: than no refusal at all. ``test_every_flag_a_refusal_names_is_a_real_flag``
#: parses every ``--flag`` token out of every refusal this module can emit and
#: asserts argparse knows it.
READER_MODULE_FLAG_HELP = (
    "`python -m scripts.parcel_capture.preflight --reader-module MODULE:FACTORY`"
)


def unavailable_reader_factory(entry: Channel) -> ChannelReader:
    """A reader that refuses, naming what is missing. The *fallback*, not the default.

    This is what makes a dev-box run useful. Nothing here opens a socket, and
    nothing here installs anything; each transport is asked whether the thing it
    would need exists, and the refusal says which thing and what to do.

    Until PS-N this was also :func:`run_preflight`'s **default**, which meant the
    tool whose whole job is to prove channels are live before the session could
    not reach a single one: on an Orin with ``rclpy`` sourced and the dog
    publishing, every channel still came back ABSENT with "this build ships no
    live reader". :func:`default_reader_factory` is the default now, and it falls
    back to this function for the transports no adapter serves — which is where
    these per-transport remedies (tegrastats not on PATH, no ``/dev/ttyACM*``)
    are better than anything the adapter registry could say.
    """

    transport = entry.transport.value

    modules_remedy = _TRANSPORT_MODULES.get(transport)
    if modules_remedy is not None:
        modules, remedy = modules_remedy
        available = [name for name in modules if _module_present(name)]
        if not available:
            return _refusing_reader(
                AbsenceReason.DEPENDENCY_MISSING,
                f"none of {', '.join(modules)} is importable in {sys.executable}",
                remedy,
            )
        return _refusing_reader(
            AbsenceReason.NOT_ATTEMPTED,
            f"{', '.join(available)} is importable but this reader factory ships no live "
            f"{transport} reader",
            f"select a live reader with {READER_MODULE_FLAG_HELP}, or pass "
            f"run_preflight(reader_factory=...); preflight refuses to guess at presence.",
        )

    if transport == "platform_tool":
        tool = entry.address.split()[0]
        if shutil.which(tool) is None:
            return _refusing_reader(
                AbsenceReason.TOOL_MISSING,
                f"{tool!r} is not on PATH",
                f"{tool} ships with JetPack; this host is not a Jetson, so expect "
                f"ABSENT here and re-run preflight on the Orin.",
            )
        return _refusing_reader(
            AbsenceReason.NOT_ATTEMPTED,
            f"{tool!r} is on PATH but this build ships no live reader for it",
            "wire the tegrastats line reader on the Orin before the session.",
        )

    glob_remedy = _TRANSPORT_DEVICE_GLOBS.get(transport)
    if glob_remedy is not None:
        pattern, remedy = glob_remedy
        matches = sorted(Path("/dev").glob(pattern.removeprefix("/dev/")))
        if not matches:
            return _refusing_reader(
                AbsenceReason.DEVICE_NODE_MISSING, f"no device matches {pattern}", remedy
            )
        return _refusing_reader(
            AbsenceReason.NOT_ATTEMPTED,
            f"{len(matches)} device(s) match {pattern} but this build ships no live reader",
            remedy,
        )

    return _refusing_reader(
        AbsenceReason.NOT_ATTEMPTED,
        f"no reader is registered for transport {transport!r}",
        "register a reader for this transport before claiming the channel exists.",
    )


def _refusing_reader(reason: AbsenceReason, detail: str, remedy: str) -> ChannelReader:
    def _reader(entry: Channel, window_s: float) -> Iterable[SampleReceipt]:
        raise TransportUnavailableError(reason, f"{entry.channel_id}: {detail}", remedy)

    return _reader


def default_reader_factory(entry: Channel) -> ChannelReader:
    """The real one: a live ingest adapter where one exists, a refusal where none does.

    This is the preflight half of the PS-G ingest fix, and it is the half that
    was never closed. ``scripts/parcel_capture/ingest/`` shipped a DDS
    subscriber, a RealSense loop and an L2 reader, ``record.py`` was rewired to
    resolve through them, and this module was left defaulting to
    :func:`unavailable_reader_factory` — so preflight, whose one job is to prove
    a channel is live *before* the session, could not reach a channel even on a
    correctly-configured Orin.

    Three refusal-shaped outcomes, all ABSENT, none a traceback:

    * the ``ingest`` subpackage will not import -> fall back;
    * no adapter serves this transport (tegrastats, the ZED-F9P, the mic array,
      the UWB fob, the camera's H.264 path) -> fall back, because
      :func:`unavailable_reader_factory`'s per-transport remedy is the more
      actionable of the two;
    * an adapter serves it but its dependency is missing here -> fall back, so
      the operator still gets the transport-level remedy with the
      never-install-the-vendor-SDK-into-.parcel warning attached.

    Only when an adapter both serves the channel **and** could run does this
    return a reader that actually subscribes. Nothing on this path can publish:
    every adapter holds its vendor object behind a ``ReadOnlyHandle`` whose
    allowlist excludes every command surface, pinned by
    ``tests/test_capture_ingest.py``.
    """

    try:
        from .ingest import IngestError, adapter_for, channel_reader_factory
    except ImportError as error:  # pragma: no cover - the subpackage ships beside this file
        return _refusing_reader(
            AbsenceReason.NOT_ATTEMPTED,
            f"the ingest subpackage is not importable ({error})",
            f"reinstall scripts/parcel_capture/ingest/, or name your own factory with "
            f"{READER_MODULE_FLAG_HELP}.",
        )
    try:
        adapter = adapter_for(entry)
    except IngestError:
        # A stated gap, not a surprise. UNSERVED_TRANSPORTS names the reason and
        # unavailable_reader_factory names the remedy; the second is the one an
        # operator can act on at 08:00, so it wins.
        return unavailable_reader_factory(entry)
    if not adapter.dependency_report().satisfied:
        return unavailable_reader_factory(entry)
    return channel_reader_factory(adapter)(entry)


def load_reader_factory(spec: str) -> ChannelReaderFactory:
    """``--reader-module pkg.mod:attr`` -> the factory it names, or a refusal.

    Fail closed in every direction (board rule 3): a spec with no colon, a module
    that will not import, an attribute that is missing, and an attribute that is
    not callable are four different refusals and none of them falls back to a
    default. A preflight that silently reverted to "no reader" after being told
    to use one is exactly the failure this card exists to close.
    """

    if not isinstance(spec, str) or spec.count(":") != 1:
        raise ProbeContractError(
            f"--reader-module {spec!r}: expected MODULE:FACTORY, e.g. "
            f"scripts.parcel_capture.ingest:live_reader_factory"
        )
    module_name, attribute = (part.strip() for part in spec.split(":"))
    if not module_name or not attribute:
        raise ProbeContractError(
            f"--reader-module {spec!r}: both the module and the factory name are required"
        )
    try:
        module = importlib.import_module(module_name)
    except Exception as error:  # an unimportable module is a refusal, never a crash
        raise ProbeContractError(
            f"--reader-module {spec!r}: {module_name} is not importable "
            f"({type(error).__name__}: {error})"
        ) from error
    factory = getattr(module, attribute, None)
    if factory is None:
        raise ProbeContractError(
            f"--reader-module {spec!r}: {module_name} has no attribute {attribute!r}"
        )
    if not callable(factory):
        raise ProbeContractError(
            f"--reader-module {spec!r}: {module_name}.{attribute} is not callable; a "
            f"reader factory takes a Channel and returns a reader"
        )
    return factory


def expected_rate_for(entry: Channel, configured_rates: Mapping[str, float]) -> float | None:
    """The rate this channel is expected to hold, or ``None`` when nobody set one.

    ``PERIODIC`` takes the matrix's device constant. ``CONFIGURED`` takes the
    capture configuration and nothing else — a rate nobody chose is not an
    expectation (PS-A's ``RateKind`` docstring), so an unconfigured D455 stream
    is unassessable rather than nominal. ``EVENT_DRIVEN`` and ``UNKNOWN`` have no
    rate by construction; an explicit override is still honoured for UNKNOWN
    because PS-D exists to replace unknowns with measurements.
    """

    override = configured_rates.get(entry.channel_id)
    if override is not None:
        if isinstance(override, bool) or not isinstance(override, (int, float)):
            raise ProbeContractError(
                f"{entry.channel_id}: configured rate must be a number, got {override!r}"
            )
        if not float(override) > 0.0:
            raise ProbeContractError(
                f"{entry.channel_id}: configured rate must be positive, got {override!r}"
            )
        if entry.rate_kind is RateKind.EVENT_DRIVEN:
            raise ProbeContractError(
                f"{entry.channel_id}: is EVENT_DRIVEN; a configured rate would turn "
                f"normal silence into a fault"
            )
        return float(override)
    if entry.rate_kind is RateKind.PERIODIC:
        return entry.nominal_rate_hz
    return None


def probe_all_channels(
    *,
    reader_factory: ChannelReaderFactory = default_reader_factory,
    window_s: float = DEFAULT_WINDOW_S,
    configured_rates: Mapping[str, float] | None = None,
    channels: Sequence[Channel] = CHANNELS,
    clock: Callable[[], int] = time.monotonic_ns,
    rest: RestPeriod | None = None,
) -> tuple[ChannelProbe, ...]:
    """Probe every channel in the PS-A matrix. No second list lives here.

    A factory that itself raises yields an ABSENT probe for that channel rather
    than aborting the run: one broken adapter must not cost the session its
    report on the other twenty-one channels.
    """

    rates = dict(configured_rates or {})
    probes: list[ChannelProbe] = []
    for entry in channels:
        try:
            expected = expected_rate_for(entry, rates)
        except ProbeContractError as exc:
            probes.append(_factory_failure_probe(entry, window_s, exc))
            continue
        try:
            reader = reader_factory(entry)
        except Exception as exc:  # noqa: BLE001 - a factory that raises is ABSENT
            probes.append(_factory_failure_probe(entry, window_s, exc, expected))
            continue
        probes.append(
            probe_channel(
                entry,
                reader,
                window_s=window_s,
                expected_rate_hz=expected,
                clock=clock,
                rest=rest,
            )
        )
    return tuple(probes)


def _factory_failure_probe(
    entry: Channel,
    window_s: float,
    exc: BaseException,
    expected: float | None = None,
) -> ChannelProbe:
    contract = isinstance(exc, ProbeContractError)
    return ChannelProbe(
        channel_id=entry.channel_id,
        messages_received=0,
        window_s=window_s,
        expected_rate_hz=expected,
        max_gap_ns=None,
        evidence=f"no probe ran: building the reader raised {type(exc).__name__}",
        absence=(
            AbsenceReason.PROBE_CONTRACT_VIOLATION if contract else AbsenceReason.PROBE_RAISED
        ),
        absence_detail=f"{type(exc).__name__}: {exc}",
        remedy="fix the reader factory for this channel and re-probe.",
        plausibility=_unjudgeable(
            entry.channel_id,
            "channel.no_message_received",
            "no probe ran, so there is nothing to rule on",
        ),
    )


# ---------------------------------------------------------------------------
# Host and device observations
# ---------------------------------------------------------------------------


def probe_host() -> tuple[Observation, ...]:
    """Who is doing the looking. Cheap, and the report is worthless without it."""

    return (
        Observation(
            key="host.label",
            value=f"{socket.gethostname()} {platform.system()} {platform.release()}",
            kind=EvidenceKind.MACHINE_READ,
            evidence="socket.gethostname() + platform.system()/release()",
        ),
        Observation(
            key="host.python",
            value=f"{platform.python_version()} at {sys.executable}",
            kind=EvidenceKind.MACHINE_READ,
            evidence="platform.python_version() + sys.executable",
        ),
    )


def probe_free_disk(path: Path | str) -> tuple[Observation, ...]:
    """Free bytes on the recording destination. Machine-read, no budget implied.

    Whether this number is *enough* is PS-E's arithmetic, not PS-D's, and this
    module deliberately does not invent a threshold it does not own.
    """

    target = Path(path)
    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        absent = Observation(
            key="storage.free_bytes",
            value=None,
            kind=EvidenceKind.ABSENT,
            evidence=f"shutil.disk_usage({str(target)!r}) raised {type(exc).__name__}: {exc}",
            absence=AbsenceReason.DEVICE_NODE_MISSING,
            remedy=f"create or mount the recording destination {target} before the session.",
        )
        return (
            absent,
            Observation(
                key="storage.total_bytes",
                value=None,
                kind=EvidenceKind.ABSENT,
                evidence=absent.evidence,
                absence=AbsenceReason.DEVICE_NODE_MISSING,
                remedy=absent.remedy,
            ),
            Observation(
                key="storage.path",
                value=str(target),
                kind=EvidenceKind.MACHINE_READ,
                evidence="the path preflight was asked about",
            ),
        )
    return (
        Observation(
            key="storage.free_bytes",
            value=int(usage.free),
            kind=EvidenceKind.MACHINE_READ,
            evidence=f"shutil.disk_usage({str(target)!r}).free = {usage.free} B "
            f"({usage.free / 2**30:.1f} GiB)",
        ),
        Observation(
            key="storage.total_bytes",
            value=int(usage.total),
            kind=EvidenceKind.MACHINE_READ,
            evidence=f"shutil.disk_usage({str(target)!r}).total = {usage.total} B",
        ),
        Observation(
            key="storage.path",
            value=str(target),
            kind=EvidenceKind.MACHINE_READ,
            evidence="the path preflight was asked about",
        ),
    )


_L4T_RELEASE = re.compile(
    r"#\s*R(?P<major>\d+)\s*\(release\).*?REVISION:\s*(?P<rev>[\d.]+)", re.DOTALL
)


def probe_jetpack(
    *,
    tegra_release: Path | str = "/etc/nv_tegra_release",
    device_tree_model: Path | str = "/proc/device-tree/model",
) -> tuple[Observation, ...]:
    """L4T release, the JetPack version derived from it, and the board model.

    ADR 0001 pins JetPack 6.2.x for the golden image. Today's session performs no
    flash (Stage-0 run sheet P2 is WAIVED-FOR-SENSOR-ONLY), so this is recorded
    as an *observation* of what the Orin already carries — it does not validate
    ADR 0001 and cannot close P5-G-INSTALL.

    The JetPack name is DERIVED through :data:`L4T_TO_JETPACK`. An L4T release
    absent from that table yields an ABSENT JetPack observation with the raw
    release string still recorded: guessing the JetPack version from an unknown
    L4T is precisely the permissive default board rule 3 forbids.
    """

    raw = _read_text_or_none(tegra_release)
    if raw is None:
        absent_evidence = f"{tegra_release} does not exist or is unreadable"
        l4t: Observation = Observation(
            key="orin.l4t_release",
            value=None,
            kind=EvidenceKind.ABSENT,
            evidence=absent_evidence,
            absence=AbsenceReason.NOT_A_JETSON,
            remedy="run preflight on the Orin; an x86 dev box has no L4T release file.",
        )
        jetpack: Observation = Observation(
            key="orin.jetpack_version",
            value=None,
            kind=EvidenceKind.ABSENT,
            evidence=f"no L4T release to derive from ({absent_evidence})",
            absence=AbsenceReason.NOT_A_JETSON,
            remedy=l4t.remedy,
        )
    else:
        match = _L4T_RELEASE.search(raw)
        if match is None:
            l4t = Observation(
                key="orin.l4t_release",
                value=None,
                kind=EvidenceKind.ABSENT,
                evidence=f"{tegra_release} did not match the R<major> ... REVISION: <rev> form; "
                f"first line was {raw.splitlines()[0][:120]!r}",
                absence=AbsenceReason.UNPARSEABLE,
                remedy="record the file contents by hand in the run sheet; do not guess.",
            )
            jetpack = Observation(
                key="orin.jetpack_version",
                value=None,
                kind=EvidenceKind.ABSENT,
                evidence="no parseable L4T release to derive from",
                absence=AbsenceReason.UNPARSEABLE,
                remedy=l4t.remedy,
            )
        else:
            release = f"{match.group('major')}.{match.group('rev')}"
            l4t = Observation(
                key="orin.l4t_release",
                value=f"L4T R{release}",
                kind=EvidenceKind.MACHINE_READ,
                evidence=f"{tegra_release}: R{match.group('major')} REVISION {match.group('rev')}",
            )
            derived = L4T_TO_JETPACK.get(release)
            if derived is None:
                jetpack = Observation(
                    key="orin.jetpack_version",
                    value=None,
                    kind=EvidenceKind.ABSENT,
                    evidence=f"L4T R{release} is not in preflight's L4T->JetPack table "
                    f"({', '.join(sorted(L4T_TO_JETPACK))}); refusing to guess",
                    absence=AbsenceReason.UNPARSEABLE,
                    remedy="record the JetPack version from `apt list nvidia-jetpack` by hand "
                    "and extend L4T_TO_JETPACK in a later card.",
                )
            else:
                jetpack = Observation(
                    key="orin.jetpack_version",
                    value=derived,
                    kind=EvidenceKind.DERIVED,
                    evidence=f"derived from L4T R{release} via preflight's L4T->JetPack table "
                    f"(a declared mapping, not a measurement)",
                )

    model_raw = _read_text_or_none(device_tree_model)
    if model_raw is None:
        board = Observation(
            key="orin.board_model",
            value=None,
            kind=EvidenceKind.ABSENT,
            evidence=f"{device_tree_model} does not exist or is unreadable",
            absence=AbsenceReason.NOT_A_JETSON,
            remedy="run preflight on the Orin.",
        )
    else:
        board = Observation(
            key="orin.board_model",
            value=model_raw.replace("\x00", "").strip() or "unreadable",
            kind=EvidenceKind.MACHINE_READ,
            evidence=f"{device_tree_model}, NUL-stripped",
        )
    return (l4t, jetpack, board)


def _read_text_or_none(path: Path | str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


_YAML_KEY = re.compile(r"^(?P<indent>[ ]*)(?P<key>[A-Za-z_][A-Za-z0-9_]*):(?P<rest>.*)$")


@dataclass(frozen=True, slots=True)
class ConfigScalar:
    """One ``key: value  # comment`` line, with the dotted path that reached it."""

    path: str
    value: str
    comment: str
    lineno: int

    @property
    def looks_like_placeholder(self) -> bool:
        haystack = f"{self.value} {self.comment}".lower()
        return any(marker in haystack for marker in PLACEHOLDER_MARKERS)


def scan_config_scalars(path: Path | str = ROBOT_CONFIG) -> tuple[ConfigScalar, ...]:
    """Textual scan of a YAML file's scalar leaves, comments retained.

    **Why not PyYAML.** The placeholder marker at ``configs/robot.yaml:128`` lives
    in the *comment* — ``interface: enp3s0  # replace with the dedicated robot
    Ethernet NIC`` — and every YAML parser discards comments. A parse would hand
    back ``"enp3s0"`` as though somebody had chosen it. So this reads lines.

    This is a scan, not a parser: it understands ``key:`` nesting by indentation
    and ignores everything else (lists, flow mappings, multi-line scalars). It
    fails **closed** — a path it fails to reconstruct simply never matches the
    exact strings in :data:`ROBOT_NIC_CONFIG_PATHS`, so a mis-scan can only lose a
    NIC, never promote ``wifi_cards.simulator.interface`` (``lo``) into one.
    """

    text = _read_text_or_none(path)
    if text is None:
        return ()
    stack: list[tuple[int, str]] = []
    scalars: list[ConfigScalar] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _YAML_KEY.match(line)
        if match is None:
            continue
        indent = len(match.group("indent"))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        key = match.group("key")
        rest = match.group("rest")
        value, _, comment = rest.partition("#")
        value = value.strip()
        dotted = ".".join([name for _, name in stack] + [key])
        if value:
            scalars.append(
                ConfigScalar(
                    path=dotted,
                    value=value.strip("'\""),
                    comment=comment.strip(),
                    lineno=lineno,
                )
            )
        else:
            stack.append((indent, key))
    return tuple(scalars)


def probe_network(
    *,
    config_path: Path | str = ROBOT_CONFIG,
    net_class_dir: Path | str = "/sys/class/net",
    environ: Mapping[str, str] | None = None,
) -> tuple[tuple[Observation, ...], tuple[Finding, ...]]:
    """The NIC the robot DDS segment would use, and the DDS domain — or neither.

    ``control/unitree_sport.py:50-53`` hard-fails on a missing
    ``/sys/class/net/<iface>``, so an unverified NIC is a session-day failure
    waiting to happen. Two config paths declare one
    (:data:`ROBOT_NIC_CONFIG_PATHS`) and they can drift; a disagreement means
    neither is trusted.
    """

    env = os.environ if environ is None else environ
    scalars = scan_config_scalars(config_path)
    by_path = {scalar.path: scalar for scalar in scalars}
    findings: list[Finding] = []
    observations: list[Observation] = []

    candidates = [by_path[path] for path in ROBOT_NIC_CONFIG_PATHS if path in by_path]
    placeholders = [scalar for scalar in candidates if scalar.looks_like_placeholder]
    for scalar in placeholders:
        findings.append(
            Finding(
                code="NIC_CONFIG_PLACEHOLDER",
                severity=FindingSeverity.MAJOR,
                detail=(
                    f"{_relpath(config_path)}:{scalar.lineno} still carries a placeholder for "
                    f"{scalar.path} ({scalar.value!r}, comment {scalar.comment!r}). Preflight "
                    f"does not trust it; the NIC actually used goes in the run sheet as an "
                    f"observation, not as a config edit."
                ),
            )
        )
    real = [scalar for scalar in candidates if not scalar.looks_like_placeholder]
    distinct = {scalar.value for scalar in real}
    if not candidates:
        observations.append(
            Observation(
                key="robot.nic",
                value=None,
                kind=EvidenceKind.ABSENT,
                evidence=(
                    f"no scalar at any of {', '.join(ROBOT_NIC_CONFIG_PATHS)} in "
                    f"{_relpath(config_path)}"
                ),
                absence=AbsenceReason.CONFIG_PLACEHOLDER,
                remedy="name the robot NIC in the run sheet as an observation.",
            )
        )
    elif not real:
        observations.append(
            Observation(
                key="robot.nic",
                value=None,
                kind=EvidenceKind.ABSENT,
                evidence=(
                    "every configured NIC candidate is a placeholder: "
                    + "; ".join(
                        f"{_relpath(config_path)}:{s.lineno} {s.path}={s.value!r}"
                        for s in placeholders
                    )
                ),
                absence=AbsenceReason.CONFIG_PLACEHOLDER,
                remedy="record the NIC the Orin really uses in run sheet §7 C0.2.",
            )
        )
    elif len(distinct) > 1:
        observations.append(
            Observation(
                key="robot.nic",
                value=None,
                kind=EvidenceKind.ABSENT,
                evidence="config paths disagree: "
                + "; ".join(f"{s.path}={s.value!r} (:{s.lineno})" for s in real),
                absence=AbsenceReason.CONFIG_AMBIGUOUS,
                remedy="reconcile the two NIC declarations before the session.",
            )
        )
        findings.append(
            Finding(
                code="NIC_CONFIG_DISAGREEMENT",
                severity=FindingSeverity.MAJOR,
                detail=(
                    f"{_relpath(config_path)} declares the robot NIC twice and the two "
                    f"disagree: " + "; ".join(f"{s.path}={s.value!r}" for s in real)
                ),
            )
        )
    else:
        iface = real[0].value
        present = (Path(net_class_dir) / iface).exists()
        if present:
            observations.append(
                Observation(
                    key="robot.nic",
                    value=iface,
                    kind=EvidenceKind.MACHINE_READ,
                    evidence=(
                        f"{real[0].path} = {iface!r} ({_relpath(config_path)}:{real[0].lineno}) "
                        f"and {net_class_dir}/{iface} exists"
                    ),
                )
            )
        else:
            observations.append(
                Observation(
                    key="robot.nic",
                    value=None,
                    kind=EvidenceKind.ABSENT,
                    evidence=(
                        f"{real[0].path} = {iface!r} but {net_class_dir}/{iface} does not "
                        f"exist on this host"
                    ),
                    absence=AbsenceReason.DEVICE_NODE_MISSING,
                    remedy=(
                        "control/unitree_sport.py:50-53 hard-fails on exactly this; fix the "
                        "interface name (or run preflight on the Orin) before the session."
                    ),
                )
            )

    observations.append(_dds_domain_observation(by_path, env, config_path))
    cyclone = env.get("CYCLONEDDS_URI")
    observations.append(
        Observation(
            key="robot.cyclonedds_uri",
            value=cyclone,
            kind=EvidenceKind.MACHINE_READ if cyclone else EvidenceKind.ABSENT,
            evidence=(
                f"CYCLONEDDS_URI={cyclone!r} in this process's environment"
                if cyclone
                else "CYCLONEDDS_URI is unset in this process's environment"
            ),
            absence=None if cyclone else AbsenceReason.NOT_ATTEMPTED,
            remedy=(
                ""
                if cyclone
                else "unset CYCLONEDDS_URI means CycloneDDS picks an interface itself; on a "
                "multi-homed Orin that is a coin flip. Pin it before the session."
            ),
        )
    )
    return tuple(observations), tuple(findings)


def _dds_domain_observation(
    by_path: Mapping[str, ConfigScalar],
    env: Mapping[str, str],
    config_path: Path | str,
) -> Observation:
    """The domain the process would actually join, refusing on disagreement.

    ``ROS_DOMAIN_ID`` in the environment is what a DDS participant really uses; a
    config that says otherwise is a trap. Both are read and any disagreement is
    an ABSENT domain, not a silent preference for one of them.
    """

    env_raw = env.get("ROS_DOMAIN_ID")
    configured = {
        path: by_path[path].value for path in DDS_DOMAIN_CONFIG_PATHS if path in by_path
    }
    if env_raw is not None and not env_raw.strip().isdigit():
        # Checked before the agreement check: a participant cannot join a domain
        # that is not a number, so this is a broken environment rather than a
        # disagreement between two candidate domains.
        return Observation(
            key="robot.dds_domain",
            value=None,
            kind=EvidenceKind.ABSENT,
            evidence=f"ROS_DOMAIN_ID={env_raw!r} is not a non-negative integer",
            absence=AbsenceReason.UNPARSEABLE,
            remedy="set a numeric ROS_DOMAIN_ID.",
        )
    values: set[str] = set(configured.values())
    if env_raw is not None:
        values.add(env_raw.strip())
    if not values:
        return Observation(
            key="robot.dds_domain",
            value=None,
            kind=EvidenceKind.ABSENT,
            evidence=f"no ROS_DOMAIN_ID in the environment and no domain in "
            f"{_relpath(config_path)}",
            absence=AbsenceReason.NOT_ATTEMPTED,
            remedy="set ROS_DOMAIN_ID explicitly on the Orin before the session.",
        )
    if len(values) > 1:
        return Observation(
            key="robot.dds_domain",
            value=None,
            kind=EvidenceKind.ABSENT,
            evidence=(
                f"ROS_DOMAIN_ID={env_raw!r} disagrees with config "
                + ", ".join(f"{path}={value!r}" for path, value in sorted(configured.items()))
            ),
            absence=AbsenceReason.CONFIG_AMBIGUOUS,
            remedy="a participant joins the domain in the ENVIRONMENT; reconcile the two.",
        )
    only = values.pop()
    if not only.isdigit():
        return Observation(
            key="robot.dds_domain",
            value=None,
            kind=EvidenceKind.ABSENT,
            evidence=f"domain id {only!r} is not a non-negative integer",
            absence=AbsenceReason.UNPARSEABLE,
            remedy="set a numeric ROS_DOMAIN_ID.",
        )
    source = "ROS_DOMAIN_ID" if env_raw is not None else ", ".join(sorted(configured))
    return Observation(
        key="robot.dds_domain",
        value=int(only),
        kind=EvidenceKind.MACHINE_READ,
        evidence=f"{source} = {only} (environment and config agree)",
    )


def _relpath(path: Path | str) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


#: A device reader returns a mapping of small strings read off the unit, or
#: raises :class:`TransportUnavailableError`. Tests inject one; the default
#: refuses because no vendor SDK exists in this venv and none will be installed.
DeviceReader = Callable[[], Mapping[str, str]]


def _unavailable_device_reader(
    device: str,
    modules: Sequence[str],
    remedy: str,
    remedy_when_present: str | None = None,
) -> DeviceReader:
    """A reader that refuses, naming WHICH half is missing.

    Card TRUTH-1 (SDK-REM-1): the two branches below are two different facts and
    deserve two different remedies. Until this card they shared one string, and
    for the D455 that string said "install pyrealsense2" on a box where
    ``pyrealsense2`` is installed — the module-present branch printing the
    module-missing remedy. ``remedy_when_present`` defaults to ``remedy``, so
    every caller that has only one true sentence (go2, l2, uwb) is unchanged.
    """

    def _reader() -> Mapping[str, str]:
        missing = [name for name in modules if not _module_present(name)]
        if missing:
            raise TransportUnavailableError(
                AbsenceReason.DEPENDENCY_MISSING,
                f"{device}: none of {', '.join(modules)} importable in {sys.executable}",
                remedy,
            )
        raise TransportUnavailableError(
            AbsenceReason.NOT_ATTEMPTED,
            f"{device}: this build ships no live identity reader",
            remedy if remedy_when_present is None else remedy_when_present,
        )

    return _reader


def _device_observations(
    reader: DeviceReader,
    *,
    fields: Mapping[str, str],
    label: str,
) -> tuple[Observation, ...]:
    """Run one device identity reader; every failure becomes ABSENT observations.

    ``fields`` maps the observation key to the reader-dict key it comes from.
    """

    try:
        read = reader()
        if not isinstance(read, Mapping):
            raise ProbeContractError(
                f"{label} reader returned {type(read).__name__}, expected a mapping"
            )
    except TransportUnavailableError as exc:
        return tuple(
            Observation(
                key=key,
                value=None,
                kind=EvidenceKind.ABSENT,
                evidence=exc.detail,
                absence=exc.reason,
                remedy=exc.remedy,
            )
            for key in fields
        )
    except Exception as exc:  # noqa: BLE001 - a probe that raises is ABSENT
        return tuple(
            Observation(
                key=key,
                value=None,
                kind=EvidenceKind.ABSENT,
                evidence=f"{label} reader raised {type(exc).__name__}: {exc}",
                absence=AbsenceReason.PROBE_RAISED,
                remedy=f"fix the {label} reader and re-probe; nothing was read.",
            )
            for key in fields
        )

    observations: list[Observation] = []
    for key, source_key in fields.items():
        raw = read.get(source_key)
        if raw is None or not isinstance(raw, str) or not raw.strip():
            observations.append(
                Observation(
                    key=key,
                    value=None,
                    kind=EvidenceKind.ABSENT,
                    evidence=f"{label} reader returned no usable {source_key!r} (got {raw!r})",
                    absence=AbsenceReason.NO_MESSAGE,
                    remedy=f"read {source_key} off the {label} by hand and record it in the "
                    f"run sheet.",
                )
            )
        else:
            observations.append(
                Observation(
                    key=key,
                    value=raw.strip(),
                    kind=EvidenceKind.MACHINE_READ,
                    evidence=f"{label} reader reported {source_key}={raw.strip()!r}",
                )
            )
    return tuple(observations)


def probe_robot_identity(reader: DeviceReader | None = None) -> tuple[Observation, ...]:
    """Edition, firmware version and serial — read off the unit or not at all.

    The firmware version is the input to the ADR-0002 security gate in
    :mod:`scripts.parcel_capture.attest`, so it must come from the robot. A
    version typed from memory, taken from a sticker, or defaulted is not a
    firmware version for this purpose.
    """

    return _device_observations(
        reader
        or _unavailable_device_reader(
            "go2",
            ("rclpy", "unitree_sdk2py"),
            "run preflight on the Orin inside the vendor/Humble environment. "
            + _VENDOR_SDK_WARNING,
        ),
        fields={
            "robot.edition": "edition",
            "robot.firmware_version": "firmware_version",
            "robot.serial": "serial",
        },
        label="go2",
    )


#: Card TRUTH-1 (SDK-REM-1): the D455 identity probe's remedy, split in two.
#:
#: This is the SECOND D455 remedy on the preflight product path
#: (``run_preflight`` -> ``probe_d455`` -> the rendered observation table), and
#: R3's registration named only ``_TRANSPORT_MODULES["realsense"]``, so it went
#: unmeasured in the first pass. It said "install pyrealsense2 in the Orin
#: capture environment" on a box where ``pyrealsense2`` is installed and where
#: no Orin exists — SDK-REM-1 verbatim, one function away from the site the card
#: fixed. Both strings below are the same measured facts as
#: ``_TRANSPORT_MODULES["realsense"]``, worded for the branch that reaches them.
_D455_IDENTITY_REMEDY_MODULE_MISSING = (
    "pyrealsense2 is an ordinary pip wheel, not a vendor SDK build. On this dev box run "
    "`.parcel/bin/pip install -e '.[camera-realsense]'` (already installed here: "
    "2.58.3.10794 cp314, measured 2026-08-22). On the Orin NX run `pip install "
    "pyrealsense2` in the DEPLOY venv, never into .parcel/, IF the dock boots a JetPack "
    "6.x (CPython 3.10) — that release publishes aarch64 wheels for cp39/cp310/cp312 "
    "ONLY, so a JetPack 5.1.1 dock (CPython 3.8) is a source build. Which JetPack the "
    "unit ships with is UNCONFIRMED."
)
#: The branch this box actually takes. The module IS importable; what is missing
#: is a live identity READER and, on this host, the camera itself. Telling the
#: operator to install the wheel here is the false-READY failure ENV-1b exists to
#: prevent, pointing the other way.
_D455_IDENTITY_REMEDY_MODULE_PRESENT = (
    "pyrealsense2 is importable here, so this is NOT a missing wheel: this build ships no "
    "live D455 identity reader, and the firmware/serial come from PS-D against the "
    "attached unit. Plug the D455 into a USB 3 (BLUE) port, direct, no hub, confirm it "
    "enumerates (`ls /dev/video*`, `lsusb | grep -i intel`), then read the identity there. "
    "Do not pip install anything for this row."
)


def probe_d455(reader: DeviceReader | None = None) -> tuple[Observation, ...]:
    return _device_observations(
        reader
        or _unavailable_device_reader(
            "d455",
            ("pyrealsense2",),
            _D455_IDENTITY_REMEDY_MODULE_MISSING,
            _D455_IDENTITY_REMEDY_MODULE_PRESENT,
        ),
        fields={"d455.firmware_version": "firmware_version", "d455.serial": "serial"},
        label="d455",
    )


def probe_l2(reader: DeviceReader | None = None) -> tuple[Observation, ...]:
    return _device_observations(
        reader
        or _unavailable_device_reader(
            "l2",
            ("unitree_lidar_sdk", "unilidar_sdk2"),
            "build unilidar_sdk2 on the Orin; the add-on L2 is not on the robot's DDS.",
        ),
        fields={"l2.firmware_version": "firmware_version", "l2.serial": "serial"},
        label="l2",
    )


_LIDAR_MODEL_TOKEN = re.compile(r"\bL[12]\b", re.IGNORECASE)


def probe_builtin_lidar(
    reader: DeviceReader | None = None,
    operator: OperatorObservation | None = None,
) -> tuple[tuple[Observation, ...], tuple[Finding, ...]]:
    """Resolve the L1-vs-L2 contradiction empirically, and name the wrong document.

    Two documents disagree (:data:`BUILTIN_LIDAR_CLAIMS`) and neither is evidence.
    A machine read wins; failing that, an operator reading the label with a
    photograph behind it counts (that is what ``session/PHOTO_LIST.md`` P02 is
    for). Failing both, the contradiction stays open and is reported as open —
    picking a side from a document is the one thing this function will not do.
    """

    findings: list[Finding] = []
    machine = _device_observations(
        reader
        or _unavailable_device_reader(
            "go2 built-in lidar",
            ("rclpy", "unitree_sdk2py"),
            "the built-in unit surfaces on utlidar/* via the robot's DDS, not through "
            "unilidar_sdk2. " + _VENDOR_SDK_WARNING,
        ),
        fields={
            "robot.builtin_lidar_model": "model",
            "robot.builtin_lidar_serial": "serial",
        },
        label="go2 built-in lidar",
    )
    observations = list(machine)
    model_obs = next(obs for obs in observations if obs.key == "robot.builtin_lidar_model")

    if not model_obs.is_known and operator is not None:
        model_obs = operator.as_observation("robot.builtin_lidar_model")
        observations = [model_obs if o.key == model_obs.key else o for o in observations]

    resolved: str | None = None
    if model_obs.is_known and isinstance(model_obs.value, str):
        token = _LIDAR_MODEL_TOKEN.search(model_obs.value)
        if token is not None:
            resolved = token.group(0).upper()

    if resolved is None:
        observations.append(
            Observation(
                key="robot.builtin_lidar_document_verdict",
                value=None,
                kind=EvidenceKind.ABSENT,
                evidence=(
                    "the built-in LiDAR model was not read off the unit, so the "
                    "L1-vs-L2 contradiction stays open; preflight will not resolve it "
                    "from a document"
                ),
                absence=(
                    AbsenceReason.NO_OPERATOR_OBSERVATION
                    if not model_obs.is_known
                    else AbsenceReason.UNPARSEABLE
                ),
                remedy=(
                    "photograph the built-in LiDAR label (session/PHOTO_LIST.md P02) and "
                    "pass it with --builtin-lidar-model MODEL --operator NAME --photo P02."
                ),
            )
        )
        findings.append(
            Finding(
                code="BUILTIN_LIDAR_UNRESOLVED",
                severity=FindingSeverity.NOTE,
                detail=(
                    "built-in LiDAR model still unresolved; the repo contradicts itself ("
                    + "; ".join(f"{doc} says {claim}" for doc, claim in BUILTIN_LIDAR_CLAIMS.items())
                    + "). Neither document is evidence."
                ),
            )
        )
        return tuple(observations), tuple(findings)

    verdicts = []
    for document, claim in BUILTIN_LIDAR_CLAIMS.items():
        verdicts.append(f"{document} says {claim} -> {'CONFIRMED' if claim == resolved else 'WRONG'}")
        if claim != resolved:
            findings.append(
                Finding(
                    code="DOCUMENT_WRONG",
                    severity=FindingSeverity.NOTE,
                    detail=(
                        f"{document} claims the built-in LiDAR is {claim}; the unit reads "
                        f"{resolved}. That document is WRONG and should be corrected by a "
                        f"later card (this tranche does not edit it)."
                    ),
                )
            )
    observations.append(
        Observation(
            key="robot.builtin_lidar_document_verdict",
            value="; ".join(verdicts),
            kind=EvidenceKind.DERIVED,
            evidence=(
                f"unit reads {resolved} ({model_obs.kind.value}: {model_obs.evidence}); each "
                f"document is ruled against that read"
            ),
        )
    )
    return tuple(observations), tuple(findings)


# ---------------------------------------------------------------------------
# Mount-day channel readiness — card SENSE-1 (scrum/20260823/task_3)
# ---------------------------------------------------------------------------
#
# WHAT THIS ANSWERS, and why the 28-row channel matrix above does not answer it.
# That matrix is the RECORDING plan: every row is a DDS/vendor topic a capture
# session writes to a bag, and on a box with no dog every one of them is
# correctly ABSENT. Mount day asks a smaller and more urgent question first —
# *can this host take data from the three things about to be bolted on at all?*
# — and the honest answer has two halves that the matrix conflates:
#
#   the SOFTWARE half   the port binds, the decoder decodes, the module imports
#   the DEVICE half     something is actually on the wire
#
# A row that says only ABSENT cannot tell an operator whether they are waiting
# on a cable or on a `pip install`, and those are different mornings. So a
# readiness row carries three states and an absence REASON from the same closed
# vocabulary the channel probes use (:class:`AbsenceReason`): READY is both
# halves, PARTIAL is "the software path is proven and nothing is on the wire",
# ABSENT is "the software path is missing, so nothing was even attempted".
#
# THE MID-360 ROW IS A REAL BIND AND A REAL DECODE, not a description of one.
# ``parcel_robot.lidar.receive_frames`` deliberately owns no socket, so nothing
# in this tree had ever proved that the host can bind the port the sensor sends
# to. This row does: it binds, listens for a fraction of a second, and runs any
# datagram that arrives through the SAME ``parse_point_frame`` the backend
# uses. On a desk that is PARTIAL/no_message; on the bench with the dog
# powered it is the first thing that goes READY.
#
# NOT AN ``Observation`` AND NOT A 29TH ``ChannelProbe``, deliberately. The
# attestation refuses observation keys it does not know
# (``attest.HardwareAttestationV1``) and the channel enumeration is pinned to
# the matrix; a readiness row is neither of those things, so it rides in its
# own field with its own default and no existing consumer changes.

#: How long the Mid-360 row listens before reporting no_message. A Mid-360
#: streaming points fills a socket buffer in single-digit milliseconds, so this
#: is generous for the question "is anything on this wire?" and cheap enough to
#: run on every preflight.
MID360_LISTEN_S = 0.05

#: Where the kernel lists sound cards. A text read, never a PortAudio open:
#: opening the array is the audio stack's job and it has an owner.
ASOUND_CARDS = "/proc/asound/cards"

#: Substrings that identify the array in a card line. Both spellings appear on
#: this host (`reSpeaker XVF3800 4-Mic Array`, `Seeed Studio reSpeaker`).
_ARRAY_CARD_TOKENS = ("xvf3800", "respeaker")

#: The modules that can open a USB audio device here. Either is enough.
_ARRAY_MODULES = ("sounddevice", "pyaudio")

_MID360_REMEDY_NO_MESSAGE = (
    "the socket is bound and the decoder is sound; nothing is sending. Power the "
    "Mid-360, confirm the sensor's host-IP/port configuration points at this host "
    "(Livox default host point port 56301), and check the robot LAN cable."
)
_MID360_REMEDY_BIND = (
    "the host could not bind the point-data port. Something else is already on it, "
    "or the address is not one of this host's. Check with `ss -ulpn` and free it; "
    "no capture can receive a point cloud until it binds."
)
_MID360_REMEDY_DECODER = (
    "the Livox decoder in this interpreter could not read a frame it built itself, "
    "so the install is broken, not the sensor. Reinstall the project into this venv "
    "and re-run before touching the robot."
)
_D455_MOUNT_REMEDY_DEVICE = (
    "plug the D455 into a USB 3 (BLUE) port, direct, no hub, and confirm it "
    "enumerates (`ls /dev/video*`, `lsusb | grep -i intel`). Do not pip install "
    "anything for this row."
)
_XVF3800_REMEDY_DEVICE = (
    "plug the reSpeaker XVF3800 in over USB and confirm the kernel lists it "
    "(`cat /proc/asound/cards`). Nothing here opens the device; the audio stack "
    "does that on the owner's own gesture."
)
_XVF3800_REMEDY_MODULE = (
    "the kernel lists the array but no host audio module can open it. Install "
    "sounddevice into the capture venv (`.parcel/bin/pip install sounddevice`)."
)


class MountReadiness(str, Enum):
    """The three answers a mount-day row is allowed to give.

    Its own enum rather than :class:`ProbeStatus`, and not only because the
    structural pin allows exactly one producer of ``ProbeStatus.PRESENT`` per
    module: these are different questions. A channel probe grades a STREAM over
    a window; this grades whether the path to a device exists at all.
    """

    READY = "ready"
    PARTIAL = "partial"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class MountChannelRow:
    """One mount-day channel, and what is true about it right now."""

    channel: str
    #: One line: what has to work on mount day for this channel to carry data.
    what: str
    readiness: MountReadiness
    evidence: str
    absence: AbsenceReason | None = None
    absence_detail: str = ""
    remedy: str = ""

    def __post_init__(self) -> None:
        # The same invariant :class:`ChannelProbe` keeps, restated over this
        # row's vocabulary: anything short of READY names a typed reason, and
        # READY may not carry one. A row that is not ready and cannot say why
        # is the "unknown read as fine" failure this whole module exists to
        # prevent.
        if self.readiness is MountReadiness.READY:
            if self.absence is not None:
                raise ProbeContractError(f"{self.channel}: a READY row carries no absence")
        elif self.absence is None:
            raise ProbeContractError(
                f"{self.channel}: {self.readiness.value} must name an AbsenceReason"
            )
        if self.readiness is not MountReadiness.READY and not self.remedy.strip():
            raise ProbeContractError(f"{self.channel}: an unready row must name a remedy")
        if not self.evidence.strip():
            raise ProbeContractError(f"{self.channel}: every row states its evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "what": self.what,
            "readiness": self.readiness.value,
            "evidence": self.evidence,
            "absence": None if self.absence is None else self.absence.value,
            "absence_detail": self.absence_detail,
            "remedy": self.remedy,
        }


def _open_point_socket(host: str, port: int) -> Any:
    """Bind a NON-BLOCKING UDP socket for the Mid-360's point stream.

    The same call ``backends/go2.py:LiveGo2Sources.open_livox_socket`` makes on
    the robot, spelled here because preflight may not import the runtime.
    """

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setblocking(False)
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


def probe_mid360_udp(
    *,
    host: str = "",
    port: int | None = None,
    listen_s: float = MID360_LISTEN_S,
    opener: Callable[[str, int], Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> MountChannelRow:
    """Bind the point-data port, listen briefly, decode whatever arrives."""

    what = "bind the Livox point-data port and decode one datagram"
    try:
        from parcel_robot.lidar.livox_udp import (
            HOST_POINT_DATA_PORT,
            LivoxDecodeError,
            build_point_frame,
            parse_point_frame,
            receive_frames,
        )
    except ImportError as error:
        return MountChannelRow(
            channel="mid360.udp",
            what=what,
            readiness=MountReadiness.ABSENT,
            evidence=f"parcel_robot.lidar is not importable in {sys.executable}",
            absence=AbsenceReason.DEPENDENCY_MISSING,
            absence_detail=str(error),
            remedy=_MID360_REMEDY_DECODER,
        )

    # THE DECODER HALF, proved against the module's own wire builder. This is
    # not a tautology: `build_point_frame` is product code and box-day (HW-9)
    # falsifies IT against one real datagram, so a decoder that cannot read it
    # is a broken install and this row says so before the sensor is blamed.
    probe_frame = build_point_frame(
        [(1000, 0, 100, 10, 0), (2000, 0, 100, 12, 0)], udp_cnt=1, frame_cnt=1
    )
    try:
        decoded = parse_point_frame(probe_frame)
    except LivoxDecodeError as error:
        return MountChannelRow(
            channel="mid360.udp",
            what=what,
            readiness=MountReadiness.ABSENT,
            evidence="parse_point_frame refused a frame build_point_frame produced",
            absence=AbsenceReason.UNPARSEABLE,
            absence_detail=str(error),
            remedy=_MID360_REMEDY_DECODER,
        )

    bind_port = int(HOST_POINT_DATA_PORT) if port is None else int(port)
    open_socket = _open_point_socket if opener is None else opener
    shown_host = host or "0.0.0.0"
    try:
        sock = open_socket(host, bind_port)
    except OSError as error:
        return MountChannelRow(
            channel="mid360.udp",
            what=what,
            readiness=MountReadiness.ABSENT,
            evidence=f"UDP {shown_host}:{bind_port} could not be bound",
            absence=AbsenceReason.PROBE_RAISED,
            absence_detail=str(error),
            remedy=_MID360_REMEDY_BIND,
        )

    refused: list[str] = []
    frames: list[Any] = []
    deadline = float(clock()) + max(0.0, float(listen_s))
    try:
        stream = receive_frames(
            sock,
            max_frames=1,
            on_refusal=lambda error: refused.append(str(error)),
            max_datagrams=64,
            expired=lambda: float(clock()) >= deadline,
        )
        while True:
            try:
                frames.append(next(stream))
            except StopIteration:
                break
            except (BlockingIOError, TimeoutError, OSError):
                break
    finally:
        _close_quietly(sock)

    decoder_note = (
        f"decoder round-trips its own wire layout ({decoded.dot_num} points, "
        f"{decoded.data_type.name})"
    )
    if frames:
        arrived = frames[0]
        return MountChannelRow(
            channel="mid360.udp",
            what=what,
            readiness=MountReadiness.READY,
            evidence=(
                f"UDP {shown_host}:{bind_port} bound; {arrived.dot_num} points decoded "
                f"from a live datagram in {listen_s:.2f}s; {decoder_note}"
            ),
        )
    if refused:
        return MountChannelRow(
            channel="mid360.udp",
            what=what,
            readiness=MountReadiness.PARTIAL,
            evidence=(
                f"UDP {shown_host}:{bind_port} bound; {len(refused)} datagram(s) arrived "
                f"and none decoded; {decoder_note}"
            ),
            absence=AbsenceReason.UNPARSEABLE,
            absence_detail=refused[0],
            remedy=(
                "datagrams are reaching this port but are not Livox point frames: "
                "check that the port belongs to the point stream and not to the "
                "command or IMU stream."
            ),
        )
    return MountChannelRow(
        channel="mid360.udp",
        what=what,
        readiness=MountReadiness.PARTIAL,
        evidence=(
            f"UDP {shown_host}:{bind_port} bound and quiet for {listen_s:.2f}s; "
            f"{decoder_note}"
        ),
        absence=AbsenceReason.NO_MESSAGE,
        absence_detail=f"no datagram arrived on {shown_host}:{bind_port}",
        remedy=_MID360_REMEDY_NO_MESSAGE,
    )


def probe_d455_mount(
    reports: Callable[[], tuple[Any, Any]] | None = None,
) -> MountChannelRow:
    """Readiness of the D455 path: the wheel, then the device node."""

    what = "import the RealSense path and see a camera enumerate"
    try:
        from .ingest.base import DevicePresence

        if reports is None:
            from .ingest.realsense import RealSenseIngest

            dependencies = RealSenseIngest.dependency_report()
            device = RealSenseIngest.device_report()
        else:
            dependencies, device = reports()
    except (ImportError, OSError, AttributeError, TypeError, ValueError) as error:
        return MountChannelRow(
            channel="d455.path",
            what=what,
            readiness=MountReadiness.ABSENT,
            evidence="the RealSense adapter could not be asked",
            absence=AbsenceReason.PROBE_RAISED,
            absence_detail=f"{type(error).__name__}: {error}",
            remedy=_D455_IDENTITY_REMEDY_MODULE_MISSING,
        )
    if not dependencies.satisfied:
        return MountChannelRow(
            channel="d455.path",
            what=what,
            readiness=MountReadiness.ABSENT,
            evidence=f"missing: {', '.join(dependencies.missing)}",
            absence=AbsenceReason.DEPENDENCY_MISSING,
            absence_detail=dependencies.remedy,
            remedy=_D455_IDENTITY_REMEDY_MODULE_MISSING,
        )
    if device.presence is DevicePresence.ATTACHED:
        return MountChannelRow(
            channel="d455.path",
            what=what,
            readiness=MountReadiness.READY,
            evidence=(
                f"{', '.join(dependencies.present)} importable; device {device.detail}"
            ),
        )
    absence = (
        AbsenceReason.DEVICE_NODE_MISSING
        if device.presence is DevicePresence.ABSENT
        else AbsenceReason.NOT_ATTEMPTED
    )
    return MountChannelRow(
        channel="d455.path",
        what=what,
        readiness=MountReadiness.PARTIAL,
        evidence=f"{', '.join(dependencies.present)} importable; no camera enumerates",
        absence=absence,
        absence_detail=device.detail,
        remedy=_D455_MOUNT_REMEDY_DEVICE,
    )


def probe_xvf3800_mount(
    *,
    asound_cards: Path | str = ASOUND_CARDS,
    modules: Sequence[str] = _ARRAY_MODULES,
) -> MountChannelRow:
    """Readiness of the mic array: the kernel's card list, then a host module.

    It READS ``/proc/asound/cards``. It does not open PortAudio, enumerate
    devices or touch a stream: this module runs on a host whose audio stack may
    be armed, and a preflight that opened the microphone would be doing the one
    thing the gateway is careful to do only on the owner's gesture.
    """

    what = "see the reSpeaker array in the kernel's card list"
    listing = _read_text_or_none(Path(asound_cards))
    present = [name for name in modules if _module_present(name)]
    if listing is None:
        return MountChannelRow(
            channel="xvf3800.array",
            what=what,
            readiness=MountReadiness.ABSENT,
            evidence=f"{asound_cards} does not exist, so no card list can be read",
            absence=AbsenceReason.DEVICE_NODE_MISSING,
            absence_detail=f"{asound_cards} is absent on this host",
            remedy=_XVF3800_REMEDY_DEVICE,
        )
    matched = [
        line.strip()
        for line in listing.splitlines()
        if any(token in line.lower() for token in _ARRAY_CARD_TOKENS)
    ]
    if not matched:
        return MountChannelRow(
            channel="xvf3800.array",
            what=what,
            readiness=MountReadiness.PARTIAL,
            evidence=(
                f"{len(listing.splitlines())} line(s) in {asound_cards}, none naming the "
                f"array; host audio modules present: {', '.join(present) or 'none'}"
            ),
            absence=AbsenceReason.DEVICE_NODE_MISSING,
            absence_detail="no card line matches the XVF3800 / reSpeaker name",
            remedy=_XVF3800_REMEDY_DEVICE,
        )
    if not present:
        return MountChannelRow(
            channel="xvf3800.array",
            what=what,
            readiness=MountReadiness.ABSENT,
            evidence=f"the kernel lists {matched[0]!r} but nothing here can open it",
            absence=AbsenceReason.DEPENDENCY_MISSING,
            absence_detail=f"none of {', '.join(modules)} importable in {sys.executable}",
            remedy=_XVF3800_REMEDY_MODULE,
        )
    return MountChannelRow(
        channel="xvf3800.array",
        what=what,
        readiness=MountReadiness.READY,
        evidence=f"kernel card {matched[0]!r}; {', '.join(present)} importable",
    )


def probe_mount_readiness(
    *,
    mid360_opener: Callable[[str, int], Any] | None = None,
    mid360_listen_s: float = MID360_LISTEN_S,
    d455_reports: Callable[[], tuple[Any, Any]] | None = None,
    asound_cards: Path | str = ASOUND_CARDS,
) -> tuple[MountChannelRow, ...]:
    """The three mount-day channels, in the order they get bolted on."""

    return (
        probe_mid360_udp(opener=mid360_opener, listen_s=mid360_listen_s),
        probe_d455_mount(d455_reports),
        probe_xvf3800_mount(asound_cards=asound_cards),
    )


#: One character per state, the same shape ``_STATUS_MARK`` uses above.
_MOUNT_MARK: Mapping[MountReadiness, str] = {
    MountReadiness.READY: "+",
    MountReadiness.PARTIAL: "~",
    MountReadiness.ABSENT: " ",
}


def format_mount_readiness(rows: Sequence[MountChannelRow]) -> list[str]:
    """The block an operator reads before the matrix, or nothing if unprobed."""

    if not rows:
        return []
    width = max(len(row.channel) for row in rows)
    lines = ["", "MOUNT READINESS (the three things being bolted on)"]
    for row in rows:
        lines.append(f"  [{_MOUNT_MARK[row.readiness]}] {row.channel:<{width}}  {row.what}")
        lines.append(f"      {row.evidence}")
        if row.absence is not None:
            lines.append(f"      why: {row.absence.value} — {row.absence_detail}")
        if row.remedy:
            lines.append(f"      remedy: {row.remedy}")
    return lines


# ---------------------------------------------------------------------------
# Support-artifact reconciliation — card S-1 (scrum/20260814/task_1)
# ---------------------------------------------------------------------------
#
# The verified P0 behind this section: four optical streams were on the
# recording plan with no ``camera_info``, no ``/tf`` and no ``/tf_static``.
# The plan now carries those support topics (``rosbag2.SUPPORT_TOPICS``), and
# this is the run-time reconciliation: the observed graph — ``ros2 topic list
# -t``, the one command the run-sheet already opens with — is checked against
# every support topic the plan requires. The semantics are the same honest
# fail-closed semantics sensor channels get: unknown is ABSENT, a REQUIRED
# support topic that is absent or type-mismatched at run time is a REFUSAL,
# and nothing here can declare a topic present without the graph showing it.

try:  # pragma: no cover - exercised only on a checkout without an install
    from scripts.parcel_capture.rosbag2 import SUPPORT_TOPICS, RecordedTopic
except ImportError:  # pragma: no cover - Orin runs this straight from a checkout
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.parcel_capture.rosbag2 import SUPPORT_TOPICS, RecordedTopic

from parcel_robot.capture.channels import (  # after the bootstrap above
    SUPPORT_ARTIFACTS_BY_ID,
    SupportNeed,
)

#: One line of ``ros2 topic list -t``: ``/topic [pkg/msg/Type]`` — or several
#: types in one bracket when the graph disagrees with itself about the topic.
_TOPIC_LIST_LINE = re.compile(r"^(?P<topic>/\S+)\s+\[(?P<types>[^\]]+)\]\s*$")


class SupportTopicStatus(str, Enum):
    """What the observed graph says about one support topic. Never permissive."""

    #: On the graph, carrying the declared type.
    PRESENT = "present"
    #: Not on the graph. Unknown is absent; absent is not a default.
    ABSENT = "absent"
    #: On the graph under a different message type — affirmative evidence of a
    #: misconfiguration, which is worse than absence and never less than one.
    TYPE_MISMATCH = "type_mismatch"


def parse_topic_list(text: str) -> dict[str, tuple[str, ...]]:
    """Parse ``ros2 topic list -t`` output, refusing anything not understood.

    A line this parser cannot read is a refusal, not a skip: a skipped line
    could be exactly the support topic whose absence would otherwise refuse
    the run, and "parse failure" must never be able to impersonate "topic
    missing" or vice versa.
    """

    observed: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _TOPIC_LIST_LINE.match(line.strip())
        if match is None:
            raise PreflightError(
                f"unparseable `ros2 topic list -t` line: {line.strip()!r}; capture "
                f"the list with exactly `ros2 topic list -t` and pass it verbatim"
            )
        types = [item.strip() for item in match.group("types").split(",") if item.strip()]
        if not types:
            raise PreflightError(
                f"topic {match.group('topic')!r} carries an empty type list; an "
                f"empty bracket is not an observation"
            )
        slot = observed.setdefault(match.group("topic"), [])
        for item in types:
            if item not in slot:
                slot.append(item)
    return {topic: tuple(types) for topic, types in observed.items()}


@dataclass(frozen=True, slots=True)
class SupportTopicCheck:
    """One support topic reconciled against the observed graph."""

    support_id: str
    topic: str
    need: str
    expected_type: str
    observed_types: tuple[str, ...]
    status: SupportTopicStatus
    #: True when this check alone forbids proceeding to record.
    refusal: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "support_id": self.support_id,
            "topic": self.topic,
            "need": self.need,
            "expected_type": self.expected_type,
            "observed_types": list(self.observed_types),
            "status": self.status.value,
            "refusal": self.refusal,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class SupportReconciliation:
    """Every support topic's verdict, with the refusals called out."""

    checks: tuple[SupportTopicCheck, ...]
    refusals: tuple[str, ...]
    findings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.refusals

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "parcel.capture.support_reconciliation.v1",
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
            "refusals": list(self.refusals),
            "findings": list(self.findings),
        }


def reconcile_support_topics(
    observed: str | Mapping[str, Sequence[str]],
    *,
    support_topics: Sequence[RecordedTopic] = SUPPORT_TOPICS,
) -> SupportReconciliation:
    """Reconcile the observed graph against the plan's support topics.

    ``observed`` is either the verbatim ``ros2 topic list -t`` output or an
    already-parsed ``topic -> types`` mapping. Refusal rules:

    * a REQUIRED support topic absent from the graph → refusal;
    * ``/tf_static`` (snapshot-substitutable) absent from the graph → refusal
      too: the snapshot is CAPTURED FROM this topic before record start, so a
      graph with no ``/tf_static`` publisher has nothing to snapshot either;
    * any support topic present under the wrong type → refusal — affirmative
      evidence of misconfiguration outranks absence;
    * an opportunistic support topic absent → finding, never a refusal (a
      stationary rig with no odometry publisher legitimately has no ``/tf``).
    """

    graph = parse_topic_list(observed) if isinstance(observed, str) else {
        str(topic): tuple(str(item) for item in types)
        for topic, types in observed.items()
    }
    checks: list[SupportTopicCheck] = []
    refusals: list[str] = []
    findings: list[str] = []
    for item in support_topics:
        if item.support_id is None:  # pragma: no cover - contract guard
            raise PreflightError(
                f"{item.topic} is not a support topic; reconcile_support_topics "
                f"takes rosbag2.SUPPORT_TOPICS rows only"
            )
        artifact = SUPPORT_ARTIFACTS_BY_ID[item.support_id]
        required = artifact.need in (
            SupportNeed.REQUIRED,
            SupportNeed.SNAPSHOT_SUBSTITUTABLE,
        )
        observed_types = graph.get(item.topic, ())
        if not observed_types:
            detail = (
                f"{item.topic} is not on the observed graph; "
                + (
                    "a REQUIRED support topic that is missing at run time is a "
                    "refusal — the bag it would have completed cannot certify"
                    if required
                    else "recorded-opportunistic: absence is a finding, not a fault"
                )
            )
            status = SupportTopicStatus.ABSENT
            refusal = required
        elif item.message_type not in observed_types:
            detail = (
                f"{item.topic} is on the graph as {list(observed_types)} but the "
                f"plan records it as {item.message_type}; a type mismatch is "
                f"affirmative evidence of misconfiguration and refuses regardless "
                f"of need"
            )
            status = SupportTopicStatus.TYPE_MISMATCH
            refusal = True
        else:
            detail = f"{item.topic} observed with the declared type"
            status = SupportTopicStatus.PRESENT
            refusal = False
        checks.append(
            SupportTopicCheck(
                support_id=item.support_id,
                topic=item.topic,
                need=artifact.need.value,
                expected_type=item.message_type,
                observed_types=observed_types,
                status=status,
                refusal=refusal,
                detail=detail,
            )
        )
        if refusal:
            refusals.append(detail)
        elif status is SupportTopicStatus.ABSENT:
            findings.append(detail)
    return SupportReconciliation(
        checks=tuple(checks), refusals=tuple(refusals), findings=tuple(findings)
    )


def reconcile_support_topics_or_raise(
    observed: str | Mapping[str, Sequence[str]],
    *,
    support_topics: Sequence[RecordedTopic] = SUPPORT_TOPICS,
) -> SupportReconciliation:
    """The gate form: raise on any refusal, listing every one."""

    result = reconcile_support_topics(observed, support_topics=support_topics)
    if not result.ok:
        raise PreflightError(
            f"support-artifact reconciliation refused "
            f"({len(result.refusals)} refusal(s)): " + " | ".join(result.refusals)
        )
    return result


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Everything preflight saw. PS-D's attestation is built from exactly this."""

    observations: tuple[Observation, ...]
    channels: tuple[ChannelProbe, ...]
    findings: tuple[Finding, ...] = ()
    window_s: float = DEFAULT_WINDOW_S
    #: The operator's rest attestation for this window, if one was made. ``None``
    #: is the default and it keeps every rest-dependent rule UNKNOWN.
    rest: RestPeriod | None = None
    #: ---- CARD SENSE-1 ---- The three mount-day channels. Its own field, with
    #: an empty default, because a readiness row is neither an ``Observation``
    #: (the attestation refuses keys it does not know) nor a 29th channel probe
    #: (the enumeration is the matrix). Empty means "not probed", which every
    #: caller that predates this card gets.
    mount_readiness: tuple[MountChannelRow, ...] = ()

    def __post_init__(self) -> None:
        keys = [obs.key for obs in self.observations]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ProbeContractError(f"duplicate observation keys: {duplicates}")
        ids = [probe.channel_id for probe in self.channels]
        dup_channels = sorted({cid for cid in ids if ids.count(cid) > 1})
        if dup_channels:
            raise ProbeContractError(f"duplicate channel probes: {dup_channels}")

    @property
    def by_key(self) -> Mapping[str, Observation]:
        return {obs.key: obs for obs in self.observations}

    @property
    def by_channel(self) -> Mapping[str, ChannelProbe]:
        return {probe.channel_id: probe for probe in self.channels}

    def observation(self, key: str) -> Observation | None:
        return self.by_key.get(key)

    def channels_with_status(self, status: ProbeStatus) -> tuple[ChannelProbe, ...]:
        return tuple(probe for probe in self.channels if probe.status is status)

    @property
    def plausibility_counts(self) -> Mapping[PlausibilityVerdict, int]:
        counts = {verdict: 0 for verdict in PlausibilityVerdict}
        for probe in self.channels:
            counts[probe.plausibility_verdict] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PREFLIGHT_SCHEMA,
            "window_s": self.window_s,
            "rest_period": None if self.rest is None else self.rest.evidence,
            "observations": [obs.to_dict() for obs in self.observations],
            "channels": [probe.to_dict() for probe in self.channels],
            "findings": [finding.to_dict() for finding in self.findings],
            # ---- CARD SENSE-1 ---- additive; a reader that predates this card
            # ignores it, and the schema name does not move for a new key.
            "mount_readiness": [row.to_dict() for row in self.mount_readiness],
        }


def run_preflight(
    *,
    reader_factory: ChannelReaderFactory = default_reader_factory,
    window_s: float = DEFAULT_WINDOW_S,
    configured_rates: Mapping[str, float] | None = None,
    storage_path: Path | str | None = None,
    robot_reader: DeviceReader | None = None,
    builtin_lidar_reader: DeviceReader | None = None,
    builtin_lidar_operator: OperatorObservation | None = None,
    d455_reader: DeviceReader | None = None,
    l2_reader: DeviceReader | None = None,
    config_path: Path | str = ROBOT_CONFIG,
    net_class_dir: Path | str = "/sys/class/net",
    environ: Mapping[str, str] | None = None,
    tegra_release: Path | str = "/etc/nv_tegra_release",
    device_tree_model: Path | str = "/proc/device-tree/model",
    channels: Sequence[Channel] = CHANNELS,
    clock: Callable[[], int] = time.monotonic_ns,
    rest_period: RestPeriod | None = None,
    # ---- CARD SENSE-1 ---- injectable whole, the way every other hardware
    # seam here is: a test names the three rows it wants and no socket is bound.
    mount_readiness: Sequence[MountChannelRow] | None = None,
) -> PreflightReport:
    """Probe everything, refuse nothing, decide nothing.

    Every argument that reaches hardware is injectable, which is how the seeded
    failures in ``tests/test_capture_preflight.py`` drive a spoofed firmware
    version or a stalled channel without a robot. The defaults reach for real
    hardware and, on a box without any, produce a complete ABSENT report.
    """

    observations: list[Observation] = []
    findings: list[Finding] = []
    observations.extend(probe_host())
    observations.extend(probe_robot_identity(robot_reader))
    lidar_obs, lidar_findings = probe_builtin_lidar(builtin_lidar_reader, builtin_lidar_operator)
    observations.extend(lidar_obs)
    findings.extend(lidar_findings)
    net_obs, net_findings = probe_network(
        config_path=config_path, net_class_dir=net_class_dir, environ=environ
    )
    observations.extend(net_obs)
    findings.extend(net_findings)
    observations.extend(probe_d455(d455_reader))
    observations.extend(probe_l2(l2_reader))
    observations.extend(
        probe_jetpack(tegra_release=tegra_release, device_tree_model=device_tree_model)
    )
    observations.extend(probe_free_disk(storage_path if storage_path is not None else Path.cwd()))

    probes = probe_all_channels(
        reader_factory=reader_factory,
        window_s=window_s,
        configured_rates=configured_rates,
        channels=channels,
        clock=clock,
        rest=rest_period,
    )
    findings.extend(_channel_findings(probes, channels))
    findings.extend(_plausibility_findings(probes, channels))
    findings.extend(cross_check_imus(probes, channels, rest=rest_period))
    # ---- CARD SENSE-1 ---- last, and after the matrix, because it is the row
    # an operator reads FIRST: it says which of the three things being bolted on
    # this host can already take data from.
    rows = tuple(probe_mount_readiness()) if mount_readiness is None else tuple(mount_readiness)
    return PreflightReport(
        observations=tuple(observations),
        channels=probes,
        findings=tuple(sorted(findings, key=lambda f: (f.severity.rank, f.code))),
        window_s=window_s,
        rest=rest_period,
        mount_readiness=rows,
    )


#: What PS-A's ``Criticality`` costs the session, in finding severity. CRITICAL
#: is "the session did not achieve the thing it exists for" and so is BLOCKING;
#: OPPORTUNISTIC is "record if present, absence costs nothing" and so is a NOTE.
#: The mapping is taken from ``capture/channels.py``'s own docstrings rather than
#: re-judged here — PS-D does not get a second opinion on PS-A's table.
_CRITICALITY_SEVERITY = {
    Criticality.CRITICAL: FindingSeverity.BLOCKING,
    Criticality.IMPORTANT: FindingSeverity.MAJOR,
    Criticality.OPPORTUNISTIC: FindingSeverity.NOTE,
}


def _channel_findings(
    probes: Sequence[ChannelProbe], channels: Sequence[Channel]
) -> tuple[Finding, ...]:
    """One finding per critical channel that is not PRESENT, plus degradations."""

    matrix = {entry.channel_id: entry for entry in channels}
    findings: list[Finding] = []
    for probe in probes:
        entry = matrix.get(probe.channel_id)
        if entry is None:
            continue
        if probe.status is ProbeStatus.DEGRADED:
            fraction = probe.rate_deficit_fraction
            findings.append(
                Finding(
                    code="CHANNEL_DEGRADED",
                    severity=_CRITICALITY_SEVERITY[entry.criticality],
                    detail=(
                        f"{probe.channel_id} ({entry.criticality.value}) is DEGRADED: "
                        f"{probe.rate_assessment.value}"
                        + (f", observed/expected = {fraction:.3f}" if fraction is not None else "")
                        + f", longest silence {(probe.max_gap_ns or 0) / 1e9:.3f} s"
                    ),
                )
            )
            continue
        if probe.status is ProbeStatus.ABSENT:
            # The matrix already said the XVF3800 is in the post, so its absence
            # is a NOTE however it is ranked; everything else is ranked by what
            # PS-A says its absence costs the session.
            severity = (
                FindingSeverity.NOTE
                if entry.presence is ChannelPresence.AWAITING_HARDWARE
                else _CRITICALITY_SEVERITY[entry.criticality]
            )
            findings.append(
                Finding(
                    code="CHANNEL_ABSENT",
                    severity=severity,
                    detail=(
                        f"{probe.channel_id} ({entry.criticality.value}, matrix says "
                        f"{entry.presence.value}) is ABSENT: {probe.absence.value if probe.absence else '?'}"
                        f" — {probe.absence_detail}"
                        + (f" REMEDY: {probe.remedy}" if probe.remedy else "")
                    ),
                )
            )
            continue
        if probe.rate_assessment in {
            RateAssessment.UNASSESSED_NO_EXPECTATION,
            RateAssessment.UNASSESSED_WINDOW_TOO_SHORT,
        } and entry.criticality is Criticality.CRITICAL:
            findings.append(
                Finding(
                    code="CRITICAL_RATE_UNASSESSED",
                    severity=FindingSeverity.MAJOR,
                    detail=(
                        f"{probe.channel_id} is PRESENT but its rate is "
                        f"{probe.rate_assessment.value}; a critical channel whose delivery "
                        f"rate nobody can assess is not a channel we can budget for "
                        f"(supply --rate {probe.channel_id}=HZ or lengthen the window)"
                    ),
                )
            )
    return tuple(findings)


# ---------------------------------------------------------------------------
# Plausibility findings and the four-IMU cross-check
# ---------------------------------------------------------------------------

#: Rule ids that report the STRUCTURE of the run rather than a sensor. They are
#: UNKNOWN because no rule applied or nothing arrived, not because a sensor is
#: suspect, so they are reported in aggregate instead of once per channel.
_RULE_NO_RULE_DEFINED = "channel.no_rule_defined"
_RULE_NO_MESSAGE = "channel.no_message_received"
_RULE_ASSESSOR_RAISED = "channel.assessor_raised"
_RULE_NO_MEASUREMENT_SUFFIX = ".no_measurement"

#: The two rules whose failure is unrecoverable after powerdown, hoisted into
#: their own finding code so nobody has to read a rule list to see it.
_DESKEW_RULES = ("point_cloud.per_point_time_field", "point_cloud.ring_field")


def _plausibility_findings(
    probes: Sequence[ChannelProbe], channels: Sequence[Channel]
) -> tuple[Finding, ...]:
    """Surface every implausible channel — and never block on one.

    Severity is capped at MAJOR **on purpose**. BLOCKING is the lane that drives
    :class:`SessionVerdict.DEGRADE_MMP`, i.e. *record nothing*, and PS-J's card
    forbids exactly that outcome: "a failed plausibility check must never silence
    a recording". MAJOR is the lane ``attest.HardwareAttestationV1.advisories``
    documents as "never hidden, decided at the go/no-go", which is where a
    suspect-but-recorded channel belongs.
    """

    matrix = {entry.channel_id: entry for entry in channels}
    findings: list[Finding] = []
    unassessed: list[str] = []
    unruled: list[str] = []
    for probe in probes:
        entry = matrix.get(probe.channel_id)
        ruling = probe.plausibility
        if entry is None or ruling is None:
            continue
        if _RULE_NO_RULE_DEFINED in ruling.unknown_rules:
            unruled.append(probe.channel_id)
        deskew = [
            check
            for check in ruling.checks
            if check.rule in _DESKEW_RULES and check.verdict is PlausibilityVerdict.FAIL
        ]
        if deskew:
            findings.append(
                Finding(
                    code="POINTCLOUD_NO_DESKEW_FIELDS",
                    severity=FindingSeverity.MAJOR,
                    detail=(
                        f"{probe.channel_id}: fields[] = "
                        f"{list(ruling.point_cloud_fields)}. "
                        + " ".join(check.detail for check in deskew)
                        + " Record the cloud anyway — but this is only discoverable while "
                        "the rig is powered, so decide NOW whether a driver setting can "
                        "add the field."
                    ),
                )
            )
        other = [
            check
            for check in ruling.checks
            if check.verdict is PlausibilityVerdict.FAIL and check.rule not in _DESKEW_RULES
        ]
        if other:
            findings.append(
                Finding(
                    code="CHANNEL_IMPLAUSIBLE",
                    severity=FindingSeverity.MAJOR,
                    detail=(
                        f"{probe.channel_id} ({entry.criticality.value}) delivered "
                        f"{probe.messages_received} message(s) and is {probe.status.value}, "
                        f"but what arrived is not physically possible: "
                        + " | ".join(f"{c.rule}: {c.detail}" for c in other)
                        + ". The channel is RECORDED REGARDLESS with this verdict in the "
                        "sidecar — a suspect channel is still evidence."
                    ),
                )
            )
        if _RULE_ASSESSOR_RAISED in ruling.unknown_rules:
            findings.append(
                Finding(
                    code="PLAUSIBILITY_ASSESSOR_FAILED",
                    severity=FindingSeverity.MAJOR,
                    detail=(
                        f"{probe.channel_id}: the plausibility assessor itself failed, so "
                        f"this channel is unruled. "
                        + (ruling.check(_RULE_ASSESSOR_RAISED) or ruling.checks[0]).detail
                    ),
                )
            )
        structural = {_RULE_NO_RULE_DEFINED, _RULE_NO_MESSAGE, _RULE_ASSESSOR_RAISED}
        unknowns = [
            rule
            for rule in ruling.unknown_rules
            if rule not in structural and not rule.endswith(_RULE_NO_MEASUREMENT_SUFFIX)
        ]
        if any(rule.endswith(_RULE_NO_MEASUREMENT_SUFFIX) for rule in ruling.unknown_rules):
            unassessed.append(probe.channel_id)
        if unknowns:
            findings.append(
                Finding(
                    code="CHANNEL_PLAUSIBILITY_UNKNOWN",
                    severity=FindingSeverity.NOTE,
                    detail=(
                        f"{probe.channel_id}: "
                        + " | ".join(
                            f"{rule}: {(ruling.check(rule) or ruling.checks[0]).detail}"
                            for rule in unknowns
                        )
                    ),
                )
            )
    if unassessed:
        findings.append(
            Finding(
                code="PLAUSIBILITY_NOT_ASSESSED",
                severity=FindingSeverity.NOTE,
                detail=(
                    f"{len(unassessed)} channel(s) have physical-plausibility rules but "
                    f"their readers supplied no physical measurement, so nothing was ruled "
                    f"on: {sorted(unassessed)}. On this dev box that is the expected and "
                    f"correct outcome; on the Orin it means the live reader is not "
                    f"extracting the quantities the rules need."
                ),
            )
        )
    if unruled:
        findings.append(
            Finding(
                code="PLAUSIBILITY_NO_RULE",
                severity=FindingSeverity.NOTE,
                detail=(
                    f"{len(unruled)} channel(s) have NO physical-plausibility rule at all, "
                    f"so nothing about their contents is asserted: {sorted(unruled)}. "
                    f"Rules are selected from the matrix's declared message_type; this line "
                    f"exists so the coverage gap is visible rather than silent."
                ),
            )
        )
    return tuple(findings)


@dataclass(frozen=True, slots=True)
class ImuCrossCheck:
    """The four IMUs, ruled against each other.

    There are four independent IMUs on this rig and at rest they should all
    report the same ``|accel|``. That makes them the cheapest available oracle
    for each other: three units at 9.81 and one at -2.17e24 identifies the
    broken one without any calibration, any documentation, or any second session.
    """

    unit_means: tuple[tuple[str, float], ...]
    units_enumerated: int
    verdict: PlausibilityVerdict
    summary: str
    findings: tuple[Finding, ...] = ()


def cross_check_imus(
    probes: Sequence[ChannelProbe],
    channels: Sequence[Channel] = CHANNELS,
    *,
    rest: RestPeriod | None = None,
) -> tuple[Finding, ...]:
    """The cross-check's findings. See :func:`imu_cross_check` for the evidence."""

    return imu_cross_check(probes, channels, rest=rest).findings


def imu_cross_check(
    probes: Sequence[ChannelProbe],
    channels: Sequence[Channel] = CHANNELS,
    *,
    rest: RestPeriod | None = None,
) -> ImuCrossCheck:
    """Group every IMU stream by physical unit and compare their mean ``|accel|``.

    Only meaningful at rest, so without a declared rest period this reports
    UNKNOWN rather than comparing numbers that have no reason to agree. The
    per-channel sensor-range rule is what catches a 1e24 reading in a moving
    take; this is what catches a unit that is merely *wrong*.
    """

    imu_channels = [entry for entry in channels if ChannelClass.IMU in classify_channel(entry)]
    enumerated = len({imu_unit_id(entry) for entry in imu_channels})
    by_unit: dict[str, list[float]] = {}
    for probe in probes:
        ruling = probe.plausibility
        if ruling is None or ruling.imu_unit_id is None:
            continue
        if ruling.accel_magnitude_mean_mps2 is None:
            continue
        by_unit.setdefault(ruling.imu_unit_id, []).append(ruling.accel_magnitude_mean_mps2)
    means = tuple(
        sorted((unit, math.fsum(values) / len(values)) for unit, values in by_unit.items())
    )
    table = ", ".join(f"{unit} |accel|={value:.6g} m/s^2" for unit, value in means)

    if rest is None:
        return ImuCrossCheck(
            unit_means=means,
            units_enumerated=enumerated,
            verdict=PlausibilityVerdict.UNKNOWN,
            summary=(
                f"{enumerated} independent IMU unit(s) enumerated, {len(means)} reported a "
                f"mean |accel|; no rest period was declared (--at-rest OPERATOR) so they "
                f"have no reason to agree and no comparison is made"
            ),
            findings=(
                Finding(
                    code="IMU_CROSS_CHECK_UNAVAILABLE",
                    severity=FindingSeverity.NOTE,
                    detail=(
                        f"the four-IMU cross-check needs a declared rest period; none was "
                        f"given. {enumerated} unit(s) enumerated from the matrix"
                        + (f"; observed: {table}" if table else "")
                    ),
                ),
            ),
        )
    if len(means) < 2:
        return ImuCrossCheck(
            unit_means=means,
            units_enumerated=enumerated,
            verdict=PlausibilityVerdict.UNKNOWN,
            summary=(
                f"{len(means)} of {enumerated} IMU unit(s) reported a mean |accel|; a "
                f"cross-check needs at least two witnesses"
            ),
            findings=(
                Finding(
                    code="IMU_CROSS_CHECK_UNAVAILABLE",
                    severity=FindingSeverity.NOTE,
                    detail=(
                        f"{rest.evidence}, but only {len(means)} of {enumerated} IMU "
                        f"unit(s) produced a mean |accel|"
                        + (f": {table}" if table else "")
                        + " — the units cannot check each other"
                    ),
                ),
            ),
        )

    values = [value for _, value in means]
    spread = max(values) - min(values)
    if spread <= IMU_CROSS_CHECK_TOLERANCE_MPS2:
        return ImuCrossCheck(
            unit_means=means,
            units_enumerated=enumerated,
            verdict=PlausibilityVerdict.PASS,
            summary=(
                f"{len(means)} of {enumerated} IMU unit(s) agree within {spread:.4g} m/s^2 "
                f"(tolerance {IMU_CROSS_CHECK_TOLERANCE_MPS2}): {table}"
            ),
        )
    median = _percentile(values, 0.5)
    outlier, outlier_value = max(means, key=lambda item: abs(item[1] - median))
    return ImuCrossCheck(
        unit_means=means,
        units_enumerated=enumerated,
        verdict=PlausibilityVerdict.FAIL,
        summary=(
            f"{len(means)} of {enumerated} IMU unit(s) DISAGREE by {spread:.6g} m/s^2 "
            f"(tolerance {IMU_CROSS_CHECK_TOLERANCE_MPS2}): {table}"
        ),
        findings=(
            Finding(
                code="IMU_CROSS_CHECK_DISAGREEMENT",
                severity=FindingSeverity.MAJOR,
                detail=(
                    f"{rest.evidence}, so every IMU should read |accel| ~ {GRAVITY_MPS2} "
                    f"m/s^2. They do not: spread {spread:.6g} m/s^2 across {len(means)} "
                    f"unit(s) ({table}). Furthest from the median ({median:.6g}) is "
                    f"{outlier} at {outlier_value:.6g} m/s^2 — treat that unit as the "
                    f"suspect and record it anyway."
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Human-readable output
# ---------------------------------------------------------------------------

_STATUS_MARK = {
    ProbeStatus.PRESENT: "PRESENT ",
    ProbeStatus.DEGRADED: "DEGRADED",
    ProbeStatus.ABSENT: "ABSENT  ",
}

_PLAUSIBILITY_MARK = {
    PlausibilityVerdict.PASS: "PASS   ",
    PlausibilityVerdict.FAIL: "FAIL   ",
    PlausibilityVerdict.UNKNOWN: "UNKNOWN",
}


def format_plausibility_block(
    report: PreflightReport, channels: Sequence[Channel] = CHANNELS
) -> list[str]:
    """The physical-plausibility section of the run header.

    Printed for every channel, every run, whatever the verdict — the point of the
    card is that "bytes arrived" stopped being the whole health story, and a
    verdict an operator has to ask for is a verdict nobody reads at 08:00.
    """

    lines = [
        "PHYSICAL PLAUSIBILITY — a channel is not healthy because bytes arrive",
        (
            f"  rest period: {report.rest.evidence}"
            if report.rest is not None
            else "  rest period: NOT DECLARED (--at-rest OPERATOR) — every rest-dependent "
            "rule is UNKNOWN, never PASS"
        ),
    ]
    cross = imu_cross_check(report.channels, channels, rest=report.rest)
    lines.append(f"  IMU cross-check [{_PLAUSIBILITY_MARK[cross.verdict].strip()}]: {cross.summary}")
    counts = report.plausibility_counts
    lines.append(
        "  "
        + "  ".join(f"{verdict.value}={counts[verdict]}" for verdict in PlausibilityVerdict)
    )
    failed = [
        probe.channel_id
        for probe in report.channels
        if probe.plausibility_verdict is PlausibilityVerdict.FAIL
    ]
    lines.append(
        f"  IMPLAUSIBLE: {', '.join(failed)} — RECORD THEM ANYWAY, a suspect channel is "
        f"still evidence"
        if failed
        else "  IMPLAUSIBLE: none"
    )
    id_width = max((len(p.channel_id) for p in report.channels), default=10)
    for probe in report.channels:
        ruling = probe.plausibility
        lines.append(
            f"  [{_PLAUSIBILITY_MARK[probe.plausibility_verdict]}] "
            f"{probe.channel_id:<{id_width}} "
            + (
                f"{ruling.samples_assessed} sample(s), classes "
                f"{', '.join(ruling.classes) or '(none)'}"
                if ruling is not None
                else "the plausibility layer did not run for this probe"
            )
        )
        if ruling is None:
            continue
        for check in ruling.checks:
            lines.append(f"      {check.verdict.value.upper():<7} {check.rule}: {check.detail}")
        for note in ruling.notes:
            lines.append(f"      note    {note}")
    return lines


def format_report(report: PreflightReport, channels: Sequence[Channel] = CHANNELS) -> str:
    """The report an operator reads at 08:00 with a dog on the bench."""

    matrix = {entry.channel_id: entry for entry in channels}
    lines: list[str] = [
        f"PARCEL CAPTURE PREFLIGHT — {PREFLIGHT_SCHEMA}",
        "=" * 78,
        "OBSERVATIONS",
    ]
    width = max((len(obs.key) for obs in report.observations), default=10)
    for obs in report.observations:
        shown = "ABSENT" if obs.value is None else str(obs.value)
        lines.append(f"  {obs.key:<{width}}  {shown}")
        lines.append(f"  {'':<{width}}    [{obs.kind.value}] {obs.evidence}")
        if obs.remedy:
            lines.append(f"  {'':<{width}}    remedy: {obs.remedy}")
    lines.extend(format_mount_readiness(report.mount_readiness))
    lines.extend(["", f"CHANNELS ({len(report.channels)} probed, window {report.window_s:.2f}s)"])
    id_width = max((len(p.channel_id) for p in report.channels), default=10)
    for probe in report.channels:
        entry = matrix.get(probe.channel_id)
        crit = entry.criticality.value if entry else "?"
        rate = probe.observed_rate_hz
        rate_text = "     -  " if rate is None else f"{rate:7.2f}Hz"
        lines.append(
            f"  [{_STATUS_MARK[probe.status]}] {probe.channel_id:<{id_width}} {rate_text} "
            f"{probe.rate_assessment.value:<28} ({crit}) "
            f"plausibility={probe.plausibility_verdict.value.upper()}"
        )
        lines.append(f"      {probe.evidence}")
        if probe.absence is not None:
            lines.append(f"      why: {probe.absence.value} — {probe.absence_detail}")
        if probe.remedy:
            lines.append(f"      remedy: {probe.remedy}")
    counts = {status: len(report.channels_with_status(status)) for status in ProbeStatus}
    lines.extend(
        [
            "",
            "  ".join(f"{status.value}={counts[status]}" for status in ProbeStatus),
            "",
        ]
    )
    lines.extend(format_plausibility_block(report, channels))
    lines.extend(["", "FINDINGS"])
    if not report.findings:
        lines.append("  (none)")
    for finding in report.findings:
        lines.append(f"  [{finding.severity.value:>8}] {finding.code}: {finding.detail}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_rate_overrides(values: Sequence[str]) -> dict[str, float]:
    """``--rate d455.color=30`` pairs. A malformed pair is a refusal."""

    rates: dict[str, float] = {}
    for raw in values:
        name, sep, number = raw.partition("=")
        if not sep or not name.strip():
            raise ProbeContractError(f"--rate expects CHANNEL_ID=HZ, got {raw!r}")
        try:
            hz = float(number)
        except ValueError as exc:
            raise ProbeContractError(f"--rate {raw!r}: {number!r} is not a number") from exc
        if math.isnan(hz) or math.isinf(hz) or not hz > 0.0:
            raise ProbeContractError(f"--rate {raw!r}: rate must be finite and positive")
        rates[name.strip()] = hz
    return rates


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    """Shared CLI surface; :mod:`scripts.parcel_capture.attest` extends it."""

    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--window", type=float, default=DEFAULT_WINDOW_S, help="observation window per channel, s"
    )
    parser.add_argument(
        "--rate", action="append", default=[], metavar="CHANNEL_ID=HZ",
        help="expected rate for a CONFIGURED channel (repeatable)",
    )
    parser.add_argument(
        "--storage", default=None, help="recording destination whose free space is measured"
    )
    parser.add_argument("--json", action="store_true", help="emit the machine-readable report")
    parser.add_argument(
        "--builtin-lidar-model", default=None,
        help="model read off the built-in LiDAR label (requires --operator and --photo)",
    )
    parser.add_argument("--operator", default=None, help="who read the label")
    parser.add_argument("--photo", default=None, help="session/PHOTO_LIST.md id, e.g. P02")
    parser.add_argument(
        "--at-rest", default=None, metavar="OPERATOR",
        help=(
            "name of the operator attesting the rig was STATIONARY for this window. "
            "Without it every rest-dependent plausibility rule (|accel| = 9.81 +/- 1.0, "
            "|gyro| < 0.05, the four-IMU cross-check) reports UNKNOWN, never PASS"
        ),
    )
    parser.add_argument(
        "--at-rest-note", default=None,
        help="what the rig was doing during the rest window, for the record",
    )
    return parser


#: What ``--reader`` may name. ``auto`` is the live ingest adapters with the
#: per-transport refusal as a fallback; ``none`` is the refusal factory alone,
#: which is a dependency census rather than a probe and must be asked for.
READER_CHOICES = ("auto", "none")


def add_reader_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add the reader-selection flags to a preflight parser.

    Deliberately **not** part of :func:`build_arg_parser`. That parser is shared
    with :mod:`scripts.parcel_capture.attest`, which does not resolve these flags
    and is not this card's file; advertising a flag a command ignores is the same
    defect as naming a flag that does not exist, one step further along.
    """

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--reader", choices=READER_CHOICES, default="auto",
        help=(
            "auto (default): read through the live ingest adapters "
            "(scripts/parcel_capture/ingest/), falling back to a refusal naming the "
            "missing dependency; none: refuse on every transport without attempting a "
            "read, which reports what is missing and proves nothing about presence"
        ),
    )
    group.add_argument(
        "--reader-module", default=None, metavar="MODULE:FACTORY",
        help=(
            "import MODULE and use its FACTORY attribute as the channel reader factory, "
            "overriding --reader. A spec that does not resolve is a refusal, never a "
            "silent fallback"
        ),
    )
    return parser


def reader_factory_from_args(args: argparse.Namespace) -> ChannelReaderFactory:
    """Which factory this invocation asked for. Never a silent default.

    A namespace with neither flag — every caller that built its parser with
    :func:`build_arg_parser` alone — gets :func:`default_reader_factory`, the
    live one, because a preflight that reaches for hardware is the point.
    """

    spec = getattr(args, "reader_module", None)
    if spec:
        return load_reader_factory(spec)
    if getattr(args, "reader", "auto") == "none":
        return unavailable_reader_factory
    return default_reader_factory


def operator_observation_from_args(args: argparse.Namespace) -> OperatorObservation | None:
    """All three of model/operator/photo, or none. Two out of three is a refusal."""

    supplied = [args.builtin_lidar_model, args.operator, args.photo]
    if not any(supplied):
        return None
    if not all(supplied):
        raise ProbeContractError(
            "--builtin-lidar-model requires --operator and --photo: an unattributed "
            "label reading is not evidence"
        )
    return OperatorObservation(
        value=args.builtin_lidar_model, operator=args.operator, photo_id=args.photo
    )


def rest_period_from_args(args: argparse.Namespace) -> RestPeriod | None:
    """``--at-rest OPERATOR``, or no rest period at all.

    A note without a name is refused: "the rig was still" with nobody attached to
    it is the kind of claim that turns into a PASS nobody can defend six months
    from now.
    """

    attested_by = getattr(args, "at_rest", None)
    note = getattr(args, "at_rest_note", None)
    if attested_by is None:
        if note:
            raise ProbeContractError(
                "--at-rest-note requires --at-rest OPERATOR: an unattributed rest claim "
                "is not evidence, and it is the only thing standing behind the "
                "9.81 +/- 1.0 m/s^2 band"
            )
        return None
    return RestPeriod(attested_by=attested_by, note=note or "")


def main(argv: Sequence[str] | None = None) -> int:
    """Probe and report. Exit 0 only when every critical channel is PRESENT.

    Never raises: a refusal is printed and exit-coded, because a traceback on a
    session morning is a tool telling an operator to debug it instead of the dog.
    """

    parser = add_reader_arguments(build_arg_parser(__doc__ or "parcel capture preflight"))
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        rates = parse_rate_overrides(args.rate)
        operator = operator_observation_from_args(args)
        # Passed explicitly rather than left to the signature default: the
        # defect this closes was main() never naming a factory at all, and a
        # default is not a wiring an operator or a test can see.
        report = run_preflight(
            reader_factory=reader_factory_from_args(args),
            window_s=float(args.window),
            configured_rates=rates,
            storage_path=args.storage,
            builtin_lidar_operator=operator,
            rest_period=rest_period_from_args(args),
        )
    except PreflightError as exc:
        print(f"PREFLIGHT REFUSED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - never a traceback on a session morning
        print(f"PREFLIGHT REFUSED (unexpected {type(exc).__name__}): {exc}", file=sys.stderr)
        return 2

    print(format_report(report))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    blocking = [f for f in report.findings if f.severity is FindingSeverity.BLOCKING]
    if blocking:
        print(
            f"\nRESULT: NOT READY — {len(blocking)} blocking finding(s). "
            f"See scrum/20260813/task_1/session/STAGE0_RUN_SHEET.md §6 (DEGRADE-MMP).",
            file=sys.stderr,
        )
        return 1
    print("\nRESULT: every critical channel PRESENT and no blocking finding.")
    return 0


__all__ = [
    "ACCEL_REST_TOLERANCE_MPS2",
    "ACCEL_SENSOR_CEILING_MPS2",
    "ASOUND_CARDS",  # CARD SENSE-1
    "BUILTIN_LIDAR_CLAIMS",
    "CELL_VOLTAGE_MAX_V",
    "CELL_VOLTAGE_MIN_V",
    "DDS_DOMAIN_CONFIG_PATHS",
    "DEFAULT_WINDOW_S",
    "DESKEW_RING_FIELD_NAMES",
    "DESKEW_TIME_FIELD_NAMES",
    "FOOT_FORCE_CHANNELS",
    "FOOT_FORCE_COUNT_MAX",
    "FOOT_FORCE_COUNT_MIN",
    "FOOT_FORCE_MIN_SAMPLES",
    "GRAVITY_MPS2",
    "GYRO_REST_CEILING_RPS",
    "GYRO_SENSOR_CEILING_RPS",
    "IMAGE_DEGENERATE_FRACTION",
    "IMU_CROSS_CHECK_TOLERANCE_MPS2",
    "L4T_TO_JETPACK",
    "MAX_GAP_PERIODS",
    "MID360_LISTEN_S",  # CARD SENSE-1
    "MIN_RATE_SAMPLES",
    "PACK_CONSISTENCY_TOLERANCE_FRACTION",
    "PACK_CONSISTENCY_TOLERANCE_V",
    "PACK_VOLTAGE_CEILING_V",
    "PLACEHOLDER_MARKERS",
    "POINT_RANGE_CEILING_M",
    "PREFLIGHT_SCHEMA",
    "RATE_DEFICIT_FLOOR",
    "RATE_EXCESS_CEILING",
    "READER_CHOICES",
    "READER_MODULE_FLAG_HELP",
    "REPO_ROOT",
    "ROBOT_CONFIG",
    "ROBOT_NIC_CONFIG_PATHS",
    "AbsenceReason",
    "ChannelClass",
    "ChannelPlausibility",
    "ChannelProbe",
    "ConfigScalar",
    "DeviceReader",
    "EvidenceKind",
    "Finding",
    "FindingSeverity",
    "FootForceSample",
    "ImageSample",
    "ImuCrossCheck",
    "ImuSample",
    "ImuStreamKind",
    "MountChannelRow",  # CARD SENSE-1
    "MountReadiness",  # CARD SENSE-1
    "Observation",
    "OperatorObservation",
    "PhysicalSample",
    "PlausibilityCheck",
    "PlausibilityVerdict",
    "PointCloudSample",
    "PowerSample",
    "PreflightError",
    "PreflightReport",
    "ProbeContractError",
    "ProbeStatus",
    "RateAssessment",
    "RestPeriod",
    "SampleReceipt",
    "TransportUnavailableError",
    "add_reader_arguments",
    "assess_plausibility",
    "build_arg_parser",
    "classify_channel",
    "cross_check_imus",
    "default_reader_factory",
    "expected_rate_for",
    "format_mount_readiness",  # CARD SENSE-1
    "format_plausibility_block",
    "format_report",
    "imu_cross_check",
    "imu_stream_kind",
    "imu_unit_id",
    "load_reader_factory",
    "main",
    "operator_observation_from_args",
    "parse_rate_overrides",
    "probe_all_channels",
    "probe_builtin_lidar",
    "probe_channel",
    "probe_d455",
    "probe_d455_mount",  # CARD SENSE-1
    "probe_free_disk",
    "probe_host",
    "probe_jetpack",
    "probe_l2",
    "probe_mid360_udp",  # CARD SENSE-1
    "probe_mount_readiness",  # CARD SENSE-1
    "probe_network",
    "probe_robot_identity",
    "probe_xvf3800_mount",  # CARD SENSE-1
    "reader_factory_from_args",
    "rest_period_from_args",
    "run_preflight",
    "scan_config_scalars",
    "unavailable_reader_factory",
]


#: Canonical import name of this module. Used only by the ``-m`` alias below.
_CANONICAL_MODULE = "scripts.parcel_capture.preflight"


if __name__ == "__main__":
    # ``python -m scripts.parcel_capture.preflight`` executes this file as
    # ``__main__``. The ingest package then imports ``..preflight`` BY NAME and
    # gets a SECOND module object, whose ``SampleReceipt`` is a different class
    # from the one ``probe_channel`` type-checks against — so every receipt a
    # live adapter produced would be rejected as
    # ``PROBE_CONTRACT_VIOLATION: reader yielded SampleReceipt, not a
    # SampleReceipt`` and every channel would read ABSENT. Measured on this box
    # the moment ``--reader-module`` first delivered a receipt through the ``-m``
    # entry point; on the Orin, with rclpy sourced and the dog publishing, it
    # would have done the same to all 23 served channels.
    #
    # Aliasing the running module under its canonical name before anything
    # imports it is the whole fix. ``setdefault`` so a caller who already
    # imported it normally keeps the copy they have.
    sys.modules.setdefault(_CANONICAL_MODULE, sys.modules[__name__])
    raise SystemExit(main())
