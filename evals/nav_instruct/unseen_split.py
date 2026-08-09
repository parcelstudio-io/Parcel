"""val_seen vs val_unseen — the scene-generalization split (instrument 1).

The headline number this produces is the **gap**, not either side of it.

How the split is kept honest
----------------------------
The unseen pack is the *same* episode set logic — same instructions, same
family/tier structure, same start poses, same v2 corrections — regenerated
against each unseen scene's **derived** landmark table. Only the scene moves.
So a gap cannot be an artefact of different episodes, different phrasings or
different difficulty tiers; it is scenes.

Which families
--------------
Only the three scene-dependent families run:
``region_goal``, ``object_goal``, ``object_relative``. ``follow_owner`` and
``circle_owner`` are scored against an owner-anchored disc at a fixed position
and would contribute the same number in every scene — including them would
dilute the gap with episodes that cannot express it. Their absence is a
deliberate narrowing, stated here rather than buried in a filter.

Binding rule from the plan: **the unseen split is never tuned against.** Nothing
in this module reads a result and changes a parameter, and the scenes are frozen
by seed.

Usage::

    .parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 --scenes all
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.nav_instruct.generator import (
    EPISODE_SET_V2,
    EpisodeSpec,
    episode_set_spec,
    generate_minival,
    landmarks_for,
    matrix_digest,
)
from evals.nav_instruct.runner import (
    ARRIVAL_RULE_FOR_VERSION,
    RUNNER_VERSION,
    NavInstructRunner,
    aggregate_results,
)
from evals.nav_instruct.scene_gen import REPO_ROOT, V2_SCENE_TRUTH_IDS, split_manifests
from evals.nav_instruct.scene_truth import SCENE_PATH

#: Families whose goals depend on the scene. See the module docstring.
UNSEEN_FAMILIES: tuple[str, ...] = ("region_goal", "object_goal", "object_relative")

SEEN_SCENE_ID = "city_block"

RESULTS_DIR = Path(__file__).resolve().parent / "results"
SPLIT_REPORT_TEMPLATE = "scene_split_{mode}.json"


def _native_table(derived: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """A scene manifest's derived section in the generator's native tuple shape."""

    out: dict[str, dict[str, Any]] = {}
    for entity_id in V2_SCENE_TRUTH_IDS:
        entry = derived[entity_id]
        record: dict[str, Any] = {"kind": entry["kind"], "label": entry["label"]}
        if "polygon" in entry:
            record["polygon"] = tuple((float(p[0]), float(p[1])) for p in entry["polygon"])
        if "position" in entry:
            record["position"] = (float(entry["position"][0]), float(entry["position"][1]))
        if "radius_m" in entry:
            record["radius_m"] = float(entry["radius_m"])
        out[entity_id] = record
    return out


def scene_pack(
    scene_id: str,
    landmarks: dict[str, dict[str, Any]],
    *,
    seed: int = 20260804,
    families: Sequence[str] = UNSEEN_FAMILIES,
) -> tuple[EpisodeSpec, ...]:
    """The v2 minival regenerated against one scene, narrowed to ``families``."""

    episodes = generate_minival(seed=seed, version=EPISODE_SET_V2, landmarks=landmarks)
    return tuple(
        dataclasses.replace(episode, episode_id=f"{scene_id}|{episode.episode_id}")
        for episode in episodes
        if episode.family in families
    )


def seen_pack(*, seed: int = 20260804) -> tuple[str, Path, tuple[EpisodeSpec, ...]]:
    landmarks = landmarks_for(episode_set_spec(EPISODE_SET_V2))
    return SEEN_SCENE_ID, SCENE_PATH, scene_pack(SEEN_SCENE_ID, landmarks, seed=seed)


def unseen_packs(
    *,
    seed: int = 20260804,
    manifests: Sequence[dict[str, Any]] | None = None,
) -> list[tuple[str, Path, tuple[EpisodeSpec, ...]]]:
    out: list[tuple[str, Path, tuple[EpisodeSpec, ...]]] = []
    for manifest in split_manifests() if manifests is None else manifests:
        scene_id = str(manifest["scene_id"])
        scene_path = REPO_ROOT / manifest["scene"]["path"]
        landmarks = _native_table(manifest["derived"])
        out.append((scene_id, scene_path, scene_pack(scene_id, landmarks, seed=seed)))
    return out


def run_one_scene(
    scene_id: str,
    scene_path: Path,
    episodes: Sequence[EpisodeSpec],
    *,
    mode: str,
    max_steps: int,
) -> dict[str, Any]:
    runner = NavInstructRunner(
        max_steps=max_steps,
        mode=mode,
        arrival_rule=ARRIVAL_RULE_FOR_VERSION[EPISODE_SET_V2],
        scene=scene_path,
    )
    results = [runner.run_episode(episode) for episode in episodes]
    aggregate = aggregate_results(
        results, episode_set_version=EPISODE_SET_V2, scene=runner.scene
    )
    return {
        "scene_id": scene_id,
        "scene": str(scene_path.relative_to(REPO_ROOT)),
        "n": aggregate["n"],
        "episode_digest": matrix_digest(tuple(episodes)),
        "sr": aggregate["sr"],
        "sr_frozen_rule": aggregate["sr_frozen_rule"],
        "spl": aggregate["spl"],
        "mean_dtg_m": aggregate["mean_dtg_m"],
        "collision_total": aggregate["collision_total"],
        "failure_histogram": aggregate["failure_histogram"],
        "authority_histogram": aggregate["authority_histogram"],
        "by_family_tier": aggregate["by_family_tier"],
        "successes": sorted(r.episode_id for r in results if r.score.success),
    }


def run_split(
    *,
    mode: str = "candidate",
    max_steps: int = 200,
    seed: int = 20260804,
    scenes: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """Run the seen scene and every unseen scene; report the gap."""

    seen_id, seen_path, seen_episodes = seen_pack(seed=seed)
    seen = run_one_scene(
        seen_id, seen_path, seen_episodes, mode=mode, max_steps=max_steps
    )
    manifests = split_manifests()
    if scenes is not None:
        wanted = {Path(item).resolve() for item in scenes}
        manifests = [
            manifest
            for manifest in manifests
            if (REPO_ROOT / manifest["scene"]["path"]).resolve() in wanted
        ]
    unseen = [
        run_one_scene(scene_id, scene_path, episodes, mode=mode, max_steps=max_steps)
        for scene_id, scene_path, episodes in unseen_packs(seed=seed, manifests=manifests)
    ]
    n_unseen = max(len(unseen), 1)
    unseen_sr = sum(item["sr"] for item in unseen) / n_unseen
    unseen_spl = sum(item["spl"] for item in unseen) / n_unseen
    unseen_dtg = sum(item["mean_dtg_m"] for item in unseen) / n_unseen
    return {
        "kind": "scene_generalization_split",
        "generated_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "runner_version": RUNNER_VERSION,
        "episode_set_version": EPISODE_SET_V2,
        "mode": mode,
        "seed": seed,
        "families": list(UNSEEN_FAMILIES),
        "episodes_per_scene": len(seen_episodes),
        "frozen_baseline": False,
        "never_tuned_against": True,
        "val_seen": seen,
        "val_unseen_scenes": unseen,
        "val_unseen_mean": {
            "scenes": len(unseen),
            "sr": unseen_sr,
            "spl": unseen_spl,
            "mean_dtg_m": unseen_dtg,
            "collision_total": sum(item["collision_total"] for item in unseen),
        },
        "gap": {
            "sr_seen_minus_unseen": seen["sr"] - unseen_sr,
            "spl_seen_minus_unseen": seen["spl"] - unseen_spl,
            "mean_dtg_unseen_minus_seen_m": unseen_dtg - seen["mean_dtg_m"],
            "reading": (
                "positive sr gap = worse on scenes nobody tuned against, which "
                "is the expected and informative direction"
            ),
        },
    }


def markdown_table(payload: dict[str, Any]) -> str:
    lines = [
        (
            f"**mode {payload['mode']} · {payload['episodes_per_scene']} "
            f"episodes/scene · families {', '.join(payload['families'])}**"
        ),
        "",
        "| scene | split | SR | SPL | mean dtg (m) | collisions |",
        "|---|---|---|---|---|---|",
    ]
    seen = payload["val_seen"]
    lines.append(
        f"| `{seen['scene_id']}` | **val_seen** | {seen['sr']:.3f} | {seen['spl']:.4f} | "
        f"{seen['mean_dtg_m']:.3f} | {seen['collision_total']} |"
    )
    for item in payload["val_unseen_scenes"]:
        lines.append(
            f"| `{item['scene_id']}` | val_unseen | {item['sr']:.3f} | {item['spl']:.4f} | "
            f"{item['mean_dtg_m']:.3f} | {item['collision_total']} |"
        )
    mean = payload["val_unseen_mean"]
    gap = payload["gap"]
    lines.append(
        f"| — | **val_unseen mean ({mean['scenes']})** | {mean['sr']:.3f} | "
        f"{mean['spl']:.4f} | {mean['mean_dtg_m']:.3f} | {mean['collision_total']} |"
    )
    lines.append("")
    lines.append(
        f"**gap (seen − unseen): SR {gap['sr_seen_minus_unseen']:+.3f} · "
        f"SPL {gap['spl_seen_minus_unseen']:+.4f} · "
        f"mean dtg {gap['mean_dtg_unseen_minus_seen_m']:+.3f} m worse unseen**"
    )
    return "\n".join(lines)


def write_report(payload: dict[str, Any], path: Path | None = None) -> Path:
    if path is None:
        path = RESULTS_DIR / SPLIT_REPORT_TEMPLATE.format(mode=payload["mode"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path
