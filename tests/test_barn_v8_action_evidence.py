from __future__ import annotations

import hashlib
import math
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.external import barn_v8_action_evidence as evidence_module
from evals.external.barn_v8_action_certifier import (
    FROZEN_V8_BARN_EVALUATOR_PROFILE,
)
from evals.external.barn_v8_action_evidence import (
    V8_ACTION_EVIDENCE_FORMAT_ID,
    V8ActionEvidenceBuilder,
    V8ActionEvidenceError,
    read_v8_action_evidence,
)

RAY_COUNT = 720
ANGLE_MIN_RAD = -math.pi
ANGLE_INCREMENT_RAD = 2.0 * math.pi / (RAY_COUNT - 1)
_FLAGS_OFFSET = 5 * 8
_VX_OFFSET = 5 * 8 + 4 + 2 * 8


def _scan(
    hits: dict[int, float] | None = None,
    *,
    fill: float = math.inf,
) -> tuple[float, ...]:
    values = [fill] * RAY_COUNT
    for index, distance in (hits or {}).items():
        values[index] = distance
    return tuple(values)


def _append(
    builder: V8ActionEvidenceBuilder,
    *,
    step: int,
    scan: tuple[float, ...] | None = None,
    issued_by_policy: bool = True,
    observation_reused: bool = False,
    vx: float = 0.1,
    yaw: float = 0.0,
    stop: bool = False,
    note: str = "policy-note",
    angle_min: float = ANGLE_MIN_RAD,
    angle_increment: float = ANGLE_INCREMENT_RAD,
    execution_order: int = 1,
    arm: str = "candidate",
    world_id: int = 4000,
    trial_id: int = 3,
    seed: int = 0xFEDCBA9876543210,
    observation_sha256: str = "a" * 64,
):
    return builder.append(
        step_index=step,
        execution_order=execution_order,
        arm=arm,
        world_id=world_id,
        trial_id=trial_id,
        seed=seed,
        issued_by_policy=issued_by_policy,
        observation_reused=observation_reused,
        normalized_scan_m=scan or _scan(),
        angle_min_rad=angle_min,
        angle_increment_rad=angle_increment,
        published_vx_mps=vx,
        published_vy_mps=0.0,
        published_yaw_rate_rps=yaw,
        published_stop=stop,
        note=note,
        policy_observation_sha256=observation_sha256,
    )


def _write_sample(path: Path, *, include_latch: bool = True):
    builder = V8ActionEvidenceBuilder()
    _append(builder, step=0, note="moving")
    if include_latch:
        _append(builder, step=4, vx=0.0, stop=True, note="policy-stop")
        _append(
            builder,
            step=5,
            issued_by_policy=False,
            observation_reused=True,
            vx=0.0,
            stop=True,
            note="policy-stop-latched",
        )
    return builder.write_exclusive(path)


def _uncompressed(raw_artifact: bytes) -> bytes:
    fields = evidence_module._FILE_HEADER.unpack_from(raw_artifact)
    declared_size = fields[9]
    compressed_size = fields[10]
    compressed = raw_artifact[
        evidence_module._FILE_HEADER.size : evidence_module._FILE_HEADER.size + compressed_size
    ]
    return evidence_module._fixed_decompress(compressed, expected_size=declared_size)


def _payloads(raw_artifact: bytes) -> list[bytes]:
    stream = _uncompressed(raw_artifact)
    _magic, _version, _profile, count = evidence_module._STREAM_HEADER.unpack_from(stream)
    offset = evidence_module._STREAM_HEADER.size
    result: list[bytes] = []
    for _ in range(count):
        _frame_magic, payload_length, _previous, _record = (
            evidence_module._FRAME_HEADER.unpack_from(stream, offset)
        )
        offset += evidence_module._FRAME_HEADER.size
        result.append(stream[offset : offset + payload_length])
        offset += payload_length
    return result


