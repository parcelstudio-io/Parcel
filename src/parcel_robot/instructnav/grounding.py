"""Typed grounding outcomes and Grounder v2 (pure scoring/API).

Hillclimb rung 2 / K4: frustum → memory order with SigLIP-2 (or string
fallback) embedding match. Outcomes are RESOLVED / MEMORY_HIT / UNSEEN /
AMBIGUOUS — recovery (scan/search/clarify) is the caller's job.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from parcel_robot.instructnav.memory import RememberedEntity
from parcel_robot.instructnav.relations import nearest_point_in_region
from parcel_robot.instructnav.siglip import SIGLIP2_MATCH_THRESHOLD, SigLIP2Matcher


class GroundingOutcome(str, Enum):
    RESOLVED = "RESOLVED"
    MEMORY_HIT = "MEMORY_HIT"
    UNSEEN = "UNSEEN"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class GroundingResult:
    outcome: GroundingOutcome
    candidate: Mapping[str, Any] | None
    candidates: tuple[Mapping[str, Any], ...]
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "candidate": dict(self.candidate) if self.candidate is not None else None,
            "candidate_count": len(self.candidates),
            "detail": self.detail,
        }


def resolve_grounding(
    *,
    frustum: Sequence[Mapping[str, Any]],
    memory: Sequence[Mapping[str, Any]],
    ambiguity_margin: float = 0.05,
    distance_ambiguity_m: float = 0.75,
    interchangeable: bool = False,
) -> GroundingResult:
    """Apply the frustum → memory order; search/refusal are caller recovery.

    Ambiguity: two top candidates within ``ambiguity_margin`` confidence **and**
    within ``distance_ambiguity_m`` range of each other. Equal-confidence GT
    landmarks at clearly different ranges resolve to the nearer (already sorted)
    hit — otherwise every dual lamppost/bench scene would be AMBIGUOUS.
    """

    frustum_hits = tuple(frustum)
    if _is_ambiguous(
        frustum_hits, ambiguity_margin, distance_ambiguity_m, interchangeable=interchangeable
    ):
        return GroundingResult(
            outcome=GroundingOutcome.AMBIGUOUS,
            candidate=None,
            candidates=frustum_hits,
            detail="ambiguous_frustum_match",
        )
    if frustum_hits:
        return GroundingResult(
            outcome=GroundingOutcome.RESOLVED,
            candidate=frustum_hits[0],
            candidates=frustum_hits,
            detail="frustum",
        )
    memory_hits = tuple(memory)
    if _is_ambiguous(
        memory_hits, ambiguity_margin, distance_ambiguity_m, interchangeable=interchangeable
    ):
        return GroundingResult(
            outcome=GroundingOutcome.AMBIGUOUS,
            candidate=None,
            candidates=memory_hits,
            detail="ambiguous_memory_match",
        )
    if memory_hits:
        return GroundingResult(
            outcome=GroundingOutcome.MEMORY_HIT,
            candidate=memory_hits[0],
            candidates=memory_hits,
            detail="memory",
        )
    return GroundingResult(
        outcome=GroundingOutcome.UNSEEN,
        candidate=None,
        candidates=(),
        detail="unseen",
    )


@dataclass(frozen=True)
class GrounderV2:
    """Pure Grounder v2: score detections + memory, emit typed outcomes.

    Does not own sensors or PlanIR — scores mappings / DetectionMsg-shaped
    dicts / RememberedEntity rows and returns :class:`GroundingResult`.
    """

    matcher: SigLIP2Matcher | None = None
    #: Real-embedding cosine gate. Fed to an auto-built matcher as its
    #: ``real_threshold``; inert on the weights-absent path (string fallback
    #: ignores it), so it never moves a frozen row. Recalibrate on real weights.
    match_threshold: float = SIGLIP2_MATCH_THRESHOLD
    ambiguity_margin: float = 0.05
    distance_ambiguity_m: float = 0.75
    #: Card PG-3 calibrated abstention, **OFF by default**. ``None`` consults the
    #: process-default policy, which ships disabled; a disabled policy is
    #: short-circuited before any field is read, so the shipping path is the
    #: pre-PG-3 path by construction. ``detector_support`` is the label head's
    #: own answer for the query term and is required when the policy is on —
    #: absent, it refuses, because not asking is not evidence of absence.
    abstention: Any = None

    def ground(
        self,
        query: str,
        *,
        detections: Sequence[Any] = (),
        memory: Sequence[Any] = (),
        robot_xy: tuple[float, float] | None = None,
        robot_yaw_rad: float = 0.0,
        interchangeable: bool = False,
        detector_support: Mapping[str, Any] | None = None,
    ) -> GroundingResult:
        """Score live detections then memory; UNSEEN when neither matches."""

        q = " ".join(str(query).strip().split())
        if not q:
            return GroundingResult(
                outcome=GroundingOutcome.UNSEEN,
                candidate=None,
                candidates=(),
                detail="empty_query",
            )
        matcher = self.matcher or SigLIP2Matcher(real_threshold=self.match_threshold)
        frustum = _rank_candidates(
            query=q,
            items=detections,
            matcher=matcher,
            source="detection",
            robot_xy=robot_xy,
            robot_yaw_rad=robot_yaw_rad,
        )
        mem = _rank_candidates(
            query=q,
            items=memory,
            matcher=matcher,
            source="memory",
            robot_xy=robot_xy,
            robot_yaw_rad=robot_yaw_rad,
        )
        result = resolve_grounding(
            frustum=frustum,
            memory=mem,
            ambiguity_margin=self.ambiguity_margin,
            distance_ambiguity_m=self.distance_ambiguity_m,
            interchangeable=interchangeable,
        )
        return _abstain_if_unsupported(
            self.abstention, q, result, frustum + mem, detector_support
        )


def _abstain_if_unsupported(
    policy: Any,
    query: str,
    result: GroundingResult,
    candidates: Sequence[Mapping[str, Any]],
    detector_support: Mapping[str, Any] | None,
) -> GroundingResult:
    """PG-3: turn a resolved-but-unsupported grounding into an honest UNSEEN.

    Only ever makes the outcome *more* conservative: a RESOLVED or MEMORY_HIT
    that perception cannot support becomes UNSEEN, whose recovery is the ask.
    AMBIGUOUS and UNSEEN are returned untouched — this gate answers "is there
    anything of this kind here at all", and it has nothing to add to "there are
    two of them" or "there are none".
    """

    if result.outcome not in (GroundingOutcome.RESOLVED, GroundingOutcome.MEMORY_HIT):
        return result
    try:
        from parcel_robot.perception_abstention import (
            active_abstention_policy,
            assess_place_query,
            detector_prompts_for,
            detector_support_from_mapping,
            place_evidence_from_mapping,
        )
    except ImportError:  # pragma: no cover — frozen BARN bundle path
        return result
    active = policy if policy is not None else active_abstention_policy()
    if not getattr(active, "enabled", False):
        return result
    prompts = detector_prompts_for(query)
    support = detector_support_from_mapping(detector_support, prompts)
    places = []
    for index, item in enumerate(candidates):
        meta = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else item
        places.append(
            place_evidence_from_mapping(
                meta,
                support.term,
                place_id=str(item.get("id") or f"candidate:{index}"),
                label=str(item.get("label") or item.get("class_id") or "place"),
                x=float(item.get("x") or 0.0),
                y=float(item.get("y") or 0.0),
                z=float(item.get("z") or 0.0),
                similarity=float(item.get("confidence") or 0.0),
            )
        )
    verdict = assess_place_query(query, support=support, places=places, policy=active)
    if verdict.admitted:
        return result
    return GroundingResult(
        outcome=GroundingOutcome.UNSEEN,
        candidate=None,
        candidates=(),
        detail=f"abstained:{verdict.reason}",
    )


def _rank_candidates(
    *,
    query: str,
    items: Sequence[Any],
    matcher: SigLIP2Matcher,
    source: str,
    robot_xy: tuple[float, float] | None,
    robot_yaw_rad: float,
) -> tuple[dict[str, Any], ...]:
    scored: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        candidate = _as_candidate_dict(
            item,
            source=source,
            robot_xy=robot_xy,
            robot_yaw_rad=robot_yaw_rad,
            index=index,
        )
        if candidate is None:
            continue
        label = str(candidate.get("label") or candidate.get("class_id") or "")
        if not label:
            continue
        match = matcher.match(query, [label])
        if match is None:
            if matcher.available:
                # A2: real SigLIP-2 already decided this label is not the queried
                # class. DELETE the cross-class substring rescue — it was the path
                # that let "streetlight" commit a "tree" ("tree" ⊂ "s-tree-tlight")
                # and "the tree" commit a lamppost via its "streetlight" alias.
                # Gated: weights-absent CI keeps the exact string rescue below,
                # byte-identical to the frozen baseline.
                continue
            # Weights absent: exact/normalized string fallback, unchanged.
            if _norm_token(query) != _norm_token(label) and _norm_token(label) not in _norm_token(
                query
            ):
                continue
            match_score = float(candidate.get("score", candidate.get("confidence", 0.5)))
            match_source = "string_exact"
        else:
            match_score = float(match.score) * float(
                candidate.get("score", candidate.get("confidence", 1.0))
            )
            match_source = match.source
        # Embedding cosine against stored vector when both sides present. A2: the
        # query side is the real text embedding when weights are present, and the
        # char-hash (byte-identical to today) when they are absent.
        emb = candidate.get("embedding")
        if isinstance(emb, (list, tuple)) and emb:
            query_emb = matcher.embed_text(query) if matcher.available else _hash_embed(query)
            if query_emb is not None and len(query_emb) == len(emb):
                cos = _cosine(query_emb, tuple(float(v) for v in emb))
                match_score = max(match_score, 0.5 * (1.0 + cos))
        candidate = {
            **candidate,
            "confidence": max(0.0, min(1.0, match_score)),
            "match_source": match_source,
        }
        scored.append(candidate)
    scored.sort(
        key=lambda c: (
            -float(c["confidence"]),
            float(c["distance_m"]) if c.get("distance_m") is not None else 1e9,
            str(c.get("id") or ""),
        )
    )
    return tuple(scored)


def _as_candidate_dict(
    item: Any,
    *,
    source: str,
    robot_xy: tuple[float, float] | None,
    robot_yaw_rad: float,
    index: int,
) -> dict[str, Any] | None:
    if isinstance(item, RememberedEntity):
        distance_m = None
        if robot_xy is not None:
            distance_m = _region_aware_memory_distance_m(item, robot_xy)
        return {
            "id": item.entity_id,
            "label": item.label,
            "class_id": item.class_id or item.label,
            "x": item.x,
            "y": item.y,
            "confidence": item.confidence,
            "score": item.confidence,
            "embedding": item.embedding,
            "distance_m": distance_m,
            "source": source,
        }
    if hasattr(item, "class_id") and hasattr(item, "bearing_rad"):
        # DetectionMsg-shaped
        class_id = str(item.class_id)
        bearing = float(item.bearing_rad)
        range_m = float(item.range_m)
        score = float(item.score)
        embedding = tuple(float(v) for v in item.embedding)
        track_id = str(getattr(item, "track_id", "") or "")
        evidence_id = str(getattr(getattr(item, "envelope", None), "evidence_id", "") or "")
        x = y = None
        if robot_xy is not None and all(math.isfinite(v) for v in (*robot_xy, robot_yaw_rad)):
            yaw = robot_yaw_rad + bearing
            x = robot_xy[0] + math.cos(yaw) * range_m
            y = robot_xy[1] + math.sin(yaw) * range_m
        return {
            "id": track_id or evidence_id or f"{source}:{index}:{class_id}",
            "label": class_id,
            "class_id": class_id,
            "x": x,
            "y": y,
            "confidence": score,
            "score": score,
            "embedding": embedding,
            "distance_m": range_m,
            "bearing_rad": bearing,
            "source": source,
        }
    if isinstance(item, Mapping):
        label = str(item.get("label") or item.get("class_id") or "")
        if not label:
            return None
        distance_m = item.get("distance_m")
        if distance_m is not None:
            try:
                distance_m = float(distance_m)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                distance_m = None
        elif robot_xy is not None and "x" in item and "y" in item:
            try:
                distance_m = math.hypot(
                    float(item["x"]) - robot_xy[0],  # type: ignore[arg-type]
                    float(item["y"]) - robot_xy[1],  # type: ignore[arg-type]
                )
            except (TypeError, ValueError):
                distance_m = None
        elif "bearing_rad" in item and "range_m" in item:
            try:
                distance_m = float(item["range_m"])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                distance_m = None
        conf = item.get("confidence", item.get("score", 0.5))
        try:
            conf_f = float(conf)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            conf_f = 0.5
        emb = item.get("embedding")
        embedding = tuple(float(v) for v in emb) if isinstance(emb, (list, tuple)) else None
        return {
            "id": str(item.get("id") or item.get("entity_id") or f"{source}:{index}"),
            "label": label,
            "class_id": str(item.get("class_id") or label),
            "x": item.get("x"),
            "y": item.get("y"),
            "confidence": conf_f,
            "score": conf_f,
            "embedding": embedding,
            "distance_m": distance_m,
            "source": source,
        }
    return None


def _is_ambiguous(
    hits: tuple[Mapping[str, Any], ...],
    ambiguity_margin: float,
    distance_ambiguity_m: float,
    *,
    interchangeable: bool = False,
) -> bool:
    if len(hits) < 2:
        return False
    if interchangeable:
        # Stuff-class instances (region goals: sidewalk, grass, road) are
        # interchangeable — "go to the sidewalk" is satisfied by the nearest
        # sidewalk, exactly as the region channel treats them as unbounded
        # stuff rather than countable things. Without this, any street with
        # two sidewalks makes every region directive AMBIGUOUS after a scan.
        # Ambiguity still applies across DISTINCT labels (sidewalk vs
        # crosswalk both matching a vague query).
        labels = {
            str(hit.get("class_id") or hit.get("label") or "") for hit in hits[:2]
        }
        if len(labels) == 1:
            return False
    c0 = float(hits[0].get("confidence", 0.0))
    c1 = float(hits[1].get("confidence", 0.0))
    if abs(c0 - c1) > ambiguity_margin:
        return False
    d0 = _candidate_distance_m(hits[0])
    d1 = _candidate_distance_m(hits[1])
    if d0 is None or d1 is None:
        # No range signal — confidence tie stays ambiguous.
        return True
    return abs(d0 - d1) <= distance_ambiguity_m


def _region_aware_memory_distance_m(
    item: RememberedEntity,
    robot_xy: tuple[float, float],
) -> float:
    """Boundary distance for remembered REGIONS, centroid for objects.

    Arbitration 2026-08-07: "the sidewalk" ranks by the distance to the
    region you can step onto, not to a centroid that may sit across the
    street — matching the K0 polygon authority and the frustum-path fix in
    navigation/instructnav_recovery.py.
    """

    if item.kind == "region" and item.polygon and len(item.polygon) >= 3:
        try:
            nearest = nearest_point_in_region(item.polygon, robot_xy, inset_m=0.0)
        except ValueError:
            pass
        else:
            return math.hypot(nearest[0] - robot_xy[0], nearest[1] - robot_xy[1])
    return math.hypot(item.x - robot_xy[0], item.y - robot_xy[1])


def _candidate_distance_m(candidate: Mapping[str, Any]) -> float | None:
    if "distance_m" in candidate and candidate["distance_m"] is not None:
        try:
            value = float(candidate["distance_m"])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return value if value >= 0.0 else None
    return None


def honest_not_found_reply(query: str, *, scanned: bool, searched: bool) -> str:
    """Refusal/report text that names the recovery attempted."""

    label = " ".join(str(query).strip().split()) or "that"
    if searched:
        return (
            f"I looked around and searched nearby but couldn't find a {label}. "
            "I am stopping here."
        )
    if scanned:
        return (
            f"I looked around and couldn't find a {label} nearby. "
            "I am stopping here."
        )
    return (
        f"I couldn't form a safe, grounded plan for {label!r} yet. "
        "Please clarify the task or let me inspect the scene again."
    )


def _norm_token(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _hash_embed(text: str, dim: int = 32) -> tuple[float, ...]:
    """Deterministic offline embed (same family as siglip string fallback)."""

    values = [0.0] * dim
    token = _norm_token(text) or "empty"
    for index, ch in enumerate(token):
        values[index % dim] += (ord(ch) % 31) / 31.0
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return tuple(v / norm for v in values)


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))
