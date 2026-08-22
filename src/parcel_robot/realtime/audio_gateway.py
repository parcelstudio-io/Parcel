"""The browser audio gateway — the lane's ears and mouth (card R7, §A).

WHAT THIS IS
------------
``RealtimeLane`` has had both audio ends since R1 and neither of them was
connected to anything: ``lane.send_audio(pcm)`` wants owner microphone frames
and nothing produced them, and ``BrowserSink`` wants a "playback gateway" and
no such object existed — which is why ``runtime._build_realtime_sink`` raised
``ImportError`` on this very module name whenever ``mode: audio`` was set. This
is that object. It is the ONLY thing between the browser and the lane, and it
is deliberately not a transport: the websocket lives next door in
``serve_websocket``/``web_panel``, and everything here is policy, buffers and
counters that a test can drive with no socket at all.

THE FOUR RULES IT ENFORCES
--------------------------
1. **Fail closed on the handshake.** A connection is refused unless the panel
   has bound its per-process CSRF token AND the client presents that exact
   token (constant-time compare). No token bound ⇒ every connection is refused;
   an unauthenticated socket never reaches the lane.
2. **Connected is not listening.** Attaching gets you the SPEAKER only. Inbound
   audio is refused and counted until the owner's explicit per-connection
   gesture arrives as its own control frame (``{"type":"mic","on":true}``).
   The browser's click handler is the only thing that sends it; a page that
   merely loads gets a mouth and no ear. What the server cannot do is verify
   that a human clicked — see ``does_not_prove`` in R7_STATUS.md — but it CAN
   refuse to treat "a socket exists" as consent, and that is what this does.
3. **Bounded, always, in both directions.** Outbound playback is a deque with a
   hard frame bound and a hard byte bound; overflow drops the OLDEST frame and
   counts it, because the newest audio is the audio the owner is about to hear.
   Inbound has no queue at all — frames are dispatched on the reader thread, so
   a slow lane backpressures TCP instead of growing a buffer — plus a hard
   per-frame size cap, so one 10 MB "audio frame" is a refusal rather than an
   allocation.
4. **The played clock is clamped here.** ``BrowserSink`` reads its
   ``first_chunk_started_monotonic`` from this object, and the lane truncates
   the provider's belief about its own reply at that number. The browser is
   attacker-shaped input: it could claim playback started long ago and push the
   truncate point past what was ever transmitted. This module owns bytes-sent,
   so this module does the clamping — an ack is clamped to the audio actually
   handed to the socket AND to the moment the first byte of the current
   utterance left, and an ack for a stale utterance is dropped and counted.

WHAT IT REFUSES TO DO
---------------------
It never opens or closes a hosted session and never touches the ledger. The
mic gesture is *reported* to the runtime through ``on_mic``; whether that opens
a paid session is the runtime's decision, and if the runtime refuses the
gateway keeps the microphone shut and tells the browser why.

THE FIFTH RULE, ADDED BY CARD R17: THE TEE IS A PASSENGER
---------------------------------------------------------
:class:`SessionAudioCapture` writes both directions to WAV files when the owner
opts in. It hangs off the same two methods the relay already runs
(``accept_audio``, ``send_audio``) and is bound by one law: **it may never slow
the relay down and it may never raise into it.** Inbound audio is dispatched on
the socket reader's own thread and outbound audio runs inside ``lane.pump()``,
so a disk that blocks for 200 ms would become 200 ms of microphone latency and
a disk that raised would become ``pump failed``. Handing bytes to the tee is
therefore a bounded, lock-free-shaped enqueue that drops and counts when the
writer thread falls behind — never a write, never a wait, never an exception.

THE SIXTH RULE, ADDED BY CARD F1-SI: THE EAR LEARNS WHOSE VOICE IT IS
---------------------------------------------------------------------
:class:`~parcel_robot.realtime.voice_identity.VoiceIdentityGate` hangs off the
same ``accept_audio`` the tee does and computes ONE speaker embedding per owner
turn (~27 ms measured, once, not per frame). It obeys the tee's law — never
raise into the relay, never grow without a bound — with one deliberate
exception: it is allowed to be *slow once per turn*, because that is the card's
whole latency budget and the alternative is a verdict that arrives after the
transcript it was supposed to gate.

**What it does NOT do here is refuse audio.** Every accepted frame still goes
up to the provider, whoever spoke it, because the emergency latch is built out
of the transcript that comes back and a stranger must always be able to stop the
dog. This module records who is speaking; ``runtime.submit_realtime_transcript``
is where that fact turns into "may this sentence move the robot", and only for
the non-emergency classes.
"""

from __future__ import annotations

import hmac
import json
import logging
import math
import os
import secrets
import socket as _socket
import struct
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.frames import CloseCode, Frame, Opcode
from websockets.http11 import Request
from websockets.protocol import OPEN
from websockets.server import ServerProtocol
from websockets.typing import Subprotocol

# ---- CARD DUPLEX-1 (task_26), correction pass. One source of truth for the
# floor under a duck. ``parcel_robot.duplex`` imports nothing from
# ``parcel_robot.realtime``, so this is a leaf dependency, and ``lane.py``
# already carries it.
from parcel_robot.duplex.turn_controller import MIN_DUCK_GAIN

from .protocol import PCM16_SAMPLE_RATE_HZ

LOGGER = logging.getLogger(__name__)

#: The websocket subprotocol a panel must ask for. The CSRF token rides beside
#: it as ``parcel-csrf.<token>`` because a browser cannot set headers on a
#: WebSocket handshake and a query parameter would land in the panel's access
#: log; the subprotocol list does not.
SUBPROTOCOL_AUDIO = "parcel-audio"
CSRF_SUBPROTOCOL_PREFIX = "parcel-csrf."

#: Where the gateway lives. One path, loopback only, same origin as the panel.
GATEWAY_PATH = "/api/realtime/audio"

#: Hard cap on one inbound microphone frame. 32 KiB of mono PCM16 at 24 kHz is
#: ~683 ms — far more than any sane capture buffer, and small enough that a
#: hostile client cannot make the reader allocate.
DEFAULT_MAX_INBOUND_FRAME_BYTES = 32 * 1024

#: Outbound playback backlog. The lane coalesces to 240 ms per chunk, so 256
#: frames is roughly a minute of speech: long enough that only a browser that
#: has genuinely stopped reading overflows.
DEFAULT_MAX_OUTBOUND_FRAMES = 256

#: A second bound on the same queue, in bytes, so a build that lowers
#: ``coalesce_ms`` cannot turn the frame bound into a memory bound by accident.
DEFAULT_MAX_OUTBOUND_BYTES = 8 * 1024 * 1024

#: The websocket layer's own allocation bound, which is a DIFFERENT bound from
#: :data:`DEFAULT_MAX_INBOUND_FRAME_BYTES` and deliberately larger. Two tiers:
#: the codec refuses to allocate more than this for one frame or one reassembled
#: message and kills the socket, while the policy layer above it refuses
#: anything over the smaller cap with a stated reason and keeps the socket. A
#: single bound would have made "your capture buffer is too big" and "you are
#: attacking me" the same event.
DEFAULT_MAX_SOCKET_FRAME_BYTES = 1024 * 1024

#: How long the socket reader parks before re-checking the stop flag, and how
#: long the writer waits for work. Bounds shutdown latency, never correctness.
DEFAULT_POLL_S = 0.05

#: Control-frame vocabulary, both directions. Small on purpose: every frame the
#: browser can send is a verb this module implements, and anything else is
#: counted as a protocol error rather than ignored.
#: Card MARK-1, correction pass. How many ``played`` acks are folded into the
#: record after an interrupt before the rest are treated as stale. A browser
#: sends at most two — whatever its timer had in flight, and the one it sends on
#: receiving ``stop`` — and the bound is what stops a client that has decided to
#: keep talking from moving a counter forever.
MAX_FINAL_ACKS_PER_UTTERANCE = 4

CLIENT_MIC = "mic"
CLIENT_PLAYED = "played"
CLIENT_PONG = "pong"
SERVER_HELLO = "hello"
SERVER_MIC = "mic"
SERVER_STOP = "stop"
SERVER_UTTERANCE = "utterance"
SERVER_REFUSED = "refused"

# ---- CARD DUPLEX-1 (task_26) — the frame that turns the voice DOWN ----
#: ``{"type": "duck", "utterance": <seq>, "gain": <0..1>}``. The one control
#: frame in this protocol that changes how a reply SOUNDS without changing
#: whether it exists: nothing is dropped, nothing is discarded, and the
#: provider is told nothing at all. It carries the utterance sequence for the
#: same reason ``stop`` does — a duck that arrives after the next reply started
#: would attenuate the wrong voice, and the panel drops a mismatched one.
SERVER_DUCK = "duck"
#: Gain outside this range is clamped rather than refused. Prototype, not
#: production: an out-of-range gain from our own lane is a bug in our own code,
#: and the failure a companion can least afford is a barge-in path that raises.
#:
#: Correction pass, finding 1: the low end is ``MIN_DUCK_GAIN`` and NOT 0.0.
#: Clamping a nonsensical gain to silence is silencing the dog, which is the
#: outcome the whole "not zero on purpose" rule exists to prevent — so the
#: clamp bottoms out at the quietest AUDIBLE level instead. Imported from the
#: turn controller rather than restated so the two cannot drift; the panel's
#: literal is pinned to it by ``tests/test_duplex1_panel_duck.py``.
DUCK_GAIN_RANGE: tuple[float, float] = (MIN_DUCK_GAIN, 1.0)
# ---- END CARD DUPLEX-1 ----


#: Card R17. How many frames may wait for the capture writer thread before the
#: tee starts dropping them. 512 outbound coalesced chunks is roughly two
#: minutes of speech and 512 inbound 20 ms frames is ten seconds of microphone:
#: far more slack than a local disk ever needs, and a hard stop on the one
#: failure mode that would otherwise turn a slow disk into unbounded memory.
DEFAULT_MAX_CAPTURE_QUEUE_FRAMES = 512

#: Names inside one capture session folder.
CAPTURE_OWNER_NAME = "owner.wav"
CAPTURE_ROBOT_NAME = "robot.wav"
CAPTURE_INDEX_NAME = "index.json"

#: Index schema id. Versioned because the runner and the fixture-extraction
#: tooling both read it and a silently-changed shape is a silently-wrong fixture.
CAPTURE_INDEX_SCHEMA = "parcel.audio_capture.index.v1"

#: Canonical PCM shape for both captured streams. The gateway negotiates mono
#: PCM16 in ``hello()`` for the inbound half and the lane pins the same for the
#: outbound half, so one number describes both files.
CAPTURE_SAMPLE_WIDTH_BYTES = 2
CAPTURE_CHANNELS = 1