def _rebuild_from_payloads(payloads: list[bytes]) -> bytes:
    count = len(payloads)
    profile_digest = bytes.fromhex(FROZEN_V8_BARN_EVALUATOR_PROFILE.identity_sha256)
    stream = bytearray(
        evidence_module._STREAM_HEADER.pack(
            evidence_module._STREAM_MAGIC,
            evidence_module.V8_ACTION_EVIDENCE_VERSION,
            profile_digest,
            count,
        )
    )
    previous = evidence_module._genesis_digest()
    for payload in payloads:
        record_digest = evidence_module._record_digest(previous, payload)
        stream.extend(
            evidence_module._FRAME_HEADER.pack(
                evidence_module._FRAME_MAGIC,
                len(payload),
                previous,
                record_digest,
            )
        )
        stream.extend(payload)
        previous = record_digest
    stream.extend(evidence_module._TRAILER.pack(evidence_module._TRAILER_MAGIC, count, previous))
    uncompressed = bytes(stream)
    compressed = evidence_module._fixed_compress(uncompressed)
    header = evidence_module._FILE_HEADER.pack(
        evidence_module._FILE_MAGIC,
        evidence_module.V8_ACTION_EVIDENCE_VERSION,
        evidence_module._COMPRESSION_ID_ZLIB,
        evidence_module._ZLIB_LEVEL,
        evidence_module._ZLIB_WBITS,
        evidence_module._ZLIB_MEM_LEVEL,
        evidence_module._ZLIB_STRATEGY,
        evidence_module._zlib_version_field(),
        count,
        len(uncompressed),
        len(compressed),
        previous,
        hashlib.sha256(uncompressed).digest(),
        hashlib.sha256(compressed).digest(),
        profile_digest,
    )
    return header + compressed


def _replace_header_field(raw_artifact: bytes, index: int, value: object) -> bytes:
    fields = list(evidence_module._FILE_HEADER.unpack_from(raw_artifact))
    fields[index] = value
    return (
        evidence_module._FILE_HEADER.pack(*fields)
        + raw_artifact[evidence_module._FILE_HEADER.size :]
    )


