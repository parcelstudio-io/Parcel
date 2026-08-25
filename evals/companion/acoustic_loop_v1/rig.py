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
import selectors
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Literal

import numpy as np

CAPTURE_RATE_HZ = 16_000
CAPTURE_FRAME_SAMPLES = 480  # 30 ms, matching voice_audio.FRAME_SAMPLES
SINK_RATE_HZ = 48_000

_REQUIRED_TOOLS = ("pw-cli", "pw-play", "pw-record", "pw-dump", "pw-link")
_GRAPH_TIMEOUT_S = 5.0
_FIRST_FRAME_TIMEOUT_S = 5.0
_STDERR_TAIL_BYTES = 4096


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


def _matching_nodes(graph: list[dict], name: str) -> list[dict]:
    return [
        entry
        for entry in graph
        if entry.get("type") == "PipeWire:Interface:Node"
        and ((entry.get("info") or {}).get("props") or {}).get("node.name") == name
    ]


def _find_owned_port_id(
    node_name: str,
    *,
    direction: Literal["in", "out"],
    monitor: bool = False,
    graph: list[dict] | None = None,
) -> int | None:
    """Resolve one exact node-owned global port id, never a name pattern.

    PipeWire exposes both a top-level object id and a node-local ``port.id``.
    ``pw-link`` requires the former.  Using the local id happens to work only
    on tiny graphs and can silently link an unrelated stream as the graph
    changes, so this helper deliberately returns ``entry["id"]``.
    """

    document = _pw_dump() if graph is None else graph
    nodes = _matching_nodes(document, node_name)
    if len(nodes) > 1:
        raise RigError(f"multiple PipeWire nodes have exact name {node_name!r}")
    if not nodes:
        return None
    node_id = int(nodes[0]["id"])
    ports = []
    for entry in document:
        if entry.get("type") != "PipeWire:Interface:Port":
            continue
        props = (entry.get("info") or {}).get("props") or {}
        try:
            owner_id = int(props.get("node.id"))
        except (TypeError, ValueError):
            continue
        if owner_id != node_id or props.get("port.direction") != direction:
            continue
        if monitor and props.get("port.monitor") is not True:
            continue
        ports.append(entry)
    if len(ports) > 1:
        qualifier = " monitor" if monitor else ""
        raise RigError(
            f"node {node_name!r} has multiple {direction}{qualifier} ports; "
            "the mono rig requires exactly one"
        )
    if not ports:
        return None
    return int(ports[0]["id"])


def _owned_port_id(
    node_name: str,
    *,
    direction: Literal["in", "out"],
    monitor: bool = False,
    graph: list[dict] | None = None,
) -> int:
    """Return one exact global port id or fail closed."""

    port_id = _find_owned_port_id(
        node_name,
        direction=direction,
        monitor=monitor,
        graph=graph,
    )
    if port_id is None:
        qualifier = " monitor" if monitor else ""
        raise RigError(f"node {node_name!r} has no {direction}{qualifier} port")
    return port_id


def _matching_links(
    output_port_id: int,
    input_port_id: int,
    *,
    graph: list[dict] | None = None,
) -> list[dict]:
    """Exact links between two global port ids."""

    document = _pw_dump() if graph is None else graph
    matches = []
    for entry in document:
        if entry.get("type") != "PipeWire:Interface:Link":
            continue
        info = entry.get("info") or {}
        try:
            output_id = int(info.get("output-port-id"))
            input_id = int(info.get("input-port-id"))
        except (TypeError, ValueError):
            continue
        if output_id == output_port_id and input_id == input_port_id:
            matches.append(entry)
    return matches


@contextlib.contextmanager
def _temporary_binary_file(*, prefix: str = "", suffix: str = "") -> Iterator[BinaryIO]:
    """Own a temporary binary file while an async child may still write it."""

    with tempfile.TemporaryFile(prefix=prefix, suffix=suffix) as handle:
        yield handle


@dataclass
class _Node:
    name: str
    description: str
    object_id: int | None = None