#: How often the index is re-written while a session is running, in seconds.
#: Bounds how much audio a KILLED process can leave written-but-unindexed;
#: a segment boundary flushes immediately regardless.
INDEX_FLUSH_INTERVAL_S = 1.0

#: Segment kinds in the index.
SEGMENT_OWNER_TURN = "owner_turn"
SEGMENT_UTTERANCE = "utterance"


def _as_int(value: object) -> int | None:
    """One browser-supplied integer, or ``None``. Card MARK-1.

    Deliberately not a refusal: an absent or unparseable channel count from a
    client that predates this field is the shipped case, and the pin — not the
    parser — is what decides whether that matters.
    """

    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class GatewayError(RuntimeError):
    """The gateway refused. Never a silent no-op."""


class GatewayAuthError(GatewayError):
    """The handshake did not present the panel's token. Fail-closed."""


class GatewayNotRunningError(GatewayError):
    """A connection arrived before ``start()`` or after ``stop()``."""


def new_capture_session_id(now: datetime | None = None) -> str:
    """A capture-session folder name: sortable, unique, and honest about scope.

    This is the id of ONE GATEWAY RUN, not of a hosted provider session. The
    gateway never learns the provider's ``rt_…`` id, and it should not: a
    session that stalls and reconnects (which happened twice in the corpus run)
    changes that id mid-conversation, and keying the recording on it would cut
    one continuous piece of audio into fragments named after an implementation
    detail the owner never sees.
    """

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"sess_{stamp}_{secrets.token_hex(3)}"


def pcm_from_playback_chunk(payload: bytes) -> bytes:
    """Unwrap one outbound playback chunk down to raw PCM.

    The lane hands the gateway a self-contained WAV per chunk (44 bytes of RIFF
    followed by ``coalesce_ms`` of PCM16), because that is what an
    ``<audio>`` element can be fed directly. Concatenating those chunks would
    produce a file with a RIFF header every 240 ms, so the tee strips each
    wrapper and writes one continuous stream instead. A payload that is not a
    WAV is passed through untouched — the sink contract does not promise a
    wrapper, and a build that stops adding one should still record.
    """

    if len(payload) < 12 or payload[0:4] != b"RIFF" or payload[8:12] != b"WAVE":
        return payload
    offset = 12
    while offset + 8 <= len(payload):
        chunk_id = payload[offset : offset + 4]
        (size,) = struct.unpack_from("<I", payload, offset + 4)
        body = offset + 8
        if chunk_id == b"data":
            end = len(payload) if size == 0 or body + size > len(payload) else body + size
            return payload[body:end]
        offset = body + size + (size & 1)
    return b""


def _wav_header(*, data_bytes: int, sample_rate_hz: int) -> bytes:
    """A 44-byte canonical PCM16 mono RIFF header for ``data_bytes`` of payload."""

    block_align = CAPTURE_CHANNELS * CAPTURE_SAMPLE_WIDTH_BYTES
    return b"".join(
        (
            b"RIFF",
            struct.pack("<I", 36 + data_bytes),
            b"WAVEfmt ",
            struct.pack("<IHHIIHH", 16, 1, CAPTURE_CHANNELS, sample_rate_hz,
                        sample_rate_hz * block_align, block_align,
                        CAPTURE_SAMPLE_WIDTH_BYTES * 8),
            b"data",
            struct.pack("<I", data_bytes),
        )
    )


def verify_capture_index(index: Any, *, session_dir: str | Path | None = None) -> list[str]:
    """Check an index against its own invariants. Empty list ⇒ the index holds.

    THE INVARIANT, AND WHY IT IS THE WHOLE POINT OF THE INDEX
    ---------------------------------------------------------
    A per-utterance index only earns its keep if a byte range in it is the
    SAME audio a listener hears at that offset in the WAV. Everything here
    exists to make drift impossible rather than unlikely:

    * segments **tile** the file — the first starts at byte 0, each one begins
      exactly where the previous ended, and the last ends at ``data_bytes``.
      There is no "unaccounted audio" state to drift into;
    * times are **derived from bytes**, not measured from a clock, so
      ``t0_s`` and ``t1_s`` cannot disagree with the offsets they describe even
      if the writer thread was descheduled for a second;
    * ``data_bytes`` is checked against the file on disk when the folder is
      given, which is what catches a header patched to the wrong size.

    Returns human-readable problems so a test (and the corpus runner) can print
    them, rather than raising on the first one.
    """

    problems: list[str] = []
    if not isinstance(index, Mapping):
        return [f"index is {type(index).__name__}, not a mapping"]
    if index.get("schema") != CAPTURE_INDEX_SCHEMA:
        problems.append(f"schema is {index.get('schema')!r}, expected {CAPTURE_INDEX_SCHEMA!r}")
    rate = index.get("sample_rate_hz")
    if not isinstance(rate, int) or rate <= 0:
        problems.append(f"sample_rate_hz is {rate!r}")
        rate = 0
    streams = index.get("streams")
    if not isinstance(streams, Mapping) or not streams:
        return problems + ["index has no streams"]
    bytes_per_second = float(rate * CAPTURE_SAMPLE_WIDTH_BYTES * CAPTURE_CHANNELS) if rate else 0.0
    for name, stream in streams.items():
        if not isinstance(stream, Mapping):
            problems.append(f"{name}: stream is not a mapping")
            continue
        data_bytes = stream.get("data_bytes")
        if not isinstance(data_bytes, int) or data_bytes < 0:
            problems.append(f"{name}: data_bytes is {data_bytes!r}")
            continue
        block = CAPTURE_SAMPLE_WIDTH_BYTES * CAPTURE_CHANNELS
        if data_bytes % block:
            problems.append(f"{name}: data_bytes {data_bytes} is not a whole {block}-byte sample")
        segments = stream.get("segments")
        if not isinstance(segments, list):
            problems.append(f"{name}: segments is {type(segments).__name__}, not a list")
            continue
        cursor = 0
        for position, segment in enumerate(segments):
            if not isinstance(segment, Mapping):
                problems.append(f"{name}[{position}]: segment is not a mapping")
                break
            start = segment.get("start_byte")
            end = segment.get("end_byte")
            if not isinstance(start, int) or not isinstance(end, int):
                problems.append(f"{name}[{position}]: byte range is {start!r}..{end!r}")
                break
            if start != cursor:
                problems.append(
                    f"{name}[{position}]: starts at {start} but the previous segment "
                    f"ended at {cursor} — the index does not tile the file"
                )
            if end < start:
                problems.append(f"{name}[{position}]: end {end} precedes start {start}")
            if bytes_per_second:
                for field, offset in (("t0_s", start), ("t1_s", end)):
                    expected = offset / bytes_per_second
                    actual = segment.get(field)
                    if not isinstance(actual, (int, float)) or abs(float(actual) - expected) > 1e-6:
                        problems.append(
                            f"{name}[{position}]: {field}={actual!r} does not match byte "
                            f"offset {offset} at {rate} Hz (expected {expected:.6f})"
                        )
            cursor = max(cursor, end)
        if segments and cursor != data_bytes:
            problems.append(
                f"{name}: segments end at {cursor} but the stream holds {data_bytes} "
                f"bytes — {abs(data_bytes - cursor)} bytes of audio are unindexed"
            )
        if session_dir is not None and isinstance(stream.get("path"), str):
            wav = Path(session_dir) / str(stream["path"])
            if wav.is_file():
                on_disk = wav.stat().st_size - 44
                if on_disk != data_bytes:
                    problems.append(
                        f"{name}: {wav.name} holds {on_disk} payload bytes, index says "
                        f"{data_bytes}"
                    )
    return problems


