from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

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


_NEGATED_OR_HYPOTHETICAL = re.compile(
    r"\b(?:do\s+not|don[' ]?t|never|cannot|can[' ]?t|could\s+not|"
    r"couldn[' ]?t|would\s+not|wouldn[' ]?t|should\s+not|shouldn[' ]?t|"
    r"must\s+not|mustn[' ]?t|what\s+if|"
    r"suppose|imagine|pretend)\b"
)
_POLITE_PREFIXES = (
    re.compile(r"^(?:hey\s+)?parcel[,.]?\s+"),
    re.compile(r"^(?:please\s+)?(?:can|could|would|will)\s+you\s+(?:please\s+)?"),
    re.compile(r"^(?:please\s+)?i\s+(?:want|need)\s+you\s+to\s+"),
    re.compile(r"^(?:please\s+)?i(?:'d|\s+would)\s+like\s+you\s+to\s+"),
    re.compile(r"^(?:please|kindly)\s+"),
)
_PACE_VERB_ALTERNATION = "|".join(sorted(PACE_VERB_TABLE, key=len, reverse=True))
_DESTINATION_PATTERNS = (
    re.compile(
        r"^(?:go|navigate|walk|move|head|drive|take\s+me"
        rf"|{_PACE_VERB_ALTERNATION})(?:\s+over)?\s+"
        r"(?:to|onto|into)\s+(?P<destination>.+)$"
    ),
    re.compile(
        r"^(?:go|navigate|walk|move|head"
        rf"|{_PACE_VERB_ALTERNATION})(?:\s+over)?\s+"
        rf"(?:{_TOWARDS_ALIASES})\s+(?P<destination>.+)$"
    ),
    re.compile(
        r"^(?:wait|stand|stay|sit|go|walk|move)(?:\s+over)?\s+"
        rf"(?:{_PROXIMITY_PREPOSITIONS})\s+(?P<destination>.+)$"
    ),
    # Locate-and-approach: the semantic resolution ladder already IS a search
    # (frustum → memory → scan → SearchEntity → honest refusal), so "find the
    # nearest lamppost" is a navigation directive, not a separate verb class.
    # ``find out ...`` is a question and must not become motion authority.
    re.compile(
        r"^(?:find|locate|look\s+for|search\s+for)(?:\s+me)?\s+"
        r"(?!out\b)(?P<destination>.+)$"
    ),
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


def semantic_goal_from_directive(directive: str) -> SemanticGoal:
    text = " ".join(directive.strip().lower().split())
    if not text:
        raise ValueError("empty navigation directive")
    normalized = navigation_directive_from_text(text) or text
    near_relation = bool(_PROXIMITY_RELATION.search(normalized))
    towards_relation = bool(_TOWARDS_RELATION.search(normalized))
    sit_relation = bool(re.search(r"\bsit\b", normalized))
    query = normalized
    for pattern in _DESTINATION_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is not None:
            query = _clean_destination(match.group("destination"))
            break
    query = re.sub(r"^(?:the|a|an)\s+", "", query).strip(" .?!") or text
    query, superlative, attributes = _split_noun_phrase(query)
    modifiers: dict[str, object] = {
        "superlative": superlative,
        "attributes": attributes,
        "pace": pace_from_directive(text),
    }
    region = _region_query(query)
    if region:
        return SemanticGoal(
            query=region,
            kind="region",
            terminal_relation="inside",
            terminal_behavior="hold" if near_relation else "stop",
            **modifiers,  # type: ignore[arg-type]
        )
    if towards_relation:
        return SemanticGoal(
            query=query,
            kind="object",
            terminal_relation="towards",
            terminal_behavior="stop",
            **modifiers,  # type: ignore[arg-type]
        )
    if sit_relation and (_NEXT_TO_RELATION.search(normalized) or near_relation):
        return SemanticGoal(
            query=query,
            kind="object",
            terminal_relation="next_to",
            terminal_behavior="hold",
            **modifiers,  # type: ignore[arg-type]
        )
    if near_relation:
        return SemanticGoal(
            query=query,
            kind="object",
            terminal_relation="near",
            terminal_behavior="hold",
            **modifiers,  # type: ignore[arg-type]
        )
    return SemanticGoal(
        query=query,
        kind="object",
        terminal_relation="near",
        terminal_behavior="hold" if near_relation else "stop",
        **modifiers,  # type: ignore[arg-type]
    )


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
