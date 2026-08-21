from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from parcel_robot.navigation.arrival_semantics import (
    CLASS_OBJECT,
    FACE_GOAL,
    RELATION_INSIDE,
    arrival_policy,
    classify_place,
    planner_relation,
    resolve_relation,
)
from parcel_robot.navigation.relation_registry import RELATIONS

GoalKind = Literal["object", "region", "relative"]

_REGION_WORDS = {
    "sidewalk",
    "pavement",
    "crosswalk",
    "grass",
    "road",
    "street",
    "plaza",
    "path",
    "trail",
}
_REGION_MODIFIERS = {
    "ahead",
    "behind",
    "closest",
    "east",
    "left",
    "nearby",
    "nearest",
    "next",
    "north",
    "other",
    "right",
    "safe",
    "safer",
    "south",
    "west",
}

# --- Modifier vocabularies (stratum-3 sidecar owns these later) -------------
#
# One module-level table per modifier family. They are deliberately small and
# data-shaped: the per-scene semantics sidecar in STRATA_GENERALIZATION_PLAN
# stratum 3 can replace the literals without touching the parsing code.

#: Superlative modifiers → canonical superlative. v1 has one value.
SUPERLATIVE_TABLE: dict[str, str] = {
    "closest": "nearest",
    "nearby": "nearest",
    "nearest": "nearest",
}

#: Motion verbs that themselves carry a pace → canonical pace. v1 has one value.
PACE_VERB_TABLE: dict[str, str] = {
    "hurry": "fast",
    "hurrying": "fast",
    "run": "fast",
    "running": "fast",
    "runs": "fast",
    "sprint": "fast",
    "sprinting": "fast",
    "sprints": "fast",
}

#: Adverbs that set the pace of an otherwise neutral motion verb.
PACE_ADVERB_TABLE: dict[str, str] = {
    "quick": "fast",
    "quickly": "fast",
}

#: Attribute adjectives recognized before the noun. Values are the attribute
#: family; the surface word is what gets stored on the goal so replies can
#: name the word the owner actually said.
ATTRIBUTE_TABLE: dict[str, str] = {
    "big": "size",
    "large": "size",
    "little": "size",
    "small": "size",
    "tall": "size",
}

#: Referring expressions that name the **owner**, not a scene object (N12).
#:
#: The owner is a tracked entity on the owner channel (``observation.owner``),
#: never a semantic-map object. Before this table "go to the owner" compiled to
#: ``NavigateTo`` with target label "owner" and spent ~38 s asking the semantic
#: map for a landmark that cannot exist, then failed with
#: ``semantic_target_not_found`` having travelled *away* from the owner.
#: Membership here is what routes those phrasings to the approach lane, which
#: is the same lane "come here" already uses — one authority for "the owner",
#: not two ways to mean it that resolve differently (the D5 class).
OWNER_REFERENT_TABLE: frozenset[str] = frozenset(
    {
        "me",
        "my owner",
        "my position",
        "my side",
        "owner",
        "the owner",
        "you",
        "your owner",
        "your side",
    }
)

_ARTICLES = frozenset({"a", "an", "the"})
#: Pace words only count inside the leading verb phrase, so "walk to the fun
#: run sign" never becomes a sprint.
_PACE_SCAN_WORDS = 3

# --- Relation vocabulary comes from the RelationSpec registry ---------------
#
# These alternations used to be literals spelled out three times in this file.
# They are now derived from ``navigation.relation_registry``, so a relation's
# words and its goal-region builder are one registered unit. The alternations
# below reproduce the previous literals exactly (pinned by
# ``tests/test_relation_registry.py``); widening a relation is now an edit to
# its RelationSpec, not to this grammar.

#: Prepositions that put the robot *beside* the target ("wait by the lamppost").
_PROXIMITY_PREPOSITIONS = RELATIONS.preposition_alternation(("near", "next_to"))
#: The ``next_to`` relation's own aliases, used to tell "sit next to X" from
#: the looser "sit by X".
_NEXT_TO_ALIASES = RELATIONS.alias_alternation(("next_to",))
#: Directed-motion prepositions ("walk towards the tree").
_TOWARDS_ALIASES = RELATIONS.alias_alternation(("towards",))