class _CaptureStream:
    """One direction's WAV file and its segment list. Writer-thread only.

    Never touched by the relay: every method here runs on
    :class:`SessionAudioCapture`'s single writer thread, which is what lets it
    do real file I/O without a lock and without a latency budget.
    """

    def __init__(self, *, name: str, path: Path, sample_rate_hz: int) -> None:
        self.name = name
        self.path = path
        self.sample_rate_hz = int(sample_rate_hz)
        self.bytes_per_second = float(
            self.sample_rate_hz * CAPTURE_SAMPLE_WIDTH_BYTES * CAPTURE_CHANNELS
        )
        self.data_bytes = 0
        self.frames = 0
        self.frames_dropped = 0
        self.segments: list[dict[str, Any]] = []
        self._open: dict[str, Any] | None = None
        self._handle: Any = None
        self.last_frame_wall: float | None = None

    # -------------------------------------------------------------- file I/O
    def _ensure_open(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("wb")
        handle.write(_wav_header(data_bytes=0, sample_rate_hz=self.sample_rate_hz))
        handle.flush()
        self._handle = handle

    def write(self, payload: bytes) -> None:
        if not payload:
            return
        self._ensure_open()
        self._handle.write(payload)
        self.data_bytes += len(payload)
        self.frames += 1

    def patch_header(self) -> None:
        """Make the on-disk RIFF sizes agree with what has been written.

        Called after every drained batch. A WAV whose header still says zero is
        a file every player refuses, so a crash mid-session would otherwise cost
        the entire recording rather than the last few frames of it.
        """

        if self._handle is None:
            return
        self._handle.flush()
        position = self._handle.tell()
        self._handle.seek(4)
        self._handle.write(struct.pack("<I", 36 + self.data_bytes))
        self._handle.seek(40)
        self._handle.write(struct.pack("<I", self.data_bytes))
        self._handle.seek(position)
        self._handle.flush()

    def close_file(self) -> None:
        if self._handle is None:
            return
        self.patch_header()
        self._handle.close()
        self._handle = None

    # ------------------------------------------------------------- segments
    def open_segment(self, *, kind: str, utterance: int | None, wall: float) -> None:
        self.close_segment()
        self._open = {
            "index": len(self.segments),
            "kind": kind,
            "utterance": utterance,
            "start_byte": self.data_bytes,
            "end_byte": self.data_bytes,
            "t0_s": self.data_bytes / self.bytes_per_second,
            "t1_s": self.data_bytes / self.bytes_per_second,
            "started_at": _iso(wall),
            "ended_at": _iso(wall),
            "frames": 0,
            "interrupted": False,
            # True while this segment is still being written to. An index
            # flushed mid-session includes it, provisionally closed at the
            # current byte offset, so the tiling invariant holds at every
            # instant rather than only after a clean shutdown.
            "open": True,
        }

    def note_frame(self) -> None:
        if self._open is not None:
            self._open["frames"] = int(self._open["frames"]) + 1

    def mark_interrupted(self, wall: float | None = None, onset_ago_s: float | None = None) -> None:
        """Mark the open robot segment barged in on, and say WHEN.

        Card MARK-1, correction pass, defect 5 — AIR-1's handoff. ``interrupted``
        alone answers "was this reply cut off"; the through-air work needs "cut
        off WHEN", because the whole measurement is a latency: the owner's voice
        reaches the array at one instant and this WAV stops at another, and
        without a stamp the second instant can only be recovered by counting
        bytes and assuming the tee never dropped one.

        ``wall`` is the clock read by ``_offer`` on the RELAY thread, i.e. the
        moment ``interrupt()`` actually ran — not the moment the writer thread
        got round to this queue entry, which can be a whole drain batch later.
        Absent ⇒ the field is simply not written, so an older caller records
        exactly what it always did.
        """

        if self._open is None:
            return
        self._open["interrupted"] = True
        if wall is not None:
            self._open["interrupted_at"] = _iso(wall)
            self._open["interrupted_byte"] = self.data_bytes
            self._open["interrupted_t_s"] = self.data_bytes / self.bytes_per_second
            # ---- CARD DUPLEX-1 (task_26) — MARK-1's H-7, taken ----
            # ``interrupted_at`` is the COMMIT. With a backchannel floor > 0 the
            # owner started talking a whole floor earlier, and the latency AIR-1
            # measures starts there. ``onset_ago_s`` is a duration so the two
            # clocks (the lane's monotonic, the tee's wall) never have to be
            # reconciled; absent ⇒ nothing is written and the index is exactly
            # what MARK-1 shipped.
            if onset_ago_s is not None:
                ago = max(0.0, float(onset_ago_s))
                self._open["interrupted_onset_at"] = _iso(wall - ago)
                self._open["interrupt_hold_ms"] = round(ago * 1000.0, 3)
            # ---- END CARD DUPLEX-1 ----

    def close_segment(self, wall: float | None = None) -> None:
        segment = self._open
        if segment is None:
            return
        segment["end_byte"] = self.data_bytes
        segment["t1_s"] = self.data_bytes / self.bytes_per_second
        segment["open"] = False
        if wall is not None:
            segment["ended_at"] = _iso(wall)
        self.segments.append(segment)
        self._open = None

    @property
    def seconds(self) -> float:
        return self.data_bytes / self.bytes_per_second

    def as_index(self) -> dict[str, Any]:
        """The index of this stream AS OF NOW, including the segment in flight.

        The open segment is reported provisionally closed at the current byte
        offset. Without it a mid-session flush would describe fewer bytes than
        the WAV holds, and ``verify_capture_index`` would (correctly) call that
        unindexed audio — so the crash-tolerant flush would ship an index that
        fails its own invariant.
        """

        segments = list(self.segments)
        if self._open is not None:
            provisional = dict(self._open)
            provisional["end_byte"] = self.data_bytes
            provisional["t1_s"] = self.data_bytes / self.bytes_per_second
            segments.append(provisional)
        return {
            "path": self.path.name,
            "data_bytes": self.data_bytes,
            "duration_s": round(self.seconds, 6),
            "frames": self.frames,
            "frames_dropped": self.frames_dropped,
            "segments": segments,
        }


def _iso(wall: float) -> str:
    return datetime.fromtimestamp(wall, tz=timezone.utc).isoformat().replace("+00:00", "Z")


class SessionAudioCapture:
    """The bounded, non-blocking tee (card R17, work item 1).

    WHAT IT WRITES
    --------------
    ``<root>/<session_id>/owner.wav`` — exactly the microphone audio the lane
    was given, i.e. what the provider heard; ``robot.wav`` — exactly the hosted
    speech the gateway was asked to play, unwrapped from its per-chunk RIFF;
    ``index.json`` — the tiling of both files into segments, so one turn can be
    cut out and dropped into a corpus as a fixture.

    WHY THE ROBOT HALF RECORDS EVEN WITH NOBODY CONNECTED
    -----------------------------------------------------
    ``send_audio`` drops playback when no browser is attached, and counts it.
    The tee still records it, because the file answers "what did the robot say"
    and not "what came out of a speaker". A reply the owner missed because
    their tab was closed is exactly the kind of thing an investigation wants.

    THE THREE BOUNDS
    ----------------
    1. the queue (``max_queue_frames``): full ⇒ the frame is DROPPED and
       counted, never awaited;
    2. the clock (``max_minutes``): reached ⇒ capture closes itself, logs once
       and never touches the session;
    3. the blast radius: every producer-side entry point swallows its own
       exceptions and disables the tee rather than propagating into the relay.
    """

    def __init__(
        self,
        *,
        root: str | Path,
        session_id: str | None = None,
        sample_rate_hz: int = PCM16_SAMPLE_RATE_HZ,
        max_minutes: float = 30.0,
        owner_gap_s: float = 0.75,
        max_queue_frames: int = DEFAULT_MAX_CAPTURE_QUEUE_FRAMES,
        on_event: Callable[[str], None] | None = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.session_id = session_id or new_capture_session_id()
        self.root = Path(root)
        self.directory = self.root / self.session_id
        self.sample_rate_hz = int(sample_rate_hz)
        self.max_seconds = max(0.0, float(max_minutes) * 60.0)
        self.owner_gap_s = max(0.0, float(owner_gap_s))
        self._max_queue = max(1, int(max_queue_frames))
        self._on_event = on_event
        self._wall = wall_clock

        self._queue: deque[tuple[str, Any, float]] = deque()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._running = False
        self._stopping = False

        self.stopped_reason = ""
        self.frames_dropped_queue_full = 0
        self.frames_dropped_after_stop = 0
        self.writer_errors = 0
        self.index_writes = 0
        self.started_at = ""
        self.closed_at = ""
        self._last_index_flush = 0.0

        self._owner = _CaptureStream(
            name="owner",
            path=self.directory / CAPTURE_OWNER_NAME,
            sample_rate_hz=self.sample_rate_hz,
        )
        self._robot = _CaptureStream(
            name="robot",
            path=self.directory / CAPTURE_ROBOT_NAME,
            sample_rate_hz=self.sample_rate_hz,
        )

    # -------------------------------------------------------------- lifecycle
    @property
    def running(self) -> bool:
        return self._running

    @property
    def index_path(self) -> Path:
        return self.directory / CAPTURE_INDEX_NAME

    def start(self) -> None:
        """Arm the tee. The FOLDER is not created here — the first frame does it.

        Lazy creation is deliberate: a stack that boots with capture on and is
        never spoken to should leave nothing behind, so an empty folder never
        becomes evidence of a session that did not happen.
        """

        with self._lock:
            if self._running:
                return
            self._running = True
            self._stopping = False
            self.started_at = _iso(self._wall())
        thread = threading.Thread(
            target=self._writer_loop, name="parcel-audio-capture", daemon=True
        )
        self._thread = thread
        thread.start()
        self._note(f"audio capture armed: {self.directory} (cap {self._cap_text()} per stream)")

    def close(self, reason: str = "closed") -> None:
        """Drain, finalize both WAVs, write the index. Idempotent, never raises."""

        with self._lock:
            if not self._running:
                return
            self._stopping = True
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        self._finalize(reason)

    # --------------------------------------------------------- producer side
    def offer_owner(self, payload: bytes) -> bool:
        """Tee one accepted microphone frame. Non-blocking; True when queued."""

        return self._offer("owner", payload)

    def offer_robot(self, payload: bytes) -> bool:
        """Tee one playback chunk. Non-blocking; True when queued."""

        return self._offer("robot", payload)

    def begin_utterance(self, sequence: int) -> None:
        """Cut a new robot segment for hosted utterance ``sequence``."""

        self._offer("utterance", int(sequence))

    def note_interrupt(self, sequence: int, onset_ago_s: float | None = None) -> None:
        """Mark the current robot segment as barged in on.

        Card DUPLEX-1: the queued payload carries how long BEFORE this call the
        owner started speaking, because with MARK-1's floor at 0 the two were
        the same instant and with a floor they are not. ``sequence`` has never
        been read on the writer side (the open segment IS the current
        utterance) and is kept in the signature for its callers.
        """

        del sequence
        self._offer("interrupt", None if onset_ago_s is None else float(onset_ago_s))

    def _offer(self, kind: str, payload: Any) -> bool:
        # THE RELAY-PATH CONTRACT lives in these eight lines. No file I/O, no
        # lock the writer thread can hold across a write, no unbounded growth,
        # and no exception type that can reach ``accept_audio`` or ``pump()``.
        try:
            if not self._running or self._stopping:
                if self._running or self.stopped_reason:
                    self.frames_dropped_after_stop += 1
                return False
            if len(self._queue) >= self._max_queue:
                self.frames_dropped_queue_full += 1
                return False
            self._queue.append((kind, payload, self._wall()))
            self._wake.set()
            return True
        except Exception:  # noqa: BLE001 - the tee may never break the relay
            self.writer_errors += 1
            self._running = False
            return False

    # ----------------------------------------------------------- writer side
    def _writer_loop(self) -> None:
        while True:
            if not self._queue:
                if self._stopping:
                    return
                self._wake.wait(0.05)
                self._wake.clear()
                continue
            try:
                self._drain()
            except Exception:  # a broken tee stops itself; the lane never sees it
                self.writer_errors += 1
                self._stopping = True
                LOGGER.warning("audio capture writer failed; capture stopped", exc_info=True)
                return

    def _drain(self) -> None:
        touched: set[str] = set()
        cut = False
        while self._queue:
            kind, payload, wall = self._queue.popleft()
            if self.stopped_reason:
                self.frames_dropped_after_stop += 1
                continue
            if kind == "owner":
                cut = self._write_owner(payload, wall) or cut
                touched.add("owner")
            elif kind == "robot":
                self._write_robot(payload, wall)
                touched.add("robot")
            elif kind == "utterance":
                self._robot.close_segment(wall)
                self._robot.open_segment(
                    kind=SEGMENT_UTTERANCE, utterance=int(payload), wall=wall
                )
                touched.add("robot")
                cut = True
            elif kind == "interrupt":
                # Card MARK-1, correction pass: the wall stamp ``note_interrupt``
                # queued, not ``self._wall()`` now. See ``mark_interrupted``.
                # Card DUPLEX-1: the payload is the onset offset, or None.
                self._robot.mark_interrupted(wall, onset_ago_s=payload)
                touched.add("robot")
            if self._over_cap():
                self._stop_at_cap()
                return
        if "owner" in touched:
            self._owner.patch_header()
        if "robot" in touched:
            self._robot.patch_header()
        # Flush the index at every segment boundary and at most once a second
        # otherwise. Learned the hard way in this card's own live proof: the
        # stack was killed rather than closed, both WAVs survived intact
        # (headers are patched every batch) and the index — written only at
        # close — was simply absent. An index that exists only after a clean
        # shutdown is missing exactly when an investigation needs it.
        #
        # The residual is stated rather than hidden: a killed process can leave
        # up to one second of audio written but unindexed, and
        # ``verify_capture_index`` reports exactly how many bytes that is.
        now = time.monotonic()
        if touched and (cut or now - self._last_index_flush >= INDEX_FLUSH_INTERVAL_S):
            self._last_index_flush = now
            self._write_index()

    def _write_owner(self, payload: bytes, wall: float) -> bool:
        """Write one microphone frame. True when it started a NEW owner segment."""

        stream = self._owner
        gap = stream.last_frame_wall is not None and (
            wall - stream.last_frame_wall > self.owner_gap_s
        )
        cut = stream._open is None or gap
        if cut:
            stream.close_segment(wall)
            stream.open_segment(kind=SEGMENT_OWNER_TURN, utterance=None, wall=wall)
        stream.write(payload)
        stream.note_frame()
        stream.last_frame_wall = wall
        return cut

    def _write_robot(self, payload: bytes, wall: float) -> None:
        stream = self._robot
        pcm = pcm_from_playback_chunk(payload)
        if stream._open is None:
            # Audio before any ``begin_utterance``. Recorded under utterance 0
            # rather than dropped, because untagged audio is still audio and an
            # index that silently omits bytes is exactly the drift this design
            # refuses to allow.
            stream.open_segment(kind=SEGMENT_UTTERANCE, utterance=0, wall=wall)
        stream.write(pcm)
        stream.note_frame()
        stream.last_frame_wall = wall

    def _over_cap(self) -> bool:
        if self.max_seconds <= 0.0:
            return False
        return self._owner.seconds >= self.max_seconds or self._robot.seconds >= self.max_seconds

    def _cap_text(self) -> str:
        if self.max_seconds < 60.0:
            return f"{self.max_seconds:.3g} s"
        return f"{self.max_seconds / 60.0:.3g} min"

    def _stop_at_cap(self) -> None:
        self.stopped_reason = "max_minutes_reached"
        self._note(
            f"audio capture reached its {self._cap_text()} cap and stopped; the "
            f"session is UNAFFECTED and keeps running"
        )
        self._finalize(self.stopped_reason)

    # -------------------------------------------------------------- finalize
    def _finalize(self, reason: str) -> None:
        with self._lock:
            if not self._running and self.closed_at:
                return
            self._running = False
            self._stopping = True
        wall = self._wall()
        self.stopped_reason = self.stopped_reason or reason
        self.closed_at = _iso(wall)
        try:
            self._owner.close_segment(wall)
            self._robot.close_segment(wall)
            self._owner.close_file()
            self._robot.close_file()
            self._write_index()
        except OSError:
            self.writer_errors += 1
            LOGGER.warning("audio capture could not be finalized", exc_info=True)

    def build_index(self) -> dict[str, Any]:
        return {
            "schema": CAPTURE_INDEX_SCHEMA,
            "session_id": self.session_id,
            "sample_rate_hz": self.sample_rate_hz,
            "sample_width_bytes": CAPTURE_SAMPLE_WIDTH_BYTES,
            "channels": CAPTURE_CHANNELS,
            "started_at": self.started_at,
            "closed_at": self.closed_at,
            "max_minutes": round(self.max_seconds / 60.0, 6),
            "owner_gap_s": self.owner_gap_s,
            "stopped_reason": self.stopped_reason,
            "frames_dropped_queue_full": self.frames_dropped_queue_full,
            "frames_dropped_after_stop": self.frames_dropped_after_stop,
            "writer_errors": self.writer_errors,
            "streams": {
                "owner": self._owner.as_index(),
                "robot": self._robot.as_index(),
            },
        }

    def _write_index(self) -> None:
        if self._owner.data_bytes == 0 and self._robot.data_bytes == 0:
            return  # nothing was ever captured; leave no folder behind
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.index_path
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.build_index(), indent=1, sort_keys=False) + "\n", encoding="utf-8"
        )
        os.replace(temporary, target)
        self.index_writes += 1

    def snapshot(self) -> dict[str, object]:
        return {
            "enabled": True,
            "running": self._running,
            "session_id": self.session_id,
            "directory": str(self.directory),
            "max_minutes": round(self.max_seconds / 60.0, 6),
            "stopped_reason": self.stopped_reason,
            "owner_bytes": self._owner.data_bytes,
            "owner_seconds": round(self._owner.seconds, 3),
            "owner_segments": len(self._owner.segments) + (1 if self._owner._open else 0),
            "robot_bytes": self._robot.data_bytes,
            "robot_seconds": round(self._robot.seconds, 3),
            "robot_segments": len(self._robot.segments) + (1 if self._robot._open else 0),
            "frames_dropped_queue_full": self.frames_dropped_queue_full,
            "frames_dropped_after_stop": self.frames_dropped_after_stop,
            "queued": len(self._queue),
            "max_queue_frames": self._max_queue,
            "writer_errors": self.writer_errors,
        }

    def _note(self, message: str) -> None:
        hook = self._on_event
        if hook is None:
            return
        try:
            hook(message)
        except (RuntimeError, TypeError, ValueError):  # pragma: no cover - defensive
            pass


