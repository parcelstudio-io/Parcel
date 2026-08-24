"""Virtual PipeWire audio rig for the Tier-1 acoustic loop eval.

WHAT THIS IS
    A per-run pair of null audio sinks created through ``pw-cli``, giving the
    eval a speaker it can record sample-accurately and a microphone it can
    inject into — with no physical transducer, no root, and no changes to the
    audio code under test.

    ``<prefix>_sink``  the robot's speaker. ``SpeakerSink`` opens it through
        the ordinary ``sounddevice`` path (it enumerates as a PulseAudio
        output device), so the real player, the real ~50 ms block loop and the
        real interrupt latch are exercised. Its ``.monitor`` is the only
        honest answer to "when did audio actually start and stop", which is
        what every barge-in and ack number in this suite is anchored to.

    ``<prefix>_mic``   the owner's mouth. Corpus utterances are injected with
        ``pw-play``; ``pw-record`` on its monitor produces the 16 kHz mono
        int16 stream that ``MicrophoneVoiceLoop`` consumes through its
        ``frames`` iterable seam.

WHAT IT DOES NOT PROVE
    There is no air, no room, no transducer and no acoustic coupling between
    the speaker and the microphone. Echo is therefore absent unless a case
    mixes it in deliberately. Room acoustics, real microphone noise, real
    speaker nonlinearity and true acoustic AEC performance are Tier-2 (
    ``acoustic_rig_v1``) and are explicitly out of scope here. Every report
    this rig feeds carries that in its ``does_not_prove`` list.

LIFECYCLE
    Nodes are created with ``object.linger=true`` because ``pw-cli`` exits
    immediately after the create command and a non-lingering node dies with
    it. Lingering nodes therefore MUST be destroyed explicitly — the context
    manager does that on every exit path, and ``orphan_nodes()`` lets the
    runner assert that teardown left nothing behind.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CAPTURE_RATE_HZ = 16_000
CAPTURE_FRAME_SAMPLES = 480  # 30 ms, matching voice_audio.FRAME_SAMPLES
SINK_RATE_HZ = 48_000

_REQUIRED_TOOLS = ("pw-cli", "pw-play", "pw-record", "pw-dump")


class RigError(RuntimeError):
    """The virtual audio rig could not be brought up or torn down."""


def rig_available() -> tuple[bool, str]:
    """Whether this host can run the virtual rig, and why not when it cannot."""

    missing = [tool for tool in _REQUIRED_TOOLS if shutil.which(tool) is None]
    if missing:
        return False, f"missing PipeWire tools: {', '.join(missing)}"
    try:
        subprocess.run(
            ["pw-cli", "info", "0"],
            capture_output=True,
            timeout=10,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as error:
        return False, f"no reachable PipeWire daemon: {error}"
    return True, "ok"


def _pw_dump() -> list[dict]:
    try:
        result = subprocess.run(
            ["pw-dump"], capture_output=True, timeout=20, check=True
        )
        return json.loads(result.stdout or b"[]")
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as error:
        raise RigError(f"pw-dump failed: {error}") from error


def node_ids_by_name(name: str) -> list[int]:
    """Object ids of every live node whose ``node.name`` equals ``name``."""

    ids = []
    for entry in _pw_dump():
        if entry.get("type") != "PipeWire:Interface:Node":
            continue
        props = (entry.get("info") or {}).get("props") or {}
        if props.get("node.name") == name:
            ids.append(int(entry["id"]))
    return ids


def orphan_nodes(prefix: str) -> list[str]:
    """Names of live nodes carrying ``prefix`` — the teardown assertion."""

    names = []
    for entry in _pw_dump():
        if entry.get("type") != "PipeWire:Interface:Node":
            continue
        props = (entry.get("info") or {}).get("props") or {}
        name = str(props.get("node.name") or "")
        if name.startswith(prefix):
            names.append(name)
    return sorted(names)


@dataclass
class _Node:
    name: str
    description: str
    object_id: int | None = None


@dataclass
class AcousticRig:
    """Per-run virtual speaker + microphone. Use as a context manager."""

    prefix: str
    _nodes: list[_Node] = field(default_factory=list, init=False)
    _entered: bool = field(default=False, init=False)

    @property
    def sink_name(self) -> str:
        return f"{self.prefix}_sink"

    @property
    def sink_monitor_name(self) -> str:
        return f"{self.sink_name}.monitor"

    @property
    def mic_name(self) -> str:
        return f"{self.prefix}_mic"

    @property
    def mic_monitor_name(self) -> str:
        return f"{self.mic_name}.monitor"

    # ------------------------------------------------------------- lifecycle
    def __enter__(self) -> AcousticRig:  # noqa: PYI034 - Self needs py3.11
        ok, reason = rig_available()
        if not ok:
            raise RigError(reason)
        # Refuse to start on top of a previous run's wreckage rather than
        # silently recording the wrong node.
        leftovers = orphan_nodes(self.prefix)
        if leftovers:
            raise RigError(
                f"nodes named {leftovers} already exist; a previous run leaked. "
                "Destroy them before re-running."
            )
        try:
            self._create(self.sink_name, "Parcel Acoustic Rig Speaker")
            self._create(self.mic_name, "Parcel Acoustic Rig Microphone")
        except Exception:
            self.close()
            raise
        self._entered = True
        # PipeWire publishes the node to PulseAudio/ALSA clients asynchronously;
        # sounddevice cannot see it for a few tens of ms after create returns.
        self._await_visible()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _create(self, name: str, description: str) -> None:
        args = (
            "{ factory.name=support.null-audio-sink "
            f"node.name={name} "
            f'node.description="{description}" '
            "media.class=Audio/Sink "
            "object.linger=true "
            "audio.position=[FL] }"
        )
        try:
            subprocess.run(
                ["pw-cli", "create-node", "adapter", args],
                capture_output=True,
                timeout=20,
                check=True,
            )
        except (subprocess.SubprocessError, OSError) as error:
            raise RigError(f"could not create node {name}: {error}") from error
        node = _Node(name=name, description=description)
        self._nodes.append(node)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            ids = node_ids_by_name(name)
            if ids:
                node.object_id = ids[-1]
                return
            time.sleep(0.05)
        raise RigError(f"node {name} never appeared in pw-dump")

    def _await_visible(self, timeout_s: float = 8.0) -> None:
        """Block until sounddevice can resolve both rig nodes."""

        import sounddevice

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            sounddevice._terminate()
            sounddevice._initialize()
            names = {str(d["name"]) for d in sounddevice.query_devices()}
            if self.sink_name in names and self.mic_name in names:
                return
            time.sleep(0.1)
        raise RigError(
            f"{self.sink_name}/{self.mic_name} never became visible to PortAudio"
        )

    def close(self) -> None:
        """Destroy every node this rig created. Safe to call twice."""

        errors = []
        for node in self._nodes:
            # Destroy by CURRENT id: the id can be re-resolved because a
            # lingering node outlives the pw-cli that made it.
            for object_id in node_ids_by_name(node.name):
                try:
                    subprocess.run(
                        ["pw-cli", "destroy", str(object_id)],
                        capture_output=True,
                        timeout=20,
                        check=True,
                    )
                except (subprocess.SubprocessError, OSError) as error:
                    errors.append(f"{node.name}: {error}")
        self._nodes = []
        self._entered = False
        if errors:
            raise RigError("teardown failed: " + "; ".join(errors))

    def link_mic_into_sink(self) -> None:
        """Route everything the virtual mic hears into the speaker's monitor.

        This is what makes acoustic ack and barge-in numbers exact instead of
        approximate. With the link in place a SINGLE recording of the sink
        monitor contains both the owner's injected speech and the robot's
        reply, on one sample-accurate clock — so "end of owner speech -> first
        audible robot audio" is a subtraction inside one file rather than a
        comparison across two processes with no shared time base.

        It is NOT an echo path: the robot's output is not fed back into the
        microphone, so barge-in is not being flattered by a coupling that does
        not exist here. Echo is Tier-2.
        """

        try:
            subprocess.run(
                ["pw-link", self.mic_name, self.sink_name],
                capture_output=True,
                timeout=20,
                check=True,
            )
        except (subprocess.SubprocessError, OSError) as error:
            raise RigError(
                f"could not link {self.mic_name} into {self.sink_name}: {error}"
            ) from error

    # ------------------------------------------------------------ device ids
    def sounddevice_index(self, name: str, kind: str) -> int:
        """Resolve a rig node through the PRODUCTION device seam.

        Uses ``voice_audio.resolve_audio_device`` deliberately: the eval must
        exercise the same name-substring resolution the runtime uses, not a
        private lookup that could drift from it.
        """

        from parcel_robot.audio.voice_loop import resolve_audio_device

        index, _detail = resolve_audio_device(name, kind=kind)
        if index is None:
            raise RigError(f"{name} resolved to the system default, not a device")
        return index

    # ------------------------------------------------------------- injection
    def play_file(self, path: str | Path, *, target: str | None = None) -> None:
        """Inject a WAV into a rig node, blocking until playback finishes."""

        target = target or self.mic_name
        try:
            subprocess.run(
                ["pw-play", "--target", target, str(path)],
                capture_output=True,
                timeout=120,
                check=True,
            )
        except (subprocess.SubprocessError, OSError) as error:
            raise RigError(f"pw-play of {path} into {target} failed: {error}") from error

    def play_file_async(
        self, path: str | Path, *, target: str | None = None
    ) -> subprocess.Popen:
        """Inject a WAV without blocking (barge-in cases need overlap)."""

        target = target or self.mic_name
        return subprocess.Popen(
            ["pw-play", "--target", target, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # -------------------------------------------------------------- capture
    @contextlib.contextmanager
    def record_monitor(self, target: str, path: str | Path) -> Iterator[None]:
        """Record a node's monitor to a raw 16 kHz mono int16 file."""

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(
            [
                "pw-record",
                "--target",
                target,
                "--rate",
                str(CAPTURE_RATE_HZ),
                "--channels",
                "1",
                "--format",
                "s16",
                "--raw",
                str(path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # pw-record takes a moment to link; without this the first injected
        # samples are lost and every onset timestamp is early.
        time.sleep(0.4)
        try:
            yield
        finally:
            time.sleep(0.3)  # let the tail drain into the file
            process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
            if process.poll() is None:
                process.kill()

    def capture_frames(
        self, *, target: str | None = None, stop: threading.Event | None = None
    ) -> Iterator[np.ndarray]:
        """A ``MicrophoneVoiceLoop(frames=...)`` source backed by pw-record.

        This is the fallback-ladder rung the plan names second: the loop's
        frames-iterable seam means the whole capture path can be swapped for a
        subprocess without touching a line of voice_audio.py.
        """

        target = target or self.mic_name
        process = subprocess.Popen(
            [
                "pw-record",
                "--target",
                target,
                "--rate",
                str(CAPTURE_RATE_HZ),
                "--channels",
                "1",
                "--format",
                "s16",
                "--raw",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        chunk_bytes = CAPTURE_FRAME_SAMPLES * 2
        try:
            assert process.stdout is not None
            while stop is None or not stop.is_set():
                payload = process.stdout.read(chunk_bytes)
                if not payload or len(payload) < chunk_bytes:
                    return
                yield np.frombuffer(payload, dtype=np.int16)
        finally:
            process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
            if process.poll() is None:
                process.kill()


# --------------------------------------------------------------- analysis
def read_raw_s16(path: str | Path) -> np.ndarray:
    return np.fromfile(str(path), dtype=np.int16)


def frame_rms(samples: np.ndarray, frame: int) -> np.ndarray:
    """Non-overlapping frame RMS — the basis of every onset/offset timestamp."""

    usable = samples.size - (samples.size % frame)
    if usable <= 0:
        return np.zeros(0, dtype=np.float64)
    blocks = samples[:usable].astype(np.float64).reshape(-1, frame)
    return np.sqrt(np.mean(np.square(blocks), axis=1))


def audio_onset_s(
    samples: np.ndarray, *, threshold: float, frame: int = 160, rate: int = CAPTURE_RATE_HZ
) -> float | None:
    """First time the signal rises above ``threshold`` (10 ms resolution)."""

    rms = frame_rms(samples, frame)
    hits = np.where(rms > threshold)[0]
    if hits.size == 0:
        return None
    return float(hits[0] * frame / rate)


def audio_offset_s(
    samples: np.ndarray, *, threshold: float, frame: int = 160, rate: int = CAPTURE_RATE_HZ
) -> float | None:
    """Last time the signal is above ``threshold`` — acoustic "stopped"."""

    rms = frame_rms(samples, frame)
    hits = np.where(rms > threshold)[0]
    if hits.size == 0:
        return None
    return float((hits[-1] + 1) * frame / rate)


def sanitize_prefix(text: str) -> str:
    """PipeWire node names must be plain identifiers."""

    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", text)
    return cleaned[:48] or "parcel_rig"


def default_prefix() -> str:
    """A per-process unique node prefix so parallel runs cannot collide."""

    return sanitize_prefix(f"parcel_acoustic_{os.getpid()}")
