"""Read-only RealSense D455 ingest — card PS-G.

The D455 is not on a DDS topic. Its bytes reach the Orin over USB3 through
``pyrealsense2``, and for the session the **primary** path is the
``realsense2_camera`` ROS node feeding ``ros2 bag record -s mcap``. This adapter
is the preflight/attestation path: it answers "is the camera there, are frames
arriving, does the IMU read 9.81 at rest, and does this build deliver per-frame
device timestamps at all" without a ROS stack in the way.

The three platform risks this module encodes rather than assumes
----------------------------------------------------------------
1. **The pip wheel may cost UVC per-frame metadata.** ``pyrealsense2`` is a real
   wheel on CPython 3.10 and 3.12 and does not exist for 3.11+; the wheel is
   reported to drop the per-frame metadata that carries the device timestamp —
   the one quantity PS-I needs from this device. So PS-H marks every D455 row's
   payload clock ``UNVERIFIED``, and
   :class:`~scripts.parcel_capture.ingest.base.IngestFrame` therefore **refuses**
   a ``source_timestamp_ns`` on these channels. The device value is still
   recorded, in the summary, beside its timestamp *domain*, where it is visible
   and cannot be mistaken for an anchor. Flipping the matrix row to
   ``DEVICE_TIMESPEC`` after the bench check is what turns it on; nothing here
   has to change.
2. **``usbfs_memory_mb`` defaults to 16 MB**, which is not enough for dual IR
   plus depth plus colour. The fix edits ``/boot/extlinux/extlinux.conf`` and
   **reboots** — it is not a session-morning fix, and :data:`USBFS_NOTE` says so.
3. **The IR pair is not free.** Two Y8 streams equal the Z16 stream exactly:
   +40% disk and +50% USB. 720p with every stream on is ~1327 Mbps, above
   Intel's own ~1200 Mbps ceiling and ~194 MB/s against a rosbag2 recorder
   observed to top out near 110-120 MB/s.

Nothing here configures the device beyond selecting streams. ``hardware_reset``
and ``set_option`` are on the never-allowed list, so a handle cannot reach them.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator, Mapping
from functools import partial
from typing import Any, ClassVar

from parcel_robot.capture import Channel, Transport

from ..preflight import AbsenceReason, ImuSample, PhysicalSample
from .base import (
    IngestAdapter,
    IngestFrame,
    IngestRefusedError,
    IngestUnavailableError,
    PayloadKind,
    ReadOnlyHandle,
    Requirement,
    now_ns,
    present,
    read_field,
    summary_payload,
)

USBFS_NOTE = (
    "usbfs_memory_mb defaults to 16 MB and that is not enough for depth + colour + both "
    "IR streams. Raising it edits /boot/extlinux/extlinux.conf and requires a REBOOT — "
    "do it the night before, never on session morning."
)

#: Stream selection per channel id. Resolution and rate are a PS-E budget
#: decision, not a device constant, which is why the matrix marks these rows
#: ``CONFIGURED`` and carries no nominal rate.
STREAM_PROFILES: Mapping[str, dict[str, Any]] = {
    "d455.color": {"stream": "color", "format": "rgb8", "index": 0},
    "d455.depth": {"stream": "depth", "format": "z16", "index": 0},
    "d455.infra1": {"stream": "infrared", "format": "y8", "index": 1},
    "d455.infra2": {"stream": "infrared", "format": "y8", "index": 2},
    "d455.accel": {"stream": "accel", "format": "motion_xyz32f", "index": 0},
    "d455.gyro": {"stream": "gyro", "format": "motion_xyz32f", "index": 0},
}

#: Motion streams, whose frames decode to a half-IMU each. The D455's accel and
#: gyro are two halves of ONE unit and PS-J groups them by ``(device, frame)``
#: so they are never counted as two witnesses at rest.
MOTION_CHANNELS = frozenset({"d455.accel", "d455.gyro"})

#: The only ``pyrealsense2`` pipeline attributes this adapter may reach.
#: ``start`` takes an ``rs.config`` naming ONE stream — selecting which sensor to
#: read is not configuring the device, and ``hardware_reset`` and ``set_option``,
#: which would be, are on NEVER_ALLOWED and cannot be added here.
_PIPELINE_ALLOWLIST = ("start", "stop", "wait_for_frames", "poll_for_frames")


def decode_motion_frame(channel_id: str, frame: Any) -> tuple[
    tuple[PhysicalSample, ...], dict[str, Any]
]:
    """A motion frame -> half an :class:`ImuSample`, plus its summary.

    ``d455.accel`` yields an accelerometer-only sample and ``d455.gyro`` a
    gyroscope-only one. That is what PS-J's ``ImuStreamKind`` expects, and
    fusing them here would invent a sample that never existed on the wire.
    """

    data = read_field(frame, "motion_data")
    if not present(data):
        data = read_field(frame, "as_motion_frame")
    vector: tuple[float, float, float] | None = None
    parts = [read_field(data, axis) for axis in ("x", "y", "z")] if present(data) else []
    if len(parts) == 3 and all(
        present(part) and not isinstance(part, bool) and isinstance(part, (int, float))
        for part in parts
    ):
        vector = (float(parts[0]), float(parts[1]), float(parts[2]))

    samples: list[PhysicalSample] = []
    if vector is not None:
        if channel_id == "d455.accel":
            samples.append(ImuSample(accel_mps2=vector))
        else:
            samples.append(ImuSample(gyro_rps=vector))
    summary = {
        "message": f"realsense/{channel_id.split('.')[-1]}",
        "vector": list(vector) if vector else None,
        "frame_number": _int_or_none(read_field(frame, "frame_number")),
        # Deliberately NOT stamp_ns. See the module docstring: until the UVC
        # metadata question is settled, this number is evidence, not a clock.
        "device_timestamp_ms": _float_or_none(read_field(frame, "timestamp")),
        "timestamp_domain": _domain(frame),
        "missing_fields": [] if vector else ["motion_data"],
        "findings": [],
    }
    return tuple(samples), summary


def decode_video_frame(channel_id: str, frame: Any) -> tuple[
    tuple[PhysicalSample, ...], dict[str, Any]
]:
    """A video frame -> arrival evidence and geometry. The pixels stay on the
    rosbag2 side: copying a 2.6 MiB colour frame into the Parcel secondary bag
    would double the session's disk cost to record it twice."""

    width = _int_or_none(read_field(frame, "width"))
    height = _int_or_none(read_field(frame, "height"))
    return (), {
        "message": f"realsense/{channel_id.split('.')[-1]}",
        "width": width,
        "height": height,
        "bytes_per_pixel": _int_or_none(read_field(frame, "bytes_per_pixel")),
        "stride": _int_or_none(read_field(frame, "stride")),
        "frame_number": _int_or_none(read_field(frame, "frame_number")),
        "device_timestamp_ms": _float_or_none(read_field(frame, "timestamp")),
        "timestamp_domain": _domain(frame),
        "missing_fields": [name for name, value in (("width", width), ("height", height))
                           if value is None],
        "findings": [
            (
                "pixels are not copied into this frame; the rosbag2 primary recording "
                "holds the image data"
            )
        ],
    }


