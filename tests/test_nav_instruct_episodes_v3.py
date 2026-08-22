"""Eval integrity for the v3 re-freeze (one correction: the next_to band).

The same four properties ``test_nav_instruct_episodes_v2.py`` pins for v2, plus
the two this re-freeze adds because it is the first one driven by a change in
``src/`` rather than in the eval:

1. **v1 and v2 did not move.** A K0 change is the most dangerous kind of
   re-freeze trigger, because the superseded sets were generated *through* the
   builder that changed. Both digests, both checked-in directories and the
   frozen ledger prefix are pinned here as well as in the v2 module.
2. **Regeneration diff.** The checked-in v3 files must equal a fresh
   generation.
3. **Oracle isolation.** v3's landmark table must *be* the artifact's derived
   section, exactly as v2's is — the band change must not have brought a
   second table with it.
4. **The correction does what it says, and only that.** Only ``next_to`` goals
   move, they move by exactly the anchor's radius, and every other family is
   byte-identical to v2.
5. **The live builder and the frozen sets disagree, on purpose.** v3's goals
   come from today's ``object_next_to_goal_region``; v1/v2's do not, and must
   not.
6. **The ledger says which set it ran.**
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evals.nav_instruct.bridge_v2_v3 import spec_bridge
from evals.nav_instruct.generator import (
    EPISODE_SET_V1,
    EPISODE_SET_V2,
    EPISODE_SET_V3,
    episode_set_spec,
    generate_minival,
    landmarks_for,
    matrix_digest,
    write_episode_files,
)
from evals.nav_instruct.runner import ARRIVAL_RULE_FOR_VERSION, DERIVED_ARRIVAL_RULE
from evals.nav_instruct.scene_truth import derived_landmark_table
from parcel_robot.instructnav.scoring import (
    NEXT_TO_BAND_M,
    next_to_band_from_centre,
    object_next_to_goal_region,
)

REPO = Path(__file__).resolve().parents[1]
EPISODES_DIR = REPO / "evals" / "nav_instruct" / "episodes"
LEDGER = REPO / "evals" / "nav_instruct" / "results" / "ledger.jsonl"
BRIDGE = REPO / "evals" / "nav_instruct" / "results" / "bridge_v2_v3.json"

FROZEN_V1_DIGEST = "cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf"
FROZEN_V2_DIGEST = "a17c04dbec43a1749386c304060fb479a71f27d4b51b8c1b0fbb949753fc563d"
FROZEN_V3_DIGEST = "919a0fea836363a6f6d04d3fb186b0dcb493aa6c76357d8af2b0c05408c556aa"

#: The ledger prefix before the v3 rows were appended: the nine original lines
#: plus the two v2 rows. Pinned so a v3 append cannot touch a byte of them.
FROZEN_LEDGER_PREFIX_LINES = 11
FROZEN_LEDGER_PREFIX_SHA256 = (
    "7c131895600022666a13001ae08c58345b5a3ccc4727eb55a582873be62048a9"
)

BENCH = "nav-object_relative-A-00-3efbba45"


def _by_id(version: str) -> dict:
    return {ep.episode_id: ep for ep in generate_minival(version=version)}


# --------------------------------------------------------------------------
# 1. the superseded sets did not move
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "digest"),
    [(EPISODE_SET_V1, FROZEN_V1_DIGEST), (EPISODE_SET_V2, FROZEN_V2_DIGEST)],
)
def test_the_band_change_did_not_move_a_frozen_digest(version: str, digest: str) -> None:
    """The property this whole re-freeze exists to protect.

    ``NEXT_TO_BAND_M`` is now measured to the anchor's surface. v1 and v2 were
    generated when it was measured to the centre, and their goals must still
    carry the centre-anchored band — otherwise every row ever measured against
    them silently means something else.
    """

    episodes = generate_minival(version=version)
    assert matrix_digest(episodes) == digest
    for episode in episodes:
        if episode.family != "object_relative":
            continue
        assert episode.goal.band_m == pytest.approx(NEXT_TO_BAND_M)


def test_v1_is_still_the_default_and_v3_must_be_asked_for_by_name() -> None:
    assert matrix_digest(generate_minival()) == FROZEN_V1_DIGEST
    assert episode_set_spec().version == EPISODE_SET_V1
    assert episode_set_spec().next_to_band_reference == "centre"
    assert episode_set_spec(EPISODE_SET_V2).next_to_band_reference == "centre"
    assert episode_set_spec(EPISODE_SET_V3).next_to_band_reference == "surface"


@pytest.mark.slow  # card P0-E: frozen-digest integrity is a nightly evidence ratchet
def test_frozen_ledger_prefix_is_byte_identical_after_the_v3_append() -> None:
    lines = LEDGER.read_text(encoding="utf-8").splitlines(keepends=True)
    assert len(lines) > FROZEN_LEDGER_PREFIX_LINES, "the v3 rows were never appended"
    prefix = "".join(lines[:FROZEN_LEDGER_PREFIX_LINES]).encode("utf-8")
    assert hashlib.sha256(prefix).hexdigest() == FROZEN_LEDGER_PREFIX_SHA256


# --------------------------------------------------------------------------
# 2. regeneration diff over the checked-in v3 files
# --------------------------------------------------------------------------


@pytest.mark.slow  # card P0-E: frozen-digest integrity is a nightly evidence ratchet
def test_checked_in_v3_files_equal_a_fresh_generation(tmp_path: Path) -> None:
    episodes = generate_minival(version=EPISODE_SET_V3)
    assert matrix_digest(episodes) == FROZEN_V3_DIGEST
    write_episode_files(episodes, tmp_path, version=EPISODE_SET_V3, seed=20260804)
    checked_in = EPISODES_DIR / EPISODE_SET_V3
    fresh_names = sorted(p.name for p in tmp_path.iterdir())
    stored_names = sorted(p.name for p in checked_in.iterdir())
    assert fresh_names == stored_names
    for name in fresh_names:
        assert (tmp_path / name).read_bytes() == (checked_in / name).read_bytes(), (
            f"v3/{name} differs from a fresh generation — either it was "
            "hand-edited or the generator changed without regenerating"
        )


@pytest.mark.slow  # card P0-E: frozen-digest integrity is a nightly evidence ratchet
def test_v3_manifest_records_the_correction_it_carries() -> None:
    manifest = json.loads((EPISODES_DIR / EPISODE_SET_V3 / "manifest.json").read_text())
    assert manifest["sha256"] == FROZEN_V3_DIGEST
    assert manifest["episode_set_version"] == EPISODE_SET_V3
    assert manifest["landmark_section"] == "derived"
    assert manifest["word_boundary_class_match"] is True
    assert manifest["visible_instance_anchoring"] is True
    assert "surface-anchored next_to band" in manifest["provenance"]


def test_episode_ids_are_identical_across_every_version() -> None:
    """The old→new mapping must stay total: a dropped id orphans a frozen row."""

    ids = {
        version: set(_by_id(version))
        for version in (EPISODE_SET_V1, EPISODE_SET_V2, EPISODE_SET_V3)
    }
    assert ids[EPISODE_SET_V1] == ids[EPISODE_SET_V2] == ids[EPISODE_SET_V3]


# --------------------------------------------------------------------------
# 3. oracle isolation
# --------------------------------------------------------------------------


def test_v3_landmark_table_is_the_derived_section_not_a_copy() -> None:
    spec = episode_set_spec(EPISODE_SET_V3)
    assert spec.landmark_section == "derived"
    assert landmarks_for(spec) == derived_landmark_table()
    # ...and identical to v2's, so the band is the only thing that moved.
    assert landmarks_for(spec) == landmarks_for(episode_set_spec(EPISODE_SET_V2))


# --------------------------------------------------------------------------
# 4. the correction does what it says, and only that
# --------------------------------------------------------------------------


def test_only_next_to_goals_moved_and_they_moved_by_the_anchor_radius() -> None:
    v2, v3 = _by_id(EPISODE_SET_V2), _by_id(EPISODE_SET_V3)
    moved, unchanged = [], []
    for episode_id, before in v2.items():
        after = v3[episode_id]
        if before.goal.as_dict() == after.goal.as_dict():
            unchanged.append(episode_id)
            continue
        moved.append(episode_id)
        assert before.family == "object_relative", episode_id
        radius = before.goal.anchor_footprint_m
        assert after.goal.anchor_footprint_m == pytest.approx(radius)
        assert after.goal.band_m == pytest.approx(
            (NEXT_TO_BAND_M[0] + radius, NEXT_TO_BAND_M[1] + radius)
        )
        # Everything about the episode except the goal is untouched.
        assert after.instruction == before.instruction
        assert after.start_pose == before.start_pose
        assert after.target_entity_id == before.target_entity_id
        assert after.seed == before.seed
    assert len(moved) == 5, moved
    assert len(unchanged) == 20, len(unchanged)


def test_the_spec_bridge_says_only_object_relative_moved() -> None:
    bridge = spec_bridge()
    assert bridge["id_mapping_is_total"]
    assert bridge["only_object_relative_moved"]
    assert bridge["counts_by_change"] == {"next_to_band": 5, "unchanged": 20}
    assert bridge["digests"] == {
        EPISODE_SET_V2: FROZEN_V2_DIGEST,
        EPISODE_SET_V3: FROZEN_V3_DIGEST,
    }


def test_v3_goals_come_from_todays_k0_builder_and_the_frozen_ones_do_not() -> None:
    """The re-freeze is exactly "adopt the live builder", asserted as such."""

    v2, v3 = _by_id(EPISODE_SET_V2), _by_id(EPISODE_SET_V3)
    for episode_id, episode in v3.items():
        if episode.family != "object_relative":
            continue
        centre = episode.goal.center
        radius = episode.goal.anchor_footprint_m
        assert centre is not None
        live = object_next_to_goal_region(
            centre, radius, entity_id=episode.goal.anchor_entity
        )
        assert episode.goal.as_dict() == live.as_dict()
        assert v2[episode_id].goal.as_dict() != live.as_dict()


def test_the_bench_episode_is_the_one_the_change_was_made_for() -> None:
    bench = _by_id(EPISODE_SET_V3)[BENCH]
    assert bench.instruction == "sit next to the bench"
    assert bench.goal.anchor_footprint_m == pytest.approx(0.733757)
    assert bench.goal.band_m == pytest.approx(next_to_band_from_centre(0.733757))
    assert bench.goal.band_m == pytest.approx((1.133757, 2.233757))


# --------------------------------------------------------------------------
# 5. ledger + bridge artifacts
# --------------------------------------------------------------------------


def test_the_v3_ledger_rows_declare_their_version_and_rule() -> None:
    rows = [
        json.loads(line)
        for line in LEDGER.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    v3_rows = [row for row in rows if row.get("baseline_version") == EPISODE_SET_V3]
    assert len(v3_rows) >= 2, "expected a v3 baseline row and a v3 candidate row"
    assert {row["mode"] for row in v3_rows} >= {"baseline", "candidate"}
    for row in v3_rows:
        assert row["episode_digest"] == FROZEN_V3_DIGEST
        # v3 changes the band and nothing else — in particular not the rule.
        assert row["arrival_rule"] == DERIVED_ARRIVAL_RULE
        assert ARRIVAL_RULE_FOR_VERSION[EPISODE_SET_V3] == DERIVED_ARRIVAL_RULE
        assert "sr_frozen_rule" in row


def test_the_bridge_artifact_isolates_this_change_and_reports_the_prediction() -> None:
    """The bridge must say what it measured *and* whether it matched.

    A bridge that only reports the measurement lets a refuted prediction
    disappear. This one carries both, and this test pins that it does.
    """

    payload = json.loads(BRIDGE.read_text(encoding="utf-8"))
    assert payload["from_version"] == EPISODE_SET_V2
    assert payload["to_version"] == EPISODE_SET_V3
    assert set(payload["corrections"]) == {"d"}
    assert payload["next_to_band_reference"] == {
        EPISODE_SET_V2: "centre",
        EPISODE_SET_V3: "surface",
    }
    compare = payload["predicted_vs_measured"]
    assert compare["prediction"]["k0_predicate_flips"] == [BENCH]
    for mode in ("baseline", "candidate"):
        cell = compare["per_mode"][mode]
        assert cell["k0_predicate_flips"] == [BENCH]
        assert cell["matches_predicted_flips"] is True
    # The prediction's *other* half was refuted by the measurement, and the
    # artifact says so rather than quietly agreeing with itself.
    assert compare["prediction_confirmed"] is False
