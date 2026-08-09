"""Seeded walk-with-me scenario generator (pure; no runtime / MuJoCo imports).

K8 frozen pack: 10 scripts covering companion integration themes.
Deterministic: same freeze seed → byte-identical script set + digest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parcel_robot.instructnav.scoring import (
    GoalRegion,
    arrival_goal_region_for_relation,
    region_inside_goal_region,
)

PACK_ID = "walk-with-me-v1"
PACK_VERSION = "walk-with-me-v1.0-k8"
FREEZE_SEED = 20260805
GENERATOR_VERSION = "walk-with-me-generator-v1"

# Themes required by ADJUDICATION K8 / Fable integration pack brief.
THEMES: tuple[str, ...] = (
    "follow",
    "wait",
    "orbit",
    "sidewalk",
    "lamppost",
    "pause_resume",
    "barge_in",
    "absent_target",
    "owner_search",
    "curb_stop",
)

# Harness routing: what the runner may attempt.
HARNESSES: frozenset[str] = frozenset(
    {"navigation", "spatial", "resume", "behavior_stub"}
)

DOES_NOT_PROVE: tuple[str, ...] = (
    (
        "real-sensor or real-robot performance (stub/headless kinematic base; "
        "oracle owner track when used)"
    ),
    (
        "acoustic barge-in / AEC under motion (barge-in scripts exercise "
        "arbitration stubs only — no mic array, no TTS playback clock)"
    ),
    (
        "owner re-identification or enrolled gallery (search/reacquire scripts "
        "use identity-perfect scripted tracks)"
    ),
    (
        "curb/crossing physics or road-entry legality under real perception "
        "(curb-stop is a companion-moment stub on scripted polygon events)"
    ),
    (
        "camera-grounded semantics (sidewalk/lamppost goals use sim ground-truth "
        "polygons, not OCR or open-vocab detectors)"
    ),
    (
        "full voice→PlanIR→executive path (pause/resume hooks ResumeStore; "
        "utterance parsing is fixture-level, not ASR)"
    ),
    (
        "hardware commissioning or Orin budgets (evidence ladder ≤ L2 sim)"
    ),
)

# Canonical city landmarks (city_block.xml nominal poses; match nav_instruct).
_SIDEWALK_POLYGON: tuple[tuple[float, float], ...] = (
    (-8.0, 2.4),
    (8.0, 2.4),
    (8.0, 3.6),
    (-8.0, 3.6),
)
_LAMPPOST = {"position": (0.2, 3.15), "radius_m": 0.06, "label": "lamppost"}


@dataclass(frozen=True)
class ScriptEvent:
    """Timed scripted event inside a walk-with-me episode."""

    kind: str  # pause | resume | barge_in | lose_owner | curb_edge | collision_near
    at_s: float
    payload: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "at_s": self.at_s,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ScriptEvent:
        return cls(
            kind=str(data["kind"]),
            at_s=float(data["at_s"]),
            payload=dict(data.get("payload") or {}),
        )


@dataclass(frozen=True)
class ScriptSpec:
    """One frozen walk-with-me integration script."""

    script_id: str
    theme: str
    instruction: str
    seed: int
    start_pose: tuple[float, float, float]
    goal: GoalRegion | None
    harness: str
    events: tuple[ScriptEvent, ...]
    success_predicate: str
    duration_s: float
    absent_target: bool
    notes: str
    placement_overrides: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.theme not in THEMES:
            raise ValueError(f"unknown theme: {self.theme!r}")
        if self.harness not in HARNESSES:
            raise ValueError(f"unknown harness: {self.harness!r}")
        if not self.script_id or not self.instruction:
            raise ValueError("script_id and instruction must be non-empty")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.duration_s <= 0.0:
            raise ValueError("duration_s must be positive")

    def as_dict(self) -> dict[str, Any]:
        return {
            "script_id": self.script_id,
            "theme": self.theme,
            "instruction": self.instruction,
            "seed": self.seed,
            "start_pose": list(self.start_pose),
            "goal": None if self.goal is None else self.goal.as_dict(),
            "harness": self.harness,
            "events": [event.as_dict() for event in self.events],
            "success_predicate": self.success_predicate,
            "duration_s": self.duration_s,
            "absent_target": self.absent_target,
            "notes": self.notes,
            "placement_overrides": dict(self.placement_overrides),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ScriptSpec:
        goal_raw = data.get("goal")
        goal = (
            GoalRegion.from_mapping(goal_raw)
            if isinstance(goal_raw, Mapping)
            else None
        )
        events_raw = data.get("events") or ()
        events = tuple(ScriptEvent.from_mapping(item) for item in events_raw)
        pose = data["start_pose"]
        return cls(
            script_id=str(data["script_id"]),
            theme=str(data["theme"]),
            instruction=str(data["instruction"]),
            seed=int(data["seed"]),
            start_pose=(float(pose[0]), float(pose[1]), float(pose[2])),
            goal=goal,
            harness=str(data["harness"]),
            events=events,
            success_predicate=str(data["success_predicate"]),
            duration_s=float(data["duration_s"]),
            absent_target=bool(data.get("absent_target", False)),
            notes=str(data.get("notes") or ""),
            placement_overrides=dict(data.get("placement_overrides") or {}),
        )


def generate_frozen_pack(*, seed: int = FREEZE_SEED) -> tuple[ScriptSpec, ...]:
    """Build the frozen 10-script walk-with-me pack (byte-stable for ``seed``)."""

    # Per-script seeds derived from the pack freeze seed — never hand-edited
    # after freeze; regenerate via this function and check digest.
    base = int(seed)
    scripts = (
        _follow(base + 1),
        _wait(base + 2),
        _orbit(base + 3),
        _sidewalk(base + 4),
        _lamppost(base + 5),
        _pause_resume(base + 6),
        _barge_in(base + 7),
        _absent_target(base + 8),
        _owner_search(base + 9),
        _curb_stop(base + 10),
    )
    themes = {script.theme for script in scripts}
    if themes != set(THEMES):
        missing = set(THEMES) - themes
        raise RuntimeError(f"pack missing themes: {sorted(missing)}")
    if not (8 <= len(scripts) <= 12):
        raise RuntimeError(f"pack size out of 8–12 range: {len(scripts)}")
    return scripts


def matrix_digest(scripts: Sequence[ScriptSpec]) -> str:
    payload = json.dumps(
        [script.as_dict() for script in scripts],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_manifest(
    scripts: Sequence[ScriptSpec],
    *,
    seed: int = FREEZE_SEED,
) -> dict[str, Any]:
    return {
        "pack_id": PACK_ID,
        "pack_version": PACK_VERSION,
        "generator_version": GENERATOR_VERSION,
        "freeze_seed": int(seed),
        "count": len(scripts),
        "themes": list(THEMES),
        "script_ids": [script.script_id for script in scripts],
        "script_seeds": {script.script_id: script.seed for script in scripts},
        "digest": matrix_digest(scripts),
        "does_not_prove": list(DOES_NOT_PROVE),
        "scripts": [script.as_dict() for script in scripts],
    }


def write_frozen_manifest(
    out_path: str | Path,
    *,
    seed: int = FREEZE_SEED,
) -> Path:
    """Write freeze manifest JSON; returns the path written."""

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scripts = generate_frozen_pack(seed=seed)
    manifest = build_manifest(scripts, seed=seed)
    path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_frozen_manifest(path: str | Path) -> tuple[dict[str, Any], tuple[ScriptSpec, ...]]:
    """Load a frozen manifest; validates digest against script payloads."""

    root = Path(path)
    raw = json.loads(root.read_text(encoding="utf-8"))
    scripts = tuple(ScriptSpec.from_mapping(item) for item in raw["scripts"])
    digest = matrix_digest(scripts)
    if digest != str(raw.get("digest") or ""):
        raise ValueError(
            f"manifest digest mismatch: recorded={raw.get('digest')!r} computed={digest!r}"
        )
    if int(raw.get("count", -1)) != len(scripts):
        raise ValueError("manifest count does not match scripts")
    if not raw.get("does_not_prove"):
        raise ValueError("manifest must carry a non-empty does_not_prove list")
    return raw, scripts


def default_freeze_path() -> Path:
    return Path(__file__).resolve().parent / "freeze" / "manifest.json"


def _follow(seed: int) -> ScriptSpec:
    return ScriptSpec(
        script_id="wwm-follow-behind",
        theme="follow",
        instruction="follow behind me",
        seed=seed,
        start_pose=(0.0, 0.0, 1.5708),
        goal=GoalRegion(kind="disc", center=(2.0, -0.5), radius_m=2.0),
        harness="spatial",
        events=(),
        success_predicate="follow_band_hold",
        duration_s=20.0,
        absent_target=False,
        notes="Owner-relative follow; formation band scored when headless spatial is available.",
        placement_overrides={"owner": {"x": 2.0, "y": -0.5}},
    )


def _wait(seed: int) -> ScriptSpec:
    return ScriptSpec(
        script_id="wwm-wait-hold",
        theme="wait",
        instruction="wait here",
        seed=seed,
        start_pose=(1.0, 0.5, 0.0),
        goal=GoalRegion(kind="disc", center=(1.0, 0.5), radius_m=0.6),
        harness="behavior_stub",
        events=(),
        success_predicate="hold_stopped",
        duration_s=8.0,
        absent_target=False,
        notes="Stay/wait hold: agent-issued stop inside start disc.",
        placement_overrides={},
    )


def _orbit(seed: int) -> ScriptSpec:
    return ScriptSpec(
        script_id="wwm-orbit-once",
        theme="orbit",
        instruction="circle me once",
        seed=seed,
        start_pose=(0.0, 0.0, 0.0),
        goal=GoalRegion(kind="disc", center=(2.0, -0.5), radius_m=2.5),
        harness="spatial",
        events=(),
        success_predicate="orbit_once",
        duration_s=25.0,
        absent_target=False,
        notes="Orbit/circle owner once; swept-revolution predicate when spatial harness runs.",
        placement_overrides={"owner": {"x": 2.0, "y": -0.5}},
    )


def _sidewalk(seed: int) -> ScriptSpec:
    goal = region_inside_goal_region(_SIDEWALK_POLYGON, entity_id="sidewalk")
    return ScriptSpec(
        script_id="wwm-sidewalk-from-road",
        theme="sidewalk",
        instruction="go to the sidewalk",
        seed=seed,
        start_pose=(0.0, 0.0, 1.5708),
        goal=goal,
        harness="navigation",
        events=(),
        success_predicate="inside_goal_stopped",
        duration_s=30.0,
        absent_target=False,
        notes="Road→sidewalk vertical slice; GoalRegion polygon authority (K0).",
        placement_overrides={},
    )


def _lamppost(seed: int) -> ScriptSpec:
    goal = arrival_goal_region_for_relation(
        "next_to",
        center=_LAMPPOST["position"],
        object_radius_m=float(_LAMPPOST["radius_m"]),
        entity_id="lamp_post_1",
        label=str(_LAMPPOST["label"]),
    )
    return ScriptSpec(
        script_id="wwm-lamppost-standoff",
        theme="lamppost",
        instruction="wait by the lamppost",
        seed=seed,
        start_pose=(0.0, 0.0, 1.5708),
        goal=goal,
        harness="navigation",
        events=(),
        success_predicate="inside_goal_stopped",
        duration_s=30.0,
        absent_target=False,
        notes="Lamppost stand-off via next_to GoalRegion (full footprint; K0).",
        placement_overrides={},
    )


def _pause_resume(seed: int) -> ScriptSpec:
    return ScriptSpec(
        script_id="wwm-pause-resume",
        theme="pause_resume",
        instruction="follow me",
        seed=seed,
        start_pose=(0.0, 0.0, 1.5708),
        goal=GoalRegion(kind="disc", center=(2.0, -0.5), radius_m=2.0),
        harness="resume",
        events=(
            ScriptEvent(kind="pause", at_s=3.0, payload={"reason": "summons"}),
            ScriptEvent(
                kind="resume",
                at_s=5.0,
                payload={"requires_fresh_observation": True},
            ),
        ),
        success_predicate="resume_fresh_observation",
        duration_s=12.0,
        absent_target=False,
        notes="Summons-suspend-resume: ResumeStore must require fresh observation.",
        placement_overrides={"owner": {"x": 2.0, "y": -0.5}},
    )


def _barge_in(seed: int) -> ScriptSpec:
    return ScriptSpec(
        script_id="wwm-barge-in-tts",
        theme="barge_in",
        instruction="follow me",
        seed=seed,
        start_pose=(0.0, 0.0, 0.0),
        goal=None,
        harness="behavior_stub",
        events=(
            ScriptEvent(
                kind="barge_in",
                at_s=2.0,
                payload={"tts_active": True, "motion_intent": False},
            ),
        ),
        success_predicate="barge_in_tts_only",
        duration_s=6.0,
        absent_target=False,
        notes="Barge-in without motion intent: TTS interrupted, base command unchanged.",
        placement_overrides={},
    )


def _absent_target(seed: int) -> ScriptSpec:
    # Off-map disc — agent must refuse / honest-not-found, not invent a goal.
    goal = GoalRegion(kind="disc", center=(40.0, 40.0), radius_m=0.5)
    return ScriptSpec(
        script_id="wwm-absent-target",
        theme="absent_target",
        instruction="walk towards the purple hydrant",
        seed=seed,
        start_pose=(0.0, 0.0, 1.5708),
        goal=goal,
        harness="navigation",
        events=(),
        success_predicate="honest_absent",
        duration_s=10.0,
        absent_target=True,
        notes="Absent-target honesty: refusal / not-found without hallucinated arrival.",
        placement_overrides={
            "absent_target": True,
            "remove_entities": ["purple_hydrant"],
        },
    )


def _owner_search(seed: int) -> ScriptSpec:
    return ScriptSpec(
        script_id="wwm-owner-search",
        theme="owner_search",
        instruction="find me",
        seed=seed,
        start_pose=(0.0, 0.0, 0.0),
        goal=GoalRegion(kind="disc", center=(4.0, 2.0), radius_m=2.0),
        harness="behavior_stub",
        events=(
            ScriptEvent(kind="lose_owner", at_s=1.0, payload={"timeout_s": 2.0}),
        ),
        success_predicate="bounded_search_or_stop",
        duration_s=15.0,
        absent_target=False,
        notes="Lost-owner → bounded search/stop; never attach to nearest person.",
        placement_overrides={"owner_path": "corner_occlusion"},
    )


def _curb_stop(seed: int) -> ScriptSpec:
    return ScriptSpec(
        script_id="wwm-curb-stop",
        theme="curb_stop",
        instruction="cross with me",
        seed=seed,
        start_pose=(2.5, 1.0, -1.5708),
        goal=None,
        harness="behavior_stub",
        events=(
            ScriptEvent(
                kind="curb_edge",
                at_s=2.0,
                payload={"require_voice_initiation": True},
            ),
        ),
        success_predicate="curb_stop_hold",
        duration_s=10.0,
        absent_target=False,
        notes="Curb-stop companion moment stub: stop at edge until voice initiation.",
        placement_overrides={},
    )