class _Connection:
    """One browser socket's outbound queue and its liveness flags.

    Owned by the gateway (which fills the queue from the lane's pump thread)
    and drained by :func:`serve_websocket` (which owns the socket).
    """

    def __init__(self, *, max_frames: int, max_bytes: int) -> None:
        self.outbox: deque[bytes | str] = deque()
        self.queued_bytes = 0
        self.max_frames = max_frames
        self.max_bytes = max_bytes
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.mic_open = False
        self.close_reason = ""

    def push(self, frame: bytes | str) -> int:
        """Enqueue one frame. Returns how many frames were dropped to fit it."""

        dropped = 0
        size = len(frame)
        self.outbox.append(frame)
        self.queued_bytes += size
        while len(self.outbox) > self.max_frames or self.queued_bytes > self.max_bytes:
            # Oldest first: the newest audio is the audio the owner is about to
            # hear, and a queue this deep means the browser stopped reading.
            evicted = self.outbox.popleft()
            self.queued_bytes -= len(evicted)
            dropped += 1
            if not self.outbox:  # pragma: no cover - only if one frame > max_bytes
                break
        self.wake.set()
        return dropped

    def drain(self) -> list[bytes | str]:
        frames = list(self.outbox)
        self.outbox.clear()
        self.queued_bytes = 0
        self.wake.clear()
        return frames

    def discard(self) -> int:
        """Throw the queue away; report how many PLAYBACK frames went with it.

        Control frames are dropped too but not counted: the only one that can be
        pending here is the ``utterance`` marker for the reply being cancelled,
        and counting it would make "four chunks of speech were cut off" read as
        five.
        """

        audio = sum(1 for frame in self.outbox if isinstance(frame, bytes))
        self.outbox.clear()
        self.queued_bytes = 0
        return audio