_PROXIMITY_RELATION = re.compile(rf"\b(?:{_PROXIMITY_PREPOSITIONS})\s+(?:the\s+)?")
_NEXT_TO_RELATION = re.compile(rf"\b(?:{_NEXT_TO_ALIASES})\b")
_TOWARDS_RELATION = re.compile(rf"\b(?:{_TOWARDS_ALIASES})\b")


@dataclass(frozen=True)
class SemanticGoal:
    query: str
    kind: GoalKind = "object"
    terminal_relation: str = "near"
    minimum_confidence: float = 0.55
    required_observations: int = 2
    terminal_behavior: str = "stop"
    superlative: str | None = None
    attributes: tuple[str, ...] = ()
    pace: str | None = None
    # --- arrival semantics (card R10) --------------------------------------
    # Additive, defaulted to the pre-R10 behaviour, and all four come from the
    # LOCAL arrival table (``navigation.arrival_semantics``) — never from a
    # hosted tool argument. ``relation_source`` records whether a model hint
    # contributed, so "did the hint matter?" is a query, not an anecdote.
    place_class: str = CLASS_OBJECT
    face: str = FACE_GOAL
    do_not_cross: bool = False
    standoff_m: float | None = None
    ask_hint: str = ""
    relation_source: str = "table"


_NEGATED_OR_HYPOTHETICAL = re.compile(
    r"\b(?:do\s+not|don[' ]?t|never|cannot|can[' ]?t|could\s+not|"
    r"couldn[' ]?t|would\s+not|wouldn[' ]?t|should\s+not|shouldn[' ]?t|"
    r"must\s+not|mustn[' ]?t|what\s+if|"
    r"suppose|imagine|pretend)\b"
)
_POLITE_PREFIXES = (
    re.compile(r"^(?:hey\s+)?parcel[,.]?\s+"),
    # "would you MIND trotting over…" is as much a request as "would you trot
    # over…"; the ``mind`` filler otherwise survived the strip and blocked the
    # verb match, dead-ending a polite physical request in conversation.
    re.compile(r"^(?:please\s+)?(?:can|could|would|will)\s+you\s+(?:please\s+|mind\s+)?"),
    re.compile(r"^(?:please\s+)?i\s+(?:want|need)\s+you\s+to\s+"),
    re.compile(r"^(?:please\s+)?i(?:'d|\s+would)\s+like\s+you\s+to\s+"),
    re.compile(r"^(?:please|kindly)\s+"),
)
_PACE_VERB_ALTERNATION = "|".join(sorted(PACE_VERB_TABLE, key=len, reverse=True))
#: Gait verbs that mean "move to a place" at a neutral pace — the casual
#: register ("trot over to the lamppost", "scoot to the bench"). Kept separate
#: from PACE_VERB_TABLE because a trot is not a declared pace level; it is just
#: a colloquial "go". Recognising them is what stops a polite "would you mind
#: trotting over to the lamppost?" from dead-ending in the conversation lane.
_GAIT_VERB_ALTERNATION = (
    "trotting|trots|trot|jogging|jogs|jog|scooting|scoots|scoot|"
    "ambling|ambles|amble|wander\\s+over|wandering|wanders|wander"
)
#: Locate-and-approach: the semantic resolution ladder already IS a search
#: (frustum → memory → scan → SearchEntity → honest refusal), so "find the
#: nearest lamppost" is a navigation directive, not a separate verb class.
#: ``find out ...`` is a question and must not become motion authority.
#:
#: Card R20 gives this pattern a NAME because it is now load-bearing twice: it
#: is still one of the destination patterns, and it is also the boundary of the
#: unknown-place gate. "Go to narnia" names a goal and is refused when nothing
#: can resolve it; "look for a mailbox" *asks the robot to look*, and an
#: exploration the owner explicitly requested is not a fabricated goal. One
#: regex, used by both, so the boundary cannot drift from the grammar.
_EXPLICIT_SEARCH_PATTERN = re.compile(
    r"^(?:find|locate|look\s+for|search\s+for)(?:\s+me)?\s+(?!out\b)(?P<destination>.+)$"
)

