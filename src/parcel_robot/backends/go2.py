"""The physical ``SimulatorBackend`` for the Go2 EDU+. Card HW-2 (task_40).

``MujocoSocketBackend`` is the only ``SimulatorBackend`` in the tree and
``observe()`` is the runtime's ONE source of pose, scan and obstacle facts
(wave-3 design §4 row S1). On the dog there is no MuJoCo, so without this
module nothing starts. :class:`Go2Backend` is that backend, and it is an
**EYE**:

* pose from ``rt/sportmodestate`` — the ODOM position and yaw the existing
  ``control/unitree_sport.py:UnitreeSportStateSource`` already decodes,
  read-only, no lease, no controller;
* scan from HW-3's Mid-360 planar band (``parcel_robot.lidar``), copied across
  by the seam snippet in that package's docstring — **including its branch**:
  ``BandScan.ranges_m == ()`` means the sweep was not a scan and the
  ``SimObservation`` must publish the absence, so ``reactive_safety`` HOLDs
  instead of reading zero measurements as clear space;
* every motion method REFUSED (:class:`Go2MotionRefused`) until the native
  sole-writer gateway exists (``docs/MOTION.md``, design §5.5). Parcel does not
  command this robot from Python.

WHAT MAKES A SCAN BELIEVABLE HERE
---------------------------------
``backend="go2"`` on the observation is only a LABEL: ``core/input_health.py``
``evidence_origin`` stamps *every* ``SimObservation`` sample SIMULATION,
because the carrier type is the authority (board D-1), and HW-3's verifier
measured a real band scan latching ``SCAN: sim_fixture_forbidden`` under
:func:`~parcel_robot.core.input_health.requirements_requiring_physical_inputs`.
Authority therefore travels beside the observation on a TYPED source:
:attr:`Go2Backend.scan_evidence_source` is a
:class:`~parcel_robot.core.input_health.CommissionedScanSource`, and
``runtime.py:_evaluate_dispatch_input_health`` reads it instead of the
observation stamp when — and only when — it declares
``EvidenceOrigin.PHYSICAL``.

The origin is declared BY CONSTRUCTION, never by configuration:

* :class:`RecordedStage0Source` reads a file, so it declares ``REPLAY`` and
  carries the fixture's name. A replay still latches under a physical
  requirements table. That is the correct answer, and it is what the desktop
  measures.
* :class:`LiveGo2Sources` opens a DDS subscriber and a UDP socket, so it
  declares ``PHYSICAL``. It cannot be constructed without the vendor SDK, and
  it says which venv provides it.

WHAT MAKES A POSE BELIEVABLE HERE (card SENSE-1, scrum/20260823/task_3)
-----------------------------------------------------------------------
The same thing, one channel later. HW-2 gave SCAN the typed seam and said in
its own rows that POSE was not in that card; the ARCH-1 verdict's blocking
finding 4 is that the omission makes ``go2_edu_plus`` — a profile whose whole
point is ``safety.require_physical_inputs: true`` — unrunnable live, because a
real dog's pose latches ``POSE: sim_fixture_forbidden``.
:attr:`Go2Backend.pose_evidence_source` is the twin:
:class:`~parcel_robot.core.input_health.CommissionedPoseSource`, declared by
the same construction (live = PHYSICAL, recording = REPLAY, and a replayed pose
still latches under a physical requirements table).

AND TWO CLOCKS, NOT ONE (X04). ``observe()`` used to stamp pose and scan with a
single ``received_at`` read at the top of the tick. Both channels are BUFFERED
— ``latest()`` returns the last DDS sample when none has arrived since, and the
socket may have gone quiet — so one tick-clock stamp made a stale pose and a
stale scan look equally fresh for ever, and freshness is the whole of the
health join's staleness branch. Each datum now carries the clock that actually
took delivery: :attr:`~parcel_robot.core.input_health.PoseDatum.captured_at` is
the state sample's own host receipt, and
:attr:`~parcel_robot.core.input_health.ScanDatum.captured_at` is the host clock
read as the last datagram of the sweep came off the socket.
``SimObservation.timestamp`` is unchanged — it is the assembly clock and half
the tree reads it — so the two receipts ride the typed datums, which is where
the join reads ``captured_at`` from anyway.

No vendor SDK is imported at module scope anywhere in this file: the vendor
imports happen inside :class:`LiveGo2Sources`, and a fresh interpreter that
imports this module has no ``unitree_sdk2py``, ``mujoco`` or ``rclpy`` in
``sys.modules`` (measured, ``tests/test_hw2_go2_backend.py``). That is the
load-bearing claim -- design §3: the vendor SDK and ``rclpy`` must never share
a process, because CycloneDDS is process-global.

It also keeps out ``parcel_robot.core`` and ``parcel_robot.control``, and that
is load-bearing rather than tidy: ``backends/__init__.py`` imports this module
and the ``commissioning/`` package imports ``backends``, so a module-scope
``from parcel_robot.core.input_health import ...`` here drags
``brain``/``instructnav``/``navigation`` into the armed commissioning tool and
reddens W0-B's guard (measured — see the note in :meth:`Go2Backend.__init__`).
``EvidenceOrigin`` therefore comes from the leaf module card W0-A carved out
for exactly this purpose, and the two health types are imported where they are
used. ``socket`` still arrives, from the sibling ``backends.mujoco``, which has
always pulled ``sim_ipc``. This module runs on the Orin's CPython 3.10
unchanged (design §5.1).
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.lidar.band import (
    BandProfile,
    nearest_obstacle_from_scan,
    scan_from_frames,
    travel_bearing_rad,
)
from parcel_robot.lidar.livox_udp import LivoxDecodeError, LivoxPointFrame, parse_point_frame
from parcel_robot.models import Pose, VelocityCommand

from .base import OwnerTrack, RobotPose, SimObservation

if TYPE_CHECKING:  # pragma: no cover - typing only
    # NOT a module-scope import. `parcel_robot.control.models` cannot be
    # reached without executing `parcel_robot.control.__init__`, which pulls
    # `control.factory` -> ... -> `navigation.envs.metaurban_env` (numpy) and
    # `sim_ipc` (socket). Nothing about reading a Livox frame needs either, and
    # this module is the one that has to import on the Orin's motion venv.
    # `from __future__ import annotations` keeps every annotation below a
    # string, and the one runtime construction imports it inside the function.
    from parcel_robot.control.models import RobotMotionState
    from parcel_robot.core.input_health import PoseDatum, ScanDatum

#: The one sentence every refusal quotes. ``docs/MOTION.md`` is doctrine and
#: this module is not where it is revisited.
MOTION_CITATION = (
    "docs/MOTION.md: Parcel commands no autonomous motion on this robot until the "
    "native sole-writer gateway owns the DDS writer and stops on its own watchdog "
    "(wave-3 design §5.5, N28/N43). Commissioning steps go through "
    "`python -m parcel_robot.unitree_control run --arm`, never through a backend."
)

#: How many graded observations `Go2Backend` keeps a datum for. The join reads
#: the current tick's observation and, after an `observe()` exception, the
#: previous one; handler threads add a couple more in flight. Eight is generous
#: and bounded — an unbounded map keyed on observations leaks in a process that
#: runs for days.
GRADED_HISTORY = 8

#: The fixture schema this reader accepts. A v2 shape must not be read as a v1.
REPLAY_SCHEMA_V1 = "parcel.stage0_replay.v1"

#: Channel names inside a replay file. They are the DDS topic / device names, so
#: a recording made on the dog needs no translation table.
REPLAY_CHANNEL_STATE = "rt/sportmodestate"
REPLAY_CHANNEL_POINTS = "livox/mid360/points"


class Go2BackendError(RuntimeError):
    """Base class for everything this backend refuses."""


class Go2MotionRefused(Go2BackendError, NotImplementedError):
    """A motion method was called on an observe-only backend.

    ``NotImplementedError`` as well as ``Go2BackendError`` so a caller that
    already handles "this backend cannot do that" keeps working, and so the
    refusal cannot be mistaken for a transport error and retried.
    """


class Go2SdkUnavailable(Go2BackendError):
    """The live adapter was asked for on a host without the vendor SDK."""


class Go2StateUnavailable(Go2BackendError):
    """No ``rt/sportmodestate`` sample has arrived yet, so there is no pose.

    Raised rather than defaulted (verifier finding F2). ``RobotPose()`` is
    ``(0, 0, 0, 0)`` — a perfectly plausible pose at the origin, published
    under a FRESH timestamp, which the health join reads as present and fresh.
    The runtime's own ``except (OSError, RuntimeError, TypeError, ValueError)``
    around ``backend.observe()`` turns this into ``observation=None``, which is
    a HOLD: the honest answer to "where is the robot?" before the robot has
    said. This is the one field the backend's own rule — "an unfilled field is
    a field nothing measured" — cannot express by leaving it unfilled.
    """


class Go2ReplayError(Go2BackendError, ValueError):
    """A recorded fixture does not parse. Evidence that does not parse is not
    evidence, so it is refused rather than half-read."""


@dataclass(frozen=True)
class _StateSample:
    """One ``rt/sportmodestate`` sample, already in this tree's vocabulary."""

    state: RobotMotionState
    stamp_ns: int | None


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Go2ReplayError(f"{field} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise Go2ReplayError(f"{field} must be finite, got {number!r}")
    return number


def _floats(value: object, count: int, field: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise Go2ReplayError(f"{field} must be {count} numbers, got {value!r}")
    return tuple(_finite(item, f"{field}[{index}]") for index, item in enumerate(value))


def state_from_sport_mode_state(
    payload: object,
    *,
    received_at: float,
    sequence: int,
    velocity_frame: str = "odom",
    session_epoch: str = "",
) -> _StateSample:
    """A recorded ``SportModeState`` payload -> :class:`RobotMotionState`.

    The field names are the ones this tree's own DDS decoder writes
    (``scripts/parcel_capture/ingest/dds.py:decode_sport_mode_state``), so a
    recording made by the capture stack replays here without a translation
    table. The odom->body velocity rotation is
    ``control/unitree_sport.py:_on_message``'s, kept identical on purpose: the
    replay must not be a *different* decoder from the live one.
    """

    from parcel_robot.control.models import RobotMotionState

    if not isinstance(payload, dict):
        raise Go2ReplayError("sport_mode_state must be an object")
    position = _floats(payload.get("position"), 3, "position")
    odom_velocity = _floats(payload.get("velocity"), 3, "velocity")
    imu = payload.get("imu_state")
    if not isinstance(imu, dict):
        raise Go2ReplayError("sport_mode_state.imu_state must be an object")
    rpy = _floats(imu.get("rpy_rad"), 3, "imu_state.rpy_rad")
    yaw = rpy[2]
    if velocity_frame == "odom":
        cosine = math.cos(yaw)
        sine = math.sin(yaw)
        body_vx = cosine * odom_velocity[0] + sine * odom_velocity[1]
        body_vy = -sine * odom_velocity[0] + cosine * odom_velocity[1]
    elif velocity_frame == "base_link":
        body_vx = odom_velocity[0]
        body_vy = odom_velocity[1]
    else:
        raise Go2ReplayError("velocity_frame must be odom or base_link")
    foot_force = payload.get("foot_force")
    if not isinstance(foot_force, (list, tuple)):
        raise Go2ReplayError("foot_force must be a list")
    stamp = payload.get("stamp_ns")
    if stamp is not None and (isinstance(stamp, bool) or not isinstance(stamp, int)):
        raise Go2ReplayError("stamp_ns must be an integer nanosecond count")
    state = RobotMotionState(
        received_at=received_at,
        sequence=sequence,
        position=position,
        roll=rpy[0],
        pitch=rpy[1],
        yaw=yaw,
        velocity=VelocityCommand(
            vx=body_vx,
            vy=body_vy,
            vyaw=_finite(payload.get("yaw_speed", 0.0), "yaw_speed"),
        ),
        mode=int(payload.get("mode", 0)),
        error_code=int(payload.get("error_code", 0)),
        source="go2_replay",
        foot_forces=tuple(float(value) for value in foot_force),
        origin=EvidenceOrigin.REPLAY,
        source_time_s=(stamp / 1e9 if stamp is not None else None),
        session_epoch=session_epoch,
    )
    return _StateSample(state=state, stamp_ns=stamp)


class RecordedStage0Source:
    """Replay of a recorded Stage-0 session: state samples and Livox frames.

    THE FORMAT (defined by card HW-2; ``scrum/20260822/task_40/DESIGN.md`` §g).
    Nothing in the tree recorded ``SportModeState_`` to disk before this card —
    ``scrum/20260813/task_1/`` holds the Stage-0 PLAN and the channel matrix,
    not samples — so the shipped fixture is SYNTHESISED and says so in its own
    header line. One JSON object per line
    (``clockmap.append_sample_jsonl``'s convention: a partial write costs at
    most the line in flight)::

        {"schema": "parcel.stage0_replay.v1", "synthesised": true, ...}
        {"t_s": 0.00, "channel": "rt/sportmodestate", "sport_mode_state": {...}}
        {"t_s": 0.01, "channel": "livox/mid360/points", "frame_hex": "..."}

    ``frame_hex`` is a REAL Livox SDK2 datagram (built by HW-3's
    ``build_point_frame``), so replay runs the real ``parse_point_frame`` and a
    box-day capture drops straight in beside it.

    ``t_s`` is the recording's own relative clock. It is mapped onto this
    process's monotonic clock at ``start()``; the device clock (``stamp_ns``,
    ``base_timestamp_ns``) is carried through unconverted.

    Declares ``EvidenceOrigin.REPLAY``. It reads a file: there is no
    configuration that makes it physical.
    """

    origin = EvidenceOrigin.REPLAY
    name = "go2_stage0_replay"

    def __init__(
        self,
        path: str | Path,
        *,
        clock=time.monotonic,
        loop: bool = False,
    ) -> None:
        self.path = Path(path)
        self.fixture_label = self.path.name
        self._clock = clock
        self._loop = bool(loop)
        self._states: list[tuple[float, object]] = []
        self._frames: list[tuple[float, LivoxPointFrame]] = []
        self._header: dict[str, Any] = {}
        self._epoch: float | None = None
        self._state_cursor = 0
        self._frame_cursor = 0
        self._sequence = 0
        self._last_state: RobotMotionState | None = None
        #: Host clock read as the last replayed frame was handed over — the
        #: replay's answer to ``LiveGo2Sources.last_frame_received_at`` (X04).
        #: A recording's receipt is when THIS process took delivery, not the
        #: recording's own ``t_s``, which is a different clock entirely.
        self.last_frame_received_at: float | None = None
        self._load()

    # -- loading -----------------------------------------------------------

    def _load(self) -> None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as error:
            raise Go2ReplayError(f"{self.path}: cannot be read: {error}") from error
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            raise Go2ReplayError(f"{self.path}: the recording is empty")
        try:
            header = json.loads(lines[0])
        except json.JSONDecodeError as error:
            raise Go2ReplayError(f"{self.path}: line 1 is not JSON: {error}") from error
        if not isinstance(header, dict) or header.get("schema") != REPLAY_SCHEMA_V1:
            raise Go2ReplayError(
                f"{self.path}: line 1 must declare schema {REPLAY_SCHEMA_V1!r}, got "
                f"{header.get('schema') if isinstance(header, dict) else header!r}"
            )
        self._header = header
        last_t = -math.inf
        for number, line in enumerate(lines[1:], start=2):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise Go2ReplayError(f"{self.path}:{number}: not JSON: {error}") from error
            if not isinstance(record, dict):
                raise Go2ReplayError(f"{self.path}:{number}: a record must be an object")
            offset = _finite(record.get("t_s"), f"{self.path}:{number}: t_s")
            if offset < last_t:
                # A recording whose clock walks backwards is a broken recording,
                # not a source of ordering faults to be replayed downstream.
                raise Go2ReplayError(
                    f"{self.path}:{number}: t_s {offset} is before the previous {last_t}"
                )
            last_t = offset
            channel = record.get("channel")
            if channel == REPLAY_CHANNEL_STATE:
                self._states.append((offset, record.get("sport_mode_state")))
            elif channel == REPLAY_CHANNEL_POINTS:
                frame_hex = record.get("frame_hex")
                if not isinstance(frame_hex, str):
                    raise Go2ReplayError(f"{self.path}:{number}: frame_hex must be a string")
                try:
                    payload = bytes.fromhex(frame_hex)
                except ValueError as error:
                    raise Go2ReplayError(
                        f"{self.path}:{number}: frame_hex is not hex: {error}"
                    ) from error
                try:
                    self._frames.append((offset, parse_point_frame(payload)))
                except LivoxDecodeError as error:
                    raise Go2ReplayError(
                        f"{self.path}:{number}: the recorded datagram does not decode: {error}"
                    ) from error
            else:
                raise Go2ReplayError(
                    f"{self.path}:{number}: unknown channel {channel!r}; this reader "
                    f"knows {REPLAY_CHANNEL_STATE!r} and {REPLAY_CHANNEL_POINTS!r}"
                )
        if not self._states:
            raise Go2ReplayError(f"{self.path}: no {REPLAY_CHANNEL_STATE} samples")

    @property
    def header(self) -> dict[str, Any]:
        """The recording's own header line, verbatim (it says if synthesised)."""

        return dict(self._header)

    # -- the source contract ----------------------------------------------

    def start(self) -> None:
        self._epoch = float(self._clock())

    def close(self) -> None:
        self._epoch = None

    def _elapsed(self) -> float:
        if self._epoch is None:
            self.start()
        return float(self._clock()) - float(self._epoch or 0.0)

    def latest(self) -> RobotMotionState | None:
        """The freshest state sample whose recorded time has arrived."""

        now = self._elapsed()
        sample: _StateSample | None = None
        while self._state_cursor < len(self._states):
            offset, payload = self._states[self._state_cursor]
            if offset > now:
                break
            self._state_cursor += 1
            self._sequence += 1
            sample = state_from_sport_mode_state(
                payload,
                received_at=float(self._clock()),
                sequence=self._sequence,
                session_epoch=str(self._header.get("session_epoch", "")),
            )
        if sample is None:
            return self._last_state
        self._last_state = sample.state
        return sample.state

    def drain(self) -> Sequence[LivoxPointFrame]:
        """Every point frame whose recorded time has arrived since the last call."""

        now = self._elapsed()
        drained: list[LivoxPointFrame] = []
        while self._frame_cursor < len(self._frames):
            offset, frame = self._frames[self._frame_cursor]
            if offset > now:
                break
            self._frame_cursor += 1
            drained.append(frame)
            self.last_frame_received_at = float(self._clock())
        if not drained and self._loop and self._frames and self._frame_cursor >= len(self._frames):
            self._frame_cursor = 0
            self._state_cursor = 0
            self._epoch = float(self._clock())
        return drained


class LiveGo2Sources:
    """The live adapter: ``rt/sportmodestate`` over DDS + Mid-360 over UDP.

    Declares ``EvidenceOrigin.PHYSICAL`` because of what it IS — a DDS
    subscriber and a bound, NON-BLOCKING UDP socket — not because anything said
    so in a file.

    **The socket is opened here, from configuration** (verifier finding F3: an
    earlier draft declared a "bound UDP socket" in this docstring while
    ``web_panel._build_backend`` passed none, so ``drain()`` returned ``()``
    forever and box-day would have been asked to prove code that did not
    exist). ``backend.livox: {host, port}`` reaches :meth:`open_livox_socket`.
    The ADDRESS is a box-day value (Q-wire); the code that uses it is not.

    **It cannot block.** ``observe()`` runs on the control loop, so a socket
    that waits for a datagram stalls the robot's own tick when the sensor goes
    quiet. A socket this class opens is ``setblocking(False)``; an INJECTED one
    is refused unless it reports a non-blocking timeout; and the drain is
    additionally bounded by ``drain_budget_s`` of wall clock. No frames is
    never an error — it is an empty band, which is "no scan", which HOLDs.

    Both vendor imports are LAZY and happen here, inside ``__init__``: nothing
    in ``parcel_robot.backends`` may import ``unitree_sdk2py`` at module scope
    (design §3: the SDK and ``rclpy`` never share a process, and the runtime's
    venv has neither). When the SDK is absent the refusal names the venv that
    has it rather than an ``ImportError`` three frames down.

    The two transports are injectable — ``state_source`` and ``socket`` — for
    exactly the reason ``UnitreeSportStateSource`` takes ``subscriber_factory``
    and ``message_type``: the vendor boundary is the only thing a desktop can
    stand in for, and standing in for it is not the same as pretending a file
    is a sensor.
    """

    origin = EvidenceOrigin.PHYSICAL
    name = "go2_live"
    fixture_label = ""

    #: Seconds of wall clock one ``drain()`` may spend. The second belt behind
    #: the non-blocking socket: whatever a transport does, the control loop's
    #: tick is bounded.
    DEFAULT_DRAIN_BUDGET_S = 0.02

    #: Datagrams one ``drain()`` may READ per frame slot it is allowed to
    #: deliver — card SENSE-1's third belt, and the one that holds when the
    #: clock cannot help. A corrupt datagram is skipped without consuming a
    #: frame slot (F4, and HW-3's row pins it), so an ALL-CORRUPT flood never
    #: reaches ``max_frames`` and the wall budget is the only thing between the
    #: control loop and a sender that is faster than the clock's resolution.
    #: Four says: tolerate three corrupt datagrams per good frame this tick,
    #: then give up and publish the sweep as it stands.
    DEFAULT_DATAGRAM_BUDGET_FACTOR = 4

    def __init__(
        self,
        *,
        interface: str = "",
        domain_id: int = 0,
        state_source: Any = None,
        socket: Any = None,
        livox_host: str = "",
        livox_port: int = 0,
        max_frames_per_drain: int = 32,
        drain_budget_s: float = DEFAULT_DRAIN_BUDGET_S,
        datagram_budget_factor: int = DEFAULT_DATAGRAM_BUDGET_FACTOR,
        clock=time.monotonic,
    ) -> None:
        self._clock = clock
        self._max_frames = int(max_frames_per_drain)
        if self._max_frames <= 0:
            raise ValueError("max_frames_per_drain must be positive")
        self.drain_budget_s = float(drain_budget_s)
        if not math.isfinite(self.drain_budget_s) or self.drain_budget_s <= 0.0:
            raise ValueError("drain_budget_s must be positive and finite")
        factor = int(datagram_budget_factor)
        if factor < 1:
            raise ValueError("datagram_budget_factor must be at least 1")
        self.max_datagrams_per_drain = self._max_frames * factor
        #: Datagrams this source refused (F4). One bad datagram costs one
        #: datagram, not the tick and not the session.
        self.refused_datagrams = 0
        #: Drains that read NOTHING because the socket reported itself blocking
        #: (card SENSE-1). Not an error: an empty band is "no scan", which
        #: HOLDs. It is counted so a rig that quietly went blocking is visible.
        self.refused_blocking_drains = 0
        #: Drains that ended on the wall-clock budget or the datagram budget
        #: rather than on an empty socket — the tick was bounded by this class
        #: and not by the sensor. Box-day reads it as "the Mid-360 is out-
        #: running the drain", which is a real finding and not a fault.
        self.bounded_drains = 0
        #: Host monotonic clock read as the LAST frame of the most recent
        #: non-empty drain came off the socket. This is the scan's own receipt
        #: (X04) and it is what ``Go2Backend`` stamps onto the ``ScanDatum``;
        #: ``None`` until a frame has been delivered.
        self.last_frame_received_at: float | None = None
        self._budget_spent = False
        self._owns_socket = False
        if socket is not None:
            self._socket = self._checked_socket(socket)
        elif livox_host.strip():
            self._socket = self.open_livox_socket(livox_host, livox_port)
            self._owns_socket = True
        else:
            self._socket = None
        if state_source is not None:
            # The VENDOR BOUNDARY is injected — the same seam
            # ``UnitreeSportStateSource(subscriber_factory=..., message_type=...)``
            # exposes, and the only thing a desktop can honestly stand in for.
            # The SDK probe below is skipped because the SDK is precisely what
            # has been replaced; the origin stays PHYSICAL because this class
            # is still the live adapter, reading a stream, not a file.
            self._state_source = state_source
        else:
            if not interface.strip():
                raise Go2SdkUnavailable(
                    "the live Go2 source needs the robot NIC name (backend.interface); "
                    "read it from `ls /sys/class/net` on the Orin"
                )
            try:
                from parcel_robot.control.unitree_sport import (
                    UnitreeChannelContext,
                    UnitreeSportStateSource,
                )
            except ImportError as error:  # pragma: no cover - defensive
                raise Go2SdkUnavailable(str(error)) from error
            self._probe_sdk()
            channel = UnitreeChannelContext(domain_id, interface)
            self._state_source = UnitreeSportStateSource(channel)

    @staticmethod
    def _checked_socket(sock: Any) -> Any:
        """Refuse a BLOCKING socket at construction, not at the first quiet tick.

        A blocking ``recv`` inside ``observe()`` stalls the control loop, and
        the failure mode is invisible until the sensor goes quiet — which is
        exactly when the robot most needs its tick. A transport that cannot
        answer ``gettimeout()`` is taken at its word (an injected vendor-
        boundary double), because the alternative is a check no double can
        satisfy; the deadline in :meth:`_read_until_empty` bounds it anyway.
        """

        gettimeout = getattr(sock, "gettimeout", None)
        if callable(gettimeout) and gettimeout() is None:
            raise ValueError(
                "the Livox socket must be non-blocking: a blocking recv() inside "
                "observe() stalls the control loop when the sensor goes quiet. "
                "Call setblocking(False) (or settimeout(0)) before handing it over."
            )
        return sock

    @staticmethod
    def open_livox_socket(host: str, port: int) -> Any:
        """Bind a non-blocking UDP socket for the Mid-360's point stream.

        ``socket`` is imported HERE and not at module scope for the reason the
        module docstring gives. HW-3's ``receive_frames`` deliberately owns no
        socket — "the caller owns the socket and therefore owns the NIC/IP/port
        question that cannot be answered until the box is opened (Q-wire)".
        This is that caller. The default port is HW-3's
        ``HOST_POINT_DATA_PORT``.
        """

        import socket as socket_module

        from parcel_robot.lidar.livox_udp import HOST_POINT_DATA_PORT

        bind_port = int(port) if port else int(HOST_POINT_DATA_PORT)
        if not 0 < bind_port < 65536:
            raise ValueError(f"backend.livox.port must be 1..65535, got {bind_port}")
        sock = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_DGRAM)
        try:
            sock.setblocking(False)
            sock.bind((host, bind_port))
        except OSError:
            sock.close()
            raise
        return sock

    @staticmethod
    def _probe_sdk() -> None:
        """Refuse NOW, by name, instead of at the first silent message.

        ``find_spec`` rather than an import: the question is whether this
        interpreter is the motion venv, and answering it must not drag a vendor
        SDK into a process that may be about to load ``rclpy`` (design §3 —
        CycloneDDS is process-global and the two must never share a process).
        """

        from importlib.util import find_spec

        try:
            found = find_spec("unitree_sdk2py") is not None
        except (ImportError, ValueError):  # a broken/partial install
            found = False
        if not found:
            raise Go2SdkUnavailable(
                "unitree_sdk2py is not importable in this interpreter. The live Go2 "
                "backend runs in the MOTION venv on the Orin (design §3: the vendor "
                "SDK and rclpy must never share a process because CycloneDDS is "
                "process-global). On a desktop use a recorded fixture instead: "
                "`backend: {kind: go2, fixture: <path>.jsonl}`."
            )

    def start(self) -> None:
        start = getattr(self._state_source, "start", None)
        if callable(start):
            start()

    def close(self) -> None:
        close = getattr(self._state_source, "close", None)
        if callable(close):
            close()
        if self._owns_socket and self._socket is not None:
            self._socket.close()
            self._socket = None

    def latest(self) -> RobotMotionState | None:
        return self._state_source.latest()

    def _count_refusal(self, error: Exception) -> None:
        """F4: one corrupt datagram costs ONE datagram.

        Without this, ``receive_frames`` raises the ``LivoxDecodeError`` out of
        the generator: the frames already yielded that tick are abandoned, the
        good datagram queued behind the corrupt one is left unread, and
        ``observe()`` raises — which used to latch the health join (H1). A
        counter and a skip is the whole fix.
        """

        del error
        self.refused_datagrams += 1

    def _socket_reports_blocking(self) -> bool:
        """True when the socket says, NOW, that its ``recv`` may block.

        ``_checked_socket`` asks this once, at construction. Card SENSE-1 asks
        it again on every drain, because a socket's blocking mode is mutable
        state on an object this class does not always own: an injected
        transport, or a reconnect path that calls ``setblocking(True)``, turns
        a bounded drain into an unbounded one silently, and the failure only
        shows up when the sensor goes quiet — which is when the control loop
        most needs its tick. A transport that cannot answer ``gettimeout()`` is
        still taken at its word (see ``_checked_socket``); the deadline below
        then bounds it to ONE recv per drain rather than to none.
        """

        gettimeout = getattr(self._socket, "gettimeout", None)
        return callable(gettimeout) and gettimeout() is None

    def _read_until_empty(self) -> Iterator[LivoxPointFrame]:
        """Yield frames until the socket has none ready or a budget is spent.

        A generator, so frames already read are KEPT when the socket runs dry
        mid-drain -- `tuple(...)` below has them. Draining nothing is not an
        error: it becomes an empty band, which becomes "no scan", which HOLDs.

        THE BUDGETS ARE INSIDE ``receive_frames`` NOW, and that is card
        SENSE-1's fix (A23). This loop used to check the deadline only BETWEEN
        yields, so neither shape of unbounded drain was actually bounded:

        * an ALL-CORRUPT FLOOD never yields. ``receive_frames`` skips a corrupt
          datagram without consuming a frame slot -- correctly, that is F4's
          "one datagram, not the tick" -- so it span inside ``next(frames)``
          for as long as the sender kept sending, and the deadline outside was
          never reached again;
        * a BLOCKING recv never returns, so the first ``next(frames)`` parked
          the control loop until a datagram arrived.

        ``expired`` is therefore checked by ``receive_frames`` itself, before
        every ``recv``, and ``max_datagrams`` bounds the flood even if the
        clock does not advance between reads.
        """

        from parcel_robot.lidar.livox_udp import receive_frames

        deadline = float(self._clock()) + self.drain_budget_s

        def expired() -> bool:
            # It RECORDS that it fired rather than letting `drain()` infer it
            # from elapsed time afterwards: `started + budget` and
            # `sum of the reads` are two different floats and the comparison
            # between them was wrong by one ulp in the measured case.
            if float(self._clock()) < deadline:
                return False
            self._budget_spent = True
            return True

        frames = receive_frames(
            self._socket,
            max_frames=self._max_frames,
            on_refusal=self._count_refusal,
            max_datagrams=self.max_datagrams_per_drain,
            expired=expired,
        )
        while True:
            try:
                frame = next(frames)
            except StopIteration:
                return
            except (BlockingIOError, TimeoutError, OSError):
                return
            # THE SCAN'S OWN RECEIPT (X04), read here and not at the top of
            # `observe()`: this is the closest a host clock gets to the moment
            # the datagram came off the socket.
            self.last_frame_received_at = float(self._clock())
            yield frame

    def drain(self) -> Sequence[LivoxPointFrame]:
        if self._socket is None:
            return ()
        if self._socket_reports_blocking():
            # Refusing to READ is the only bound that exists for a blocking
            # recv, and it costs exactly what a quiet sensor costs: an empty
            # band -> no scan -> HOLD. It never costs the pose, which
            # `observe()` has already taken.
            self.refused_blocking_drains += 1
            return ()
        self._budget_spent = False
        refused_before = self.refused_datagrams
        drained = tuple(self._read_until_empty())
        datagrams = len(drained) + (self.refused_datagrams - refused_before)
        if self._budget_spent or datagrams >= self.max_datagrams_per_drain:
            self.bounded_drains += 1
        return drained


class Go2Backend:
    """Observe-only ``SimulatorBackend`` over a Go2 EDU+ (design §5.4).

    Construct it with ONE source object that provides both channels
    (``latest() -> RobotMotionState | None`` and
    ``drain() -> Sequence[LivoxPointFrame]``): :class:`RecordedStage0Source` on
    a desktop, :class:`LiveGo2Sources` on the dog. The source's declared
    ``origin`` is what :attr:`scan_evidence_source` commissions; this class
    never chooses it.

    :attr:`name` is the SOURCE's (``go2_live`` / ``go2_stage0_replay``), never
    a bare ``"go2"`` for both (verifier finding F5). It reaches
    ``SimObservation.backend`` and the latch record, and a reader has to be
    able to tell a recording from a robot without opening the config.
    """

    def __init__(
        self,
        source: Any,
        *,
        band_profile: BandProfile | None = None,
        clock=time.monotonic,
        session_epoch: str = "",
    ) -> None:
        # LAZY, and the reason is a measured guard, not taste:
        # `parcel_robot.core.input_health` cannot be imported without executing
        # `parcel_robot.core.__init__` -> `core.motion_shaping` ->
        # `parcel_robot.navigation` -> `brain`/`instructnav`. `backends/
        # __init__.py` imports this module, and the `commissioning/` package
        # imports `backends`, so a module-scope import here reddens
        # `tests/test_w0b_commissioning.py
        # ::test_importing_commissioning_does_not_import_the_runtime` — the
        # W0-B guard that keeps the armed commissioning tool out of the
        # runtime's dependency tree. (That package is named here in the
        # `commissioning/` form on purpose: W0-B's GATE 5 refuses even a dotted
        # mention of it outside its own seam.) `EvidenceOrigin` comes from the leaf
        # module card W0-A carved out for exactly this, and the two health
        # types are imported where they are used. Same idiom as
        # `runtime.py:_evaluate_dispatch_input_health`.
        from parcel_robot.core.input_health import CommissionedPoseSource, CommissionedScanSource

        for method in ("latest", "drain"):
            if not callable(getattr(source, method, None)):
                raise TypeError(f"a Go2 source must expose a callable {method}()")
        origin = getattr(source, "origin", None)
        if not isinstance(origin, EvidenceOrigin):
            raise TypeError(
                "a Go2 source must DECLARE its origin as an EvidenceOrigin; a string "
                "is not a declaration (card W0-A)"
            )
        self.source = source
        self.name = str(getattr(source, "name", "") or "go2")
        self.band_profile = band_profile if band_profile is not None else BandProfile()
        self._clock = clock
        self._session_epoch = str(session_epoch)
        self._scan_sequence = 0
        self._latest_scan: ScanDatum | None = None
        self._latest_frame_time_ns: int | None = None
        self._scan_received_at: float | None = None
        # ONE socket, and `observe()` is called from the control loop AND from
        # HTTP handler threads (`runtime.py:6210,9551,10295`). Without this
        # lock two threads drain the same socket and race on the sequence
        # counter (verifier note N4, the mechanism behind H2).
        self._lock = threading.Lock()
        # H2: the datum travels WITH the observation it graded. Identity-keyed
        # and BOUNDED — a few ticks is all any caller can still be holding, and
        # an unbounded map keyed on observations is a leak in a process that
        # runs for days. An observation older than the window reads back as
        # "no datum", which leaves the observation's own stamp in place: the
        # fail-closed direction.
        self._graded: deque[tuple[int, SimObservation, ScanDatum]] = deque(maxlen=GRADED_HISTORY)
        # ---- CARD SENSE-1 (scrum/20260823/task_3): the pose half -----------
        # A SECOND deque rather than a fourth slot in the one above, and the
        # reason is HW-2's semantics, not tidiness: `_graded` is appended to
        # only when the sweep WAS a scan, so its eviction order is part of
        # what rows H2a/H2b measure. Pose exists on every observation this
        # backend publishes — including the scan-less ones — so sharing the
        # deque would change which observations `scan_datum_for` can still
        # answer for. Same bound, same identity keying, same fail-closed
        # "older than the window reads as no datum".
        self._graded_pose: deque[tuple[int, SimObservation, PoseDatum]] = deque(
            maxlen=GRADED_HISTORY
        )
        #: The typed seam. ``runtime.py:_evaluate_dispatch_input_health`` reads
        #: it INSTEAD of the observation stamp when it declares PHYSICAL.
        self.scan_evidence_source = CommissionedScanSource(
            self,
            origin=origin,
            session_epoch=self._session_epoch,
            fixture_label=str(getattr(source, "fixture_label", "") or ""),
            name=self.name,
        )
        #: The pose twin (verdict blocking finding 4). Same declaration, same
        #: latch, one channel over. It has NO product read site yet — the join
        #: still stamps pose through ``evidence_origin`` and
        #: ``tests/test_hw2_go2_backend.py::test_b3_pose_authority_is_not_in_
        #: this_card`` still measures that — because the read site is
        #: ``runtime.py``, which this card may not touch. What lands here is
        #: the seam and its proof at the join itself: a live pose passes the
        #: physical table through this source, a replayed one latches.
        self.pose_evidence_source = CommissionedPoseSource(
            self,
            origin=origin,
            session_epoch=self._session_epoch,
            fixture_label=str(getattr(source, "fixture_label", "") or ""),
            name=self.name,
        )

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        start = getattr(self.source, "start", None)
        if callable(start):
            start()

    def close(self) -> None:
        close = getattr(self.source, "close", None)
        if callable(close):
            close()

    # -- the scan seam -----------------------------------------------------

    def latest_scan(self) -> ScanDatum | None:
        """The scan datum behind the last :meth:`observe`, or ``None``.

        ``None`` means NO SCAN — the sweep measured fewer than
        ``BandProfile.min_populated_bins`` bins (HW-3's ``ranges_m == ()``), or
        ``observe`` has not run. The health join reads that as *missing*, which
        is a recoverable HOLD; it is never a stubbed sample.
        """

        return self._latest_scan

    def scan_datum_for(self, key: object) -> ScanDatum | None:
        """The `ScanDatum` built from the frames that produced ``key``'s scan.

        ``key`` is the ``SimObservation`` :meth:`observe` returned. **This is
        the H2 fix**: the join grades an observation it may have taken several
        ticks ago (``observe()`` also runs on HTTP handler threads and any
        `observe()` exception leaves the previous observation in place), so a
        LATEST datum let it grade observation N against sweep N+1 — and in one
        direction that REMOVED a fault, reporting no SCAN fault for a scan-less
        observation where `scan_evidence_from_observation` says `missing`.

        Matching is by IDENTITY, not equality: two ticks of a stationary robot
        looking at the same wall produce equal observations that are not the
        same evidence. `None` — an observation with no scan, or one older than
        the bounded window — leaves the caller's own stamp in place.
        """

        with self._lock:
            for identity, observation, datum in reversed(self._graded):
                if identity == id(key) and observation is key:
                    return datum
        return None

    # -- the pose seam (card SENSE-1) --------------------------------------

    def pose_datum_for(self, key: object) -> PoseDatum | None:
        """The `PoseDatum` built from the state sample that produced ``key``.

        The pose half of :meth:`scan_datum_for`, keyed the same way and for the
        same measured reason (H2): ``observe()`` also runs on HTTP handler
        threads and the join may be grading an observation several ticks old,
        so answering "what is the LATEST pose?" would let it grade observation
        N against state N+1. Identity, not equality — two ticks of a standing
        dog produce equal poses that are not the same evidence.
        """

        with self._lock:
            for identity, observation, datum in reversed(self._graded_pose):
                if identity == id(key) and observation is key:
                    return datum
        return None

    def _scan_receipt(self, frames: Sequence[LivoxPointFrame], *, fallback: float) -> float:
        """The host clock the last frame of this sweep was received at (X04).

        ``fallback`` — the assembly clock — is used when the source keeps no
        receipt, or reports one that is not a finite number, or when the drain
        produced nothing at all (there is no sweep to date, and the no-scan
        branch throws the value away anyway). It is the PERMISSIVE direction,
        so it is deliberately narrow: both shipped sources keep a receipt, and
        a source that does not is a third-party one whose scan must still get a
        number the freshness check can read.
        """

        if not frames:
            return fallback
        receipt = getattr(self.source, "last_frame_received_at", None)
        if isinstance(receipt, bool) or not isinstance(receipt, (int, float)):
            return fallback
        if not math.isfinite(float(receipt)):
            return fallback
        return float(receipt)

    def latest_scan_age_s(self, now: float | None = None) -> float | None:
        """Age of the scan behind the last observation, in seconds.

        This is the sixth stopping-envelope term (``bridge/timing.py``'s
        ``CARD HW-2`` region, design §6): the Mid-360 frame's age at the moment
        a command candidate is built. On the dog it is measured as the p99 of
        this reading under load; on a desktop replay it measures the replay
        loop and means nothing about the robot.
        """

        if self._scan_received_at is None:
            return None
        moment = float(self._clock()) if now is None else float(now)
        return max(0.0, moment - self._scan_received_at)

    # -- the SimulatorBackend contract ------------------------------------

    def observe(self) -> SimObservation:
        from parcel_robot.core.input_health import PoseDatum, ScanDatum  # see __init__'s note

        with self._lock:
            # THE POSE COMES FIRST, and it comes before the socket is drained
            # (F2). Two reasons: a tick that cannot answer "where is the
            # robot?" must not publish (0, 0, 0, 0) under a fresh timestamp,
            # and refusing before the drain means the refused tick does not
            # eat the frames the next one will need.
            state = self.source.latest()
            if state is None:
                raise Go2StateUnavailable(
                    "no rt/sportmodestate sample has arrived yet, so this backend has "
                    "no pose to publish. It refuses rather than defaulting to the "
                    "origin: the health join reads a defaulted pose as present and "
                    "fresh. Check that the Sport service is up and that the DDS "
                    "domain/interface are the robot's (design §4 S4)."
                )
            # THE ASSEMBLY CLOCK, and from here on it is ONLY that (X04). It
            # is what `SimObservation.timestamp` has always been and half the
            # tree reads it, so it does not move; what moves is that it is no
            # longer also passed off as the receipt of two buffered channels
            # that took delivery at their own moments.
            timestamp = float(self._clock())

            # THE POSE'S OWN RECEIPT: the host clock at which the DDS sample
            # this pose was read from arrived. `latest()` is a POLL over a
            # buffer, so on a quiet stream it returns the same sample tick
            # after tick; stamping it with `timestamp` made a pose from a
            # stream that had stopped look permanently fresh to the health
            # join's staleness branch, which is the one branch that exists to
            # notice a stream that stopped.
            pose_datum = PoseDatum(
                captured_at=float(state.received_at),
                sequence=int(state.sequence),
                frame_id="odom",
                payload_valid=True,
                source_time_s=state.source_time_s,
                # The epoch this BACKEND was commissioned under, exactly as the
                # `ScanDatum` below carries it. The producer's own
                # `state.session_epoch` is `CommissionedStateSource`'s axis on
                # the feedback channel and is deliberately not re-checked here:
                # the shipped replay fixture declares an epoch
                # (`hw2-synthetic-2026-08-23`) that no backend config names, so
                # checking it would latch tick one of every desktop replay —
                # a refusal with no defect behind it.
                session_epoch=self._session_epoch,
            )

            frames = tuple(self.source.drain())
            scan = scan_from_frames(frames, self.band_profile)
            # THE SCAN'S OWN RECEIPT: the host clock read as the last datagram
            # of this sweep came off the socket, which the source records
            # (`LiveGo2Sources.last_frame_received_at`). A source that does not
            # keep one leaves the assembly clock in place; both shipped sources
            # keep one.
            received_at = self._scan_receipt(frames, fallback=timestamp)

            if not scan.ranges_m:
                # HW-3's branch, verbatim: this sweep is NOT a scan. Publish the
                # absence — `scan_present()` is False, the health join reports SCAN
                # missing, translation HOLDs — and never copy an empty BandScan
                # across as if it were a scan. No datum is recorded, so
                # `scan_datum_for` returns None for this observation and the
                # join sees `missing` through BOTH paths.
                self._latest_scan = None
                self._scan_received_at = None
                scanless = self._observation(state, timestamp=timestamp)
                # The POSE is recorded even here, and that is the difference
                # between the two channels: a sweep with no returns is a real
                # answer from the LiDAR, but this tick still has a pose — the
                # one `Go2StateUnavailable` above refused to fabricate.
                self._graded_pose.append((id(scanless), scanless, pose_datum))
                return scanless

            self._scan_sequence += 1
            self._scan_received_at = received_at
            self._latest_frame_time_ns = frames[-1].base_timestamp_ns if frames else None
            datum = ScanDatum(
                captured_at=received_at,
                sequence=self._scan_sequence,
                frame_id="base_link",
                payload_valid=True,
                populated_bins=scan.populated_bins,
                points_seen=scan.points_seen,
                source_time_ns=self._latest_frame_time_ns,
                session_epoch=self._session_epoch,
            )
            self._latest_scan = datum
            bearing = travel_bearing_rad(state.velocity.vx, state.velocity.vy)
            fix = nearest_obstacle_from_scan(scan, self.band_profile, travel_bearing=bearing)
            observation = self._observation(
                state,
                timestamp=timestamp,
                nearest_obstacle_m=(fix.clearance_m if fix else None),
                nearest_obstacle_bearing_rad=(fix.bearing_rad if fix else None),
                lidar_ranges=scan.ranges_m,
                lidar_angle_min_rad=scan.angle_min_rad,
                lidar_angle_increment_rad=scan.angle_increment_rad,
                lidar_range_min_m=scan.range_min_m,
                lidar_range_max_m=scan.range_max_m,
            )
            self._graded.append((id(observation), observation, datum))
            self._graded_pose.append((id(observation), observation, pose_datum))
            return observation

    def _observation(
        self,
        state: RobotMotionState,
        *,
        timestamp: float,
        **scan_fields: Any,
    ) -> SimObservation:
        """Assemble the observation. Every field this card has no sensor for is
        left at its dataclass default, deliberately — an unfilled field is a
        field nothing measured, and inventing one is how a simulator's premises
        become a robot's beliefs."""

        robot = RobotPose(
            x=state.position[0],
            y=state.position[1],
            z=state.position[2],
            yaw=state.yaw,
        )
        return SimObservation(
            timestamp=timestamp,
            robot=robot,
            # There is no owner sensor on this backend. `visible=False` is the
            # honest default and every consumer already degrades on it (OT-2).
            owner=OwnerTrack(visible=False),
            backend=self.name,
            **scan_fields,
        )

    # -- the hand this backend does not have -------------------------------

    def _refuse(self, what: str) -> Go2MotionRefused:
        return Go2MotionRefused(f"Go2Backend refuses {what}: {MOTION_CITATION}")

    def move(self, command: VelocityCommand) -> None:
        del command
        raise self._refuse("move()")

    def pose(self, pose: Pose) -> None:
        del pose
        raise self._refuse("pose() (a teleport has no physical meaning)")

    def trajectory(self, skill: object) -> None:
        del skill
        raise self._refuse("trajectory()")

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy
        raise self._refuse("move_owner() (the owner is a person, not a body in a scene)")

    def set_owner_visible(self, visible: bool) -> None:
        del visible
        raise self._refuse("set_owner_visible()")

    # -- the stop path, which must NEVER raise ----------------------------
    #
    # ``control/adapters.py:55,73,87,106`` calls ``backend.stop()`` on its
    # startup, stop, emergency-stop and close paths. A backend that threw out
    # of those would turn a safe no-op into an exception ON THE SAFETY PATH —
    # the opposite of what refusing motion is for. This backend never commanded
    # anything, so "stop" is truthfully nothing to do, and saying so costs
    # nothing. The dog's real stop is the handheld remote (docs/MOTION.md:441).

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def clear_emergency_stop(self) -> None:
        return None

    def expression(self, joint_offsets: dict[str, float]) -> None:
        """No expression channel. The Protocol's own rule: expressive liveness
        degrades to snapshot-only, never fails a run."""

        del joint_offsets


def band_profile_from_config(section: object) -> BandProfile:
    """``backend.band:`` -> :class:`BandProfile`, refusing an unknown key by name.

    The read-site guard (TRUTH-1's rule): a misspelled band key would otherwise
    merge cleanly and leave the filter at its shipped default while the file on
    disk said otherwise.
    """

    if section is None:
        return BandProfile()
    if not isinstance(section, dict):
        raise TypeError("backend.band must be a mapping")
    allowed = {
        "z_lo_m",
        "z_hi_m",
        "bins",
        "angle_min_rad",
        "range_min_m",
        "range_max_m",
        "min_populated_bins",
        "corridor_half_angle_rad",
        "extrinsic",
    }
    unknown = sorted(str(key) for key in section if str(key) not in allowed)
    if unknown:
        raise ValueError(
            f"unknown backend.band key(s): {', '.join(unknown)}; allowed: "
            f"{', '.join(sorted(allowed))}"
        )
    values = dict(section)
    extrinsic = values.get("extrinsic")
    if extrinsic is not None:
        if not isinstance(extrinsic, (list, tuple)):
            raise ValueError("backend.band.extrinsic must be a 4x4 row-major matrix")
        values["extrinsic"] = tuple(
            tuple(float(cell) for cell in row) if isinstance(row, Iterable) else row
            for row in extrinsic
        )
    return BandProfile(**values)


__all__ = [
    "MOTION_CITATION",
    "REPLAY_CHANNEL_POINTS",
    "REPLAY_CHANNEL_STATE",
    "REPLAY_SCHEMA_V1",
    "Go2Backend",
    "Go2BackendError",
    "Go2MotionRefused",
    "Go2ReplayError",
    "Go2SdkUnavailable",
    "Go2StateUnavailable",
    "LiveGo2Sources",
    "RecordedStage0Source",
    "band_profile_from_config",
    "state_from_sport_mode_state",
]
