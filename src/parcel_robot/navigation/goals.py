from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

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


@dataclass(frozen=True)
class SemanticGoal:
    query: str
    kind: GoalKind = "object"
    terminal_relation: str = "near"
    minimum_confidence: float = 0.55
    required_observations: int = 2
    terminal_behavior: str = "stop"


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
_DESTINATION_PATTERNS = (
    re.compile(
        r"^(?:go|navigate|walk|move|head|drive|take\s+me)(?:\s+over)?\s+"
        r"(?:to|onto|into)\s+(?P<destination>.+)$"
    ),
    re.compile(
        r"^(?:wait|stand|stay|go|walk|move)(?:\s+over)?\s+"
        r"(?:by|near|beside|next\s+to|at)\s+(?P<destination>.+)$"
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
    clean = clean.strip()
    # Addressing the dog and a polite modal can both be present.
    clean = _POLITE_PREFIXES[0].sub("", clean, count=1)
    for prefix in _POLITE_PREFIXES[1:]:
        updated = prefix.sub("", clean, count=1)
        if updated != clean:
            clean = updated
            break
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


def semantic_goal_from_directive(directive: str) -> SemanticGoal:
    text = " ".join(directive.strip().lower().split())
    if not text:
        raise ValueError("empty navigation directive")
    normalized = navigation_directive_from_text(text) or text
    near_relation = bool(
        re.search(r"\b(?:by|near|beside|next\s+to|at)\s+(?:the\s+)?", normalized)
    )
    query = normalized
    for pattern in _DESTINATION_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is not None:
            query = _clean_destination(match.group("destination"))
            break
    query = re.sub(r"^(?:the|a|an)\s+", "", query).strip(" .?!") or text
    region = _region_query(query)
    if region:
        return SemanticGoal(
            query=region,
            kind="region",
            terminal_relation="inside",
            terminal_behavior="hold" if near_relation else "stop",
        )
    return SemanticGoal(
        query=query,
        kind="object",
        terminal_relation="near",
        terminal_behavior="hold" if near_relation else "stop",
    )


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
