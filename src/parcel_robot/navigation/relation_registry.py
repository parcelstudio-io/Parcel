"""RelationSpec registry — one registered unit per spatial relation (stratum 3).

Before this module the vocabulary of a spatial relation was spread across three
surfaces that had to be edited together and could silently disagree: the
inline preposition alternations in :mod:`parcel_robot.navigation.goals`, the
goal-region builders in :mod:`parcel_robot.instructnav.scoring`, and the
per-relation branches scattered through the pipeline and the scorer. This
module is the *lookup layer* that names them as one unit each:

    name · aliases · anchor kinds · frame-of-reference policy ·
    predicate · goal-region builder

**It adds no geometry.** Every registered relation delegates to the existing K0
builder in ``instructnav.scoring``, which stays the single arrival authority
(``object_near_goal_region``, ``object_next_to_goal_region``,
``object_towards_goal_region``, ``region_inside_goal_region``,
``owner_anchored_goal_region``). The predicate is ``GoalRegion.contains`` —
literally the same call the scorer makes — so planning and K0 verification can
never drift apart by construction rather than by convention.

Registering a new relation is one :func:`register_relation` call with a builder
(QSRlib precedent: a relation is data, not a code path). The registry is
fail-closed: duplicate names and aliases already owned by another relation are
rejected at registration time.

**What this module is NOT.** It is not an ontology engine and it does not
decide *which* relation a directive means — that stays with the deterministic
grammar in ``goals.py``, which now reads its preposition alternations from
here instead of keeping its own copy.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.instructnav.scoring import (
    NEXT_TO_BAND_M,
    TOWARDS_BAND_M,
    GoalRegion,
    object_near_goal_region,
    object_next_to_goal_region,
    object_towards_goal_region,
    owner_anchored_goal_region,
    region_inside_goal_region,
)

#: Anchor kinds a relation may bind to. ``owner`` is deliberately distinct from
#: ``object``: the owner is a tracked entity on the owner channel, never a
#: semantic-map object (backlog N12 — one authority for "the owner").
ANCHOR_KINDS: frozenset[str] = frozenset({"object", "region", "owner"})

#: Frame-of-reference policy (the SLOOP / Sr3D distinction). ``absolute`` needs
#: no viewpoint; ``relative`` is resolved from the *robot's* current pose;
#: ``intrinsic`` would need the anchor's own facing, which no relation in this
#: registry uses yet.
FRAMES_OF_REFERENCE: frozenset[str] = frozenset({"absolute", "relative", "intrinsic"})

#: The relations whose goal regions are distance bands around the same anchor.
#: These are the family a JEPD (jointly exhaustive, pairwise disjoint) label
#: check applies to — see ``tests/test_relation_registry.py``.
PROXIMITY_FAMILY: tuple[str, ...] = ("next_to", "near", "towards")


@dataclass(frozen=True)
class RelationAnchor:
    """Everything a goal-region builder needs about the thing being referred to.

    Deliberately anaemic: it carries scene geometry the caller already has, and
    no mission state, so a relation predicate stays pure and testable.
    """

    kind: str
    center: tuple[float, float] | None = None
    polygon: tuple[tuple[float, float], ...] | None = None
    radius_m: float = 0.0
    label: str = ""
    entity_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ANCHOR_KINDS:
            raise ValueError(f"unsupported anchor kind: {self.kind!r}")
        if self.radius_m < 0.0:
            raise ValueError("anchor radius_m must be >= 0")


GoalRegionBuilder = Callable[[RelationAnchor], GoalRegion]


@dataclass(frozen=True)
class RelationSpec:
    """One spatial relation, registered as a single unit.

    ``goal_region_builder`` is ``None`` only for relations whose success is a
    *trajectory* property rather than a region membership (``orbit``). Those
    report ``has_goal_region == False`` instead of pretending to a region — a
    fabricated disc would be a second, disagreeing arrival authority.
    """

    name: str
    aliases: tuple[str, ...]
    anchor_kinds: tuple[str, ...]
    frame_of_reference: str
    terminal_behavior: str
    summary: str
    goal_region_builder: GoalRegionBuilder | None = None
    #: The subset of ``aliases`` that the deterministic directive grammar
    #: accepts as a destination preposition ("wait **by** the lamppost").
    #: Empty when the relation is reached some other way — ``inside`` is
    #: selected by region-noun classification, not by a preposition.
    preposition_aliases: tuple[str, ...] = ()
    #: How the robot offers this relation back to the owner in a
    #: clarification ("I can **go to it**"). Present tense, second person for
    #: owner-anchored relations. Empty means the relation is never offered.
    offer_phrase: str = ""
    #: Nominal band for band-shaped relations, recorded so the proximity-family
    #: overlap can be computed without constructing a scene.
    nominal_band_m: tuple[float, float] | None = None
    #: Free-form provenance for the band/region choice.
    band_source: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip().lower():
            raise ValueError("relation name must be lowercase and trimmed")
        if not self.aliases:
            raise ValueError(f"relation {self.name!r} must declare at least one alias")
        for alias in self.aliases:
            if alias != alias.strip().lower() or not alias:
                raise ValueError(f"relation alias must be lowercase and trimmed: {alias!r}")
        unknown_prepositions = set(self.preposition_aliases) - set(self.aliases)
        if unknown_prepositions:
            raise ValueError(
                f"relation {self.name!r} preposition aliases are not aliases: "
                f"{sorted(unknown_prepositions)}"
            )
        bad_kinds = set(self.anchor_kinds) - ANCHOR_KINDS
        if bad_kinds or not self.anchor_kinds:
            raise ValueError(f"relation {self.name!r} has invalid anchor kinds: {self.anchor_kinds}")
        if self.frame_of_reference not in FRAMES_OF_REFERENCE:
            raise ValueError(
                f"relation {self.name!r} frame of reference is not one of "
                f"{sorted(FRAMES_OF_REFERENCE)}"
            )
        if self.terminal_behavior not in {"stop", "hold"}:
            raise ValueError(f"relation {self.name!r} terminal behavior must be stop|hold")

    @property
    def has_goal_region(self) -> bool:
        return self.goal_region_builder is not None

    def accepts(self, anchor_kind: str) -> bool:
        return anchor_kind in self.anchor_kinds

    def goal_region(self, anchor: RelationAnchor) -> GoalRegion:
        """Build the K0 arrival region for this relation against ``anchor``."""

        if self.goal_region_builder is None:
            raise ValueError(
                f"relation {self.name!r} has no goal region (its success is a "
                "trajectory property, not region membership)"
            )
        if not isinstance(anchor, RelationAnchor):
            raise TypeError("goal_region requires a RelationAnchor")
        if not self.accepts(anchor.kind):
            raise ValueError(
                f"relation {self.name!r} does not accept a {anchor.kind!r} anchor "
                f"(accepts {list(self.anchor_kinds)})"
            )
        return self.goal_region_builder(anchor)

    def holds(
        self,
        pose_xy: tuple[float, float],
        anchor: RelationAnchor,
        *,
        anchor_xy: tuple[float, float] | None = None,
    ) -> bool:
        """The relation's predicate — the SAME one K0 verification uses.

        There is no second implementation: this is ``GoalRegion.contains`` on
        the region :meth:`goal_region` builds, so a planner asking "would this
        pose satisfy the relation?" and the scorer asking "did it?" cannot
        disagree.
        """

        region = self.goal_region(anchor)
        return region.contains(float(pose_xy[0]), float(pose_xy[1]), anchor_xy=anchor_xy)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "preposition_aliases": list(self.preposition_aliases),
            "anchor_kinds": list(self.anchor_kinds),
            "frame_of_reference": self.frame_of_reference,
            "terminal_behavior": self.terminal_behavior,
            "has_goal_region": self.has_goal_region,
            "nominal_band_m": list(self.nominal_band_m) if self.nominal_band_m else None,
            "band_source": self.band_source,
            "offer_phrase": self.offer_phrase,
            "summary": self.summary,
        }


# --- builders (thin adapters onto the K0 authority) -------------------------


def _require_center(anchor: RelationAnchor, relation: str) -> tuple[float, float]:
    if anchor.center is None:
        raise ValueError(f"{relation} relation requires an anchor center")
    return (float(anchor.center[0]), float(anchor.center[1]))


def _near_region(anchor: RelationAnchor) -> GoalRegion:
    return object_near_goal_region(
        _require_center(anchor, "near"),
        float(anchor.radius_m),
        label=anchor.label,
        entity_id=anchor.entity_id,
    )


def _next_to_region(anchor: RelationAnchor) -> GoalRegion:
    return object_next_to_goal_region(
        _require_center(anchor, "next_to"),
        float(anchor.radius_m),
        entity_id=anchor.entity_id,
    )


def _towards_region(anchor: RelationAnchor) -> GoalRegion:
    return object_towards_goal_region(
        _require_center(anchor, "towards"),
        entity_id=anchor.entity_id,
    )


def _inside_region(anchor: RelationAnchor) -> GoalRegion:
    if anchor.polygon is None or len(tuple(anchor.polygon)) < 3:
        raise ValueError("inside relation requires an anchor polygon with >=3 vertices")
    return region_inside_goal_region(anchor.polygon, entity_id=anchor.entity_id)


def _owner_disc(anchor: RelationAnchor) -> GoalRegion:
    return owner_anchored_goal_region(
        _require_center(anchor, "follow"),
        entity_id=anchor.entity_id or "owner",
    )


_BUILTIN_RELATIONS: tuple[RelationSpec, ...] = (
    RelationSpec(
        name="near",
        offer_phrase="go to it",
        aliases=("at", "beside", "by", "near"),
        preposition_aliases=("at", "beside", "by", "near"),
        anchor_kinds=("object",),
        frame_of_reference="absolute",
        terminal_behavior="hold",
        goal_region_builder=_near_region,
        band_source="instructnav.scoring.object_near_envelope_m (StandOffEnvelope authority)",
        summary="stand in the object's vicinity band, outside its stand-off",
        notes=(
            (
                "The band is derived per object radius and label, so it is the only "
                "proximity relation whose envelope moves with the anchor's size."
            ),
        ),
    ),
    RelationSpec(
        name="next_to",
        offer_phrase="sit next to it",
        aliases=("next to",),
        preposition_aliases=("next to",),
        anchor_kinds=("object", "owner"),
        frame_of_reference="absolute",
        terminal_behavior="hold",
        goal_region_builder=_next_to_region,
        nominal_band_m=NEXT_TO_BAND_M,
        band_source="instructnav.scoring.NEXT_TO_BAND_M",
        summary="settle in the social annulus beside the anchor",
    ),
    RelationSpec(
        name="towards",
        offer_phrase="walk towards it",
        aliases=("toward", "towards"),
        preposition_aliases=("toward", "towards"),
        anchor_kinds=("object",),
        frame_of_reference="relative",
        terminal_behavior="stop",
        goal_region_builder=_towards_region,
        nominal_band_m=TOWARDS_BAND_M,
        band_source="instructnav.scoring.TOWARDS_BAND_M",
        summary="move toward the anchor and stop short of it",
        notes=(
            (
                "Relative frame: 'towards' is motion from the robot's current pose, "
                "so an unmoved robot already inside the band has not satisfied it."
            ),
        ),
    ),
    RelationSpec(
        name="inside",
        offer_phrase="walk onto it",
        aliases=("in", "inside", "within"),
        preposition_aliases=(),
        anchor_kinds=("region",),
        frame_of_reference="absolute",
        terminal_behavior="stop",
        goal_region_builder=_inside_region,
        band_source="instructnav.scoring.region_inside_goal_region (scene polygon)",
        summary="stand within the region polygon",
        notes=(
            (
                "Reached by region-noun classification in goals.py, not by a "
                "preposition: 'go to the sidewalk' has no relation word at all."
            ),
        ),
    ),
    RelationSpec(
        name="follow",
        offer_phrase="come to you",
        aliases=("come", "follow", "heel"),
        preposition_aliases=(),
        anchor_kinds=("owner",),
        frame_of_reference="relative",
        terminal_behavior="hold",
        goal_region_builder=_owner_disc,
        band_source="instructnav.scoring.OWNER_ARRIVAL_RADIUS_M",
        summary="close on the owner and hold the formation band",
        notes=(
            (
                "The approach lane, not a semantic-map query: the owner is a tracked "
                "entity on the owner channel (backlog N12)."
            ),
        ),
    ),
    RelationSpec(
        name="behind",
        offer_phrase="walk behind you",
        aliases=("behind",),
        preposition_aliases=(),
        anchor_kinds=("owner",),
        frame_of_reference="intrinsic",
        terminal_behavior="hold",
        goal_region_builder=_owner_disc,
        band_source="instructnav.scoring.OWNER_ARRIVAL_RADIUS_M",
        summary="stage behind the owner's direction of travel",
        notes=(
            (
                "Intrinsic frame — the only registered relation that needs the "
                "anchor's own heading, which is why it carries the "
                "owner_heading_available admission precondition and plain follow "
                "does not (arbiter ruling 2026-08-06)."
            ),
        ),
    ),
    RelationSpec(
        name="orbit",
        offer_phrase="circle around you",
        aliases=("around", "circle", "orbit"),
        preposition_aliases=(),
        anchor_kinds=("owner",),
        frame_of_reference="relative",
        terminal_behavior="stop",
        goal_region_builder=None,
        summary="sweep a full revolution around the owner",
        notes=(
            (
                "No goal region on purpose: orbit success is net signed swept "
                "angle (instructnav.scoring.orbit_revolutions), a trajectory "
                "property. A disc would be a second arrival authority that "
                "disagreed with the sweep."
            ),
        ),
    ),
)


class RelationRegistry:
    """Name/alias lookup over registered :class:`RelationSpec` units."""

    def __init__(self, specs: Sequence[RelationSpec] = ()) -> None:
        self._by_name: dict[str, RelationSpec] = {}
        self._by_alias: dict[str, str] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: RelationSpec) -> RelationSpec:
        """Add one relation; fail closed on a duplicate name or stolen alias."""

        if not isinstance(spec, RelationSpec):
            raise TypeError("register requires a RelationSpec")
        if spec.name in self._by_name:
            raise ValueError(f"relation {spec.name!r} is already registered")
        for alias in spec.aliases:
            owner = self._by_alias.get(alias)
            if owner is not None and owner != spec.name:
                raise ValueError(
                    f"alias {alias!r} already resolves to relation {owner!r}; "
                    "an alias must name exactly one relation"
                )
        self._by_name[spec.name] = spec
        for alias in spec.aliases:
            self._by_alias[alias] = spec.name
        return spec

    def names(self) -> tuple[str, ...]:
        return tuple(self._by_name)

    def specs(self) -> tuple[RelationSpec, ...]:
        return tuple(self._by_name.values())

    def get(self, name: str) -> RelationSpec:
        try:
            return self._by_name[str(name).strip().lower()]
        except KeyError as error:
            raise KeyError(f"unknown relation: {name!r}") from error

    def has(self, name: str) -> bool:
        return str(name).strip().lower() in self._by_name

    def resolve_word(self, word: str) -> RelationSpec | None:
        """Return the relation an alias names, else ``None`` (never guesses)."""

        clean = " ".join(str(word).strip().lower().split())
        name = self._by_alias.get(clean)
        return None if name is None else self._by_name[name]

    def aliases(self) -> dict[str, str]:
        """alias → relation name, for callers that need the whole table."""

        return dict(self._by_alias)

    def preposition_alternation(self, names: Sequence[str]) -> str:
        """Regex alternation of the destination prepositions for ``names``.

        This is what ``goals.py`` splices into its directive grammar instead of
        keeping a second copy of the vocabulary. Multi-word aliases become
        ``\\s+``-joined so "next to" matches "next  to" as well.
        """

        words: list[str] = []
        for name in names:
            words.extend(self.get(name).preposition_aliases)
        if not words:
            raise ValueError(f"no destination prepositions registered for {list(names)}")
        return "|".join(re.escape(word).replace(r"\ ", r"\s+") for word in sorted(set(words)))

    def alias_alternation(self, names: Sequence[str]) -> str:
        """Regex alternation of every alias for ``names`` (not just prepositions)."""

        words: list[str] = []
        for name in names:
            words.extend(self.get(name).aliases)
        if not words:
            raise ValueError(f"no aliases registered for {list(names)}")
        return "|".join(re.escape(word).replace(r"\ ", r"\s+") for word in sorted(set(words)))


#: The process-wide registry. Import this, do not build a second one — two
#: registries is the D5 disagreement class the plan's anti-goals forbid.
RELATIONS = RelationRegistry(_BUILTIN_RELATIONS)


def get_relation(name: str) -> RelationSpec:
    return RELATIONS.get(name)


def resolve_relation_word(word: str) -> RelationSpec | None:
    return RELATIONS.resolve_word(word)


def relation_names() -> tuple[str, ...]:
    return RELATIONS.names()


def register_relation(spec: RelationSpec) -> RelationSpec:
    return RELATIONS.register(spec)


def preposition_alternation(names: Sequence[str]) -> str:
    return RELATIONS.preposition_alternation(names)


def alias_alternation(names: Sequence[str]) -> str:
    return RELATIONS.alias_alternation(names)


def proximity_band_overlaps(
    *,
    object_radius_m: float = 0.0,
    label: str = "",
) -> dict[tuple[str, str], tuple[float, float] | None]:
    """Measure where the proximity family's bands overlap, for one anchor size.

    JEPD ("exactly one label at any distance") is the property this family
    would have if the bands partitioned the ray. **They do not**, and this
    function is how the overlap is measured rather than asserted away: it
    returns, for each ordered pair, the closed interval of anchor distances
    admitted by both bands, or ``None`` when they are disjoint.

    The overlap is intentional — ``next_to`` is a *social* placement band and
    ``towards`` is a *motion-stopped-short* band; a pose can honestly satisfy
    both. What matters is that the ranges are pinned, so a band edit that
    changes them is a red build (``tests/test_relation_registry.py``).
    """

    anchor = RelationAnchor(
        kind="object",
        center=(0.0, 0.0),
        radius_m=float(object_radius_m),
        label=label,
        entity_id="overlap-probe",
    )
    bands: dict[str, tuple[float, float]] = {}
    for name in PROXIMITY_FAMILY:
        region = RELATIONS.get(name).goal_region(anchor)
        assert region.band_m is not None  # every proximity relation is band-shaped
        lo = max(float(region.band_m[0]), float(region.anchor_footprint_m))
        bands[name] = (lo, float(region.band_m[1]))

    overlaps: dict[tuple[str, str], tuple[float, float] | None] = {}
    for index, first in enumerate(PROXIMITY_FAMILY):
        for second in PROXIMITY_FAMILY[index + 1 :]:
            lo = max(bands[first][0], bands[second][0])
            hi = min(bands[first][1], bands[second][1])
            overlaps[(first, second)] = (lo, hi) if lo <= hi else None
    return overlaps


def proximity_labels_at(
    distance_m: float,
    *,
    object_radius_m: float = 0.0,
    label: str = "",
) -> tuple[str, ...]:
    """Every proximity relation whose band admits a pose ``distance_m`` away."""

    anchor = RelationAnchor(
        kind="object",
        center=(0.0, 0.0),
        radius_m=float(object_radius_m),
        label=label,
        entity_id="label-probe",
    )
    return tuple(
        name
        for name in PROXIMITY_FAMILY
        if RELATIONS.get(name).holds((float(distance_m), 0.0), anchor)
    )


__all__ = [
    "ANCHOR_KINDS",
    "FRAMES_OF_REFERENCE",
    "PROXIMITY_FAMILY",
    "RELATIONS",
    "GoalRegionBuilder",
    "RelationAnchor",
    "RelationRegistry",
    "RelationSpec",
    "alias_alternation",
    "get_relation",
    "preposition_alternation",
    "proximity_band_overlaps",
    "proximity_labels_at",
    "register_relation",
    "relation_names",
    "resolve_relation_word",
]
