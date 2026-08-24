"""Eval integrity for the val_unseen split and the mutation panel (Wave 2).

Three properties, and each is a way the split could quietly stop meaning
anything.

1. **The scenes are frozen.** A checked-in scene that differs from a fresh
   generation from its seed means the benchmark moved. That is the same
   golden-file discipline ``scene_truth.json`` already has, applied to a
   directory of scenes.
2. **The acceptance filters bite.** A rejection sampler whose filters never
   reject is not a filter, and a filter that would reject the *frozen* scene is
   calibrated wrong. Both directions are asserted.
3. **The split is a scene comparison, not an episode comparison.** The unseen
   packs must carry the same instructions, tiers and start poses as the seen
   pack — otherwise the gap is measuring different episodes.

The mutation panel's own machinery is checked here too (pure parts only; the
panel itself is a nightly script): the six defects are the plan's six, every
mutation restores what it patched, and a run that differs from clean with no
check reddened is reported as a survivor rather than swallowed.
"""

from __future__ import annotations

import functools
import json
import sys
from pathlib import Path

import pytest

from evals.nav_instruct.scene_gen import (
    OUT_DIR,
    REQUIRED_LANDMARKS,
    ROBOT_CLEARANCE_M,
    V2_SCENE_TRUTH_IDS,
    VAL_UNSEEN_SEEDS,
    SceneRejected,
    check_navigability,
    check_overlap,
    generate_scene,
    sample_params,
    scene_xml,
    split_manifests,
)
from evals.nav_instruct.scene_truth import SCENE_PATH, V2_LANDMARK_IDS, derive_scene_truth
from evals.nav_instruct.unseen_split import UNSEEN_FAMILIES, seen_pack, unseen_packs

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. the scenes are frozen
# ---------------------------------------------------------------------------


def test_the_split_has_the_five_frozen_scenes() -> None:
    manifests = split_manifests()
    assert [item["seed"] for item in manifests] == sorted(VAL_UNSEEN_SEEDS)
    for manifest in manifests:
        assert manifest["split"] == "val_unseen"
        assert manifest["never_tuned_against"] is True
        for key in ("scene", "semantics_sidecar", "derived", "acceptance", "params"):
            assert key in manifest


@pytest.mark.parametrize("seed", VAL_UNSEEN_SEEDS)
def test_checked_in_scene_equals_a_fresh_generation(seed: int) -> None:
    """A scene that drifted from its seed is a benchmark that moved."""

    fresh = generate_scene(seed, out_dir=OUT_DIR, write=False)
    stored = json.loads((OUT_DIR / f"{fresh['scene_id']}.truth.json").read_text())
    assert stored == fresh, (
        f"{fresh['scene_id']} differs from a fresh generation — either the MJCF "
        "was hand-edited or the sampler changed without regenerating"
    )
    scene_path = REPO / stored["scene"]["path"]
    assert scene_path.is_file()
    assert (REPO / stored["semantics_sidecar"]).is_file()


@pytest.mark.parametrize("seed", VAL_UNSEEN_SEEDS)
def test_every_scene_carries_a_loadable_semantics_sidecar(seed: int) -> None:
    """The sidecar is an artifact, not decoration: the real loader must accept it."""

    from parcel_robot.perception.scene_semantics import load_scene_semantics

    manifest = json.loads((OUT_DIR / f"val_unseen_{seed}.truth.json").read_text())
    sidecar = load_scene_semantics(REPO / manifest["semantics_sidecar"])
    assert sidecar.scene == manifest["scene"]["path"]
    # The vocabulary is copied from the frozen block's sidecar, never retyped.
    reference = load_scene_semantics(REPO / "configs/scenes/city_block.semantics.yaml")
    assert sidecar.object_prefix_table() == reference.object_prefix_table()
    assert sidecar.alias_table() == reference.alias_table()


@pytest.mark.parametrize("seed", VAL_UNSEEN_SEEDS)
def test_every_scene_supplies_the_landmarks_the_episode_pack_needs(seed: int) -> None:
    manifest = json.loads((OUT_DIR / f"val_unseen_{seed}.truth.json").read_text())
    derived = manifest["derived"]
    missing = [key for key in V2_SCENE_TRUTH_IDS if key not in derived]
    assert not missing, f"val_unseen_{seed} cannot build the v2 pack: missing {missing}"


