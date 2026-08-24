"""Derived scene-truth tables for NAV_INSTRUCT (eval instrument 6).

The NAV_INSTRUCT generator's landmark table was hand-transcribed from
``city_block.xml``. That is the golden-file defect the audit names: edit the
scene and every episode goal silently moves with nothing to notice. This module
is the derived path — landmark and goal tables computed from
:func:`~parcel_robot.perception.city_semantics.extract_city_semantics` over the actual
scene file — plus a checked-in artifact (``scene_truth.json``) that a PR-tier
test regenerates and diffs. A hand edit of the artifact, or a scene edit that
does not regenerate it, is a red build.

Two tables live in the artifact and they are **not** the same thing:

``derived``
    What the scene actually contains, computed. The truth.
``transcribed``
    The values the frozen episode set was built from, carried verbatim. The
    generator reads *this* one, so the frozen minival digest cannot move.

``transcription_deltas`` records every place the two disagree. As of the Wave 0
measurement they disagree in five places (see ``docs``/``scrum`` record and
``tests/test_nav_instruct_scene_truth.py``); adopting the derived values would
change every affected episode goal and therefore requires a re-freeze, which is
out of scope for a zero-behaviour-change round. Until that card lands the delta
is *pinned*, not hidden: the test asserts the delta set exactly, so it can
neither grow nor be silently adopted.

``mujoco`` is imported lazily inside :func:`derive_scene_truth` so the generator
— and every pure consumer of the transcribed table — stays free of the sim
dependency.

THE SURFACE CONVENTION (artifact v2, card PG-2)
----------------------------------------------
``derived`` and ``transcribed`` describe every object as a **centre plus a
circumscribed radius**. No RGB-D sensor can measure that. The 2026-08-21 mapping
bench built a semantic map from 120 rendered RGB-D frames and found building
entries landing **1–3 cm from the visible facade and 1.2–1.7 m from the geom
centre — 6/6 in the oracle arm, 5/6 in the open-vocab arm**
(`scrum/20260821/perception/bench_mapping.md`). That is not an error; a depth
camera sees surfaces and never centroids. Graded against ``derived``, a working
pipeline scores 1.2–1.7 m and fails.

So the artifact gained a third, sibling table:

``surfaces``
    Per entity, the **sensor-measurable target**: for a ``near``-class place the
    nearest-surface set (one footprint primitive per constituent geom, the
    thing a depth ray can actually land on); for an ``inside``-class place the
    interior polygon, byte-identical to that entity's ``derived`` polygon.
``surface_convention``
    The versioned rules — what each measure means, what the per-class scoring
    rule is, and the requirement that every localization claim carry a null
    control. Scoring lives in ``evals/nav_instruct/surface_scoring.py``.

**Why a sibling table and not a field inside ``derived``.** ``derived`` exists to
be compared field-by-field with ``transcribed`` (see
``tests/test_nav_instruct_scene_truth.py``, which asserts three ``derived`` rows
are *equal* to their hand-typed counterparts). Adding a key to one side of that
comparison would break the equality half of the proof for no benefit. A sibling
section leaves every existing consumer — the generator, the frozen minival
digest, ``derived_landmark_table`` — reading exactly the bytes it read before.

**Which class is measured how is NOT decided here.** It is read from
``parcel_robot.navigation.arrival_semantics.localization_target``, the table that
already owns what arrival means per class, so the answer key and the robot
cannot come to disagree about what "the building" is.

Usage::

    .parcel/bin/python -m evals.nav_instruct.scene_truth --check
    .parcel/bin/python -m evals.nav_instruct.scene_truth --regenerate
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Scene the NAV_INSTRUCT episode set is defined against.
SCENE_RELPATH = "src/parcel_robot/scenes/city_block.xml"
SCENE_PATH = REPO_ROOT / SCENE_RELPATH

#: Checked-in generated artifact. Never hand-edit — regenerate.
ARTIFACT_PATH = Path(__file__).resolve().parent / "scene_truth.json"

#: Card W-1. The held-out scene variant, and the *only* other scene this module
#: knows how to derive a truth artifact for.
#:
#: It carries no ``transcribed`` section and no ``transcription_deltas``,
#: because those two record a disagreement between the episode generator's hand
#: table and the scene — and nothing generates episodes against the held-out
#: block. An empty section would look like agreement; the section is absent
#: instead, and ``held_out`` says so in the artifact itself.
HELD_OUT_SCENE_ID = "city_block_b"
HELD_OUT_SCENE_RELPATH = "src/parcel_robot/scenes/city_block_b.xml"
HELD_OUT_ARTIFACT_PATH = Path(__file__).resolve().parent / "scene_truth_city_block_b.json"

#: scene id -> (scene relpath, artifact path, carries a hand transcription)
SCENE_TARGETS: dict[str, tuple[str, Path, bool]] = {
    "city_block": (SCENE_RELPATH, ARTIFACT_PATH, True),
    HELD_OUT_SCENE_ID: (HELD_OUT_SCENE_RELPATH, HELD_OUT_ARTIFACT_PATH, False),
}

#: Bumped 1 -> 2 by card PG-2, which ADDED the ``surfaces`` and
#: ``surface_convention`` sections. Nothing in ``derived`` / ``transcribed`` /
#: ``transcription_deltas`` moved by a byte, so a v1 reader that ignores unknown
#: top-level keys keeps working unchanged; the bump exists so a consumer that
#: needs a surface can *require* it instead of discovering its absence at
#: runtime.
ARTIFACT_VERSION = 2

#: Version of the surface convention itself, independent of the artifact
#: envelope: bump this when what a surface MEANS changes (a new primitive, a
#: different measure per class), not when the scene moves.
SURFACE_CONVENTION_VERSION = 1

#: Footprint primitives a surface part may be. Closed on purpose — a geom type
#: the derivation has never seen is an error, never a silently dropped surface,
#: because a missing surface would grade as "this place has no measurable
#: target" and quietly re-open the defect this card closed.
SURFACE_SHAPE_RECT = "rect"
SURFACE_SHAPE_CIRCLE = "circle"
SURFACE_SHAPES: tuple[str, ...] = (SURFACE_SHAPE_RECT, SURFACE_SHAPE_CIRCLE)

#: Largest deviation from the identity quaternion a box geom may carry and still
#: have an axis-aligned footprint. Every box in ``city_block.xml`` is unrotated
#: today; a rotated one would make the 4-corner rect below a LIE, so the
#: derivation raises rather than emitting a wrong answer key.
_QUAT_IDENTITY_TOL = 1e-9

#: Decimal places every derived float is rounded to before it lands in the
#: artifact. 1e-6 m is four orders of magnitude below the smallest arrival band
#: in the system, so it cannot mask a scene edit, and it keeps the artifact
#: stable against float formatting noise.
ROUND_DP = 6

#: The landmark ids the episode generator actually consumes. The scene holds
#: more (bldg_2..6, tree_2, planter_2); they are derived and recorded but the
#: transcription only ever covered these, so only these can disagree.
GENERATOR_LANDMARK_IDS: tuple[str, ...] = (
    "sidewalk",
    "sidewalk_south",
    "crosswalk",
    "lamp_post_1",
    "lamp_post_2",
    "bench_1",
    "tree_1",
    "planter_1",
    "bldg_1",
)

#: The landmark ids the **v2** episode set consumes: the v1 nine, plus
#: ``tree_2``. The extra id is not a widening for its own sake — the v2 spec fix
#: for ``nav-object_goal-D-15`` re-anchors "walk towards the tree" to the tree
#: instance the robot can actually see, and that instance is ``tree_2``. A
#: generator that cannot name ``tree_2`` cannot express the corrected episode.
#:
#: Deliberately NOT widened further. ``planter_2`` is the same ambiguity class
#: (``planter_1``/``planter_2`` are co-located with the two trees and
#: "go next to the planter" is equally definite-but-plural), and it is left
#: OPEN and recorded rather than fixed here: this re-freeze carries exactly the
#: three approved corrections and no fourth.
V2_LANDMARK_IDS: tuple[str, ...] = GENERATOR_LANDMARK_IDS + ("tree_2",)


def scene_sha256(path: str | Path = SCENE_PATH) -> str:
    """SHA-256 of the scene file, so drift is attributable to a specific edit."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def derive_scene_truth(scene: str | Path = SCENE_PATH) -> dict[str, Any]:
    """Compute the landmark table from the scene — never transcribe it.

    Regions become ``{"kind": "region", "label", "polygon"}`` and objects
    ``{"kind": "object", "label", "position", "radius_m"}``: the same shape the
    generator's hand table uses, so the two are directly comparable.
    """

    import mujoco  # local: keeps the pure eval path free of the sim dependency

    from parcel_robot.perception.city_semantics import extract_city_semantics

    model = mujoco.MjModel.from_xml_path(str(scene))
    regions, objects = extract_city_semantics(model)
    table: dict[str, dict[str, Any]] = {}
    for region in regions:
        table[str(region["id"])] = {
            "kind": "region",
            "label": str(region["label"]),
            "polygon": [[_round(p[0]), _round(p[1])] for p in region["polygon"]],
        }
    for item in objects:
        position = item["position"]
        table[str(item["id"])] = {
            "kind": "object",
            "label": str(item["label"]),
            "position": [_round(position[0]), _round(position[1])],
            "radius_m": _round(item["metadata"]["radius_m"]),
        }
    return dict(sorted(table.items()))


