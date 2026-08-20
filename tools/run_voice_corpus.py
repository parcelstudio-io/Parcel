#!/usr/bin/env python3
"""Replay a spoken query corpus through a LIVE stack, UI-mounted (card R17, §2/§3).

WHAT THIS IS FOR
----------------
On 2026-08-20 the owner spoke the 52-query voice corpus to the live robot for
the first time. It cost real money, it produced the most informative eval of
the project so far — and **it can never be run again**, because the gateway did
not persist the audio. The transcripts survived; the sound did not.

This runner is the other half of the answer (the tee in
``realtime/audio_gateway.py`` is the first half): given a folder of WAVs and
the corpus TSV, it speaks them to a live stack **through the real browser audio
gateway** — the same websocket, the same handshake, the same
mic-gesture-before-audio ordering an actual browser uses — one query at a time,
waiting for each turn to genuinely settle before the next, with a deliberate
pause so a human can watch.

THE UI IS THE DELIVERABLE, NOT A SIDE EFFECT
--------------------------------------------
Nothing here is headless-by-design. The panel and the MuJoCo window stay live
for the whole run: the owner watches the dog take each spoken instruction and
execute it, in order, at a pace a person can follow, while this process prints
what it heard, what the robot said, which tools fired and how it scored. That
is what "show me the UI of the robot when you run this eval" means. A run whose
only artifact is a JSON file has not done the job.

THE THREE THINGS IT REFUSES TO DO
---------------------------------
1. **It will not drive the owner's stack by accident.** Port 8765 is theirs.
   Targeting it requires ``--stack owner --i-am-the-owner`` typed out in full;
   anything less is a refusal before a single socket is opened.
2. **It will not step over a latched emergency stop.** live_run_1's defining
   failure was 84 seconds and 18 owner turns spoken into a robot that could not
   move and never said so. Here, an ``estop-pos`` query must latch (that is the
   assertion) and the latch is then RELEASED before the next query — and if it
   will not release, the run ABORTS. A harness that scores 20 queries against a
   frozen robot is worse than no harness, because it produces confident numbers
   about nothing.
3. **It will not resolve its own output path against the cwd.** The scoring run
   of 2026-08-20 deposited its artifacts under a doubled repo-relative prefix
   for exactly that reason. ``--out`` is resolved once, printed, and refused if
   it contains a repeated path segment run.

SCORING
-------
Verdicts are MECHANICAL. Where the gold column names something checkable — a
tool, a goal, a latch, "no mission" — the runner decides. Where the gold column
asks for a judgement a program cannot make ("warm in-character reply"), it
records everything and returns ``NEEDS_REVIEW`` rather than inventing a
verdict. Silence is the one prose case it will fail on its own authority: a
query that produced no reply, no tool and no event did not "partially" work.

USAGE
-----
    .parcel/bin/python tools/run_voice_corpus.py \
        --corpus evals/20260820/voice_corpus_v1 \
        --out    evals/20260820/voice_corpus_v1/replay_run_1 \
        --port   8823 --pace 2.5
"""

from __future__ import annotations

import argparse
import array
import contextlib
import json
import os
import re
import sys
import time
import wave
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib import error as urlerror
from urllib import request as urlrequest

if TYPE_CHECKING:
    from typing_extensions import Self

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:  # running from a checkout, not a wheel
    sys.path.insert(0, str(REPO_ROOT / "src"))

from parcel_robot.realtime.audio_gateway import (
    CSRF_SUBPROTOCOL_PREFIX,
    GATEWAY_PATH,
    SUBPROTOCOL_AUDIO,
)

#: The owner's panel. Not a default, not a fallback — a tripwire.
OWNER_PANEL_PORT = 8765

#: Where an executor's own stack lives by default. Deliberately not adjacent to
#: 8765, so a typo'd digit cannot land on the owner.
DEFAULT_PORT = 8823

#: The wire format the gateway negotiates in ``hello``. Read back from the
#: server anyway — this is only the fallback for a stack that says nothing.
DEFAULT_SAMPLE_RATE_HZ = 24000

#: One injected microphone frame. 20 ms of 24 kHz mono PCM16 = 960 bytes, which
#: is what ``index.html``'s ScriptProcessor produces.
FRAME_MS = 20

#: The seven tools the realtime broker exposes (state.realtime.broker.tools).
KNOWN_TOOLS = (
    "get_status",
    "recall_memory",
    "play_gesture",
    "set_pose",
    "navigate_to",
    "circle_owner",
    "follow_owner",
)

#: Tools that move the robot. Used for "no motion" gold cells and for reading a
#: latched rejection.
MOTION_TOOLS = ("play_gesture", "set_pose", "navigate_to", "circle_owner", "follow_owner")

VERDICT_PASS = "PASS"
VERDICT_PARTIAL = "PARTIAL"
VERDICT_FAIL = "FAIL"
VERDICT_BLOCKED = "BLOCKED_BY_LATCH"
VERDICT_NOT_ATTEMPTED = "NOT_ATTEMPTED"
#: The one extension to the live_run_1 verdict set, and it is an honesty
#: mechanism: a program cannot grade "warm in-character reply", and a program
#: that pretends it can produces a scoreboard nobody should trust.
VERDICT_NEEDS_REVIEW = "NEEDS_REVIEW"

VERDICT_ORDER = (
    VERDICT_PASS,
    VERDICT_PARTIAL,
    VERDICT_FAIL,
    VERDICT_BLOCKED,
    VERDICT_NEEDS_REVIEW,
    VERDICT_NOT_ATTEMPTED,
)

#: Phrases that make a reply readable as an ask or a refusal. Deliberately
#: short and deliberately visible: a long fuzzy lexicon would quietly turn
#: NEEDS_REVIEW rows into PASS rows, which is the failure mode this whole file
#: is built to avoid.
ASK_MARKERS = (
    "which ",
    "where is",
    "what would you like",
    "tell me",
    "just say",
    "let me know",
    "do you mean",
    "i don't know where",
    "i dont know where",
    "?",
)
REFUSAL_MARKERS = (
    "i can't",
    "i cant",
    "i cannot",
    "can not",
    "i'm not able",
    "im not able",
    "not able to",
    "i don't have",
    "i dont have",
    "no ability",
    "not something i can",
    "that's not safe",
    "thats not safe",
    "not safe",
    "i won't",
    "i wont",
    "sorry",
)

#: What the gateway says when the latch has eaten a motion call.
LATCH_REJECTION_MARKER = "emergency stop"


class RunnerRefusal(RuntimeError):
    """The runner refused to start. Always before anything is touched."""


class RunnerAbort(RuntimeError):
    """The run stopped mid-corpus. The partial run folder is still written."""


# --------------------------------------------------------------------- corpus
@dataclass(frozen=True)
class Query:
    id: str
    category: str
    query: str
    expected: str
    wav: Path | None = None

    @property
    def attempted(self) -> bool:
        return self.wav is not None