_DESTINATION_PATTERNS = (
    re.compile(
        r"^(?:go|navigate|walk|move|head|drive|take\s+me"
        rf"|{_GAIT_VERB_ALTERNATION}|{_PACE_VERB_ALTERNATION})(?:\s+over)?\s+"
        r"(?:to|onto|into)\s+(?P<destination>.+)$"
    ),
    re.compile(
        r"^(?:go|navigate|walk|move|head"
        rf"|{_GAIT_VERB_ALTERNATION}|{_PACE_VERB_ALTERNATION})(?:\s+over)?\s+"
        rf"(?:{_TOWARDS_ALIASES})\s+(?P<destination>.+)$"
    ),
    re.compile(
        r"^(?:wait|stand|stay|sit|go|walk|move)(?:\s+over)?\s+"
        rf"(?:{_PROXIMITY_PREPOSITIONS})\s+(?P<destination>.+)$"
    ),
    _EXPLICIT_SEARCH_PATTERN,
)
_RATIONALE_BOUNDARY = re.compile(
    r"\s+(?:so\s+that|because|since|so\s+(?:i|you|we)|in\s+order\s+to|to\s+avoid)\b"
)


def navigation_directive_from_text(text: str) -> str | None:
    """Return a bounded destination directive from an explicit imperative.

    This deterministic path handles safety-motivated and relational requests
    without depending on an LLM, while rejecting negation and hypotheticals.
    """

    clean = _normalized_text(text)
    if not clean or navigation_directive_is_blocked(clean):
        return None
    clean = _strip_leading_prefixes(clean)
    clean = re.sub(r"[?!]+$", "", clean).strip()
    for pattern in _DESTINATION_PATTERNS:
        match = pattern.fullmatch(clean)
        if match is None:
            continue
        destination = _clean_destination(match.group("destination"))
        if not destination or destination in {
            "forward",
            "backward",
            "back",
            "left",
            "right",
            "here",
        }:
            return None
        # Retain the relation words so semantic parsing can distinguish
        # "inside the sidewalk" from "near the lamppost".
        command = clean[: match.start("destination")]
        return f"{command}{destination}".strip()
    return None


def navigation_directive_is_blocked(text: str) -> bool:
    """Reject language that must never be interpreted as motion authority."""

    return bool(_NEGATED_OR_HYPOTHETICAL.search(_normalized_text(text)))


def pace_from_directive(text: str) -> str | None:
    """Return the canonical pace a directive's verb phrase asks for, else None.

    Table-driven and deliberately shallow: only the first few words after the
    address/politeness prefix are considered, so a pace word appearing inside a
    target name ("walk to the fun run sign") never becomes motion authority.
    """

    clean = _strip_leading_prefixes(_normalized_text(text), strip_pace_adverb=False)
    for word in re.findall(r"[a-z]+", clean)[:_PACE_SCAN_WORDS]:
        pace = PACE_VERB_TABLE.get(word) or PACE_ADVERB_TABLE.get(word)
        if pace is not None:
            return pace
    return None


def owner_referent_from_directive(directive: str) -> str | None:
    """Return the owner-referring target a directive names, else ``None``.

    Pure and table-driven. Callers use it to send the directive down the
    *approach* lane instead of building a ``NavigateTo`` semantic-map query
    (backlog N12); the owner is never a semantic-map label.
    """

    text = " ".join(str(directive).strip().lower().split())
    if not text or navigation_directive_is_blocked(text):
        return None
    goal = semantic_goal_from_directive(text)
    if goal.kind != "object":
        return None
    query = goal.query.strip()
    return query if query in OWNER_REFERENT_TABLE else None