class SurfaceDerivationError(ValueError):
    """A scene whose surfaces cannot be derived honestly. Never a warning."""


def derive_scene_surfaces(scene: str | Path = SCENE_PATH) -> dict[str, Any]:
    """Compute the sensor-measurable target for every semantic entity.

    Returns ``entity_id -> record``, where a record is::

        {
          "kind":          "object" | "region",   # the geometry kind
          "label":         "building",            # the scene class
          "place_class":   "object",              # arrival_semantics class
          "measure":       "surface" | "interior",
          "parts":         [...],                 # objects: nearest-surface set
          "interior_polygon": [[x, y], ...],      # regions: the graded interior
        }

    ``kind`` and ``place_class`` are deliberately two fields: ``door_1`` is an
    *object* geometrically and a *portal* to arrival, and it is the portal row
    that decides how a perception answer for it is measured.

    Objects carry ``parts`` — one footprint primitive per constituent geom, in
    ``associated_lidar_ids`` order. That set, not a single polygon, is what a
    depth camera can land on: the bench is four separate boxes and a ray hits
    whichever one faces the robot. Regions carry ``interior_polygon`` and no
    parts; see the module docstring for why.
    """

    import mujoco  # local: keeps the pure eval path free of the sim dependency

    from parcel_robot.navigation.arrival_semantics import (
        LOCALIZATION_INTERIOR,
        classify_place,
        localization_target,
    )
    from parcel_robot.perception.city_semantics import extract_city_semantics
    from parcel_robot.perception.scene_semantics import scene_semantics

    model = mujoco.MjModel.from_xml_path(str(scene))
    regions, objects = extract_city_semantics(model)

    sidecar = scene_semantics()
    region_labels = tuple(
        word
        for item in sidecar.classes
        if item.kind == "region"
        for word in (item.name, *item.aliases)
    )
    object_labels = tuple(
        word
        for item in sidecar.classes
        if item.kind == "object"
        for word in (item.name, *item.aliases)
    )

    def _classified(label: str) -> tuple[str, str]:
        place_class = classify_place(
            label, region_labels=region_labels, object_labels=object_labels
        )
        return place_class, localization_target(place_class)

    table: dict[str, Any] = {}

    for region in regions:
        label = str(region["label"])
        place_class, measure = _classified(label)
        if measure != LOCALIZATION_INTERIOR:
            raise SurfaceDerivationError(
                f"region {region['id']!r} classified as {place_class!r}, whose "
                f"localization target is {measure!r}; a region the arrival table "
                f"does not measure by containment would change `inside` arrival"
            )
        table[str(region["id"])] = {
            "kind": "region",
            "label": label,
            "place_class": place_class,
            "measure": measure,
            # Byte-identical to the same entity's ``derived`` polygon. That
            # equality IS the "inside-class arrival is unaffected" guarantee,
            # and tests/test_scene_surface_truth.py asserts it entity by entity.
            "interior_polygon": [[_round(p[0]), _round(p[1])] for p in region["polygon"]],
        }

    for item in objects:
        label = str(item["label"])
        place_class, measure = _classified(label)
        if measure == LOCALIZATION_INTERIOR:
            raise SurfaceDerivationError(
                f"object {item['id']!r} classified as {place_class!r}, which is "
                f"measured by containment; an RGB-D sensor cannot see inside a "
                f"solid, so this entity would have no measurable target"
            )
        geom_names = list(item["metadata"].get("associated_lidar_ids") or ())
        if not geom_names:
            raise SurfaceDerivationError(
                f"object {item['id']!r} lists no constituent geoms, so it has no "
                f"surface a sensor could measure"
            )
        table[str(item["id"])] = {
            "kind": "object",
            "label": label,
            "place_class": place_class,
            "measure": measure,
            "parts": [_geom_footprint(model, name) for name in geom_names],
        }

    return dict(sorted(table.items()))


