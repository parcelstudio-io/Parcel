"""Typed request/response contract for the perception daemon (card P1-A).

One AF_UNIX stream, one framing rule, three operations. The framing follows the
pattern :mod:`parcel_robot.simulation.ipc` already uses — a Unix socket carrying a JSON
object — with one change forced by the payload: a 1280×720 RGB frame is 2.7 MB,
and base64 inside JSON would cost a copy, a 33 % inflation and a parse on every
frame of a 10 Hz stream. So each message is::

    [4-byte big-endian header length][UTF-8 JSON header][raw payload bytes]

The header names every payload part in order (``parts``: name, dtype, shape,
nbytes) and the payload is their concatenation. Nothing is inferred: a message
whose declared byte count disagrees with what arrives is a refusal, not a
best-effort decode.

Why a process boundary at all
-----------------------------
The detector is a GPU model that takes ~98 ms on an idle box and 132–139 ms
under this wave's concurrent load (P0-C, and Fable's refuter row C-1). The
robot's reactive path runs at 10 Hz. In-process, one CUDA stall, one ORT arena
resize or one model reload lands directly on the control loop. Out of process,
the worst case is a socket read that times out and a detector that reports
``stale`` — which the runtime already knows how to survive, because
``CameraIngress.poll_once`` never lets a detector error blank the map.

Limits, and why each one is where it is
---------------------------------------
* :data:`MAX_QUERY_PHRASES` = 16 — the SAME ceiling
  ``CameraDetectionFrame.__post_init__`` enforces ("query batch exceeds 16
  phrases"). Fable's wave verification row D-R2 measured what happens when a
  union crosses it in the ingress: every poll raises, only ``stats.errors``
  moves, and the robot goes silently blind. The daemon therefore refuses a
  17-phrase batch **loudly, at the boundary**, with the count in the message,
  instead of accepting work whose result cannot legally be published.
* :data:`MAX_PAYLOAD_BYTES` = 32 MiB — comfortably above one RGB+depth pair at
  1280×720 (6.5 MB), far below anything that could exhaust the daemon's memory.
* :data:`MAX_HEADER_BYTES` = 64 KiB — a header is metadata; one this large is a
  malformed or hostile peer.
"""

from __future__ import annotations

import json
import socket
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

PROTOCOL_VERSION = 1

#: Length prefix: unsigned 32-bit big-endian header size.
_HEADER_STRUCT = struct.Struct(">I")
HEADER_PREFIX_BYTES = _HEADER_STRUCT.size

MAX_HEADER_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = 32 * 1024 * 1024
MAX_PARTS = 4

#: Mirrors ``camera_channel.ingress.CameraDetectionFrame``'s own ceiling. See
#: the module docstring: exceeding it downstream is SILENT blindness, so it is
#: refused here where the refusal is visible.
MAX_QUERY_PHRASES = 16
MAX_PHRASE_CHARS = 64

#: Detections returned per frame. Mirrors the ingress' retention ceiling so the
#: daemon can never hand back more rows than the consumer may legally keep.
MAX_DETECTIONS = 256

OP_HEALTH = "health"
OP_DETECT = "detect"
OP_EMBED_IMAGE = "embed_image"
OP_EMBED_TEXT = "embed_text"
OP_SHUTDOWN = "shutdown"

OPERATIONS: frozenset[str] = frozenset(
    {OP_HEALTH, OP_DETECT, OP_EMBED_IMAGE, OP_EMBED_TEXT, OP_SHUTDOWN}
)

#: dtypes a payload part may declare. Deliberately a closed set: an arbitrary
#: dtype string reaching ``np.dtype`` is an unnecessary parser surface.
ALLOWED_DTYPES: frozenset[str] = frozenset({"uint8", "uint16", "float32", "float64"})

DEFAULT_SOCKET_NAME = "parcel_perception.sock"


class ProtocolError(ValueError):
    """A message violated the contract. Never a transport problem."""


class DaemonUnavailable(RuntimeError):
    """The daemon could not be reached, or the peer went away mid-message.

    Distinct from :class:`ProtocolError` on purpose: this one is the condition
    the client must DEGRADE on (return no detections, mark ``stale``), while a
    protocol error is a bug that should be visible.
    """


def default_socket_path() -> str:
    """Per-user default socket path.

    Under ``$XDG_RUNTIME_DIR`` when it exists so the socket is user-private and
    cleaned up on logout, falling back to ``/tmp``. NOT the sim's
    ``/tmp/parcel_sim.sock``: two different services sharing a path is how one
    of them silently talks to the other.
    """

    import os
    from pathlib import Path

    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    base = Path(runtime_dir) if runtime_dir and Path(runtime_dir).is_dir() else Path("/tmp")
    return str(base / DEFAULT_SOCKET_NAME)


