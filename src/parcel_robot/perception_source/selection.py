"""Which map answers "where is the bench" — the oracle, or the dog's own map.

Card C-3, the cutover. Before this module every semantic candidate on the
mission path came from MuJoCo ground truth: ``extract_city_semantics`` /
``visible_city_semantics`` read the scene sidecar, stamped ``confidence: 0.98``
by fiat, and handed the rows to ``ObservationSemanticMap.query``. C-2 built a
map the robot writes itself. This module is the switch between them.

**Two axes, not one.**

``perception.tier`` (``detection_adapter.perception_chain``) already exists and
selects how much *noise* is applied to whatever candidates arrive: ``T0`` is the
identity, ``T1`` is the calibrated D455 ladder. It says nothing about where the
candidates came from — both tiers read the oracle.

``perception.semantic_source`` — this module — selects *where the candidates
come from*:

``oracle``
    **The default and the shipped setting.** The MuJoCo GT read, unchanged. A
    policy at this source is short-circuited before a single field of the
    learned map is touched, so the shipping path is the pre-C-3 path by
    construction rather than by measurement.

``learned_map``
    C-2's :class:`~parcel_robot.online_map.OnlineSemanticMap` is the only
    candidate source. Confidences are earned from evidence; there is no 0.98.

``shadow``
    The oracle drives the robot and the learned map runs beside it. Every
    disagreement is classified and logged with the frames that produced it.
    This is the migration instrument, not a deployment mode.

**Why the card's word "T1" is not the config value.** The card says
``perception.tier: T1`` selects the learned map. ``T1`` is already taken in this
tree by the noise ladder, frozen ``nav_instruct`` rows record a ``tier`` field,
and ``tests/test_cam_foundation.py::test_tier_does_not_install_a_perception_chain``
is a hard-gate node id. Redefining it would silently change what an archived
eval row means. So the axes get two keys and one test pins that they are
orthogonal. See ``scrum/20260821/task_13/evidence/C3_PREREGISTRATION.md`` §1,
where the collision was resolved before any code was written.

**The POI arm.** :class:`~parcel_robot.navigation.grounder.PlaceGrounder` fires
BEFORE semantic search and grounds "crosswalk" / "coffee shop" / "park" /
"bookstore" to hardcoded coordinates from ``demo_pois.yaml``. It is a second
oracle, it was owned by no card, and under any source that is supposed to be
reading the dog's own map it must be empty — otherwise a T1-only mission can
"succeed" by consulting a lookup table. :attr:`SemanticSourcePolicy.poi_grounding_enabled`
is that decision, in one place, so a caller cannot forget it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: The MuJoCo ground-truth oracle. The default; byte-identical to pre-C-3.
SOURCE_ORACLE = "oracle"
#: C-2's ``OnlineSemanticMap`` alone. The card calls this "T1".
SOURCE_LEARNED_MAP = "learned_map"
#: Oracle drives, learned map runs beside it, divergences logged. The card calls
#: this "T0_shadow_T1".
SOURCE_SHADOW = "shadow"

#: The COMPLETE set of sources :meth:`SemanticSourcePolicy.from_mapping` accepts.
#: Exported so a claim about a source can be checked instead of believed.
REGISTERED_SOURCES: tuple[str, ...] = (SOURCE_ORACLE, SOURCE_LEARNED_MAP, SOURCE_SHADOW)

#: The card's vocabulary, accepted as input spellings and normalised to the
#: keys above. ``T1`` is deliberately NOT in this table: it is a registered
#: *tier* name and accepting it here would recreate exactly the ambiguity §1 of
#: the pre-registration resolved. ``T1_MAP`` is the unambiguous spelling.
_SPELLINGS: dict[str, str] = {
    "oracle": SOURCE_ORACLE,
    "t0": SOURCE_ORACLE,
    "ground_truth": SOURCE_ORACLE,
    "learned_map": SOURCE_LEARNED_MAP,
    "t1_map": SOURCE_LEARNED_MAP,
    "online_map": SOURCE_LEARNED_MAP,
    "shadow": SOURCE_SHADOW,
    "t0_shadow_t1": SOURCE_SHADOW,
    "t0_shadow_t1_map": SOURCE_SHADOW,
}


class SemanticSourceRefused(ValueError):
    """A source configuration that cannot be honoured. Never a silent default."""


def normalize_source(value: object) -> str:
    """Accept the card's spellings; refuse anything else, loudly.

    ``T1`` is refused with the reason, because a config that says ``T1`` and
    means "read the learned map" would otherwise silently select the oracle
    with a noise ladder on top — the failure this whole two-axis split exists
    to make impossible.
    """

    if isinstance(value, bool) or not isinstance(value, str):
        raise SemanticSourceRefused(
            "perception.semantic_source must be a string; "
            f"registered sources are {list(REGISTERED_SOURCES)}"
        )
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    if key == "t1":
        raise SemanticSourceRefused(
            "perception.semantic_source: 'T1' is ambiguous and is refused. 'T1' is "
            "a registered perception TIER (the calibrated noise ladder over the "
            "oracle, detection_adapter.perception_chain.REGISTERED_TIERS) and it "
            "does not change where candidates come from. If you meant the card's "
            "T1 — read C-2's learned map — write 'learned_map' (or 'T1_MAP'). "
            "If you meant the noise ladder, set perception.tier, not "
            "perception.semantic_source."
        )
    try:
        return _SPELLINGS[key]
    except KeyError:
        raise SemanticSourceRefused(
            f"unknown perception.semantic_source: {value!r}; registered sources "
            f"are {list(REGISTERED_SOURCES)}"
        ) from None


@dataclass(frozen=True)
class SemanticSourcePolicy:
    """Where semantic candidates come from, and what that implies elsewhere.

    Every implication of the source lives on this object rather than being
    re-derived at each call site. A consumer that asks "should the POI table be
    loaded" gets the same answer as the consumer that asks "should the learned
    map be read", because there is one object answering both.
    """

    source: str = SOURCE_ORACLE
    #: Log divergences even outside ``shadow``. Off by default; ``shadow``
    #: turns it on regardless, because a shadow run that logs nothing is not a
    #: shadow run.
    log_divergence: bool = False

    def __post_init__(self) -> None:
        if self.source not in REGISTERED_SOURCES:
            raise SemanticSourceRefused(
                f"unknown semantic source: {self.source!r}; registered sources "
                f"are {list(REGISTERED_SOURCES)}"
            )
        if not isinstance(self.log_divergence, bool):
            raise SemanticSourceRefused(
                "perception.semantic_source_log_divergence must be a boolean"
            )

    # -- what the source means, asked once, answered once -------------------

    @property
    def is_oracle(self) -> bool:
        """True on the shipping default. Callers short-circuit on this."""

        return self.source == SOURCE_ORACLE

    @property
    def reads_learned_map(self) -> bool:
        """Whether C-2's map is consulted at all this run."""

        return self.source in (SOURCE_LEARNED_MAP, SOURCE_SHADOW)

    @property
    def drives_from_learned_map(self) -> bool:
        """Whether the learned map's answer is the one the robot ACTS on.

        False under ``shadow`` — that is the whole point of shadow mode. A
        consumer that confuses this with :attr:`reads_learned_map` would let the
        migration instrument drive the robot.
        """

        return self.source == SOURCE_LEARNED_MAP

    @property
    def divergence_logging(self) -> bool:
        return self.source == SOURCE_SHADOW or self.log_divergence

    @property
    def poi_grounding_enabled(self) -> bool:
        """REVISION §1. The POI table is a second oracle; it is OFF off-oracle.

        ``PlaceGrounder`` grounds four ``demo_pois.yaml`` classes to hardcoded
        coordinates before semantic search ever runs. Under ``learned_map`` a
        "successful" mission through that path measures a lookup table, and
        under ``shadow`` it would make both arms agree for a reason that has
        nothing to do with either map.
        """

        return self.source == SOURCE_ORACLE

    def as_dict(self) -> dict[str, Any]:
        """The whole policy, for an evidence row or an ``/api/state`` block."""

        return {
            "semantic_source": self.source,
            "reads_learned_map": self.reads_learned_map,
            "drives_from_learned_map": self.drives_from_learned_map,
            "divergence_logging": self.divergence_logging,
            "poi_grounding_enabled": self.poi_grounding_enabled,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> SemanticSourcePolicy:
        """Read the ``perception:`` block. Absent key ⇒ oracle ⇒ unchanged.

        Unknown ``semantic_source*`` keys fail closed for the same reason the
        abstention block does: a typo that reads as "the default" looks exactly
        like a switch that never flipped.
        """

        if not data:
            return cls()
        if not isinstance(data, Mapping):
            raise SemanticSourceRefused(
                "perception block must be a mapping"
            )
        known = {"semantic_source", "semantic_source_log_divergence"}
        present = {key for key in data if str(key).startswith("semantic_source")}
        unknown = sorted(present - known)
        if unknown:
            raise SemanticSourceRefused(
                f"unknown perception.semantic_source key(s): {', '.join(unknown)}"
            )
        if "semantic_source" not in data:
            # Absent means absent. Do not construct from a partial block: a
            # config that sets only the log flag has not chosen a source.
            if "semantic_source_log_divergence" in data:
                raise SemanticSourceRefused(
                    "perception.semantic_source_log_divergence was set without "
                    "perception.semantic_source; a run that logs divergence "
                    "without naming a source has not chosen one"
                )
            return cls()
        source = normalize_source(data["semantic_source"])
        raw_log = data.get("semantic_source_log_divergence", False)
        if not isinstance(raw_log, bool):
            raise SemanticSourceRefused(
                "perception.semantic_source_log_divergence must be a boolean"
            )
        return cls(source=source, log_divergence=raw_log)


#: The process-default policy. Mirrors ``perception_abstention``'s
#: ``active_abstention_policy`` and ``perception_chain``'s
#: ``active_perception_chain`` so there is ONE house convention for "what is
#: installed on the mission path", not three.
_ACTIVE_SOURCE = SemanticSourcePolicy()


def active_semantic_source() -> SemanticSourcePolicy:
    """The source every ingress consults. Oracle until something installs otherwise."""

    return _ACTIVE_SOURCE


def use_semantic_source(policy: SemanticSourcePolicy | None) -> None:
    """Install (or reset to oracle, with ``None``) the process-default source."""

    global _ACTIVE_SOURCE
    if policy is None:
        _ACTIVE_SOURCE = SemanticSourcePolicy()
        return
    if not isinstance(policy, SemanticSourcePolicy):
        raise TypeError("policy must be a SemanticSourcePolicy or None")
    _ACTIVE_SOURCE = policy


#: The map the non-oracle sources read. C-2 builds and owns the object; this is
#: only the seam that says WHICH instance the mission path is reading, in the
#: same shape as the two seams above. It is ``None`` until something installs
#: one, and a source that reads the learned map with nothing installed answers
#: with no candidates rather than falling back to the oracle — a silent fallback
#: to ground truth is precisely the failure this card exists to remove.
_ACTIVE_LEARNED_MAP: Any = None


def active_learned_map() -> Any:
    """The ``OnlineSemanticMap`` installed on the mission path, or ``None``."""

    return _ACTIVE_LEARNED_MAP


def use_learned_map(learned_map: Any) -> None:
    """Install (or clear, with ``None``) the process-default learned map.

    Duck-typed on purpose: the contract this seam needs is ``around_me`` /
    ``active_entries`` / ``navigability`` / ``resolve``, and requiring the
    concrete class would make the seam untestable without a store on disk. The
    four methods are checked, so a wrong object is refused here rather than
    discovered as an empty candidate list three layers down.
    """

    global _ACTIVE_LEARNED_MAP
    if learned_map is None:
        _ACTIVE_LEARNED_MAP = None
        return
    missing = [
        name
        for name in ("around_me", "active_entries", "navigability", "resolve")
        if not callable(getattr(learned_map, name, None))
    ]
    if missing:
        raise TypeError(
            "a learned map must provide "
            f"{', '.join(sorted(missing))} — got {type(learned_map).__name__}"
        )
    _ACTIVE_LEARNED_MAP = learned_map
