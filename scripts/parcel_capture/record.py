"""MCAP writer, MCAP reader, and the crash-safe recording loop — card PS-B.

Board: ``scrum/20260813/task_1/README.md`` §PS-B. This is the transport half of
``parcel-capture``; :mod:`scripts.parcel_capture.sidecar` is the evidence half.

Why not ``bags/recorder.py``
----------------------------
That recorder is kept and must not be edited, but it cannot carry a physical
session, and the reasons are specific:

* ``recorder.py:111`` writes every payload as a JSON line. A 1280x720 RGB8
  frame is not a JSON line.
* ``recorder.py:116`` rewrites ``manifest.json`` in full after **every**
  message, putting an O(bag) write in the per-message hot path.
* ``recorder.py:40-41`` refuses to append to a non-empty bag and never calls
  ``fsync`` — so an interrupted recording is both unresumable and, in the
  window before the page cache is flushed, unbounded in what it lost.
* ``recorder.py:94-98,114`` stamps ONE global ``sequence`` and increments it
  after the write, so a per-topic drop leaves no hole at all (PS-A's defect).

Its ``schema.py`` is the opposite: already hardware-shaped, already accepting
``source="hardware"`` and ``source_clock="sensor"``. So this card keeps the
schema, calls ``make_manifest`` unmodified, and replaces the transport.

Crash safety, and where the manifest lives
------------------------------------------
The single most important property here is that a SIGKILL mid-write leaves a
bag that is *readable up to the last complete message* and *provably truncated*
rather than provably short. Three decisions carry it:

1. **Append-only bytes, no rewrite.** The MCAP stream is the only thing in the
   hot path. Nothing already written is ever revisited, so a crash can only
   ever cost the tail.
2. **The sidecar is a recovery pass, not an exit path.** A manifest written by
   the dying process is not obtainable, so this module does not try:
   :mod:`~scripts.parcel_capture.sidecar` builds the ``parcel.bag.v1`` manifest
   by *reading the bytes that survived*. A bag whose recorder was killed still
   yields a complete, honest sidecar.
3. **Truncation is a byte-level fact, a drop is a sequence-level fact.** They
   are recorded by two independent mechanisms that cannot be confused:
   :class:`ScanTermination` comes from the framing (is there a ``DataEnd`` +
   ``Footer`` + terminal magic, and does the last record's declared length fit
   in the file?), while a drop comes from a hole in one channel's number line.
   A truncated bag has a *suffix* missing from every channel and therefore no
   holes; a dropping sensor has *interior* holes and a clean footer. The
   distinction is not a heuristic — it is which of two disjoint signals fired.

The MCAP subset written here
----------------------------
``mcap`` is not installed in ``.parcel/`` and the board forbids installing it,
so this module contains a **self-contained writer for a small subset of the
MCAP 0.9 file format**: magic, ``Header``, one ``Schema`` + one ``Channel`` per
capture channel, ``Message`` records, an optional ``Metadata`` record recording
how the session ended, ``DataEnd``, ``Footer``, terminal magic. No chunking, no
compression, no message index, no summary section. That subset is deliberate —
chunk-compressed writing buffers messages *inside* the writer, which is exactly
the state a SIGKILL destroys, and an index written at close is exactly the
structure a SIGKILL never reaches.

The risk of hand-rolling it is real and is stated in ``PSB_STATUS.md``: this
writer has never been read by the reference ``mcap`` implementation.
:func:`cross_validate_with_mcap_library` exists to settle that on the Orin,
where ``mcap`` is installable, and it reports ``UNAVAILABLE`` here rather than
claiming a validation that did not happen.

Nothing in this file arms anything
----------------------------------
There is no publisher, no ``ControlManager``, no lease, no motion client, and
no vendor SDK import. :func:`missing_dependencies` names what a live capture
would need and refuses without it; it never installs anything, and the absence
of ``unitree_sdk2py`` from the Parcel venv stays the strongest motion guarantee
the project has.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import math
import os
import shutil
import struct
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

from parcel_robot.capture import (
    CHANNELS,
    ENVELOPE_SCHEMA,
    UNCALIBRATED,
    CaptureEnvelope,
    CaptureError,
    Channel,
    ChannelHealth,
    ChannelSequenceBook,
    ChannelSequenceLedger,
    Transport,
    canonical_json,
    channel,
)
from parcel_robot.evidence_origin import EvidenceOrigin

if TYPE_CHECKING:  # pragma: no cover - annotations only; never evaluated at runtime
    from typing import Self

# --------------------------------------------------------------------------
# MCAP wire format (subset of the 0.9 specification)
# --------------------------------------------------------------------------

#: ``0x89 M C A P 0 \r \n``. The sixth byte is the format version character.
MCAP_MAGIC = b"\x89MCAP0\r\n"

OP_HEADER = 0x01
OP_FOOTER = 0x02
OP_SCHEMA = 0x03
OP_CHANNEL = 0x04
OP_MESSAGE = 0x05
OP_CHUNK = 0x06
OP_MESSAGE_INDEX = 0x07
OP_CHUNK_INDEX = 0x08
OP_ATTACHMENT = 0x09
OP_ATTACHMENT_INDEX = 0x0A
OP_STATISTICS = 0x0B
OP_METADATA = 0x0C
OP_METADATA_INDEX = 0x0D
OP_SUMMARY_OFFSET = 0x0E
OP_DATA_END = 0x0F

#: Spec opcodes this reader knowingly steps over. A ``Chunk`` is deliberately
#: NOT here: it contains messages, and skipping it would silently lose them.
_SKIPPABLE_OPCODES = frozenset(
    {
        OP_MESSAGE_INDEX,
        OP_CHUNK_INDEX,
        OP_ATTACHMENT,
        OP_ATTACHMENT_INDEX,
        OP_STATISTICS,
        OP_METADATA_INDEX,
        OP_SUMMARY_OFFSET,
    }
)

#: Written into the ``Header`` record. Not a ROS profile: these payloads are
#: Parcel capture envelopes, and claiming ``ros2`` would invite a consumer to
#: decode them as CDR.
MCAP_PROFILE = "parcel-capture"
MCAP_LIBRARY = "parcel-capture minimal-mcap writer v1"

#: ``Channel.message_encoding``. Every message is a length-prefixed
#: :data:`~parcel_robot.capture.ENVELOPE_SCHEMA` JSON header followed by the
#: raw device bytes, unmodified.
MESSAGE_ENCODING = "parcel.capture.envelope.v1+raw"
SCHEMA_ENCODING = "parcel.capture.channel.v1+json"

#: ``Channel.metadata`` key carrying the PS-A channel id verbatim, so the
#: reverse mapping from topic to channel is read rather than inferred.
CHANNEL_ID_METADATA_KEY = "parcel_channel_id"

#: Name of the ``Metadata`` record the recorder writes at close. Its absence is
#: itself evidence: a bag without it was never closed by its recorder.
CLOSE_METADATA_NAME = "parcel.capture.close.v1"

#: Largest record this reader will allocate for. Far above any plausible
#: message (a 1280x720 RGB8 frame is 2.6 MiB) and far below a length prefix
#: read out of corrupted bytes.
MAX_RECORD_BYTES = 512 * 1024 * 1024

_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")
_RECORD_HEADER = struct.Struct("<BQ")


class McapWriteError(RuntimeError):
    """A value that cannot be represented in the MCAP wire format."""


class McapReadError(RuntimeError):
    """A bag whose bytes could not be decoded. Never a partial guess."""


class NotAnMcapFileError(McapReadError):
    """The file does not begin with the MCAP magic at all."""


class RecorderRefusedError(RuntimeError):
    """The recorder declined to start or to accept a message."""


class RecorderLatchedError(RuntimeError):
    """A write failed; the recording is over and says why.

    Carries the :class:`LatchReason` so a caller classifies without parsing
    text, and so the close-metadata record can name it inside the bag.
    """

    def __init__(self, reason: LatchReason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail


class LiveSourceUnavailableError(RuntimeError):
    """A live channel cannot be read here, with the reason and what to do."""


def _u16(value: int, *, field: str) -> bytes:
    return _pack(_U16, value, field=field, limit=0xFFFF)


def _u32(value: int, *, field: str) -> bytes:
    return _pack(_U32, value, field=field, limit=0xFFFF_FFFF)


def _u64(value: int, *, field: str) -> bytes:
    return _pack(_U64, value, field=field, limit=0xFFFF_FFFF_FFFF_FFFF)


def _pack(fmt: struct.Struct, value: int, *, field: str, limit: int) -> bytes:
    """Range-check then pack. An out-of-range value is a refusal, never a wrap.

    A silently wrapped sequence number would fabricate a duplicate, which is
    the one thing the per-channel number line must never contain.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise McapWriteError(f"{field} must be an int, got {type(value).__name__} {value!r}")
    if not 0 <= value <= limit:
        raise McapWriteError(f"{field} must be in [0, {limit}], got {value!r}")
    return fmt.pack(value)


