"""Leaf-level exact bundle and manifest verification."""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .contracts import SCHEMA_ID, ResearchEventV1, canonical_json_bytes, event_id_digest, sha256_hex

BUNDLE_MANIFEST_VERSION = "parcel.research_bundle_manifest.v1"
MANIFEST_KEYS = frozenset(
    {
        "manifest_version",
        "schema",
        "bundle_sha256",
        "bundle_path",
        "priority",
        "event_count",
        "first_event_id",
        "last_event_id",
        "event_id_digest",
        "uncompressed_bytes",
        "compressed_bytes",
        "run_ids",
        "streams",
        "lineage",
        "manifest_sha256_without_self",
    }
)


@dataclass(frozen=True, slots=True)
class PersistedBundleShapeV1:
    bundle_sha256: str
    priority: int
    event_count: int
    compressed_bytes: int
    uncompressed_bytes: int
    manifest_file_sha256: str
    manifest_content_sha256: str
    event_id_digest: str
    first_event_id: str
    last_event_id: str
    lineage_sha256: str


def _load_manifest(path: Path, shape: PersistedBundleShapeV1) -> dict[str, object]:
    raw = path.read_bytes()
    if sha256_hex(raw) != shape.manifest_file_sha256:
        raise ValueError("exact manifest file checksum mismatch")
    if not raw.endswith(b"\n"):
        raise ValueError("source bundle manifest is not canonical")
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("source_bundle_manifest_invalid") from exc
    if not isinstance(decoded, dict):
        raise TypeError("source bundle manifest must be an object")
    manifest: dict[str, object] = decoded
    if set(manifest) != MANIFEST_KEYS or canonical_json_bytes(manifest) + b"\n" != raw:
        raise ValueError("manifest shape or canonical encoding mismatch")
    claimed = manifest.pop("manifest_sha256_without_self")
    if claimed != shape.manifest_content_sha256:
        raise ValueError("persisted manifest content checksum mismatch")
    if claimed != sha256_hex(canonical_json_bytes(manifest)):
        raise ValueError("manifest checksum mismatch")
    return manifest


def _replay_events(compressed: bytes, shape: PersistedBundleShapeV1) -> list[ResearchEventV1]:
    try:
        plain = gzip.decompress(compressed)
    except (gzip.BadGzipFile, EOFError, OSError) as exc:
        raise ValueError("bundle compression is invalid") from exc
    if len(plain) != shape.uncompressed_bytes:
        raise ValueError("uncompressed byte count mismatch")
    lines = plain.splitlines()
    if len(lines) != shape.event_count:
        raise ValueError("event count mismatch")
    events: list[ResearchEventV1] = []
    for line in lines:
        decoded: Mapping[str, object] = json.loads(line)
        if canonical_json_bytes(decoded) != line:
            raise ValueError("event is not canonical JSON")
        events.append(ResearchEventV1.from_mapping(decoded))
    return events


def verify_persisted_bundle(
    bundle_path: Path,
    manifest_path: Path,
    shape: PersistedBundleShapeV1,
    *,
    expected_event_hashes: Mapping[str, str],
) -> None:
    manifest = _load_manifest(manifest_path, shape)
    compressed = bundle_path.read_bytes()
    if len(compressed) != shape.compressed_bytes or sha256_hex(compressed) != shape.bundle_sha256:
        raise ValueError("bundle checksum or byte count mismatch")
    expected_manifest = {
        "manifest_version": BUNDLE_MANIFEST_VERSION,
        "bundle_sha256": shape.bundle_sha256,
        "bundle_path": bundle_path.name,
        "priority": shape.priority,
        "event_count": shape.event_count,
        "uncompressed_bytes": shape.uncompressed_bytes,
        "compressed_bytes": shape.compressed_bytes,
        "event_id_digest": shape.event_id_digest,
        "first_event_id": shape.first_event_id,
        "last_event_id": shape.last_event_id,
    }
    if any(manifest.get(key) != value for key, value in expected_manifest.items()):
        raise ValueError("bundle manifest metadata mismatch")
    lineage = manifest.get("lineage")
    if not isinstance(lineage, dict):
        raise TypeError("manifest lineage must be an object")
    if sha256_hex(canonical_json_bytes(lineage)) != shape.lineage_sha256:
        raise ValueError("manifest lineage checksum mismatch")
    events = _replay_events(compressed, shape)
    actual_hashes = {event.event_id: event.sha256 for event in events}
    if actual_hashes != dict(expected_event_hashes) or len(actual_hashes) != len(events):
        raise ValueError("bundle events do not match immutable spool records")
    if {event.priority for event in events} != {shape.priority}:
        raise ValueError("bundle crosses priority classes")
    if event_id_digest(events) != shape.event_id_digest:
        raise ValueError("event ID digest mismatch")
    if manifest.get("run_ids") != sorted({event.run_id for event in events}):
        raise ValueError("manifest run IDs mismatch")
    if manifest.get("streams") != sorted({event.stream for event in events}):
        raise ValueError("manifest streams mismatch")
    expected_lineage: dict[str, object] = {
        "model": "openlineage-inspired-minimal-v1",
        "job": {"namespace": "parcel.research", "name": "summary-bundle-v1"},
        "inputs": sorted(
            {
                event.provenance.code_sha256 + ":" + event.provenance.config_sha256
                for event in events
            }
        ),
        "output": shape.bundle_sha256,
    }
    exact_manifest: dict[str, object] = {
        **expected_manifest,
        "schema": SCHEMA_ID,
        "run_ids": sorted({event.run_id for event in events}),
        "streams": sorted({event.stream for event in events}),
        "lineage": expected_lineage,
    }
    if manifest != exact_manifest:
        raise ValueError("manifest is not the exact replay-derived manifest")