class BrowserAudioGateway:
    """Loopback bridge between one browser and one :class:`RealtimeLane`.

    Satisfies ``browser_sink.PlaybackGateway`` (``begin_utterance`` /
    ``send_audio`` / ``interrupt`` / ``played_started_monotonic``) and owns the
    inbound half through :meth:`accept_audio`.
    """

    def __init__(
        self,
        *,
        on_audio: Callable[[bytes], None],
        on_mic: Callable[[bool], None] | None = None,
        on_event: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sample_rate_hz: int = PCM16_SAMPLE_RATE_HZ,
        max_inbound_frame_bytes: int = DEFAULT_MAX_INBOUND_FRAME_BYTES,
        max_outbound_frames: int = DEFAULT_MAX_OUTBOUND_FRAMES,
        max_outbound_bytes: int = DEFAULT_MAX_OUTBOUND_BYTES,
        capture: SessionAudioCapture | None = None,
        voice_identity: Any | None = None,
        capture_channels: int = 1,
        capture_beam: int | None = None,
    ) -> None:
        self._on_audio = on_audio
        self._on_mic = on_mic
        self._on_event = on_event
        #: Card R17. The optional tee. ``None`` is the shipped default and means
        #: every audio path here is byte-for-byte what R7 shipped.
        self._capture = capture
        #: Card F1-SI. The optional speaker-identity gate. ``None`` — and a gate
        #: with no enrolled profile — both mean every audio path here is
        #: byte-for-byte what R7/R17 shipped, and the gate says which it is.
        self._voice_identity = voice_identity
        self._clock = clock
        #: Card MARK-1. Which ear the browser is told to open. The reSpeaker
        #: XVF3800 presents TWO capture channels (measured on this host:
        #: ``hw:2,0`` is S16_LE / 16 kHz / CHANNELS: 2) — ch0 is the conference
        #: beam and ch1 is the ASR beam — and asking for one channel makes the
        #: audio stack DOWNMIX them, which is a different, worse microphone than
        #: either. ``capture_beam=None`` is the shipped default and pins
        #: nothing: the ear is whatever the browser opened, recorded and stated
        #: but never refused. Set it and the pin becomes a refusal (card AIR-1
        #: commissions the array and decides that).
        self._capture_channels = max(1, int(capture_channels))
        self._capture_beam = None if capture_beam is None else max(0, int(capture_beam))
        self._sample_rate_hz = int(sample_rate_hz)
        self._bytes_per_ms = (self._sample_rate_hz * 2) / 1000.0
        self._max_inbound_frame_bytes = int(max_inbound_frame_bytes)
        self._max_outbound_frames = max(1, int(max_outbound_frames))
        self._max_outbound_bytes = max(1, int(max_outbound_bytes))

        self._lock = threading.RLock()
        self._token: str | None = None
        self._running = False
        self._conn: _Connection | None = None

        #: Current utterance, its transmitted size, and its clamped anchor.
        self._utterance_seq = 0
        self._sent_bytes_this_utterance = 0
        self._first_send_at: float | None = None
        self._played_started: float | None = None
        #: Card MARK-1. The monotonic floor under this utterance's acks, and the
        #: one-final-ack slot an interrupt opens. See :meth:`ack_played`.
        self._played_ack_ms = 0.0
        #: Card MARK-1, correction pass. Set while the browser reports its
        #: schedule has run dry; ``None`` means playback is live.
        self._playback_drained_ms: float | None = None
        self._interrupted_seq = 0
        self._interrupted_sent_ms = 0.0
        self._final_ack_seen = True

        # ------------------------------------------------------------ counters
        self.connections = 0
        self.connections_refused = 0
        self.connections_displaced = 0
        self.mic_opens = 0
        self.mic_refusals = 0
        #: Card R16. Microphones shut by ``close_mic`` — i.e. by the runtime,
        #: because the lane hung up on an idle session. Never the owner's own
        #: click (that path is ``set_mic``), so the two cannot be confused.
        self.mic_closes_by_runtime = 0
        self.frames_in = 0
        self.bytes_in = 0
        self.frames_refused_unarmed = 0
        self.frames_oversize = 0
        self.frames_out = 0
        self.bytes_out = 0
        self.frames_dropped_backpressure = 0
        self.frames_dropped_no_client = 0
        #: Queued playback thrown away by a barge-in. Deliberately NOT folded
        #: into ``frames_dropped_backpressure``: that counter means "the browser
        #: stopped reading", which is a defect, and this one means "the owner
        #: interrupted", which is the product working. One number for both would
        #: make a panel with a stalled socket look exactly like a chatty owner.
        self.frames_discarded_interrupt = 0
        self.utterances = 0
        self.interrupts = 0
        self.played_acks = 0
        self.stale_acks = 0
        #: Card MARK-1. Acks that reported LESS heard audio than an earlier ack
        #: for the same utterance. Kept apart from ``stale_acks`` on purpose: a
        #: stale ack is a frame about a reply that is over, and this one is a
        #: client whose playback bookkeeping is wrong about the reply in flight.
        self.regressive_acks = 0
        #: Acks that reported the browser's schedule had run dry.
        self.drained_acks = 0
        #: The single post-interrupt ack, and the position it reported.
        self.final_acks = 0
        self.last_final_played_ms: float | None = None
        #: Card MARK-1. Mic arms refused because the ear the browser opened was
        #: not the beam this gateway pins. Only ever non-zero when a beam IS
        #: pinned; unpinned is the shipped default and refuses nothing.
        self.capture_pin_refusals = 0
        #: What the browser last reported about the ear it actually opened.
        self.capture_channels_reported: int | None = None
        self.capture_beam_reported: int | None = None
        # ---- CARD DUPLEX-1 (task_26) — the duck, from outside ----
        #: Duck frames actually sent, of which how many were a return to unity,
        #: and the level of the last one. ``duck_refusals`` is a duck with no
        #: reply to attenuate (or nobody listening) — counted rather than sent,
        #: because a duck applied to the NEXT reply is a bug that would only
        #: ever be heard, never logged.
        self.ducks = 0
        self.duck_resumes = 0
        self.duck_refusals = 0
        self.last_duck_gain: float | None = None
        # ---- END CARD DUPLEX-1 ----
        self.control_errors = 0

    # --------------------------------------------------------------- lifecycle
    def bind_token(self, token: str) -> None:
        """Adopt the panel's per-process CSRF token. The only key that opens this."""

        clean = str(token).strip()
        with self._lock:
            self._token = clean or None

    def start(self) -> None:
        with self._lock:
            self._running = True
            capture = self._capture
        if capture is not None:
            capture.start()
        self._note("audio gateway armed (idle; no microphone until the owner asks)")

    def _end_voice_turn(self) -> None:
        """Card F1-SI. The microphone shut, so the owner turn in flight is over.

        Settles the gate's current turn instead of leaving it open across a
        silence the gate will never see frames for. Without it a turn that ended
        because the owner released the button would keep its ``pending`` verdict
        until the next turn's first frame — and a transcript that arrived in
        between would refuse to arm for the wrong reason.

        Best-effort by construction: the gate swallows its own failures, and
        this method exists on the shutdown path where nothing may raise.
        """

        with self._lock:
            identity = self._voice_identity
        if identity is not None:
            identity.end_turn()

    def stop(self) -> None:
        self._end_voice_turn()
        with self._lock:
            self._running = False
            conn = self._conn
            self._conn = None
            capture = self._capture
        if capture is not None:
            capture.close("gateway stopped")
        if conn is not None:
            conn.close_reason = "gateway stopped"
            conn.closed.set()
            conn.wake.set()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def connected(self) -> bool:
        with self._lock:
            conn = self._conn
            return conn is not None and not conn.closed.is_set()

    @property
    def mic_open(self) -> bool:
        with self._lock:
            conn = self._conn
            return bool(conn is not None and not conn.closed.is_set() and conn.mic_open)

    # ------------------------------------------------------------- handshake
    def authorize(self, token: str | None) -> None:
        """Raise unless this is the panel. No bound token ⇒ nothing is the panel."""

        with self._lock:
            expected = self._token
            running = self._running
        if not running:
            raise GatewayNotRunningError("audio gateway is not running")
        if not expected:
            raise GatewayAuthError(
                "audio gateway has no panel token bound; the panel server binds "
                "one at startup. Refusing every connection is the fail-closed answer."
            )
        if not token or not hmac.compare_digest(str(token), expected):
            raise GatewayAuthError("audio gateway handshake presented no valid panel token")

    def attach(self, token: str | None) -> _Connection:
        """Authorize, then claim the single connection slot. Newest wins.

        A reloaded page leaves a socket that TCP has not noticed yet; refusing
        the new one would lock the owner out of their own robot until a keepalive
        expired. The displaced connection is closed explicitly and counted, so
        "two panels are fighting" is a number rather than a mystery.
        """

        try:
            self.authorize(token)
        except GatewayError:
            with self._lock:
                self.connections_refused += 1
            raise
        conn = _Connection(
            max_frames=self._max_outbound_frames,
            max_bytes=self._max_outbound_bytes,
        )
        with self._lock:
            previous = self._conn
            self._conn = conn
            self.connections += 1
            if previous is not None and not previous.closed.is_set():
                self.connections_displaced += 1
            # A new panel inherits no playback state: the old browser's acks
            # must never anchor this one's played clock.
            self._played_started = None
            self._first_send_at = None
            self._playback_drained_ms = None
        if previous is not None:
            previous.close_reason = "displaced by a newer panel connection"
            previous.closed.set()
            previous.wake.set()
        conn.push(json.dumps(self.hello()))
        self._note("audio gateway: panel connected (microphone still closed)")
        return conn

    def detach(self, conn: _Connection, reason: str = "") -> None:
        """Release the slot if this connection still holds it. Idempotent."""

        with self._lock:
            if self._conn is conn:
                self._conn = None
                self._played_started = None
                self._first_send_at = None
                self._playback_drained_ms = None
            was_open = conn.mic_open
            conn.mic_open = False
        conn.close_reason = conn.close_reason or reason
        conn.closed.set()
        conn.wake.set()
        if was_open:
            self._end_voice_turn()
            self._report_mic(False)
        self._note(f"audio gateway: panel disconnected ({conn.close_reason or 'closed'})")

    def hello(self) -> dict[str, Any]:
        """The wire format the hosted session negotiates, stated to the client.

        The client does not get to choose. ``protocol.SessionUpdate`` pins mono
        PCM16 at :data:`PCM16_SAMPLE_RATE_HZ` for the output half and the
        provider defaults the input half to the same, so a browser capturing at
        48 kHz has to resample before it sends. Saying the number out loud is
        what lets a headless client be honest about doing it.

        CARD MARK-1 — ``capture`` IS NOT ``input``
        ------------------------------------------
        ``input`` describes the PCM the browser must SEND (mono, always). The
        new ``capture`` block describes the DEVICE it should open to get it: how
        many hardware channels to ask for, and which of them is the ear. They
        are different questions and were being answered by one number, which is
        how ``channelCount: 1`` came to mean "let the audio stack average the
        conference beam and the ASR beam together and give me that".
        """

        return {
            "type": SERVER_HELLO,
            "input": {
                "format": "pcm16",
                "rate": self._sample_rate_hz,
                "channels": 1,
                "max_frame_bytes": self._max_inbound_frame_bytes,
            },
            "capture": {"channels": self._capture_channels, "beam": self._capture_beam},
            "output": {"format": "wav", "rate": self._sample_rate_hz, "channels": 1},
            "mic_open": False,
        }

    # ------------------------------------------------------------- inbound ear
    def accept_audio(self, conn: _Connection, payload: bytes) -> bool:
        """One microphone frame from the browser. True when it went up.

        Deliberately synchronous: the lane's ``send_audio`` is called on the
        socket reader's own thread, so a lane that is busy backpressures the TCP
        window instead of filling a queue nobody bounded.
        """

        size = len(payload)
        if size > self._max_inbound_frame_bytes:
            with self._lock:
                self.frames_oversize += 1
            self._send_control(
                conn,
                {
                    "type": SERVER_REFUSED,
                    "reason": (
                        f"microphone frame of {size} bytes exceeds the "
                        f"{self._max_inbound_frame_bytes}-byte cap"
                    ),
                },
            )
            return False
        with self._lock:
            armed = conn.mic_open and self._conn is conn and self._running
        if not armed:
            with self._lock:
                self.frames_refused_unarmed += 1
                first = self.frames_refused_unarmed == 1
            if first:
                self._send_control(
                    conn,
                    {
                        "type": SERVER_REFUSED,
                        "reason": (
                            "the microphone is not armed for this connection; "
                            "send {\"type\":\"mic\",\"on\":true} after the owner's gesture"
                        ),
                    },
                )
            return False
        if not payload:
            return False
        with self._lock:
            self.frames_in += 1
            self.bytes_in += size
            capture = self._capture
            identity = self._voice_identity
        frame = bytes(payload)
        # Card R17: tee BEFORE the lane, and outside the lock. Before, because
        # ``_on_audio`` is a synchronous hop into the lane on this same socket
        # reader thread and a busy lane must not also delay the recording;
        # outside, because nothing the tee does may ever be serialized against
        # the counters the snapshot reads.
        if capture is not None:
            capture.offer_owner(frame)
        # Card F1-SI: the verify hook, POST-VAD in the only sense this side of
        # the wire has one — the browser sends frames only while the owner's
        # microphone is open, and the gate cuts turns on the same silence gap
        # the tee cuts segments on. It runs BEFORE the lane for the same reason
        # the tee does (a busy lane must not delay the verdict a transcript is
        # about to need) and it never decides whether the frame goes up: it
        # cannot, because a stranger's spoken emergency phrase has to reach the
        # transcriber for the latch to fire at all. (The phrase itself has one
        # literal in this source tree, in ``realtime/ingress.py``, and
        # ``test_the_spoken_phrase_exists_exactly_once_in_the_source_tree``
        # keeps it that way — it caught this very comment.)
        if identity is not None:
            identity.observe_frame(frame)
        self._on_audio(frame)
        return True

    def set_mic(
        self,
        conn: _Connection,
        want_open: bool,
        *,
        channels: object = None,
        beam: object = None,
    ) -> bool:
        """The owner's per-connection gesture. Returns the state that now holds.

        Opening asks the runtime first (``on_mic``): if it refuses — no session,
        no budget, no credential — the microphone stays shut and the browser is
        told why. Fail-closed, exactly like every other arming surface here.

        CARD MARK-1 — WHICH EAR DID YOU ACTUALLY OPEN?
        ----------------------------------------------
        ``channels`` and ``beam`` are what the browser says it got back from
        ``getUserMedia`` after applying the ``capture`` block in ``hello()``.
        They are always RECORDED, so a session can answer "what microphone was
        this?" afterwards. They are only ever REFUSED when a beam is pinned:
        without a pin (the shipped default) a downmixed ear is accepted and
        stated, because taking the owner's microphone away over a beam index is
        a worse failure than a slightly worse microphone, and because the fix
        for it is a hardware commissioning step (card AIR-1) and not a click.
        """

        with self._lock:
            if self._conn is not conn or conn.closed.is_set() or not self._running:
                self.mic_refusals += 1
                self._send_control(
                    conn,
                    {"type": SERVER_MIC, "on": False, "reason": "this connection is not current"},
                )
                return False
            already = conn.mic_open
        if want_open and not already:
            refusal = self._check_capture_pin(channels, beam)
            if refusal is not None:
                with self._lock:
                    self.mic_refusals += 1
                    self.capture_pin_refusals += 1
                self._send_control(conn, {"type": SERVER_MIC, "on": False, "reason": refusal})
                self._note(f"audio gateway: microphone refused — {refusal}")
                return False
            try:
                self._report_mic(True, raising=True)
            except (GatewayError, OSError, RuntimeError, TypeError, ValueError) as error:
                with self._lock:
                    self.mic_refusals += 1
                self._send_control(conn, {"type": SERVER_MIC, "on": False, "reason": str(error)})
                self._note(f"audio gateway: microphone refused — {error}")
                return False
            with self._lock:
                conn.mic_open = True
                self.mic_opens += 1
            self._send_control(conn, {"type": SERVER_MIC, "on": True, "reason": "armed"})
            self._note(f"audio gateway: microphone opened by owner gesture{self._ear_text()}")
            return True
        if not want_open and already:
            with self._lock:
                conn.mic_open = False
            self._end_voice_turn()
            self._report_mic(False)
            self._send_control(conn, {"type": SERVER_MIC, "on": False, "reason": "closed by owner"})
            self._note("audio gateway: microphone closed by owner")
            return False
        self._send_control(conn, {"type": SERVER_MIC, "on": already, "reason": "unchanged"})
        return already

    def _check_capture_pin(self, channels: object, beam: object) -> str | None:
        """Record the ear the browser opened; refuse it only against a pin.

        Returns the refusal sentence, or ``None`` to let the arming continue.
        Called without the lock (it takes it), before ``on_mic`` is consulted:
        a microphone that is going to be refused for being the wrong ear must
        not first open a paid session.
        """

        got_channels = _as_int(channels)
        got_beam = _as_int(beam)
        with self._lock:
            self.capture_channels_reported = got_channels
            self.capture_beam_reported = got_beam
            pin = self._capture_beam
            want_channels = self._capture_channels
        if pin is None:
            return None
        if got_channels is None:
            return (
                f"this gateway pins capture channel {pin} and the browser did not say which "
                "ear it opened; send {\"type\":\"mic\",\"on\":true,\"channels\":N,\"beam\":I}"
            )
        if got_channels < pin + 1:
            return (
                f"this gateway pins capture channel {pin} (of {want_channels}) and the browser "
                f"opened {got_channels} channel(s): the beams were downmixed into one ear, "
                "which is a different microphone from the one that was asked for"
            )
        if got_beam != pin:
            return (
                f"this gateway pins capture channel {pin} and the browser is sending "
                f"channel {got_beam}"
            )
        return None

    def _ear_text(self) -> str:
        """How the last-armed ear reads in a note. Card MARK-1."""

        with self._lock:
            channels = self.capture_channels_reported
            beam = self.capture_beam_reported
            pin = self._capture_beam
        if channels is None:
            return ""
        if channels <= 1:
            return f" (ear: {channels} channel, downmixed{'' if pin is None else ' — PINNED'})"
        return f" (ear: channel {beam} of {channels})"

    def close_mic(self, reason: str) -> bool:
        """Shut the ear because the RUNTIME says so. Card R16, work item 3.

        The one thing an idle hang-up needs from this module and the only thing
        it is allowed to want. The gateway itself keeps running, keeps its token
        bound and keeps accepting connections — "armed but idle", the state
        ``start()`` announces — but the browser is told the microphone is off, so
        its button goes back to "Enable microphone" and ONE click re-arms it,
        which is the gesture that re-opens the session. Without this the page
        would sit there saying "Listening" while streaming PCM into a session
        that no longer exists.

        Deliberately does NOT fire ``on_mic``: the runtime is the caller, it
        already knows, and reporting a mic close back to it would run the "the
        session stays open" path for a session that has just been closed.

        Returns whether a microphone was actually open to close. Idempotent.
        """

        with self._lock:
            conn = self._conn
            if conn is None or conn.closed.is_set() or not conn.mic_open:
                return False
            conn.mic_open = False
            self.mic_closes_by_runtime += 1
        self._end_voice_turn()
        self._send_control(conn, {"type": SERVER_MIC, "on": False, "reason": str(reason)})
        self._note(
            f"audio gateway: microphone closed by the runtime ({reason}); the gateway "
            "stays armed and the owner's next click re-opens the session"
        )
        return True

    def handle_control(self, conn: _Connection, raw: str) -> None:
        """One JSON control frame from the browser. Anything unknown is counted."""

        try:
            body = json.loads(raw)
        except (TypeError, ValueError):
            with self._lock:
                self.control_errors += 1
            return
        if not isinstance(body, dict):
            with self._lock:
                self.control_errors += 1
            return
        kind = str(body.get("type", "")).strip()
        if kind == CLIENT_MIC:
            # Card MARK-1: ``channels``/``beam`` are optional and absent from
            # every pre-MARK-1 client, which is exactly what an unpinned gateway
            # accepts. A pinned one refuses the silence — see ``_check_capture_pin``.
            self.set_mic(
                conn,
                bool(body.get("on", False)),
                channels=body.get("channels"),
                beam=body.get("beam"),
            )
            return
        if kind == CLIENT_PLAYED:
            self.ack_played(body.get("utterance"), body.get("ms"), body.get("drained", False))
            return
        if kind == CLIENT_PONG:
            return
        with self._lock:
            self.control_errors += 1

    # ------------------------------------------------------- outbound mouth
    def begin_utterance(self) -> None:
        """A new hosted reply starts. Playback anchor and byte count reset."""

        with self._lock:
            self._utterance_seq += 1
            self.utterances += 1
            self._sent_bytes_this_utterance = 0
            self._first_send_at = None
            self._played_started = None
            # Card MARK-1: the monotonic floor is per UTTERANCE. Carrying it
            # across would make the second reply's first honest ack look like a
            # regression and silently pin the mark at the first reply's length.
            self._played_ack_ms = 0.0
            self._playback_drained_ms = None
            # Card DUPLEX-1: the panel puts its gain back to unity on this
            # frame, so the gateway's idea of the level has to reset with it or
            # the snapshot describes a duck nobody is applying.
            self.last_duck_gain = None
            conn = self._live_connection()
            seq = self._utterance_seq
            capture = self._capture
        if capture is not None:
            capture.begin_utterance(seq)
        if conn is not None:
            self._send_control(conn, {"type": SERVER_UTTERANCE, "utterance": seq})

    def send_audio(self, chunk: bytes) -> None:
        """One WAV-wrapped playback chunk down to the browser.

        Never raises. This runs inside ``lane.pump()``: an exception here would
        surface as ``pump failed`` and take the whole conversation down because
        a browser tab was closed. A hosted reply with nobody listening is a
        counted drop, and the counter is in the snapshot.
        """

        payload = bytes(chunk)
        if not payload:
            return
        with self._lock:
            capture = self._capture
        # Card R17: the tee records what the ROBOT SAID, which is why it runs
        # before the no-client check. A reply that reached nobody because the
        # tab was closed is precisely the sort of thing an investigation of a
        # session later wants to listen to.
        if capture is not None:
            capture.offer_robot(payload)
        with self._lock:
            conn = self._live_connection()
            if conn is None:
                self.frames_dropped_no_client += 1
                return
            dropped = conn.push(payload)
            self.frames_dropped_backpressure += dropped
            self.frames_out += 1
            self.bytes_out += len(payload)
            self._sent_bytes_this_utterance += len(payload)
            if self._first_send_at is None:
                self._first_send_at = self._clock()
            overflowed = dropped > 0
        if overflowed:
            self._note(
                f"audio gateway: browser is not draining playback; dropped {dropped} "
                f"frame(s) (bound {self._max_outbound_frames} frames / "
                f"{self._max_outbound_bytes} bytes)"
            )

    # ---- CARD DUPLEX-1 (task_26) — the sink may now turn the voice DOWN ----
    #: Advertised to :class:`~parcel_robot.realtime.browser_sink.BrowserSink` so
    #: it can pass the onset without probing a signature.
    accepts_interrupt_onset = True

    def duck(self, gain: float) -> None:
        """Attenuate the reply in the browser. Nothing is dropped or cancelled.

        The whole point of a provisional barge-in is that it costs nothing when
        it turns out to be a "mm-hmm": the schedule keeps running, the played
        clock keeps advancing, the provider is told nothing, and MARK-1's ack
        arithmetic is untouched — the owner heard the ducked audio, quietly, and
        the truncate mark still has to say so. So this method deliberately does
        NOT touch ``_played_started``, ``_sent_bytes_this_utterance`` or the
        outbox: it sends one control frame and counts it.

        Never raises. It is called from the pump thread on the barge-in path.
        """

        low, high = DUCK_GAIN_RANGE
        try:
            level = max(low, min(high, float(gain)))
        except (TypeError, ValueError):
            with self._lock:
                self.duck_refusals += 1
            return
        with self._lock:
            conn = self._live_connection()
            seq = self._utterance_seq
            if conn is None or seq <= 0:
                # No reply is playing (or nobody is listening): a duck frame now
                # would attenuate whatever comes next. Counted, not sent.
                self.duck_refusals += 1
                return
            self.ducks += 1
            self.last_duck_gain = level
            if level >= high:
                self.duck_resumes += 1
        self._send_control(conn, {"type": SERVER_DUCK, "utterance": seq, "gain": level})

    # ---- END CARD DUPLEX-1 ----

    def interrupt(self, *, onset_ago_s: float | None = None) -> None:
        """Barge-in. Drop what is queued and tell the browser to stop playing.

        The lane already cancels the response and truncates the provider's
        transcript; without this frame the browser would keep playing the audio
        already in its own buffer and the owner would be talked over by a reply
        the model has been told it never finished.

        Card DUPLEX-1: ``onset_ago_s`` is how long before this call the owner
        started speaking — a duration, not a stamp, so the lane's monotonic
        clock never has to be reconciled with the tee's wall clock. It reaches
        the capture index as ``interrupted_onset_at`` (MARK-1's handoff H-7).
        """

        with self._lock:
            self.interrupts += 1
            conn = self._live_connection()
            seq = self._utterance_seq
            self._played_started = None
            self._first_send_at = None
            self._played_ack_ms = 0.0
            self._playback_drained_ms = None
            # Card MARK-1: this utterance is now allowed exactly one FINAL ack —
            # the browser's last word on what came out of the speaker before it
            # stopped. Recorded, never anchoring: see ``_record_final_ack``.
            self._interrupted_seq = seq
            self._interrupted_sent_ms = self._sent_bytes_this_utterance / self._bytes_per_ms
            self._final_ack_seen = False
            self.final_acks = 0
            self.last_final_played_ms = None
            discarded = 0 if conn is None else conn.discard()
            self.frames_discarded_interrupt += discarded
            capture = self._capture
        if capture is not None:
            capture.note_interrupt(seq, onset_ago_s=onset_ago_s)
        if conn is not None:
            self._send_control(conn, {"type": SERVER_STOP, "utterance": seq})

    @property
    def played_started_monotonic(self) -> float | None:
        """When the BROWSER said this utterance started playing. Clamped here.

        Card MARK-1, correction pass, defect 3. While playback is DRAINED the
        anchor is recomputed against the current clock so that the elapsed time
        the lane derives from it stays pinned at the position the browser last
        reported. The lane's arithmetic is untouched — it still reads one
        number and subtracts — but that number no longer pretends a silent
        speaker is still playing. Before this, the only thing bounding a
        truncate across a stall was ``enqueued_ms``, which saves you exactly
        while the socket is not running ahead of the tab.
        """

        with self._lock:
            drained = self._playback_drained_ms
            if drained is None:
                return self._played_started
            anchor = self._clock() - (drained / 1000.0)
            if self._first_send_at is not None:
                anchor = max(self._first_send_at, anchor)
            return anchor

    def ack_played(self, utterance: object, ms: object, drained: object = False) -> bool:
        """Fold one browser playback ack into the played clock, clamped.

        Four independent clamps, because this is the number the lane hands the
        provider as "what the owner actually heard":

        * an ack for anything but the CURRENT utterance is dropped (a stale ack
          from the reply before a barge-in would otherwise anchor this one) —
          with one exception, the single FINAL ack a client is invited to send
          after an interrupt, which is recorded and never anchors anything;
        * the reported position is clamped to the audio actually handed to the
          socket, so the browser cannot claim to have played more than was sent;
        * the derived anchor is never earlier than the moment the first byte of
          this utterance left, so it cannot claim playback began before there
          was anything to play;
        * **card MARK-1: within one utterance the position may only GO UP.**
          Heard audio does not un-hear itself. The client that shipped in
          ``index.html`` re-stamped its playback origin every time its schedule
          ran dry and then reported a position measured from the re-stamp — so
          in the middle of a reply the owner was still listening to, it reported
          ~0 and dragged the truncate point back with it (measured: 1 441 ms of
          error on the stall fixtures, ``tests/test_mark1_barge_in_mark.py``).
          A regressive ack is dropped and counted here rather than trusted,
          which makes the mark honest even for a browser that is not.
        """

        try:
            seq = int(utterance)  # type: ignore[arg-type]
            position_ms = float(ms)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            with self._lock:
                self.control_errors += 1
            return False
        if not math.isfinite(position_ms):
            with self._lock:
                self.control_errors += 1
            return False
        with self._lock:
            if seq != self._utterance_seq or self._first_send_at is None:
                return self._record_final_ack(seq, position_ms)
            sent_ms = self._sent_bytes_this_utterance / self._bytes_per_ms
            clamped = min(max(0.0, position_ms), sent_ms)
            if clamped < self._played_ack_ms:
                self.regressive_acks += 1
                if not bool(drained) and self._playback_drained_ms is not None:
                    # Correction pass. The position walked backwards, so it is
                    # refused — but a NON-drained ack is still positive evidence
                    # that audio is coming out again, and leaving the freeze on
                    # would keep reporting the stall for another timer period.
                    # Unfreeze AT the monotonic floor: playback is live, and the
                    # owner has heard exactly what was last accepted. (This is
                    # the common shape right after an underrun resumes: the
                    # scheduling lead-in is not audio anyone has heard yet, so
                    # the client's position dips by ~20 ms.)
                    self._playback_drained_ms = None
                    self._played_started = max(
                        self._first_send_at, self._clock() - (self._played_ack_ms / 1000.0)
                    )
                return False
            self._played_ack_ms = clamped
            now = self._clock()
            self._played_started = max(self._first_send_at, now - (clamped / 1000.0))
            self.played_acks += 1
            # Card MARK-1, correction pass, defect 3. A DRAINED ack says the
            # schedule has run dry: the position has stopped moving even though
            # the wall clock has not. Freeze it. Any later ordinary ack means
            # audio is coming out again, so the freeze is lifted by the same
            # frame that proves it should be.
            if bool(drained):
                self._playback_drained_ms = clamped
                self.drained_acks += 1
            else:
                self._playback_drained_ms = None
            return True

    def _record_final_ack(self, seq: int, position_ms: float) -> bool:
        """Acks that arrive AFTER an interrupt. Card MARK-1.

        Called with the lock held. The lane truncated the provider's belief the
        moment VAD fired — before any of these could possibly arrive — so none
        of them can move the mark and none of them tries to. What they are for
        is the record: the browser's own last word on how much of the reply came
        out of the speaker, which is what an audit compares against the
        ``audio_end_ms`` the provider was told.

        CORRECTION PASS, defect 6. This used to keep exactly ONE slot, and on a
        real socket the wrong ack won it. ``interrupt()`` clears
        ``_first_send_at`` immediately, but the browser's ~100 ms timer may
        already have a ``played`` frame in flight; that frame lands here first,
        takes the slot, and the browser's true final position — sent when it
        actually received ``stop`` — is then discarded as stale. The recorded
        number was silently up to one timer period early.

        So: fold, do not latch. Heard audio only grows, so the LARGEST
        post-interrupt position is the right one whatever order the frames
        arrive in, and the count is bounded so a chatty client cannot spin it.
        """

        if seq != self._interrupted_seq or self.final_acks >= MAX_FINAL_ACKS_PER_UTTERANCE:
            self.stale_acks += 1
            return False
        self._final_ack_seen = True
        self.final_acks += 1
        clamped = min(max(0.0, position_ms), self._interrupted_sent_ms)
        previous = self.last_final_played_ms
        self.last_final_played_ms = clamped if previous is None else max(previous, clamped)
        return False

    # ---------------------------------------------------------------- plumbing
    def _live_connection(self) -> _Connection | None:
        conn = self._conn
        if conn is None or conn.closed.is_set():
            return None
        return conn

    def _send_control(self, conn: _Connection, body: dict[str, Any]) -> None:
        with self._lock:
            dropped = conn.push(json.dumps(body, separators=(",", ":")))
            self.frames_dropped_backpressure += dropped

    def _report_mic(self, open_: bool, *, raising: bool = False) -> None:
        hook = self._on_mic
        if hook is None:
            return
        try:
            hook(open_)
        except (OSError, RuntimeError, TypeError, ValueError):
            if raising:
                raise
            LOGGER.debug("audio gateway mic hook raised on close", exc_info=True)

    def _note(self, message: str) -> None:
        hook = self._on_event
        if hook is None:
            return
        try:
            hook(message)
        except (RuntimeError, TypeError, ValueError):  # pragma: no cover - defensive
            pass

    @property
    def voice_identity(self) -> Any | None:
        """The speaker-identity gate this gateway feeds, if any.

        Read by ``runtime.submit_realtime_transcript`` at the moment a hosted
        transcript needs to know whose turn it belonged to. Exposed as a
        property rather than passed around so there is exactly one gate per
        gateway and no second one can be constructed by accident — two gates
        would mean two turn segmentations and a verdict about the wrong audio.
        """

        with self._lock:
            return self._voice_identity

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            conn = self._conn
            capture = self._capture
            identity = self._voice_identity
            return {
                "kind": "browser_audio",
                # Card R17. ``{"enabled": false}`` when the owner has not opted
                # in, so "capture is off" is a stated fact in /api/state rather
                # than an absent key a reader has to interpret.
                "capture": (
                    {"enabled": False} if capture is None else capture.snapshot()
                ),
                # Card F1-SI. Same rule, and it matters more here: "no gate" and
                # "a gate with nobody enrolled" both mean any voice can command
                # the robot, and a reader must be able to see that rather than
                # infer it from an absent key.
                "voice_identity": (
                    {
                        "enabled": False,
                        "reason": (
                            "no speaker-identity gate is wired to this gateway: any "
                            "voice in the room can arm a command"
                        ),
                    }
                    if identity is None
                    else identity.snapshot()
                ),
                "running": self._running,
                "token_bound": self._token is not None,
                "connected": conn is not None and not conn.closed.is_set(),
                "mic_open": bool(conn is not None and not conn.closed.is_set() and conn.mic_open),
                "sample_rate_hz": self._sample_rate_hz,
                "connections": self.connections,
                "connections_refused": self.connections_refused,
                "connections_displaced": self.connections_displaced,
                "mic_opens": self.mic_opens,
                "mic_refusals": self.mic_refusals,
                "mic_closes_by_runtime": self.mic_closes_by_runtime,
                "frames_in": self.frames_in,
                "bytes_in": self.bytes_in,
                "frames_refused_unarmed": self.frames_refused_unarmed,
                "frames_oversize": self.frames_oversize,
                "frames_out": self.frames_out,
                "bytes_out": self.bytes_out,
                "queued_frames": 0 if conn is None else len(conn.outbox),
                "max_outbound_frames": self._max_outbound_frames,
                "max_inbound_frame_bytes": self._max_inbound_frame_bytes,
                "frames_dropped_backpressure": self.frames_dropped_backpressure,
                "frames_dropped_no_client": self.frames_dropped_no_client,
                "frames_discarded_interrupt": self.frames_discarded_interrupt,
                "utterances": self.utterances,
                "interrupts": self.interrupts,
                "played_acks": self.played_acks,
                "stale_acks": self.stale_acks,
                # Card MARK-1. Barge-in mark integrity, from outside: acks that
                # tried to walk the played clock backwards, the browser's last
                # word after an interrupt, and which ear it actually opened.
                "regressive_acks": self.regressive_acks,
                "drained_acks": self.drained_acks,
                "playback_drained_ms": self._playback_drained_ms,
                "final_acks": self.final_acks,
                "last_final_played_ms": self.last_final_played_ms,
                "capture_channels_pinned": self._capture_channels,
                "capture_beam_pinned": self._capture_beam,
                "capture_channels_reported": self.capture_channels_reported,
                "capture_beam_reported": self.capture_beam_reported,
                "capture_pin_refusals": self.capture_pin_refusals,
                # ---- CARD DUPLEX-1 (task_26). The provisional barge-in, from
                # outside: how often the reply was turned down instead of cut
                # off, how often it came back up, and the level right now.
                "ducks": self.ducks,
                "duck_resumes": self.duck_resumes,
                "duck_refusals": self.duck_refusals,
                "last_duck_gain": self.last_duck_gain,
                # ---- END CARD DUPLEX-1 ----
                "control_errors": self.control_errors,
            }


