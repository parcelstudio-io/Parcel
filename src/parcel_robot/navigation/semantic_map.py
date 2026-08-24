from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from parcel_robot.observation.carrier_view import carrier_view

from .base import NavObservation
from .goals import SemanticGoal

if TYPE_CHECKING:
    from parcel_robot.contracts.navigation_snapshot_v2 import NavigationSnapshotV2
    from parcel_robot.contracts.observation_carrier import ObservationCarrierV1


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
    by measurement. See :mod:`parcel_robot.perception.abstention` for why a
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
            if _matches(goal.query, candidate.label, candidate.metadata.get("aliases")):
                candidates.append(candidate)
        # Card A2 (NAV-GLUE) fix 1 — the kind match is STRICT-FIRST, TOLERANT
        # ONLY WHEN STRICT FINDS NOTHING.
        #
        # It used to be plain equality, and NAV-CORE measured what that costs
        # off-oracle: ``goals.semantic_goal_from_directive("bed")`` returns
        # ``kind="region"`` (R10's place-class table), while
        # ``semantic_map.learned_map_candidates`` stamps every row it emits
        # ``kind="object"`` — a hard-coded constant, not a measurement — so all
        # 12 ``bed`` episodes answered ``not_found`` about a place the map was
        # holding the whole time.
        #
        # The fix is here and not at the ingress because the two ``kind``
        # fields answer different questions and only one of them is about the
        # place. The GOAL's kind is a function of the owner's PHRASING: "go to
        # the bed" compiles to ``region``/``inside`` and "sit by the bed" to
        # ``object``/``next_to``, same place, same map row. Stamping the
        # ingress from the place-class table would fix the first sentence and
        # break the second. So the map keeps saying what it saw, the goal keeps
        # saying how the owner wants to arrive, and the join stops requiring
        # them to be the same word.
        #
        # Strict-first is what keeps this ADDITIVE: wherever a same-kind
        # candidate exists the result is byte-identical to the old one, in
        # order and in membership, so no oracle row can move. The relaxation
        # can only turn a ``not_found`` into a candidate, never re-rank a
        # resolution that already had one.
        exact = [item for item in candidates if item.kind == goal.kind]
        candidates = exact or candidates
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
        from parcel_robot.perception.abstention import (
            ABSTAIN_LABEL_DISAGREEMENT,
            OUTCOME_ASK,
            RANKING_MARGIN_LABEL_STRENGTH,
            AbstentionVerdict,
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
    #
    # Card P0-D: that is the right background for the ROBUST-Z estimator, which
    # was fitted on a cosine that scores every place. It is the wrong one for
    # the label-strength estimator, whose question is explicitly "how much
    # stronger than the best ALTERNATIVE", and a place that does not carry the
    # queried label is not an alternative. Measured on the C-3 fixtures: two
    # equally well-observed places both score ``evidence_confidence`` 0.8647, so
    # the whole-map background makes the ratio exactly 1.0 and refuses every
    # query — the same structural zero the robust z had, wearing a new hat. So
    # under that estimator the background IS the matching set, which is what
    # "among matching candidates" means, and non-matching places contribute
    # nothing rather than a spurious tie.
    background: list[float] = []
    # Card P1-D (refutation D-5): the module constant, not a bare literal that
    # could silently stop matching if the mode were ever renamed.
    if getattr(active, "ranking_margin_mode", "") == RANKING_MARGIN_LABEL_STRENGTH:
        background = [float(candidate.confidence) for candidate in candidates]
    else:
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
        # No ``veto=`` here on purpose. Card P1-D, post-verification: an earlier
        # draft passed ``getattr(active, "veto", None)``, which was ALWAYS None
        # because no such attribute exists — so the signal the roster selected
        # never ran on the product path. The gate now resolves the seat the
        # config named (``perception_abstention.resolve_veto``), which means
        # every call site gets it, including ones written after this comment.
    )
    # ------------------------------------------------------------- D-R3 ---
    # Card P1-D. An admission earned only through a SUBSTRING match is not an
    # admission. ``_match_strength`` reports how each candidate met the query;
    # a spelling coincidence ("a coffee shop" ⊃ "shop") may produce a candidate
    # to ASK about but may never authorize motion, because the failure
    # direction here is the dangerous one — the dog drives somewhere it was not
    # asked to go, confidently, having passed every evidence gate on a place
    # that really is well-observed. It is simply the wrong place.
    #
    # Checked AFTER the gate rather than by filtering candidates before it, so
    # the refusal reason is the honest one and the ASK can still name the place.
    if verdict.admitted and verdict.place_id is not None:
        winner = next(
            (c for c in candidates if c.candidate_id == verdict.place_id), None
        )
        if winner is not None and _match_strength(
            goal.query, winner.label, winner.metadata.get("aliases")
        ) not in ADMISSIBLE_MATCHES:
            asking = bool(getattr(active, "ask_below_threshold", False))
            verdict = AbstentionVerdict(
                False,
                verdict.query,
                ABSTAIN_LABEL_DISAGREEMENT,
                verdict.alternatives,
                winner.candidate_id if asking else None,
                {**dict(verdict.signals), "substring_match_only": 1.0},
                OUTCOME_ASK if asking else "",
                winner.label if asking else "",
            )
    try:
        observation.extras["abstention_verdict"] = verdict.as_dict()
    except (AttributeError, TypeError):  # pragma: no cover — read-only extras
        pass
    if not verdict.admitted:
        return []
    return [c for c in candidates if c.candidate_id == verdict.place_id] or candidates