def _write_tampered(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    return path


def test_round_trip_preserves_exact_float64_scan_action_and_episode_identity(
    tmp_path: Path,
) -> None:
    special_nan_bytes = bytes.fromhex("010000000000f87f")
    special_nan = struct.unpack("<d", special_nan_bytes)[0]
    scan = _scan({0: special_nan, 1: math.inf, 2: 1.25})
    builder = V8ActionEvidenceBuilder()
    written_record = _append(
        builder,
        step=7,
        scan=scan,
        vx=-0.2,
        yaw=-0.4,
        note="secret-policy-note-not-stored",
        execution_order=0,
        arm="reference",
        world_id=4030,
        trial_id=9,
        seed=(1 << 64) - 1,
    )
    target = tmp_path / "actions.v8e"

    write_result = builder.write_exclusive(target)
    read_result = read_v8_action_evidence(
        target,
        expected_artifact_sha256=write_result.identity.artifact_sha256,
    )
    record = read_result.records[0]

    assert record == written_record
    assert record.normalized_scan_float64_le[:8] == special_nan_bytes
    assert record.normalized_scan_float64_le[8:16] == struct.pack("<d", math.inf)
    assert record.normalized_scan_float64_le[16:24] == struct.pack("<d", 1.25)
    assert record.normalized_scan_float64_le != struct.pack("<720d", *([math.inf] * 720))
    assert record.published_vx_mps == -0.2
    assert record.published_vy_mps == 0.0
    assert record.published_yaw_rate_rps == -0.4
    assert record.published_stop is False
    assert record.step_index == 7
    assert record.execution_order == 0
    assert record.arm == "reference"
    assert record.world_id == 4030
    assert record.trial_id == 9
    assert record.seed == (1 << 64) - 1
    assert record.certificate.profile_sha256 == write_result.identity.profile_sha256
    assert record.certificate.examined_ray_count == 720
    assert record.note_sha256 == hashlib.sha256(b"secret-policy-note-not-stored").hexdigest()
    assert record.policy_observation_sha256 == "a" * 64
    assert b"secret-policy-note-not-stored" not in _uncompressed(target.read_bytes())


def test_artifact_is_deterministic_and_returns_hash_size_count_and_root_metadata(
    tmp_path: Path,
) -> None:
    first = _write_sample(tmp_path / "first.v8e")
    second = _write_sample(tmp_path / "second.v8e")

    first_bytes = (tmp_path / "first.v8e").read_bytes()
    second_bytes = (tmp_path / "second.v8e").read_bytes()
    assert first_bytes == second_bytes
    assert first.identity.format_id == V8_ACTION_EVIDENCE_FORMAT_ID
    assert first.identity.artifact_sha256 == hashlib.sha256(first_bytes).hexdigest()
    assert first.identity.artifact_sha256 == second.identity.artifact_sha256
    assert first.identity.artifact_size_bytes == len(first_bytes)
    assert first.identity.record_count == 3
    assert (
        first.identity.root_record_sha256
        == read_v8_action_evidence(tmp_path / "first.v8e").records[-1].record_sha256
    )
    assert first.identity.profile_sha256 == (FROZEN_V8_BARN_EVALUATOR_PROFILE.identity_sha256)
    assert first.identity.arm == "candidate"
    assert first.identity.execution_order == 1
    assert first.identity.world_id == 4000
    assert first.identity.trial_id == 3
    assert first.identity.seed == 0xFEDCBA9876543210
    assert first.identity.compression == {
        "algorithm": "zlib-deflate",
        "level": 9,
        "wbits": 15,
        "mem_level": 9,
        "strategy": "Z_FIXED",
        "strategy_value": evidence_module.zlib.Z_FIXED,
        "producing_zlib_runtime_version": evidence_module.zlib.ZLIB_RUNTIME_VERSION,
    }


def test_artifact_write_is_exclusive_read_only_and_builder_is_single_use(
    tmp_path: Path,
) -> None:
    target = tmp_path / "immutable.v8e"
    builder = V8ActionEvidenceBuilder()
    _append(builder, step=0)
    builder.write_exclusive(target)

    assert target.is_file()
    assert os.stat(target).st_mode & 0o222 == 0
    with pytest.raises(RuntimeError, match="already written"):
        builder.write_exclusive(tmp_path / "other.v8e")
    with pytest.raises(RuntimeError, match="cannot append"):
        _append(builder, step=1)

    competing = V8ActionEvidenceBuilder()
    _append(competing, step=0)
    with pytest.raises(FileExistsError, match="refusing to replace immutable"):
        competing.write_exclusive(target)


def test_forced_temporary_name_collision_preserves_foreign_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "collision.v8e"
    collision_hex = "forced-collision"
    temporary = tmp_path / f".{target.name}.{os.getpid()}.{collision_hex}.tmp"
    foreign = b"foreign-file-owned-by-another-writer\n"
    temporary.write_bytes(foreign)
    monkeypatch.setattr(
        evidence_module.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=collision_hex),
    )
    builder = V8ActionEvidenceBuilder()
    _append(builder, step=0)

    with pytest.raises(FileExistsError):
        builder.write_exclusive(target)

    assert temporary.read_bytes() == foreign
    assert target.exists() is False


def test_evaluator_overhead_is_separate_metadata_not_controller_latency(
    tmp_path: Path,
) -> None:
    write_result = _write_sample(tmp_path / "overhead.v8e")
    read_result = read_v8_action_evidence(tmp_path / "overhead.v8e")

    assert write_result.overhead.operation == "write"
    assert write_result.overhead.certificate_recomputation_ns >= 0
    assert write_result.overhead.record_validation_and_encoding_ns >= 0
    assert write_result.overhead.compression_and_immutable_write_ns >= 0
    assert write_result.overhead.included_in_controller_latency is False
    assert read_result.overhead.operation == "read_verify"
    assert read_result.overhead.certificate_recomputation_ns >= 0
    assert read_result.overhead.artifact_parse_and_verification_ns >= 0
    assert read_result.overhead.included_in_controller_latency is False
    assert "controller_latency" not in write_result.identity.as_dict()