# --------------------------------------------------------------- the transport
def select_csrf_subprotocol(offered: object) -> tuple[str | None, str | None]:
    """Split a client's subprotocol list into (chosen protocol, token).

    A browser cannot put a header on a WebSocket handshake, so the panel token
    rides as a second offered subprotocol. It is deliberately NOT a query
    parameter: ``BaseHTTPRequestHandler.log_message`` prints the request line,
    and a token in the URL is a token in the terminal scrollback.
    """

    chosen: str | None = None
    token: str | None = None
    for item in offered or ():
        name = str(item).strip()
        if name == SUBPROTOCOL_AUDIO:
            chosen = name
        elif name.startswith(CSRF_SUBPROTOCOL_PREFIX):
            token = name[len(CSRF_SUBPROTOCOL_PREFIX) :]
    return chosen, token


def serve_websocket(
    gateway: BrowserAudioGateway,
    sock: _socket.socket,
    request: Request,
    *,
    poll_s: float = DEFAULT_POLL_S,
) -> None:
    """Run one browser audio socket to completion on the calling thread.

    Sans-I/O framing from ``websockets`` (RFC 6455 masking, fragmentation,
    control frames and the close handshake are its problem, not ours) with the
    two halves split across two threads: the caller reads, a writer thread
    drains the gateway's outbound queue. Both mutate the protocol object, so a
    single lock covers "advance the protocol and put its bytes on the wire".

    Returns when either end hangs up. The caller (``web_panel``) owns the
    socket and closes it.
    """

    offered = request.headers.get_all("Sec-WebSocket-Protocol")
    names: list[str] = []
    for value in offered:
        names.extend(part.strip() for part in str(value).split(",") if part.strip())
    chosen, token = select_csrf_subprotocol(names)

    protocol = ServerProtocol(
        subprotocols=[Subprotocol(SUBPROTOCOL_AUDIO)] if chosen else None,
        select_subprotocol=lambda _proto, _offered: (
            Subprotocol(SUBPROTOCOL_AUDIO) if chosen else None
        ),
        max_size=DEFAULT_MAX_SOCKET_FRAME_BYTES,
    )
    assembler = _Reassembler(max_bytes=DEFAULT_MAX_SOCKET_FRAME_BYTES)
    io_lock = threading.Lock()

    def flush() -> None:
        for data in protocol.data_to_send():
            if data == b"":
                try:
                    sock.shutdown(_socket.SHUT_WR)
                except OSError:  # pragma: no cover - peer already gone
                    pass
                continue
            sock.sendall(data)

    # ------------------------------------------------------------- handshake
    #
    # The request arrives ALREADY PARSED (``BaseHTTPRequestHandler`` read it),
    # but the Sans-I/O parser is a generator that starts life suspended inside
    # ``Request.parse`` waiting for a request line of its own. Calling
    # ``accept()`` without satisfying it leaves it parked there, and the first
    # websocket frame the browser sends is then swallowed by an HTTP parser
    # that will never finish — a socket that handshakes perfectly, plays audio
    # perfectly, and is stone deaf. Re-serializing the request and feeding it in
    # is what walks the parser from CONNECTING into the frame loop.
    try:
        protocol.receive_data(request.serialize())
        parsed = [event for event in protocol.events_received() if isinstance(event, Request)]
        response = protocol.accept(parsed[0] if parsed else request)
        protocol.send_response(response)
        with io_lock:
            flush()
    except (OSError, WebSocketException):
        return
    if protocol.state is not OPEN:
        return

    # The upgrade is complete; only NOW is the token checked, so a refusal is a
    # websocket close with a stated reason rather than a bare TCP reset.
    try:
        conn = gateway.attach(token)
    except GatewayError as error:
        try:
            with io_lock:
                protocol.send_close(CloseCode.POLICY_VIOLATION, str(error)[:120])
                flush()
        except (OSError, WebSocketException):  # pragma: no cover - defensive
            pass
        return

    def writer() -> None:
        while not conn.closed.is_set():
            if not conn.wake.wait(poll_s):
                continue
            for frame in conn.drain():
                try:
                    with io_lock:
                        if isinstance(frame, str):
                            protocol.send_text(frame.encode())
                        else:
                            protocol.send_binary(frame)
                        flush()
                except (OSError, WebSocketException, ConnectionClosed):
                    conn.close_reason = conn.close_reason or "playback write failed"
                    conn.closed.set()
                    return
        # Best-effort goodbye. A browser that already left will not see it.
        try:
            with io_lock:
                protocol.send_close(CloseCode.GOING_AWAY, conn.close_reason[:120] or "closing")
                flush()
        except (OSError, WebSocketException, ConnectionClosed):  # pragma: no cover
            pass

    pump = threading.Thread(target=writer, name="parcel-audio-gateway-out", daemon=True)
    pump.start()
    sock.settimeout(poll_s)
    try:
        while not conn.closed.is_set():
            try:
                data = sock.recv(65536)
            except TimeoutError:
                continue
            except OSError:
                conn.close_reason = conn.close_reason or "socket read failed"
                break
            with io_lock:
                if data:
                    protocol.receive_data(data)
                else:
                    protocol.receive_eof()
                events = protocol.events_received()
                flush()
            try:
                for event in events:
                    if isinstance(event, Frame):
                        _dispatch(gateway, conn, event, assembler)
            except WebSocketException as error:
                conn.close_reason = f"protocol violation: {error}"
                with io_lock:
                    protocol.send_close(CloseCode.PROTOCOL_ERROR, str(error)[:120])
                    flush()
                break
            if not data:
                conn.close_reason = conn.close_reason or "browser hung up"
                break
            if protocol.state is not OPEN:
                conn.close_reason = conn.close_reason or "close handshake complete"
                break
    finally:
        gateway.detach(conn, "socket closed")
        pump.join(timeout=1.0)


