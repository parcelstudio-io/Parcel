"""What "arrived" MEANS, per semantic class — the local arrival table (card R10).

WHY THIS IS A TABLE AND NOT A PROMPT
------------------------------------
The 2026-08-19/20 nav bench (``csbench/reports/bench_navmodel.md``, cell D) put
15 arrival phrasings x 3 samples through two hosted tiers and measured the split
this module encodes:

* **relation** ("on the sidewalk" -> ``inside``, "get to the door" -> ``near``,
  "come to me" -> ``social``) was answered correctly **36/36 on both tiers**, and
  the mini tier was 15/15 self-consistent. A model hint is therefore worth
  reading — it is the cheapest available source of the one judgement a local
  word table cannot generalize (``rug``, ``kitchen``, ``bed`` are regions no
  shipped region-noun list contains).
* **face** was answered ``face=goal`` for "get to the door" **6/6 on both
  tiers**, where the owner wants the robot turned BACK to them. Terminal
  orientation and door etiquette are owner policy, and the model gets them
  reliably wrong.

So relation is HYBRID (the model may hint, this table validates and may
override, this table alone decides when no hint arrives) and face/etiquette are
LOCAL ONLY. There is no code path in this module by which a hosted argument can
set ``face``, ``do_not_cross``, ``standoff_m`` or ``ask_hint``: they are read
off :data:`ARRIVAL_TABLE` by class and by nothing else.

WHAT "VALIDATED" MEANS, PRECISELY
---------------------------------
:func:`resolve_relation` accepts a hint in exactly two cases:

1. **agrees** — the hint equals the class's table relation. Free confirmation,
   no behaviour change, recorded so the agreement rate stays measurable.
2. **refines** — the class is genuinely UNKNOWN to the local vocabulary (so the
   table's own answer is the fail-safe ``near``, not a positive judgement) AND
   the local map supplies the geometry the refinement needs: ``inside`` requires
   a grounded polygon, ``social`` requires a person/owner anchor.

Everything else loses to the table, with a machine-readable reason. A hint that
contradicts a POSITIVELY classified place never wins — "near the sidewalk" does
not become a near-goal because a model said so, and "inside the door" never
becomes a doorway-straddling region goal.

RELATIONSHIP TO ``relation_registry``
-------------------------------------
This module adds no geometry and no predicate. ``inside`` / ``near`` are the
registry's registered relations and keep their existing K0 goal regions;
``social`` is the person stand-off expressed as a ``near`` terminal with an
explicit stand-off, so it reaches the same single arrival authority rather than
growing a second one. :func:`planner_relation` is the one-line translation.

WHAT A PERCEPTION ANSWER FOR THIS CLASS IS MEASURED AGAINST (card PG-2)
----------------------------------------------------------------------
:attr:`ArrivalPolicy.localization_target` is the one new field, and it is the
*only* thing this card added here. It says, per class, which part of the place a
depth sensor can actually put a number on:

``surface``
    The exterior. A ``near`` terminal is a stand-off from a thing you stop
    BESIDE, and an RGB-D camera only ever sees that thing's outward faces.
    Measured 2026-08-21 on 120 rendered frames: building entries land **1–3 cm
    from the visible facade and 1.2–1.7 m from the geom centre, 6/6** in the
    oracle arm (`scrum/20260821/perception/bench_mapping.md`). Grading such an
    answer against the centre marks a correct pipeline wrong.
``interior``
    The inside. An ``inside`` terminal succeeds by footprint containment, so
    the region's own area *is* the measurable target and nothing changes.

The field exists here rather than in the eval because "what does arrival mean
for this class" already has an authority, and a perception scorer that spelled
its own class -> metric map would be a second one free to drift from it.
``evals/nav_instruct/surface_scoring.py`` reads THIS table and holds no map of
its own. Nothing in the navigator, the planner or the goal builder reads this
field: it changes what a measurement is compared to, never where the robot goes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from parcel_robot.authority import PERSON_SOCIAL_ZONE_M

__all__ = [
    "ARRIVAL_TABLE",
    "CLASS_OBJECT",
    "CLASS_PERSON",
    "CLASS_PORTAL",
    "CLASS_REGION",
    "CLASS_UNKNOWN",
    "FACE_GOAL",
    "FACE_OWNER",
    "FACE_TRAVEL",
    "LOCALIZATION_INTERIOR",
    "LOCALIZATION_SURFACE",
    "LOCALIZATION_TARGETS",
    "PLACE_CLASSES",
    "PORTAL_WORDS",
    "RELATION_HINTS",
    "RELATION_INSIDE",
    "RELATION_NEAR",
    "RELATION_SOCIAL",
    "SOCIAL_STANDOFF_M",
    "ArrivalPolicy",
    "RelationDecision",
    "arrival_fact",
    "arrival_policy",
    "classify_place",
    "localization_target",
    "planner_relation",
    "resolve_relation",
]

#: The closed relation vocabulary a hosted ``navigate_to`` may hint at. Three
#: values because the bench probe measured these three and nothing else, and an
#: enum the model cannot leave is what stopped ``play_gesture("do a backflip")``.
RELATION_INSIDE = "inside"
RELATION_NEAR = "near"
RELATION_SOCIAL = "social"
RELATION_HINTS: frozenset[str] = frozenset(
    {RELATION_INSIDE, RELATION_NEAR, RELATION_SOCIAL}
)

#: Terminal orientation. LOCAL ONLY — never settable from a tool argument.
FACE_GOAL = "goal"
FACE_OWNER = "owner"
FACE_TRAVEL = "travel"

#: What a perception answer for a class is MEASURED against (card PG-2). Two
#: values because a depth camera can return exactly two kinds of ground-truth
#: fact about a place: a point on its outside, or a point in its inside.
#: LOCAL ONLY, like ``face`` — never settable from a tool argument, and read by
#: the eval scorer rather than by anything on the robot's control path.
LOCALIZATION_SURFACE = "surface"
LOCALIZATION_INTERIOR = "interior"
LOCALIZATION_TARGETS: frozenset[str] = frozenset(
    {LOCALIZATION_SURFACE, LOCALIZATION_INTERIOR}
)

CLASS_REGION = "region"
CLASS_PORTAL = "portal"
CLASS_OBJECT = "object"
CLASS_PERSON = "person"
CLASS_UNKNOWN = "unknown"
PLACE_CLASSES: tuple[str, ...] = (
    CLASS_REGION,
    CLASS_PORTAL,
    CLASS_OBJECT,
    CLASS_PERSON,
    CLASS_UNKNOWN,
)

#: Social stand-off for person goals: the near edge of Hall's social zone, the
#: value the proxemics survey in ``res_semnav.md`` §10 names for a companion
#: approach. DERIVED from the safety authority, never written as a literal —
#: ``tests/test_authority_no_literal_drift.py`` is the archon that caught the
#: first draft of this line spelling ``1.2`` by hand (F-proximity family).
#: Expressed as a stand-off so the ``near`` band builder — the ONE arrival
#: authority — still evaluates the predicate.
SOCIAL_STANDOFF_M: float = PERSON_SOCIAL_ZONE_M


@dataclass(frozen=True)
class ArrivalPolicy:
    """Everything the LOCAL side decides about one class's terminal."""

    place_class: str
    #: The table's terminal relation. Wins every conflict with a model hint.
    relation: str
    #: Where the body points once stopped. Local policy, never model-supplied.
    face: str = FACE_GOAL
    #: Portals only: stop AT the threshold, never travel through it.
    do_not_cross: bool = False
    #: Explicit stand-off in metres, or ``None`` to use the relation's own band.
    standoff_m: float | None = None
    #: The terminal speech act the local side wants, verbatim, or "".
    ask_hint: str = ""
    #: Which part of the place a perception answer for this class is scored
    #: against — :data:`LOCALIZATION_SURFACE` or :data:`LOCALIZATION_INTERIOR`.
    #: Defaults to the surface because that is the fail-safe: measuring an
    #: unknown place's exterior can only ever be conservative, while assuming
    #: an interior asserts a containment nobody established.
    localization_target: str = LOCALIZATION_SURFACE
    #: Hints that may REFINE this entry when the local map supports them. Only
    #: the fail-safe UNKNOWN row has any: a positively classified place is a
    #: judgement the local side has already made.
    refinements: frozenset[str] = frozenset()
    #: Why this row reads the way it does. Quoted in logs and status docs.
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "place_class": self.place_class,
            "relation": self.relation,
            "face": self.face,
            "do_not_cross": self.do_not_cross,
            "standoff_m": self.standoff_m,
            "ask_hint": self.ask_hint,
            "localization_target": self.localization_target,
        }