def semantic_goal_from_directive(
    directive: str,
    *,
    relation_hint: str | None = None,
    region_labels: tuple[str, ...] = (),
    object_labels: tuple[str, ...] = (),
    region_support: bool = False,
    person_support: bool = False,
) -> SemanticGoal:
    """Compile a directive into a goal, with R10's hybrid arrival relation.

    Every pre-R10 branch below is UNCHANGED in the relation and kind it emits;
    the arrival table only adds ``face``/``do_not_cross``/``ask_hint`` alongside
    them. One thing is genuinely new, and only in the FINAL default branch: a
    place the region-noun grammar does not recognize but the arrival table
    classifies as a region ("the rug", "the kitchen") now terminates INSIDE
    instead of near, and an accepted model hint may refine an otherwise-unknown
    place the same way. Explicit owner phrasing always outranks both — "wait BY
    the lamppost" stays ``near`` no matter what any table or model says, because
    that is the owner's own word for the relation they want.

    ``relation_hint`` is the hosted model's optional ``navigate_to.relation``
    argument. It is validated by :func:`arrival_semantics.resolve_relation` and
    can only ever agree with the table or refine a genuinely unknown class that
    the local map supports — ``region_support``/``person_support`` are that
    local evidence, and both default False so an unsupported refinement is
    refused by construction rather than by remembering to check.
    """

    text = " ".join(directive.strip().lower().split())
    if not text:
        raise ValueError("empty navigation directive")
    normalized = navigation_directive_from_text(text) or text
    near_relation = bool(_PROXIMITY_RELATION.search(normalized))
    towards_relation = bool(_TOWARDS_RELATION.search(normalized))
    sit_relation = bool(re.search(r"\bsit\b", normalized))
    # Card R20. The noun, the superlative and the attributes come from the one
    # helper the admission gate also calls, so "which word will the grounder be
    # asked for?" has exactly one answer for both. See ``_destination_noun``.
    query, superlative, attributes = _destination_noun(text)
    modifiers: dict[str, object] = {
        "superlative": superlative,
        "attributes": attributes,
        "pace": pace_from_directive(text),
    }
    place_class = classify_place(
        query, region_labels=region_labels, object_labels=object_labels
    )
    decision = resolve_relation(
        place_class,
        relation_hint,
        region_support=region_support,
        person_support=person_support,
    )
    policy = arrival_policy(place_class)
    # The table's local half. NOTHING here is reachable from a tool argument.
    etiquette: dict[str, object] = {
        "place_class": place_class,
        "face": policy.face,
        "do_not_cross": policy.do_not_cross,
        "standoff_m": policy.standoff_m,
        "ask_hint": policy.ask_hint,
        "relation_source": decision.source,
    }
    region = _region_query(query)
    if region:
        return SemanticGoal(
            query=region,
            kind="region",
            terminal_relation="inside",
            terminal_behavior="hold" if near_relation else "stop",
            **modifiers,  # type: ignore[arg-type]
            **etiquette,  # type: ignore[arg-type]
        )
    if towards_relation:
        return SemanticGoal(
            query=query,
            kind="object",
            terminal_relation="towards",
            terminal_behavior="stop",
            **modifiers,  # type: ignore[arg-type]
            **etiquette,  # type: ignore[arg-type]
        )
    if sit_relation and (_NEXT_TO_RELATION.search(normalized) or near_relation):
        return SemanticGoal(
            query=query,
            kind="object",
            terminal_relation="next_to",
            terminal_behavior="hold",
            **modifiers,  # type: ignore[arg-type]
            **etiquette,  # type: ignore[arg-type]
        )
    if near_relation:
        # The owner said "by"/"beside"/"at". Their word wins over every table.
        return SemanticGoal(
            query=query,
            kind="object",
            terminal_relation="near",
            terminal_behavior="hold",
            **modifiers,  # type: ignore[arg-type]
            **etiquette,  # type: ignore[arg-type]
        )
    if planner_relation(decision.relation) == RELATION_INSIDE:
        # A region the region-noun grammar missed, or a supported refinement.
        return SemanticGoal(
            query=query,
            kind="region",
            terminal_relation="inside",
            terminal_behavior="stop",
            **modifiers,  # type: ignore[arg-type]
            **etiquette,  # type: ignore[arg-type]
        )
    return SemanticGoal(
        query=query,
        kind="object",
        terminal_relation="near",
        terminal_behavior="stop",
        **modifiers,  # type: ignore[arg-type]
        **etiquette,  # type: ignore[arg-type]
    )


