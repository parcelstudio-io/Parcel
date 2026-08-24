from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .base import GoalPose


class PlaceGrounder:
    """Map natural-language directives to city POI goals.

    **Card C-3 / REVISION §1: this is a second oracle.** It fires BEFORE
    semantic search (``pipeline.DirectiveNavigator.parse``) and grounds any
    directive containing one of ``demo_pois.yaml``'s four class names —
    "coffee shop", "bookstore", "park", "crosswalk" — to a hardcoded
    coordinate, tagged ``goal_source: known_poi``. Nothing about that path
    consults perception. Under a semantic source that is supposed to be reading
    the dog's own map, a mission that "succeeds" through here has measured a
    lookup table, so the POI arm is constructed EMPTY off-oracle.

    ``disabled_reason`` is carried rather than implied: an empty table because
    the operator emptied the YAML and an empty table because the source is
    ``learned_map`` are different facts, and a harness proving the cutover has
    to be able to tell them apart.
    """

    def __init__(self, pois: list[dict[str, Any]], *, disabled_reason: str = ""):
        self.pois = pois
        self.disabled_reason = str(disabled_reason)

    @property
    def enabled(self) -> bool:
        """Whether the POI arm can ground anything at all."""

        return not self.disabled_reason and bool(self.pois)

    @classmethod
    def from_yaml(cls, path: str | Path) -> PlaceGrounder:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(list(data.get("pois") or []))

    @classmethod
    def disabled(cls, reason: str) -> PlaceGrounder:
        """An empty POI arm that says why it is empty."""

        if not reason:
            raise ValueError("a disabled PlaceGrounder must carry its reason")
        return cls([], disabled_reason=reason)

    @classmethod
    def for_semantic_source(cls, path: str | Path, policy: Any = None) -> PlaceGrounder:
        """Load the POI table only when the semantic source is the oracle.

        ``policy=None`` consults the process-default source, which ships as
        ``oracle`` — so the shipping construction is exactly
        :meth:`from_yaml` and the default path is unchanged.

        Fail-CLOSED on the union: if either the caller's policy or the
        process-default is off-oracle, the table stays empty. Disabling a
        lookup table can only make grounding more honest; the asymmetry is
        deliberate.
        """

        try:
            from parcel_robot.perception_source.selection import active_semantic_source
        except ImportError:  # pragma: no cover — frozen BARN bundle path
            return cls.from_yaml(path)
        candidates = [active_semantic_source()]
        if policy is not None:
            candidates.append(policy)
        # ONE check, deliberately. An earlier draft also tested
        # ``source != SOURCE_ORACLE`` here as belt-and-braces, and the seeded
        # defect for "the POI table is re-enabled off-oracle" came back GREEN:
        # the second guard caught the mutation and the harness could no longer
        # see the first one fail. Redundancy that hides a defect from its own
        # seed is worse than no redundancy, so the decision lives in exactly one
        # place — ``SemanticSourcePolicy.poi_grounding_enabled``.
        for candidate in candidates:
            if not getattr(candidate, "poi_grounding_enabled", True):
                source = getattr(candidate, "source", "non-oracle")
                return cls.disabled(
                    f"perception.semantic_source={source!r}: the POI table is a "
                    "second oracle and is empty off-oracle (card C-3 REVISION 1)"
                )
        return cls.from_yaml(path)

    def ground(self, directive: str) -> GoalPose:
        text = directive.strip().lower()
        if not text:
            raise ValueError("empty navigation directive")

        if self.disabled_reason:
            # LookupError is the existing "not a POI" signal and the caller
            # already falls through to semantic search on it. Raising the same
            # type keeps the disable a SOURCE decision rather than a new control
            # path — but the reason travels, so a harness can prove the POI arm
            # was off rather than merely unlucky.
            raise LookupError(f"POI grounding is disabled: {self.disabled_reason}")

        scored: list[tuple[int, dict[str, Any]]] = []
        for poi in self.pois:
            score = 0
            label = str(poi.get("label") or poi.get("id") or "").lower()
            names = [str(n).lower() for n in (poi.get("names") or poi.get("aliases") or [])]
            street = str(poi.get("street", "")).lower()
            category = str(poi.get("category", "")).lower()

            for token in names + ([label] if label else []):
                if token and token in text:
                    score += 5
            if street and street in text:
                score += 3
            if category and category in text:
                score += 1
            # Whole words only. A substring test scored "near" (from the POI
            # name "crosswalk near coffee") inside "the nearest lamppost" and
            # grounded a superlative object directive to the crosswalk POI,
            # which then never reached the semantic path at all.
            for word in re.findall(r"[a-z0-9]+", " ".join(names) + " " + label):
                if len(word) >= 4 and re.search(rf"\b{re.escape(word)}\b", text):
                    score += 1
            if score > 0:
                scored.append((score, poi))

        if not scored:
            raise LookupError(
                f"could not ground directive to a known place: {directive!r}. "
                f"Known POIs: {[p.get('id') for p in self.pois]}"
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        poi = scored[0][1]
        xyz = poi.get("position") or poi.get("xyz") or [0.0, 0.0, 0.0]
        label = str(poi.get("label") or (poi.get("names") or [poi.get("id", "")])[0])
        return GoalPose(
            x=float(xyz[0]),
            y=float(xyz[1]),
            z=float(xyz[2]) if len(xyz) > 2 else 0.0,
            heading_deg=float(poi.get("heading_deg", 0.0)),
            poi_id=str(poi.get("id", "")),
            label=label,
        )
