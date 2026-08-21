from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from .base import NavObservation
from .goals import SemanticGoal

if TYPE_CHECKING:
    from parcel_robot.backends.base import SimObservation


@dataclass(frozen=True)
class SemanticCandidate:
    candidate_id: str
    label: str
    x: float
    y: float
    z: float = 0.0
    confidence: float = 0.0
    kind: str = "object"
    polygon: tuple[tuple[float, float], ...] = ()
    source: str = "perception"
    observed_at: float | None = None
    reachable: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.z, self.confidence)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("semantic candidate values must be finite")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("semantic candidate confidence must be between zero and one")
        if not self.candidate_id or len(self.candidate_id) > 128:
            raise ValueError("semantic candidate id is invalid")
        if not self.label or len(self.label) > 160:
            raise ValueError("semantic candidate label is invalid")
        if self.kind not in {"object", "region"}:
            raise ValueError("semantic candidate kind is invalid")
        if not isinstance(self.reachable, bool):
            raise TypeError("semantic candidate reachable must be a boolean")
        if self.observed_at is not None and not math.isfinite(self.observed_at):
            raise ValueError("semantic candidate observation time must be finite")
        if any(not math.isfinite(axis) for point in self.polygon for axis in point):
            raise ValueError("semantic candidate polygon must be finite")


class SemanticMap(Protocol):
    def query(self, goal: SemanticGoal, observation: NavObservation) -> list[SemanticCandidate]: ...


@dataclass(frozen=True)
class ObservationSemanticMap:
    """Read validated semantic candidates produced by an on-robot perception adapter.

    ``abstention`` is card PG-3's calibrated abstention gate and is **OFF by
    default** — ``None`` consults the process-default policy, which ships
    disabled, and a disabled policy is short-circuited before a single field is
    read, so the shipping path is the pre-PG-3 path by construction rather than
    by measurement. See :mod:`parcel_robot.perception_abstention` for why a
    cosine ranking cannot say "I don't know" and what replaces it.
    """

    abstention: Any = None

    def query(self, goal: SemanticGoal, observation: NavObservation) -> list[SemanticCandidate]:
        raw = observation.extras.get("semantic_candidates", [])
        if not isinstance(raw, (list, tuple)):
            return []
        candidates: list[SemanticCandidate] = []
        for index, item in enumerate(raw[:64]):
            try:
                candidate = _candidate(item, index)
            except (KeyError, TypeError, ValueError):
                continue
            if candidate.kind == goal.kind and _matches(
                goal.query, candidate.label, candidate.metadata.get("aliases")
            ):
                candidates.append(candidate)
        robot_x, robot_y = observation.position[:2]
        ordered = sorted(
            candidates,
            key=lambda item: (
                -item.confidence,
                math.hypot(item.x - robot_x, item.y - robot_y),
                item.candidate_id,
            ),
        )
        return _abstention_filtered(self.abstention, goal, observation, ordered)


def _abstention_filtered(
    policy: Any,
    goal: SemanticGoal,
    observation: NavObservation,
    candidates: list[SemanticCandidate],
) -> list[SemanticCandidate]:
    """PG-3: refuse rather than return a place perception cannot support.

    Fail-CLOSED and empty-handed: a refusal returns ``[]``, which is exactly the
    UNSEEN the ladder already knows how to answer honestly (R20's ask). The
    verdict is recorded on ``observation.extras['abstention_verdict']`` so the
    reason is auditable rather than being inferred from an empty list.
    """

    try:
        from parcel_robot.perception_abstention import (
            active_abstention_policy,
            assess_place_query,
            detector_prompts_for,
            detector_support_from_mapping,
            place_evidence_from_mapping,
        )
    except ImportError:  # pragma: no cover — frozen BARN bundle path
        return candidates
    active = policy if policy is not None else active_abstention_policy()
    if not getattr(active, "enabled", False):
        return candidates
    prompts = detector_prompts_for(goal.query)
    support = detector_support_from_mapping(
        observation.extras.get("detector_support"), prompts
    )
    places = [
        place_evidence_from_mapping(
            candidate.metadata,
            support.term,
            place_id=candidate.candidate_id,
            label=candidate.label,
            x=candidate.x,
            y=candidate.y,
            z=candidate.z,
            similarity=candidate.confidence,
        )
        for candidate in candidates
    ]
    # The ranking margin's background is the WHOLE map, not the label-matching
    # subset. Scoring a query against only the candidates that already matched
    # it would ask "does this stand out from things like itself", which a single
    # match answers trivially and which is not the question.
    background: list[float] = []
    for item in observation.extras.get("semantic_candidates", []) or []:
        if isinstance(item, Mapping):
            value = item.get("confidence", item.get("score"))
        else:
            value = getattr(item, "confidence", None)
        try:
            background.append(float(value))
        except (TypeError, ValueError):
            continue
    verdict = assess_place_query(
        goal.query,
        support=support,
        places=places,
        policy=active,
        map_similarities=background or None,
    )
    try:
        observation.extras["abstention_verdict"] = verdict.as_dict()
    except (AttributeError, TypeError):  # pragma: no cover — read-only extras
        pass
    if not verdict.admitted:
        return []
    return [c for c in candidates if c.candidate_id == verdict.place_id] or candidates