def _geom_footprint(model: Any, geom_name: str) -> dict[str, Any]:
    """One geom's ground-plane footprint primitive.

    The footprint is the horizontal cross-section outline: what a depth ray
    travelling parallel to the ground can hit. Boxes give a rectangle, cylinders
    and spheres give a circle. Any other geom type raises — a scene that grows
    one needs a deliberate convention decision, not a guess.
    """

    import mujoco

    geom_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, geom_name)
    if geom_id < 0:
        raise SurfaceDerivationError(f"scene has no geom named {geom_name!r}")
    geom_type = int(model.geom_type[geom_id])
    x = float(model.geom_pos[geom_id, 0])
    y = float(model.geom_pos[geom_id, 1])
    size = model.geom_size[geom_id]

    if geom_type == int(mujoco.mjtGeom.mjGEOM_BOX):
        quat = [float(v) for v in model.geom_quat[geom_id]]
        if abs(quat[0] - 1.0) > _QUAT_IDENTITY_TOL or any(
            abs(v) > _QUAT_IDENTITY_TOL for v in quat[1:]
        ):
            raise SurfaceDerivationError(
                f"geom {geom_name!r} is a rotated box (quat={quat}); its footprint "
                f"is not the axis-aligned rectangle this derivation would emit"
            )
        sx, sy = float(size[0]), float(size[1])
        return {
            "geom": geom_name,
            "shape": SURFACE_SHAPE_RECT,
            "polygon": [
                [_round(x - sx), _round(y - sy)],
                [_round(x + sx), _round(y - sy)],
                [_round(x + sx), _round(y + sy)],
                [_round(x - sx), _round(y + sy)],
            ],
        }
    if geom_type in {
        int(mujoco.mjtGeom.mjGEOM_CYLINDER),
        int(mujoco.mjtGeom.mjGEOM_SPHERE),
    }:
        return {
            "geom": geom_name,
            "shape": SURFACE_SHAPE_CIRCLE,
            "center": [_round(x), _round(y)],
            "radius_m": _round(float(size[0])),
        }
    raise SurfaceDerivationError(
        f"geom {geom_name!r} has type {geom_type}, for which no footprint "
        f"primitive is defined; add one deliberately rather than dropping the "
        f"surface"
    )


