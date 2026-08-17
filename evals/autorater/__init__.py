"""Conversation-quality AutoRaters for Parcel.

Compare a base and a test response — single-turn or multi-turn, with metadata —
and return either a signed "which was better" score or a countable side metric
such as the number of punts.

    from evals.autorater import RatingRequest, Response, Turn, default_registry

Rated scores are only comparable within one ``rater_id@rater_version``.
"""

from evals.autorater.base import (
    AutoRater,
    ComparativeAutoRater,
    JudgeBackend,
    JudgeError,
    RaterRegistry,
    SideMetricAutoRater,
    parse_judge_json,
)
from evals.autorater.raters import (
    HonestyRater,
    LlamaCppJudge,
    LLMPuntRater,
    MultiTurnCoherenceRater,
    PairwiseQualityRater,
    PersonaConsistencyRater,
    RulePuntRater,
    ScriptedJudge,
    default_registry,
)
from evals.autorater.types import (
    ComparativeVerdict,
    MetricDelta,
    RatingRequest,
    Response,
    SideMetric,
    Turn,
)

__all__ = [
    "AutoRater",
    "ComparativeAutoRater",
    "ComparativeVerdict",
    "HonestyRater",
    "JudgeBackend",
    "JudgeError",
    "LLMPuntRater",
    "LlamaCppJudge",
    "MetricDelta",
    "MultiTurnCoherenceRater",
    "PairwiseQualityRater",
    "PersonaConsistencyRater",
    "RaterRegistry",
    "RatingRequest",
    "Response",
    "RulePuntRater",
    "ScriptedJudge",
    "SideMetric",
    "SideMetricAutoRater",
    "Turn",
    "default_registry",
    "parse_judge_json",
]