def semantic_candidates_from_observation(
    observation: SimObservation,
    *,
    chain: Any = None,
) -> list[dict[str, Any]]:
    """Convert validated camera/depth tracks into the navigator's typed payload.

    Stratum 2: this is the **one** semantic ingress on the mission path, and it
    runs the ``detection_adapter`` perception chain. ``chain=None`` consults the
    process-default chain, which is tier T0 (pass-through) unless a harness has
    installed otherwise — so the shipping path is byte-identical to the oracle
    read this replaced, by construction rather than by measurement.
    """

    candidates: list[dict[str, Any]] = [
        {
            "id": region.region_id,
            "label": region.label,
            "polygon": [list(point) for point in region.polygon],
            "confidence": region.confidence,
            "kind": "region",
            "source": region.source,
            "reachable": region.reachable,
            "metadata": dict(region.metadata or {}),
        }
        for region in observation.semantic_regions
    ]
    candidates.extend(
        {
            "id": item.object_id,
            "label": item.label,
            "position": list(item.position),
            "confidence": item.confidence,
            "kind": "object",
            "source": item.source,
            "reachable": item.reachable,
            "metadata": dict(item.metadata or {}),
        }
        for item in observation.semantic_objects
    )
    active = chain if chain is not None else _active_chain()
    if active is None:
        return candidates
    robot = observation.robot
    return active.process(
        candidates,
        robot_x=float(robot.x),
        robot_y=float(robot.y),
        robot_yaw_rad=float(robot.yaw),
    )


def _active_chain() -> Any:
    """Resolve the process-default perception chain.

    Soft: frozen BARN bundles ship a ``parcel_robot`` tree that predates
    ``detection_adapter``, and this module is reachable from a v8 replacement
    source. ``None`` means "no chain", which is the pre-stratum-2 read and is
    exactly what T0 would have produced anyway.
    """

    try:
        from parcel_robot.detection_adapter.perception_chain import (
            active_perception_chain,
        )
    except ImportError:  # pragma: no cover — frozen BARN bundle path
        return None
    return active_perception_chain()


def lidar_payload_from_observation(observation: SimObservation) -> list[dict[str, Any]]:
    return [
        {
            "id": item.obstacle_id,
            "distance_m": item.distance_m,
            "bearing_rad": item.bearing_rad,
        }
        for item in observation.lidar_obstacles
    ]


