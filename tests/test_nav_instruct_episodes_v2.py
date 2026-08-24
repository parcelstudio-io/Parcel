"""Eval integrity for the v2 re-freeze (instrument 6, applied to a new baseline).

Four things are pinned, and each corresponds to a way a re-freeze can go wrong.

1. **v1 did not move.** A re-freeze that quietly perturbs the set it supersedes
   destroys every comparison anyone has ever made. The v1 digest, the checked-in
   v1 episode files, and the frozen ledger prefix are all pinned here as well as
   in ``test_nav_instruct_scene_truth.py`` / ``test_nav_instruct_rescoring.py`` —
   deliberately twice, because this is the property most worth over-testing.
2. **Regeneration diff.** The checked-in v2 episode files must equal a fresh
   generation. A hand edit is a red build, exactly as for ``scene_truth.json``.
3. **Oracle isolation.** The v2 landmark table must *be* the artifact's derived
   section, not a copy of it — no transcription may re-enter through the new
   version.
4. **The corrections do what they say.** One test per correction, asserting on
   the two named mis-specified episodes and on the visibility rule that fixed
   one of them, including that the rule's constants equal the world's.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from evals.nav_instruct.generator import (
    EPISODE_SET_V1,
    EPISODE_SET_V1A,
    EPISODE_SET_V2,
    VISIBILITY_HALF_FOV_RAD,
    VISIBILITY_MAX_RANGE_M,
    episode_set_spec,
    generate_minival,
    landmarks_for,
    matrix_digest,
    visible_from_start,
    write_episode_files,
)
from evals.nav_instruct.runner import (
    ARRIVAL_RULE_FOR_VERSION,
    DEFAULT_ARRIVAL_RULE,
    DERIVED_ARRIVAL_RULE,
    FROZEN_ARRIVAL_RULE,
)
from evals.nav_instruct.scene_truth import V2_LANDMARK_IDS, derived_landmark_table, load_artifact

REPO = Path(__file__).resolve().parents[1]
EPISODES_DIR = REPO / "evals" / "nav_instruct" / "episodes"
LEDGER = REPO / "evals" / "nav_instruct" / "results" / "ledger.jsonl"

FROZEN_V1_DIGEST = "cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf"
FROZEN_V2_DIGEST = "a17c04dbec43a1749386c304060fb479a71f27d4b51b8c1b0fbb949753fc563d"

#: sha256 of the first nine ledger lines — everything written before the v2
#: rows were appended. Pinned in Wave 0 as seven lines; the two
#: ``derived_rescoring`` rows made it nine. The v2 append must not touch any of
#: them.
FROZEN_LEDGER_PREFIX_LINES = 9
FROZEN_LEDGER_PREFIX_SHA256 = (
    "dab60242975a86f26e0518571158c3f3bd8191f16623f8f51cc8b80c7f1f2fe0"
)

#: The two rows Lane D found mis-specified, and what they must anchor to now.
B05 = "nav-object_goal-B-05-0ee314d5"
D15 = "nav-object_goal-D-15-109547e2"


def _by_id(version: str) -> dict:
    return {ep.episode_id: ep for ep in generate_minival(version=version)}


def _plain(value):
    """Tuples -> lists, so a native table compares against artifact JSON."""

    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


# --------------------------------------------------------------------------
# 1. v1 did not move
# --------------------------------------------------------------------------


def test_v1_digest_is_untouched_by_the_v2_work() -> None:
    assert matrix_digest(generate_minival(version=EPISODE_SET_V1)) == FROZEN_V1_DIGEST


def test_v1_is_still_the_default_everywhere() -> None:
    """v2 has to be asked for by name. A default that drifts is a silent re-freeze."""

    assert matrix_digest(generate_minival()) == FROZEN_V1_DIGEST
    assert episode_set_spec().version == EPISODE_SET_V1
    assert ARRIVAL_RULE_FOR_VERSION[EPISODE_SET_V1] == FROZEN_ARRIVAL_RULE


def test_frozen_ledger_prefix_is_byte_identical_after_the_v2_append() -> None:
    lines = LEDGER.read_text(encoding="utf-8").splitlines(keepends=True)
    assert len(lines) > FROZEN_LEDGER_PREFIX_LINES, "the v2 rows were never appended"
    prefix = "".join(lines[:FROZEN_LEDGER_PREFIX_LINES]).encode("utf-8")
    assert hashlib.sha256(prefix).hexdigest() == FROZEN_LEDGER_PREFIX_SHA256


def test_the_v2_ledger_rows_declare_their_version_and_rule() -> None:
    """A row that does not say which set it ran is a row nobody can compare."""

    rows = [
        json.loads(line)
        for line in LEDGER.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    v2_rows = [row for row in rows if row.get("baseline_version") == EPISODE_SET_V2]
    assert len(v2_rows) >= 2, "expected a v2 baseline row and a v2 candidate row"
    for row in v2_rows:
        assert row["episode_digest"] == FROZEN_V2_DIGEST
        assert row["arrival_rule"] == DERIVED_ARRIVAL_RULE
        assert "sr_frozen_rule" in row, "the superseded rule must stay visible"


# --------------------------------------------------------------------------
# 2. regeneration diff over the checked-in episode files
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "digest"),
    [(EPISODE_SET_V1, FROZEN_V1_DIGEST), (EPISODE_SET_V2, FROZEN_V2_DIGEST)],
)
def test_checked_in_episode_files_equal_a_fresh_generation(
    version: str, digest: str, tmp_path: Path
) -> None:
    episodes = generate_minival(version=version)
    assert matrix_digest(episodes) == digest
    write_episode_files(episodes, tmp_path, version=version, seed=20260804)
    checked_in = EPISODES_DIR / version
    fresh_names = sorted(p.name for p in tmp_path.iterdir())
    stored_names = sorted(p.name for p in checked_in.iterdir())
    assert fresh_names == stored_names
    for name in fresh_names:
        assert (tmp_path / name).read_bytes() == (checked_in / name).read_bytes(), (
            f"{version}/{name} differs from a fresh generation — either it was "
            "hand-edited or the generator changed without regenerating"
        )


def test_manifest_records_which_corrections_the_set_carries() -> None:
    manifest = json.loads((EPISODES_DIR / EPISODE_SET_V2 / "manifest.json").read_text())
    assert manifest["sha256"] == FROZEN_V2_DIGEST
    assert manifest["episode_set_version"] == EPISODE_SET_V2
    assert manifest["landmark_section"] == "derived"
    assert manifest["word_boundary_class_match"] is True
    assert manifest["visible_instance_anchoring"] is True


def test_episode_ids_are_identical_across_versions() -> None:
    """The old→new mapping must be total: a dropped id orphans a frozen row."""

    ids = {
        version: set(_by_id(version))
        for version in (EPISODE_SET_V1, EPISODE_SET_V1A, EPISODE_SET_V2)
    }
    assert ids[EPISODE_SET_V1] == ids[EPISODE_SET_V1A] == ids[EPISODE_SET_V2]


# --------------------------------------------------------------------------
# 3. oracle isolation — no transcription may re-enter through v2
# --------------------------------------------------------------------------


def test_v2_landmark_table_is_the_derived_section_not_a_copy() -> None:
    spec = episode_set_spec(EPISODE_SET_V2)
    table = landmarks_for(spec)
    assert spec.landmark_section == "derived"
    assert table == derived_landmark_table()
    artifact = load_artifact()["derived"]
    for entity_id in V2_LANDMARK_IDS:
        entry = table[entity_id]
        truth = artifact[entity_id]
        assert entry["label"] == truth["label"]
        if "position" in truth:
            assert list(entry["position"]) == truth["position"]
            assert entry["radius_m"] == truth["radius_m"]
        else:
            assert [list(p) for p in entry["polygon"]] == truth["polygon"]


def test_v2_adopts_every_pinned_transcription_delta() -> None:
    """Correction (a) is complete: no delta is left un-adopted in v2."""

    artifact = load_artifact()
    table = landmarks_for(episode_set_spec(EPISODE_SET_V2))
    for delta in artifact["transcription_deltas"]:
        entity_id, field = delta["entity_id"], delta["field"]
        assert _plain(table[entity_id][field]) == delta["derived"], (
            f"v2 still carries the transcribed {field} for {entity_id}"
        )


def test_v1_still_carries_every_pinned_transcription_delta() -> None:
    """...and correction (a) did not leak backwards into the frozen set."""

    artifact = load_artifact()
    table = landmarks_for(episode_set_spec(EPISODE_SET_V1))
    for delta in artifact["transcription_deltas"]:
        entity_id, field = delta["entity_id"], delta["field"]
        assert _plain(table[entity_id][field]) == delta["transcribed"]


# --------------------------------------------------------------------------
# 4. the corrections do what they say
# --------------------------------------------------------------------------


def test_correction_b_streetlight_no_longer_scores_against_a_tree() -> None:
    """B-05: "walk towards the streetlight" contains the substring "tree"."""

    v1, v2 = _by_id(EPISODE_SET_V1)[B05], _by_id(EPISODE_SET_V2)[B05]
    assert "streetlight" in v1.instruction and v1.instruction == v2.instruction
    assert v1.target_entity_id == "tree_1", "the defect this test exists for is gone"
    assert v2.target_entity_id == "lamp_post_1"
    assert v2.goal.anchor_entity == "lamp_post_1"


def test_correction_b_the_tree_anchors_to_the_tree_in_frame() -> None:
    """D-15: the definite reference resolves to what the robot can actually see."""

    v1, v2 = _by_id(EPISODE_SET_V1)[D15], _by_id(EPISODE_SET_V2)[D15]
    assert v1.target_entity_id == "tree_1"
    assert v2.target_entity_id == "tree_2"
    table = landmarks_for(episode_set_spec(EPISODE_SET_V2))
    assert not visible_from_start(v2.start_pose, table["tree_1"]["position"])
    assert visible_from_start(v2.start_pose, table["tree_2"]["position"])


def test_every_v2_object_anchor_is_visible_or_deliberately_qualified() -> None:
    """No v2 episode may anchor to an invisible instance while a visible one exists.

    The two tier-qualified exceptions are named, not waived: tier C exists to
    force a search and tier E's target is absent by construction.
    """

    table = landmarks_for(episode_set_spec(EPISODE_SET_V2))
    offenders = []
    for episode in generate_minival(version=EPISODE_SET_V2):
        target = episode.target_entity_id
        if episode.absent_target or episode.tier in {"C", "E"} or target not in table:
            continue
        entry = table[target]
        if entry.get("kind") != "object":
            continue
        label = entry["label"]
        siblings = [
            key
            for key, value in table.items()
            if value.get("kind") == "object" and value.get("label") == label
        ]
        if len(siblings) < 2:
            continue
        if visible_from_start(episode.start_pose, entry["position"]):
            continue
        if any(
            visible_from_start(episode.start_pose, table[key]["position"])
            for key in siblings
        ):
            offenders.append((episode.episode_id, episode.instruction, target))
    assert not offenders, f"v2 anchors to an unobservable instance: {offenders}"


def test_visibility_constants_match_the_world() -> None:
    """The generator's copy of the frustum must equal the world's own defaults."""

    import inspect

    from parcel_robot.perception.city_semantics import visible_city_semantics

    signature = inspect.signature(visible_city_semantics)
    assert signature.parameters["max_range_m"].default == VISIBILITY_MAX_RANGE_M
    assert math.isclose(
        signature.parameters["half_fov_rad"].default, VISIBILITY_HALF_FOV_RAD
    )


def test_visibility_predicate_matches_the_worlds_predicate() -> None:
    """Same inputs, same answer — not just the same constants."""

    from parcel_robot.perception.city_semantics import _visible

    poses = [(0.0, 0.0, 0.0), (0.1, -0.05, 1.0), (-6.0, -6.0, 2.5), (2.0, 2.0, -1.4)]
    targets = [(5.0, 3.1), (-5.0, 3.15), (0.2, 3.15), (13.0, 0.0), (0.0, 0.0)]
    for pose in poses:
        for target in targets:
            assert visible_from_start(pose, target) == _visible(
                target, pose[0], pose[1], pose[2], VISIBILITY_MAX_RANGE_M, VISIBILITY_HALF_FOV_RAD
            )


def test_correction_c_is_the_default_rule_and_v1_can_still_be_replayed() -> None:
    assert DEFAULT_ARRIVAL_RULE == DERIVED_ARRIVAL_RULE
    assert ARRIVAL_RULE_FOR_VERSION[EPISODE_SET_V2] == DERIVED_ARRIVAL_RULE
    assert ARRIVAL_RULE_FOR_VERSION[EPISODE_SET_V1] == FROZEN_ARRIVAL_RULE


def test_v1a_is_correction_a_alone() -> None:
    """The bridge's intermediate must differ from v1 only by the landmark table."""

    spec_v1 = episode_set_spec(EPISODE_SET_V1)
    spec_v1a = episode_set_spec(EPISODE_SET_V1A)
    assert spec_v1a.landmark_section == "derived"
    assert spec_v1a.word_boundary_class_match == spec_v1.word_boundary_class_match
    assert spec_v1a.visible_instance_anchoring == spec_v1.visible_instance_anchoring
    # The two spec-fix rows must therefore be untouched in v1a.
    v1, v1a = _by_id(EPISODE_SET_V1), _by_id(EPISODE_SET_V1A)
    for episode_id in (B05, D15):
        assert v1a[episode_id].target_entity_id == v1[episode_id].target_entity_id
