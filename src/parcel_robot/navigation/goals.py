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


@dataclass(frozen=True)
class SemanticGoal:
    query: str
    kind: GoalKind = "object"
    terminal_relation: str = "near"
    minimum_confidence: float = 0.55
    required_observations: int = 2


def semantic_goal_from_directive(directive: str) -> SemanticGoal:
    text = " ".join(directive.strip().lower().split())
    if not text:
        raise ValueError("empty navigation directive")
    # Remove command framing but keep the owner's destination wording.
    query = re.sub(
        r"^(?:i want you to |please )?(?:go|navigate|walk|take me|move)(?: over)? to\s+(?:the\s+)?",
        "",
        text,
    ).strip(" .")
    query = query or text
    words = set(re.findall(r"[a-z0-9]+", query))
    region = next((word for word in _REGION_WORDS if word in words), None)
    if region:
        return SemanticGoal(query=region, kind="region", terminal_relation="inside")
    return SemanticGoal(query=query, kind="object", terminal_relation="near")
