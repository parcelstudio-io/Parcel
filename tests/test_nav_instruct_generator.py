"""N-S4: seeded episode generator tiers A–E, ≥20/family, deterministic."""

from __future__ import annotations

from evals.nav_instruct.generator import (
    EPISODES_PER_FAMILY_MIN,
    FAMILIES,
    TIERS,
    generate_episode_matrix,
    generate_minival,
    matrix_digest,
    write_episode_files,
)


def test_matrix_has_all_families_tiers_and_min_counts():
    episodes = generate_episode_matrix(seed=20260804, per_family=25)
    assert len(episodes) == 25 * len(FAMILIES)
    for family in FAMILIES:
        family_eps = [ep for ep in episodes if ep.family == family]
        assert len(family_eps) >= EPISODES_PER_FAMILY_MIN
        tiers = {ep.tier for ep in family_eps}
        assert tiers == set(TIERS)


def test_same_seed_byte_identical():
    a = generate_episode_matrix(seed=42, per_family=20)
    b = generate_episode_matrix(seed=42, per_family=20)
    assert matrix_digest(a) == matrix_digest(b)
    assert [ep.as_dict() for ep in a] == [ep.as_dict() for ep in b]


def test_different_seed_diverges():
    a = matrix_digest(generate_episode_matrix(seed=1, per_family=20))
    b = matrix_digest(generate_episode_matrix(seed=2, per_family=20))
    assert a != b


def test_tier_b_marks_outside_frustum_and_tier_e_absent():
    episodes = generate_episode_matrix(seed=7, per_family=20)
    tier_b = [ep for ep in episodes if ep.tier == "B" and ep.family == "region_goal"]
    assert tier_b
    assert all("outside_frustum" in ep.notes for ep in tier_b)

    tier_e = [
        ep
        for ep in episodes
        if ep.tier == "E" and ep.family in {"region_goal", "object_goal"}
    ]
    assert tier_e
    assert all(ep.absent_target for ep in tier_e)


def test_write_episode_files_and_minival(tmp_path):
    episodes = generate_minival(seed=20260804, count=25)
    assert len(episodes) == 25
    paths = write_episode_files(episodes, tmp_path)
    assert len(paths) == 25
    assert (tmp_path / "manifest.json").is_file()
