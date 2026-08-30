"""Scene admission for the demo POI table — card C1 (POI-ORACLE-1), follow-up F1.

``PlaceGrounder`` answers a directive out of ``configs/navigation/cities/
demo_pois.yaml`` before semantic search ever runs, so "go to the crosswalk"
resolved to a hardcoded coordinate no matter which scene was loaded. NAV-GEN-1
measured what that costs on 30 procedurally generated scenes: 90/90 crosswalk
episodes ground to ``crosswalk_a`` at ``(3.5, -0.6)``, 42 of them declaring
``arrived`` with the body in no crosswalk at all (``research/20260829/
nav-gen-attribution-1/RESULTS.md`` §5.3, ``VERDICT.md`` §1.1/§5.2).

**The rule is IDENTITY, not geometry** (integrator's F1 ruling). A POI table's
coordinates are facts about ONE scene — ``demo_pois.yaml`` says so itself:
``crosswalk_a`` is "kept inside the compact MuJoCo city block for an end-to-end
demo". A polygon on generated seed 880027 that happens to contain
``(3.5, -0.6)`` does not make "crosswalk near coffee, 42nd street" true on that
seed; answering there is a coincidence, and C1's own first cut measured the
cost of honouring it — the 15 coincidence-admitted episodes carried all 6
remaining false arrivals while the 75 refused ones carried none.

So: **the table declares the scene it was surveyed on** (``scene_id`` in the
YAML) and a POI may answer only while the loaded scene IS that scene.

* :data:`OUTCOME_ADMITTED` — loaded scene id == the table's declared id.
* :data:`OUTCOME_SCENE_MISMATCH` — some other scene is loaded. Refused;
  ``mission.metadata['poi_refused'] = "scene_mismatch:<loaded>/<declared>"``.
* :data:`OUTCOME_NO_SCENE` — nothing published a scene, so nothing can vouch
  for the coordinates. Refused, token ``"no_scene"``. A real robot running
  under the oracle source must never be answered by the demo table.

The geometric predicate C1 shipped first (is an instance of the POI's class
within a body's reach of the coordinate?) survives **only as a diagnostic** on
:class:`PoiAdmission` — ``geometry_backed`` / ``nearest_instance_id`` /
``nearest_distance_m``. It never decides admission. It is kept because it is
what distinguishes "this scene has nothing like that place" from "this scene
has one and the table still isn't talking about it", which is exactly the
distinction the F1 ruling turns on.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE

#: DIAGNOSTIC ONLY (F1): the band the demoted geometric predicate reports on.
#: A body standing on the POI coordinate touches the instance's arrival
#: geometry. Read off the profile so a half-size robot reports a tighter band.
DIAGNOSTIC_BAND_M: float = DEFAULT_ROBOT_PROFILE.footprint_radius_m

OUTCOME_ADMITTED = "admitted"
OUTCOME_SCENE_MISMATCH = "scene_mismatch"
OUTCOME_NO_SCENE = "no_scene"

#: The metadata token for "no venue published a scene" (F1 requirement 4).
REASON_NO_SCENE = "no_scene"


@dataclass(frozen=True)
class SceneInstance:
    """One semantic instance the loaded scene declares, with its geometry.

    Regions carry a polygon; objects carry a centre and the declared goal band
    (the annulus the K0 arrival authority already uses). Both are read from the
    metadata the extractor emits — no geometry is restated here. Since F1 this
    is diagnostic material only.
    """

    instance_id: str
    label: str
    aliases: tuple[str, ...] = ()
    polygon: tuple[tuple[float, float], ...] = ()
    center: tuple[float, float] | None = None
    band_m: tuple[float, float] | None = None

    def distance_to_arrival_geometry(self, x: float, y: float) -> float:
        """Metres from ``(x, y)`` to this instance's arrival geometry; 0 inside."""

        if self.polygon:
            return _polygon_distance(x, y, self.polygon)
        if self.center is None:
            return math.inf
        distance = math.hypot(x - self.center[0], y - self.center[1])
        if self.band_m is None:
            return distance
        low, high = float(self.band_m[0]), float(self.band_m[1])
        if distance < low:
            return low - distance
        if distance > high:
            return distance - high
        return 0.0

    def class_names(self) -> tuple[str, ...]:
        """The class names this instance answers to: its label and its aliases."""

        names = (_normalized(self.label), *(_normalized(alias) for alias in self.aliases))
        return tuple(name for name in names if name)


