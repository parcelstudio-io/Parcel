"""Derived scene-truth tables for NAV_INSTRUCT (eval instrument 6).

The NAV_INSTRUCT generator's landmark table was hand-transcribed from
``city_block.xml``. That is the golden-file defect the audit names: edit the
scene and every episode goal silently moves with nothing to notice. This module
is the derived path — landmark and goal tables computed from
:func:`~parcel_robot.city_semantics.extract_city_semantics` over the actual
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

ARTIFACT_VERSION = 1

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

    from parcel_robot.city_semantics import extract_city_semantics

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


def build_artifact(scene: str | Path = SCENE_PATH) -> dict[str, Any]:
    """The full checked-in artifact payload, derived from the scene."""

    derived = derive_scene_truth(scene)
    transcribed = transcribed_table()
    return {
        "artifact_version": ARTIFACT_VERSION,
        "generated_by": "evals/nav_instruct/scene_truth.py",
        "do_not_hand_edit": (
            "regenerate with: .parcel/bin/python -m evals.nav_instruct.scene_truth "
            "--regenerate"
        ),
        "scene": {"path": SCENE_RELPATH, "sha256": scene_sha256(scene)},
        "generator_landmark_ids": list(GENERATOR_LANDMARK_IDS),
        "derived": derived,
        "transcribed": transcribed,
        "transcription_deltas": transcription_deltas(derived, transcribed),
    }


def write_artifact(path: str | Path = ARTIFACT_PATH) -> Path:
    """Regenerate the checked-in artifact from the scene."""

    target = Path(path)
    target.write_text(
        json.dumps(build_artifact(), sort_keys=True, indent=2) + "\n",
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
    args = parser.parse_args(argv)

    fresh = build_artifact()
    if args.regenerate:
        write_artifact()
        print(json.dumps({"regenerated": str(ARTIFACT_PATH)}, indent=2))
        return 0

    stored = load_artifact() if ARTIFACT_PATH.exists() else None
    drifted = stored != fresh
    print(
        json.dumps(
            {
                "artifact": str(ARTIFACT_PATH),
                "scene_sha256": fresh["scene"]["sha256"],
                "drifted": drifted,
                "transcription_deltas": fresh["transcription_deltas"],
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