def test_stop_latch_repeats_exact_last_scan_and_zero_action(tmp_path: Path) -> None:
    target = tmp_path / "latch.v8e"
    result = _write_sample(target)

    records = read_v8_action_evidence(target).records
    policy_stop, latch = records[-2:]
    assert policy_stop.issued_by_policy is True
    assert policy_stop.observation_reused is False
    assert policy_stop.published_stop is True
    assert latch.issued_by_policy is False
    assert latch.observation_reused is True
    assert latch.published_stop is True
    assert latch.published_vx_mps == 0.0
    assert latch.published_vy_mps == 0.0
    assert latch.published_yaw_rate_rps == 0.0
    assert latch.normalized_scan_float64_le == policy_stop.normalized_scan_float64_le
    assert latch.policy_observation_sha256 == policy_stop.policy_observation_sha256
    assert result.identity.root_record_sha256 == latch.record_sha256


def test_builder_rejects_reuse_on_first_record() -> None:
    builder = V8ActionEvidenceBuilder()

    with pytest.raises(V8ActionEvidenceError, match="first evidence record"):
        _append(
            builder,
            step=0,
            issued_by_policy=False,
            observation_reused=True,
            vx=0.0,
            stop=True,
        )


def test_builder_rejects_reuse_without_prior_stop() -> None:
    builder = V8ActionEvidenceBuilder()
    _append(builder, step=0)

    with pytest.raises(V8ActionEvidenceError, match="prior published stop"):
        _append(
            builder,
            step=1,
            issued_by_policy=False,
            observation_reused=True,
            vx=0.0,
            stop=True,
        )


def test_builder_rejects_changed_scan_or_geometry_on_reuse() -> None:
    changed_scan = V8ActionEvidenceBuilder()
    _append(changed_scan, step=0, vx=0.0, stop=True)
    with pytest.raises(V8ActionEvidenceError, match="exact prior scan"):
        _append(
            changed_scan,
            step=1,
            scan=_scan({10: 2.0}),
            issued_by_policy=False,
            observation_reused=True,
            vx=0.0,
            stop=True,
        )

    changed_observation = V8ActionEvidenceBuilder()
    _append(changed_observation, step=0, vx=0.0, stop=True)
    with pytest.raises(V8ActionEvidenceError, match="complete prior observation digest"):
        _append(
            changed_observation,
            step=1,
            issued_by_policy=False,
            observation_reused=True,
            vx=0.0,
            stop=True,
            observation_sha256="b" * 64,
        )

    changed_geometry = V8ActionEvidenceBuilder()
    _append(changed_geometry, step=0, vx=0.0, stop=True)
    with pytest.raises(V8ActionEvidenceError, match="exact prior scan geometry"):
        _append(
            changed_geometry,
            step=1,
            issued_by_policy=False,
            observation_reused=True,
            vx=0.0,
            stop=True,
            angle_increment=ANGLE_INCREMENT_RAD + 1e-10,
        )


def test_builder_rejects_policy_resume_after_latch() -> None:
    builder = V8ActionEvidenceBuilder()
    _append(builder, step=0, vx=0.0, stop=True)
    _append(
        builder,
        step=1,
        issued_by_policy=False,
        observation_reused=True,
        vx=0.0,
        stop=True,
    )

    with pytest.raises(V8ActionEvidenceError, match="cannot resume"):
        _append(builder, step=2, vx=0.0, stop=True)


@pytest.mark.parametrize(
    ("kwargs", "error_type", "message"),
    (
        ({"execution_order": 2}, ValueError, "execution_order must be 0 or 1"),
        ({"arm": "treatment"}, ValueError, "arm must be one of"),
        ({"world_id": -1}, ValueError, "unsigned 64-bit"),
        ({"trial_id": True}, TypeError, "must be an integer"),
        ({"seed": 1 << 64}, ValueError, "unsigned 64-bit"),
        ({"stop": True}, ValueError, "published stop must have zero velocity"),
        ({"observation_sha256": "not-a-digest"}, ValueError, "lowercase SHA-256"),
        (
            {"issued_by_policy": False, "observation_reused": False},
            V8ActionEvidenceError,
            "either a fresh policy action",
        ),
    ),
)
def test_builder_rejects_malformed_identity_flags_or_action(
    kwargs: dict[str, object],
    error_type: type[Exception],
    message: str,
) -> None:
    builder = V8ActionEvidenceBuilder()

    with pytest.raises(error_type, match=message):
        _append(builder, step=0, **kwargs)