@dataclass(frozen=True)
class SceneInstanceSet:
    """The loaded scene: WHICH scene it is, and what it declares.

    ``scene_id`` is the identity F1 admits on — the MJCF's own ``model`` name
    (``parcel_city_block`` for the demo block, ``parcel_val_unseen_880027`` for
    a generated seed). The instances are diagnostic.
    """

    scene_id: str
    instances: tuple[SceneInstance, ...]
    #: The spec lists this was built from, kept ONLY for an identity check, so
    #: a venue re-publishing the same two lists costs two ``is`` comparisons
    #: instead of a rebuild. Holding the references also makes ``is`` safe — a
    #: list we hold cannot be freed and have its address reused.
    source_regions: Any = field(default=None, repr=False, compare=False)
    source_objects: Any = field(default=None, repr=False, compare=False)
    _source_lengths: tuple[int, int] = field(default=(-1, -1), repr=False, compare=False)

    def is_view_of(self, regions: Any, objects: Any) -> bool:
        return (
            self.source_regions is regions
            and self.source_objects is objects
            and len(regions) == self._source_lengths[0]
            and len(objects) == self._source_lengths[1]
        )

    def matching(self, tokens: frozenset[str]) -> tuple[SceneInstance, ...]:
        return tuple(
            item for item in self.instances if any(name in tokens for name in item.class_names())
        )

    def instance_ids(self) -> tuple[str, ...]:
        """The legal instance ids of this scene, in declaration order."""

        return tuple(item.instance_id for item in self.instances)


@dataclass(frozen=True)
class PoiAdmission:
    """Whether the loaded scene lets this POI answer a directive, and why.

    ``reason`` is the token that reaches ``mission.metadata['poi_refused']``
    (F1 requirement 4): ``"scene_mismatch:<loaded>/<declared>"`` or
    ``"no_scene"``. ``detail`` is the prose for a human reading a log. The
    three ``geometry`` fields are DIAGNOSTIC and never decide anything.
    """

    admitted: bool
    outcome: str
    reason: str = ""
    detail: str = ""
    loaded_scene_id: str = ""
    declared_scene_id: str = ""
    geometry_backed: bool | None = None
    nearest_instance_id: str = ""
    nearest_distance_m: float | None = None


class PoiRefused(LookupError):
    """The loaded scene is not the scene this POI table was surveyed on.

    ``LookupError`` is the existing "not a POI" signal and ``parse`` already
    falls through to semantic search on it, so the refusal stays a SOURCE
    decision rather than a new control path — but the reason travels, so a
    harness can tell "the directive named no POI" from "the POI was refused",
    exactly as ``disabled_reason`` did for the off-oracle empty table.
    """

    def __init__(self, admission: PoiAdmission, poi_id: str = ""):
        super().__init__(admission.reason or admission.outcome)
        self.admission = admission
        self.poi_id = poi_id


# ---------------------------------------------------------------------------
# The published scene.
#
# The navigator cannot see the world it drives: ``DirectiveNavigator`` is built
# from a config path (``simulation/headless_city.py:735``), and every scene fact
# reaches it through per-frame observations that do not exist yet when ``parse``
# runs. So the scene publishes itself where it is READ — ``extract_city_semantics``
# is the one place that holds both the compiled model (whose ``model`` name is
# the scene's identity) and the semantic specs, and every venue that loads a
# city scene goes through it before it builds a navigator. Same process-scoped
# published-source idiom ``perception_source.selection`` uses for the active
# semantic source and the learned map; the state and the types live here.
# ---------------------------------------------------------------------------

_ACTIVE: SceneInstanceSet | None = None


def scene_id_from_model(model: Any) -> str:
    """The scene's own identity: the MJCF ``<mujoco model="...">`` name.

    MuJoCo writes the model name first in its ``names`` blob. An unnamed model
    yields ``""``, which is not an identity and therefore cannot match a POI
    table's declaration — the refusing direction, deliberately.
    """

    names = getattr(model, "names", b"")
    if isinstance(names, bytes):
        return names.split(b"\x00")[0].decode("utf-8", "replace")
    return str(names or "").split("\x00")[0]