def _string(value: str, *, field: str) -> bytes:
    if not isinstance(value, str):
        raise McapWriteError(f"{field} must be a str, got {type(value).__name__}")
    encoded = value.encode("utf-8")
    return _u32(len(encoded), field=f"len({field})") + encoded


def _blob(value: bytes, *, field: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise McapWriteError(f"{field} must be bytes, got {type(value).__name__}")
    payload = bytes(value)
    return _u32(len(payload), field=f"len({field})") + payload


def _string_map(value: Mapping[str, str], *, field: str) -> bytes:
    body = b"".join(
        _string(str(key), field=f"{field}.key") + _string(str(item), field=f"{field}.value")
        for key, item in value.items()
    )
    return _u32(len(body), field=f"len({field})") + body


def _record(opcode: int, content: bytes) -> bytes:
    return _RECORD_HEADER.pack(opcode, len(content)) + content


def channel_schema_bytes(entry: Channel) -> bytes:
    """The self-describing ``Schema`` payload written for one channel.

    A bag that carries its own slice of ``CHANNEL_MATRIX.md`` can be read six
    months from now without this repository at the right commit.
    """

    return json.dumps(
        {
            "channel_id": entry.channel_id,
            "human_name": entry.human_name,
            "device": entry.device.value,
            "transport": entry.transport.value,
            "address": entry.address,
            "message_type": entry.message_type,
            "rate_kind": entry.rate_kind.value,
            "nominal_rate_hz": entry.nominal_rate_hz,
            "frame_id": entry.frame_id,
            "criticality": entry.criticality.value,
            "presence": entry.presence.value,
            "matrix_row": entry.matrix_row,
            "note": entry.note,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def frame_payload(envelope: CaptureEnvelope, payload: bytes) -> bytes:
    """``uint32 header_len | envelope JSON | raw device bytes``.

    The envelope travels *with* the bytes rather than in a side table, because
    a side table is a second file to lose.
    """

    header = canonical_json(envelope).encode("utf-8")
    return _u32(len(header), field="envelope_header_len") + header + bytes(payload)


def unframe_payload(data: bytes) -> tuple[dict[str, Any], bytes]:
    """Inverse of :func:`frame_payload`. Malformed input raises, never defaults."""

    if len(data) < _U32.size:
        raise McapReadError(f"message payload is {len(data)} bytes, too short for a header")
    (header_len,) = _U32.unpack_from(data, 0)
    end = _U32.size + header_len
    if end > len(data):
        raise McapReadError(
            f"message payload declares a {header_len}-byte envelope header but carries "
            f"{len(data) - _U32.size} bytes after the prefix"
        )
    try:
        record = json.loads(data[_U32.size : end].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise McapReadError(f"envelope header is not decodable JSON: {error}") from error
    if not isinstance(record, dict):
        raise McapReadError(f"envelope header must be a JSON object, got {type(record).__name__}")
    return record, data[end:]


class MinimalMcapWriter:
    """Streaming, append-only writer for the MCAP subset described above.

    It owns no buffering policy of its own: it writes to the handle it is
    given, and the caller decides when bytes leave the process. That is the
    point — the durability knob belongs to :class:`CaptureRecorder`, which is
    the thing that knows what a crash would cost.
    """

    __slots__ = ("_channel_ids", "_finished", "_handle", "_offset")

    def __init__(
        self,
        handle: BinaryIO,
        *,
        profile: str = MCAP_PROFILE,
        library: str = MCAP_LIBRARY,
    ) -> None:
        self._handle = handle
        self._channel_ids: dict[str, int] = {}
        self._finished = False
        self._offset = 0
        self._emit(MCAP_MAGIC)
        self._emit(
            _record(
                OP_HEADER,
                _string(profile, field="profile") + _string(library, field="library"),
            )
        )

    @property
    def bytes_written(self) -> int:
        return self._offset

    @property
    def finished(self) -> bool:
        return self._finished

    def register(self, entry: Channel) -> int:
        """Write the ``Schema`` + ``Channel`` pair for one capture channel.

        Registration happens before any message, so even a bag truncated in its
        first second still describes every channel it was going to record.
        """

        if entry.channel_id in self._channel_ids:
            raise McapWriteError(f"channel already registered: {entry.channel_id}")
        assigned = len(self._channel_ids) + 1
        self._emit(
            _record(
                OP_SCHEMA,
                _u16(assigned, field="schema_id")
                + _string(entry.message_type, field="schema_name")
                + _string(SCHEMA_ENCODING, field="schema_encoding")
                + _blob(channel_schema_bytes(entry), field="schema_data"),
            )
        )
        self._emit(
            _record(
                OP_CHANNEL,
                _u16(assigned, field="channel_id")
                + _u16(assigned, field="schema_id")
                + _string(entry.bag_topic, field="topic")
                + _string(MESSAGE_ENCODING, field="message_encoding")
                + _string_map(
                    {
                        CHANNEL_ID_METADATA_KEY: entry.channel_id,
                        "frame_id": entry.frame_id,
                        "envelope_schema": ENVELOPE_SCHEMA,
                    },
                    field="channel_metadata",
                ),
            )
        )
        self._channel_ids[entry.channel_id] = assigned
        return assigned

    def write_message(
        self,
        channel_id: str,
        *,
        sequence: int,
        log_time_ns: int,
        publish_time_ns: int,
        data: bytes,
    ) -> int:
        """Append one ``Message`` record. Returns the bytes it occupied."""

        if self._finished:
            raise McapWriteError("writer already finished")
        assigned = self._channel_ids.get(channel_id)
        if assigned is None:
            raise McapWriteError(f"channel not registered: {channel_id!r}")
        content = (
            _u16(assigned, field="message.channel_id")
            + _u32(sequence, field="message.sequence")
            + _u64(log_time_ns, field="message.log_time")
            + _u64(publish_time_ns, field="message.publish_time")
            + bytes(data)
        )
        return self._emit(_record(OP_MESSAGE, content))

    def write_metadata(self, name: str, metadata: Mapping[str, str]) -> int:
        if self._finished:
            raise McapWriteError("writer already finished")
        return self._emit(
            _record(
                OP_METADATA,
                _string(name, field="metadata.name")
                + _string_map(metadata, field="metadata.map"),
            )
        )

    def finish(self) -> int:
        """Write ``DataEnd``, ``Footer`` and the terminal magic.

        Their presence is the ONLY thing that makes a bag clean rather than
        truncated, so nothing else in this class may write them.

        ``data_section_crc`` and ``summary_crc`` are written as ``0``, the
        spec's "not available" value. That is a deliberate refusal to emit a
        checksum whose exact byte range this implementation has not validated
        against the reference reader — a wrong CRC is worse than an absent one.
        """

        if self._finished:
            raise McapWriteError("writer already finished")
        written = self._emit(_record(OP_DATA_END, _u32(0, field="data_section_crc")))
        written += self._emit(
            _record(
                OP_FOOTER,
                _u64(0, field="summary_start")
                + _u64(0, field="summary_offset_start")
                + _u32(0, field="summary_crc"),
            )
        )
        written += self._emit(MCAP_MAGIC)
        self._finished = True
        return written

    def _emit(self, chunk: bytes) -> int:
        self._handle.write(chunk)
        self._offset += len(chunk)
        return len(chunk)


# --------------------------------------------------------------------------
# Reading a bag back, including one that was killed mid-write
# --------------------------------------------------------------------------


class ScanTermination(str, Enum):
    """How the byte stream ended. Three disjoint outcomes, none permissive."""

    #: ``DataEnd`` + ``Footer`` + terminal magic, nothing after them.
    CLEAN = "clean"
    #: The file ends before a record it already declared, or before the
    #: terminal structure. The recorder did not get to close the bag.
    TRUNCATED = "truncated"
    #: Bytes are all present but do not decode. Corruption, not a short write.
    CORRUPT = "corrupt"


@dataclass(frozen=True)
class ScannedMessage:
    """One message recovered from a bag."""

    channel: Channel
    envelope: CaptureEnvelope
    log_time_ns: int
    publish_time_ns: int
    payload_bytes: int
    offset: int
    payload: bytes | None = None


@dataclass(frozen=True)
class McapScan:
    """Everything the bytes on disk say, and nothing they do not.

    :attr:`termination` is a statement about the FRAMING. It is deliberately
    independent of :meth:`ledger`, which is a statement about the per-channel
    number lines, so that "the recorder was killed" and "a sensor dropped
    messages" can never be inferred from the same evidence.
    """

    path: Path
    file_bytes: int
    messages: tuple[ScannedMessage, ...]
    channels: tuple[Channel, ...]
    termination: ScanTermination
    detail: str
    last_complete_offset: int
    trailing_bytes: int
    saw_data_end: bool
    saw_footer: bool
    saw_terminal_magic: bool
    skipped_records: int
    close_metadata: Mapping[str, str] | None
    profile: str
    library: str

    @property
    def is_clean(self) -> bool:
        return self.termination is ScanTermination.CLEAN

    @property
    def message_count(self) -> int:
        return len(self.messages)

    def counts(self) -> dict[str, int]:
        """Messages recovered per channel id, in table order."""

        tally = {entry.channel_id: 0 for entry in self.channels}
        for message in self.messages:
            tally[message.channel.channel_id] = tally.get(message.channel.channel_id, 0) + 1
        return tally

    def ledger(self) -> ChannelSequenceLedger:
        """Per-channel number lines read back off the record."""

        ledger = ChannelSequenceLedger()
        ledger.observe_all(message.envelope for message in self.messages)
        return ledger

    def origins(self) -> frozenset[EvidenceOrigin]:
        return frozenset(message.envelope.origin for message in self.messages)


class _Cursor:
    """Bounded reader over one record's content. A short field is an error."""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def _take(self, count: int, field: str) -> bytes:
        end = self._pos + count
        if end > len(self._data):
            raise McapReadError(
                f"record field {field} wants {count} bytes, only "
                f"{len(self._data) - self._pos} remain"
            )
        chunk = self._data[self._pos : end]
        self._pos = end
        return chunk

    def u16(self, field: str) -> int:
        return _U16.unpack(self._take(_U16.size, field))[0]

    def u32(self, field: str) -> int:
        return _U32.unpack(self._take(_U32.size, field))[0]

    def u64(self, field: str) -> int:
        return _U64.unpack(self._take(_U64.size, field))[0]

    def string(self, field: str) -> str:
        length = self.u32(f"len({field})")
        try:
            return self._take(length, field).decode("utf-8")
        except UnicodeDecodeError as error:
            raise McapReadError(f"record field {field} is not UTF-8: {error}") from error

    def blob(self, field: str) -> bytes:
        return self._take(self.u32(f"len({field})"), field)

    def string_map(self, field: str) -> dict[str, str]:
        body = _Cursor(self.blob(field))
        pairs: dict[str, str] = {}
        while body.remaining:
            key = body.string(f"{field}.key")
            pairs[key] = body.string(f"{field}.value")
        return pairs

    def rest(self) -> bytes:
        chunk = self._data[self._pos :]
        self._pos = len(self._data)
        return chunk

    @property
    def remaining(self) -> int:
        return len(self._data) - self._pos


def read_mcap(path: Path | str, *, keep_payloads: bool = False) -> McapScan:
    """Recover every complete message, and classify how the file ends.

    Never raises on a truncated or corrupt bag — that is the point; recovery is
    the normal case after a crash. It raises only when the file is not an MCAP
    file at all, which is a different finding and must not be reported as
    truncation.
    """

    path = Path(path)
    try:
        file_bytes = path.stat().st_size
    except OSError as error:
        raise McapReadError(f"cannot stat {path}: {error}") from error

    messages: list[ScannedMessage] = []
    by_mcap_id: dict[int, Channel] = {}
    ordered: list[Channel] = []
    close_metadata: dict[str, str] | None = None
    profile = ""
    library = ""
    skipped = 0
    saw_data_end = False
    saw_footer = False
    saw_terminal_magic = False
    termination = ScanTermination.CLEAN
    detail = ""
    offset = 0

    with path.open("rb") as handle:
        magic = handle.read(len(MCAP_MAGIC))
        if magic != MCAP_MAGIC:
            if len(magic) < len(MCAP_MAGIC) and MCAP_MAGIC.startswith(magic):
                return McapScan(
                    path=path,
                    file_bytes=file_bytes,
                    messages=(),
                    channels=(),
                    termination=ScanTermination.TRUNCATED,
                    detail=(
                        f"file ends inside the leading MCAP magic after {len(magic)} of "
                        f"{len(MCAP_MAGIC)} bytes"
                    ),
                    last_complete_offset=0,
                    trailing_bytes=file_bytes,
                    saw_data_end=False,
                    saw_footer=False,
                    saw_terminal_magic=False,
                    skipped_records=0,
                    close_metadata=None,
                    profile="",
                    library="",
                )
            raise NotAnMcapFileError(
                f"{path} does not begin with the MCAP magic (got {magic!r})"
            )
        offset = len(MCAP_MAGIC)

        while True:
            head = handle.read(_RECORD_HEADER.size)
            if not head:
                break
            if len(head) < _RECORD_HEADER.size:
                termination = ScanTermination.TRUNCATED
                detail = (
                    f"record header truncated at offset {offset}: {len(head)} of "
                    f"{_RECORD_HEADER.size} bytes"
                )
                break
            opcode, length = _RECORD_HEADER.unpack(head)
            if length > MAX_RECORD_BYTES:
                termination = ScanTermination.CORRUPT
                detail = (
                    f"record opcode 0x{opcode:02x} at offset {offset} declares {length} "
                    f"bytes, above the {MAX_RECORD_BYTES}-byte ceiling"
                )
                break
            content = handle.read(length)
            if len(content) < length:
                termination = ScanTermination.TRUNCATED
                detail = (
                    f"record opcode 0x{opcode:02x} at offset {offset} declares {length} "
                    f"bytes, {len(content)} present"
                )
                break

            try:
                if opcode == OP_HEADER:
                    cursor = _Cursor(content)
                    profile = cursor.string("profile")
                    library = cursor.string("library")
                elif opcode == OP_SCHEMA:
                    pass  # self-describing, and the channel record is authoritative
                elif opcode == OP_CHANNEL:
                    entry, mcap_id = _decode_channel(content)
                    if mcap_id in by_mcap_id:
                        raise McapReadError(f"duplicate MCAP channel id {mcap_id}")
                    by_mcap_id[mcap_id] = entry
                    ordered.append(entry)
                elif opcode == OP_MESSAGE:
                    messages.append(
                        _decode_message(
                            content,
                            by_mcap_id=by_mcap_id,
                            offset=offset,
                            keep_payload=keep_payloads,
                        )
                    )
                elif opcode == OP_METADATA:
                    cursor = _Cursor(content)
                    name = cursor.string("metadata.name")
                    pairs = cursor.string_map("metadata.map")
                    if name == CLOSE_METADATA_NAME:
                        close_metadata = pairs
                elif opcode == OP_DATA_END:
                    saw_data_end = True
                elif opcode == OP_FOOTER:
                    saw_footer = True
                    offset += _RECORD_HEADER.size + length
                    trailer = handle.read(len(MCAP_MAGIC))
                    if trailer == MCAP_MAGIC:
                        saw_terminal_magic = True
                        offset += len(MCAP_MAGIC)
                        if handle.read(1):
                            termination = ScanTermination.CORRUPT
                            detail = "bytes present after the terminal MCAP magic"
                    else:
                        termination = ScanTermination.TRUNCATED
                        detail = (
                            f"footer present but terminal magic is {len(trailer)} of "
                            f"{len(MCAP_MAGIC)} bytes"
                        )
                    break
                elif opcode == OP_CHUNK:
                    raise McapReadError(
                        "chunked MCAP is not readable by this recovery reader; the "
                        "messages inside the chunk would be silently lost"
                    )
                elif opcode in _SKIPPABLE_OPCODES:
                    skipped += 1
                else:
                    raise McapReadError(f"unknown MCAP opcode 0x{opcode:02x}")
            except (McapReadError, CaptureError) as error:
                termination = ScanTermination.CORRUPT
                detail = f"record opcode 0x{opcode:02x} at offset {offset}: {error}"
                break
            offset += _RECORD_HEADER.size + length

    if termination is ScanTermination.CLEAN and not (saw_data_end and saw_terminal_magic):
        termination = ScanTermination.TRUNCATED
        detail = (
            f"file ends without a complete terminal structure "
            f"(data_end={saw_data_end}, footer={saw_footer}, magic={saw_terminal_magic})"
        )

    return McapScan(
        path=path,
        file_bytes=file_bytes,
        messages=tuple(messages),
        channels=tuple(ordered),
        termination=termination,
        detail=detail,
        last_complete_offset=offset,
        trailing_bytes=max(file_bytes - offset, 0),
        saw_data_end=saw_data_end,
        saw_footer=saw_footer,
        saw_terminal_magic=saw_terminal_magic,
        skipped_records=skipped,
        close_metadata=close_metadata,
        profile=profile,
        library=library,
    )


def _decode_channel(content: bytes) -> tuple[Channel, int]:
    cursor = _Cursor(content)
    mcap_id = cursor.u16("channel.id")
    cursor.u16("channel.schema_id")
    topic = cursor.string("channel.topic")
    encoding = cursor.string("channel.message_encoding")
    metadata = cursor.string_map("channel.metadata")
    if encoding != MESSAGE_ENCODING:
        raise McapReadError(
            f"channel {topic!r} declares message_encoding {encoding!r}, expected "
            f"{MESSAGE_ENCODING!r}"
        )
    declared = metadata.get(CHANNEL_ID_METADATA_KEY)
    if declared is None:
        raise McapReadError(f"channel {topic!r} carries no {CHANNEL_ID_METADATA_KEY}")
    entry = channel(declared)
    if entry.bag_topic != topic:
        raise McapReadError(
            f"channel metadata says {declared!r} but the topic is {topic!r}; the bag "
            f"disagrees with itself"
        )
    return entry, mcap_id


def _decode_message(
    content: bytes,
    *,
    by_mcap_id: Mapping[int, Channel],
    offset: int,
    keep_payload: bool,
) -> ScannedMessage:
    cursor = _Cursor(content)
    mcap_id = cursor.u16("message.channel_id")
    sequence = cursor.u32("message.sequence")
    log_time = cursor.u64("message.log_time")
    publish_time = cursor.u64("message.publish_time")
    entry = by_mcap_id.get(mcap_id)
    if entry is None:
        raise McapReadError(f"message names unregistered MCAP channel id {mcap_id}")
    record, payload = unframe_payload(cursor.rest())
    envelope = CaptureEnvelope.from_dict(record)
    if envelope.channel_id != entry.channel_id:
        raise McapReadError(
            f"message on channel {entry.channel_id!r} carries an envelope for "
            f"{envelope.channel_id!r}"
        )
    if envelope.sequence != sequence:
        raise McapReadError(
            f"MCAP sequence {sequence} disagrees with envelope sequence "
            f"{envelope.sequence} on {entry.channel_id}"
        )
    return ScannedMessage(
        channel=entry,
        envelope=envelope,
        log_time_ns=log_time,
        publish_time_ns=publish_time,
        payload_bytes=len(payload),
        offset=offset,
        payload=payload if keep_payload else None,
    )


def sha256_file(path: Path | str, *, block_bytes: int = 1024 * 1024) -> tuple[str, int]:
    """Streaming digest and size. Returns ``(hexdigest, byte_count)``.

    Streaming rather than ``read_bytes()`` because the thing being digested may
    be hundreds of gibibytes and the machine doing it has 8-16 GiB of RAM.
    """

    digest = hashlib.sha256()
    total = 0
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(block_bytes)
            if not block:
                break
            digest.update(block)
            total += len(block)
    return digest.hexdigest(), total


# --------------------------------------------------------------------------
# Space budget: refusing to start is cheaper than a truncated session
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SpaceBudget:
    """What the caller expects to write. There is no default.

    ``bytes_per_second`` is PS-E's arithmetic, not this module's guess. A
    recorder constructed without a budget refuses to start, because "we did not
    compute it" must not be the permissive answer to "is there room".
    """

    bytes_per_second: float
    duration_s: float
    #: Headroom over the raw estimate. Filesystems need slack, and a bag that
    #: fills the volume takes the attestation and the sidecar down with it.
    margin: float = 0.15

    def __post_init__(self) -> None:
        for name in ("bytes_per_second", "duration_s", "margin"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RecorderRefusedError(f"SpaceBudget.{name} must be a number, got {value!r}")
            if not math.isfinite(value):
                raise RecorderRefusedError(f"SpaceBudget.{name} must be finite, got {value!r}")
        if self.bytes_per_second <= 0.0 or self.duration_s <= 0.0:
            raise RecorderRefusedError(
                "SpaceBudget needs a positive rate and duration; a zero budget is not a "
                "budget"
            )
        if self.margin < 0.0:
            raise RecorderRefusedError("SpaceBudget.margin must be non-negative")

    @property
    def required_bytes(self) -> int:
        return int(self.bytes_per_second * self.duration_s * (1.0 + self.margin)) + 1


@dataclass(frozen=True)
class SpaceCheck:
    free_bytes: int
    required_bytes: int
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "free_bytes": self.free_bytes,
            "required_bytes": self.required_bytes,
            "ok": self.ok,
            "detail": self.detail,
        }


def check_space(destination: Path | str, budget: SpaceBudget | None) -> SpaceCheck:
    """Fail closed: no budget, or an unreadable volume, is a refusal."""

    target = Path(destination)
    probe = target if target.exists() else target.parent
    if budget is None:
        return SpaceCheck(
            free_bytes=-1,
            required_bytes=-1,
            ok=False,
            detail=(
                "no SpaceBudget supplied — the PS-E budget for the requested duration is "
                "required before recording; unknown is not permission"
            ),
        )
    try:
        free = shutil.disk_usage(probe).free
    except OSError as error:
        return SpaceCheck(
            free_bytes=-1,
            required_bytes=budget.required_bytes,
            ok=False,
            detail=f"cannot read free space at {probe}: {error}",
        )
    required = budget.required_bytes
    ok = free >= required
    return SpaceCheck(
        free_bytes=free,
        required_bytes=required,
        ok=ok,
        detail=(
            f"{free} bytes free at {probe}, {required} required for "
            f"{budget.duration_s:g}s at {budget.bytes_per_second:g} B/s "
            f"(+{budget.margin:.0%} margin)"
        ),
    )


# --------------------------------------------------------------------------
# The recorder
# --------------------------------------------------------------------------


class LatchReason(str, Enum):
    """Why a recording ended other than by being asked to.

    Mirrors W0-B's ``JOURNAL_WRITE_FAILED`` lane: the first latch wins, the
    record survives, and degradation is named rather than absorbed.
    """

    DISK_FULL = "disk_full"
    WRITE_FAILED = "write_failed"
    ENCODE_FAILED = "encode_failed"


_DISK_FULL_ERRNOS = frozenset(
    code
    for code in (getattr(errno, name, None) for name in ("ENOSPC", "EDQUOT"))
    if code is not None
)


@dataclass(frozen=True)
class RecorderSummary:
    """The recorder's own account of the session, as it closed."""

    bag_id: str
    path: Path
    messages_written: int
    counts: Mapping[str, int]
    drops: Mapping[str, int]
    bytes_written: int
    closed_cleanly: bool
    reason: str
    latch_reason: LatchReason | None
    latch_detail: str
    close_problem: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "bag_id": self.bag_id,
            "path": str(self.path),
            "messages_written": self.messages_written,
            "counts": dict(self.counts),
            "drops": dict(self.drops),
            "bytes_written": self.bytes_written,
            "closed_cleanly": self.closed_cleanly,
            "reason": self.reason,
            "latch_reason": None if self.latch_reason is None else self.latch_reason.value,
            "latch_detail": self.latch_detail,
            "close_problem": self.close_problem,
        }


class CaptureRecorder:
    """Stamp, frame and append one session's messages to an MCAP bag.

    Contract, in the order it matters:

    * It **refuses to start** without a :class:`SpaceBudget` that fits, over an
      empty path, with a declared origin.
    * It mints the per-channel sequence at receipt via PS-A's
      :class:`~parcel_robot.capture.ChannelSequenceBook`, so a message accepted
      here and not on disk leaves a hole with a channel's name on it.
    * A write failure **latches** under a named reason, refuses every later
      message, and still closes the file. Degradation is never silent.
    * ``close()`` writes the recorder's own account into the bag as a
      ``Metadata`` record before the footer, so a reader can compare what the
      recorder believed it wrote against what survived.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        bag_id: str,
        channels: Sequence[Channel],
        origin: EvidenceOrigin,
        budget: SpaceBudget | None,
        fixture_label: str | None = None,
        calibration_ref: str = UNCALIBRATED,
        fsync_every_messages: int | None = None,
        fsync_every_ns: int | None = 1_000_000_000,
        buffer_bytes: int = 256 * 1024,
    ) -> None:
        if not bag_id.strip():
            raise RecorderRefusedError("bag_id must be non-empty")
        if not isinstance(origin, EvidenceOrigin) or origin is EvidenceOrigin.UNKNOWN:
            raise RecorderRefusedError(
                f"origin must be a declared EvidenceOrigin, got {origin!r} — a recording "
                f"that declares nothing must never pass for a physical measurement"
            )
        entries = tuple(channels)
        if not entries:
            raise RecorderRefusedError("a recording with no channels records nothing")
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, Channel):
                raise RecorderRefusedError(f"channels must be Channel records, got {entry!r}")
            if entry.channel_id in seen:
                raise RecorderRefusedError(f"duplicate channel: {entry.channel_id}")
            seen.add(entry.channel_id)
        if buffer_bytes < 1024:
            raise RecorderRefusedError("buffer_bytes must be at least 1024")

        self._path = Path(path)
        self._bag_id = bag_id
        self._channels = entries
        self._origin = origin
        self._fixture_label = fixture_label
        self._calibration_ref = calibration_ref
        self._fsync_every_messages = fsync_every_messages
        self._fsync_every_ns = fsync_every_ns

        # The directory has to exist before free space on it can be measured;
        # creating it is the only side effect a refusal may leave behind.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._space = check_space(self._path, budget)
        if not self._space.ok:
            raise RecorderRefusedError(f"refusing to start: {self._space.detail}")
        if self._path.exists() and self._path.stat().st_size > 0:
            raise RecorderRefusedError(
                f"refusing to overwrite a non-empty bag: {self._path} — a session's bytes "
                f"are never reconstructable"
            )

        self._book = ChannelSequenceBook()
        self._counts: dict[str, int] = {entry.channel_id: 0 for entry in entries}
        self._drops: dict[str, int] = {entry.channel_id: 0 for entry in entries}
        self._written = 0
        self._latch: tuple[LatchReason, str] | None = None
        self._closed = False
        self._close_problem = ""
        self._since_fsync = 0
        self._last_fsync_ns: int | None = None

        self._handle = self._path.open("wb", buffering=buffer_bytes)
        try:
            self._writer = MinimalMcapWriter(self._handle)
            for entry in entries:
                self._writer.register(entry)
            self._sync()
        except BaseException:
            self._handle.close()
            raise

    # ----------------------------------------------------------- properties

    @property
    def path(self) -> Path:
        return self._path

    @property
    def space_check(self) -> SpaceCheck:
        return self._space

    @property
    def latched(self) -> bool:
        return self._latch is not None

    @property
    def latch_reason(self) -> LatchReason | None:
        return None if self._latch is None else self._latch[0]

    @property
    def latch_detail(self) -> str:
        return "" if self._latch is None else self._latch[1]

    @property
    def messages_written(self) -> int:
        return self._written

    @property
    def counts(self) -> Mapping[str, int]:
        return dict(self._counts)

    @property
    def drops(self) -> Mapping[str, int]:
        return dict(self._drops)

    # --------------------------------------------------------------- record

    def record(
        self,
        channel_id: str,
        payload: bytes,
        *,
        host_monotonic_ns: int,
        host_realtime_ns: int,
        source_timestamp_ns: int | None = None,
        health: ChannelHealth = ChannelHealth.UNKNOWN,
    ) -> CaptureEnvelope:
        """Stamp and append one received message.

        Raises rather than returning a sentinel in every failure mode: a
        malformed message is a :class:`~parcel_robot.capture.CaptureRefusedError`
        from PS-A, a latched recorder is a :class:`RecorderLatchedError`, and a
        write failure latches first and then raises. There is no path on which
        this returns normally without bytes having reached the writer.
        """

        if self._closed:
            raise RecorderRefusedError("recorder is closed")
        if self._latch is not None:
            raise RecorderLatchedError(self._latch[0], self._latch[1])
        if channel_id not in self._counts:
            raise RecorderRefusedError(
                f"channel {channel_id!r} was not declared for this recording; declared: "
                f"{sorted(self._counts)}"
            )
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise RecorderRefusedError(
                f"payload must be raw bytes, got {type(payload).__name__} — this recorder "
                f"does not serialise for its caller"
            )
        envelope = self._book.stamp(
            channel_id,
            host_monotonic_ns=host_monotonic_ns,
            host_realtime_ns=host_realtime_ns,
            origin=self._origin,
            source_timestamp_ns=source_timestamp_ns,
            fixture_label=self._fixture_label,
            calibration_ref=self._calibration_ref,
            health=health,
        )
        try:
            self._writer.write_message(
                channel_id,
                sequence=envelope.sequence,
                log_time_ns=host_realtime_ns,
                # MCAP demands a uint64 here. When the device gives no clock we
                # repeat log_time rather than invent one; the authoritative
                # answer is the envelope's explicitly null source_timestamp_ns.
                publish_time_ns=(
                    host_realtime_ns if source_timestamp_ns is None else source_timestamp_ns
                ),
                data=frame_payload(envelope, bytes(payload)),
            )
        except McapWriteError as error:
            self._latch_failure(LatchReason.ENCODE_FAILED, str(error))
            raise RecorderLatchedError(LatchReason.ENCODE_FAILED, str(error)) from error
        except OSError as error:
            reason = (
                LatchReason.DISK_FULL
                if error.errno in _DISK_FULL_ERRNOS
                else LatchReason.WRITE_FAILED
            )
            detail = f"{type(error).__name__}({error.errno}) writing {channel_id}: {error}"
            self._latch_failure(reason, detail)
            raise RecorderLatchedError(reason, detail) from error

        self._counts[channel_id] += 1
        self._written += 1
        self._maybe_sync(host_monotonic_ns)
        return envelope

    def drop(self, channel_id: str, *, reason: str) -> int:
        """Burn a sequence number for a message received and NOT written.

        A capture stack with a bounded queue must be able to drop under
        backpressure — the alternative is unbounded memory on an 8 GiB Orin.
        What it must never do is drop *silently*, and this is why PS-A mints
        the sequence at receipt: calling this leaves an INTERIOR hole in one
        channel's number line, so the loss is provable from the bag alone and
        is attributed to exactly the channel that suffered it.

        The count is also carried in the close record, giving the sidecar two
        independent statements about the same loss to reconcile.
        """

        if self._closed:
            raise RecorderRefusedError("recorder is closed")
        if channel_id not in self._counts:
            raise RecorderRefusedError(f"channel {channel_id!r} was not declared")
        if not reason.strip():
            raise RecorderRefusedError("a drop must state its reason")
        self._drops[channel_id] += 1
        return self._book.next_sequence(channel_id)

    def close(self, *, reason: str = "complete") -> RecorderSummary:
        """Close the bag, best effort, and never raise.

        Every step here can fail on a full or read-only volume, and none of
        those failures may cost the operator the bytes already on disk. A
        problem is reported in :attr:`RecorderSummary.close_problem` and, where
        it prevented the footer, shows up in the scan as a truncation — which
        is the truth.
        """

        if self._closed:
            return self._summary(reason=reason)
        self._closed = True
        problems: list[str] = []
        try:
            self._writer.write_metadata(CLOSE_METADATA_NAME, self._close_metadata(reason))
        except (OSError, McapWriteError) as error:
            problems.append(f"close metadata: {error}")
        try:
            self._writer.finish()
        except (OSError, McapWriteError) as error:
            problems.append(f"footer: {error}")
        try:
            self._sync()
        except OSError as error:
            problems.append(f"fsync: {error}")
        try:
            self._handle.close()
        except OSError as error:
            problems.append(f"close: {error}")
        self._close_problem = "; ".join(problems)
        return self._summary(reason=reason)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, _tb: object) -> None:
        if exc_type is None:
            self.close()
        else:
            self.close(reason=f"aborted: {getattr(exc_type, '__name__', exc_type)}")

    # -------------------------------------------------------------- private

    def _summary(self, *, reason: str) -> RecorderSummary:
        latched = self._latch
        return RecorderSummary(
            bag_id=self._bag_id,
            path=self._path,
            messages_written=self._written,
            counts=dict(self._counts),
            drops=dict(self._drops),
            bytes_written=self._writer.bytes_written,
            closed_cleanly=self._writer.finished and not self._close_problem,
            reason=reason if latched is None else latched[0].value,
            latch_reason=None if latched is None else latched[0],
            latch_detail="" if latched is None else latched[1],
            close_problem=self._close_problem,
        )

    def _close_metadata(self, reason: str) -> dict[str, str]:
        latched = self._latch
        return {
            "bag_id": self._bag_id,
            "reason": reason if latched is None else latched[0].value,
            "latch_reason": "" if latched is None else latched[0].value,
            "latch_detail": "" if latched is None else latched[1],
            "messages_written": str(self._written),
            "counts": json.dumps(self._counts, sort_keys=True, separators=(",", ":")),
            "drops": json.dumps(self._drops, sort_keys=True, separators=(",", ":")),
            "envelope_schema": ENVELOPE_SCHEMA,
            "origin": self._origin.value,
            "space_check": json.dumps(self._space.to_dict(), sort_keys=True),
        }

    def _latch_failure(self, reason: LatchReason, detail: str) -> None:
        """First latch wins, exactly as W0-B's session does."""

        if self._latch is None:
            self._latch = (reason, detail)

    def _maybe_sync(self, host_monotonic_ns: int) -> None:
        self._since_fsync += 1
        if self._fsync_every_messages and self._since_fsync >= self._fsync_every_messages:
            self._sync_or_latch()
            return
        if self._fsync_every_ns is None:
            return
        if self._last_fsync_ns is None:
            self._last_fsync_ns = host_monotonic_ns
            return
        if host_monotonic_ns - self._last_fsync_ns >= self._fsync_every_ns:
            self._last_fsync_ns = host_monotonic_ns
            self._sync_or_latch()

    def _sync_or_latch(self) -> None:
        try:
            self._sync()
        except OSError as error:
            reason = (
                LatchReason.DISK_FULL
                if error.errno in _DISK_FULL_ERRNOS
                else LatchReason.WRITE_FAILED
            )
            detail = f"{type(error).__name__}({error.errno}) on fsync: {error}"
            self._latch_failure(reason, detail)
            raise RecorderLatchedError(reason, detail) from error

    def _sync(self) -> None:
        self._since_fsync = 0
        self._handle.flush()
        os.fsync(self._handle.fileno())


# --------------------------------------------------------------------------
# Live-source dependency seam — declared, gated, and never installed
# --------------------------------------------------------------------------

#: What a live reader for each transport would need to import. This module
#: never imports any of them; it reports and refuses.
TRANSPORT_DEPENDENCIES: Mapping[Transport, tuple[str, ...]] = {
    Transport.DDS: ("rclpy",),
    Transport.UNILIDAR_SDK2: ("unilidar_sdk2",),
    Transport.VENDOR_VIDEO: ("unitree_sdk2py",),
    Transport.REALSENSE: ("pyrealsense2",),
    Transport.PLATFORM_TOOL: (),
    Transport.SERIAL: ("serial",),
    Transport.VENDOR_UWB: ("unitree_sdk2py",),
    Transport.USB_AUDIO: ("sounddevice",),
}

#: Executables a live reader would shell out to. ``tegrastats`` is a binary,
#: not a module, so a module probe alone would call it READY on a laptop that
#: has never seen a Jetson — unknown must read as absent, not as ready.
TRANSPORT_EXECUTABLES: Mapping[Transport, tuple[str, ...]] = {
    Transport.DDS: (),
    Transport.UNILIDAR_SDK2: (),
    Transport.VENDOR_VIDEO: (),
    Transport.REALSENSE: (),
    Transport.PLATFORM_TOOL: ("tegrastats",),
    Transport.SERIAL: (),
    Transport.VENDOR_UWB: (),
    Transport.USB_AUDIO: (),
}

INSTALL_HINTS: Mapping[str, str] = {
    "rclpy": "Orin only: source /opt/ros/humble/setup.bash (JetPack 6.2.x ships it)",
    "tegrastats": "Orin only: ships with JetPack; absent on any non-Jetson host",
    "unilidar_sdk2": "Orin only: build unitree unilidar_sdk2 and put it on PYTHONPATH",
    "unitree_sdk2py": (
        "Orin only, and NEVER into .parcel/ — its absence from the Parcel venv is the "
        "project's strongest motion guarantee (PHYSICAL_SESSION_PLAN.md)"
    ),
    "pyrealsense2": "Orin only: pip install pyrealsense2 inside the deploy venv",
    "serial": "Orin only: pip install pyserial inside the deploy venv",
    "sounddevice": "Orin only: pip install sounddevice inside the deploy venv",
    "mcap": (
        "optional, cross-validation only: pip install mcap inside the DEPLOY venv to "
        "check this writer against the reference reader"
    ),
}

_UNMAPPED = sorted(
    member.value
    for member in Transport
    if member not in TRANSPORT_DEPENDENCIES or member not in TRANSPORT_EXECUTABLES
)
if _UNMAPPED:  # pragma: no cover - import-time invariant
    raise RecorderRefusedError(
        f"transports with no declared dependencies: {_UNMAPPED} — an unmapped transport "
        f"must not silently read as 'nothing required'"
    )


def module_available(name: str) -> bool:
    """True only if the module can be located. Any failure reads as absent."""

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def missing_requirements(entry: Channel) -> tuple[str, ...]:
    """Everything a live reader for this channel needs and does not have.

    Modules and executables together, because either one absent means the
    channel cannot be read — and "we did not check" must never look like
    "ready".
    """

    absent = [
        name
        for name in TRANSPORT_DEPENDENCIES[entry.transport]
        if not module_available(name)
    ]
    absent.extend(
        name
        for name in TRANSPORT_EXECUTABLES[entry.transport]
        if shutil.which(name) is None
    )
    return tuple(absent)


def missing_dependencies(channels: Iterable[Channel]) -> dict[str, tuple[str, ...]]:
    """Per channel id, what a live reader needs and does not have."""

    report: dict[str, tuple[str, ...]] = {}
    for entry in channels:
        absent = missing_requirements(entry)
        if absent:
            report[entry.channel_id] = absent
    return report


def dependency_report(channels: Iterable[Channel]) -> str:
    """Human-readable, actionable. Printed by ``--check``; never a traceback.

    The presence column is PS-A's prior, not a probe: ``LIVE`` here means "we
    expect this on the confirmed hardware", never "it is there". PS-D settles
    that against the unit.
    """

    entries = tuple(channels)
    missing = missing_dependencies(entries)
    lines = [f"channels requested: {len(entries)}"]
    for entry in entries:
        absent = missing.get(entry.channel_id, ())
        state = (
            "reader deps present"
            if not absent
            else f"UNAVAILABLE (missing: {', '.join(absent)})"
        )
        lines.append(
            f"  {entry.channel_id:<24} {entry.transport.value:<15} "
            f"{entry.presence.value:<18} {state}"
        )
    if missing:
        lines.append("")
        lines.append("what each missing requirement needs:")
        for name in sorted({name for names in missing.values() for name in names}):
            lines.append(f"  {name}: {INSTALL_HINTS.get(name, 'not declared')}")
    return "\n".join(lines)


def resolve_live_source(entry: Channel) -> Any:
    """The live reader for this channel, or a refusal that names what is missing.

    **Amended by card PS-G.** As shipped by PS-B this function refused for every
    transport ("there is no live backend on this card") and
    ``preflight.py``'s ``unavailable_reader_factory`` did the same, which meant
    the capture stack had a recorder and nothing to record — the tranche's
    blocking defect. :mod:`scripts.parcel_capture.ingest` now owns the DDS,
    RealSense and L2 readers, and this seam resolves through it.

    The refusal path is unchanged and still fires here, because none of
    ``rclpy``, ``pyrealsense2`` or ``unilidar_sdk2`` is installed on this box and
    the board forbids installing them. What changed is that the refusal now
    means "the dependency is absent", not "nobody wrote the reader".

    The import is deliberately local: ``ingest`` imports ``preflight``, and
    keeping the edge inside the call means neither module's import graph grows a
    cycle and ``record.py`` stays importable with the subpackage absent.
    """

    absent = missing_requirements(entry)
    if absent:
        hints = "; ".join(f"{name}: {INSTALL_HINTS.get(name, 'not declared')}" for name in absent)
        raise LiveSourceUnavailableError(
            f"{entry.channel_id}: cannot read {entry.transport.value} here — missing "
            f"{', '.join(absent)}. {hints}"
        )
    try:
        from .ingest import adapter_for
    except ImportError as error:  # pragma: no cover - the subpackage ships beside this file
        raise LiveSourceUnavailableError(
            f"{entry.channel_id}: the ingest subpackage is not importable ({error}); the "
            f"PS-E rehearsal sources drive CaptureRecorder through this same seam"
        ) from error
    try:
        return adapter_for(entry)
    except Exception as error:  # any resolution failure is a refusal, never a traceback
        raise LiveSourceUnavailableError(
            f"{entry.channel_id}: {entry.transport.value} dependencies are present but no "
            f"ingest adapter resolved — {error}"
        ) from error


def cross_validate_with_mcap_library(path: Path | str) -> tuple[str, str]:
    """Read the bag back with the reference ``mcap`` package, if it exists.

    Returns ``(status, detail)`` where status is ``"validated"``, ``"failed"``
    or ``"unavailable"``. It is ``"unavailable"`` on this dev box by design —
    ``mcap`` is not installed and the board forbids installing it — and the
    sidecar records that as an unproven claim rather than a passed one.
    """

    if not module_available("mcap"):
        return (
            "unavailable",
            (
                "the reference mcap package is not installed here; this writer has not been "
                "read by the reference implementation (run on the Orin deploy venv)"
            ),
        )
    try:  # pragma: no cover - no mcap on this host, by board rule
        from mcap.reader import make_reader  # type: ignore[import-not-found]

        with Path(path).open("rb") as handle:
            reader = make_reader(handle)
            count = sum(1 for _ in reader.iter_messages())
        return ("validated", f"reference mcap reader decoded {count} message(s)")
    except Exception as error:  # noqa: BLE001 - any failure is the finding
        return ("failed", f"reference mcap reader rejected the bag: {error}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

_EXIT_OK = 0
_EXIT_REFUSED = 2
_EXIT_DEPENDENCIES = 3
_EXIT_BAG_NOT_CLEAN = 4
#: Byte-clean framing, but a channel lost messages between receipt and record.
#: A separate code from 4 on purpose: the two failures have different causes,
#: different fixes, and must never collapse into one signal.
_EXIT_CHANNEL_LOSS = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.parcel_capture.record",
        description=(
            "parcel-capture: read-only multi-channel sensor recorder. Subscribes, reads "
            "device handles, and writes MCAP. It never publishes, never arms anything, "
            "and never installs a vendor SDK."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report per-channel live-source readiness and free space, then exit",
    )
    parser.add_argument(
        "--verify",
        metavar="BAG.mcap",
        help="scan an existing bag and report how it ends (clean/truncated/corrupt)",
    )
    parser.add_argument(
        "--dest", metavar="DIR", default=".", help="destination directory for the space check"
    )
    parser.add_argument(
        "--duration-s", type=float, default=None, help="planned session length, seconds"
    )
    parser.add_argument(
        "--bytes-per-second",
        type=float,
        default=None,
        help="PS-E budget for the selected channel set; required before recording",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Refuses with an actionable message; never tracebacks."""

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.verify:
            return _cli_verify(Path(args.verify))
        return _cli_check(args)
    except (McapReadError, RecorderRefusedError, LiveSourceUnavailableError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return _EXIT_REFUSED
    except OSError as error:
        print(f"REFUSED: {type(error).__name__}: {error}", file=sys.stderr)
        return _EXIT_REFUSED


def _cli_verify(path: Path) -> int:
    scan = read_mcap(path)
    print(f"bag: {scan.path}")
    print(f"bytes: {scan.file_bytes}  messages recovered: {scan.message_count}")
    print(f"termination: {scan.termination.value}")
    if scan.detail:
        print(f"detail: {scan.detail}")
    print(f"last complete offset: {scan.last_complete_offset}  trailing: {scan.trailing_bytes}")
    if scan.close_metadata is not None:
        print(f"recorder close record: {dict(scan.close_metadata)}")
    else:
        print("recorder close record: ABSENT (the recorder never closed this bag)")
    reports = scan.ledger().report()
    lost = 0
    for channel_id, count in sorted(scan.counts().items()):
        report = reports.get(channel_id)
        gap = "" if report is None else f"  missing={report.missing_count}"
        lost += 0 if report is None else report.missing_count
        print(f"  {channel_id:<28} {count}{gap}")
    if not scan.is_clean:
        return _EXIT_BAG_NOT_CLEAN
    if lost:
        print(
            f"PER-CHANNEL LOSS: {lost} message(s) were received and never written. The "
            f"framing is intact, so this is loss, not truncation."
        )
        return _EXIT_CHANNEL_LOSS
    return _EXIT_OK


def _cli_check(args: argparse.Namespace) -> int:
    entries = CHANNELS
    print(dependency_report(entries))
    print()
    budget = None
    if args.bytes_per_second is not None and args.duration_s is not None:
        budget = SpaceBudget(
            bytes_per_second=args.bytes_per_second, duration_s=args.duration_s
        )
    space = check_space(Path(args.dest), budget)
    print(f"space: {'OK' if space.ok else 'REFUSED'} — {space.detail}")
    have_mcap = module_available("mcap")
    print(
        f"mcap reference reader: {'present' if have_mcap else 'ABSENT'} — "
        f"{INSTALL_HINTS['mcap']}"
    )
    missing = missing_dependencies(entries)
    if missing or not space.ok:
        print()
        print(
            "REFUSED: this host cannot run a live capture. That is the expected outcome "
            "on the dev box: the capture stack is a deploy artifact for the Orin "
            "(JetPack 6.2.x / Humble / Python 3.10). Nothing was installed.",
            file=sys.stderr,
        )
        return _EXIT_DEPENDENCIES
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())