def surface_convention() -> dict[str, Any]:
    """The versioned rules, carried in the artifact so it is self-describing.

    An answer key that ships its own grading contract is one a reader months
    from now can audit without finding this module first. Every literal here is
    imported from the authority that owns it — nothing is re-typed.
    """

    from evals.nav_instruct.surface_scoring import (
        MIN_NULL_DRAWS,
        NULL_ALPHA,
        REGION_EVIDENCE_MAJORITY,
        SURFACE_BUDGET_M,
    )
    from parcel_robot.navigation.arrival_semantics import (
        LOCALIZATION_INTERIOR,
        LOCALIZATION_SURFACE,
    )

    return {
        "version": SURFACE_CONVENTION_VERSION,
        "why": (
            "scene_truth's centre+radius convention is unmeasurable by any RGB-D "
            "sensor: the 2026-08-21 mapping bench put building entries 1-3 cm "
            "from the visible facade and 1.2-1.7 m from the geom centre, 6/6 in "
            "the oracle arm and 5/6 in the open-vocab arm. Grading perception "
            "against the centre fails a working pipeline."
        ),
        "authority": (
            "which class is measured how is read from "
            "parcel_robot.navigation.arrival_semantics.localization_target; this "
            "artifact holds no class -> metric map of its own"
        ),
        "scoring_module": "evals/nav_instruct/surface_scoring.py",
        "measures": {
            LOCALIZATION_SURFACE: {
                "applies_to": "near-class places (object, portal, person, unknown)",
                "target": "the nearest-surface set in `parts`",
                "statistic": "surface_error_m = min over parts of |distance to that part's footprint outline|",
                "passes_when": f"surface_error_m <= {SURFACE_BUDGET_M}",
                "note": (
                    "unsigned: a point deep INSIDE a solid is as wrong as one "
                    "outside it, because no sensor could have produced it"
                ),
            },
            LOCALIZATION_INTERIOR: {
                "applies_to": "inside-class places (region)",
                "target": "`interior_polygon`, byte-identical to the entity's `derived` polygon",
                "statistic": (
                    "containment of the answer point PLUS evidence_inside_fraction "
                    "over the answering entry's own supporting points"
                ),
                "passes_when": (
                    f"the point is contained AND evidence_inside_fraction >= "
                    f"{REGION_EVIDENCE_MAJORITY}"
                ),
                "note": (
                    "bare containment is UNINFORMATIVE for large regions: the "
                    "bench measured sidewalk and crosswalk at 0.00 m against a "
                    "RANDOM map (p=1.00, p=0.52). The evidence fraction is what "
                    "a random map cannot pass, and the null control is what "
                    "proves it in any particular scene."
                ),
            },
        },
        "null_control": {
            "required": True,
            "rule": (
                "EVERY localization claim carries a null control. A number "
                "without one is not a result; the scorer cannot construct a "
                "claim without it."
            ),
            "procedure": (
                "re-scatter the same population uniformly over the mapped area, "
                "recompute the same statistic, report p = P(null at least as "
                "good as observed)"
            ),
            "min_draws": MIN_NULL_DRAWS,
            "alpha": NULL_ALPHA,
            "verdicts": {
                "pass": "the statistic passed AND beat the null at alpha",
                "fail": "the statistic did not pass",
                "uninformative": (
                    "the statistic passed but did NOT beat the null — the metric "
                    "could not discriminate here, so this may not be reported as "
                    "a pass"
                ),
            },
        },
    }


