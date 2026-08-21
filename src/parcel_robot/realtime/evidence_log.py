"""Per-session JSONL evidence log — the substrate the eval model stands on.

Card EV-1 (``scrum/20260820/task_11``), work item 1, from
``research/SYNTHESIS_EVAL.md`` decision 2:

    Every false positive in Prototype B's extended checks was a 100-slot
    ring-buffer eviction artifact; the run-scoring agent hit the same wall
    attributing the e-stop latch. A per-session JSONL event log is the
    substrate the whole eval model stands on.

THE DEFECT THIS EXISTS BECAUSE OF
---------------------------------
``RobotRuntime._events`` is a 100-slot deque shared with every chatty source in
the process. R4-lite gave mission lifecycle its own ring and R21 gave safety
lifecycle its own ring for exactly this reason, and both are still *rings* —
20 and 24 slots of the most recent facts, in memory, gone at process exit.
The consequences are on the record:

* ``live_run_1`` could not attribute its own emergency latch, because the
  attributed event was flushed out of ``_events`` fourteen seconds later
  (R21 §5.1 reproduces the eviction exactly);
* the assertion bench's ``tool_provenance`` and ``unanswered_turn`` checks
  produced 17 findings on that run that were *eviction artifacts* — the tool
  event that would have explained the row had already rolled off the end.

A ring answers "what is happening"; an eval needs "what happened". So this
module writes the stream, not the window.

WHAT IT IS
----------
One append-only JSON-lines file per session, beside the R17 audio recordings'
layout: ``<root>/<session_id>/events.jsonl`` sits next to that session's
``owner.wav`` / ``robot.wav`` / ``index.json`` when audio capture is on, and is
the only file in the folder when it is off. One row per runtime fact, in the
order the runtime produced it, each tagged with the ring it also went to:

    {"seq": 1, "stream": "event",   "wall": "...", "id": 1, "role": "realtime",
     "text": "...", "level": "info"}
    {"seq": 2, "stream": "mission", "wall": "...", "kind": "started", ...}
    {"seq": 3, "stream": "safety",  "wall": "...", "kind": "latched", ...}

``seq`` is this log's own monotonic counter and is the ONLY total order across
the three streams; each ring's own ``id`` is preserved beside it, because a
reader that wants "mission row 4" must not have to count.

UNCAPPED, AND WHAT THAT COSTS
-----------------------------
There is no row limit and nothing is ever evicted: that is the entire point.
There IS a byte ceiling (:data:`DEFAULT_MAX_LOG_BYTES`), and reaching it makes
the log **stop and say so** — the last row written is a `log_closed` row naming
the cap — rather than silently dropping the oldest rows. A truncated-at-a-named-
point record is auditable; a silently-evicted one is what produced this card.
Rotation is per SESSION, not per size: a new session is a new folder, so one
file is always one conversation.

THE SAME LAW AS THE R17 TEE
---------------------------
The producers are ``_emit`` / ``_log_mission`` / ``_log_safety``, which run on
control loops, on the socket reader thread and inside ``lane.pump()``. So:

1. **The producer never does I/O.** ``offer()`` appends to a bounded deque and
   sets an event; a single daemon thread does every write.
2. **The producer never waits.** A full queue drops the row and counts it
   (``rows_dropped_queue_full``) — it never blocks a control loop on a disk.
3. **The producer never raises.** Every entry point swallows its own
   exceptions, counts them and disables the log. A broken disk may cost the
   evidence; it may never cost the conversation.

Bound 2 is the one place this design is weaker than the in-memory ring, and it
is reported rather than hidden: ``rows_dropped_queue_full`` is in the snapshot,
and a dropped row writes a `rows_dropped` marker into the file as soon as the
writer catches up, so the gap is visible from the artifact alone.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: File name inside one session folder. Deliberately shares the folder with
#: R17's ``owner.wav`` / ``robot.wav`` / ``index.json`` so that an audio byte
#: range and an event row are the same session by construction.
EVIDENCE_LOG_NAME = "events.jsonl"

#: Schema id, carried on the header row. Versioned because the assertion suite
#: and any future replay tool both read this file, and a silently-changed shape
#: is a silently-wrong verdict.
EVIDENCE_LOG_SCHEMA = "parcel.session_evidence.v1"

#: The three streams a row can belong to. A reader that wants "the events the
#: panel would have shown" filters ``stream == "event"``; the whole point of the
#: file is that it does not have to.
STREAM_EVENT = "event"
STREAM_MISSION = "mission"
STREAM_SAFETY = "safety"
STREAM_MARKER = "marker"
EVIDENCE_STREAMS: frozenset[str] = frozenset(
    {STREAM_EVENT, STREAM_MISSION, STREAM_SAFETY, STREAM_MARKER}
)

#: How many rows may wait for the writer thread. Runtime facts arrive at a
#: handful per second at their loudest (proximity chatter is already coalesced
#: upstream), so 8192 is minutes of slack — and a hard stop on the one failure
#: mode that would turn a stalled disk into unbounded memory.
DEFAULT_MAX_QUEUE_ROWS = 8192

#: Byte ceiling for ONE session's log. Reaching it stops the LOG, never the
#: session, and the stop is written into the file. 64 MiB is roughly two million
#: event rows — orders of magnitude past any real session — so this is the size
#: of "something is looping", not the size of "a long conversation".
DEFAULT_MAX_LOG_BYTES = 64 * 1024 * 1024

#: How often the file is flushed to the OS while a session runs. A killed
#: process loses at most this much; R17 learned the same lesson about its index.
FLUSH_INTERVAL_S = 1.0


def _iso(wall: float) -> str:
    return datetime.fromtimestamp(wall, tz=timezone.utc).isoformat()


class SessionEventLog:
    """The append-only per-session evidence writer.

    Constructed by the runtime, fed by the three ring writers, read by
    ``evals/assertions``. Never raises into its callers.
    """

    def __init__(
        self,
        *,
        root: str | Path,
        session_id: str,
        max_queue_rows: int = DEFAULT_MAX_QUEUE_ROWS,
        max_bytes: int = DEFAULT_MAX_LOG_BYTES,
        on_event: Callable[[str], None] | None = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.session_id = str(session_id)
        self.root = Path(root)
        self.directory = self.root / self.session_id
        self._max_queue = max(1, int(max_queue_rows))
        self.max_bytes = max(0, int(max_bytes))
        self._on_event = on_event
        self._wall = wall_clock

        self._queue: deque[dict[str, Any]] = deque()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._running = False
        self._stopping = False
        self._handle: Any = None
        self._last_flush = 0.0

        self._seq = 0
        self.rows_written = 0
        self.rows_dropped_queue_full = 0
        self.rows_dropped_after_stop = 0
        self.writer_errors = 0
        self.bytes_written = 0
        self.stopped_reason = ""
        self.started_at = ""
        self.closed_at = ""
        #: Set when a drop happened and the marker row has not been written yet.
        self._pending_drop_note = 0

    # -------------------------------------------------------------- lifecycle
    @property
    def running(self) -> bool:
        return self._running

    @property
    def path(self) -> Path:
        return self.directory / EVIDENCE_LOG_NAME

    def start(self) -> None:
        """Arm the log and write its header row.

        Unlike the R17 tee the folder IS created here, and the header row is
        written eagerly: an empty audio folder is evidence of a session that did
        not happen, but an event log with only a header is evidence of a session
        that happened and said nothing — which is precisely the shape of
        ``live_run_1``'s dead lane, and worth keeping.
        """

        with self._lock:
            if self._running:
                return
            self._running = True
            self._stopping = False
            self.started_at = _iso(self._wall())
        thread = threading.Thread(
            target=self._writer_loop, name="parcel-evidence-log", daemon=True
        )
        self._thread = thread
        thread.start()
        self._offer_row(
            STREAM_MARKER,
            {
                "kind": "log_opened",
                "schema": EVIDENCE_LOG_SCHEMA,
                "session_id": self.session_id,
                "max_bytes": self.max_bytes,
            },
        )
        self._note(f"session evidence log armed: {self.path}")

    def close(self, reason: str = "closed") -> None:
        """Drain, write the closing marker, flush and close. Never raises."""

        with self._lock:
            if not self._running:
                return
        self._offer_row(STREAM_MARKER, {"kind": "log_closed", "reason": str(reason)})
        with self._lock:
            self._stopping = True
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        self._finalize(reason)

    # ---------------------------------------------------------- producer side
    def offer(self, stream: str, row: Mapping[str, Any]) -> bool:
        """Record one runtime fact. Non-blocking; True when queued.

        ``stream`` names which ring the row also went to. An unknown stream is
        refused rather than written: the assertion suite dispatches on this
        field, and a typo that became a new stream would silently remove rows
        from every check that reads the old one.
        """

        if stream not in EVIDENCE_STREAMS:
            return False
        return self._offer_row(stream, row)

    def _offer_row(self, stream: str, row: Mapping[str, Any]) -> bool:
        try:
            with self._lock:
                if not self._running:
                    self.rows_dropped_after_stop += 1
                    return False
                if self._stopping and stream != STREAM_MARKER:
                    self.rows_dropped_after_stop += 1
                    return False
                if len(self._queue) >= self._max_queue:
                    # Drop, never wait: this call is on a control loop.
                    self.rows_dropped_queue_full += 1
                    self._pending_drop_note += 1
                    return False
                self._seq += 1
                payload: dict[str, Any] = {
                    "seq": self._seq,
                    "stream": stream,
                    "wall": _iso(self._wall()),
                }
                for key, value in row.items():
                    if key not in ("seq", "stream", "wall"):
                        payload[key] = value
                self._queue.append(payload)
            self._wake.set()
            return True
        except Exception:  # noqa: BLE001 - the log may never break the runtime
            self.writer_errors += 1
            self._running = False
            return False

    # ------------------------------------------------------------ writer side
    def _writer_loop(self) -> None:
        while True:
            self._wake.wait(timeout=0.25)
            self._wake.clear()
            try:
                self._drain()
            except Exception:  # noqa: BLE001 - a broken log disables itself
                self.writer_errors += 1
                with self._lock:
                    self._running = False
                return
            with self._lock:
                if self._stopping and not self._queue:
                    return

    def _drain(self) -> None:
        drops = 0
        while True:
            with self._lock:
                if not self._queue:
                    drops = self._pending_drop_note
                    self._pending_drop_note = 0
                    break
                row = self._queue.popleft()
            self._write_row(row)
        if drops:
            # The gap is named in the file, not only in a counter: a reader with
            # the artifact and nothing else must be able to see that rows are
            # missing here rather than infer a quiet minute.
            self._write_row(
                {
                    "seq": -1,
                    "stream": STREAM_MARKER,
                    "wall": _iso(self._wall()),
                    "kind": "rows_dropped",
                    "rows": int(drops),
                    "reason": "evidence queue full",
                }
            )
        self._flush_if_due()

    def _ensure_open(self) -> None:
        if self._handle is not None:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")

    def _write_row(self, row: Mapping[str, Any]) -> None:
        if self.max_bytes and self.bytes_written >= self.max_bytes:
            return
        try:
            line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
        except Exception:  # noqa: BLE001 - a hostile row costs its own line only
            line = json.dumps(
                {
                    "seq": row.get("seq", -1),
                    "stream": row.get("stream", STREAM_MARKER),
                    "wall": row.get("wall", ""),
                    "kind": "unserializable_row",
                },
                ensure_ascii=False,
            ) + "\n"
        self._ensure_open()
        self._handle.write(line)
        self.rows_written += 1
        self.bytes_written += len(line.encode("utf-8"))
        if self.max_bytes and self.bytes_written >= self.max_bytes:
            self._stop_at_cap()

    def _flush_if_due(self) -> None:
        if self._handle is None:
            return
        now = self._wall()
        if now - self._last_flush < FLUSH_INTERVAL_S:
            return
        self._last_flush = now
        self._handle.flush()

    def _stop_at_cap(self) -> None:
        """Reaching the byte ceiling stops the LOG and says so in the LOG."""

        if self.stopped_reason:
            return
        self.stopped_reason = "byte cap"
        text = (
            f"session evidence log reached its {self.max_bytes} byte cap and "
            "stopped; the session is UNAFFECTED and keeps running"
        )
        try:
            line = json.dumps(
                {
                    "seq": -1,
                    "stream": STREAM_MARKER,
                    "wall": _iso(self._wall()),
                    "kind": "log_capped",
                    "max_bytes": self.max_bytes,
                    "text": text,
                },
                ensure_ascii=False,
            ) + "\n"
            self._handle.write(line)
            self._handle.flush()
            self.rows_written += 1
        except Exception:  # noqa: BLE001 - the cap notice is best-effort
            self.writer_errors += 1
        with self._lock:
            self._stopping = True
        self._note(text)

    def _finalize(self, reason: str) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            self.closed_at = _iso(self._wall())
            if not self.stopped_reason:
                self.stopped_reason = reason
        handle = self._handle
        self._handle = None
        if handle is not None:
            try:
                handle.flush()
                handle.close()
            except Exception:  # noqa: BLE001 - teardown must not raise
                self.writer_errors += 1

    # ---------------------------------------------------------------- reporting
    def snapshot(self) -> dict[str, object]:
        """What ``/api/state`` shows about the log.

        ``enabled`` is stated rather than implied by the key's absence, the same
        rule R17's capture snapshot follows: off must be a fact a reader can
        see, not something they infer.
        """

        return {
            "enabled": True,
            "running": self._running,
            "path": str(self.path),
            "session_id": self.session_id,
            "rows_written": self.rows_written,
            "bytes_written": self.bytes_written,
            "rows_dropped_queue_full": self.rows_dropped_queue_full,
            "rows_dropped_after_stop": self.rows_dropped_after_stop,
            "writer_errors": self.writer_errors,
            "max_bytes": self.max_bytes,
            "stopped_reason": self.stopped_reason,
            "started_at": self.started_at,
            "closed_at": self.closed_at,
        }

    def _note(self, message: str) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(message)
        except Exception:  # noqa: BLE001 - a noisy observer is not a defect here
            self.writer_errors += 1


# ------------------------------------------------------------------- reading


def iter_event_log(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield rows from an evidence log, skipping unparseable lines.

    A killed process can leave a partial last line. Skipping it is correct and
    losing the whole file to it would not be: the point of an append-only log
    is that every complete row before the crash is still evidence.
    """

    target = Path(path)
    if not target.is_file():
        return
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def read_event_log(path: str | Path) -> list[dict[str, Any]]:
    """The whole log as a list, oldest first."""

    return list(iter_event_log(path))