def _domain(frame: Any) -> str | None:
    """Which clock the device timestamp is on. ``None`` when the build cannot say.

    The three RealSense domains are not interchangeable: ``hardware_clock`` is
    the sensor, ``system_time`` is the host, and ``global_time`` is librealsense
    already having applied its own offset. Recording a number without its domain
    is what makes a later alignment silently wrong.
    """

    value = read_field(frame, "timestamp_domain")
    if not present(value):
        return None
    name = read_field(value, "name")
    return str(name) if present(name) else str(value)


def _int_or_none(value: Any) -> int | None:
    if not present(value) or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _float_or_none(value: Any) -> float | None:
    if not present(value) or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def decoder_for(entry: Channel) -> Callable[[Any], tuple[tuple[PhysicalSample, ...], dict[str, Any]]]:
    """The decoder this stream's frames go through, already bound to its channel.

    One dispatch, exported so the cross-package structural pin can ask which
    decoder runs for a channel instead of keeping a second copy of the mapping.
    A channel with no declared stream profile refuses rather than falling through
    to the video decoder: guessing a profile is how ``d455.gyro`` would come back
    holding colour frames.
    """

    if entry.channel_id not in STREAM_PROFILES:
        raise IngestRefusedError(
            f"{entry.channel_id}: no RealSense stream profile is declared for it; "
            f"known: {sorted(STREAM_PROFILES)}"
        )
    if entry.channel_id in MOTION_CHANNELS:
        return partial(decode_motion_frame, entry.channel_id)
    return partial(decode_video_frame, entry.channel_id)


def attributable(summary: Mapping[str, Any]) -> bool:
    """Did this frame decode as the stream the channel declares?

    A pipeline started without an ``rs.config`` runs librealsense's DEFAULT
    profile, which is depth + colour. Measured on this box against a double
    modelling exactly that: reading ``d455.gyro`` for 10 ms yielded 1094 frames,
    every one of them a colour frame with no motion vector, and ``probe_channel``
    reported the D455's **gyroscope** PRESENT with 935 messages. Presence claimed
    from another stream's pixels is the one thing preflight must never do.

    :meth:`RealSenseIngest.stream_selection` is the fix at the source; this is the
    fail-closed check behind it, because a config that silently did not take must
    read as ABSENT and not as a healthy channel.
    """

    return not summary.get("missing_fields")