#: The table. Keyed by semantic class, exhaustive over :data:`PLACE_CLASSES`,
#: and the ONLY authority on face / do-not-cross / stand-off / ask-hint.
ARRIVAL_TABLE: dict[str, ArrivalPolicy] = {
    CLASS_REGION: ArrivalPolicy(
        place_class=CLASS_REGION,
        relation=RELATION_INSIDE,
        face=FACE_TRAVEL,
        localization_target=LOCALIZATION_INTERIOR,
        rationale=(
            "a region goal succeeds by footprint containment, not by range to a "
            "sampled point (ObjectNav Revisited; CoNVOI surface masks); the "
            "sensor sees the region's own top surface, so its interior IS the "
            "measurable target and PG-2 changed nothing here"
        ),
    ),
    CLASS_PORTAL: ArrivalPolicy(
        place_class=CLASS_PORTAL,
        relation=RELATION_NEAR,
        face=FACE_OWNER,
        do_not_cross=True,
        ask_hint="ask the owner what they would like to do next",
        localization_target=LOCALIZATION_SURFACE,
        rationale=(
            "stopping IN a doorway violates the social-navigation competency "
            "convention; the owner's terminal is turn-back-and-ask, which the "
            "bench measured at 0/12 from the model"
        ),
    ),
    CLASS_OBJECT: ArrivalPolicy(
        place_class=CLASS_OBJECT,
        relation=RELATION_NEAR,
        face=FACE_OWNER,
        localization_target=LOCALIZATION_SURFACE,
        rationale=(
            "an object terminal is an errand the owner asked for; ending it "
            "turned back toward them is the F-formation the approach studies "
            "name, and it is the orientation the model never proposes; the "
            "sensor sees the object's outward faces and never its centroid, so "
            "a perception answer is measured to the surface (PG-2)"
        ),
    ),
    CLASS_PERSON: ArrivalPolicy(
        place_class=CLASS_PERSON,
        relation=RELATION_SOCIAL,
        face=FACE_GOAL,
        standoff_m=SOCIAL_STANDOFF_M,
        localization_target=LOCALIZATION_SURFACE,
        rationale="social-zone near edge, facing the person, never looming",
    ),
    CLASS_UNKNOWN: ArrivalPolicy(
        place_class=CLASS_UNKNOWN,
        relation=RELATION_NEAR,
        face=FACE_OWNER,
        refinements=frozenset({RELATION_INSIDE, RELATION_SOCIAL}),
        localization_target=LOCALIZATION_SURFACE,
        rationale=(
            "an unclassified place gets the fail-safe near terminal — never a "
            "guess; this is the ONE row a supported model hint may refine"
        ),
    ),
}


