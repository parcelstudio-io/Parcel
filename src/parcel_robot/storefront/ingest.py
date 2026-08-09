"""Ingest OCR hits as DetectionMsg evidence into SemanticMemory (pure helper)."""

from __future__ import annotations

import math
from collections.abc import Sequence

from parcel_robot.contracts import (
    SCHEMA_VERSION,
    DetectionMsg,
    EvidenceEnvelopeV1,
    expires_from_ttl,
)
from parcel_robot.contracts.freshness import DEFAULT_DETECTION_TTL_NS
from parcel_robot.instructnav.memory import RememberedEntity, SemanticMemory2D
from parcel_robot.storefront.ocr import OcrHit
from parcel_robot.storefront.placards import normalize_sign_text

DOES_NOT_PROVE = (
    "OCR→DetectionMsg ingest on synthetic fixtures does not prove wild "
    "storefront named-place precision.",
)


def _stable_embedding(text: str, *, dims: int = 8) -> tuple[float, ...]:
    """Deterministic low-dim embedding from characters (not a real text encoder)."""

    normalized = normalize_sign_text(text)
    vals = [0.0] * dims
    for i, ch in enumerate(normalized.encode("ascii", errors="ignore")):
        vals[i % dims] += (ch % 31) / 31.0
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return tuple(v / norm for v in vals)


def ocr_hit_to_detection(
    hit: OcrHit,
    *,
    received_monotonic_ns: int,
    source_timestamp_ns: int | None = None,
    sequence: int = 0,
    frame_id: str = "camera_color_optical_frame",
    calibration_id: str = "d455-intrinsics-nominal",
    ttl_ns: int = DEFAULT_DETECTION_TTL_NS,
    class_prefix: str = "storefront",
) -> DetectionMsg:
    """Map one OCR hit to a detector-shaped ``DetectionMsg``.

    ``class_id`` becomes ``storefront:<normalized text>`` so SemanticMemory can
    recall brand/sign strings. Bearing/range come from fixture metadata when
    present; otherwise origin-facing defaults.
    """

    if hit.bearing_rad is None or hit.range_m is None:
        raise ValueError(
            "ocr hit needs bearing_rad and range_m for DetectionMsg ingest "
            "(fake OCR supplies these from fixtures)"
        )
    text = normalize_sign_text(hit.text)
    class_id = f"{class_prefix}:{text.replace(' ', '_').lower()}"
    if len(class_id) > 64:
        class_id = class_id[:64]
    evidence_id = hit.evidence_ref or f"ocr:{hit.backend}:{sequence}"
    # EvidenceEnvelope identifiers disallow some punctuation — sanitize.
    safe_id = "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in evidence_id)
    if not safe_id or not safe_id[0].isalnum():
        safe_id = f"ocr_{safe_id}" if safe_id else f"ocr_{sequence}"
    src_ts = (
        int(source_timestamp_ns)
        if source_timestamp_ns is not None
        else int(received_monotonic_ns)
    )
    envelope = EvidenceEnvelopeV1(
        schema_version=SCHEMA_VERSION,
        evidence_id=safe_id[:128],
        source=f"sim.storefront.ocr.{hit.backend}",
        source_timestamp_ns=src_ts,
        received_monotonic_ns=int(received_monotonic_ns),
        sequence=int(sequence),
        frame_id=frame_id,
        scene_revision=0,
        expires_monotonic_ns=expires_from_ttl(
            received_monotonic_ns=int(received_monotonic_ns),
            ttl_ns=ttl_ns,
        ),
        calibration_id=calibration_id,
        provenance=(
            "p3_storefront_ocr",
            hit.backend,
            *(["unverified_paddle"] if hit.backend == "paddleocr" else []),
        ),
    )
    track = hit.storefront_id.replace("-", "_") if hit.storefront_id else ""
    if track and not track[0].isalnum():
        track = f"sf_{track}"
    return DetectionMsg(
        envelope=envelope,
        class_id=class_id,
        embedding=_stable_embedding(text),
        bearing_rad=float(hit.bearing_rad),
        range_m=float(hit.range_m),
        score=float(hit.score),
        track_id=track[:128] if track else "",
    )


def ocr_hits_to_detections(
    hits: Sequence[OcrHit],
    *,
    received_monotonic_ns: int,
    source_timestamp_ns: int | None = None,
    sequence: int = 0,
) -> tuple[DetectionMsg, ...]:
    return tuple(
        ocr_hit_to_detection(
            hit,
            received_monotonic_ns=received_monotonic_ns,
            source_timestamp_ns=source_timestamp_ns,
            sequence=sequence + index,
        )
        for index, hit in enumerate(hits)
    )


def ingest_ocr_hits(
    memory: SemanticMemory2D,
    hits: Sequence[OcrHit],
    *,
    robot_x: float,
    robot_y: float,
    robot_yaw_rad: float,
    now_s: float,
    received_monotonic_ns: int,
    source_timestamp_ns: int | None = None,
    sequence: int = 0,
) -> tuple[DetectionMsg, ...]:
    """Convert OCR hits → DetectionMsg → ``SemanticMemory2D.observe_detections``.

    Also observes a human-readable label row (brand / expected text) so
    ``recall("nike")`` works without the ``storefront:`` prefix.
    """

    detections = ocr_hits_to_detections(
        hits,
        received_monotonic_ns=received_monotonic_ns,
        source_timestamp_ns=source_timestamp_ns,
        sequence=sequence,
    )
    memory.observe_detections(
        detections,
        robot_x=robot_x,
        robot_y=robot_y,
        robot_yaw_rad=robot_yaw_rad,
        now_s=now_s,
    )
    # Extra label aliases for brand / raw text recall.
    extras: list[dict[str, object]] = []
    for hit, det in zip(hits, detections, strict=True):
        labels = {
            normalize_sign_text(hit.text).lower(),
            normalize_sign_text(hit.brand).lower() if hit.brand else "",
        }
        world_yaw = robot_yaw_rad + float(det.bearing_rad)
        x = robot_x + math.cos(world_yaw) * float(det.range_m)
        y = robot_y + math.sin(world_yaw) * float(det.range_m)
        for label in labels:
            if not label:
                continue
            extras.append(
                {
                    "entity_id": f"{det.envelope.evidence_id}:{label.replace(' ', '_')}",
                    "label": label,
                    "x": x,
                    "y": y,
                    "confidence": float(det.score),
                    "kind": "object",
                    "class_id": det.class_id,
                    "embedding": list(det.embedding),
                }
            )
    if extras:
        memory.observe(extras, now_s=now_s)
    return detections


def recall_storefront(
    memory: SemanticMemory2D,
    query: str,
    *,
    now_s: float,
) -> tuple[RememberedEntity, ...]:
    """Recall by brand/text query (case-insensitive)."""

    return memory.recall(query, now_s=now_s)