def test_the_generator_and_the_scene_truth_module_agree_on_the_id_set() -> None:
    """One id list, asserted equal rather than kept in sync by hand."""

    assert set(V2_SCENE_TRUTH_IDS) == set(V2_LANDMARK_IDS)


# ---------------------------------------------------------------------------
# 2. the filters bite, and are calibrated against the frozen scene
# ---------------------------------------------------------------------------


def test_the_frozen_city_block_passes_the_filters_it_is_the_reference_for(tmp_path) -> None:
    """A filter that would reject the scene every number was measured on is wrong.

    The frozen block has no ``SceneParams``, so only the geometry filters that
    read the derived table are applied — which is exactly the half that could
    be mis-calibrated (the building-box half is checked against a proposal
    below).
    """

    from evals.nav_instruct.scene_gen import check_support

    derived = derive_scene_truth(SCENE_PATH)
    check_support(derived)
    for entity_id in REQUIRED_LANDMARKS:
        assert entity_id in derived


def _derive_proposal(params, tag: str):
    import tempfile

    from evals.nav_instruct.scene_gen import OUT_DIR as generated_dir

    # Written inside the generated-scenes directory so the MJCF's relative
    # ``include`` of the Go2 model resolves exactly as an emitted scene's does.
    with tempfile.NamedTemporaryFile(
        dir=generated_dir, suffix=".xml", mode="w", delete=True
    ) as handle:
        handle.write(scene_xml(params, scene_id=f"probe_{tag}"))
        handle.flush()
        return derive_scene_truth(handle.name)


def test_the_overlap_filter_rejects_a_scene_it_should() -> None:
    """A filter is only a filter if a bad proposal actually fails it.

    Built by hand rather than hunted for in the sampler's stream: a filter
    proved by "some seed happened to trip it" is proved by luck.
    """

    import dataclasses

    good = sample_params(VAL_UNSEEN_SEEDS[0], 0)
    # Put the bench where the lamppost already is.
    bad = dataclasses.replace(good, bench_x=good.lamp_post_1_x)
    with pytest.raises(SceneRejected, match="overlap"):
        check_overlap(bad, _derive_proposal(bad, "overlap"))


def test_the_navigability_filter_rejects_a_scene_it_should() -> None:
    """Wall a building across the road and no start pose can reach anything."""

    import dataclasses

    good = sample_params(VAL_UNSEEN_SEEDS[0], 0)
    wall = ((0.0, 0.0, 8.0, 8.0), *good.buildings)
    bad = dataclasses.replace(good, buildings=wall)
    with pytest.raises(SceneRejected, match="navigability"):
        check_navigability(bad, _derive_proposal(good, "nav"))


def test_the_support_filter_rejects_furniture_off_the_pavement() -> None:
    from evals.nav_instruct.scene_gen import check_support

    good = sample_params(VAL_UNSEEN_SEEDS[0], 0)
    # Drop the bench onto the road, off its pavement.
    derived = _derive_proposal(good, "support")
    derived["bench_1"] = {
        **derived["bench_1"],
        "position": [derived["bench_1"]["position"][0], -0.5],
    }
    with pytest.raises(SceneRejected, match="support"):
        check_support(derived)


def test_navigability_clearance_is_derived_from_the_robot_profile() -> None:
    from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE

    assert ROBOT_CLEARANCE_M > DEFAULT_ROBOT_PROFILE.footprint_radius_m
    assert ROBOT_CLEARANCE_M == pytest.approx(
        DEFAULT_ROBOT_PROFILE.footprint_radius_m + 0.32
    )


# ---------------------------------------------------------------------------
# 3. the split compares scenes, not episodes
# ---------------------------------------------------------------------------


def test_unseen_packs_carry_the_same_episodes_as_the_seen_pack() -> None:
    """Same instructions, tiers and start poses — only the scene may differ."""

    _, _, seen = seen_pack()
    assert seen, "the seen pack is empty"
    seen_by_key = {(ep.family, ep.tier): ep for ep in seen}
    assert {ep.family for ep in seen} == set(UNSEEN_FAMILIES)
    for scene_id, _, pack in unseen_packs():
        assert len(pack) == len(seen), f"{scene_id} has a different episode count"
        for episode in pack:
            twin = seen_by_key[(episode.family, episode.tier)]
            assert episode.instruction == twin.instruction
            assert episode.start_pose == twin.start_pose
            assert episode.episode_id.startswith(f"{scene_id}|")