def load_corpus(tsv: Path) -> list[Query]:
    """Read ``queries.tsv``. Header is required; the gold column is column 4."""

    rows: list[Query] = []
    with tsv.open(encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        required = ["id", "category", "query", "expected"]
        if header[:4] != required:
            raise RunnerRefusal(
                f"{tsv} header is {header!r}; expected {required!r} as the first four columns"
            )
        for line in handle:
            if not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                raise RunnerRefusal(f"{tsv}: short row {parts!r}")
            rows.append(
                Query(
                    id=parts[0].strip(),
                    category=parts[1].strip(),
                    query=parts[2].strip(),
                    expected=parts[3].strip(),
                )
            )
    if not rows:
        raise RunnerRefusal(f"{tsv} has a header and no queries")
    return rows


def attach_audio(queries: Sequence[Query], corpus_dir: Path) -> list[Query]:
    """Pair each query with its WAV. ``record.sh`` writes ``NN_category.wav``."""

    paired: list[Query] = []
    for query in queries:
        candidates = [
            corpus_dir / f"{query.id}_{query.category}.wav",
            corpus_dir / f"{query.id}.wav",
        ]
        found = next((path for path in candidates if path.is_file()), None)
        paired.append(
            Query(
                id=query.id,
                category=query.category,
                query=query.query,
                expected=query.expected,
                wav=found,
            )
        )
    return paired


def _to_mono_int16(frames: bytes, *, channels: int, width: int) -> array.array:
    """Any WAV sample format ``wave`` will hand us → one mono int16 array.

    Written out rather than delegated because ``audioop`` — which every previous
    audio path in this repo used — was REMOVED from the standard library in
    Python 3.13, and this venv is 3.14. A replay harness that only runs on an
    interpreter the project no longer uses is not a harness.
    """

    if width == 2:
        samples = array.array("h")
        samples.frombytes(frames)
        if sys.byteorder == "big":
            samples.byteswap()
    elif width == 1:  # WAV 8-bit is UNSIGNED
        samples = array.array("h", ((value - 128) << 8 for value in frames))
    elif width == 4:
        wide = array.array("i")
        wide.frombytes(frames)
        if sys.byteorder == "big":
            wide.byteswap()
        samples = array.array("h", (value >> 16 for value in wide))
    else:
        raise RunnerRefusal(f"unsupported WAV sample width: {width} bytes")
    if channels <= 1:
        return samples
    mixed = array.array("h", bytes(2 * (len(samples) // channels)))
    for index in range(len(mixed)):
        base = index * channels
        mixed[index] = sum(samples[base : base + channels]) // channels
    return mixed


def _resample_int16(samples: array.array, *, source_hz: int, target_hz: int) -> array.array:
    """Linear resample. The same arithmetic R7's live proof used, kept explicit."""

    if source_hz == target_hz or not samples:
        return samples
    ratio = float(source_hz) / float(target_hz)
    count = max(1, int(len(samples) / ratio))
    out = array.array("h", bytes(2 * count))
    last = len(samples) - 1
    for index in range(count):
        position = index * ratio
        left = int(position)
        if left >= last:
            out[index] = samples[last]
            continue
        weight = position - left
        out[index] = int(samples[left] * (1.0 - weight) + samples[left + 1] * weight)
    return out


def read_wav_as_pcm(path: Path, target_hz: int) -> tuple[bytes, float, int]:
    """One WAV → mono PCM16 at ``target_hz``. Returns (pcm, seconds, source_hz)."""

    with contextlib.closing(wave.open(str(path), "rb")) as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        source_hz = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    samples = _to_mono_int16(frames, channels=channels, width=width)
    samples = _resample_int16(samples, source_hz=source_hz, target_hz=target_hz)
    if sys.byteorder == "big":
        samples = array.array("h", samples)
        samples.byteswap()
    pcm = samples.tobytes()
    return pcm, len(pcm) / float(target_hz * 2), source_hz


# ------------------------------------------------------------------- targeting
@dataclass(frozen=True)
class Target:
    host: str
    port: int

    @property
    def origin(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def is_owner_stack(self) -> bool:
        return self.port == OWNER_PANEL_PORT


def resolve_target(
    *, stack: str, host: str, port: int | None, i_am_the_owner: bool
) -> Target:
    """Decide which stack to drive, and refuse the owner's unless asked in full.

    Two independent guards, because they fail differently: ``--stack owner``
    is someone who MEANT the owner's stack, and ``--port 8765`` is someone who
    did not. Both end at the same refusal, and the refusal happens before any
    socket, any GET and any spend.
    """

    if stack not in {"own", "owner"}:
        raise RunnerRefusal(f"--stack must be 'own' or 'owner', got {stack!r}")
    resolved_port = port if port is not None else (
        OWNER_PANEL_PORT if stack == "owner" else DEFAULT_PORT
    )
    target = Target(host=host, port=int(resolved_port))
    if (stack == "owner" or target.is_owner_stack) and not i_am_the_owner:
        raise RunnerRefusal(
            f"refusing to drive {target.origin}: that is the owner's stack "
            f"(port {OWNER_PANEL_PORT}). This runner POSTs emergency-stop "
            f"releases and opens paid hosted sessions. Re-run with "
            f"--stack owner --i-am-the-owner if you ARE the owner; otherwise "
            f"start your own stack and pass --port."
        )
    return target


def resolve_out_dir(raw: str, *, exist_ok: bool = False) -> Path:
    """Absolute run-folder path, with the doubled-prefix trap disarmed.

    live_run_1's artifacts landed at
    ``evals/20260820/voice_corpus_v1/evals/20260820/voice_corpus_v1/live_run_1``
    because a repo-relative path was resolved against a cwd that was already
    inside the repo. The fix belongs at the collector, so here it is: the path
    is resolved once, and a resolved path that repeats a run of segments is a
    refusal rather than a surprise discovered days later by a reader.
    """

    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    resolved = Path(os.path.normpath(str(path)))
    parts = resolved.parts
    for size in range(3, len(parts) // 2 + 1):
        for start in range(len(parts) - 2 * size + 1):
            first = parts[start : start + size]
            second = parts[start + size : start + 2 * size]
            if first == second:
                raise RunnerRefusal(
                    f"--out resolves to {resolved}, which repeats the segment run "
                    f"{'/'.join(first)}. That is the doubled repo-relative prefix "
                    f"that misplaced live_run_1's artifacts: a repo-relative path "
                    f"was joined onto a cwd already inside the repo. Pass an "
                    f"absolute path, or a path relative to the current directory."
                )
    if resolved.exists() and not exist_ok:
        raise RunnerRefusal(
            f"--out {resolved} already exists. Run folders are written once; "
            f"pick a new one so an earlier run cannot be silently overwritten."
        )
    return resolved


# ----------------------------------------------------------------- stack client
class StackClient:
    """The panel's HTTP + websocket surface, as a live client would use it."""

    def __init__(self, target: Target, *, timeout: float = 10.0) -> None:
        self.target = target
        self.timeout = timeout
        self.csrf_token = ""
        self.posts = 0

    # ------------------------------------------------------------------ HTTP
    def _get(self, path: str) -> bytes:
        request = urlrequest.Request(
            f"{self.target.origin}{path}", headers={"Host": f"{self.target.host}:{self.target.port}"}
        )
        with urlrequest.urlopen(request, timeout=self.timeout) as response:
            return response.read()

    def fetch_token(self) -> str:
        """Lift the per-process CSRF token out of the panel page, as a browser does."""

        body = self._get("/").decode("utf-8", "replace")
        match = re.search(r'const CSRF_TOKEN = "([^"]+)"', body)
        if not match:
            raise RunnerAbort(
                f"{self.target.origin}/ did not contain a CSRF token; is this a Parcel panel?"
            )
        self.csrf_token = match.group(1)
        return self.csrf_token

    def state(self) -> dict[str, Any]:
        return json.loads(self._get("/api/state"))

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        request = urlrequest.Request(
            f"{self.target.origin}{path}",
            data=body,
            method="POST",
            headers={
                "Host": f"{self.target.host}:{self.target.port}",
                "Content-Type": "application/json",
                "X-Parcel-CSRF": self.csrf_token,
                "Origin": self.target.origin,
            },
        )
        self.posts += 1
        with urlrequest.urlopen(request, timeout=self.timeout) as response:
            raw = response.read()
        return json.loads(raw) if raw else {}

    # ------------------------------------------------------------- websocket
    def audio_url(self) -> str:
        return f"ws://{self.target.host}:{self.target.port}{GATEWAY_PATH}"

    def subprotocols(self) -> list[str]:
        return [SUBPROTOCOL_AUDIO, f"{CSRF_SUBPROTOCOL_PREFIX}{self.csrf_token}"]


class AudioClient:
    """One websocket to the gateway, doing exactly what ``index.html`` does.

    Minus the DOM: gesture first, then microphone frames in real time, then
    ``played`` acks for every chunk that comes back. The acks matter — R7's
    live proof could only ever truncate a barge-in at 0 ms because its headless
    client never sent one, so this client sends them and the played clock is
    exercised instead of assumed.
    """

    def __init__(self, client: StackClient, *, sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ):
        self._client = client
        self.sample_rate_hz = sample_rate_hz
        self._socket: Any = None
        self.hello: dict[str, Any] = {}
        self.audio_chunks_in = 0
        self.audio_bytes_in = 0
        self.control_frames: list[dict[str, Any]] = []
        self._utterance = 0
        self._played_ms = 0.0

    def __enter__(self) -> Self:
        from websockets.sync.client import connect

        self._socket = connect(
            self._client.audio_url(),
            subprotocols=self._client.subprotocols(),
            open_timeout=10,
            max_size=4 * 1024 * 1024,
        )
        self.hello = self._await_control("hello", timeout=5.0)
        rate = ((self.hello.get("input") or {}).get("rate")) or self.sample_rate_hz
        self.sample_rate_hz = int(rate)
        return self

    def __exit__(self, *_exc: object) -> None:
        with contextlib.suppress(Exception):
            self._socket.close()

    def arm_microphone(self, timeout: float = 10.0) -> dict[str, Any]:
        """The owner's gesture, as its own control frame. Opens the paid session."""

        self._socket.send(json.dumps({"type": "mic", "on": True}))
        reply = self._await_control("mic", timeout=timeout)
        if not reply.get("on"):
            raise RunnerAbort(
                f"the stack refused to open the microphone: {reply.get('reason', '(no reason)')}"
            )
        return reply

    def close_microphone(self) -> None:
        with contextlib.suppress(Exception):
            self._socket.send(json.dumps({"type": "mic", "on": False}))

    def _await_control(self, kind: str, *, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self._recv(timeout=deadline - time.monotonic())
            if frame is None:
                continue
            if isinstance(frame, dict) and frame.get("type") == kind:
                return frame
        raise RunnerAbort(f"timed out waiting {timeout:.0f}s for a '{kind}' frame from the gateway")

    def _recv(self, timeout: float) -> dict[str, Any] | None:
        """One frame. Binary is playback (acked); text is control (recorded)."""

        if timeout <= 0:
            return None
        try:
            message = self._socket.recv(timeout=timeout)
        except TimeoutError:
            return None
        if isinstance(message, bytes):
            self.audio_chunks_in += 1
            self.audio_bytes_in += len(message)
            payload = len(message) - 44 if message[:4] == b"RIFF" else len(message)
            self._played_ms += (payload / 2.0) / self.sample_rate_hz * 1000.0
            if self._utterance:
                with contextlib.suppress(Exception):
                    self._socket.send(
                        json.dumps(
                            {"type": "played", "utterance": self._utterance,
                             "ms": round(self._played_ms, 3)}
                        )
                    )
            return None
        body = json.loads(message)
        if isinstance(body, dict):
            self.control_frames.append(body)
            if body.get("type") == "utterance":
                self._utterance = int(body.get("utterance") or 0)
                self._played_ms = 0.0
            return body
        return None

    def pump(self, seconds: float) -> None:
        """Read (and ack) whatever arrives for ``seconds``. Never blocks longer."""

        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._recv(timeout=min(remaining, 0.25))

    def speak(self, pcm: bytes, *, pad_ms: int = 0, realtime: bool = True) -> int:
        """Stream one utterance up the microphone, in real time, framed like a browser.

        Real time is not politeness: the provider's server VAD is watching this
        stream, and a corpus blasted up at disk speed is a corpus the endpointer
        sees as one enormous utterance.
        """

        frame_bytes = int(self.sample_rate_hz * 2 * FRAME_MS / 1000)
        payload = pcm + b"\x00" * int(self.sample_rate_hz * 2 * pad_ms / 1000)
        start = time.monotonic()
        sent = 0
        for index in range(0, len(payload), frame_bytes):
            frame = payload[index : index + frame_bytes]
            self._socket.send(frame)
            sent += len(frame)
            if realtime:
                target = start + (sent / 2.0) / self.sample_rate_hz
                slack = target - time.monotonic()
                if slack > 0:
                    time.sleep(min(slack, 0.25))
            self._recv(timeout=0.0)
        return sent


# ------------------------------------------------------------------ observation
def _rows(state: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = state.get(key)
    return list(value) if isinstance(value, list) else []


def _lane(state: dict[str, Any]) -> dict[str, Any]:
    realtime = state.get("realtime")
    lane = realtime.get("lane") if isinstance(realtime, dict) else None
    return lane if isinstance(lane, dict) else {}


def _spend(state: dict[str, Any]) -> float:
    realtime = state.get("realtime")
    if not isinstance(realtime, dict):
        return 0.0
    try:
        return float(realtime.get("spend_usd") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def is_latched(state: dict[str, Any]) -> bool:
    if bool(state.get("emergency_stopped")):
        return True
    motion = state.get("motion")
    if isinstance(motion, dict) and bool(motion.get("emergency_stopped")):
        return True
    control = state.get("control")
    return isinstance(control, dict) and bool(control.get("emergency_stopped"))


@dataclass
class Baseline:
    """Everything the runner counts, sampled immediately before a query."""

    chat: int = 0
    events: int = 0
    missions: int = 0
    brokered: int = 0
    spend: float = 0.0
    latched: bool = False

    @classmethod
    def sample(cls, state: dict[str, Any]) -> Baseline:
        return cls(
            chat=len(_rows(state, "chat")),
            events=len(_rows(state, "events")),
            missions=len(_rows(state, "mission_log")),
            brokered=len(_lane(state).get("brokered_tool_calls") or []),
            spend=_spend(state),
            latched=is_latched(state),
        )


@dataclass
class Observation:
    """The delta one query produced. Attribution is by sequence, not by guess."""

    heard: list[str] = field(default_factory=list)
    said: list[str] = field(default_factory=list)
    tools: list[dict[str, str]] = field(default_factory=list)
    missions: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    latched_during: bool = False
    latched_after: bool = False
    spend_delta: float = 0.0
    settled: bool = False
    settle_reason: str = ""
    elapsed_s: float = 0.0
    open_missions: list[str] = field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        return [entry["tool"] for entry in self.tools]

    @property
    def executed_tools(self) -> list[str]:
        return [entry["tool"] for entry in self.tools if entry.get("status") == "ok"]

    @property
    def mission_goals(self) -> list[str]:
        return [str(entry.get("goal") or "") for entry in self.missions if entry.get("kind") == "started"]


TOOL_EVENT = re.compile(r"^tool ([a-z_]+): ([a-z_]+)(?:\s*[—-]\s*(.*))?$")


def observe(baseline: Baseline, state: dict[str, Any]) -> Observation:
    """Everything new in ``state`` since ``baseline``, attributed to this turn."""

    chat = _rows(state, "chat")[baseline.chat :]
    events = _rows(state, "events")[baseline.events :]
    missions = _rows(state, "mission_log")[baseline.missions :]
    observation = Observation(
        heard=[str(row.get("text") or "") for row in chat if row.get("role") == "user"],
        said=[str(row.get("text") or "") for row in chat if row.get("role") == "assistant"],
        events=events,
        missions=missions,
        latched_after=is_latched(state),
        spend_delta=round(_spend(state) - baseline.spend, 6),
    )
    for row in events:
        match = TOOL_EVENT.match(str(row.get("text") or "").strip())
        if match:
            observation.tools.append(
                {
                    "tool": match.group(1),
                    "status": match.group(2),
                    "detail": (match.group(3) or "").strip(),
                    "at": str(row.get("timestamp") or ""),
                }
            )
    started = [str(row.get("goal") or "") for row in missions if row.get("kind") == "started"]
    ended = [str(row.get("goal") or "") for row in missions if row.get("kind") == "ended"]
    for goal in started:
        if goal in ended:
            ended.remove(goal)
        else:
            observation.open_missions.append(goal)
    return observation


# ---------------------------------------------------------------------- scoring
@dataclass(frozen=True)
class Gold:
    """The gold column, parsed into the parts a program can actually check."""

    tools: tuple[str, ...]
    goal: str
    latch_expected: bool
    no_latch_expected: bool
    refusal_expected: bool
    ask_expected: bool
    forbids_mission: bool
    probe: bool


NAV_GOAL = re.compile(r"navigate_to\s+([a-z0-9 ]+)", re.IGNORECASE)
_GOAL_NOISE = re.compile(r"\b(place|class|region|or|ask|arrival|inside|near)\b", re.IGNORECASE)


def parse_gold(expected: str) -> Gold:
    lowered = expected.lower()
    tools = tuple(tool for tool in KNOWN_TOOLS if tool in lowered)
    goal = ""
    match = NAV_GOAL.search(expected)
    if match:
        raw = match.group(1).split(";")[0]
        raw = _GOAL_NOISE.sub(" ", raw)
        goal = " ".join(raw.split()).strip().lower()
        if "-" in match.group(1) or goal in {"", "food", "park", "grass"} and "class" in lowered:
            goal = ""  # "food-class place" names a category, not a mapped goal
    return Gold(
        tools=tools,
        goal=goal,
        latch_expected=("latch fires" in lowered or "should latch" in lowered
                        or "emergency latch" in lowered),
        no_latch_expected="no latch" in lowered,
        refusal_expected="refus" in lowered,
        ask_expected=("ask" in lowered or "clarif" in lowered),
        forbids_mission=any(
            phrase in lowered
            for phrase in (
                "no fabricated mission",
                "no mission",
                "no motion",
                "no guess",
                "no uncommanded mission",
                "no junk",
                "only mission after confirmation",
            )
        ),
        probe="probe" in lowered,
    )


def _matches(text: str, markers: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def score(query: Query, observation: Observation, gold: Gold) -> tuple[str, list[str], str]:
    """One verdict, its evidence and a note. Mechanical or explicitly deferred."""

    evidence: list[str] = []
    for line in observation.heard:
        evidence.append(f'heard: "{line}"')
    for line in observation.said:
        evidence.append(f'said: "{line}"')
    for entry in observation.tools:
        evidence.append(
            f"tool {entry['tool']}: {entry['status']}"
            + (f" — {entry['detail']}" if entry["detail"] else "")
        )
    for entry in observation.missions:
        evidence.append(
            f"mission {entry.get('kind')} goal={entry.get('goal')} "
            f"state={entry.get('state')} reason={entry.get('reason')}"
        )
    evidence.append(f"latched during turn: {observation.latched_during}")
    evidence.append(f"settled: {observation.settled} ({observation.settle_reason}) "
                    f"after {observation.elapsed_s:.1f}s")

    spoke = bool(observation.said)
    acted = bool(observation.tools) or bool(observation.missions)

    # 1. the emergency stop, both directions, before anything else is considered
    if gold.latch_expected:
        if observation.latched_during:
            return VERDICT_PASS, evidence, "the latch fired, which is the whole assertion."
        return (
            VERDICT_FAIL,
            evidence,
            ("no latch. Either the phrase was mis-transcribed before the matcher saw "
            "it, or the matcher declined it — the captured owner.wav for this "
            "segment is the artifact that tells those apart."),
        )
    if gold.no_latch_expected:
        if observation.latched_during:
            return VERDICT_FAIL, evidence, "FALSE LATCH: a negative-set phrase stopped the robot."
        if spoke:
            return (
                VERDICT_PASS,
                evidence,
                ("no latch, and the utterance reached the model and came back "
                "paraphrased — affirmative proof the matcher declined it rather "
                "than the turn simply vanishing."),
            )
        return (
            VERDICT_PARTIAL,
            evidence,
            ("no latch, but no reply either, so 'the matcher declined it' and 'the "
            "turn was lost' are indistinguishable from this run."),
        )

    # 2. a latch that is not this query's business
    if observation.latched_during and any(
        LATCH_REJECTION_MARKER in entry["detail"].lower() for entry in observation.tools
    ):
        return (
            VERDICT_BLOCKED,
            evidence,
            ("a motion tool was rejected by the emergency-stop latch; the reasoning "
            "above the motion gate is not scored here."),
        )

    # 3. the gold cell names tools
    if gold.tools:
        fired = [name for name in gold.tools if name in observation.tool_names]
        if fired:
            if gold.forbids_mission and observation.mission_goals:
                return (
                    VERDICT_FAIL,
                    evidence,
                    (f"the gold cell forbids a mission and one started "
                    f"({', '.join(observation.mission_goals)})."),
                )
            if gold.goal:
                goals = " ".join(observation.mission_goals).lower()
                details = " ".join(entry["detail"] for entry in observation.tools).lower()
                if gold.goal in goals or gold.goal in details:
                    return VERDICT_PASS, evidence, f"{', '.join(fired)} fired for '{gold.goal}'."
                return (
                    VERDICT_PARTIAL,
                    evidence,
                    (f"{', '.join(fired)} fired but the goal is "
                    f"{observation.mission_goals or '(none recorded)'}, not '{gold.goal}'."),
                )
            return VERDICT_PASS, evidence, f"{', '.join(fired)} fired."
        if acted:
            return (
                VERDICT_PARTIAL,
                evidence,
                (f"expected {', '.join(gold.tools)}; "
                f"{', '.join(observation.tool_names) or 'a mission'} happened instead."),
            )
        if spoke:
            return (
                VERDICT_PARTIAL,
                evidence,
                (f"a reply was spoken but {', '.join(gold.tools)} never fired — the "
                f"'talks about it, does not do it' shape."),
            )
        return VERDICT_FAIL, evidence, "nothing happened: no reply, no tool, no mission."

    # 4. refusal / ask cells
    if gold.refusal_expected or gold.ask_expected:
        if observation.mission_goals and gold.forbids_mission:
            return (
                VERDICT_FAIL,
                evidence,
                (f"a refusal or an ask was required and a mission started instead "
                f"({', '.join(observation.mission_goals)}) — the fabricated-mission defect."),
            )
        if not spoke:
            return VERDICT_FAIL, evidence, "no reply at all where a refusal or an ask was required."
        joined = " ".join(observation.said)
        if gold.ask_expected and _matches(joined, ASK_MARKERS):
            return VERDICT_PASS, evidence, "the reply asks rather than guesses."
        if gold.refusal_expected and _matches(joined, REFUSAL_MARKERS):
            return VERDICT_PASS, evidence, "the reply refuses in plain words."
        return (
            VERDICT_NEEDS_REVIEW,
            evidence,
            ("a reply exists and no mission was fabricated, but whether it reads as "
            "a real refusal or an ask is a judgement this runner will not make."),
        )

    # 5. probes have no gold behaviour by construction
    if gold.probe:
        return VERDICT_NEEDS_REVIEW, evidence, "probe: the gold cell asks to record, not to grade."

    # 6. prose cells. Silence is the one thing a program may fail on its own.
    if not spoke and not acted:
        return (
            VERDICT_FAIL,
            evidence,
            ("no reply, no tool, no event. live_run_1's headline finding was that "
            "the dominant defect is not wrong answers but no answers; this is one."),
        )
    return (
        VERDICT_NEEDS_REVIEW,
        evidence,
        ("the gold cell asks for a judgement about wording. Everything observed is "
        "recorded above for a human (or a judge model) to grade."),
    )


# ------------------------------------------------------------------------ colour
class Ink:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def verdict(self, verdict: str) -> str:
        return self(
            f"{verdict:<16}",
            {
                VERDICT_PASS: "1;32",
                VERDICT_PARTIAL: "1;33",
                VERDICT_FAIL: "1;31",
                VERDICT_BLOCKED: "1;35",
                VERDICT_NEEDS_REVIEW: "1;36",
                VERDICT_NOT_ATTEMPTED: "1;30",
            }.get(verdict, "0"),
        )


# ------------------------------------------------------------------------ runner
@dataclass
class RunnerOptions:
    pace_s: float = 2.5
    quiet_s: float = 3.0
    turn_timeout_s: float = 45.0
    mission_settle_s: float = 25.0
    poll_s: float = 0.35
    pad_ms: int = 800
    release_timeout_s: float = 8.0
    #: Consecutive turns that produce NOTHING — no transcript, no reply, no
    #: tool, no event — before the run aborts. This card's own live proof is
    #: the argument: the hosted lane went silent at q30 and the harness kept
    #: speaking into it for twenty more queries, producing twenty confident
    #: FAILs about a lane that was not answering anybody. That is the same
    #: defect as scoring against a latched robot, arriving from a different
    #: direction, and it deserves the same answer. 0 disables.
    silence_abort: int = 4
    limit: int = 0
    only: tuple[str, ...] = ()


class CorpusRunner:
    """Sequential, UI-mounted replay with e-stop hygiene that cannot be skipped."""

    def __init__(
        self,
        *,
        client: StackClient,
        queries: Sequence[Query],
        options: RunnerOptions,
        ink: Ink,
        out: Path,
        stream: Any = sys.stdout,
        audio_factory: Any = None,
    ) -> None:
        # Injectable so the harness's own logic — pacing, settling, e-stop
        # hygiene, scoring — is testable without a socket, a stack or a bill.
        self._audio_factory = audio_factory or AudioClient
        self.client = client
        self.queries = list(queries)
        self.options = options
        self.ink = ink
        self.out = out
        self.stream = stream
        self.results: list[dict[str, Any]] = []
        self.trace: list[dict[str, Any]] = []
        self.started_at = ""
        self.finished_at = ""
        self.spend_start = 0.0
        self.spend_end = 0.0
        self.latch_releases = 0
        self.aborted = ""
        self.silent_turns = 0

    # ------------------------------------------------------------------ output
    def say(self, text: str = "") -> None:
        print(text, file=self.stream, flush=True)

    # ------------------------------------------------- the e-stop hygiene gate
    def ensure_latch_clear(self, *, context: str) -> dict[str, Any]:
        """Release a latched e-stop, or ABORT. Never a warning, never a skip.

        This is item 3 of the card and the direct answer to live_run_1: 90
        seconds of that run were spoken into a robot that could not move,
        because nothing in the harness had an opinion about a latch. Releasing
        is owner-authorised for eval runs; failing to release is fatal, because
        every verdict after it would be a lie about a frozen robot.
        """

        state = self.client.state()
        if not is_latched(state):
            return {"was_latched": False, "released": False}
        self.say(self.ink("        ⏹ emergency stop is LATCHED — releasing before continuing", "1;35"))
        self.client.post("/api/action", {"action": "clear_emergency_stop"})
        self.latch_releases += 1
        deadline = time.monotonic() + self.options.release_timeout_s
        while time.monotonic() < deadline:
            time.sleep(self.options.poll_s)
            if not is_latched(self.client.state()):
                self.say(self.ink("        ⏵ latch released; the robot can move again", "1;32"))
                return {"was_latched": True, "released": True}
        raise RunnerAbort(
            f"the emergency-stop latch did not release within "
            f"{self.options.release_timeout_s:.0f}s ({context}). Refusing to speak the "
            f"rest of the corpus into a robot that cannot move: live_run_1 did that "
            f"for 84 seconds and every verdict after the latch was worthless."
        )

    def check_lane_is_answering(self, record: dict[str, Any]) -> None:
        """Abort when the stack has stopped answering. The latch lesson, generalised.

        A turn that produced no transcript, no reply, no tool and no event is
        not a slow turn — the stack did not hear it or cannot respond. One is
        noise; ``silence_abort`` in a row is a dead lane, and every verdict
        after that point is a confident statement about nothing.

        This card's own live proof is the evidence: the hosted lane went silent
        at q30 and the harness dutifully spoke twenty more queries into it,
        producing sixteen FAILs and four PARTIALs that describe the lane's
        health and not the product's behaviour — plus about $0.25 of spend to
        learn it twenty times over.
        """

        if not self.options.silence_abort:
            return
        answered = bool(record.get("said") or record.get("tools") or record.get("heard"))
        if answered or record.get("verdict") == VERDICT_NOT_ATTEMPTED:
            self.silent_turns = 0
            return
        self.silent_turns += 1
        self.say(
            self.ink(
                f"        ⚠ nothing came back for {self.silent_turns} turn(s) in a row",
                "1;33",
            )
        )
        if self.silent_turns < self.options.silence_abort:
            return
        raise RunnerAbort(
            f"the stack produced nothing at all for {self.silent_turns} consecutive "
            f"queries — no transcript, no reply, no tool, no event. The lane has "
            f"stopped answering, so every remaining verdict would describe the "
            f"lane's health rather than the product's behaviour. Check "
            f"state.realtime.lane (stalls / voice_turns_owed / recent_server_errors) "
            f"and re-run."
        )

    # -------------------------------------------------------------- turn logic
    def settle(self, audio: AudioClient, baseline: Baseline) -> Observation:
        """Wait for the turn to actually finish. Reply + tool + mission terminal."""

        start = time.monotonic()
        last_change = start
        signature: tuple[int, int, int, int] | None = None
        latched_during = False
        observation = Observation()
        while True:
            audio.pump(self.options.poll_s)
            state = self.client.state()
            observation = observe(baseline, state)
            latched_during = latched_during or is_latched(state)
            observation.latched_during = latched_during
            now = time.monotonic()
            observation.elapsed_s = now - start
            current = (
                len(observation.heard) + len(observation.said),
                len(observation.events),
                len(observation.missions),
                len(observation.tools),
            )
            if current != signature:
                signature = current
                last_change = now
            quiet_for = now - last_change
            substantive = bool(observation.said or observation.tools or observation.missions)
            if observation.open_missions and observation.elapsed_s < self.options.mission_settle_s:
                # A mission that has started and not ended is the turn still
                # happening. live_run_1 could never score arrival because the
                # next query preempted every mission 4-6 s in; this is the wait
                # that makes arrival testable at all.
                continue
            if substantive and quiet_for >= self.options.quiet_s:
                observation.settled = True
                observation.settle_reason = (
                    "quiet after a reply/tool"
                    if not observation.open_missions
                    else "mission still running at the mission-settle bound"
                )
                return observation
            if observation.elapsed_s >= self.options.turn_timeout_s:
                observation.settled = False
                observation.settle_reason = (
                    f"turn timeout at {self.options.turn_timeout_s:.0f}s with "
                    f"{'no substantive response' if not substantive else 'activity still arriving'}"
                )
                return observation

    def run_one(self, position: int, total: int, query: Query, audio: AudioClient) -> dict[str, Any]:
        header = f"[{position}/{total}] {query.category:<19} q{query.id}"
        self.say()
        self.say(self.ink(header, "1;37") + f'  "{query.query}"')
        self.say(f"        gold : {query.expected}")

        if query.wav is None:
            self.say(self.ink("        (no WAV in the corpus folder — NOT_ATTEMPTED)", "1;30"))
            return {
                "id": query.id,
                "category": query.category,
                "query": query.query,
                "expected": query.expected,
                "wav": None,
                "verdict": VERDICT_NOT_ATTEMPTED,
                "evidence": ["no recording for this id in the corpus folder"],
                "notes": "record.sh has not produced this query's WAV yet.",
                "scoring": "not_attempted",
            }

        pcm, seconds, source_hz = read_wav_as_pcm(query.wav, audio.sample_rate_hz)
        baseline = Baseline.sample(self.client.state())
        self.say(
            f"        ▶ speaking {seconds:.1f}s of {query.wav.name} "
            f"({source_hz} Hz → {audio.sample_rate_hz} Hz) …"
        )
        sent = audio.speak(pcm, pad_ms=self.options.pad_ms)
        observation = self.settle(audio, baseline)

        gold = parse_gold(query.expected)
        verdict, evidence, notes = score(query, observation, gold)

        for line in observation.heard:
            self.say(f"        heard: {self.ink(line, '0;36')}")
        for line in observation.said:
            self.say(f"        said : {self.ink(line, '0;37')}")
        for entry in observation.tools:
            colour = "0;32" if entry["status"] == "ok" else "0;31"
            self.say(
                f"        tool : {self.ink(entry['tool'] + ' → ' + entry['status'], colour)}"
                + (f"  {entry['detail']}" if entry["detail"] else "")
            )
        for goal in observation.mission_goals:
            self.say(f"        goal : {goal}")
        if not observation.settled:
            self.say(self.ink(f"        ⚠ {observation.settle_reason}", "1;33"))
        self.say(f"        {self.ink.verdict(verdict)} {notes}")

        # The latch is released by the CALLER, after this record is banked. A
        # release that fails aborts the run, and the query that caused it must
        # still be scored: losing the verdict for the very utterance that
        # latched the robot would throw away the most interesting row in the run.
        record = {
            "id": query.id,
            "category": query.category,
            "query": query.query,
            "expected": query.expected,
            "wav": query.wav.name,
            "wav_seconds": round(seconds, 3),
            "wav_source_hz": source_hz,
            "injected_bytes": sent,
            "matched_owner_turn": observation.heard[0] if observation.heard else "",
            "heard": observation.heard,
            "said": observation.said,
            "tools": observation.tools,
            "missions": observation.missions,
            "verdict": verdict,
            "evidence": evidence,
            "notes": notes,
            "scoring": "mechanical",
            "latch": {
                "fired_during_turn": observation.latched_during,
                "still_latched_after_turn": observation.latched_after,
                "released_by_runner": False,
            },
            "settled": observation.settled,
            "settle_reason": observation.settle_reason,
            "elapsed_s": round(observation.elapsed_s, 2),
            "spend_usd": observation.spend_delta,
        }
        self.say(
            f"        spend: ${observation.spend_delta:.4f}   "
            f"(run total ${_spend(self.client.state()) - self.spend_start:.4f})"
        )
        return record

    def run(self) -> None:
        selected = [
            query
            for query in self.queries
            if not self.options.only or query.id in self.options.only
        ]
        if self.options.limit:
            selected = selected[: self.options.limit]
        total = len(selected)
        state = self.client.state()
        self.spend_start = _spend(state)
        self.started_at = datetime.now(timezone.utc).isoformat()

        self.say(self.ink("── pre-flight ───────────────────────────────────────────", "1;37"))
        self.ensure_latch_clear(context="pre-flight")
        self.say(f"        stack   : {self.client.target.origin}")
        self.say(f"        mode    : {((state.get('realtime') or {}).get('mode'))}")
        self.say(f"        queries : {total}")
        self.say(f"        out     : {self.out}")
        self.say(f"        spend so far on this stack: ${self.spend_start:.4f}")

        with self._audio_factory(self.client) as audio:
            self.say(f"        gateway : {json.dumps(audio.hello)}")
            audio.arm_microphone()
            self.say(self.ink("        🎙 microphone armed by gesture — the session is open", "1;32"))
            for position, query in enumerate(selected, start=1):
                try:
                    record = self.run_one(position, total, query, audio)
                except RunnerAbort as error:
                    self.aborted = str(error)
                    self.say(self.ink(f"\n✖ ABORTED: {error}", "1;31"))
                    break
                self.results.append(record)
                try:
                    # Item 3 of the card, and it runs after EVERY query rather
                    # than only after the estop-positives: a latch can arrive
                    # from the panel's Space key or a mis-transcription, and the
                    # next query must never be spoken into a frozen robot.
                    latch = self.ensure_latch_clear(context=f"after q{query.id}")
                except RunnerAbort as error:
                    self.aborted = str(error)
                    self.say(self.ink(f"\n✖ ABORTED: {error}", "1;31"))
                    break
                if isinstance(record.get("latch"), dict):
                    record["latch"]["released_by_runner"] = bool(latch["released"])
                try:
                    self.check_lane_is_answering(record)
                except RunnerAbort as error:
                    self.aborted = str(error)
                    self.say(self.ink(f"\n✖ ABORTED: {error}", "1;31"))
                    break
                if position < total:
                    # Pace by READING the socket, not by sleeping on it: the
                    # gap is for a human to watch, and a client that stops
                    # draining playback for two seconds is a client the gateway
                    # starts counting backpressure drops against.
                    audio.pump(self.options.pace_s)
            audio.close_microphone()
            self.audio_summary = {
                "hello": audio.hello,
                "playback_chunks_received": audio.audio_chunks_in,
                "playback_bytes_received": audio.audio_bytes_in,
                "control_frames": len(audio.control_frames),
            }

        for query in selected[len(self.results) :]:
            self.results.append(
                {
                    "id": query.id,
                    "category": query.category,
                    "query": query.query,
                    "expected": query.expected,
                    "wav": query.wav.name if query.wav else None,
                    "verdict": VERDICT_NOT_ATTEMPTED,
                    "evidence": ["the run aborted before this query"],
                    "notes": self.aborted or "not reached",
                    "scoring": "not_attempted",
                }
            )
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.spend_end = _spend(self.client.state())


# ------------------------------------------------------------------- run folder
def verdict_totals(results: Sequence[dict[str, Any]]) -> dict[str, int]:
    totals = {verdict: 0 for verdict in VERDICT_ORDER}
    for row in results:
        totals[str(row.get("verdict"))] = totals.get(str(row.get("verdict")), 0) + 1
    return {key: value for key, value in totals.items() if value}


def category_totals(results: Sequence[dict[str, Any]]) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for row in results:
        bucket = grouped.setdefault(str(row.get("category")), {})
        verdict = str(row.get("verdict"))
        bucket[verdict] = bucket.get(verdict, 0) + 1
    return grouped


def write_run_folder(
    runner: CorpusRunner,
    *,
    corpus_dir: Path,
    tsv: Path,
    state: dict[str, Any],
    options: RunnerOptions,
) -> None:
    """The scored run folder, in live_run_1's shape plus one honest extension."""

    out = runner.out
    out.mkdir(parents=True, exist_ok=True)
    totals = verdict_totals(runner.results)
    attempted = [row for row in runner.results if row.get("verdict") != VERDICT_NOT_ATTEMPTED]
    results = {
        "run": str(out),
        "corpus": str(tsv),
        "corpus_audio": str(corpus_dir),
        "scored_at": datetime.now(timezone.utc).date().isoformat(),
        "scored_by": (
            "tools/run_voice_corpus.py — MECHANICAL scoring. A verdict here comes "
            "from a checkable predicate (a tool fired, a goal matched, the latch "
            "did or did not engage, a mission started where the gold cell forbade "
            "one). Gold cells that ask for a judgement about wording are recorded "
            "and returned as NEEDS_REVIEW rather than graded."
        ),
        "stack": runner.client.target.origin,
        "started_at": runner.started_at,
        "finished_at": runner.finished_at,
        "session_window": f"{runner.started_at} - {runner.finished_at}",
        "corpus_queries": len(runner.results),
        "queries_attempted": len(attempted),
        "queries_not_attempted": len(runner.results) - len(attempted),
        "raw_audio_persisted": True,
        "raw_audio_note": (
            "Every query in this run was injected from a WAV on disk in "
            f"{corpus_dir}; the audio that produced each verdict still exists and "
            "the run is repeatable."
        ),
        "aborted": runner.aborted,
        "verdict_totals": totals,
        "category_totals": category_totals(runner.results),
        "costs": {
            "spend_before_usd": round(runner.spend_start, 6),
            "spend_after_usd": round(runner.spend_end, 6),
            "run_cost_usd": round(runner.spend_end - runner.spend_start, 6),
            "per_query_usd": {
                row["id"]: row.get("spend_usd", 0.0)
                for row in runner.results
                if row.get("spend_usd") is not None
            },
        },
        "estop_hygiene": {
            "latch_releases_by_runner": runner.latch_releases,
            "latched_at_end": is_latched(state),
            "policy": (
                "every estop-pos query asserts the latch fired and the latch is "
                "then released before the next query; a latch that will not "
                "release aborts the run"
            ),
        },
        "audio_client": getattr(runner, "audio_summary", {}),
        # Card R17's two halves, joined: if the stack was also running the
        # session tee, the recording of THIS run is named here, so a reader can
        # go and listen to the audio behind any verdict below.
        "session_capture": (
            ((state.get("realtime") or {}).get("gateway") or {}).get("capture")
            if isinstance(state.get("realtime"), dict)
            else None
        ),
        "pacing": {
            "pace_s": options.pace_s,
            "quiet_s": options.quiet_s,
            "turn_timeout_s": options.turn_timeout_s,
            "mission_settle_s": options.mission_settle_s,
            "pad_ms": options.pad_ms,
            "silence_abort": options.silence_abort,
        },
        "results": runner.results,
    }
    (out / "results.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    (out / "state.json").write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    (out / "session_slices.json").write_text(
        json.dumps(
            {
                "mission_log": _rows(state, "mission_log"),
                "events": _rows(state, "events"),
                "chat": _rows(state, "chat"),
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "README.md").write_text(render_readme(results), encoding="utf-8")


def render_readme(results: dict[str, Any]) -> str:
    """A human-first summary. The JSON is evidence; this is what gets read."""

    totals = results["verdict_totals"]
    lines = [
        f"# Voice corpus replay — {Path(results['run']).name}",
        "",
        (f"UI-mounted sequential replay of `{results['corpus']}` against "
        f"**{results['stack']}**, {results['started_at']} → {results['finished_at']}."),
        "",
        (f"Every query was spoken from a WAV through the real browser audio gateway, "
        f"one at a time, waiting for each turn to settle. "
        f"**{results['queries_attempted']}/{results['corpus_queries']} attempted**, "
        f"cost **${results['costs']['run_cost_usd']:.4f}**."),
        "",
    ]
    if results["aborted"]:
        lines += [f"> **The run aborted:** {results['aborted']}", ""]
    lines += [
        "## Verdicts",
        "",
        "| verdict | n |",
        "| --- | --- |",
    ]
    for verdict in VERDICT_ORDER:
        if verdict in totals:
            lines.append(f"| {verdict} | {totals[verdict]} |")
    lines += [
        "",
        "`NEEDS_REVIEW` is not a failure: it is the runner declining to grade a gold",
        "cell that asks for a judgement about wording. Everything observed for those",
        "rows is in `results.json`.",
        "",
        "## By category",
        "",
        "| category | " + " | ".join(VERDICT_ORDER) + " |",
        "| --- |" + " --- |" * len(VERDICT_ORDER),
    ]
    for category, bucket in results["category_totals"].items():
        cells = " | ".join(str(bucket.get(verdict, "")) for verdict in VERDICT_ORDER)
        lines.append(f"| {category} | {cells} |")
    lines += [
        "",
        "## Emergency-stop hygiene",
        "",
        f"* latch releases performed by the runner: **{results['estop_hygiene']['latch_releases_by_runner']}**",
        f"* latched at the end of the run: **{results['estop_hygiene']['latched_at_end']}**",
        f"* policy: {results['estop_hygiene']['policy']}",
        "",
        "live_run_1 spent its last 84 seconds and 18 owner turns speaking into a",
        "robot that could not move. In this harness that state cannot persist past",
        "one query.",
        "",
        "## Per-query",
        "",
    ]
    for row in results["results"]:
        lines.append(f"### q{row['id']} · {row['category']} · {row['verdict']}")
        lines.append("")
        lines.append(f'*Query:* "{row["query"]}"  ')
        lines.append(f"*Gold:* {row['expected']}  ")
        if row.get("matched_owner_turn"):
            lines.append(f'*Heard:* "{row["matched_owner_turn"]}"  ')
        for said in row.get("said", []) or []:
            lines.append(f'*Said:* "{said}"  ')
        for tool in row.get("tools", []) or []:
            detail = f" — {tool['detail']}" if tool.get("detail") else ""
            lines.append(f"*Tool:* `{tool['tool']}` → {tool['status']}{detail}  ")
        lines.append("")
        lines.append(row.get("notes", ""))
        lines.append("")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_voice_corpus.py",
        description="Replay a spoken query corpus through a live Parcel stack, UI-mounted.",
    )
    parser.add_argument("--corpus", required=True, help="corpus dir holding queries.tsv and the WAVs")
    parser.add_argument("--out", required=True, help="run folder to create (must not exist)")
    parser.add_argument("--queries", default="", help="override the TSV path")
    parser.add_argument("--stack", default="own", choices=("own", "owner"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--i-am-the-owner",
        action="store_true",
        help="required to target the owner's stack; nothing else unlocks it",
    )
    parser.add_argument("--pace", type=float, default=2.5, help="seconds between queries")
    parser.add_argument("--quiet", type=float, default=3.0, help="silence that ends a turn")
    parser.add_argument("--turn-timeout", type=float, default=45.0)
    parser.add_argument("--mission-settle", type=float, default=25.0)
    parser.add_argument("--pad-ms", type=int, default=800, help="trailing silence per utterance")
    parser.add_argument(
        "--silence-abort",
        type=int,
        default=4,
        help="abort after N consecutive queries that produce nothing at all (0 disables)",
    )
    parser.add_argument("--limit", type=int, default=0, help="stop after N queries")
    parser.add_argument("--only", default="", help="comma-separated query ids")
    parser.add_argument("--no-color", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ink = Ink(enabled=not args.no_color and sys.stdout.isatty())
    try:
        target = resolve_target(
            stack=args.stack, host=args.host, port=args.port, i_am_the_owner=args.i_am_the_owner
        )
        corpus_dir = Path(args.corpus).expanduser().resolve()
        tsv = Path(args.queries).expanduser().resolve() if args.queries else corpus_dir / "queries.tsv"
        if not tsv.is_file():
            raise RunnerRefusal(f"no queries.tsv at {tsv}")
        out = resolve_out_dir(args.out)
        queries = attach_audio(load_corpus(tsv), corpus_dir)
    except RunnerRefusal as error:
        print(ink(f"refused: {error}", "1;31"), file=sys.stderr)
        return 2

    options = RunnerOptions(
        pace_s=args.pace,
        quiet_s=args.quiet,
        turn_timeout_s=args.turn_timeout,
        mission_settle_s=args.mission_settle,
        pad_ms=args.pad_ms,
        silence_abort=args.silence_abort,
        limit=args.limit,
        only=tuple(part.strip() for part in args.only.split(",") if part.strip()),
    )
    client = StackClient(target)
    try:
        client.fetch_token()
    except (urlerror.URLError, OSError) as error:
        print(ink(f"cannot reach {target.origin}: {error}", "1;31"), file=sys.stderr)
        return 3

    runner = CorpusRunner(client=client, queries=queries, options=options, ink=ink, out=out)
    exit_code = 0
    try:
        runner.run()
    except RunnerAbort as error:
        runner.aborted = str(error)
        print(ink(f"\n✖ aborted: {error}", "1;31"), file=sys.stderr)
        exit_code = 4
    finally:
        # The run folder is written even when the stack died mid-run: a partial
        # scored run is evidence and an unwritten one is nothing.
        try:
            state = client.state()
        except (urlerror.URLError, OSError, ValueError) as error:
            state = {"detail": f"the stack was unreachable at teardown: {error}"}
        write_run_folder(runner, corpus_dir=corpus_dir, tsv=tsv, state=state, options=options)
        print()
        print(ink(f"run folder: {out}", "1;37"))
        print(f"verdicts  : {json.dumps(verdict_totals(runner.results))}")
        print(f"cost      : ${runner.spend_end - runner.spend_start:.4f}")
    return exit_code


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