@dataclass
class _Recorder:
    process: subprocess.Popen
    node_name: str
    source_port_id: int
    input_port_id: int
    stderr_file: BinaryIO
    cleanup: contextlib.ExitStack


@dataclass
class AcousticRig:
    """Per-run virtual speaker + microphone. Use as a context manager."""

    prefix: str
    _nodes: list[_Node] = field(default_factory=list, init=False)
    _processes: list[subprocess.Popen] = field(default_factory=list, init=False)
    _links: list[tuple[int, int]] = field(default_factory=list, init=False)
    _process_lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _stream_counter: int = field(default=0, init=False)
    _entered: bool = field(default=False, init=False)

    @property
    def sink_name(self) -> str:
        return f"{self.prefix}_sink"

    @property
    def mic_name(self) -> str:
        return f"{self.prefix}_mic"

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
            # PipeWire publishes the nodes to PulseAudio/ALSA clients
            # asynchronously; sounddevice cannot see them immediately.
            self._await_visible()
        except Exception:
            self.close()
            raise
        self._entered = True
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
        """Stop every child and destroy every node. Safe to call twice.

        Capture generators may still be waiting for selectable input when the
        voice loop stops. Their ``finally`` blocks therefore cannot be the
        sole owner of ``pw-record`` cleanup: the rig also retains every async
        child and closes it before removing the PipeWire nodes.
        """

        errors = []
        with self._process_lock:
            processes = list(self._processes)
        for process in processes:
            try:
                self._stop_process(process)
            except (OSError, subprocess.SubprocessError, RigError) as error:
                errors.append(f"child {process.args!r}: {error}")
        with self._process_lock:
            links = list(self._links)
        for output_port_id, input_port_id in links:
            try:
                self._disconnect_ports(output_port_id, input_port_id)
            except (OSError, subprocess.SubprocessError, RigError) as error:
                errors.append(
                    f"link {output_port_id}->{input_port_id}: {error}"
                )
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

    def _track_process(self, process: subprocess.Popen) -> subprocess.Popen:
        """Register an asynchronous PipeWire child with the rig lifecycle."""

        with self._process_lock:
            self._processes.append(process)
        return process

    def _stop_process(self, process: subprocess.Popen, *, timeout_s: float = 5.0) -> None:
        """Boundedly terminate, reap, and forget one tracked child.

        Rig teardown and a generator's ``finally`` can race.  Serializing the
        complete stop transaction makes two callers idempotent instead of
        letting both observe a live child and independently signal it.
        """

        with self._process_lock:
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()
                try:
                    process.wait(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                    process.wait(timeout=timeout_s)
            else:
                # Reap an already-exited child as well; Popen.wait is idempotent.
                process.wait(timeout=timeout_s)
            if process.poll() is None:
                raise RigError(f"child remained alive after kill: {process.args!r}")
            while process in self._processes:
                self._processes.remove(process)

    def live_child_processes(self) -> list[str]:
        """Commands of tracked children that survived teardown."""

        with self._process_lock:
            processes = list(self._processes)
        return [repr(process.args) for process in processes if process.poll() is None]

    def _next_stream_name(self, kind: str) -> str:
        with self._process_lock:
            self._stream_counter += 1
            suffix = self._stream_counter
        base = sanitize_prefix(self.prefix)[:32]
        return f"{base}_{sanitize_prefix(kind)[:8]}_{suffix}"

    def _await_owned_port_id(
        self,
        node_name: str,
        *,
        direction: Literal["in", "out"],
        monitor: bool = False,
        process: subprocess.Popen | None = None,
        timeout_s: float = _GRAPH_TIMEOUT_S,
    ) -> int:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                raise RigError(
                    f"PipeWire stream {node_name!r} exited before publishing its port"
                )
            port_id = _find_owned_port_id(
                node_name,
                direction=direction,
                monitor=monitor,
            )
            if port_id is not None:
                return port_id
            time.sleep(0.025)
        qualifier = " monitor" if monitor else ""
        raise RigError(
            f"node {node_name!r} did not publish one {direction}{qualifier} "
            f"port within {timeout_s:.1f}s"
        )

    def _connect_ports(
        self,
        output_port_id: int,
        input_port_id: int,
        *,
        timeout_s: float = _GRAPH_TIMEOUT_S,
    ) -> None:
        try:
            subprocess.run(
                ["pw-link", "-L", str(output_port_id), str(input_port_id)],
                capture_output=True,
                timeout=20,
                check=True,
            )
        except (subprocess.SubprocessError, OSError) as error:
            raise RigError(
                f"could not link ports {output_port_id}->{input_port_id}: {error}"
            ) from error
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            matches = _matching_links(output_port_id, input_port_id)
            if len(matches) > 1:
                raise RigError(
                    f"multiple links connect ports {output_port_id}->{input_port_id}"
                )
            if matches:
                state = str((matches[0].get("info") or {}).get("state") or "")
                if state == "error":
                    raise RigError(
                        f"PipeWire link {output_port_id}->{input_port_id} entered error"
                    )
                with self._process_lock:
                    self._links.append((output_port_id, input_port_id))
                return
            time.sleep(0.025)
        raise RigError(
            f"PipeWire never published link {output_port_id}->{input_port_id}"
        )

    def _disconnect_ports(self, output_port_id: int, input_port_id: int) -> None:
        """Remove one exact link. Safe when node teardown removed it first."""

        with self._process_lock:
            tracked = (output_port_id, input_port_id) in self._links
        if tracked and _matching_links(output_port_id, input_port_id):
            try:
                subprocess.run(
                    ["pw-link", "-d", str(output_port_id), str(input_port_id)],
                    capture_output=True,
                    timeout=20,
                    check=True,
                )
            except (subprocess.SubprocessError, OSError) as error:
                raise RigError(
                    f"could not disconnect ports {output_port_id}->{input_port_id}: {error}"
                ) from error
        with self._process_lock:
            while (output_port_id, input_port_id) in self._links:
                self._links.remove((output_port_id, input_port_id))

    @staticmethod
    def _stderr_tail(stderr_file: BinaryIO) -> str:
        try:
            stderr_file.flush()
            stderr_file.seek(0, os.SEEK_END)
            size = stderr_file.tell()
            stderr_file.seek(max(0, size - _STDERR_TAIL_BYTES))
            return stderr_file.read().decode("utf-8", errors="replace").strip()
        except (OSError, ValueError):
            return ""

    def _start_recorder(self, source_node_name: str, destination: str) -> _Recorder:
        """Start one unlinked recorder, then own and verify its exact graph link."""

        node_name = self._next_stream_name("record")
        cleanup = contextlib.ExitStack()
        stderr_file = cleanup.enter_context(
            _temporary_binary_file(prefix=f"{node_name}_", suffix=".stderr")
        )
        process = self._track_process(
            subprocess.Popen(
                [
                    "pw-record",
                    "--target",
                    "0",
                    "--properties",
                    json.dumps({"node.name": node_name, "media.name": node_name}),
                    "--rate",
                    str(CAPTURE_RATE_HZ),
                    "--channels",
                    "1",
                    "--channel-map",
                    "MONO",
                    "--format",
                    "s16",
                    "--raw",
                    destination,
                ],
                stdout=subprocess.PIPE if destination == "-" else subprocess.DEVNULL,
                stderr=stderr_file,
            )
        )
        try:
            source_port_id = self._await_owned_port_id(
                source_node_name,
                direction="out",
                monitor=True,
            )
            input_port_id = self._await_owned_port_id(
                node_name,
                direction="in",
                process=process,
            )
            self._connect_ports(source_port_id, input_port_id)
        except Exception as error:
            self._stop_process(process)
            tail = self._stderr_tail(stderr_file)
            cleanup.close()
            detail = f"; pw-record stderr: {tail}" if tail else ""
            raise RigError(f"could not start explicit recorder: {error}{detail}") from error
        return _Recorder(
            process=process,
            node_name=node_name,
            source_port_id=source_port_id,
            input_port_id=input_port_id,
            stderr_file=stderr_file,
            cleanup=cleanup,
        )

    def _finish_recorder(self, recorder: _Recorder) -> str:
        """Disconnect, stop, reap and close one recorder; return bounded stderr."""

        errors: list[str] = []
        try:
            self._disconnect_ports(recorder.source_port_id, recorder.input_port_id)
        except RigError as error:
            errors.append(str(error))
        try:
            self._stop_process(recorder.process)
        except (OSError, subprocess.SubprocessError, RigError) as error:
            errors.append(str(error))
        if recorder.process.stdout is not None:
            with contextlib.suppress(OSError):
                recorder.process.stdout.close()
        tail = self._stderr_tail(recorder.stderr_file)
        recorder.cleanup.close()
        if errors:
            raise RigError("; ".join(errors))
        return tail

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

        mic_monitor_port = self._await_owned_port_id(
            self.mic_name,
            direction="out",
            monitor=True,
        )
        sink_input_port = self._await_owned_port_id(
            self.sink_name,
            direction="in",
        )
        self._connect_ports(mic_monitor_port, sink_input_port)

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
        return self._track_process(
            subprocess.Popen(
                ["pw-play", "--target", target, str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )

    # -------------------------------------------------------------- capture
    @contextlib.contextmanager
    def record_monitor(self, target: str, path: str | Path) -> Iterator[None]:
        """Record an exact node's monitor to a raw 16 kHz mono int16 file.

        ``target`` is the source node name, not a synthetic ``.monitor`` name.
        The rig resolves its sole ``port.monitor=true`` output and explicitly
        links that global port id to an un-autolinked recorder it owns.
        """

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        recorder = self._start_recorder(target, str(path))
        try:
            yield
        finally:
            time.sleep(0.3)  # let the tail drain into the file
            self._finish_recorder(recorder)

    def capture_frames(
        self,
        *,
        target: str | None = None,
        stop: threading.Event | None = None,
        first_frame_timeout_s: float = _FIRST_FRAME_TIMEOUT_S,
    ) -> Iterator[np.ndarray]:
        """A ``MicrophoneVoiceLoop(frames=...)`` source backed by pw-record.

        This is the fallback-ladder rung the plan names second: the loop's
        frames-iterable seam means the whole capture path can be swapped for a
        subprocess without touching a line of voice_audio.py.
        """

        if first_frame_timeout_s <= 0:
            raise ValueError("first_frame_timeout_s must be positive")
        target = target or self.mic_name
        recorder = self._start_recorder(target, "-")
        process = recorder.process
        chunk_bytes = CAPTURE_FRAME_SAMPLES * 2
        buffer = bytearray()
        first_frame_deadline = time.monotonic() + first_frame_timeout_s
        selector = selectors.DefaultSelector()
        try:
            assert process.stdout is not None
            descriptor = process.stdout.fileno()
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_READ)
            while True:
                if stop is not None and stop.is_set():
                    return
                events = selector.select(timeout=0.1)
                for key, _mask in events:
                    try:
                        payload = os.read(key.fd, max(chunk_bytes, 65_536))
                    except BlockingIOError:
                        continue
                    if payload:
                        buffer.extend(payload)
                while len(buffer) >= chunk_bytes:
                    payload = bytes(buffer[:chunk_bytes])
                    del buffer[:chunk_bytes]
                    yield np.frombuffer(payload, dtype=np.int16)
                    first_frame_deadline = float("inf")
                    if stop is not None and stop.is_set():
                        return
                return_code = process.poll()
                if return_code is not None:
                    tail = self._stderr_tail(recorder.stderr_file)
                    detail = f"; stderr: {tail}" if tail else ""
                    raise RigError(
                        f"pw-record exited with {return_code} before a complete frame{detail}"
                    )
                if time.monotonic() >= first_frame_deadline:
                    tail = self._stderr_tail(recorder.stderr_file)
                    detail = f"; stderr: {tail}" if tail else ""
                    raise RigError(
                        "pw-record produced no complete microphone frame within "
                        f"{first_frame_timeout_s:.1f}s{detail}"
                    )
        finally:
            selector.close()
            self._finish_recorder(recorder)


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
