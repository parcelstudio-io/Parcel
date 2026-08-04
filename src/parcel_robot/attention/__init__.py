"""Attention/reaction foundations (pure modules; numpy/stdlib only)."""

from .arbiter import ReactionArbiter, ReactionDecision, ReactionSpec
from .stimuli import (
    Stimulus,
    StimulusBus,
    StimulusKind,
    name_fusion_score,
    summons_prosody_score,
)

__all__ = [
    "ReactionArbiter",
    "ReactionDecision",
    "ReactionSpec",
    "Stimulus",
    "StimulusBus",
    "StimulusKind",
    "name_fusion_score",
    "summons_prosody_score",
]
