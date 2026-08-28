"""Deterministic content-addressed bundles and exact replay verification."""

from __future__ import annotations

import gzip
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .bundle_validation import BUNDLE_MANIFEST_VERSION, MANIFEST_KEYS
from .contracts import (
    SCHEMA_ID,
    ResearchEventV1,
    canonical_json_bytes,
    event_id_digest,
    sha256_hex,
)
from .spool import ResearchSpool


@dataclass(frozen=True, slots=True)
class BundleArtifactV1:
    bundle_sha256: str
    bundle_path: Path
    manifest_path: Path
    priority: int
    event_count: int
    compressed_bytes: int
    uncompressed_bytes: int
    event_id_digest: str
    manifest_sha256: str
    manifest_file_sha256: str
    lineage_sha256: str


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_immutable(path: Path, payload: bytes, staging_path: Path) -> bool:
    """Atomically create ``path`` or verify an identical prior object."""

    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"content-addressed path has different bytes: {path.name}")
        return False
    if staging_path.parent != path.parent:
        raise ValueError("staging path must share the publication directory")
    descriptor = os.open(staging_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link publication is exclusive: unlike ``os.replace`` it can
        # never overwrite an immutable object another process just published.
        try:
            os.link(staging_path, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise ValueError(f"content-addressed path raced with different bytes: {path.name}")
            return False
        if path.read_bytes() != payload:
            raise RuntimeError("immutable bundle write did not round-trip")
        _fsync_directory(path.parent)
        return True
    finally:
        if staging_path.exists():
            staging_path.unlink()
            _fsync_directory(path.parent)


def _claim_events(event_bytes: tuple[bytes, ...]) -> list[ResearchEventV1]:
    events: list[ResearchEventV1] = []
    for encoded in event_bytes:
        decoded = json.loads(encoded)
        if canonical_json_bytes(decoded) != encoded:
            raise ValueError("spool contains non-canonical event JSON")
        events.append(ResearchEventV1.from_mapping(decoded))
    if len({event.priority for event in events}) != 1:
        raise ValueError("one bundle may contain exactly one priority class")
    return events


def _manifest_payload(
    events: list[ResearchEventV1],
    bundle_sha: str,
    bundle_path: Path,
    compressed: bytes,
    plain: bytes,
) -> tuple[bytes, str, str, str, str]:
    lineage: dict[str, object] = {
        "model": "openlineage-inspired-minimal-v1",
        "job": {"namespace": "parcel.research", "name": "summary-bundle-v1"},
        "inputs": sorted(
            {
                event.provenance.code_sha256 + ":" + event.provenance.config_sha256
                for event in events
            }
        ),
        "output": bundle_sha,
    }
    id_digest = event_id_digest(events)
    manifest_without_digest: dict[str, object] = {
        "manifest_version": BUNDLE_MANIFEST_VERSION,
        "schema": SCHEMA_ID,
        "bundle_sha256": bundle_sha,
        "bundle_path": bundle_path.name,
        "priority": events[0].priority,
        "event_count": len(events),
        "first_event_id": events[0].event_id,
        "last_event_id": events[-1].event_id,
        "event_id_digest": id_digest,
        "uncompressed_bytes": len(plain),
        "compressed_bytes": len(compressed),
        "run_ids": sorted({event.run_id for event in events}),
        "streams": sorted({event.stream for event in events}),
        "lineage": lineage,
    }
    manifest_sha = sha256_hex(canonical_json_bytes(manifest_without_digest))
    payload = canonical_json_bytes(
        {**manifest_without_digest, "manifest_sha256_without_self": manifest_sha}
    ) + b"\n"
    return (
        payload,
        manifest_sha,
        sha256_hex(payload),
        sha256_hex(canonical_json_bytes(lineage)),
        id_digest,
    )


def build_bundle(
    spool: ResearchSpool,
    *,
    target_uncompressed_bytes: int = 512 * 1024,
    max_events: int = 4096,
    now: datetime | None = None,
) -> BundleArtifactV1 | None:
    """Claim one priority class, write it, verify it, then commit the claim.

    ``now`` is injectable so consent expiry and queue selection share the
    caller's logical clock. Production callers omit it and use wall time.
    """

    claim = spool.claim_queued(
        target_uncompressed_bytes=target_uncompressed_bytes,
        max_events=max_events,
        now=now,
    )
    if claim is None:
        return None
    intent_recorded = False
    try:
        events = _claim_events(claim.event_bytes)
        priority = events[0].priority
        plain = b"".join(event.canonical_bytes() + b"\n" for event in events)
        compressed = gzip.compress(plain, compresslevel=6, mtime=0)
        bundle_sha = sha256_hex(compressed)
        bundle_path = spool.bundle_root / f"p{priority}-{bundle_sha}.jsonl.gz"
        manifest_payload, manifest_sha, manifest_file_sha, lineage_sha, id_digest = (
            _manifest_payload(events, bundle_sha, bundle_path, compressed, plain)
        )
        manifest_path = spool.bundle_root / f"{bundle_sha}.manifest.json"
        bundle_stage = spool.bundle_root / f".stage-{claim.claim_token}.bundle"
        manifest_stage = spool.bundle_root / f".stage-{claim.claim_token}.manifest"
        spool.record_bundle_publication_intent(
            claim_token=claim.claim_token,
            bundle_sha256=bundle_sha,
            bundle_path=bundle_path,
            manifest_path=manifest_path,
            bundle_stage_path=bundle_stage,
            manifest_stage_path=manifest_stage,
        )
        intent_recorded = True
        _write_immutable(bundle_path, compressed, bundle_stage)
        _write_immutable(manifest_path, manifest_payload, manifest_stage)

        artifact = BundleArtifactV1(
            bundle_sha256=bundle_sha,
            bundle_path=bundle_path,
            manifest_path=manifest_path,
            priority=priority,
            event_count=len(events),
            compressed_bytes=len(compressed),
            uncompressed_bytes=len(plain),
            event_id_digest=id_digest,
            manifest_sha256=manifest_sha,
            manifest_file_sha256=manifest_file_sha,
            lineage_sha256=lineage_sha,
        )
        replayed = replay_bundle(artifact)
        if tuple(event.event_id for event in replayed) != tuple(event.event_id for event in events):
            raise RuntimeError("bundle replay changed event order")
        spool.register_bundle(
            claim_token=claim.claim_token,
            bundle_sha256=bundle_sha,
            bundle_path=bundle_path,
            manifest_path=manifest_path,
            priority=priority,
            event_ids=[event.event_id for event in events],
            compressed_bytes=len(compressed),
            uncompressed_bytes=len(plain),
            manifest_file_sha256=manifest_file_sha,
            manifest_content_sha256=manifest_sha,
            event_id_digest=id_digest,
            first_event_id=events[0].event_id,
            last_event_id=events[-1].event_id,
            lineage_sha256=lineage_sha,
        )
        return artifact
    except Exception:
        if intent_recorded:
            spool.abandon_bundle_publication(claim.claim_token)
            spool.reconcile_bundle_artifacts()
        else:
            spool.release_claim(claim.claim_token)
        raise


def replay_bundle(artifact: BundleArtifactV1) -> tuple[ResearchEventV1, ...]:
    """Verify every content and manifest binding before returning events."""

    manifest_raw = artifact.manifest_path.read_bytes()
    if not manifest_raw.endswith(b"\n"):
        raise ValueError("manifest is not canonical newline-terminated JSON")
    manifest = json.loads(manifest_raw)
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        raise ValueError("manifest shape mismatch")
    if canonical_json_bytes(manifest) + b"\n" != manifest_raw:
        raise ValueError("manifest is not canonical JSON")
    if manifest.get("manifest_version") != BUNDLE_MANIFEST_VERSION:
        raise ValueError("unsupported bundle manifest")
    if sha256_hex(manifest_raw) != artifact.manifest_file_sha256:
        raise ValueError("exact manifest file checksum mismatch")
    claimed_manifest_sha = manifest.pop("manifest_sha256_without_self", None)
    actual_manifest_sha = sha256_hex(canonical_json_bytes(manifest))
    if claimed_manifest_sha != actual_manifest_sha or claimed_manifest_sha != artifact.manifest_sha256:
        raise ValueError("manifest checksum mismatch")

    compressed = artifact.bundle_path.read_bytes()
    if sha256_hex(compressed) != artifact.bundle_sha256:
        raise ValueError("bundle checksum mismatch")
    if manifest.get("bundle_sha256") != artifact.bundle_sha256:
        raise ValueError("manifest binds a different bundle")
    if manifest.get("bundle_path") != artifact.bundle_path.name:
        raise ValueError("manifest binds a different bundle path")
    if manifest.get("event_count") != artifact.event_count:
        raise ValueError("manifest event count mismatch")
    if manifest.get("priority") != artifact.priority:
        raise ValueError("manifest priority mismatch")
    if manifest.get("compressed_bytes") != artifact.compressed_bytes:
        raise ValueError("manifest compressed byte count mismatch")
    if manifest.get("uncompressed_bytes") != artifact.uncompressed_bytes:
        raise ValueError("manifest uncompressed byte count mismatch")
    if len(compressed) != artifact.compressed_bytes:
        raise ValueError("compressed byte count mismatch")
    plain = gzip.decompress(compressed)
    if len(plain) != artifact.uncompressed_bytes:
        raise ValueError("uncompressed byte count mismatch")
    lines = plain.splitlines()
    if len(lines) != artifact.event_count:
        raise ValueError("event count mismatch")

    events: list[ResearchEventV1] = []
    for line in lines:
        decoded: Mapping[str, object] = json.loads(line)
        if canonical_json_bytes(decoded) != line:
            raise ValueError("event is not canonical JSON")
        events.append(ResearchEventV1.from_mapping(decoded))
    ids = [event.event_id for event in events]
    if len(ids) != len(set(ids)):
        raise ValueError("bundle contains duplicate event IDs")
    if event_id_digest(events) != artifact.event_id_digest:
        raise ValueError("event ID digest mismatch")
    if manifest.get("event_id_digest") != artifact.event_id_digest:
        raise ValueError("manifest event ID digest mismatch")
    if {event.priority for event in events} != {artifact.priority}:
        raise ValueError("bundle crosses priority classes")
    if manifest.get("first_event_id") != events[0].event_id:
        raise ValueError("manifest first event mismatch")
    if manifest.get("last_event_id") != events[-1].event_id:
        raise ValueError("manifest last event mismatch")
    if manifest.get("run_ids") != sorted({event.run_id for event in events}):
        raise ValueError("manifest run IDs mismatch")
    if manifest.get("streams") != sorted({event.stream for event in events}):
        raise ValueError("manifest streams mismatch")
    lineage = manifest.get("lineage")
    if not isinstance(lineage, dict):
        raise TypeError("manifest lineage must be an object")
    if sha256_hex(canonical_json_bytes(lineage)) != artifact.lineage_sha256:
        raise ValueError("manifest lineage checksum mismatch")
    return tuple(events)