def verify_event_log(rows: list[Mapping[str, Any]]) -> list[str]:
    """Name every way this log is not a complete record. Empty == complete.

    The executable statement of the property the checks depend on: no eviction,
    no reordering, and any gap named in the file itself. An assertion run over a
    log that fails this is reading a window, not a stream, and the eval model
    says so out loud rather than scoring it.
    """

    problems: list[str] = []
    if not rows:
        return ["log is empty: not even a header row"]
    first = rows[0]
    if first.get("kind") != "log_opened":
        problems.append("first row is not the log_opened header")
    schema = first.get("schema")
    if first.get("kind") == "log_opened" and schema != EVIDENCE_LOG_SCHEMA:
        problems.append(f"schema {schema!r} != {EVIDENCE_LOG_SCHEMA!r}")
    previous = 0
    for row in rows:
        seq = row.get("seq")
        if not isinstance(seq, int):
            problems.append(f"row without an integer seq: {row.get('kind', row.get('stream'))}")
            continue
        if seq < 0:
            continue  # markers written by the writer thread carry no sequence
        if seq <= previous:
            problems.append(f"seq {seq} does not follow {previous}: rows are not in order")
        elif seq != previous + 1:
            problems.append(f"seq jumps {previous} -> {seq}: {seq - previous - 1} row(s) missing")
        previous = seq
        stream = row.get("stream")
        if stream not in EVIDENCE_STREAMS:
            problems.append(f"row {seq} has unknown stream {stream!r}")
    dropped = [row for row in rows if row.get("kind") == "rows_dropped"]
    for row in dropped:
        problems.append(f"log declares {row.get('rows')} dropped row(s): the record has a hole")
    capped = [row for row in rows if row.get("kind") == "log_capped"]
    for row in capped:
        problems.append(f"log stopped at its {row.get('max_bytes')} byte cap: the record is truncated")
    return problems


__all__ = [
    "DEFAULT_MAX_LOG_BYTES",
    "DEFAULT_MAX_QUEUE_ROWS",
    "EVIDENCE_LOG_NAME",
    "EVIDENCE_LOG_SCHEMA",
    "EVIDENCE_STREAMS",
    "STREAM_EVENT",
    "STREAM_MARKER",
    "STREAM_MISSION",
    "STREAM_SAFETY",
    "SessionEventLog",
    "iter_event_log",
    "read_event_log",
    "verify_event_log",
]