# --- classification ---------------------------------------------------------
#
# Word tables, deliberately data-shaped and small. They classify the PHRASE the
# owner used; they never assert the place exists (that is grounding's job).

#: Portal nouns. A portal is a thing you pass THROUGH, and the whole point of
#: the class is that the robot must not.
PORTAL_WORDS: frozenset[str] = frozenset(
    {
        "door",
        "doors",
        "doorway",
        "entrance",
        "entry",
        "entryway",
        "exit",
        "gate",
        "gateway",
        "threshold",
    }
)

#: Region nouns BEYOND the navigation grammar's own ``goals._REGION_WORDS``.
#: The bench's firm-gold ``inside`` phrasings that no shipped table contained
#: are listed by name, so the local side answers them without needing a hint.
EXTRA_REGION_WORDS: frozenset[str] = frozenset(
    {
        "bed",
        "carpet",
        "courtyard",
        "deck",
        "driveway",
        "field",
        "garden",
        "kitchen",
        "lawn",
        "mat",
        "patio",
        "rug",
        "yard",
    }
)

#: Person referents that are not the owner. Owner referents come from
#: ``goals.OWNER_REFERENT_TABLE`` so there is one authority for "the owner".
PERSON_WORDS: frozenset[str] = frozenset(
    {
        "her",
        "him",
        "person",
        "somebody",
        "someone",
        "them",
        "they",
    }
)

#: Modifiers that may decorate a place noun without changing its class
#: ("the nearest sidewalk", "the big door", "my kitchen").
_MODIFIERS: frozenset[str] = frozenset(
    {
        "a",
        "ahead",
        "an",
        "back",
        "behind",
        "big",
        "closest",
        "east",
        "far",
        "front",
        "large",
        "left",
        "little",
        "main",
        "my",
        "nearby",
        "nearest",
        "next",
        "north",
        "other",
        "right",
        "safe",
        "safer",
        "small",
        "south",
        "tall",
        "that",
        "the",
        "this",
        "to",
        "west",
        "your",
    }
)