def publish_scene_semantics(
    regions: Sequence[Mapping[str, Any]],
    objects: Sequence[Mapping[str, Any]],
    *,
    scene_id: str = "",
) -> SceneInstanceSet:
    """Publish the loaded scene — its identity and what it declares."""

    global _ACTIVE
    active = _ACTIVE
    if active is not None and active.scene_id == str(scene_id) and active.is_view_of(
        regions, objects
    ):
        return active
    _ACTIVE = SceneInstanceSet(
        scene_id=str(scene_id),
        instances=scene_instances_from_specs(regions, objects),
        source_regions=regions,
        source_objects=objects,
        _source_lengths=(len(regions), len(objects)),
    )
    return _ACTIVE


def active_scene_instances() -> SceneInstanceSet | None:
    """The published scene, or ``None`` when no venue has published one."""

    return _ACTIVE


def clear_scene_instances() -> None:
    """Forget the published scene (a test; a venue tearing its world down)."""

    global _ACTIVE
    _ACTIVE = None


def scene_instances_from_specs(
    regions: Sequence[Mapping[str, Any]],
    objects: Sequence[Mapping[str, Any]],
) -> tuple[SceneInstance, ...]:
    """Typed instances from the region/object specs the extractor emits."""

    out: list[SceneInstance] = []
    for item in regions or ():
        polygon = tuple(
            (float(point[0]), float(point[1])) for point in (item.get("polygon") or ())
        )
        if len(polygon) < 3:
            continue
        out.append(
            SceneInstance(
                instance_id=str(item.get("id", "")),
                label=str(item.get("label", "")),
                aliases=_aliases(item),
                polygon=polygon,
            )
        )
    for item in objects or ():
        position = tuple(item.get("position") or ())
        if len(position) < 2:
            continue
        metadata = item.get("metadata") or {}
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        goal_region = metadata.get("goal_region") or {}
        band = goal_region.get("band_m") if isinstance(goal_region, Mapping) else None
        if band is None and metadata.get("vicinity_radius_m") is not None:
            band = (0.0, float(metadata["vicinity_radius_m"]))
        out.append(
            SceneInstance(
                instance_id=str(item.get("id", "")),
                label=str(item.get("label", "")),
                aliases=_aliases(item),
                center=(float(position[0]), float(position[1])),
                band_m=(float(band[0]), float(band[1])) if band is not None else None,
            )
        )
    return tuple(out)


def poi_class_tokens(poi: Mapping[str, Any]) -> frozenset[str]:
    """The class names a POI row claims: its category, its label, its names.

    Diagnostic since F1 (it is what the demoted geometric predicate matches
    on). Matching is exact on a normalized name, never substring: ``door``'s
    alias "entrance" is a whole word inside the POI name "park entrance", and a
    substring rule would let a doorway speak for a park.
    """

    tokens = {
        _normalized(poi.get("category")),
        _normalized(poi.get("label")),
        *(_normalized(name) for name in (poi.get("names") or poi.get("aliases") or ())),
    }
    return frozenset(token for token in tokens if token)


def geometry_diagnostic(
    poi: Mapping[str, Any],
    scene: SceneInstanceSet | None,
    *,
    band_m: float = DIAGNOSTIC_BAND_M,
) -> tuple[bool | None, str, float | None]:
    """DIAGNOSTIC ONLY — would the loaded scene's own geometry back this POI?

    Returns ``(backed, nearest_instance_id, distance_m)``; ``backed`` is
    ``None`` when the scene declares no instance of the POI's class at all.
    **Never** consulted by :func:`admit_poi`: on generated seed 880027 this
    says "backed" for a coordinate the table has no business answering there,
    which is precisely why F1 demoted it.
    """

    if scene is None:
        return None, "", None
    position = tuple(poi.get("position") or poi.get("xyz") or ())
    if len(position) < 2:
        return None, "", None
    x, y = float(position[0]), float(position[1])
    candidates = scene.matching(poi_class_tokens(poi))
    if not candidates:
        return None, "", None
    nearest = min(candidates, key=lambda item: item.distance_to_arrival_geometry(x, y))
    distance = nearest.distance_to_arrival_geometry(x, y)
    return distance <= band_m, nearest.instance_id, distance