# --- card R20: unknown-place goal admission ---------------------------------
#
# live_run_1 (2026-08-20, §d): "Go to Narnia." and "Take me to the moon." were
# admitted as ``navigate_to`` goals and ran as missions — 4.25 s and 10.7 s of
# ``state=searching reason=scan_behavior_rotate``, the robot turning on the spot
# hunting for a place that cannot exist — while "let's go home" got a textbook
# ask. R10's ``validate_place`` catches junk ARGUMENT SHAPES ("with owner",
# "run route") and deliberately admits an unheard-of noun for authority parity
# with the typed panel. Both lanes were therefore wrong in the same way, and
# that is why the fix is HERE, in the grammar both lanes compile through,
# instead of in the hosted broker: parity is preserved by making the typed path
# refuse too, not by making the hosted path stricter than it.
#
# Two things this gate is NOT:
#
# * It is not a safety gate. Nothing it refuses was dangerous; the missions it
#   stops were harmless rotations. It is an HONESTY gate, and the failure it
#   prevents is the robot committing out loud ("Okay—I'll go wait near narnia
#   safely.") to something it has no way to do.
# * It is not a ban on exploration. ``_EXPLICIT_SEARCH_PATTERN`` above is the
#   boundary: an owner who says "look for a mailbox" has asked for a search and
#   gets one, unknown noun or not. Only *goal* phrasing — "go to X", "take me
#   to X" — has to name something the robot can resolve.

#: Verdict reasons. Every one of them is reported, including the admissions, so
#: "why did this go through?" is a field rather than an inference.
PLACE_ADMITTED = "known_place"
PLACE_EXPLICIT_SEARCH = "explicit_search"
PLACE_OWNER_REFERENT = "owner_referent"
PLACE_NO_VOCABULARY = "no_vocabulary"
PLACE_NOT_A_DIRECTIVE = "not_a_navigation_directive"
PLACE_UNKNOWN = "unknown_place"

#: How many real places a refusal offers back. Three is the most a spoken
#: sentence carries without turning into a list the owner stops listening to.
PLACE_OFFER_LIMIT = 3


@dataclass(frozen=True)
class PlaceAdmission:
    """May this directive become a goal, and what to say when it may not."""

    admitted: bool
    query: str = ""
    reason: str = ""
    #: Real places to offer instead, nearest first. Empty when the robot's map
    #: has nothing to offer — which is a different sentence, not a shorter one.
    alternatives: tuple[str, ...] = ()

    def fact(self) -> str:
        """The refusal as a FACT, for the hosted model to read and paraphrase.

        Third person and present tense on purpose. R15's rule is that a broker
        detail may not speak in the robot's own voice, because a first-person
        promise is what the model compressed into "Done—I made a small circle
        around you"; the same rule applies to a first-person refusal, which a
        model will happily re-voice as something it decided rather than
        something its map says.
        """

        if not self.alternatives:
            return (
                f"the robot's map has no place called {self.query!r}, and it has no "
                "mapped places to offer instead; ask the owner where they want to go"
            )
        return (
            f"the robot's map has no place called {self.query!r}; the places it does "
            f"know nearby are {_join_places(self.alternatives)}; ask the owner which "
            "of those they mean, or which real place they want"
        )

    def reply(self) -> str:
        """The refusal as a SENTENCE, for the typed lane to say as itself."""

        if not self.alternatives:
            return (
                f'I don\'t know a place called "{self.query}", and I have no mapped '
                "places to offer instead. Could you name somewhere I can see?"
            )
        return (
            f'I don\'t know a place called "{self.query}" — the ones I do know nearby '
            f"are {_join_places(self.alternatives)}. Which would you like?"
        )


