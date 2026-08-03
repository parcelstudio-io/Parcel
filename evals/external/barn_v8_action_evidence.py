"""Deterministic, tamper-evident per-action artifacts for the BARN v8 trial.

The artifact contains only evaluator-visible inputs and outputs: the exact
normalized float64 scan bins, their geometry, and the final command published
to the BARN boundary.  Every record embeds a certificate recomputed by the
independent evaluator checker.  Policy notes are reduced to SHA-256 digests;
policy-provided certificates or private policy state are never accepted.

Files use a versioned little-endian frame format wrapped in zlib with frozen
parameters.  Per-record SHA-256 chaining and duplicated stream/file metadata
make truncation, reordering, and ordinary mutation detectable.  This is an
integrity format, not a cryptographic signature against an attacker capable of
rewriting an entire artifact and all of its hashes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import time
import uuid
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .barn_v8_action_certifier import (
    FROZEN_V8_BARN_EVALUATOR_PROFILE,
    V8BarnActionCertificate,
    certify_v8_published_barn_action,
)

V8_ACTION_EVIDENCE_FORMAT_ID = "parcel-barn-v8-action-evidence-v1"
V8_ACTION_EVIDENCE_VERSION = 1
V8_ACTION_EVIDENCE_ARMS = ("reference", "candidate")

_FILE_MAGIC = b"PV8AEZ01"
_STREAM_MAGIC = b"PV8AES01"
_FRAME_MAGIC = b"V8RF"
_TRAILER_MAGIC = b"PV8AET01"
_COMPRESSION_ID_ZLIB = 1
_ZLIB_LEVEL = 9
_ZLIB_WBITS = 15
_ZLIB_MEM_LEVEL = 9
_ZLIB_STRATEGY = zlib.Z_FIXED
_RAY_COUNT = 720
_SCAN_STRUCT = struct.Struct("<720d")
_SCAN_SIZE_BYTES = _SCAN_STRUCT.size
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ZERO_DIGEST = b"\x00" * 32
_MAX_ARM_BYTES = 32
_MAX_CERTIFICATE_BYTES = 64 * 1024
_MAX_RECORD_BYTES = 128 * 1024
_MAX_RECORDS = 1_000_000
_MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024

# file magic, version, compression settings, producing zlib version, record
# count, raw/compressed sizes, chain root, raw/compressed/profile digests.
_FILE_HEADER = struct.Struct("<8sHBBBBB8sQQQ32s32s32s32s")
_STREAM_HEADER = struct.Struct("<8sH32sQ")
_FRAME_HEADER = struct.Struct("<4sI32s32s")
_TRAILER = struct.Struct("<8sQ32s")

# step, paired execution order, world, trial, seed, three flags + reserved,
# scan geometry, vx/vy/yaw, arm length, note digest, certificate length.
_RECORD_PREFIX = struct.Struct("<QQQQQBBBBdddddH32sI")
_RECORD_CHAIN_DOMAIN = b"parcel-barn-v8-action-evidence-record-chain-v1\x00"
_RECORD_GENESIS_DOMAIN = b"parcel-barn-v8-action-evidence-genesis-v1\x00"


class V8ActionEvidenceError(ValueError):
    """Raised when evidence violates the frozen format or semantic contract."""


def _sha256_bytes(payload: bytes) -> bytes:
    return hashlib.sha256(payload).digest()


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_certificate(certificate: V8BarnActionCertificate) -> bytes:
    return json.dumps(
        certificate.as_dict(),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _uint64(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not 0 <= value <= (1 << 64) - 1:
        raise ValueError(f"{name} must fit an unsigned 64-bit integer")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be boolean")
    return value


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _arm_bytes(arm: object) -> bytes:
    if not isinstance(arm, str) or arm not in V8_ACTION_EVIDENCE_ARMS:
        raise ValueError(f"arm must be one of {V8_ACTION_EVIDENCE_ARMS!r}")
    encoded = arm.encode("utf-8")
    if not encoded or len(encoded) > _MAX_ARM_BYTES:
        raise ValueError("arm encoding is invalid")
    return encoded


def _note_digest(note: object) -> bytes:
    if not isinstance(note, str):
        raise TypeError("note must be a string")
    return hashlib.sha256(note.encode("utf-8")).digest()


def _profile_digest() -> bytes:
    return bytes.fromhex(FROZEN_V8_BARN_EVALUATOR_PROFILE.identity_sha256)


def _genesis_digest() -> bytes:
    return _sha256_bytes(_RECORD_GENESIS_DOMAIN + _profile_digest())


def _record_digest(previous_digest: bytes, payload: bytes) -> bytes:
    return _sha256_bytes(_RECORD_CHAIN_DOMAIN + previous_digest + payload)


def _zlib_version_field() -> bytes:
    encoded = zlib.ZLIB_RUNTIME_VERSION.encode("ascii")
    if not encoded or len(encoded) > 8:
        raise RuntimeError("zlib runtime version cannot be represented in evidence header")
    return encoded.ljust(8, b"\x00")


def _fixed_compress(payload: bytes) -> bytes:
    compressor = zlib.compressobj(
        level=_ZLIB_LEVEL,
        method=zlib.DEFLATED,
        wbits=_ZLIB_WBITS,
        memLevel=_ZLIB_MEM_LEVEL,
        strategy=_ZLIB_STRATEGY,
    )
    return compressor.compress(payload) + compressor.flush(zlib.Z_FINISH)


def _fixed_decompress(payload: bytes, *, expected_size: int) -> bytes:
    if not 0 <= expected_size <= _MAX_UNCOMPRESSED_BYTES:
        raise V8ActionEvidenceError("declared uncompressed evidence size is invalid")
    decompressor = zlib.decompressobj(wbits=_ZLIB_WBITS)
    try:
        result = decompressor.decompress(payload, expected_size + 1)
        if len(result) > expected_size or decompressor.unconsumed_tail:
            raise V8ActionEvidenceError("decompressed evidence exceeds its declared size")
        result += decompressor.flush()
    except zlib.error as exc:
        raise V8ActionEvidenceError("compressed evidence payload is invalid or truncated") from exc
    if not decompressor.eof:
        raise V8ActionEvidenceError("compressed evidence payload is truncated")
    if decompressor.unused_data or decompressor.unconsumed_tail:
        raise V8ActionEvidenceError("compressed evidence payload has trailing data")
    if len(result) != expected_size:
        raise V8ActionEvidenceError("uncompressed evidence size mismatch")
    return result


@dataclass(frozen=True, slots=True)
class V8ActionEvidenceRecord:
    """One verified action, exact scan bytes, and independent certificate."""

    step_index: int
    execution_order: int
    arm: str
    world_id: int
    trial_id: int
    seed: int
    issued_by_policy: bool
    observation_reused: bool
    angle_min_rad: float
    angle_increment_rad: float
    normalized_scan_float64_le: bytes
    published_vx_mps: float
    published_vy_mps: float
    published_yaw_rate_rps: float
    published_stop: bool
    note_sha256: str
    certificate: V8BarnActionCertificate
    previous_record_sha256: str
    record_sha256: str

    @property
    def normalized_scan_m(self) -> tuple[float, ...]:
        return _SCAN_STRUCT.unpack(self.normalized_scan_float64_le)

    @property
    def normalized_scan_float64_sha256(self) -> str:
        return _sha256_hex(self.normalized_scan_float64_le)

    def report_metadata(self) -> dict[str, Any]:
        """Return scalar metadata without duplicating the 5,760-byte scan."""

        return {
            "step_index": self.step_index,
            "execution_order": self.execution_order,
            "arm": self.arm,
            "world_id": self.world_id,
            "trial_id": self.trial_id,
            "seed": self.seed,
            "issued_by_policy": self.issued_by_policy,
            "observation_reused": self.observation_reused,
            "angle_min_rad": self.angle_min_rad,
            "angle_increment_rad": self.angle_increment_rad,
            "normalized_scan_float64_sha256": self.normalized_scan_float64_sha256,
            "published_vx_mps": self.published_vx_mps,
            "published_vy_mps": self.published_vy_mps,
            "published_yaw_rate_rps": self.published_yaw_rate_rps,
            "published_stop": self.published_stop,
            "note_sha256": self.note_sha256,
            "certificate": self.certificate.as_dict(),
            "previous_record_sha256": self.previous_record_sha256,
            "record_sha256": self.record_sha256,
        }


@dataclass(frozen=True, slots=True)
class V8ActionEvidenceArtifactIdentity:
    """Content and episode identity returned after write or verification."""

    format_id: str
    format_version: int
    path: str
    artifact_sha256: str
    artifact_size_bytes: int
    compressed_payload_sha256: str
    compressed_payload_size_bytes: int
    uncompressed_payload_sha256: str
    uncompressed_payload_size_bytes: int
    record_count: int
    root_record_sha256: str
    profile_id: str
    profile_sha256: str
    arm: str
    execution_order: int
    world_id: int
    trial_id: int
    seed: int
    compression: Mapping[str, str | int]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class V8EvidenceOverheadMetadata:
    """Evaluator overhead, explicitly excluded from controller latency."""

    operation: str
    certificate_recomputation_ns: int
    record_validation_and_encoding_ns: int
    compression_and_immutable_write_ns: int
    artifact_parse_and_verification_ns: int
    included_in_controller_latency: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class V8ActionEvidenceWriteResult:
    identity: V8ActionEvidenceArtifactIdentity
    overhead: V8EvidenceOverheadMetadata


@dataclass(frozen=True, slots=True)
class V8ActionEvidenceReadResult:
    identity: V8ActionEvidenceArtifactIdentity
    records: tuple[V8ActionEvidenceRecord, ...]
    overhead: V8EvidenceOverheadMetadata


def _validate_record_sequence(
    record: V8ActionEvidenceRecord,
    previous: V8ActionEvidenceRecord | None,
) -> None:
    if record.execution_order not in (0, 1):
        raise V8ActionEvidenceError("execution_order must be 0 or 1")
    if record.arm not in V8_ACTION_EVIDENCE_ARMS:
        raise V8ActionEvidenceError("record arm is invalid")
    if record.published_vy_mps != 0.0:
        raise V8ActionEvidenceError("published BARN lateral velocity must be zero")
    if record.published_stop and (
        record.published_vx_mps != 0.0 or record.published_yaw_rate_rps != 0.0
    ):
        raise V8ActionEvidenceError("a published stop must have zero velocity")
    if record.issued_by_policy == record.observation_reused:
        raise V8ActionEvidenceError(
            "records must be either a fresh policy action or a reused stop latch"
        )

    if previous is None:
        if record.observation_reused:
            raise V8ActionEvidenceError("the first evidence record cannot reuse an observation")
        return

    if record.step_index <= previous.step_index:
        raise V8ActionEvidenceError("evidence steps must be unique and strictly increasing")
    for name in ("execution_order", "arm", "world_id", "trial_id", "seed"):
        if getattr(record, name) != getattr(previous, name):
            raise V8ActionEvidenceError(f"episode identity changed within artifact: {name}")
    if previous.observation_reused and not record.observation_reused:
        raise V8ActionEvidenceError("a stop-latched episode cannot resume policy observations")
    if record.observation_reused:
        if not previous.published_stop:
            raise V8ActionEvidenceError("observation reuse requires a prior published stop")
        if not record.published_stop or record.issued_by_policy:
            raise V8ActionEvidenceError("observation reuse is reserved for stop-latched records")
        if record.published_vx_mps != 0.0 or record.published_yaw_rate_rps != 0.0:
            raise V8ActionEvidenceError("a stop-latched record must publish zero action")
        if record.normalized_scan_float64_le != previous.normalized_scan_float64_le:
            raise V8ActionEvidenceError("a reused observation must repeat the exact prior scan")
        if struct.pack(
            "<dd", record.angle_min_rad, record.angle_increment_rad
        ) != struct.pack("<dd", previous.angle_min_rad, previous.angle_increment_rad):
            raise V8ActionEvidenceError(
                "a reused observation must repeat the exact prior scan geometry"
            )


class V8ActionEvidenceBuilder:
    """Build and exclusively install one arm/world/trial evidence artifact."""

    def __init__(self) -> None:
        self._records: list[V8ActionEvidenceRecord] = []
        self._frames: list[bytes] = []
        self._certificate_ns = 0
        self._encoding_ns = 0
        self._written = False

    @property
    def records(self) -> tuple[V8ActionEvidenceRecord, ...]:
        return tuple(self._records)

    def append(
        self,
        *,
        step_index: int,
        execution_order: int,
        arm: str,
        world_id: int,
        trial_id: int,
        seed: int,
        issued_by_policy: bool,
        observation_reused: bool,
        normalized_scan_m: Sequence[float],
        angle_min_rad: float,
        angle_increment_rad: float,
        published_vx_mps: float,
        published_vy_mps: float,
        published_yaw_rate_rps: float,
        published_stop: bool,
        note: str,
    ) -> V8ActionEvidenceRecord:
        if self._written:
            raise RuntimeError("cannot append after evidence has been written")
        if len(self._records) >= _MAX_RECORDS:
            raise V8ActionEvidenceError("evidence artifact exceeds the record-count limit")
        started = time.perf_counter_ns()
        step = _uint64(step_index, "step_index")
        order = _uint64(execution_order, "execution_order")
        if order not in (0, 1):
            raise ValueError("execution_order must be 0 or 1")
        world = _uint64(world_id, "world_id")
        trial = _uint64(trial_id, "trial_id")
        episode_seed = _uint64(seed, "seed")
        arm_encoded = _arm_bytes(arm)
        issued = _boolean(issued_by_policy, "issued_by_policy")
        reused = _boolean(observation_reused, "observation_reused")
        stopped = _boolean(published_stop, "published_stop")
        vy = _finite_number(published_vy_mps, "published_vy_mps")
        if vy != 0.0:
            raise ValueError("published BARN lateral velocity must be zero")
        scan_values = tuple(normalized_scan_m)

        certificate_started = time.perf_counter_ns()
        certificate = certify_v8_published_barn_action(
            published_vx_mps,
            published_yaw_rate_rps,
            scan_values,
            angle_min_rad=angle_min_rad,
            angle_increment_rad=angle_increment_rad,
            control_period_s=FROZEN_V8_BARN_EVALUATOR_PROFILE.control_period_s,
        )
        certificate_elapsed = time.perf_counter_ns() - certificate_started
        self._certificate_ns += certificate_elapsed

        vx = certificate.published_vx_mps
        yaw_rate = certificate.published_yaw_rate_rps
        if stopped and (vx != 0.0 or yaw_rate != 0.0):
            raise ValueError("a published stop must have zero velocity")
        try:
            scan_bytes = _SCAN_STRUCT.pack(*(float(value) for value in scan_values))
        except (TypeError, ValueError, struct.error) as exc:  # pragma: no cover - certifier owns it.
            raise V8ActionEvidenceError("normalized scan cannot be encoded as float64") from exc
        note_digest = _note_digest(note)
        certificate_bytes = _canonical_certificate(certificate)
        if len(certificate_bytes) > _MAX_CERTIFICATE_BYTES:
            raise V8ActionEvidenceError("certificate exceeds the evidence format limit")

        prefix = _RECORD_PREFIX.pack(
            step,
            order,
            world,
            trial,
            episode_seed,
            int(issued),
            int(reused),
            int(stopped),
            0,
            certificate.angle_min_rad,
            certificate.angle_increment_rad,
            vx,
            0.0,
            yaw_rate,
            len(arm_encoded),
            note_digest,
            len(certificate_bytes),
        )
        payload = prefix + arm_encoded + scan_bytes + certificate_bytes
        if len(payload) > _MAX_RECORD_BYTES:
            raise V8ActionEvidenceError("record exceeds the evidence format limit")
        previous_digest = (
            bytes.fromhex(self._records[-1].record_sha256)
            if self._records
            else _genesis_digest()
        )
        record_digest = _record_digest(previous_digest, payload)
        record = V8ActionEvidenceRecord(
            step_index=step,
            execution_order=order,
            arm=arm,
            world_id=world,
            trial_id=trial,
            seed=episode_seed,
            issued_by_policy=issued,
            observation_reused=reused,
            angle_min_rad=certificate.angle_min_rad,
            angle_increment_rad=certificate.angle_increment_rad,
            normalized_scan_float64_le=scan_bytes,
            published_vx_mps=vx,
            published_vy_mps=0.0,
            published_yaw_rate_rps=yaw_rate,
            published_stop=stopped,
            note_sha256=note_digest.hex(),
            certificate=certificate,
            previous_record_sha256=previous_digest.hex(),
            record_sha256=record_digest.hex(),
        )
        previous_record = self._records[-1] if self._records else None
        _validate_record_sequence(record, previous_record)
        frame = _FRAME_HEADER.pack(
            _FRAME_MAGIC,
            len(payload),
            previous_digest,
            record_digest,
        ) + payload
        self._records.append(record)
        self._frames.append(frame)
        self._encoding_ns += time.perf_counter_ns() - started - certificate_elapsed
        return record

    def _uncompressed_payload(self) -> tuple[bytes, bytes]:
        if not self._records:
            raise V8ActionEvidenceError("refusing to write an empty evidence artifact")
        record_count = len(self._records)
        root_digest = bytes.fromhex(self._records[-1].record_sha256)
        stream = bytearray(
            _STREAM_HEADER.pack(
                _STREAM_MAGIC,
                V8_ACTION_EVIDENCE_VERSION,
                _profile_digest(),
                record_count,
            )
        )
        for frame in self._frames:
            stream.extend(frame)
        stream.extend(_TRAILER.pack(_TRAILER_MAGIC, record_count, root_digest))
        return bytes(stream), root_digest

    def write_exclusive(self, path: str | Path) -> V8ActionEvidenceWriteResult:
        """Atomically install immutable bytes and return content/root metadata."""

        if self._written:
            raise RuntimeError("evidence builder has already written an artifact")
        started = time.perf_counter_ns()
        uncompressed, root_digest = self._uncompressed_payload()
        if len(uncompressed) > _MAX_UNCOMPRESSED_BYTES:
            raise V8ActionEvidenceError("evidence artifact exceeds the uncompressed size limit")
        compressed = _fixed_compress(uncompressed)
        record_count = len(self._records)
        uncompressed_digest = _sha256_bytes(uncompressed)
        compressed_digest = _sha256_bytes(compressed)
        header = _FILE_HEADER.pack(
            _FILE_MAGIC,
            V8_ACTION_EVIDENCE_VERSION,
            _COMPRESSION_ID_ZLIB,
            _ZLIB_LEVEL,
            _ZLIB_WBITS,
            _ZLIB_MEM_LEVEL,
            _ZLIB_STRATEGY,
            _zlib_version_field(),
            record_count,
            len(uncompressed),
            len(compressed),
            root_digest,
            uncompressed_digest,
            compressed_digest,
            _profile_digest(),
        )
        artifact = header + compressed
        if len(artifact) > _MAX_ARTIFACT_BYTES:
            raise V8ActionEvidenceError("evidence artifact exceeds the file size limit")

        requested = Path(path).expanduser()
        requested.parent.mkdir(parents=True, exist_ok=True)
        parent = requested.parent.resolve()
        target = parent / requested.name
        temporary = parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(artifact)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), 0o444)
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise FileExistsError(
                    f"refusing to replace immutable v8 action evidence: {target}"
                ) from exc
            _fsync_directory(parent)
        finally:
            temporary.unlink(missing_ok=True)

        self._written = True
        finished = time.perf_counter_ns()
        identity = _artifact_identity(
            path=target,
            artifact=artifact,
            compressed=compressed,
            uncompressed=uncompressed,
            root_digest=root_digest,
            records=self.records,
            producing_zlib_version=zlib.ZLIB_RUNTIME_VERSION,
        )
        return V8ActionEvidenceWriteResult(
            identity=identity,
            overhead=V8EvidenceOverheadMetadata(
                operation="write",
                certificate_recomputation_ns=self._certificate_ns,
                record_validation_and_encoding_ns=max(0, self._encoding_ns),
                compression_and_immutable_write_ns=finished - started,
                artifact_parse_and_verification_ns=0,
                included_in_controller_latency=False,
            ),
        )


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - platform/filesystem dependent.
        return
    try:
        os.fsync(descriptor)
    except OSError:  # pragma: no cover - some filesystems reject directory fsync.
        pass
    finally:
        os.close(descriptor)


def _artifact_identity(
    *,
    path: Path,
    artifact: bytes,
    compressed: bytes,
    uncompressed: bytes,
    root_digest: bytes,
    records: tuple[V8ActionEvidenceRecord, ...],
    producing_zlib_version: str,
) -> V8ActionEvidenceArtifactIdentity:
    first = records[0]
    return V8ActionEvidenceArtifactIdentity(
        format_id=V8_ACTION_EVIDENCE_FORMAT_ID,
        format_version=V8_ACTION_EVIDENCE_VERSION,
        path=str(path.resolve()),
        artifact_sha256=_sha256_hex(artifact),
        artifact_size_bytes=len(artifact),
        compressed_payload_sha256=_sha256_hex(compressed),
        compressed_payload_size_bytes=len(compressed),
        uncompressed_payload_sha256=_sha256_hex(uncompressed),
        uncompressed_payload_size_bytes=len(uncompressed),
        record_count=len(records),
        root_record_sha256=root_digest.hex(),
        profile_id=FROZEN_V8_BARN_EVALUATOR_PROFILE.profile_id,
        profile_sha256=FROZEN_V8_BARN_EVALUATOR_PROFILE.identity_sha256,
        arm=first.arm,
        execution_order=first.execution_order,
        world_id=first.world_id,
        trial_id=first.trial_id,
        seed=first.seed,
        compression={
            "algorithm": "zlib-deflate",
            "level": _ZLIB_LEVEL,
            "wbits": _ZLIB_WBITS,
            "mem_level": _ZLIB_MEM_LEVEL,
            "strategy": "Z_FIXED",
            "strategy_value": _ZLIB_STRATEGY,
            "producing_zlib_runtime_version": producing_zlib_version,
        },
    )


def _unpack_bool(value: int, name: str) -> bool:
    if value not in (0, 1):
        raise V8ActionEvidenceError(f"record {name} flag is malformed")
    return bool(value)


def _decode_record_payload(
    payload: bytes,
    *,
    previous_digest: bytes,
    record_digest: bytes,
) -> tuple[V8ActionEvidenceRecord, int]:
    if len(payload) < _RECORD_PREFIX.size:
        raise V8ActionEvidenceError("record payload is truncated")
    (
        step,
        execution_order,
        world_id,
        trial_id,
        seed,
        issued_raw,
        reused_raw,
        stopped_raw,
        reserved,
        angle_min,
        angle_increment,
        vx,
        vy,
        yaw_rate,
        arm_length,
        note_digest,
        certificate_length,
    ) = _RECORD_PREFIX.unpack_from(payload)
    if reserved != 0:
        raise V8ActionEvidenceError("record reserved flags are nonzero")
    if not 0 < arm_length <= _MAX_ARM_BYTES:
        raise V8ActionEvidenceError("record arm length is invalid")
    if not 0 < certificate_length <= _MAX_CERTIFICATE_BYTES:
        raise V8ActionEvidenceError("record certificate length is invalid")
    expected_size = _RECORD_PREFIX.size + arm_length + _SCAN_SIZE_BYTES + certificate_length
    if len(payload) != expected_size:
        raise V8ActionEvidenceError("record payload length does not match its fields")

    offset = _RECORD_PREFIX.size
    arm_payload = payload[offset : offset + arm_length]
    offset += arm_length
    try:
        arm = arm_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise V8ActionEvidenceError("record arm is not valid UTF-8") from exc
    _arm_bytes(arm)
    scan_bytes = payload[offset : offset + _SCAN_SIZE_BYTES]
    offset += _SCAN_SIZE_BYTES
    certificate_bytes = payload[offset : offset + certificate_length]
    try:
        stored_certificate = json.loads(certificate_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V8ActionEvidenceError("record certificate is not valid JSON") from exc
    if not isinstance(stored_certificate, Mapping):
        raise V8ActionEvidenceError("record certificate must be a JSON object")

    issued = _unpack_bool(issued_raw, "issued_by_policy")
    reused = _unpack_bool(reused_raw, "observation_reused")
    stopped = _unpack_bool(stopped_raw, "published_stop")
    if execution_order not in (0, 1):
        raise V8ActionEvidenceError("execution_order must be 0 or 1")
    if not math.isfinite(vy) or vy != 0.0:
        raise V8ActionEvidenceError("published BARN lateral velocity must be zero")
    scan_values = _SCAN_STRUCT.unpack(scan_bytes)
    certificate_started = time.perf_counter_ns()
    try:
        certificate = certify_v8_published_barn_action(
            vx,
            yaw_rate,
            scan_values,
            angle_min_rad=angle_min,
            angle_increment_rad=angle_increment,
            control_period_s=FROZEN_V8_BARN_EVALUATOR_PROFILE.control_period_s,
        )
    except (TypeError, ValueError) as exc:
        raise V8ActionEvidenceError(
            "record action, scan, geometry, or profile contract is invalid"
        ) from exc
    certificate_elapsed = time.perf_counter_ns() - certificate_started
    if certificate_bytes != _canonical_certificate(certificate):
        raise V8ActionEvidenceError(
            "stored certificate does not match independent evaluator recomputation"
        )

    record = V8ActionEvidenceRecord(
        step_index=step,
        execution_order=execution_order,
        arm=arm,
        world_id=world_id,
        trial_id=trial_id,
        seed=seed,
        issued_by_policy=issued,
        observation_reused=reused,
        angle_min_rad=angle_min,
        angle_increment_rad=angle_increment,
        normalized_scan_float64_le=scan_bytes,
        published_vx_mps=vx,
        published_vy_mps=vy,
        published_yaw_rate_rps=yaw_rate,
        published_stop=stopped,
        note_sha256=note_digest.hex(),
        certificate=certificate,
        previous_record_sha256=previous_digest.hex(),
        record_sha256=record_digest.hex(),
    )
    return record, certificate_elapsed


def read_v8_action_evidence(
    path: str | Path,
    *,
    expected_artifact_sha256: str | None = None,
) -> V8ActionEvidenceReadResult:
    """Fully decompress, parse, chain-check, and recertify an evidence file."""

    started = time.perf_counter_ns()
    source = Path(path).expanduser()
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError(f"v8 action evidence is missing or unsafe: {source}")
    source = source.resolve()
    if source.stat().st_size > _MAX_ARTIFACT_BYTES:
        raise V8ActionEvidenceError("evidence artifact exceeds the file size limit")
    artifact = source.read_bytes()
    artifact_sha256 = _sha256_hex(artifact)
    if expected_artifact_sha256 is not None:
        if _SHA256.fullmatch(expected_artifact_sha256) is None:
            raise ValueError("expected_artifact_sha256 must be a lowercase SHA-256 digest")
        if artifact_sha256 != expected_artifact_sha256:
            raise V8ActionEvidenceError("evidence artifact SHA-256 does not match expectation")
    if len(artifact) < _FILE_HEADER.size:
        raise V8ActionEvidenceError("evidence artifact header is truncated")
    (
        magic,
        version,
        compression_id,
        level,
        wbits,
        mem_level,
        strategy,
        zlib_version_raw,
        declared_count,
        declared_uncompressed_size,
        declared_compressed_size,
        declared_root,
        declared_uncompressed_digest,
        declared_compressed_digest,
        declared_profile_digest,
    ) = _FILE_HEADER.unpack_from(artifact)
    if magic != _FILE_MAGIC:
        raise V8ActionEvidenceError("bad v8 action evidence magic")
    if version != V8_ACTION_EVIDENCE_VERSION:
        raise V8ActionEvidenceError("unsupported v8 action evidence version")
    if (
        compression_id,
        level,
        wbits,
        mem_level,
        strategy,
    ) != (
        _COMPRESSION_ID_ZLIB,
        _ZLIB_LEVEL,
        _ZLIB_WBITS,
        _ZLIB_MEM_LEVEL,
        _ZLIB_STRATEGY,
    ):
        raise V8ActionEvidenceError("v8 action evidence compression profile changed")
    try:
        producing_zlib_version = zlib_version_raw.rstrip(b"\x00").decode("ascii")
    except UnicodeDecodeError as exc:
        raise V8ActionEvidenceError("producing zlib version metadata is malformed") from exc
    if not producing_zlib_version:
        raise V8ActionEvidenceError("producing zlib version metadata is empty")
    if not 1 <= declared_count <= _MAX_RECORDS:
        raise V8ActionEvidenceError("declared evidence record count is invalid")
    if declared_profile_digest != _profile_digest():
        raise V8ActionEvidenceError("evidence evaluator profile identity mismatch")
    if declared_compressed_size > _MAX_ARTIFACT_BYTES:
        raise V8ActionEvidenceError("declared compressed evidence size is invalid")
    expected_artifact_size = _FILE_HEADER.size + declared_compressed_size
    if len(artifact) < expected_artifact_size:
        raise V8ActionEvidenceError("evidence artifact is truncated")
    if len(artifact) > expected_artifact_size:
        raise V8ActionEvidenceError("evidence artifact has trailing bytes")
    compressed = artifact[_FILE_HEADER.size :]
    if _sha256_bytes(compressed) != declared_compressed_digest:
        raise V8ActionEvidenceError("compressed evidence SHA-256 mismatch")
    uncompressed = _fixed_decompress(
        compressed,
        expected_size=declared_uncompressed_size,
    )
    if _sha256_bytes(uncompressed) != declared_uncompressed_digest:
        raise V8ActionEvidenceError("uncompressed evidence SHA-256 mismatch")

    if len(uncompressed) < _STREAM_HEADER.size + _TRAILER.size:
        raise V8ActionEvidenceError("uncompressed evidence stream is truncated")
    stream_magic, stream_version, stream_profile_digest, stream_count = (
        _STREAM_HEADER.unpack_from(uncompressed)
    )
    if stream_magic != _STREAM_MAGIC or stream_version != V8_ACTION_EVIDENCE_VERSION:
        raise V8ActionEvidenceError("uncompressed evidence stream identity mismatch")
    if stream_profile_digest != declared_profile_digest:
        raise V8ActionEvidenceError("stream and file profile identities differ")
    if stream_count != declared_count:
        raise V8ActionEvidenceError("stream and file record counts differ")

    offset = _STREAM_HEADER.size
    expected_previous = _genesis_digest()
    records: list[V8ActionEvidenceRecord] = []
    certificate_ns = 0
    for _record_number in range(declared_count):
        if offset + _FRAME_HEADER.size > len(uncompressed):
            raise V8ActionEvidenceError("evidence record frame is truncated")
        frame_magic, payload_length, previous_digest, record_digest = (
            _FRAME_HEADER.unpack_from(uncompressed, offset)
        )
        offset += _FRAME_HEADER.size
        if frame_magic != _FRAME_MAGIC:
            raise V8ActionEvidenceError("evidence record frame magic is invalid")
        if not _RECORD_PREFIX.size <= payload_length <= _MAX_RECORD_BYTES:
            raise V8ActionEvidenceError("evidence record payload length is invalid")
        if offset + payload_length > len(uncompressed):
            raise V8ActionEvidenceError("evidence record payload is truncated")
        payload = uncompressed[offset : offset + payload_length]
        offset += payload_length
        if previous_digest != expected_previous:
            raise V8ActionEvidenceError("evidence record hash chain predecessor mismatch")
        if _record_digest(previous_digest, payload) != record_digest:
            raise V8ActionEvidenceError("evidence record hash chain digest mismatch")
        record, record_certificate_ns = _decode_record_payload(
            payload,
            previous_digest=previous_digest,
            record_digest=record_digest,
        )
        certificate_ns += record_certificate_ns
        previous_record = records[-1] if records else None
        _validate_record_sequence(record, previous_record)
        records.append(record)
        expected_previous = record_digest

    if offset + _TRAILER.size > len(uncompressed):
        raise V8ActionEvidenceError("evidence stream trailer is truncated")
    trailer_magic, trailer_count, trailer_root = _TRAILER.unpack_from(uncompressed, offset)
    offset += _TRAILER.size
    if trailer_magic != _TRAILER_MAGIC:
        raise V8ActionEvidenceError("evidence stream trailer magic is invalid")
    if offset != len(uncompressed):
        raise V8ActionEvidenceError("uncompressed evidence stream has trailing bytes")
    if trailer_count != declared_count:
        raise V8ActionEvidenceError("evidence trailer record count mismatch")
    if trailer_root != expected_previous or declared_root != expected_previous:
        raise V8ActionEvidenceError("evidence record hash-chain root mismatch")

    record_tuple = tuple(records)
    identity = _artifact_identity(
        path=source,
        artifact=artifact,
        compressed=compressed,
        uncompressed=uncompressed,
        root_digest=expected_previous,
        records=record_tuple,
        producing_zlib_version=producing_zlib_version,
    )
    elapsed = time.perf_counter_ns() - started
    return V8ActionEvidenceReadResult(
        identity=identity,
        records=record_tuple,
        overhead=V8EvidenceOverheadMetadata(
            operation="read_verify",
            certificate_recomputation_ns=certificate_ns,
            record_validation_and_encoding_ns=0,
            compression_and_immutable_write_ns=0,
            artifact_parse_and_verification_ns=max(0, elapsed - certificate_ns),
            included_in_controller_latency=False,
        ),
    )


__all__ = [
    "V8_ACTION_EVIDENCE_ARMS",
    "V8_ACTION_EVIDENCE_FORMAT_ID",
    "V8_ACTION_EVIDENCE_VERSION",
    "V8ActionEvidenceArtifactIdentity",
    "V8ActionEvidenceBuilder",
    "V8ActionEvidenceError",
    "V8ActionEvidenceReadResult",
    "V8ActionEvidenceRecord",
    "V8ActionEvidenceWriteResult",
    "V8EvidenceOverheadMetadata",
    "read_v8_action_evidence",
]