def normalize_query(query: object) -> tuple[str, ...]:
    """Validate an open-vocab batch, refusing an over-long one BY COUNT.

    Whitespace is collapsed and duplicates are dropped before the count is
    checked, so "the same phrase twice" does not spend the budget — but the
    ceiling itself is hard, and the refusal names the number that was sent.
    """

    if query is None:
        return ()
    if isinstance(query, str):
        items: list[str] = [query]
    elif isinstance(query, Sequence):
        items = [str(item) for item in query]
    else:
        raise ProtocolError("query must be a string or a sequence of strings")
    phrases: list[str] = []
    for item in items:
        text = " ".join(str(item).split())
        if not text:
            continue
        if len(text) > MAX_PHRASE_CHARS:
            raise ProtocolError(
                f"query phrase exceeds {MAX_PHRASE_CHARS} characters: {text[:32]!r}…"
            )
        if text not in phrases:
            phrases.append(text)
    if len(phrases) > MAX_QUERY_PHRASES:
        raise ProtocolError(
            f"query batch has {len(phrases)} phrases; the ceiling is "
            f"{MAX_QUERY_PHRASES} because CameraDetectionFrame refuses more — a "
            "larger batch would produce detections that cannot be published, and "
            "the consumer would go blind while only its error counter moved"
        )
    return tuple(phrases)


@dataclass(frozen=True, slots=True)
class Part:
    """One named array in a message payload."""

    name: str
    dtype: str
    shape: tuple[int, ...]
    nbytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or len(self.name) > 32:
            raise ProtocolError("part name must be a short non-empty string")
        if self.dtype not in ALLOWED_DTYPES:
            raise ProtocolError(f"part dtype {self.dtype!r} is not allowed")
        if not self.shape or len(self.shape) > 4:
            raise ProtocolError("part shape must have 1-4 dimensions")
        for dim in self.shape:
            if isinstance(dim, bool) or not isinstance(dim, int) or dim < 1:
                raise ProtocolError("part shape dimensions must be positive integers")
        expected = int(np.dtype(self.dtype).itemsize)
        for dim in self.shape:
            expected *= int(dim)
        if self.nbytes != expected:
            raise ProtocolError(
                f"part {self.name!r} declares {self.nbytes} bytes but its shape/dtype "
                f"needs {expected}"
            )
        if self.nbytes > MAX_PAYLOAD_BYTES:
            raise ProtocolError(f"part {self.name!r} exceeds the payload ceiling")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "shape": list(self.shape),
            "nbytes": self.nbytes,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Part:
        if not isinstance(value, Mapping):
            raise ProtocolError("part must be an object")
        missing = {"name", "dtype", "shape", "nbytes"} - set(value)
        if missing:
            raise ProtocolError(f"part missing keys: {sorted(missing)}")
        shape = value["shape"]
        if not isinstance(shape, (list, tuple)):
            raise ProtocolError("part shape must be a sequence")
        return cls(
            name=str(value["name"]),
            dtype=str(value["dtype"]),
            shape=tuple(int(dim) for dim in shape),
            nbytes=int(value["nbytes"]),
        )

    @classmethod
    def for_array(cls, name: str, array: np.ndarray) -> Part:
        arr = np.ascontiguousarray(array)
        dtype = str(arr.dtype)
        if dtype not in ALLOWED_DTYPES:
            raise ProtocolError(f"array {name!r} has unsupported dtype {dtype!r}")
        return cls(name=name, dtype=dtype, shape=tuple(int(d) for d in arr.shape), nbytes=arr.nbytes)