def admit_navigation_place(
    directive: str,
    known: Sequence[str] = (),
    *,
    offer: Sequence[str] = (),
) -> PlaceAdmission:
    """May ``directive`` become a navigation goal against this vocabulary?

    ``known`` is the RESOLUTION set — every label, class name and alias the
    grounder could match, in any order. ``offer`` is the OFFER list — real
    places nearest first, which is what makes "the ones I do know nearby are…"
    a true sentence rather than an alphabetical dump. They are separate
    arguments because they answer different questions and come from different
    places; ``offer`` falls back to ``known`` so a caller with only one list
    still gets a refusal that names something.

    **Fail-open on an empty vocabulary, deliberately.** A robot whose map has
    not loaded knows no places at all, and a gate that refused everything then
    would take the whole navigation surface down over a missing sidecar. R10's
    ``_realtime_places`` already made the same call for the same reason. The
    verdict says ``no_vocabulary`` so the difference is visible in the record
    rather than looking like an admission.
    """

    text = " ".join(str(directive).strip().lower().split())
    if not text or navigation_directive_is_blocked(text):
        return PlaceAdmission(True, "", PLACE_NOT_A_DIRECTIVE)
    # JURISDICTION, and it is narrow on purpose. This gate only judges strings
    # the destination grammar itself calls a directive. "go to here" and "go to
    # forward" are excluded destinations that ``navigation_directive_from_text``
    # already returns ``None`` for, and the router refuses them by name — an
    # answer that says which rule declined is better than "I don't know a place
    # called 'here'", and two layers refusing the same string for two different
    # reasons is how a refusal stops meaning anything.
    normalized = navigation_directive_from_text(text)
    if normalized is None:
        return PlaceAdmission(True, "", PLACE_NOT_A_DIRECTIVE)
    if _EXPLICIT_SEARCH_PATTERN.fullmatch(normalized):
        return PlaceAdmission(True, _destination_noun(text)[0], PLACE_EXPLICIT_SEARCH)
    query = _destination_noun(text)[0]
    if not query:
        return PlaceAdmission(True, "", PLACE_NOT_A_DIRECTIVE)
    if query in OWNER_REFERENT_TABLE:
        # N12: the owner is a tracked entity on the owner channel and never a
        # semantic-map label, so "go to me" is resolvable precisely because it
        # is NOT in the place vocabulary. Refusing it here would break the
        # approach lane over a list it was never meant to appear on.
        return PlaceAdmission(True, query, PLACE_OWNER_REFERENT)
    vocabulary = tuple(
        dict.fromkeys(
            " ".join(str(name).split()).lower() for name in known if str(name).strip()
        )
    )
    if not vocabulary:
        return PlaceAdmission(True, query, PLACE_NO_VOCABULARY)
    if _place_is_known(query, vocabulary):
        return PlaceAdmission(True, query, PLACE_ADMITTED)
    return PlaceAdmission(False, query, PLACE_UNKNOWN, _place_offers(offer or known))


def place_query_from_directive(directive: str) -> str:
    """The noun a directive will hand the grounder, or ``""``.

    Public because the admission verdict names it out loud and callers (and
    tests) need the same answer the compiler will reach.
    """

    text = " ".join(str(directive).strip().lower().split())
    return _destination_noun(text)[0] if text else ""


def _place_is_known(query: str, vocabulary: Sequence[str]) -> bool:
    """Can anything in ``vocabulary`` plausibly be what ``query`` names?

    DELIBERATELY PERMISSIVE, because the two errors are not symmetric. Admitting
    a place the grounder then fails to find costs the owner an honest "I looked
    and couldn't find it" — the behaviour that already existed. Refusing a place
    the robot can actually reach costs them the robot. So a match is whole
    phrase, head noun, or either string containing the other as a whole-word
    phrase: "coffee shop" is found inside "coffee shop at 42nd street", and
    "bench" is found inside "the big oak bench".
    """

    if not query:
        return False
    for entry in vocabulary:
        if entry == query or _phrase_within(query, entry) or _phrase_within(entry, query):
            return True
    return False


def _phrase_within(needle: str, haystack: str) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def _place_offers(names: Sequence[str]) -> tuple[str, ...]:
    """The first :data:`PLACE_OFFER_LIMIT` distinct places, order preserved."""

    seen: list[str] = []
    for name in names:
        clean = " ".join(str(name).split())
        if clean and clean.lower() not in {item.lower() for item in seen}:
            seen.append(clean)
        if len(seen) >= PLACE_OFFER_LIMIT:
            break
    return tuple(seen)


def _join_places(names: Sequence[str]) -> str:
    articled = [f"the {name}" for name in names]
    if len(articled) == 1:
        return articled[0]
    return f"{', '.join(articled[:-1])} and {articled[-1]}"


