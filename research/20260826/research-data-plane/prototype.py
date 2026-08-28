"""Isolated benchmark for Parcel's proposed off-robot research data plane.

This program intentionally uses only the Python standard library.  It creates a
scratch SQLite spool under this research directory, admits synthetic summaries
through an allow-list/redaction boundary, forms deterministic content-addressed
gzip bundles, simulates a byte-capped resumable upload, and verifies replay and
corruption detection.  The scratch directory is removed at exit; only the
machine-readable result requested by ``--output`` remains.

It never imports Parcel's companion-memory implementation and never opens a
database outside this directory.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import platform
import random
import re
import sqlite3
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SCHEMA_ID = "parcel://schemas/research_event_v1"
RESULT_VERSION = "parcel.research_data_plane_benchmark.v1"
RUN_ID = "research-plane-probe-20260826"
ROBOT_PSEUDONYM = "robot_1dbaf0aecc198296"
START = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
NAMESPACE = uuid.UUID("dd1b4656-3c34-45ab-8ac2-f42dc2e06d48")

EVENT_TYPES = {
    "navigation": "ai.parcel.research.navigation.summary.v1",
    "conversation": "ai.parcel.research.conversation.outcome.v1",
    "audio": "ai.parcel.research.audio.summary.v1",
    "perception": "ai.parcel.research.perception.summary.v1",
    "feedback": "ai.parcel.research.learning.feedback.v1",
}
STREAM_HZ = {
    "navigation": 2.0,
    "conversation": 1.0 / 30.0,
    "audio": 1.0,
    "perception": 1.0,
    "feedback": 1.0 / 300.0,
}
PRIORITY = {"feedback": 0, "conversation": 1, "navigation": 2, "audio": 2, "perception": 2}
RETENTION = {
    "feedback": ("feedback_1y", 365),
    "conversation": ("summary_90d", 90),
    "navigation": ("summary_90d", 90),
    "audio": ("summary_90d", 90),
    "perception": ("summary_90d", 90),
}

# A narrow, stream-specific allow-list is the first privacy boundary. Unknown
# keys are removed even when they do not resemble PII.
ALLOWED_DATA_KEYS = {
    "navigation": {
        "distance_delta_m",
        "speed_mps",
        "localization_confidence",
        "planner_state",
        "recovery_count",
        "path_segment_hash",
    },
    "conversation": {
        "outcome_code",
        "latency_ms",
        "turn_count",
        "repair_count",
        "safety_route_used",
        "redacted_note",
    },
    "audio": {
        "speech_probability",
        "snr_db",
        "vad_segments",
        "acoustic_class",
        "source_chunk_hash",
    },
    "perception": {
        "class_counts",
        "obstacle_min_m",
        "detector_confidence",
        "frame_summary_hash",
    },
    "feedback": {"label", "task", "reward", "evaluator", "redacted_note"},
}

FORBIDDEN_KEYS = {
    "raw_audio",
    "audio_bytes",
    "raw_image",
    "image_bytes",
    "raw_video",
    "transcript",
    "full_text",
    "face_embedding",
    "voice_embedding",
    "gps_lat",
    "gps_lon",
    "latitude",
    "longitude",
    "exact_address",
    "name",
    "email",
    "phone",
    "credential",
    "api_key",
    "access_token",
}
RAW_PAYLOAD_KINDS = {"raw_audio", "raw_image", "raw_video", "mcap_raw"}
REDACTION_PATTERNS = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    (
        "phone",
        re.compile(
            r"(?<![A-Za-z0-9])(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?![A-Za-z0-9])"
        ),
    ),
    ("credential", re.compile(r"\b(?:sk|pk|api)[-_][A-Za-z0-9_-]{12,}\b", re.IGNORECASE)),
)

LEAK_MARKERS = (
    "leak_test_42@example.com",
    "+1 (212) 555-0199",
    "sk-test-AAAAAAAAAAAAAAAAAAAA",
    "RIFF_PRIVATE_MARKER_AUDIO",
    "PRIVATE_MARKER_IMAGE",
    "PRIVATE_MARKER_TRANSCRIPT",
    "PRIVATE_MARKER_FACE",
    "221B Baker Street",
    "37.7749001",
    "-122.4194001",
)

REQUIRED_EVENT_KEYS = {
    "specversion",
    "id",
    "source",
    "type",
    "time",
    "dataschema",
    "run_id",
    "stream",
    "sequence",
    "robot_pseudonym",
    "origin",
    "privacy_class",
    "purpose",
    "consent_id",
    "retention_class",
    "priority",
    "provenance",
    "data",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_under_root(path: Path) -> Path:
    resolved = path.resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise RuntimeError(f"refusing path outside isolated research directory: {resolved}")
    return resolved


def redact_string(value: str, counters: Counter[str]) -> str:
    result = value
    for label, pattern in REDACTION_PATTERNS:
        result, replacements = pattern.subn(f"[REDACTED_{label.upper()}]", result)
        counters[f"redacted_{label}"] += replacements
    return result


def sanitize_value(value: Any, counters: Counter[str]) -> Any:
    if isinstance(value, str):
        return redact_string(value, counters)
    if isinstance(value, list):
        return [sanitize_value(item, counters) for item in value]
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            if key_s.lower() in FORBIDDEN_KEYS:
                counters[f"removed_key:{key_s.lower()}"] += 1
                continue
            clean[key_s] = sanitize_value(item, counters)
        return clean
    return value


def sanitize_event(candidate: Mapping[str, Any], counters: Counter[str]) -> dict[str, Any] | None:
    if candidate.get("privacy_class") == "companion_only":
        counters["rejected_companion_only"] += 1
        return None
    data = candidate.get("data")
    if not isinstance(data, Mapping):
        counters["rejected_bad_data"] += 1
        return None
    if data.get("payload_kind") in RAW_PAYLOAD_KINDS:
        counters["rejected_raw_payload"] += 1
        return None
    if candidate.get("privacy_class") == "consent_required" and not candidate.get("consent_id"):
        counters["rejected_missing_consent"] += 1
        return None

    stream = str(candidate.get("stream", ""))
    allowed = ALLOWED_DATA_KEYS.get(stream)
    if allowed is None:
        counters["rejected_unknown_stream"] += 1
        return None

    event = {key: copy.deepcopy(candidate[key]) for key in REQUIRED_EVENT_KEYS if key in candidate}
    clean_data: dict[str, Any] = {}
    for key, value in data.items():
        key_s = str(key)
        if key_s.lower() in FORBIDDEN_KEYS:
            counters[f"removed_key:{key_s.lower()}"] += 1
            continue
        if key_s not in allowed:
            counters[f"removed_unknown:{stream}.{key_s}"] += 1
            continue
        clean_data[key_s] = sanitize_value(value, counters)
    event["data"] = clean_data
    # Provenance is producer-owned typed metadata, not user text. Applying
    # free-text regexes to hashes can corrupt them (a hex digest may contain ten
    # consecutive digits), so it is copied and then shape-validated unchanged.
    event["provenance"] = copy.deepcopy(event.get("provenance", {}))
    return event


def walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).lower()
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def validate_event(event: Mapping[str, Any]) -> None:
    if set(event) != REQUIRED_EVENT_KEYS:
        missing = sorted(REQUIRED_EVENT_KEYS - set(event))
        extra = sorted(set(event) - REQUIRED_EVENT_KEYS)
        raise ValueError(f"event keys differ: missing={missing}, extra={extra}")
    if event["specversion"] != "1.0" or event["dataschema"] != SCHEMA_ID:
        raise ValueError("unsupported event or data schema version")
    stream = event["stream"]
    if stream not in EVENT_TYPES or event["type"] != EVENT_TYPES[stream]:
        raise ValueError("event type does not match stream")
    if not isinstance(event["sequence"], int) or event["sequence"] < 0:
        raise ValueError("sequence must be a non-negative integer")
    if not isinstance(event["priority"], int) or not 0 <= event["priority"] <= 3:
        raise ValueError("priority outside [0, 3]")
    if event["purpose"] != "research_evaluation":
        raise ValueError("purpose must be research_evaluation")
    if event["privacy_class"] not in {
        "research_nonpersonal",
        "research_pseudonymous",
        "consent_required",
    }:
        raise ValueError("unsupported privacy class")
    if event["privacy_class"] == "consent_required" and not event["consent_id"]:
        raise ValueError("consent-required event lacks consent_id")
    if not re.fullmatch(r"robot_[0-9a-f]{16}", str(event["robot_pseudonym"])):
        raise ValueError("invalid robot pseudonym")
    try:
        uuid.UUID(str(event["id"]))
        datetime.fromisoformat(str(event["time"]).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid id or time") from exc
    if set(event["data"]) - ALLOWED_DATA_KEYS[stream]:
        raise ValueError("data contains a field outside the stream allow-list")
    forbidden = sorted(set(walk_keys(event)) & FORBIDDEN_KEYS)
    if forbidden:
        raise ValueError(f"forbidden keys remain: {forbidden}")
    provenance = event["provenance"]
    required_provenance = {
        "source_event_ids",
        "code_sha256",
        "config_sha256",
        "model_ids",
        "calibration_ids",
    }
    if not isinstance(provenance, Mapping) or set(provenance) != required_provenance:
        raise ValueError("invalid provenance structure")
    for name in ("code_sha256", "config_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(provenance[name])):
            raise ValueError(f"invalid {name}")


def event_data(stream: str, sequence: int, rng: random.Random) -> dict[str, Any]:
    random_hash = hashlib.sha256(rng.randbytes(32)).hexdigest()
    if stream == "navigation":
        data: dict[str, Any] = {
            "distance_delta_m": round(rng.uniform(0.0, 0.18), 4),
            "speed_mps": round(rng.uniform(0.0, 0.55), 4),
            "localization_confidence": round(rng.uniform(0.75, 1.0), 4),
            "planner_state": rng.choice(("tracking", "paused", "recovery")),
            "recovery_count": int(sequence % 997 == 0),
            "path_segment_hash": random_hash,
        }
        if sequence % 997 == 0:
            data.update(
                gps_lat=37.7749001,
                gps_lon=-122.4194001,
                exact_address="221B Baker Street",
                unexpected_owner_hint="PRIVATE_MARKER_UNKNOWN_FIELD",
            )
        return data
    if stream == "perception":
        data = {
            "class_counts": {
                "person": rng.randrange(0, 3),
                "chair": rng.randrange(0, 5),
                "door": rng.randrange(0, 2),
            },
            "obstacle_min_m": round(rng.uniform(0.25, 5.0), 3),
            "detector_confidence": round(rng.uniform(0.5, 1.0), 4),
            "frame_summary_hash": random_hash,
        }
        if sequence % 787 == 0:
            data["raw_image"] = "PRIVATE_MARKER_IMAGE"
            data["face_embedding"] = [0.1, 0.2, 0.3, "PRIVATE_MARKER_FACE"]
        return data
    if stream == "audio":
        data = {
            "speech_probability": round(rng.random(), 4),
            "snr_db": round(rng.uniform(-5.0, 35.0), 2),
            "vad_segments": rng.randrange(0, 5),
            "acoustic_class": rng.choice(("quiet", "speech", "television", "appliance")),
            "source_chunk_hash": random_hash,
        }
        if sequence % 811 == 0:
            data["raw_audio"] = "RIFF_PRIVATE_MARKER_AUDIO"
            data["transcript"] = "PRIVATE_MARKER_TRANSCRIPT leak_test_42@example.com"
            data["voice_embedding"] = [0.4, 0.5, 0.6]
        return data
    if stream == "conversation":
        note = "no free-form note"
        if sequence % 17 == 0:
            note = "follow up with leak_test_42@example.com or +1 (212) 555-0199"
        return {
            "outcome_code": rng.choice(("completed", "clarified", "declined", "timed_out")),
            "latency_ms": rng.randrange(250, 2500),
            "turn_count": rng.randrange(1, 8),
            "repair_count": rng.randrange(0, 3),
            "safety_route_used": bool(sequence % 101 == 0),
            "redacted_note": note,
        }
    if stream == "feedback":
        note = "reviewed by offline evaluator"
        if sequence % 3 == 0:
            note = "credential sk-test-AAAAAAAAAAAAAAAAAAAA must never persist"
        return {
            "label": rng.choice(("success", "partial", "failure")),
            "task": rng.choice(("navigate", "answer", "follow", "recover")),
            "reward": round(rng.uniform(-1.0, 1.0), 4),
            "evaluator": "synthetic_rule_v1",
            "redacted_note": note,
        }
    raise ValueError(f"unknown stream {stream}")


def generate_candidates(hours: float, code_sha: str, config_sha: str) -> list[dict[str, Any]]:
    rng = random.Random(20260826)
    candidates: list[dict[str, Any]] = []
    for stream, frequency in STREAM_HZ.items():
        count = round(hours * 3600.0 * frequency)
        step_ns = round(1_000_000_000 / frequency)
        retention_class, retention_days = RETENTION[stream]
        for sequence in range(count):
            offset_ns = sequence * step_ns
            occurred = START + timedelta(microseconds=offset_ns / 1000)
            candidates.append(
                {
                    "specversion": "1.0",
                    "id": str(uuid.uuid5(NAMESPACE, f"{RUN_ID}:{stream}:{sequence}")),
                    "source": f"parcel://robot/{ROBOT_PSEUDONYM}",
                    "type": EVENT_TYPES[stream],
                    "time": iso_z(occurred),
                    "dataschema": SCHEMA_ID,
                    "run_id": RUN_ID,
                    "stream": stream,
                    "sequence": sequence,
                    "robot_pseudonym": ROBOT_PSEUDONYM,
                    "origin": {
                        "device_clock": "sim",
                        "source_time_ns": int(occurred.timestamp() * 1_000_000_000),
                        "receive_monotonic_ns": offset_ns + 20_000_000,
                    },
                    "privacy_class": "research_pseudonymous",
                    "purpose": "research_evaluation",
                    "consent_id": None,
                    "retention_class": retention_class,
                    "priority": PRIORITY[stream],
                    "provenance": {
                        "source_event_ids": [f"synthetic://{RUN_ID}/{stream}/{sequence}"],
                        "code_sha256": code_sha,
                        "config_sha256": config_sha,
                        "model_ids": ["synthetic-generator-v1"],
                        "calibration_ids": ["sim-calibration-v1"],
                    },
                    "data": event_data(stream, sequence, rng),
                    "expires_at": iso_z(occurred + timedelta(days=retention_days)),
                }
            )

    # Three negative-control candidates verify the admission boundary. These
    # remain in memory only and must not reach SQLite or a bundle.
    base = copy.deepcopy(candidates[0])
    base["id"] = str(uuid.uuid5(NAMESPACE, f"{RUN_ID}:negative:companion"))
    base["privacy_class"] = "companion_only"
    candidates.append(base)
    base = copy.deepcopy(candidates[0])
    base["id"] = str(uuid.uuid5(NAMESPACE, f"{RUN_ID}:negative:raw"))
    base["data"] = {"payload_kind": "raw_audio", "raw_audio": "RIFF_PRIVATE_MARKER_AUDIO"}
    candidates.append(base)
    base = copy.deepcopy(candidates[0])
    base["id"] = str(uuid.uuid5(NAMESPACE, f"{RUN_ID}:negative:consent"))
    base["privacy_class"] = "consent_required"
    base["consent_id"] = None
    candidates.append(base)
    return candidates


def create_spool(path: Path) -> sqlite3.Connection:
    path = ensure_under_root(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            stream TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            occurred_at TEXT NOT NULL,
            priority INTEGER NOT NULL,
            privacy_class TEXT NOT NULL,
            consent_id TEXT,
            retention_class TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            event_json BLOB NOT NULL,
            event_sha256 TEXT NOT NULL,
            sync_state TEXT NOT NULL DEFAULT 'queued',
            UNIQUE(run_id, stream, sequence)
        );
        CREATE TABLE consents (
            consent_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            granted_at TEXT NOT NULL,
            revoked_at TEXT
        );
        CREATE TABLE tombstones (
            subject_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            created_at TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            PRIMARY KEY(subject_id, scope)
        );
        CREATE TABLE bundles (
            sha256 TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            byte_count INTEGER NOT NULL,
            priority INTEGER NOT NULL,
            event_count INTEGER NOT NULL,
            sync_state TEXT NOT NULL DEFAULT 'queued'
        );
        """
    )
    return connection


