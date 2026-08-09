"""Eval integrity (instrument 6): the landmark tables are generated, not typed.

Three things are pinned here:

1. **Regeneration diff** — the checked-in ``scene_truth.json`` must equal a
   fresh derivation from ``city_block.xml``. A hand edit of the artifact, or a
   scene edit that skips regeneration, is a red build. This is the test that
   replaces "any scene edit currently corrupts goals silently".
2. **Transcription delta** — the hand-transcribed table the frozen episode set
   was built from is compared field by field against the derived truth. Entries
   that agree must agree *exactly*; entries that disagree must be exactly the
   pinned list below, with the pinned values. So the delta can neither grow
   (new drift) nor shrink silently (someone adopting derived values without a
   re-freeze).
3. **Digest immunity** — the generator now reads its table from the artifact,
   and the frozen minival digest must not have moved by a single byte.
"""

from __future__ import annotations

import json

import pytest

from evals.nav_instruct.generator import _LANDMARKS, generate_minival, matrix_digest
from evals.nav_instruct.scene_truth import (
    ARTIFACT_PATH,
    GENERATOR_LANDMARK_IDS,
    SCENE_PATH,
    build_artifact,
    derive_scene_truth,
    landmark_table,
    load_artifact,
    scene_sha256,
    transcribed_table,
    transcription_deltas,
)

#: The frozen NAV_INSTRUCT minival episode set. Both the 2026-08-05 baseline row
#: and the 2026-08-06 candidate row were measured against this digest.
FROZEN_MINIVAL_DIGEST = "cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf"

#: Every place the hand-transcribed table disagrees with the scene, measured
#: 2026-08-06 (Wave 0). NOT a target — a pinned defect. Adopting the derived
#: values moves episode goals and requires a re-freeze; that is a separate card.
#: Until it lands, this list is the contract.
PINNED_TRANSCRIPTION_DELTAS: tuple[dict, ...] = (
    {
        "entity_id": "bench_1",
        "field": "position",
        "transcribed": [-2.5, 3.0],
        "derived": [-2.5, 3.045],
    },
    {
        "entity_id": "bench_1",
        "field": "radius_m",
        "transcribed": 0.7,
        "derived": 0.733757,
    },
    {
        "entity_id": "bldg_1",
        "field": "radius_m",
        "transcribed": 1.8,
        "derived": 2.343075,
    },
    {
        "entity_id": "crosswalk",
        "field": "polygon",
        "transcribed": [[2.3, -0.4], [3.9, -0.4], [3.9, 2.0], [2.3, 2.0]],
        "derived": [[2.35, -0.4], [3.85, -0.4], [3.85, 2.0], [2.35, 2.0]],
    },
    {
        "entity_id": "sidewalk",
        "field": "polygon",
        "transcribed": [[-8.0, 2.4], [8.0, 2.4], [8.0, 3.6], [-8.0, 3.6]],
        "derived": [[-8.0, 2.2], [8.0, 2.2], [8.0, 4.2], [-8.0, 4.2]],
    },
    {
        "entity_id": "sidewalk_south",
        "field": "polygon",
        "transcribed": [[-8.0, -3.6], [8.0, -3.6], [8.0, -2.4], [-8.0, -2.4]],
        "derived": [[-8.0, -3.75], [8.0, -3.75], [8.0, -2.25], [-8.0, -2.25]],
    },
    {
        "entity_id": "tree_1",
        "field": "radius_m",
        "transcribed": 0.45,
        "derived": 0.58,
    },
)

#: The landmarks the transcription got right. These are the equality half of the
#: proof: the derivation is real, and where the hand table is correct it is
#: reproduced exactly.
EXACT_MATCH_IDS: tuple[str, ...] = ("lamp_post_1", "lamp_post_2", "planter_1")


@pytest.fixture(scope="module")
def fresh_artifact() -> dict:
    return build_artifact()


def test_checked_in_artifact_equals_a_fresh_derivation(fresh_artifact: dict) -> None:
    """PR-tier regeneration diff: artifact ≡ recompute(scene)."""

    stored = load_artifact()
    assert stored == fresh_artifact, (
        "scene_truth.json is stale or hand-edited. Regenerate with:\n"
        "  .parcel/bin/python -m evals.nav_instruct.scene_truth --regenerate\n"
        "and re-read the transcription deltas before landing the change."
    )


def test_artifact_pins_the_scene_it_was_derived_from(fresh_artifact: dict) -> None:
    stored = load_artifact()
    assert SCENE_PATH.exists()
    assert stored["scene"]["sha256"] == scene_sha256(SCENE_PATH)
    assert stored["scene"]["path"] == "src/parcel_robot/scenes/city_block.xml"


def test_artifact_is_valid_json_and_sorted() -> None:
    """The artifact must stay diffable: sorted keys, trailing newline."""

    raw = ARTIFACT_PATH.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert raw == json.dumps(json.loads(raw), sort_keys=True, indent=2) + "\n"


def test_derivation_reproduces_the_landmarks_the_transcription_got_right() -> None:
    """Equality half: where the hand table is correct, the derivation matches it."""

    derived = derive_scene_truth()
    transcribed = transcribed_table()
    for entity_id in EXACT_MATCH_IDS:
        assert derived[entity_id] == transcribed[entity_id], entity_id


def test_transcription_delta_is_exactly_the_pinned_set() -> None:
    """The hand table disagrees with the scene in these places and no others.

    A new row means fresh drift (someone edited the scene or the table). A
    missing row means someone adopted a derived value — which moves episode
    goals and needs a re-freeze, not a quiet edit. Either way: red.
    """

    measured = transcription_deltas(derive_scene_truth(), transcribed_table())
    assert measured == [dict(row) for row in PINNED_TRANSCRIPTION_DELTAS], (
        "the derived/transcribed delta changed. If a scene edit caused it, "
        "regenerate scene_truth.json and re-pin here WITH a note in the backlog; "
        "if a value was adopted, the frozen NAV_INSTRUCT rows must be re-frozen."
    )


def test_every_generator_landmark_exists_in_the_scene() -> None:
    """No transcribed landmark may be an invention with no scene counterpart."""

    derived = derive_scene_truth()
    missing = [key for key in GENERATOR_LANDMARK_IDS if key not in derived]
    assert not missing, f"transcribed landmarks absent from the scene: {missing}"


def test_generator_reads_its_landmarks_from_the_artifact() -> None:
    """One checked-in place holds the table the generator uses."""

    assert _LANDMARKS == landmark_table()
    assert set(_LANDMARKS) == set(GENERATOR_LANDMARK_IDS)
    # Shape matters: the digest is computed over these values.
    assert isinstance(_LANDMARKS["bench_1"]["position"], tuple)
    assert isinstance(_LANDMARKS["sidewalk"]["polygon"], tuple)
    assert isinstance(_LANDMARKS["sidewalk"]["polygon"][0], tuple)


def test_frozen_minival_episode_digest_is_unchanged() -> None:
    """Routing the table through the artifact moved nothing (byte-identical)."""

    assert matrix_digest(generate_minival(seed=20260804)) == FROZEN_MINIVAL_DIGEST