def semantic_candidates_from_observation(
    observation: ObservationCarrierV1,
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

    # Card C-3. The SOURCE axis is decided before a single oracle field is
    # read, so ``oracle`` (the shipping default) reaches the code below by the
    # only path that ever existed and cannot differ from it. Off-oracle the
    # oracle read is not merely discarded — it is never performed, which is the
    # difference between "the learned map drove" and "the learned map agreed".
    source_policy = _active_source()
    if source_policy is not None and source_policy.drives_from_learned_map:
        return learned_map_candidates(observation)

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


#: Card C-3. How fast an evidence-derived confidence saturates, in frames. A
#: place seen once is not a place seen twenty times, and the difference has to
#: survive into the number a downstream threshold reads. Set to the abstention
#: gate's own ``min_evidence_frames`` so the two agree about what "enough
#: observations" means instead of drifting apart; imported rather than retyped.
EVIDENCE_SATURATION_FRAMES = 7.0


def evidence_confidence(entry: Any) -> float:
    """An honest confidence for a learned place. **Never a constant.**

    The oracle stamped ``0.98`` on every row by fiat, which made every candidate
    maximally trusted and every downstream confidence threshold vacuous. This is
    the replacement, and it is built from what the map actually accumulated:

    * **label purity** — the share of this place's own detections that carried
      its label. A place whose detections disagree about what it is has earned
      less than one whose detections agree.
    * **evidence saturation** — ``1 - exp(-frames / N)``, monotone in the number
      of independent frames and bounded below 1. It cannot reach 1.0, because a
      map built from a finite number of looks has not earned certainty.

    Both terms come from persisted counters, so the same entry yields the same
    number in a later session. A seeded defect replaces this with a literal and
    the seed goes red on the variance of the output, not on the value — a
    constant is detectable without agreeing on which constant would be wrong.
    """

    detections = max(0, int(getattr(entry, "detection_count", 0) or 0))
    support = max(0, int(getattr(entry, "label_support", 0) or 0))
    frames = max(0, int(getattr(entry, "evidence_frames", 0) or 0))
    purity = (support / detections) if detections else 0.0
    saturation = 1.0 - math.exp(-frames / EVIDENCE_SATURATION_FRAMES)
    value = purity * saturation
    # Clamp into the SemanticCandidate contract without ever reaching 1.0.
    return max(0.0, min(0.999, value))


def learned_map_candidates(
    observation: ObservationCarrierV1,
    *,
    learned_map: Any = None,
    radius_m: float | None = None,
) -> list[dict[str, Any]]:
    """Card C-3 — semantic candidates from the dog's own map, not the oracle.

    Same payload shape the oracle read produced, so ``ObservationSemanticMap``
    and ``GrounderV2`` consume it unchanged; that identical consumer contract is
    what makes the cutover a source swap rather than a rewrite of the ladder.

    What is deliberately NOT carried across:

    * **the 0.98.** :func:`evidence_confidence` earns the number instead.
    * **the closed label set.** ``metadata['aliases']`` are the entry's own
      admissible names — detector labels and names promoted after k consistent
      visits — never the scene sidecar's declared vocabulary. This is what makes
      the Narnia refusal a property of perception rather than of a list the
      world file happened to ship.
    * **guaranteed reachability.** The oracle asserted ``reachable``; the map
      reports whether the robot's own body has stood near the place, and says
      which source it used.

    An absent or empty map returns ``[]``. That is the honest answer for a robot
    that has not looked yet, and the ladder already knows how to answer UNSEEN.
    """

    active = learned_map if learned_map is not None else active_learned_map()
    if active is None:
        return []
    robot = observation.robot
    try:
        rows = active.around_me(
            float(robot.x),
            float(robot.y),
            float(robot.yaw),
            radius_m=(
                float(radius_m) if radius_m is not None else _default_visibility_range()
            ),
            limit=64,
        )
    except (AttributeError, TypeError, ValueError):
        return []
    by_id = {
        str(getattr(entry, "entry_id", "")): entry
        for entry in getattr(active, "active_entries", lambda: ())()
    }
    candidates: list[dict[str, Any]] = []
    for row in rows:
        entry = by_id.get(str(row.get("entry_id", "")))
        if entry is None:
            continue
        navigability, navigability_source = _navigability(active, entry)
        candidates.append(
            {
                "id": str(entry.entry_id),
                "label": str(entry.label),
                "position": [
                    float(entry.surface_x),
                    float(entry.surface_y),
                    float(entry.surface_z),
                ],
                "confidence": evidence_confidence(entry),
                "kind": "object",
                "source": "online_map",
                # The map does not assert reachability; it reports whether the
                # robot has been able to stand there. PG-3's navigability signal
                # is the gate, and it reads the metadata below.
                "reachable": navigability > 0.0,
                "metadata": {
                    "semantic_source": "learned_map",
                    "aliases": list(row.get("names") or ()),
                    "evidence_frames": int(entry.evidence_frames),
                    "detection_count": int(entry.detection_count),
                    "label_support": int(entry.label_support),
                    "visits": int(getattr(entry, "visits", 0) or 0),
                    "peak_score": float(getattr(entry, "peak_score", 0.0) or 0.0),
                    "hygiene_note": str(getattr(entry, "hygiene_note", "")),
                    "navigability": navigability,
                    "navigability_source": navigability_source,
                    "first_seen_wall_s": float(entry.first_seen_wall_s),
                    "last_seen_wall_s": float(entry.last_seen_wall_s),
                },
            }
        )
    return candidates


def _navigability(active: Any, entry: Any) -> tuple[float, str]:
    try:
        value, source = active.navigability(entry)
        return float(value), str(source)
    except (AttributeError, TypeError, ValueError):
        return 0.0, "unavailable"


def _default_visibility_range() -> float:
    try:
        from parcel_robot.online_map.online_map import DEFAULT_VISIBILITY_RANGE_M

        return float(DEFAULT_VISIBILITY_RANGE_M)
    except (ImportError, TypeError, ValueError):  # pragma: no cover
        return 15.0


def _active_source() -> Any:
    """Resolve the process-default semantic source. ``None`` ⇒ oracle.

    Soft-import for the same reason ``_active_chain`` is soft: a frozen BARN
    bundle ships a ``parcel_robot`` tree that predates this package. ``None``
    means "no source axis", which is the pre-C-3 read and is exactly what
    ``oracle`` produces anyway.
    """

    try:
        from parcel_robot.perception_source.selection import active_semantic_source
    except ImportError:  # pragma: no cover — frozen BARN bundle path
        return None
    return active_semantic_source()


def active_learned_map() -> Any:
    """The process-installed ``OnlineSemanticMap``, or ``None``."""

    try:
        from parcel_robot.perception_source.selection import active_learned_map as _map
    except ImportError:  # pragma: no cover — frozen BARN bundle path
        return None
    return _map()


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


def lidar_payload_from_observation(observation: ObservationCarrierV1) -> list[dict[str, Any]]:
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


#: How a query met a candidate's label. Card P1-D, refutation D-R3.
#:
#: The distinction exists because these three are not the same claim and the
#: pre-P1-D code returned one bool for all of them:
#:
#:   ``exact``      the query IS this label (after normalization)
#:   ``alias``      a curated synonym said so — ``city_semantics.CLASS_ALIASES``
#:                  or the candidate's own alias list, or SigLIP-2's cosine
#:   ``substring``  one string happens to contain the other. "a coffee shop"
#:                  contains "shop"; "streetlight" contains "tree"... no, but
#:                  "tree" ⊂ "street", which is how a lamppost once matched a
#:                  tree. This is a COINCIDENCE OF SPELLING and it is evidence
#:                  of nothing.
#:   ``none``       no relation
MATCH_EXACT = "exact"
MATCH_ALIAS = "alias"
MATCH_SUBSTRING = "substring"
MATCH_NONE = "none"

#: Match strengths that may reach an ADMIT. A substring hit may produce a
#: candidate — so the dog can ask "did you mean the shop?" — but it may never
#: authorize motion on its own. See :func:`_abstention_filtered`.
ADMISSIBLE_MATCHES: frozenset[str] = frozenset({MATCH_EXACT, MATCH_ALIAS})


def _matches(query: str, label: str, aliases: Any) -> bool:
    """Does this candidate answer the query at all? (Any strength.)

    Kept as the bool it always was so the candidate-gathering call site is
    unchanged: a substring hit still PRODUCES a candidate. What changed in card
    P1-D is that producing a candidate and being allowed to drive to it are now
    two different questions — see :func:`_match_strength` and D-R3.
    """

    return _match_strength(query, label, aliases) != MATCH_NONE


def _match_strength(query: str, label: str, aliases: Any) -> str:
    """Match a query against one candidate label (plus that label's aliases).

    Important: do **not** inject other vocabulary classes into ``texts`` just
    because the query names a class — that made every candidate match
    ``\"sidewalk\"`` / ``\"lamppost\"`` and collapsed grounding to AMBIGUOUS.

    Card P1-D (refutation D-R3, ``scrum/20260822/WAVE_P0_VERIFICATION_FABLE.md``):
    returns HOW it matched, not just whether. The substring fallback below is on
    the mission path whenever SigLIP-2 weights are absent, and it admitted
    ``"a coffee shop"`` against a map entry labelled ``shop`` — an admission,
    i.e. the dog drives somewhere it was not asked to go. The fallback is kept
    (deleting it would refuse real synonyms this deployment has no embedder for)
    and demoted: a substring hit is at most an ASK.
    """

    normalized_query = _normalized(query)
    if not normalized_query:
        return MATCH_NONE
    # "the bench" IS the bench. Determiners are stripped before the identity
    # test — otherwise the owner's own natural phrasing would be demoted to a
    # substring hit and the dog would ask about a place it can name exactly.
    # Same determiner list ``perception_abstention.detector_prompts_for`` uses.
    bare_query = _without_determiner(query)
    if bare_query and bare_query == _without_determiner(label):
        return MATCH_EXACT
    texts = [label]
    if isinstance(aliases, (list, tuple)):
        texts.extend(str(alias) for alias in aliases[:16])
    # The candidate's OWN alias list is curated data, exactly like CLASS_ALIASES
    # below, so a whole-string hit against it is a real synonym.
    if any(_without_determiner(text) == bare_query for text in texts):
        return MATCH_ALIAS
    try:
        from parcel_robot.perception.city_semantics import CLASS_ALIASES

        for class_label, class_aliases in CLASS_ALIASES.items():
            class_norm = _without_determiner(class_label)
            label_in_class = class_norm == _without_determiner(label) or any(
                _normalized(alias) == _normalized(label) for alias in class_aliases
            )
            if not label_in_class:
                continue
            texts.append(class_label)
            texts.extend(class_aliases)
            # Query is this class name or one of its aliases → accept (a real
            # synonym via the curated alias table, not a substring coincidence).
            if class_norm == bare_query or any(
                _without_determiner(alias) == bare_query for alias in class_aliases
            ):
                return MATCH_ALIAS
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
        hit = matcher.match(str(query), [str(t) for t in texts])
        return MATCH_ALIAS if hit is not None else MATCH_NONE
    # Weights absent: substring containment, then the matcher's own loud string
    # fallback. Card P1-D: both are reported as MATCH_SUBSTRING rather than as
    # an accept. The set of candidates this produces is UNCHANGED — every
    # containment that matched before still matches — and what changed is that
    # the gate above can now tell a spelling coincidence from a synonym.
    for text in texts:
        normalized_text = _normalized(text)
        if normalized_text and (
            normalized_query in normalized_text or normalized_text in normalized_query
        ):
            return MATCH_SUBSTRING
    if matcher is not None:
        hit = matcher.match(str(query), [str(t) for t in texts])
        if hit is not None:
            return MATCH_SUBSTRING
    return MATCH_NONE


def _normalized(value: object) -> str:
    return "".join(re.findall(r"[a-z0-9]+", str(value).lower()))


#: Determiners that carry no referent of their own. Card P1-D: stripped before
#: the exact/alias identity tests so "the bench" is the bench, while possessives
#: ("my office") and proper nouns ("Narnia") are left alone — rewriting those
#: would be a guess about what the owner meant.
_DETERMINERS = ("a", "an", "the")


def _without_determiner(value: object) -> str:
    words = re.findall(r"[a-z0-9]+", str(value).lower())
    while words and words[0] in _DETERMINERS:
        words = words[1:]
    return "".join(words)


def semantic_candidates_from_snapshot(
    snapshot: NavigationSnapshotV2, *, chain: Any = None
) -> list[dict[str, Any]]:
    """Card A4's V2 entry point for the semantic-candidate ingress.

    ``SemanticObservationV1`` carries the evidence id that produced it, which
    the carrier shape could not; the re-projection drops that link, so reading
    ``snapshot.semantics`` natively is the cutover this path is waiting for.
    """

    return semantic_candidates_from_observation(carrier_view(snapshot), chain=chain)


def lidar_payload_from_snapshot(snapshot: NavigationSnapshotV2) -> list[dict[str, Any]]:
    """Card A4's V2 entry point for the LiDAR payload."""

    return lidar_payload_from_observation(carrier_view(snapshot))