class _Reassembler:
    """Frames in, whole messages out. Bounded, because fragments are attacker-shaped.

    Sans-I/O ``websockets`` hands out FRAMES, not messages: its ``max_size``
    bounds one frame, and a client that sends ten thousand one-byte
    continuations of the same message would otherwise grow this buffer without
    limit. The running total is bounded by the same socket-frame cap, and
    breaching it is a protocol failure rather than a policy refusal — nothing
    legitimate fragments a 20 ms capture buffer.
    """

    def __init__(self, *, max_bytes: int) -> None:
        self._max_bytes = int(max_bytes)
        self._opcode: Opcode | None = None
        self._parts = bytearray()

    def feed(self, frame: Frame) -> tuple[Opcode, bytes] | None:
        opcode = frame.opcode
        if opcode in (Opcode.CLOSE, Opcode.PING, Opcode.PONG):
            return None  # control frames are the protocol object's business
        if opcode is Opcode.CONT:
            if self._opcode is None:
                raise WebSocketException("continuation frame with nothing to continue")
        else:
            if self._opcode is not None:
                raise WebSocketException("new data frame while a message was unfinished")
            self._opcode = opcode
            self._parts.clear()
        self._parts.extend(frame.data)
        if len(self._parts) > self._max_bytes:
            raise WebSocketException(
                f"fragmented message exceeded {self._max_bytes} bytes"
            )
        if not frame.fin:
            return None
        opcode_out = self._opcode
        payload = bytes(self._parts)
        self._opcode = None
        self._parts.clear()
        assert opcode_out is not None
        return opcode_out, payload