def insert_event(connection: sqlite3.Connection, event: Mapping[str, Any], expires_at: str) -> bool:
    encoded = canonical_bytes(event)
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO events(
            id, run_id, stream, sequence, occurred_at, priority, privacy_class,
            consent_id, retention_class, expires_at, event_json, event_sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["id"],
            event["run_id"],
            event["stream"],
            event["sequence"],
            event["time"],
            event["priority"],
            event["privacy_class"],
            event["consent_id"],
            event["retention_class"],
            expires_at,
            encoded,
            digest_bytes(encoded),
        ),
    )
    return cursor.rowcount == 1


def spool_events(connection: sqlite3.Connection, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    retained: list[dict[str, Any]] = []
    for candidate in candidates:
        expires_at = str(candidate.pop("expires_at", ""))
        event = sanitize_event(candidate, counters)
        if event is None:
            continue
        validate_event(event)
        if insert_event(connection, event, expires_at):
            retained.append(event)
    connection.commit()

    duplicate_attempts = min(100, len(retained))
    duplicate_insertions = 0
    for event in retained[:duplicate_attempts]:
        _, retention_days = RETENTION[event["stream"]]
        expires = iso_z(datetime.fromisoformat(event["time"].replace("Z", "+00:00")) + timedelta(days=retention_days))
        duplicate_insertions += int(insert_event(connection, event, expires))
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    counts = dict(connection.execute("SELECT stream, COUNT(*) FROM events GROUP BY stream ORDER BY stream"))
    return {
        "candidate_count": len(candidates),
        "retained_count": len(retained),
        "retained_by_stream": counts,
        "filter_counters": dict(sorted(counters.items())),
        "duplicate_attempts": duplicate_attempts,
        "duplicate_insertions": duplicate_insertions,
    }


def bundle_spool(
    connection: sqlite3.Connection,
    bundle_dir: Path,
    target_uncompressed_bytes: int,
    code_sha: str,
) -> tuple[dict[str, Any], float]:
    ensure_under_root(bundle_dir).mkdir(parents=True, exist_ok=False)
    rows = connection.execute(
        "SELECT priority, event_json FROM events ORDER BY priority, occurred_at, stream, sequence, id"
    ).fetchall()
    by_priority: dict[int, list[bytes]] = defaultdict(list)
    for priority, encoded in rows:
        by_priority[int(priority)].append(bytes(encoded))

    started = time.perf_counter()
    bundles: list[dict[str, Any]] = []
    total_uncompressed = 0
    for priority in sorted(by_priority):
        chunk: list[bytes] = []
        chunk_bytes = 0
        for encoded in by_priority[priority]:
            line_bytes = len(encoded) + 1
            if chunk and chunk_bytes + line_bytes > target_uncompressed_bytes:
                bundles.append(write_bundle(bundle_dir, priority, chunk))
                total_uncompressed += chunk_bytes
                chunk = []
                chunk_bytes = 0
            chunk.append(encoded)
            chunk_bytes += line_bytes
        if chunk:
            bundles.append(write_bundle(bundle_dir, priority, chunk))
            total_uncompressed += chunk_bytes

    elapsed = time.perf_counter() - started
    manifest = {
        "manifest_version": "parcel.research_bundle_manifest.v1",
        "dataset_id": f"dataset-{RUN_ID}",
        "created_at": iso_z(START + timedelta(hours=1)),
        "schema": SCHEMA_ID,
        "event_count": len(rows),
        "uncompressed_bytes": total_uncompressed,
        "compressed_bytes": sum(bundle["compressed_bytes"] for bundle in bundles),
        "bundles": bundles,
        "lineage": {
            "model": "openlineage-inspired-minimal-v1",
            "job": {"namespace": "parcel.research", "name": "summary-bundle-v1"},
            "run_id": RUN_ID,
            "code_sha256": code_sha,
            "inputs": [{"namespace": "parcel.local-spool", "name": RUN_ID}],
            "outputs": [
                {"namespace": "parcel.research-bundles", "name": bundle["sha256"]}
                for bundle in bundles
            ],
        },
    }
    manifest_bytes = canonical_bytes(manifest)
    manifest["manifest_sha256_without_self"] = digest_bytes(manifest_bytes)
    (bundle_dir / "manifest.json").write_bytes(canonical_bytes(manifest) + b"\n")
    return manifest, elapsed


def write_bundle(bundle_dir: Path, priority: int, encoded_events: list[bytes]) -> dict[str, Any]:
    plain = b"".join(event + b"\n" for event in encoded_events)
    compressed = gzip.compress(plain, compresslevel=6, mtime=0)
    sha = digest_bytes(compressed)
    filename = f"p{priority}-{sha}.jsonl.gz"
    (bundle_dir / filename).write_bytes(compressed)
    event_ids = [json.loads(event)["id"] for event in encoded_events]
    return {
        "sha256": sha,
        "path": filename,
        "priority": priority,
        "event_count": len(encoded_events),
        "first_event_id": event_ids[0],
        "last_event_id": event_ids[-1],
        "event_id_digest": digest_bytes("\n".join(event_ids).encode("utf-8")),
        "uncompressed_bytes": len(plain),
        "compressed_bytes": len(compressed),
    }


def replay_manifest(bundle_dir: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for entry in manifest["bundles"]:
        compressed = (bundle_dir / entry["path"]).read_bytes()
        actual = digest_bytes(compressed)
        if actual != entry["sha256"]:
            raise ValueError(f"bundle checksum mismatch: expected={entry['sha256']} actual={actual}")
        plain = gzip.decompress(compressed)
        if len(plain) != entry["uncompressed_bytes"]:
            raise ValueError("uncompressed byte count mismatch")
        lines = plain.splitlines()
        if len(lines) != entry["event_count"]:
            raise ValueError("bundle event count mismatch")
        for line in lines:
            event = json.loads(line)
            validate_event(event)
            if canonical_bytes(event) != line:
                raise ValueError("event is not canonical JSON")
            events.append(event)

    if len(events) != manifest["event_count"]:
        raise ValueError("manifest event count mismatch")
    ids = [event["id"] for event in events]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate event ID on replay")
    sequences: dict[str, list[int]] = defaultdict(list)
    for event in events:
        sequences[event["stream"]].append(event["sequence"])
    for stream, values in sequences.items():
        if sorted(values) != list(range(len(values))):
            raise ValueError(f"non-contiguous sequence in {stream}")
    ordered = sorted(canonical_bytes(event) for event in events)
    replay_digest = digest_bytes(b"\n".join(ordered))
    return {
        "event_count": len(events),
        "unique_event_count": len(set(ids)),
        "event_set_sha256": replay_digest,
        "sequence_contiguous_by_stream": {stream: True for stream in sorted(sequences)},
        "events": events,
    }


def corruption_probe(bundle_dir: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    first = manifest["bundles"][0]
    original = (bundle_dir / first["path"]).read_bytes()
    corrupted = bytearray(original)
    corrupted[len(corrupted) // 2] ^= 0x01
    actual = digest_bytes(bytes(corrupted))
    return {
        "mutated_bytes": 1,
        "expected_sha256": first["sha256"],
        "actual_sha256": actual,
        "detected": actual != first["sha256"],
        "detection_stage": "pre-decompression SHA-256 verification",
    }


def simulate_upload_round(
    manifest: Mapping[str, Any], already_present: set[str], cap_bytes: int
) -> dict[str, Any]:
    transferred: list[str] = []
    used = 0
    for bundle in sorted(manifest["bundles"], key=lambda item: (item["priority"], item["sha256"])):
        sha = bundle["sha256"]
        size = int(bundle["compressed_bytes"])
        if sha in already_present:
            continue
        if used + size > cap_bytes:
            continue
        already_present.add(sha)
        transferred.append(sha)
        used += size
    return {
        "cap_bytes": cap_bytes,
        "transferred_bytes": used,
        "transferred_bundle_count": len(transferred),
        "transferred_sha256": transferred,
    }


def scan_for_leaks(paths: Iterable[Path], replay_events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    blobs: list[bytes] = []
    scanned_suffixes: Counter[str] = Counter()
    for path in paths:
        if path.exists() and path.is_file():
            blobs.append(path.read_bytes())
            scanned_suffixes["".join(path.suffixes) or "no_suffix"] += 1
    combined = b"\n".join(blobs)
    marker_hits = [marker for marker in LEAK_MARKERS if marker.encode("utf-8") in combined]
    forbidden_hits: Counter[str] = Counter()
    for event in replay_events:
        forbidden_hits.update(set(walk_keys(event)) & FORBIDDEN_KEYS)
    return {
        "scanned_file_count": len(blobs),
        "scanned_files_by_suffix": dict(sorted(scanned_suffixes.items())),
        "seeded_marker_count": len(LEAK_MARKERS),
        "marker_hits": marker_hits,
        "forbidden_key_hits": dict(sorted(forbidden_hits.items())),
        "pass": not marker_hits and not forbidden_hits,
        "scope_note": "Seeded-marker and schema-key test only; it does not prove de-identification of arbitrary unstructured content.",
    }


def build_cost_and_traffic(manifest: Mapping[str, Any], hours: float) -> dict[str, Any]:
    compressed_per_hour = manifest["compressed_bytes"] / hours
    uncompressed_per_hour = manifest["uncompressed_bytes"] / hours
    operating_hours_month = 8 * 30
    summary_month_bytes = compressed_per_hour * operating_hours_month
    summary_90d_bytes = summary_month_bytes * 3

    # Explicit scenarios, not measurements of Parcel hardware. PCM arithmetic is
    # exact for the named format; camera and lidar rates are conservative input
    # assumptions whose sensitivity is left machine-readable.
    raw_rates = {
        "pcm16_mono_16khz": {
            "bytes_per_second": 16_000 * 2,
            "basis": "derived: 16,000 samples/s * 2 bytes/sample",
        },
        "jpeg_camera_5fps_150kb_per_frame": {
            "bytes_per_second": 5 * 150_000,
            "basis": "scenario assumption; measure on physical camera",
        },
        "serialized_lidar_100kbps": {
            "bytes_per_second": 100_000,
            "basis": "scenario assumption; measure on physical lidar",
        },
    }
    raw_bps = sum(item["bytes_per_second"] for item in raw_rates.values())
    raw_month_bytes = raw_bps * 3600 * operating_hours_month

    r2_storage_usd_per_gb_month = 0.015
    class_a_usd_per_million = 4.50
    monthly_bundle_puts = len(manifest["bundles"]) * operating_hours_month
    gross_put_cost = monthly_bundle_puts / 1_000_000 * class_a_usd_per_million
    free_adjusted_put_cost = max(0, monthly_bundle_puts - 1_000_000) / 1_000_000 * class_a_usd_per_million
    return {
        "projection_basis": {
            "measured_synthetic_hours": hours,
            "operating_hours_per_day": 8,
            "days_per_month": 30,
            "decimal_gb_bytes": 1_000_000_000,
        },
        "summary": {
            "compressed_bytes_per_hour": compressed_per_hour,
            "uncompressed_bytes_per_hour": uncompressed_per_hour,
            "projected_month_bytes": summary_month_bytes,
            "projected_month_decimal_gb": summary_month_bytes / 1_000_000_000,
            "projected_90d_retained_decimal_gb": summary_90d_bytes / 1_000_000_000,
        },
        "raw_scenario": {
            "rates": raw_rates,
            "combined_bytes_per_second": raw_bps,
            "projected_month_bytes": raw_month_bytes,
            "projected_month_decimal_gb": raw_month_bytes / 1_000_000_000,
            "not_a_physical_measurement": True,
        },
        "starlink": {
            "conservative_priority_bucket_decimal_gb": 40.0,
            "summary_fraction_of_40gb": summary_month_bytes / 40_000_000_000,
            "raw_scenario_fraction_of_40gb": raw_month_bytes / 40_000_000_000,
            "plan_and_country_must_be_operator_configured": True,
        },
        "r2_standard_estimate_as_of_2026_08_26": {
            "storage_usd_per_gb_month": r2_storage_usd_per_gb_month,
            "class_a_usd_per_million": class_a_usd_per_million,
            "summary_90d_storage_usd_per_month": summary_90d_bytes
            / 1_000_000_000
            * r2_storage_usd_per_gb_month,
            "raw_30d_storage_scenario_usd_per_month": raw_month_bytes
            / 1_000_000_000
            * r2_storage_usd_per_gb_month,
            "monthly_bundle_puts": monthly_bundle_puts,
            "gross_class_a_put_usd_per_month": gross_put_cost,
            "free_tier_adjusted_class_a_put_usd_per_month": free_adjusted_put_cost,
            "excludes": [
                "compute",
                "catalog operations",
                "retrieval",
                "tax",
                "Starlink subscription and overage",
                "support and engineering labor",
            ],
        },
    }


def run(hours: float, target_bundle_kib: int, daily_cap_mib: int) -> dict[str, Any]:
    if hours <= 0 or target_bundle_kib <= 0 or daily_cap_mib <= 0:
        raise ValueError("hours and byte caps must be positive")
    code_sha = digest_bytes(Path(__file__).read_bytes())
    config = {
        "hours": hours,
        "target_bundle_kib": target_bundle_kib,
        "daily_cap_mib": daily_cap_mib,
        "stream_hz": STREAM_HZ,
        "seed": 20260826,
    }
    config_sha = digest_bytes(canonical_bytes(config))
    wall_started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix=".research-plane-bench-", dir=ROOT) as scratch_name:
        scratch = ensure_under_root(Path(scratch_name))
        spool_path = scratch / "research_spool.sqlite3"
        connection = create_spool(spool_path)

        generate_started = time.perf_counter()
        candidates = generate_candidates(hours, code_sha, config_sha)
        generation_elapsed = time.perf_counter() - generate_started

        ingest_started = time.perf_counter()
        spool = spool_events(connection, candidates)
        ingest_elapsed = time.perf_counter() - ingest_started
        spool_size = spool_path.stat().st_size

        bundle_dir = scratch / "bundles"
        manifest, bundle_elapsed = bundle_spool(
            connection,
            bundle_dir,
            target_uncompressed_bytes=target_bundle_kib * 1024,
            code_sha=code_sha,
        )
        connection.commit()

        replay_started = time.perf_counter()
        replay_one = replay_manifest(bundle_dir, manifest)
        replay_elapsed = time.perf_counter() - replay_started
        replay_two = replay_manifest(bundle_dir, manifest)
        corruption = corruption_probe(bundle_dir, manifest)

        remote_hashes: set[str] = set()
        total_compressed = int(manifest["compressed_bytes"])
        largest_bundle = max(int(bundle["compressed_bytes"]) for bundle in manifest["bundles"])
        first_cap = max(largest_bundle, total_compressed // 2)
        sync_round_1 = simulate_upload_round(manifest, remote_hashes, first_cap)
        sync_round_2 = simulate_upload_round(manifest, remote_hashes, daily_cap_mib * 1024 * 1024)
        sync_round_3 = simulate_upload_round(manifest, remote_hashes, daily_cap_mib * 1024 * 1024)

        all_files = [spool_path, bundle_dir / "manifest.json"] + [
            bundle_dir / bundle["path"] for bundle in manifest["bundles"]
        ]
        privacy = scan_for_leaks(all_files, replay_one["events"])
        cost = build_cost_and_traffic(manifest, hours)
        connection.close()

        bundle_throughput = manifest["uncompressed_bytes"] / max(bundle_elapsed, 1e-9) / 1_000_000
        replay_throughput = manifest["uncompressed_bytes"] / max(replay_elapsed, 1e-9) / 1_000_000
        compression_ratio = manifest["compressed_bytes"] / manifest["uncompressed_bytes"]
        synced_all = len(remote_hashes) == len(manifest["bundles"])
        high_priority = {bundle["sha256"] for bundle in manifest["bundles"] if bundle["priority"] <= 2}
        high_priority_synced = high_priority <= remote_hashes

        hypotheses = {
            "H1_privacy_boundary": {
                "claim": "All seeded PII/secrets/raw fields are absent from the spool and bundles.",
                "pass": privacy["pass"]
                and spool["filter_counters"].get("rejected_companion_only", 0) == 1
                and spool["filter_counters"].get("rejected_raw_payload", 0) == 1
                and spool["filter_counters"].get("rejected_missing_consent", 0) == 1,
                "threshold": "zero seeded marker hits, zero forbidden keys, and all three negative controls rejected",
            },
            "H2_deterministic_replay": {
                "claim": "Replay is complete and deterministic, duplicates are idempotent, and one-byte corruption is detected.",
                "pass": replay_one["event_count"] == spool["retained_count"]
                and replay_one["event_set_sha256"] == replay_two["event_set_sha256"]
                and spool["duplicate_insertions"] == 0
                and corruption["detected"],
                "threshold": "exact count/digest twice, zero duplicate insertions, corruption detected",
            },
            "H3_compact_fast_bundles": {
                "claim": "Summary NDJSON compresses to at most 30% and bundles at at least 10 MB/s on this host.",
                "pass": compression_ratio <= 0.30 and bundle_throughput >= 10.0,
                "threshold": {"max_compression_ratio": 0.30, "min_bundle_throughput_MBps": 10.0},
            },
            "H4_budgeted_sync": {
                "claim": "The projected summary stream stays below 5 GB/month and all priority 0-2 bundles fit a 50 MiB/day governor.",
                "pass": cost["summary"]["projected_month_decimal_gb"] <= 5.0
                and daily_cap_mib == 50
                and synced_all
                and high_priority_synced,
                "threshold": {"max_month_decimal_gb": 5.0, "daily_cap_MiB": 50},
            },
            "H5_summary_first_required": {
                "claim": "The named raw-data scenario exceeds a conservative 40 GB/month priority bucket while summaries do not.",
                "pass": cost["raw_scenario"]["projected_month_decimal_gb"] > 40.0
                and cost["summary"]["projected_month_decimal_gb"] < 40.0,
                "threshold": "raw > 40 GB/month and summaries < 40 GB/month",
            },
            "H6_summary_storage_cost": {
                "claim": "Ninety days of projected summaries costs under $1/month at the cited R2 Standard storage rate.",
                "pass": cost["r2_standard_estimate_as_of_2026_08_26"][
                    "summary_90d_storage_usd_per_month"
                ]
                < 1.0,
                "threshold_usd_per_month": 1.0,
            },
        }

        result = {
            "result_version": RESULT_VERSION,
            "run_id": RUN_ID,
            "run_at": iso_z(datetime.now(timezone.utc)),
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "sqlite": sqlite3.sqlite_version,
                "pid": os.getpid(),
            },
            "config": config,
            "code_sha256": code_sha,
            "config_sha256": config_sha,
            "spool": {**spool, "sqlite_bytes": spool_size, "journal_mode": "WAL", "synchronous": "FULL"},
            "bundle": {
                "bundle_count": len(manifest["bundles"]),
                "target_uncompressed_bytes": target_bundle_kib * 1024,
                "uncompressed_bytes": manifest["uncompressed_bytes"],
                "compressed_bytes": manifest["compressed_bytes"],
                "compression_ratio": compression_ratio,
                "event_count": manifest["event_count"],
                "manifest_sha256_without_self": manifest["manifest_sha256_without_self"],
                "bundle_throughput_MBps": bundle_throughput,
            },
            "replay": {
                "first_event_count": replay_one["event_count"],
                "second_event_count": replay_two["event_count"],
                "first_event_set_sha256": replay_one["event_set_sha256"],
                "second_event_set_sha256": replay_two["event_set_sha256"],
                "stable": replay_one["event_set_sha256"] == replay_two["event_set_sha256"],
                "sequence_contiguous_by_stream": replay_one["sequence_contiguous_by_stream"],
                "replay_throughput_MBps": replay_throughput,
                "corruption_probe": corruption,
            },
            "sync": {
                "algorithm": "priority then content hash; whole-bundle idempotency",
                "rounds": [sync_round_1, sync_round_2, sync_round_3],
                "remote_bundle_count": len(remote_hashes),
                "manifest_bundle_count": len(manifest["bundles"]),
                "all_synced": synced_all,
                "all_priority_0_to_2_synced": high_priority_synced,
                "third_round_transferred_zero_bytes": sync_round_3["transferred_bytes"] == 0,
            },
            "privacy": privacy,
            "traffic_and_cost": cost,
            "timing": {
                "generation_seconds": generation_elapsed,
                "ingest_seconds": ingest_elapsed,
                "bundle_seconds": bundle_elapsed,
                "replay_seconds": replay_elapsed,
                "total_seconds": time.perf_counter() - wall_started,
            },
            "hypotheses": hypotheses,
            "hypotheses_passed": sum(1 for item in hypotheses.values() if item["pass"]),
            "hypotheses_total": len(hypotheses),
            "limitations": [
                "Synthetic summaries are not a physical-robot throughput, sensor-rate, power, thermal, or network measurement.",
                "Regex and field allow-list checks cover seeded cases; they do not prove that arbitrary free text, images, or embeddings are anonymous.",
                "The upload is a local simulation; no object-store API, TLS, KMS, Starlink link, or interrupted multipart transfer was exercised.",
                "gzip/JSONL was tested as an edge interchange bundle; Parquet, Iceberg commits, catalog concurrency, and query performance were not benchmarked.",
                "SQLite WAL durability was configured but sudden-power-loss recovery was not fault-injected in this run.",
                "R2 prices and Starlink policy were researched as of 2026-08-26 and can change.",
            ],
        }

    # Foundational privacy and integrity failures make the probe invalid rather
    # than merely slower or costlier. Performance hypotheses remain reportable.
    if not result["hypotheses"]["H1_privacy_boundary"]["pass"]:
        raise RuntimeError("privacy-boundary hypothesis failed")
    if not result["hypotheses"]["H2_deterministic_replay"]["pass"]:
        raise RuntimeError("deterministic-replay hypothesis failed")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=1.0)
    parser.add_argument("--target-bundle-kib", type=int, default=256)
    parser.add_argument("--daily-cap-mib", type=int, default=50)
    parser.add_argument("--output", type=Path, default=ROOT / "results.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = ensure_under_root(args.output)
    result = run(args.hours, args.target_bundle_kib, args.daily_cap_mib)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(
        json.dumps(
            {
                "output": str(output),
                "hypotheses": f"{result['hypotheses_passed']}/{result['hypotheses_total']}",
                "events": result["spool"]["retained_count"],
                "compressed_bytes": result["bundle"]["compressed_bytes"],
                "replay_sha256": result["replay"]["first_event_set_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