def classify_place(
    place: str,
    *,
    region_labels: frozenset[str] | set[str] | tuple[str, ...] = (),
    object_labels: frozenset[str] | set[str] | tuple[str, ...] = (),
) -> str:
    """Classify a place PHRASE into one of :data:`PLACE_CLASSES`.

    ``region_labels`` / ``object_labels`` let a caller fold the live scene
    vocabulary in (``city_semantics.CLASS_ALIASES`` keys and their aliases), so
    a scene that declares a class this module never heard of still classifies —
    without this module transcribing any scene's contents.

    Fails SAFE: anything the tables cannot place is :data:`CLASS_UNKNOWN`, whose
    row is the ``near`` terminal. It never guesses a class from a substring.
    """

    # Local import: ``goals`` imports the relation registry, and importing it at
    # module scope would make this module part of that import cycle for callers
    # (``goals`` itself wants to read this table).
    from parcel_robot.navigation.goals import (
        _REGION_WORDS,
        OWNER_REFERENT_TABLE,
    )

    phrase = _normalize(place)
    if not phrase:
        return CLASS_UNKNOWN
    if phrase in OWNER_REFERENT_TABLE or phrase in {"here", "over here"}:
        return CLASS_PERSON
    words = [word for word in re.findall(r"[a-z0-9]+", phrase)]
    if not words:
        return CLASS_UNKNOWN
    nouns = [word for word in words if word not in _MODIFIERS]
    if not nouns:
        return CLASS_UNKNOWN

    region_vocab = {_normalize(label) for label in region_labels if _normalize(label)}
    object_vocab = {_normalize(label) for label in object_labels if _normalize(label)}
    # Whole-phrase matches first: a scene alias may be two words ("lamp post").
    if phrase in region_vocab:
        return CLASS_REGION
    if phrase in object_vocab:
        return CLASS_OBJECT

    # Head noun last: "the front door" is a door, "street light" is a light.
    head = nouns[-1]
    if head in PORTAL_WORDS:
        return CLASS_PORTAL
    if head in PERSON_WORDS:
        return CLASS_PERSON
    if head in _REGION_WORDS or head in EXTRA_REGION_WORDS or head in region_vocab:
        return CLASS_REGION
    if head in object_vocab:
        return CLASS_OBJECT
    if len(nouns) > 1:
        # "big oak tree" — the modifier-stripped tail did not match, so try the
        # full noun phrase against the scene vocabulary before giving up.
        joined = " ".join(nouns)
        if joined in region_vocab:
            return CLASS_REGION
        if joined in object_vocab:
            return CLASS_OBJECT
    return CLASS_UNKNOWN


def arrival_policy(place_class: str) -> ArrivalPolicy:
    """The table row for a class. Unknown/blank/garbage -> the fail-safe row."""

    return ARRIVAL_TABLE.get(str(place_class), ARRIVAL_TABLE[CLASS_UNKNOWN])


def localization_target(place_class: str) -> str:
    """What a perception answer for this class is scored against (card PG-2).

    The single authority the perception scorer reads. Returns
    :data:`LOCALIZATION_SURFACE` or :data:`LOCALIZATION_INTERIOR`; an unknown
    class falls through :func:`arrival_policy` to the fail-safe row, which is
    ``surface``.
    """

    return arrival_policy(place_class).localization_target


# --- hybrid relation --------------------------------------------------------


@dataclass(frozen=True)
class RelationDecision:
    """The outcome of validating one model relation hint against the table."""

    relation: str
    place_class: str
    #: ``table`` | ``model_hint_agrees`` | ``model_hint_refines``
    source: str
    #: The normalized hint as received, "" when the model sent none.
    hint: str = ""
    #: True only when the hint contributed. ``model_hint_agrees`` counts.
    hint_accepted: bool = False
    #: Machine-readable why. Always non-empty when a hint was sent and lost.
    reason: str = ""

    @property
    def hint_overridden(self) -> bool:
        return bool(self.hint) and not self.hint_accepted

    def as_dict(self) -> dict[str, Any]:
        return {
            "relation": self.relation,
            "place_class": self.place_class,
            "source": self.source,
            "hint": self.hint,
            "hint_accepted": self.hint_accepted,
            "reason": self.reason,
        }