def _dispatch(
    gateway: BrowserAudioGateway,
    conn: _Connection,
    frame: Frame,
    assembler: _Reassembler,
) -> None:
    """One decoded websocket frame → the gateway's inbound half.

    BINARY is microphone PCM, TEXT is a JSON control frame. The distinction is
    the OPCODE and never the payload's shape: ``Frame.data`` is bytes for both,
    and a first cut of this function keyed off ``isinstance(data, str)`` and
    silently fed every control frame to the microphone.
    """

    assembled = assembler.feed(frame)
    if assembled is None:
        return
    opcode, payload = assembled
    if opcode is Opcode.BINARY:
        gateway.accept_audio(conn, payload)
        return
    if opcode is Opcode.TEXT:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WebSocketException("text frame is not valid UTF-8") from error
        gateway.handle_control(conn, text)


__all__ = [
    "CAPTURE_INDEX_NAME",
    "CAPTURE_INDEX_SCHEMA",
    "CAPTURE_OWNER_NAME",
    "CAPTURE_ROBOT_NAME",
    "CSRF_SUBPROTOCOL_PREFIX",
    "DEFAULT_MAX_CAPTURE_QUEUE_FRAMES",
    "DEFAULT_MAX_INBOUND_FRAME_BYTES",
    "DEFAULT_MAX_OUTBOUND_BYTES",
    "DEFAULT_MAX_OUTBOUND_FRAMES",
    "GATEWAY_PATH",
    "SUBPROTOCOL_AUDIO",
    "BrowserAudioGateway",
    "GatewayAuthError",
    "GatewayError",
    "GatewayNotRunningError",
    "SessionAudioCapture",
    "new_capture_session_id",
    "pcm_from_playback_chunk",
    "select_csrf_subprotocol",
    "serve_websocket",
    "verify_capture_index",
]