def _destination_noun(text: str) -> tuple[str, str | None, tuple[str, ...]]:
    """``(noun query, superlative, attributes)`` for an already-normalized text.

    Lifted verbatim out of :func:`semantic_goal_from_directive` so card R20's
    admission gate and the goal compiler cannot read the directive differently.
    A gate that refused one noun while the compiler searched for another would
    be the worst of both worlds: it would refuse real places and still admit
    fabricated ones. Sharing the function makes that structurally impossible
    rather than a thing tests have to keep noticing.
    """

    normalized = navigation_directive_from_text(text) or text
    query = normalized
    for pattern in _DESTINATION_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is not None:
            query = _clean_destination(match.group("destination"))
            break
    query = re.sub(r"^(?:the|a|an)\s+", "", query).strip(" .?!") or text
    return _split_noun_phrase(query)


def _strip_leading_prefixes(clean: str, *, strip_pace_adverb: bool = True) -> str:
    """Drop address, politeness, and (optionally) pace-adverb prefixes.

    ``pace_from_directive`` keeps the adverb so it can read it; the directive
    extractor drops it so the verb alternation still matches.
    """

    clean = clean.strip()
    # Addressing the dog and a polite modal can both be present.
    clean = _POLITE_PREFIXES[0].sub("", clean, count=1)
    for prefix in _POLITE_PREFIXES[1:]:
        updated = prefix.sub("", clean, count=1)
        if updated != clean:
            clean = updated
            break
    # "quickly go to the bench" — the adverb is pace, not part of the verb.
    head = clean.split(maxsplit=1)
    if strip_pace_adverb and len(head) == 2 and head[0] in PACE_ADVERB_TABLE:
        clean = head[1]
    return clean.strip()


def _split_noun_phrase(query: str) -> tuple[str, str | None, tuple[str, ...]]:
    """Peel a superlative and size adjectives off a target noun phrase.

    Conservative and fail-safe by construction: only words present in the
    modifier tables are peeled, every other adjective stays part of the noun
    query (so an unknown word still reaches the grounder as it does today), and
    a phrase that would reduce to nothing is returned untouched.

    Returns ``(noun_query, superlative, attributes)`` where ``attributes`` holds
    the surface words the owner said, in order.
    """

    tokens = [token for token in query.replace(",", " ").split() if token]
    if not tokens:
        return query, None, ()
    superlative: str | None = None
    attributes: list[str] = []
    head = 0
    while head < len(tokens):
        token = tokens[head]
        if token in _ARTICLES:
            head += 1
            continue
        if superlative is None and token in SUPERLATIVE_TABLE:
            superlative = SUPERLATIVE_TABLE[token]
            head += 1
            continue
        if token in ATTRIBUTE_TABLE:
            attributes.append(token)
            head += 1
            continue
        break
    tail = len(tokens)
    # Trailing form: "the lamppost nearby".
    if superlative is None and tail - head > 1 and tokens[tail - 1] in SUPERLATIVE_TABLE:
        superlative = SUPERLATIVE_TABLE[tokens[tail - 1]]
        tail -= 1
    noun = " ".join(tokens[head:tail]).strip()
    if not noun:
        # Modifiers only — "go to the nearest" names no target, so keep the
        # phrase intact rather than inventing one.
        return query, None, ()
    return noun, superlative, tuple(attributes)


def _clean_destination(value: str) -> str:
    destination = _RATIONALE_BOUNDARY.split(value, maxsplit=1)[0]
    destination = re.split(r"[.?!]", destination, maxsplit=1)[0]
    return destination.strip(" ,.!?")


def _normalized_text(value: object) -> str:
    text = str(value).translate(
        str.maketrans(
            {
                "\N{LEFT SINGLE QUOTATION MARK}": "'",
                "\N{RIGHT SINGLE QUOTATION MARK}": "'",
                "\N{MODIFIER LETTER APOSTROPHE}": "'",
                "`": "'",
            }
        )
    )
    return " ".join(text.strip().lower().split())


def _region_query(query: str) -> str | None:
    """Classify a region by its noun phrase, not incidental word overlap.

    For example, ``street light`` is an object even though ``street`` alone is
    a traversable region. Bounded positional modifiers still allow phrases such
    as ``nearest sidewalk`` and ``sidewalk ahead``.
    """

    words = re.findall(r"[a-z0-9]+", query)
    for index, word in enumerate(words):
        if word not in _REGION_WORDS:
            continue
        modifiers = words[:index] + words[index + 1 :]
        if all(modifier in _REGION_MODIFIERS for modifier in modifiers):
            return word
    return None