#: Source values, named so callers do not spell them.
SOURCE_TABLE = "table"
SOURCE_HINT_AGREES = "model_hint_agrees"
SOURCE_HINT_REFINES = "model_hint_refines"


def resolve_relation(
    place_class: str,
    hint: str | None = None,
    *,
    region_support: bool = False,
    person_support: bool = False,
) -> RelationDecision:
    """Hybrid relation: the model may hint, the local table decides.

    ``region_support`` / ``person_support`` describe what the LOCAL map can
    actually back: a polygon exists for this place, or the anchor is a tracked
    person. A refinement without its support is refused, because accepting
    ``inside`` for a place with no polygon would manufacture a region goal out
    of a sentence — the exact failure LM-Nav's label-level grounding cannot
    express (``res_semnav.md`` §1).
    """

    policy = arrival_policy(place_class)
    resolved_class = policy.place_class
    clean = _normalize(hint)
    if not clean:
        return RelationDecision(
            relation=policy.relation,
            place_class=resolved_class,
            source=SOURCE_TABLE,
        )
    if clean not in RELATION_HINTS:
        return RelationDecision(
            relation=policy.relation,
            place_class=resolved_class,
            source=SOURCE_TABLE,
            hint=clean,
            reason="relation_hint_not_a_relation",
        )
    if clean == policy.relation:
        return RelationDecision(
            relation=policy.relation,
            place_class=resolved_class,
            source=SOURCE_HINT_AGREES,
            hint=clean,
            hint_accepted=True,
        )
    if clean not in policy.refinements:
        # A positively classified place already carries a local judgement. The
        # table wins, and the disagreement is recorded rather than swallowed.
        return RelationDecision(
            relation=policy.relation,
            place_class=resolved_class,
            source=SOURCE_TABLE,
            hint=clean,
            reason="relation_hint_conflicts_with_class_table",
        )
    supported = {
        RELATION_INSIDE: bool(region_support),
        RELATION_SOCIAL: bool(person_support),
        RELATION_NEAR: True,
    }[clean]
    if not supported:
        return RelationDecision(
            relation=policy.relation,
            place_class=resolved_class,
            source=SOURCE_TABLE,
            hint=clean,
            reason="relation_hint_unsupported_by_local_map",
        )
    return RelationDecision(
        relation=clean,
        place_class=resolved_class,
        source=SOURCE_HINT_REFINES,
        hint=clean,
        hint_accepted=True,
    )


def planner_relation(relation: str) -> str:
    """Translate a table relation into the navigator's registered relation.

    ``social`` is not a registered relation — it is the ``near`` predicate with
    the social stand-off. Translating here keeps ONE arrival authority instead
    of registering a second band that would have to agree with the first.
    """

    clean = _normalize(relation)
    if clean == RELATION_SOCIAL:
        return RELATION_NEAR
    if clean in {RELATION_INSIDE, RELATION_NEAR}:
        return clean
    return RELATION_NEAR


# --- the terminal fact ------------------------------------------------------


def arrival_fact(
    *,
    place: str,
    policy: ArrivalPolicy,
    owner_name: str = "",
    relation: str = "",
) -> str:
    """The sentence the runtime narrates when a mission terminal is reached.

    A FACT plus, when the table asks for one, the speech-act hint spelled out
    inline. The bench is unambiguous that the ask does not emerge on its own
    (A2 0/6, B4 0/6, both tiers): if the hint is not in the item, the model
    reports and stops. Nothing here decides anything — the ask-hint text is a
    table constant and the rest is the mission's own outcome.
    """

    label = " ".join(str(place).split()) or "the place you asked for"
    used = _normalize(relation) or policy.relation
    if used == RELATION_INSIDE:
        body = f"You are now standing inside {label}."
    elif used == RELATION_SOCIAL:
        body = f"You have stopped a polite step from {label}."
    elif policy.do_not_cross:
        body = f"You have stopped just short of {label}, without going through it."
    else:
        body = f"You have arrived beside {label}."
    if policy.face == FACE_OWNER:
        who = " ".join(str(owner_name).split())
        body += f" You are turned back to face {who or 'your owner'}."
    if policy.ask_hint:
        body += f" Now {policy.ask_hint}."
    return body


def _normalize(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())
