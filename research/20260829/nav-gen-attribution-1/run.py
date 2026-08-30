"""NAV-GEN-1 — run the shipped navigator across the clearance sweep.

Pre-registration: ``DESIGN.md`` (FROZEN).  Reproduce with

    env -u TMPDIR OPENBLAS_NUM_THREADS=32 .parcel/bin/python \
      research/20260829/nav-gen-attribution-1/run.py --all --seed 20260829

THE ARMS AND THE EXACT CONFIG KEY
---------------------------------
The one clearance knob the config store exposes on the shipped profile is
``configs/navigation/models/grid.yaml`` ``controller.map_safety_margin_m``
(0.10 m commissioned).  The planner's HARD, non-traversable inflation is

    GridPlannerConfig.inflation_radius_m
      = max(robot_radius_m + effective_hard_margin_m, gate_lateral_clearance_m)

and on this profile ``map_gate_clearance_m`` is unset, so
``_planner_coupling_ring_m(None, hard_margin_m=m)`` returns the ring whose
lateral demand the footprint term already covers and the max collapses to

    inflation = SafetyEnvelope.footprint_radius_m (0.32) + map_safety_margin_m

**The DESIGN's "down to 0.20 m" is unreachable through the config store, and
this is recorded rather than worked around.**  ``ClearanceProfile`` refuses a
negative margin ("planner_hard_margin_m must be non-negative"), and the 0.32 m
footprint disc is a code constant (``authority.DEFAULT_SAFETY_ENVELOPE``), not
a config key, so 0.32 m is the architectural FLOOR of this quantity.  Reaching
0.20 m would require editing ``src/``, which this probe may not do.  The
closest faithful thing is run: the sweep spans the commissioned 0.42 m down to
the 0.32 m floor in four steps.

No arm touches the reactive-safety stop/slow bands: ``configs/robot.yaml``
``safety.obstacle_stop_m`` 0.65 / ``obstacle_slow_m`` 1.2 are read by the
harness from the untouched repo config in every arm and asserted per run.

NOTHING UNDER ``src/``, ``evals/``, ``configs/`` OR ANY OTHER RESEARCH FOLDER
IS WRITTEN.  Each arm gets its own navigation config TREE under
``~/.cache/parcel-0e/ng1/navcfg/<arm>/`` (a copy of
``configs/navigation/default.yaml`` with absolute ``models_root`` / ``pois_path``
plus a copy of ``configs/navigation/models/`` whose ``grid.yaml`` carries that
arm's margin), and the harness is pointed at it by assigning
``harness.navigation_config``.

Evidence tier: ``desktop-sim``.  CPU only, no GPU, no sockets, no hosted call.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# HOST DISCIPLINE. ``OPENBLAS_NUM_THREADS=32`` is this session's cap for the
# PARENT; every worker is pinned to ONE BLAS thread here (an override, not a
# setdefault, because spawn children inherit the parent's environment), so N
# workers cost N threads and stay under the 48-thread ceiling. The parent does
# no BLAS work of its own.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import episodes as EP

REPO = EP.REPO
SCRATCH = EP.SCRATCH
NAVCFG = SCRATCH / "navcfg"
RAW = SCRATCH / "raw"

COMMISSIONED_MARGIN_M = 0.10
FOOTPRINT_RADIUS_M = 0.32          # authority.DEFAULT_SAFETY_ENVELOPE
MAX_STEPS = 1800                   # HeadlessCityQualityHarness.run default
#: MA-1's per-goal frame budget, used only to reconcile with its 4.5 % row.
MA1_FRAME_BUDGET = 420


COMMISSIONED_STOP_DISTANCE_M = 0.80   # configs/navigation/default.yaml safety


@dataclass(frozen=True)
class Arm:
    name: str
    margin_m: float = COMMISSIONED_MARGIN_M
    stop_distance_m: float = COMMISSIONED_STOP_DISTANCE_M
    sweep: str = "A"
    commissioned: bool = False
    blocks: tuple = ("generated", "frozen")
    note: str = ""

    @property
    def footprint_term_m(self) -> float:
        return round(FOOTPRINT_RADIUS_M + self.margin_m, 4)

    @property
    def inflation_m(self) -> float:
        """The inflation the LIVE planner resolves to, not the config's own sum.

        ``DirectiveNavigator._create_navigator`` commissions the grid planner
        with ``map_gate_clearance_m = safety.stop_distance_m``, so the max in
        ``GridPlannerConfig.inflation_radius_m`` is taken against the GATE term,
        not the footprint term. This property reproduces that computation.
        """

        from parcel_robot.navigation.grid_navigator import _planner_coupling_ring_m
        from parcel_robot.navigation.grid_planner import GridPlannerConfig

        ring = _planner_coupling_ring_m(self.stop_distance_m, hard_margin_m=self.margin_m)
        cfg = GridPlannerConfig(resolution_m=0.10, grid_size_cells=161,
                                safety_margin_m=self.margin_m, gate_clearance_m=ring)
        return round(cfg.inflation_radius_m, 4)


#: Sweep A — the key the DESIGN names, ``map_safety_margin_m``.
#: Sweep B — the key that actually MOVES the live planner's inflation,
#: ``configs/navigation/default.yaml`` ``safety.stop_distance_m``, which
#: ``DirectiveNavigator`` passes to the planner as its commissioned gate ring.
#: B arms run the generated block only (H-NG1b's "the same episodes").
ARMS: tuple[Arm, ...] = (
    Arm("A0", commissioned=True, note="commissioned config, repo path, untouched"),
    Arm("A0c", note="plumbing control: scratch config tree at the commissioned value"),
    Arm("A1", margin_m=0.07),
    Arm("A2", margin_m=0.05),
    Arm("A3", margin_m=0.02),
    Arm("A4", margin_m=0.00, note="floor of the footprint term"),
    Arm("B1", stop_distance_m=0.65, sweep="B", blocks=("generated",)),
    Arm("B2", stop_distance_m=0.50, sweep="B", blocks=("generated",)),
    Arm("B3", stop_distance_m=0.40, sweep="B", blocks=("generated",)),
    Arm("B4", stop_distance_m=0.32, sweep="B", blocks=("generated",),
        note="floor: ClearanceProfile refuses a ring inside the 0.32 m body hull"),
)
ARM_BY_NAME = {a.name: a for a in ARMS}

# ===========================================================================
# Reason classification (H-NG1a).  Product spellings, collected from
# navigation/pipeline.py and confirmed against the observed histogram.
# ===========================================================================

GROUNDING_REASONS = frozenset({
    "directive_not_understood", "semantic_target_not_found", "not_found",
    "semantic_search_exhausted", "place_not_found",
})
TERMINATION_CLEARANCE_REASONS = frozenset({
    "semantic_target_unreachable", "goal_blocked", "unroutable",
    "semantic_arrival_verification_failed", "verification_failed",
    "blocked_route_gate", "semantic_replan_after_unroutable_goal",
    "semantic_replan_after_unreachable_pose",
})

#: WRONG INSTANCE is decided against the SCENE, not against a name pattern:
#: the legal ids for a target class are exactly the ids of the scene entities
#: carrying that label (``episodes.instances``).  This is what catches
#: ``configs/navigation/cities/demo_pois.yaml``'s hardcoded ``crosswalk_a`` at
#: (3.5, -0.6): it is a POI-table id, present in no generated scene, so a
#: mission that "arrives" there grounded to a lookup table rather than to the
#: world in front of it.


def classify(row: dict) -> str:
    reason = str(row.get("reason") or "")
    if row.get("wrong_instance") or reason in GROUNDING_REASONS:
        return "grounding"
    if reason in TERMINATION_CLEARANCE_REASONS:
        return "termination_clearance"
    if row.get("false_arrival"):
        return "false_arrival"
    return "other"


# ===========================================================================
# Per-arm navigation config trees
# ===========================================================================


def build_arm_config(arm: Arm) -> Path:
    """Return the navigation config path this arm runs on."""

    repo_default = REPO / "configs" / "navigation" / "default.yaml"
    if arm.commissioned:
        return repo_default                      # A0: the shipped file itself
    root = NAVCFG / arm.name
    models = root / "models"
    if models.exists():
        shutil.rmtree(models)
    models.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO / "configs" / "navigation" / "models", models)
    grid = models / "grid.yaml"
    text = grid.read_text(encoding="utf-8")
    old = f"  map_safety_margin_m: {COMMISSIONED_MARGIN_M:.2f}"
    if old not in text:
        raise RuntimeError(f"grid.yaml no longer carries {old!r}")
    text = text.replace(old, f"  map_safety_margin_m: {arm.margin_m:.2f}", 1)
    grid.write_text(text, encoding="utf-8")
    default_text = repo_default.read_text(encoding="utf-8")
    old_stop = f"  stop_distance_m: {COMMISSIONED_STOP_DISTANCE_M:.1f}"
    if old_stop not in default_text:
        raise RuntimeError(f"default.yaml no longer carries {old_stop!r}")
    default_text = default_text.replace(
        old_stop, f"  stop_distance_m: {arm.stop_distance_m:.2f}", 1)
    default_text = default_text.replace(
        "models_root: configs/navigation/models", f"models_root: {models}", 1)
    default_text = default_text.replace(
        "pois_path: configs/navigation/cities/demo_pois.yaml",
        f"pois_path: {REPO / 'configs/navigation/cities/demo_pois.yaml'}", 1)
    out = root / "default.yaml"
    out.write_text(default_text, encoding="utf-8")
    return out


def planner_facts(config_path: Path) -> dict:
    """Read back what the planner will ACTUALLY inflate by, from the config."""

    import yaml

    from parcel_robot.navigation.grid_navigator import _planner_coupling_ring_m
    from parcel_robot.navigation.grid_planner import GridPlannerConfig

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    models_root = Path(str(data.get("models_root")))
    if not models_root.is_absolute():
        models_root = (REPO / models_root).resolve()
    model = yaml.safe_load((models_root / "grid.yaml").read_text(encoding="utf-8"))
    controller = model["controller"]
    margin = float(controller["map_safety_margin_m"])
    ring = _planner_coupling_ring_m(controller.get("map_gate_clearance_m"),
                                    hard_margin_m=margin)
    cfg = GridPlannerConfig(
        resolution_m=float(controller["grid_resolution_m"]),
        grid_size_cells=int(controller["grid_size_cells"]),
        safety_margin_m=margin, gate_clearance_m=ring,
    )
    # The LIVE path: DirectiveNavigator._create_navigator commissions the grid
    # planner with map_gate_clearance_m = safety.stop_distance_m, so the config
    # file's own controller value (unset here) is NOT what the planner gets.
    stop_distance = float((data.get("safety") or {}).get("stop_distance_m", -1))
    live_ring = _planner_coupling_ring_m(stop_distance, hard_margin_m=margin)
    live = GridPlannerConfig(
        resolution_m=float(controller["grid_resolution_m"]),
        grid_size_cells=int(controller["grid_size_cells"]),
        safety_margin_m=margin, gate_clearance_m=live_ring)
    return {
        "config_path": str(config_path),
        "grid_model": str(models_root / "grid.yaml"),
        "active_model": data.get("active_model"),
        "map_safety_margin_m": margin,
        "map_gate_clearance_m_in_model_file": controller.get("map_gate_clearance_m"),
        "footprint_term_m": round(cfg.robot_radius_m + margin, 6),
        "robot_radius_m": round(cfg.robot_radius_m, 6),
        "config_only_inflation_radius_m": round(cfg.inflation_radius_m, 6),
        "nav_safety_stop_distance_m": stop_distance,
        "live_planner_gate_ring_m": round(live_ring, 6),
        "live_planner_gate_lateral_m": round(live.gate_lateral_clearance_m, 6),
        "LIVE_planner_inflation_radius_m": round(live.inflation_radius_m, 6),
        "live_narrowest_routable_corridor_m": round(2 * live.inflation_radius_m, 6),
    }


# ===========================================================================
# One work unit: (arm, block, scene_seed) -> every episode on that world
# ===========================================================================


def _path_length(path) -> float:
    return round(sum(math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
                     for i in range(len(path) - 1)), 4)


def run_unit(args) -> dict:
    arm_name, block, scene_seed, config_path, only_target = args
    import numpy as np

    from parcel_robot.simulation.headless_city import HeadlessCityQualityHarness

    t0 = time.time()
    world = EP.world_for(block, scene_seed)
    harness = HeadlessCityQualityHarness(world)
    # The ONLY override: which navigation config tree the navigator is built
    # from. reactive_safety / spatial_config stay as robot.yaml commissioned
    # them and are asserted below.
    harness.navigation_config = Path(config_path)
    stop_band = float(harness.reactive_safety.obstacle_stop_m)
    slow_band = float(harness.reactive_safety.obstacle_slow_m)
    assert abs(stop_band - 0.65) < 1e-9 and abs(slow_band - 1.2) < 1e-9, (
        f"reactive-safety bands moved: {stop_band}/{slow_band}")

    geos = {t: EP.goal_geometry(world, t) for t in EP.TARGETS}
    insts = {t: EP.instances(world, t) for t in EP.TARGETS}
    legal_ids = {t: [i for i, _g in insts[t]] for t in EP.TARGETS}
    scene_facts = {
        "block": block, "scene_seed": scene_seed,
        "empirical": EP.empirical_density(world),
        "goals": {t: (EP.goal_clearance_stats(world, g) if g else None)
                  for t, g in geos.items()},
    }

    eps = [e for e in (EP.generated_episodes() if block == "generated"
                       else EP.control_episodes())
           if e.scene_seed == scene_seed and e.block == block
           and (only_target is None or e.target == only_target)]
    rows = []
    for ep in eps:
        geo = geos[ep.target]
        start = EP.start_pose(world, ep)
        world._scan_rng = np.random.default_rng(7)   # order-independence (no-op:
        # the headless world requests a zero-noise scan, so the stream is never
        # drawn from; reseeding makes that independence provable rather than
        # assumed).
        world.reset(robot=start)
        r = harness.run(ep.directive, max_steps=MAX_STEPS)
        rb = r.final_observation.robot
        fx, fy = float(rb.x), float(rb.y)
        path = list(r.path)
        inside_strict = bool(EP.T.inside_goal_band(world, ep.target, fx, fy))
        dtg = geo.distance_to_band(fx, fy) if geo else None
        first_entry = -1
        for i, (px, py) in enumerate(path):
            if EP.T.inside_goal_band(world, ep.target, px, py):
                first_entry = i
                break
        tid = r.target_id or ""
        legal = legal_ids[ep.target]
        wrong_instance = bool(tid) and tid not in legal
        inst = insts[ep.target]
        inside_any = EP.inside_any_instance(inst, fx, fy)
        dtg_any = min((g.distance_to_band(fx, fy) for _i, g in inst), default=None)
        entry_any = any(EP.inside_any_instance(inst, px, py) for px, py in path)
        row = {
            "arm": arm_name, "episode_id": ep.episode_id, "block": block,
            "scene_seed": scene_seed, "target": ep.target, "pose_index": ep.pose_index,
            "start": [round(v, 6) for v in start],
            "status": r.status, "reason": r.reason,
            "terminal_relation": r.terminal_relation, "target_id": r.target_id,
            "wrong_instance": wrong_instance,
            "resolved_in_scene": bool(tid) and tid in legal,
            "legal_instance_ids": legal,
            "nav_claimed_success": bool(r.succeeded),
            "terminal_stopped": bool(r.stopped),
            "terminal_xy": [round(fx, 4), round(fy, 4)],
            "dtg_m": None if dtg is None else round(float(dtg), 4),
            "inside_strict_band": inside_strict,
            "inside_any_instance_band": inside_any,
            "band_entry_any_instance": entry_any,
            "dtg_any_instance_m": None if dtg_any is None else round(float(dtg_any), 4),
            "inside_2x_band": bool(geo.inside_two_x_band(fx, fy)) if geo else False,
            "band_entry": first_entry >= 0,
            "first_band_entry_step": first_entry,
            "band_entry_within_ma1_budget": 0 <= first_entry <= MA1_FRAME_BUDGET,
            "minimum_clearance_m": (None if not math.isfinite(r.minimum_clearance_m)
                                    else round(float(r.minimum_clearance_m), 4)),
            "required_obstacle_clearance_m": round(float(r.required_obstacle_clearance_m), 4),
            "collision_count": int(r.collision_count),
            "steps": len(path),
            "path_length_m": _path_length(path),
            "semantic_scan_steps": int(r.semantic_scan_steps),
            "goal_band_clearance_max_m": (scene_facts["goals"][ep.target] or {}).get(
                "band_clearance_max_m"),
            "goal_nearest_obstacle_m": (scene_facts["goals"][ep.target] or {}).get(
                "goal_nearest_obstacle_m"),
        }
        # Strict success: the truth region predicate, not the navigator's
        # claim — inside the goal band with the body stopped ON THIS FRAME.
        # NOT MA-1's `arrived`, which also requires ORACLE_SETTLE_FRAMES = 5
        # frames of stillness (closed_loop_core.py:256-267); the harness's
        # run() returns at the stop, so no settle window is observable here.
        # See RESULTS.md 7.3a.
        row["strict_success"] = bool(inside_strict and row["terminal_stopped"])
        # Card C2 (ARRIVAL-SETTLE-1) — the ONLY change to this file. The
        # harness now keeps OBSERVING for `DEFAULT_SETTLE_FRAMES` after the
        # terminal frame, so MA-1's gold predicate ("inside the band with the
        # body still for 5 frames") is finally observable here; the terminal
        # frame itself is snapshotted BEFORE that window, so `strict_success`
        # above and every column beside it are the numbers they always were.
        # `settled_success` is the like-for-like partner: same truth band, the
        # settle instead of the one frame. `goal_source` closes VERDICT §5.2's
        # caveat that "raw rows do not log goal_source".
        row["settled"] = bool(r.settled)
        row["settle_frames_observed"] = int(r.settle_frames_observed)
        row["inside_arrival_region"] = r.inside_arrival_region
        row["arrived_verified"] = bool(r.arrived_verified)
        row["goal_source"] = r.goal_source
        row["poi_refused"] = r.poi_refused
        row["arrival_not_verified_reason"] = r.arrival_not_verified_reason
        row["settled_success"] = bool(inside_strict and r.settled)
        # The fairer oracle: ANY scene entity carrying the requested label.
        row["strict_success_any_instance"] = bool(inside_any and row["terminal_stopped"])
        # A mission that declared success while the body is in no instance's
        # band at all.
        row["false_arrival"] = bool(r.succeeded and not inside_any)
        row["class"] = classify(row)
        rows.append(row)
    return {"arm": arm_name, "block": block, "scene_seed": scene_seed,
            "only_target": only_target, "rows": rows, "scene_facts": scene_facts,
            "wall_s": round(time.time() - t0, 2)}


def host_snapshot() -> dict:
    try:
        load = os.getloadavg()
    except OSError:
        load = None
    gpu = ""
    try:
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=20, check=False).stdout.strip()
    except Exception:  # noqa: BLE001
        gpu = "unavailable"
    return {"loadavg": load, "cpus": os.cpu_count(), "gpu": gpu,
            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def arm_units(arm: Arm, config_path: Path, blocks=None) -> list:
    """One unit per (arm, world) — the frozen block is split per target so no
    single unit becomes the long pole of the pool."""

    blocks = blocks if blocks is not None else arm.blocks
    units = []
    if "generated" in blocks:
        units += [(arm.name, "generated", s, str(config_path), None) for s in EP.SCENE_SEEDS]
    if "frozen" in blocks:
        units += [(arm.name, "frozen", EP.CONTROL_SCENE_KEY, str(config_path), t)
                  for t in EP.TARGETS]
    return units


def run_units(units: list, workers: int, label: str = "") -> dict:
    """Run every unit in ONE pool and group the rows by arm."""

    import multiprocessing as mp

    by_arm: dict = {}
    t0 = time.time()
    done = 0
    with mp.get_context("spawn").Pool(workers) as pool:
        for res in pool.imap_unordered(run_unit, units, chunksize=1):
            slot = by_arm.setdefault(res["arm"], {"rows": [], "scene_facts": []})
            slot["rows"].extend(res["rows"])
            if res["only_target"] in (None, EP.TARGETS[0]):
                slot["scene_facts"].append(res["scene_facts"])
            done += 1
            if done % 25 == 0:
                print(f"  [{label}] {done}/{len(units)} units {time.time()-t0:.0f}s",
                      flush=True)
    for arm_name, slot in by_arm.items():
        slot["rows"].sort(key=lambda r: (r["block"], r["scene_seed"], r["target"],
                                         r["pose_index"]))
        slot["arm"] = arm_name
        slot["wall_s"] = round(time.time() - t0, 1)
    return by_arm


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seed", type=int, default=20260829)
    ap.add_argument("--arms", default="")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--determinism", action="store_true",
                    help="re-run A0 and prove the two runs are byte-identical")
    ap.add_argument("--sweep", default="all", choices=("all", "A", "B"))
    ap.add_argument("--stage", default="run", choices=("run", "prepare", "facts"))
    a = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    NAVCFG.mkdir(parents=True, exist_ok=True)
    host_start = host_snapshot()
    print(json.dumps({"host_start": host_start}), flush=True)

    if a.stage == "prepare":
        man = EP.scene_manifest()
        params = {str(s): EP.scene_params(s) for s in EP.SCENE_SEEDS}
        (RAW / "scenes.json").write_text(json.dumps(
            {"manifest": man, "params": params, "episodes": EP.summary()}, indent=2))
        print(json.dumps({"scenes": man["n"], "manifest_sha256": man["manifest_sha256"]}))
        return

    arms = ([ARM_BY_NAME[n] for n in a.arms.split(",")] if a.arms
            else [x for x in ARMS if a.sweep in ("all", x.sweep)])
    cfgs = {arm.name: build_arm_config(arm) for arm in arms}
    facts = {arm.name: planner_facts(cfgs[arm.name]) for arm in arms}
    (RAW / "arm_config_facts.json").write_text(json.dumps(facts, indent=2))
    print(json.dumps(facts, indent=2), flush=True)

    if a.stage == "facts":
        return

    # RUN PROVENANCE.  ``--workers`` was quoted three different ways in the
    # first RESULTS.md (24 / 32 / 40) because no artifact carried it; it is
    # recorded here so ``analyze.py`` can render it instead of a reader typing
    # one in.  ``blas_threads_per_worker`` is the environment the run was
    # launched with, not a request.
    index = {
        "seed": a.seed,
        "host_start": host_start,
        "arms": {},
        "arm_config_facts": facts,
        "run_provenance": {
            "workers": a.workers,
            "blas_threads_per_worker": os.environ.get("OPENBLAS_NUM_THREADS"),
            "cpus": host_start.get("cpus"),
            "argv": list(sys.argv[1:]),
        },
    }
    units = []
    for arm in arms:
        units += arm_units(arm, cfgs[arm.name])
    by_arm = run_units(units, a.workers, label="arms")
    for arm in arms:
        res = by_arm[arm.name]
        out = RAW / f"rows_{arm.name}.json"
        out.write_text(json.dumps(res))
        n_ok = sum(1 for r in res["rows"] if r["strict_success"])
        index["arms"][arm.name] = {"episodes": len(res["rows"]), "wall_s": res["wall_s"],
                                   "strict_success": n_ok, "file": out.name}
        print(json.dumps({"arm": arm.name, "episodes": len(res["rows"]),
                          "strict_success": n_ok, "wall_s": res["wall_s"]}), flush=True)

    if a.determinism:
        a0 = ARM_BY_NAME["A0"]
        rep = run_units(arm_units(a0, cfgs.get("A0") or build_arm_config(a0)),
                        a.workers, label="A0-repeat")["A0"]
        (RAW / "rows_A0_repeat.json").write_text(json.dumps(rep))
        first = json.loads((RAW / "rows_A0.json").read_text())["rows"]
        identical = json.dumps(first, sort_keys=True) == json.dumps(rep["rows"], sort_keys=True)
        index["determinism"] = {"a0_repeat_identical": identical,
                                "episodes": len(rep["rows"])}
        print(json.dumps({"a0_repeat_identical": identical}), flush=True)

    index["host_end"] = host_snapshot()
    (RAW / "index.json").write_text(json.dumps(index, indent=2))
    print(json.dumps({"host_end": index["host_end"]}), flush=True)


if __name__ == "__main__":
    main()