def admit_poi(
    poi: Mapping[str, Any],
    *,
    scene: SceneInstanceSet | None,
    declared_scene_id: str,
) -> PoiAdmission:
    """F1: a POI answers only while the scene it was surveyed on is loaded."""

    poi_id = str(poi.get("id", "")) or "<unnamed>"
    declared = str(declared_scene_id or "")
    backed, nearest_id, distance = geometry_diagnostic(poi, scene)
    if scene is None:
        return PoiAdmission(
            False,
            OUTCOME_NO_SCENE,
            reason=REASON_NO_SCENE,
            detail=(
                f"no venue published a scene, so nothing vouches for {poi_id}'s "
                f"coordinates; the demo POI table declares scene {declared!r}"
            ),
            declared_scene_id=declared,
        )
    loaded = scene.scene_id
    if declared and loaded == declared:
        return PoiAdmission(
            True,
            OUTCOME_ADMITTED,
            detail=f"the loaded scene IS {declared!r}, the scene {poi_id} was surveyed on",
            loaded_scene_id=loaded,
            declared_scene_id=declared,
            geometry_backed=backed,
            nearest_instance_id=nearest_id,
            nearest_distance_m=distance,
        )
    return PoiAdmission(
        False,
        OUTCOME_SCENE_MISMATCH,
        reason=f"{OUTCOME_SCENE_MISMATCH}:{loaded}/{declared}",
        detail=(
            f"{poi_id} is a place in scene {declared or '<undeclared>'!r}; the loaded scene is "
            f"{loaded or '<unnamed>'!r}"
            + (
                f" (the scene's own {nearest_id!r} is {distance:.2f} m from the coordinate — "
                "a coincidence, not a reason to answer)"
                if backed
                else ""
            )
        ),
        loaded_scene_id=loaded,
        declared_scene_id=declared,
        geometry_backed=backed,
        nearest_instance_id=nearest_id,
        nearest_distance_m=distance,
    )


def ground_admitted_poi(grounder: Any, directive: str) -> Any:
    """``grounder.ground(directive)``, admitted only on the table's own scene.

    Deliberately a module function taking the grounder rather than a method on
    it: a frozen BARN v8 bundle ships a ``PlaceGrounder`` that predates this
    card while taking ``pipeline.py`` as a reviewed replacement source, and
    ``pipeline._build_grounder`` exists precisely because calling a method that
    copy does not have turned a whole derivation into an ``AttributeError``.
    A table with no ``scene_id`` (that bundle's copy; a hand-built table) can
    never match a loaded scene, which is the refusing direction.
    """

    goal = grounder.ground(directive)
    poi_id = str(getattr(goal, "poi_id", "") or "")
    admission = admit_poi(
        _poi_row(grounder, goal, poi_id),
        scene=active_scene_instances(),
        declared_scene_id=str(getattr(grounder, "scene_id", "") or ""),
    )
    if not admission.admitted:
        raise PoiRefused(admission, poi_id=poi_id)
    return goal


def poi_lookup_metadata(grounder: Any, error: BaseException) -> dict[str, str]:
    """The mission-metadata keys that say why no POI answered this directive.

    ``poi_grounding_disabled`` (card C-3 REVISION 1: the table is empty off
    oracle) and ``poi_refused`` (card C1/F1: the loaded scene is not the
    table's scene) are different facts, and a harness proving either one has to
    tell them apart from "the directive named no POI at all", which carries
    neither key — that third case is the shipped behaviour and stays untagged.
    """

    if isinstance(error, PoiRefused):
        return {"poi_refused": error.admission.reason}
    disabled = str(getattr(grounder, "disabled_reason", "") or "")
    return {"poi_grounding_disabled": disabled} if disabled else {}


def _poi_row(grounder: Any, goal: Any, poi_id: str) -> dict[str, Any]:
    """The table row behind a grounded goal — its category and names matter."""

    for row in getattr(grounder, "pois", ()) or ():
        if isinstance(row, Mapping) and str(row.get("id", "")) == poi_id:
            return dict(row)
    return {
        "id": poi_id,
        "label": str(getattr(goal, "label", "") or ""),
        "position": (float(getattr(goal, "x", 0.0)), float(getattr(goal, "y", 0.0))),
    }


def _aliases(item: Mapping[str, Any]) -> tuple[str, ...]:
    metadata = item.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        return ()
    return tuple(str(alias) for alias in (metadata.get("aliases") or ()))


def _normalized(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _polygon_distance(x: float, y: float, polygon: tuple[tuple[float, float], ...]) -> float:
    if _inside(x, y, polygon):
        return 0.0
    count = len(polygon)
    return min(
        _segment_distance(x, y, *polygon[index], *polygon[(index + 1) % count])
        for index in range(count)
    )


def _inside(x: float, y: float, polygon: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < crossing:
                inside = not inside
    return inside


def _segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    dx, dy = bx - ax, by - ay
    denominator = dx * dx + dy * dy
    t = (
        0.0
        if denominator <= 0.0
        else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denominator))
    )
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