def build_frame(entry: Channel, samples: tuple[PhysicalSample, ...], summary: dict[str, Any]) -> IngestFrame:
    """One decoded frame -> one :class:`IngestFrame`. No source timestamp: see
    the module docstring."""

    monotonic_ns, realtime_ns = now_ns()
    return IngestFrame(
        channel_id=entry.channel_id,
        host_monotonic_ns=monotonic_ns,
        host_realtime_ns=realtime_ns,
        payload=summary_payload(summary),
        payload_kind=PayloadKind.DERIVED_SUMMARY,
        source_timestamp_ns=None,
        measurements=samples,
        detail=f"{entry.channel_id} via pyrealsense2 ({summary.get('timestamp_domain')})",
    )


def frame_from_realsense(entry: Channel, frame: Any) -> IngestFrame:
    """Decode one RealSense frame into an :class:`IngestFrame`."""

    samples, summary = decoder_for(entry)(frame)
    return build_frame(entry, samples, summary)


class RealSenseIngest(IngestAdapter):
    """Subscribe-only reader for the six D455 streams."""

    adapter_name: ClassVar[str] = "realsense"
    transports: ClassVar[frozenset[Transport]] = frozenset({Transport.REALSENSE})
    payload_kind: ClassVar[PayloadKind] = PayloadKind.DERIVED_SUMMARY
    #: A D455 on USB is a UVC device and enumerates as ``/dev/video*``. Card
    #: ENV-1: this is the IMPORT-FREE half of the presence question, and it is
    #: checked BEFORE ``pyrealsense2`` is imported so a preflight on a
    #: camera-less box never loads the SDK. It is deliberately coarse — any
    #: webcam creates these nodes — and :meth:`_require_enumerated_device` is
    #: the precise half, run once the SDK is legitimately in memory.
    device_nodes: ClassVar[tuple[str, ...]] = ("video*",)
    device_remedy: ClassVar[str] = (
        "plug the D455 into a USB 3 (BLUE) port, direct, no hub, and confirm it "
        "enumerates: `ls /dev/video*` then `lsusb | grep -i intel`. Only one process "
        "may hold the camera, so stop any other reader first. On the Orin also raise "
        "usbfs_memory_mb before the session — that edit REBOOTS the box."
    )
    requirements: ClassVar[tuple[Requirement, ...]] = (
        Requirement(
            "pyrealsense2",
            # Card TRUTH-1 (SDK-REM-1). The old text scoped the whole remedy
            # to the Orin, named CPython 3.10 and 3.12 as the only usable
            # interpreters, and denied that any wheel existed above 3.10 — the
            # two stale strings this card's greps keep dead, DESCRIBED here and
            # deliberately not reproduced, because a retraction that quotes the
            # claim defeats the guard that hunts it (see the module docstring
            # of tests/test_truth1_texts.py). It was wrong three ways: it sent
            # a DESK operator to hardware they do not have; the interpreter
            # claim was never measured and is false; and it implied the Orin
            # needs something other than pip, which it does not.
            # TWO HOSTS now exist for real — this x86_64
            # dev box on CPython 3.14, and the Jetson Orin NX 16 GB that ships
            # with the Go2 EDU PLUS the owner ordered on 2026-08-22 — so the
            # remedy names both and says what is true on each. Everything
            # below was measured on 2026-08-22 from this box (`pip index
            # versions pyrealsense2` + the PyPI file list for that release) and
            # is dated so the next reader re-measures rather than inherits.
            "HERE (x86_64, CPython 3.14): `.parcel/bin/pip install -e "
            "'.[camera-realsense]'` — already installed, 2.58.3.10794, a cp314 "
            "manylinux1_x86_64 wheel, reported INSTALLED and LATEST on "
            "2026-08-22. ON THE ORIN NX (aarch64) the answer depends on which "
            "JetPack the EDU dock boots, and that is UNCONFIRMED until the box "
            "is opened: reseller and forum reports have Go2 EDU docks shipping "
            "JetPack 5.1.1 (Ubuntu 20.04, CPython 3.8) AND being flashed to "
            "6.2.1 (Ubuntu 22.04, CPython 3.10). On JetPack 6.x: `pip install "
            "pyrealsense2` into the DEPLOY venv and NEVER into .parcel/ — the "
            "wheel exists, "
            "pyrealsense2-2.58.3.10794-cp310-cp310-manylinux2014_aarch64.whl, "
            "though nobody has run it on the unit yet, and librealsense has an "
            "open 'D455 not detected on JetPack 6.2' report whose workaround is "
            "a source build with -DFORCE_RSUSB_BACKEND=ON. On JetPack 5.1.1 "
            "there is no aarch64 wheel for CPython 3.8 at all. That release "
            "ships 13 files: manylinux1_x86_64 for cp310-cp314, "
            "manylinux2014_aarch64 for cp39/cp310/cp312 ONLY, win_amd64 for "
            "cp310-cp314 — so every other aarch64 interpreter (3.8, 3.11, 3.13, "
            "3.14) needs a source build, 2-3 hours and not a session-morning "
            "task. Check per-frame metadata survives whichever build you land "
            "on.",
        ),
    )
    notes: ClassVar[tuple[str, ...]] = (
        (
            "Per-frame device timestamps are UNVERIFIED on the pip wheel, so every D455 "
            "frame carries a null source_timestamp_ns and records the device value in its "
            "summary beside the timestamp domain."
        ),
        USBFS_NOTE,
        (
            "The IR pair is not free: two Y8 streams equal the Z16 stream exactly (+40% "
            "disk, +50% USB). 720p all-streams is above Intel's own USB ceiling."
        ),
        (
            "Open reports on D455-over-Orin-NX include ~80% RGB frame drop and a dead "
            "IMU. Measure frame counts for ten minutes before the session, not during it."
        ),
    )

    def __init__(self, *, serial: str | None = None) -> None:
        self.serial = serial

    def _module(self, entry: Channel) -> Any:
        """``pyrealsense2``, or a refusal. Never imported by a dependency probe."""

        if entry.channel_id not in STREAM_PROFILES:
            raise IngestRefusedError(
                f"{entry.channel_id}: no RealSense stream profile is declared for it; "
                f"known: {sorted(STREAM_PROFILES)}"
            )
        self.require_dependencies()
        # Card ENV-1, and the ordering is the point: the /dev census is checked
        # BEFORE the import, so on a box that has the wheel and no camera this
        # returns a named device refusal without ``pyrealsense2`` ever entering
        # ``sys.modules``. That is what keeps
        # ``test_a_full_preflight_run_never_imports_a_vendor_sdk`` true now that
        # the wheel is installed here.
        self.require_device()
        try:
            return importlib.import_module("pyrealsense2")
        except ImportError as error:
            raise IngestUnavailableError(
                AbsenceReason.DEPENDENCY_MISSING,
                f"pyrealsense2 became unimportable between the probe and the open: {error}",
                self.requirements[0].remedy,
            ) from error

    def _require_enumerated_device(self, rs: Any) -> None:
        """librealsense\'s own device list, or a named refusal. Card ENV-1.

        :meth:`~..base.IngestAdapter.require_device` answered from ``/dev`` and
        cannot tell a D455 from a laptop webcam. This can: on a host with a UVC
        camera and no RealSense, ``rs.context().query_devices()`` is empty, and
        without this gate ``pipeline.start()`` raises a librealsense
        ``RuntimeError`` that preflight files as ``probe_raised`` — a reason
        that names neither the device nor a remedy.

        Reached through :func:`~..base.read_field` and wrapped in a
        :class:`~..base.ReadOnlyHandle` whose allowlist is exactly
        ``query_devices``, so a build that spells ``context`` differently yields
        a refusal rather than an ``AttributeError`` inside a probe, and nothing
        else on the context is reachable from here.
        """

        factory = read_field(rs, "context")
        if not present(factory):
            # Card ENV-1b closes a fail-open hole. This used to ``return``, on
            # the reasoning that a build with no ``rs.context`` should let the
            # open speak for itself — but the open does not speak, it crashes:
            # a webcam-only host reached ``pipeline.start()`` and preflight filed
            # ``probe_raised — RuntimeError``, the exact unattributable absence
            # ENV-1 was written to remove. It is also inconsistent with
            # :meth:`stream_selection`, which already refuses UNPARSEABLE when a
            # build exposes no ``rs.stream``/``rs.config``. Fail closed and name
            # the symbol, so the operator sees "this build cannot be interrogated"
            # rather than a librealsense traceback attributed to the camera.
            raise IngestUnavailableError(
                AbsenceReason.UNPARSEABLE,
                "pyrealsense2 imports here but this build exposes no rs.context, so "
                "the device list cannot be read and no channel can be attributed to a "
                "camera rather than to a crashed probe",
                "check the pyrealsense2 build: `python -c \"import pyrealsense2 as rs; "
                'print(rs.__version__, rs.context)"`. A build that cannot enumerate '
                "devices must not be used for the D455 rows.",
            )
        handle = ReadOnlyHandle(factory(), allowed=("query_devices",), label="realsense context")
        try:
            count = len(list(handle.query_devices()))
        except Exception as error:  # a probe that raises is ABSENT, never a traceback
            raise IngestUnavailableError(
                AbsenceReason.UNPARSEABLE,
                f"pyrealsense2 imported but rs.context().query_devices() raised: {error}",
                self.device_remedy,
            ) from error
        if count:
            return
        raise IngestUnavailableError(
            AbsenceReason.DEVICE_NODE_MISSING,
            "pyrealsense2 imports here but rs.context().query_devices() enumerates 0 "
            "devices: no RealSense is attached to this host",
            self.device_remedy,
        )

    def open_pipeline(self, entry: Channel) -> ReadOnlyHandle:
        """A pipeline handle, or an actionable refusal. Never configures the device."""

        rs = self._module(entry)
        self._require_enumerated_device(rs)
        pipeline = rs.pipeline()
        return ReadOnlyHandle(
            pipeline, allowed=_PIPELINE_ALLOWLIST, label=f"realsense pipeline {entry.channel_id}"
        )

    def stream_selection(self, entry: Channel) -> Any:
        """An ``rs.config`` enabling exactly this channel's stream.

        Without one, ``pipeline.start()`` runs librealsense's DEFAULT profile —
        depth + colour — whatever stream the caller meant, and the six D455 rows
        become indistinguishable from each other. :func:`attributable` records
        the measurement that showed it.

        Resolution and rate are deliberately NOT set. They are a PS-E budget
        decision, the matrix marks these rows ``CONFIGURED`` with no nominal
        rate, and a number nobody chose is not an expectation — so this selects
        the stream and lets librealsense pick a profile for it. Selecting a
        stream is the one thing this module's docstring has always promised;
        until now it was the one thing it did not do.

        Every reach into the vendor module goes through
        :func:`~..base.read_field`, so a build that spells its enums differently
        yields a named refusal instead of an ``AttributeError`` inside a probe.
        """

        rs = self._module(entry)
        profile = STREAM_PROFILES[entry.channel_id]
        streams = read_field(rs, "stream")
        stream = read_field(streams, profile["stream"]) if present(streams) else None
        factory = read_field(rs, "config")
        if not present(stream) or not present(factory):
            raise IngestUnavailableError(
                AbsenceReason.UNPARSEABLE,
                f"{entry.channel_id}: this pyrealsense2 build exposes no "
                f"rs.stream.{profile['stream']} or no rs.config, so the stream cannot be "
                f"selected and the pipeline would deliver the default profile instead",
                "check the pyrealsense2 version on the Orin: `python -c \"import "
                "pyrealsense2 as rs; print(rs.__version__, rs.stream, rs.config)\"`. A "
                "build that cannot select a stream must not be used for the D455 rows.",
            )
        config = factory()
        index = int(profile["index"])
        if index:
            config.enable_stream(stream, index)
        else:
            config.enable_stream(stream)
        return config

    def read_frames(self, entry: Channel, window_s: float) -> Iterator[IngestFrame]:
        """Open the declared stream, collect for the window, stop.

        Two fail-closed gates, because a false PRESENT on this device is a lie in
        the session's go/no-go: the pipeline is started **against a config that
        names this channel's stream**, and any frame that does not decode as that
        stream is discarded rather than counted. A channel whose config silently
        did not take therefore reads ABSENT, which is the correct answer.
        """

        handle = self.open_pipeline(entry)
        config = self.stream_selection(entry)
        decode = decoder_for(entry)
        # ``started`` exists because an unconditional stop() MASKED the real
        # failure: measured on this box before card ENV-1, a start() that failed
        # for want of a device surfaced to the operator as
        # "probe_raised — RuntimeError: stop() cannot be called before start()",
        # which names the wrong call and offers no remedy at all.
        started = False
        try:
            handle.start(config)
            started = True
            end_ns = now_ns()[0] + int(window_s * 1e9)
            while now_ns()[0] < end_ns:
                frames = handle.poll_for_frames()
                if not frames:
                    continue
                for frame in frames:
                    samples, summary = decode(frame)
                    if not attributable(summary):
                        continue
                    yield build_frame(entry, samples, summary)
        finally:
            if started:
                handle.stop()

    def channels(self) -> tuple[Channel, ...]:
        from parcel_robot.capture import CHANNELS

        return tuple(entry for entry in CHANNELS if entry.channel_id in STREAM_PROFILES)