def _candidate(item: Any, index: int) -> SemanticCandidate:
    if isinstance(item, SemanticCandidate):
        return item
    if not isinstance(item, dict):
        raise TypeError("candidate must be a mapping")
    polygon_raw = item.get("polygon") or []
    if not isinstance(polygon_raw, (list, tuple)) or len(polygon_raw) > 256:
        raise TypeError("candidate polygon is invalid")
    polygon = tuple((float(point[0]), float(point[1])) for point in polygon_raw)
    center = item.get("position") or item.get("centroid")
    if center is None and polygon:
        center = (
            sum(point[0] for point in polygon) / len(polygon),
            sum(point[1] for point in polygon) / len(polygon),
            0.0,
        )
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        raise TypeError("candidate requires a position or polygon")
    metadata = item.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise TypeError("candidate metadata must be a mapping")
    reachable = item.get("reachable", True)
    if not isinstance(reachable, bool):
        raise TypeError("candidate reachable must be a boolean")
    kind = item.get("kind", "object")
    if kind not in {"object", "region"}:
        raise ValueError("candidate kind is invalid")
    return SemanticCandidate(
        candidate_id=str(item.get("id") or f"candidate-{index}"),
        label=str(item["label"]),
        x=float(center[0]),
        y=float(center[1]),
        z=float(center[2]) if len(center) > 2 else 0.0,
        confidence=float(item.get("confidence", 0.0)),
        kind=kind,
        polygon=polygon,
        source=str(item.get("source", "perception")),
        observed_at=(float(item["observed_at"]) if item.get("observed_at") is not None else None),
        reachable=reachable,
        metadata=dict(metadata),
    )


_SIGLIP_MATCHER: Any = None
_SIGLIP_INIT = False


def _siglip_matcher() -> Any:
    """Lazy SigLIP seam — loud-degrades once when weights are missing."""

    global _SIGLIP_MATCHER, _SIGLIP_INIT
    if _SIGLIP_INIT:
        return _SIGLIP_MATCHER
    _SIGLIP_INIT = True
    try:
        from parcel_robot.instructnav.siglip import SigLIP2Matcher

        _SIGLIP_MATCHER = SigLIP2Matcher()
    except Exception:  # noqa: BLE001 — keep grounder online if seam fails
        _SIGLIP_MATCHER = None
    return _SIGLIP_MATCHER


def _matches(query: str, label: str, aliases: Any) -> bool:
    """Match a query against one candidate label (plus that label's aliases).

    Important: do **not** inject other vocabulary classes into ``texts`` just
    because the query names a class — that made every candidate match
    ``\"sidewalk\"`` / ``\"lamppost\"`` and collapsed grounding to AMBIGUOUS.
    """

    normalized_query = _normalized(query)
    if not normalized_query:
        return False
    texts = [label]
    if isinstance(aliases, (list, tuple)):
        texts.extend(str(alias) for alias in aliases[:16])
    try:
        from parcel_robot.city_semantics import CLASS_ALIASES

        for class_label, class_aliases in CLASS_ALIASES.items():
            class_norm = _normalized(class_label)
            label_in_class = class_norm == _normalized(label) or any(
                _normalized(alias) == _normalized(label) for alias in class_aliases
            )
            if not label_in_class:
                continue
            texts.append(class_label)
            texts.extend(class_aliases)
            # Query is this class name or one of its aliases → accept (a real
            # synonym via the curated alias table, not a substring coincidence).
            if class_norm == normalized_query or any(
                _normalized(alias) == normalized_query for alias in class_aliases
            ):
                return True
    except ImportError:
        pass
    # SigLIP-2 embedding glue (N-C1 / A2). Missing weights → loud string_fallback
    # inside the matcher (U25). Only score against this candidate's label-local
    # texts. Never inject other vocabulary classes into ``texts``.
    matcher = _siglip_matcher()
    if matcher is not None and matcher.available:
        # A2: real SigLIP-2 present. Identity is decided by neural cosine — NO
        # substring containment, which is the path that let "tree" match a
        # lamppost via its "streetlight" alias ("tree" ⊂ "street"). This is the
        # semantic_map half of the cross-class false-positive deletion.
        return matcher.match(str(query), [str(t) for t in texts]) is not None
    # Weights absent: byte-identical to the pre-neural path — substring
    # containment first, then the matcher's own loud string fallback.
    for text in texts:
        normalized_text = _normalized(text)
        if normalized_text and (
            normalized_query in normalized_text or normalized_text in normalized_query
        ):
            return True
    if matcher is not None:
        hit = matcher.match(str(query), [str(t) for t in texts])
        if hit is not None:
            return True
    return False


def _normalized(value: object) -> str:
    return "".join(re.findall(r"[a-z0-9]+", str(value).lower()))
