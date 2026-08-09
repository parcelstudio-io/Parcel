"""Conversation lane helpers: DialogueAct shapes, no physical tool schemas (K6/B1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from parcel_robot.contracts.v1 import SCHEMA_VERSION, DialogueActV1, DialogueClaimV1

# Physical authority must never appear in the conversation-lane schema.
PHYSICAL_TOOL_NAMES = frozenset(
    {
        "run_pose",
        "run_skill",
        "set_velocity",
        "set_motion_backend",
        "navigate",
        "set_behavior",
        "run_spatial_behavior",
        "stop_motion",
    }
)

# Conversation may read status / info tools only.
CONVERSATION_ALLOWED_TOOLS = frozenset({"get_status"})


def strip_physical_tools(
    tools: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return tool schemas safe for the conversation model (fail-closed)."""

    kept: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            continue
        # Drop every physical authority schema. get_status and info tools remain.
        if name in PHYSICAL_TOOL_NAMES:
            continue
        kept.append(dict(tool))
    return kept


def conversation_tool_definitions(
    all_tools: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Conversation-lane schema: strip every physical tool definition."""

    return strip_physical_tools(all_tools)


def dialogue_act_from_text(
    *,
    turn_id: str,
    text: str,
    speech_style: str = "neutral",
    acknowledgement_kind: str = "reply",
    asks_clarification: bool = False,
    claims: Sequence[DialogueClaimV1] = (),
    social_cues: Sequence[str] = (),
) -> DialogueActV1:
    """Build a contracts DialogueActV1 for the conversation lane."""

    return DialogueActV1(
        schema_version=SCHEMA_VERSION,
        turn_id=turn_id,
        text=text,
        speech_style=speech_style,
        acknowledgement_kind=acknowledgement_kind,
        claims=tuple(claims),
        social_cues=tuple(social_cues),
        asks_clarification=asks_clarification,
    )


def tentative_claim(text: str, *, evidence_ref: str = "conversation") -> DialogueClaimV1:
    return DialogueClaimV1(
        text=text,
        veracity="tentative",
        evidence_ref=evidence_ref,
    )


__all__ = [
    "CONVERSATION_ALLOWED_TOOLS",
    "PHYSICAL_TOOL_NAMES",
    "conversation_tool_definitions",
    "dialogue_act_from_text",
    "strip_physical_tools",
    "tentative_claim",
]