def transcribed_table() -> dict[str, dict[str, Any]]:
    """The hand-transcribed table exactly as the frozen episode set used it.

    This is the authority for episode generation until a re-freeze card adopts
    the derived values. It is defined here — not in the generator — so the
    artifact is the single checked-in place both tables live.
    """

    return {
        "sidewalk": {
            "kind": "region",
            "label": "sidewalk",
            "polygon": [[-8.0, 2.4], [8.0, 2.4], [8.0, 3.6], [-8.0, 3.6]],
        },
        "sidewalk_south": {
            "kind": "region",
            "label": "sidewalk",
            "polygon": [[-8.0, -3.6], [8.0, -3.6], [8.0, -2.4], [-8.0, -2.4]],
        },
        "crosswalk": {
            "kind": "region",
            "label": "crosswalk",
            "polygon": [[2.3, -0.4], [3.9, -0.4], [3.9, 2.0], [2.3, 2.0]],
        },
        "lamp_post_1": {
            "kind": "object",
            "label": "lamppost",
            "position": [0.2, 3.15],
            "radius_m": 0.06,
        },
        "lamp_post_2": {
            "kind": "object",
            "label": "lamppost",
            "position": [-6.7, -2.9],
            "radius_m": 0.06,
        },
        "bench_1": {
            "kind": "object",
            "label": "bench",
            "position": [-2.5, 3.0],
            "radius_m": 0.7,
        },
        "tree_1": {
            "kind": "object",
            "label": "tree",
            "position": [-5.0, 3.15],
            "radius_m": 0.45,
        },
        "planter_1": {
            "kind": "object",
            "label": "planter",
            "position": [-5.0, 3.15],
            "radius_m": 0.45,
        },
        "bldg_1": {
            "kind": "object",
            "label": "building",
            "position": [-4.5, 5.5],
            "radius_m": 1.8,
        },
    }


