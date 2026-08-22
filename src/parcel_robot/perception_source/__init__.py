"""Card C-3 — where semantic candidates come from, and the shadow instrument.

``selection`` owns the axis (``oracle`` / ``learned_map`` / ``shadow``) and every
implication of it, including whether the ``demo_pois.yaml`` POI arm may load.
``shadow`` owns the divergence taxonomy, its two denominators, and the
frames-attached evidence rows.

Deliberately NOT here: the noise ladder (``detection_adapter.perception_chain``,
``perception.tier``) and the abstention gate (``perception_abstention``, PG-3).
Those are separate axes owned by other cards; this package selects a source and
consumes their verdicts, it does not fork either.
"""

from __future__ import annotations

from .selection import (
    REGISTERED_SOURCES,
    SOURCE_LEARNED_MAP,
    SOURCE_ORACLE,
    SOURCE_SHADOW,
    SemanticSourcePolicy,
    SemanticSourceRefused,
    active_learned_map,
    active_semantic_source,
    normalize_source,
    use_learned_map,
    use_semantic_source,
)
from .shadow import (
    ADMISSION_FLIP,
    AGREED,
    BENIGN_MISS,
    DIVERGENCE_CLASSES,
    HARD_GATE_CLASSES,
    LOCALIZATION_DELTA,
    REFUSAL_FLIP,
    AgreementRow,
    ArmVerdict,
    Divergence,
    SensingEnvelope,
    ShadowLedger,
    ShadowRefused,
    classify,
    divergence_events,
    envelope_comparability,
)

__all__ = [
    "ADMISSION_FLIP",
    "AGREED",
    "BENIGN_MISS",
    "DIVERGENCE_CLASSES",
    "HARD_GATE_CLASSES",
    "LOCALIZATION_DELTA",
    "REFUSAL_FLIP",
    "REGISTERED_SOURCES",
    "SOURCE_LEARNED_MAP",
    "SOURCE_ORACLE",
    "SOURCE_SHADOW",
    "AgreementRow",
    "ArmVerdict",
    "Divergence",
    "SemanticSourcePolicy",
    "SemanticSourceRefused",
    "SensingEnvelope",
    "ShadowLedger",
    "ShadowRefused",
    "active_learned_map",
    "active_semantic_source",
    "classify",
    "divergence_events",
    "envelope_comparability",
    "normalize_source",
    "use_learned_map",
    "use_semantic_source",
]