def test_builder_rejects_duplicate_nonmonotonic_or_changed_episode_identity() -> None:
    duplicate = V8ActionEvidenceBuilder()
    _append(duplicate, step=2)
    with pytest.raises(V8ActionEvidenceError, match="strictly increasing"):
        _append(duplicate, step=2)

    nonmonotonic = V8ActionEvidenceBuilder()
    _append(nonmonotonic, step=2)
    with pytest.raises(V8ActionEvidenceError, match="strictly increasing"):
        _append(nonmonotonic, step=1)

    changed = V8ActionEvidenceBuilder()
    _append(changed, step=0)
    with pytest.raises(V8ActionEvidenceError, match="episode identity changed.*world_id"):
        _append(changed, step=1, world_id=4001)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("magic", "bad v8 action evidence magic"),
        ("version", "unsupported v8 action evidence version"),
        ("truncated", "evidence artifact is truncated"),
        ("trailing", "evidence artifact has trailing bytes"),
        ("count", "stream and file record counts differ"),
        ("size", "decompressed evidence exceeds its declared size"),
        ("profile", "evaluator profile identity mismatch"),
        ("compressed_hash", "compressed evidence SHA-256 mismatch"),
    ),
)
def test_reader_rejects_bad_header_truncation_trailing_count_and_hashes(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    original_path = tmp_path / "original.v8e"
    _write_sample(original_path, include_latch=False)
    raw = original_path.read_bytes()
    if mutation == "magic":
        changed = b"BADMAGIC" + raw[8:]
    elif mutation == "version":
        changed = bytearray(raw)
        struct.pack_into("<H", changed, 8, 1)
        changed = bytes(changed)
    elif mutation == "truncated":
        changed = raw[:-1]
    elif mutation == "trailing":
        changed = raw + b"x"
    elif mutation == "count":
        changed = _replace_header_field(raw, 8, 2)
    elif mutation == "size":
        changed = _replace_header_field(
            raw,
            9,
            evidence_module._FILE_HEADER.unpack_from(raw)[9] - 1,
        )
    elif mutation == "profile":
        changed = _replace_header_field(raw, 14, b"\x01" * 32)
    else:
        compressed_digest = bytearray(evidence_module._FILE_HEADER.unpack_from(raw)[13])
        compressed_digest[0] ^= 1
        changed = _replace_header_field(raw, 13, bytes(compressed_digest))
    tampered = _write_tampered(tmp_path / f"{mutation}.v8e", changed)

    with pytest.raises(V8ActionEvidenceError, match=message):
        read_v8_action_evidence(tampered)


@pytest.mark.parametrize("second_step", (1, 0))
def test_reader_rejects_duplicate_or_nonmonotonic_step_after_integrity_rebuild(
    tmp_path: Path,
    second_step: int,
) -> None:
    builder = V8ActionEvidenceBuilder()
    _append(builder, step=1)
    _append(builder, step=2)
    original = tmp_path / "steps-original.v8e"
    builder.write_exclusive(original)
    payloads = _payloads(original.read_bytes())
    second = bytearray(payloads[1])
    struct.pack_into("<Q", second, 0, second_step)
    payloads[1] = bytes(second)
    tampered = _write_tampered(
        tmp_path / "duplicate-step.v8e",
        _rebuild_from_payloads(payloads),
    )

    with pytest.raises(V8ActionEvidenceError, match="strictly increasing"):
        read_v8_action_evidence(tampered)


def test_reader_rejects_reuse_on_first_record_after_integrity_rebuild(tmp_path: Path) -> None:
    builder = V8ActionEvidenceBuilder()
    _append(builder, step=0, vx=0.0, stop=True)
    original = tmp_path / "reuse-first-original.v8e"
    builder.write_exclusive(original)
    payloads = _payloads(original.read_bytes())
    first = bytearray(payloads[0])
    first[_FLAGS_OFFSET] = 0
    first[_FLAGS_OFFSET + 1] = 1
    payloads[0] = bytes(first)
    tampered = _write_tampered(
        tmp_path / "reuse-first.v8e",
        _rebuild_from_payloads(payloads),
    )

    with pytest.raises(V8ActionEvidenceError, match="first evidence record"):
        read_v8_action_evidence(tampered)


def test_reader_rejects_changed_reused_scan_after_integrity_rebuild(tmp_path: Path) -> None:
    builder = V8ActionEvidenceBuilder()
    _append(builder, step=0, vx=0.0, stop=True)
    _append(builder, step=1, scan=_scan({10: 2.0}), vx=0.0, stop=True)
    original = tmp_path / "changed-reuse-original.v8e"
    builder.write_exclusive(original)
    payloads = _payloads(original.read_bytes())
    second = bytearray(payloads[1])
    second[_FLAGS_OFFSET] = 0
    second[_FLAGS_OFFSET + 1] = 1
    payloads[1] = bytes(second)
    tampered = _write_tampered(
        tmp_path / "changed-reuse.v8e",
        _rebuild_from_payloads(payloads),
    )

    with pytest.raises(V8ActionEvidenceError, match="repeat the exact prior scan"):
        read_v8_action_evidence(tampered)


@pytest.mark.parametrize("field", ("action", "scan", "certificate"))
def test_reader_recomputes_certificate_and_rejects_semantic_tampering(
    tmp_path: Path,
    field: str,
) -> None:
    builder = V8ActionEvidenceBuilder()
    _append(builder, step=0, scan=_scan({10: 2.0}), vx=0.1)
    original = tmp_path / "semantic-original.v8e"
    builder.write_exclusive(original)
    payloads = _payloads(original.read_bytes())
    payload = bytearray(payloads[0])
    prefix = evidence_module._RECORD_PREFIX.unpack_from(payload)
    arm_length = prefix[14]
    certificate_length = prefix[17]
    scan_offset = evidence_module._RECORD_PREFIX.size + arm_length
    certificate_offset = scan_offset + evidence_module._SCAN_SIZE_BYTES
    if field == "action":
        struct.pack_into("<d", payload, _VX_OFFSET, 0.2)
    elif field == "scan":
        struct.pack_into("<d", payload, scan_offset + 10 * 8, 1.5)
    else:
        certificate_payload = bytes(
            payload[certificate_offset : certificate_offset + certificate_length]
        )
        replacement = certificate_payload.replace(
            b"parcel-v8-all-ray-yaw-swept-projected-cap",
            b"tamper-v8-all-ray-yaw-swept-projected-cap",
        )
        assert len(replacement) == len(certificate_payload)
        payload[certificate_offset : certificate_offset + certificate_length] = replacement
    payloads[0] = bytes(payload)
    tampered = _write_tampered(
        tmp_path / f"semantic-{field}.v8e",
        _rebuild_from_payloads(payloads),
    )

    with pytest.raises(
        V8ActionEvidenceError,
        match="stored certificate does not match independent evaluator recomputation",
    ):
        read_v8_action_evidence(tampered)


def test_reader_rejects_hash_chain_damage_even_when_container_hashes_are_rebuilt(
    tmp_path: Path,
) -> None:
    original = tmp_path / "chain-original.v8e"
    _write_sample(original, include_latch=False)
    raw = original.read_bytes()
    stream = bytearray(_uncompressed(raw))
    record_digest_offset = evidence_module._STREAM_HEADER.size + 4 + 4 + 32
    stream[record_digest_offset] ^= 1
    compressed = evidence_module._fixed_compress(bytes(stream))
    fields = list(evidence_module._FILE_HEADER.unpack_from(raw))
    fields[9] = len(stream)
    fields[10] = len(compressed)
    fields[12] = hashlib.sha256(stream).digest()
    fields[13] = hashlib.sha256(compressed).digest()
    changed = evidence_module._FILE_HEADER.pack(*fields) + compressed
    tampered = _write_tampered(tmp_path / "chain-damaged.v8e", changed)

    with pytest.raises(V8ActionEvidenceError, match="hash chain digest mismatch"):
        read_v8_action_evidence(tampered)


def test_reader_rejects_wrong_expected_artifact_digest(tmp_path: Path) -> None:
    target = tmp_path / "expected-hash.v8e"
    _write_sample(target, include_latch=False)

    with pytest.raises(V8ActionEvidenceError, match="does not match expectation"):
        read_v8_action_evidence(target, expected_artifact_sha256="0" * 64)
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        read_v8_action_evidence(target, expected_artifact_sha256="BAD")