def test_unseen_goals_actually_move_with_the_scene() -> None:
    """If the goals did not move, the split would be five copies of one number."""

    _, _, seen = seen_pack()
    seen_goals = {(ep.family, ep.tier): ep.goal.as_dict() for ep in seen}
    for scene_id, _, pack in unseen_packs():
        moved = sum(
            1
            for episode in pack
            if episode.goal.as_dict() != seen_goals[(episode.family, episode.tier)]
        )
        assert moved > 0, f"{scene_id} produced goals identical to the seen scene"


def test_the_spatial_families_are_excluded_on_purpose() -> None:
    """Owner-anchored goals are scene-independent and would dilute the gap."""

    assert "follow_owner" not in UNSEEN_FAMILIES
    assert "circle_owner" not in UNSEEN_FAMILIES


# ---------------------------------------------------------------------------
# the mutation panel's own machinery (pure parts; the panel is a nightly script)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _panel():
    """Import the nightly panel script as a module.

    Registered in ``sys.modules`` before execution: its dataclasses resolve
    their own module at class-creation time and a module that is not registered
    makes that lookup return ``None``.
    """

    import importlib.util

    name = "parcel_mutation_panel"
    spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / "mutation_panel.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


#: Instrument 6's original six defects. None of them may disappear.
PLAN_SIX_DEFECTS = frozenset(
    {
        "arrival_radius_x2",
        "reactive_gate_disabled",
        "pose_offset_0m5",
        "inverted_relation",
        "dropped_detections",
        "doubled_envelope",
    }
)
#: Defects added since, each by a named card. The set stays EXACT — a mutant may
#: not appear without landing here — but growing the panel is the point of it,
#: so a new defect is one line rather than a red build.
ADDED_DEFECTS = {
    # Card VS-6 (2026-08-11): a view-consistent phantom, i.e. perception
    # inventing a persistent object the multi-view confirmer cannot reject.
    "phantom_view_consistent": "VS-6",
}


def test_the_panel_seeds_exactly_the_defects_its_cards_declare() -> None:
    assert set(_panel().MUTATIONS) == PLAN_SIX_DEFECTS | set(ADDED_DEFECTS)


def test_every_mutation_restores_what_it_patched() -> None:
    """A panel that leaks a defect into the process is the defect."""

    panel = _panel()
    from parcel_robot import authority
    from parcel_robot.instructnav import scoring
    from parcel_robot.simulation import headless_city

    watched = [
        (scoring.GoalRegion, "contains"),
        (authority, "DEFAULT_STAND_OFF_ENVELOPE"),
        (headless_city, "semantic_candidates_from_observation"),
    ]
    before = [getattr(target, name) for target, name in watched]
    for factory in panel.MUTATIONS.values():
        with factory():
            pass
    after = [getattr(target, name) for target, name in watched]
    assert before == after


def test_a_changed_run_with_no_reddened_check_is_reported_as_a_survivor() -> None:
    """The panel's own failure mode: swallowing blindness as a pass."""

    panel = _panel()
    clean = {
        "n": 1,
        "successes": ["a"],
        "mean_dtg_m": 1.0,
        "collisions": 0,
        "authority": {"agreement": 1},
        "failure_histogram": {"none": 1},
        "episodes": [
            {
                "episode_id": "a",
                "success": True,
                "distance_to_goal_m": 1.0,
                "final_xy": [0.0, 0.0],
                "path_length_m": 1.0,
                "failure": "none",
                "min_clearance_m": 1.0,
            }
        ],
    }
    # Same verdicts, same geometry within tolerance — but not the same run.
    changed = json.loads(json.dumps(clean))
    changed["episodes"][0]["path_length_m"] = 1.05
    assert panel.harness_checks(changed, clean) == panel.harness_checks(clean, clean)
    assert not panel._identical(changed, clean)


def test_an_identical_run_is_an_equivalent_mutant_not_a_survivor() -> None:
    panel = _panel()
    clean = {"a": 1, "episodes": []}
    assert panel._identical(json.loads(json.dumps(clean)), clean)