def transcription_deltas(
    derived: Mapping[str, Mapping[str, Any]],
    transcribed: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Every place the hand table and the scene disagree, one row per field.

    Sorted and rounded so the list is a stable, diffable artifact. An entity
    present in one table and missing from the other is itself a row.
    """

    rows: list[dict[str, Any]] = []
    for entity_id in GENERATOR_LANDMARK_IDS:
        hand = transcribed.get(entity_id)
        truth = derived.get(entity_id)
        if hand is None or truth is None:
            rows.append(
                {
                    "entity_id": entity_id,
                    "field": "presence",
                    "transcribed": hand is not None,
                    "derived": truth is not None,
                }
            )
            continue
        for field in ("kind", "label", "polygon", "position", "radius_m"):
            if field not in hand and field not in truth:
                continue
            hand_value = _normalise(hand.get(field))
            truth_value = _normalise(truth.get(field))
            if hand_value != truth_value:
                rows.append(
                    {
                        "entity_id": entity_id,
                        "field": field,
                        "transcribed": hand_value,
                        "derived": truth_value,
                    }
                )
    return sorted(rows, key=lambda row: (row["entity_id"], row["field"]))


def build_artifact(
    scene: str | Path = SCENE_PATH,
    *,
    relpath: str = SCENE_RELPATH,
    transcription: bool = True,
) -> dict[str, Any]:
    """The full checked-in artifact payload, derived from the scene.

    ``transcription=False`` (card W-1, the held-out variant) omits the
    generator's hand table and the deltas against it rather than emitting them
    empty: there is no generator table for that scene to disagree with, and an
    empty delta list would read as "checked, agreed".
    """

    derived = derive_scene_truth(scene)
    payload: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "generated_by": "evals/nav_instruct/scene_truth.py",
        "do_not_hand_edit": (
            "regenerate with: .parcel/bin/python -m evals.nav_instruct.scene_truth "
            "--regenerate"
        ),
        "scene": {"path": relpath, "sha256": scene_sha256(scene)},
        "derived": derived,
        "surface_convention": surface_convention(),
        "surfaces": derive_scene_surfaces(scene),
    }
    if transcription:
        transcribed = transcribed_table()
        payload["generator_landmark_ids"] = list(GENERATOR_LANDMARK_IDS)
        payload["transcribed"] = transcribed
        payload["transcription_deltas"] = transcription_deltas(derived, transcribed)
    else:
        payload["held_out"] = (
            "This scene exists only so a generalization claim can be earned on "
            "pixels no perception component was tuned against. It carries no "
            "episode generator table. See tests/test_held_out_scene.py."
        )
    return payload


def write_artifact(path: str | Path = ARTIFACT_PATH, **kwargs: Any) -> Path:
    """Regenerate the checked-in artifact from the scene."""

    target = Path(path)
    target.write_text(
        json.dumps(build_artifact(**kwargs), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_artifact(path: str | Path = ARTIFACT_PATH) -> dict[str, Any]:
    """Read the checked-in artifact. No mujoco, no scene parse."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def landmark_table(path: str | Path = ARTIFACT_PATH) -> dict[str, dict[str, Any]]:
    """The transcribed landmark table in the generator's native shape.

    Tuples, not lists — the generator's ``_LANDMARKS`` values flow straight into
    frozen ``GoalRegion``/``EpisodeSpec`` fields, and the episode digest is
    computed over their JSON form, so the shape must be preserved exactly.
    """

    return _native_table(load_artifact(path)["transcribed"])


def derived_landmark_table(
    path: str | Path = ARTIFACT_PATH,
    *,
    ids: Sequence[str] = V2_LANDMARK_IDS,
) -> dict[str, dict[str, Any]]:
    """The **derived** landmark table — the scene's own geometry, computed.

    This is the table the v2 episode set is generated from (re-freeze correction
    (a)). It is the artifact's ``derived`` section restricted to ``ids`` and
    reshaped into the generator's native tuple form, so nothing about it is
    transcribed: change the scene and this table changes with it, and
    ``test_checked_in_artifact_equals_a_fresh_derivation`` reddens if the
    artifact was not regenerated.
    """

    derived = load_artifact(path)["derived"]
    missing = [key for key in ids if key not in derived]
    if missing:
        raise KeyError(f"scene-truth artifact has no derived entry for: {missing}")
    return _native_table({key: derived[key] for key in ids})


def surface_table(path: str | Path = ARTIFACT_PATH) -> dict[str, dict[str, Any]]:
    """The checked-in ``surfaces`` section. No mujoco, no scene parse.

    Refuses an artifact older than the convention rather than returning ``{}``:
    an empty surface table and a missing surface table look identical to a
    scorer, and one of them means "grade against the centre again".
    """

    artifact = load_artifact(path)
    version = artifact.get("artifact_version")
    if not isinstance(version, int) or version < 2:
        raise KeyError(
            f"scene-truth artifact is v{version!r}, which predates the surface "
            f"convention; regenerate with: .parcel/bin/python -m "
            f"evals.nav_instruct.scene_truth --regenerate"
        )
    surfaces = artifact.get("surfaces")
    if not isinstance(surfaces, Mapping) or not surfaces:
        raise KeyError("scene-truth artifact carries no surfaces section")
    return {str(key): dict(value) for key, value in surfaces.items()}


def _native_table(section: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for entity_id, entry in section.items():
        record: dict[str, Any] = {"kind": entry["kind"], "label": entry["label"]}
        if "polygon" in entry:
            record["polygon"] = tuple((float(p[0]), float(p[1])) for p in entry["polygon"])
        if "position" in entry:
            record["position"] = (float(entry["position"][0]), float(entry["position"][1]))
        if "radius_m" in entry:
            record["radius_m"] = float(entry["radius_m"])
        out[entity_id] = record
    return out


def _round(value: Any) -> float:
    return round(float(value), ROUND_DP)


def _normalise(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _round(value)
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="rewrite scene_truth.json from the scene",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the checked-in artifact differs from the scene",
    )
    parser.add_argument(
        "--scene",
        choices=sorted(SCENE_TARGETS),
        default="city_block",
        help="which scene's truth artifact to regenerate or check (card W-1)",
    )
    args = parser.parse_args(argv)

    relpath, artifact_path, transcription = SCENE_TARGETS[args.scene]
    scene_path = REPO_ROOT / relpath
    fresh = build_artifact(scene_path, relpath=relpath, transcription=transcription)
    if args.regenerate:
        write_artifact(
            artifact_path, scene=scene_path, relpath=relpath, transcription=transcription
        )
        print(json.dumps({"regenerated": str(artifact_path)}, indent=2))
        return 0

    stored = load_artifact(artifact_path) if artifact_path.exists() else None
    drifted = stored != fresh
    print(
        json.dumps(
            {
                "artifact": str(artifact_path),
                "scene_sha256": fresh["scene"]["sha256"],
                "drifted": drifted,
                "transcription_deltas": fresh.get("transcription_deltas", []),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if args.check and drifted:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