def encode(header: Mapping[str, Any], arrays: Mapping[str, np.ndarray] | None = None) -> bytes:
    """Serialize one message. ``arrays`` become the header's ``parts`` in order."""

    body = dict(header)
    payload = b""
    if arrays:
        if len(arrays) > MAX_PARTS:
            raise ProtocolError(f"a message may carry at most {MAX_PARTS} arrays")
        parts: list[dict[str, Any]] = []
        chunks: list[bytes] = []
        total = 0
        for name, array in arrays.items():
            arr = np.ascontiguousarray(array)
            part = Part.for_array(name, arr)
            total += part.nbytes
            if total > MAX_PAYLOAD_BYTES:
                raise ProtocolError("message payload exceeds the ceiling")
            parts.append(part.as_dict())
            chunks.append(arr.tobytes())
        body["parts"] = parts
        payload = b"".join(chunks)
    else:
        body.setdefault("parts", [])
    raw = json.dumps(body, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_HEADER_BYTES:
        raise ProtocolError("message header exceeds the ceiling")
    return _HEADER_STRUCT.pack(len(raw)) + raw + payload


def _recv_exactly(sock: socket.socket, count: int) -> bytes:
    """Read exactly ``count`` bytes or raise :class:`DaemonUnavailable`."""

    if count == 0:
        return b""
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        try:
            chunk = sock.recv(min(remaining, 1 << 20))
        except (TimeoutError, socket.timeout) as exc:  # noqa: UP041 - explicit for clarity
            raise DaemonUnavailable(f"timed out reading {count} bytes") from exc
        except OSError as exc:
            raise DaemonUnavailable(f"socket error reading {count} bytes: {exc}") from exc
        if not chunk:
            raise DaemonUnavailable("peer closed the connection mid-message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def decode(sock: socket.socket) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Read exactly one message off ``sock``.

    Returns the header (with ``parts`` removed) and the decoded arrays. Raises
    :class:`DaemonUnavailable` when the peer goes away and
    :class:`ProtocolError` when it sends something the contract forbids.
    """

    prefix = _recv_exactly(sock, HEADER_PREFIX_BYTES)
    (header_len,) = _HEADER_STRUCT.unpack(prefix)
    if header_len == 0 or header_len > MAX_HEADER_BYTES:
        raise ProtocolError(f"header length {header_len} is out of bounds")
    raw = _recv_exactly(sock, header_len)
    try:
        header = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"header is not valid JSON: {exc}") from exc
    if not isinstance(header, dict):
        raise ProtocolError("header must be a JSON object")
    if int(header.get("v", 0)) != PROTOCOL_VERSION:
        raise ProtocolError(
            f"protocol version {header.get('v')!r} != {PROTOCOL_VERSION}; refusing to "
            "guess at a peer from a different build"
        )
    raw_parts = header.pop("parts", [])
    if not isinstance(raw_parts, list):
        raise ProtocolError("parts must be a list")
    if len(raw_parts) > MAX_PARTS:
        raise ProtocolError(f"a message may carry at most {MAX_PARTS} arrays")
    parts = [Part.from_mapping(item) for item in raw_parts]
    total = sum(part.nbytes for part in parts)
    if total > MAX_PAYLOAD_BYTES:
        raise ProtocolError(f"declared payload of {total} bytes exceeds the ceiling")
    payload = _recv_exactly(sock, total)
    arrays: dict[str, np.ndarray] = {}
    offset = 0
    for part in parts:
        chunk = payload[offset : offset + part.nbytes]
        offset += part.nbytes
        arrays[part.name] = np.frombuffer(chunk, dtype=np.dtype(part.dtype)).reshape(part.shape)
    return header, arrays


def request_header(op: str, request_id: int, **fields: Any) -> dict[str, Any]:
    """Build a validated request header."""

    if op not in OPERATIONS:
        raise ProtocolError(f"unknown operation {op!r}; expected one of {sorted(OPERATIONS)}")
    header: dict[str, Any] = {"v": PROTOCOL_VERSION, "op": op, "id": int(request_id)}
    header.update(fields)
    return header


def ok_header(op: str, request_id: int, **fields: Any) -> dict[str, Any]:
    header: dict[str, Any] = {
        "v": PROTOCOL_VERSION,
        "op": op,
        "id": int(request_id),
        "status": "ok",
    }
    header.update(fields)
    return header


def error_header(op: str, request_id: int, error: str, *, kind: str = "error") -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION,
        "op": str(op),
        "id": int(request_id),
        "status": "error",
        "kind": str(kind),
        "error": str(error)[:512],
    }


def detection_to_wire(detection: Any) -> dict[str, Any]:
    """``PixelDetection`` → the wire row. Boxes stay integer pixel bounds."""

    box = tuple(int(v) for v in detection.box)
    return {
        "label": str(detection.label),
        "score": float(detection.score),
        "box": list(box),
        "seg_id": None if detection.seg_id is None else int(detection.seg_id),
        "instance_key": (
            None if detection.instance_key is None else str(detection.instance_key)
        ),
    }


def detection_from_wire(value: Mapping[str, Any]) -> Any:
    """The wire row → ``PixelDetection`` (imported lazily; leaf-module rule)."""

    from parcel_robot.detection_adapter.pixel_detections import PixelDetection

    if not isinstance(value, Mapping):
        raise ProtocolError("detection must be an object")
    missing = {"label", "score", "box"} - set(value)
    if missing:
        raise ProtocolError(f"detection missing keys: {sorted(missing)}")
    box = value["box"]
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ProtocolError("detection box must be a 4-sequence")
    seg_id = value.get("seg_id")
    instance_key = value.get("instance_key")
    return PixelDetection(
        label=str(value["label"]),
        score=float(value["score"]),
        box=(int(box[0]), int(box[1]), int(box[2]), int(box[3])),
        seg_id=None if seg_id is None else int(seg_id),
        instance_key=None if instance_key is None else str(instance_key),
    )


__all__ = [
    "ALLOWED_DTYPES",
    "DEFAULT_SOCKET_NAME",
    "HEADER_PREFIX_BYTES",
    "MAX_DETECTIONS",
    "MAX_HEADER_BYTES",
    "MAX_PARTS",
    "MAX_PAYLOAD_BYTES",
    "MAX_PHRASE_CHARS",
    "MAX_QUERY_PHRASES",
    "OPERATIONS",
    "OP_DETECT",
    "OP_EMBED_IMAGE",
    "OP_EMBED_TEXT",
    "OP_HEALTH",
    "OP_SHUTDOWN",
    "PROTOCOL_VERSION",
    "DaemonUnavailable",
    "Part",
    "ProtocolError",
    "decode",
    "default_socket_path",
    "detection_from_wire",
    "detection_to_wire",
    "encode",
    "error_header",
    "normalize_query",
    "ok_header",
    "request_header",
]
