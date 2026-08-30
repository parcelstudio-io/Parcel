"""VALUE-CHANGES-MEASURED-1 (card W6) — the four arms, harness-only.

Pre-registration: ``DESIGN.md`` (FROZEN 2026-08-30 06:43 EDT).  RESEARCH ONLY:
no product edit, no config edit, no git write, no hosted call.

Two value changes, fully crossed:

    V1  progress_watchdog.held_stall_release   False (shipped)  ->  True
    V2  GridPlannerConfig.inflation_radius_m   1.0223 (shipped) ->  1.12

Both are injected as HARNESS overrides: each arm gets its own navigation config
TREE under ``$NG1_SCRATCH/navcfg/<arm>/`` and the harness is pointed at it.  The
repo's ``configs/**`` is a read-only input.  See DESIGN.md sec. 3 for why
``map_hard_safety_margin_m`` is an exact-value injection of V2 and not a proxy.

Stages::

    --stage facts    build every arm tree and read the LIVE navigator/planner
    --stage ng1      NAV-GEN-1 A0, 530 episodes x 5 arms, ONE pool
    --stage frozen   one arm's v4 minival + mutation panel (run per arm, own process)

Evidence tier: ``desktop-sim``.  CPU only.  Physical motion: NO-GO.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Host discipline, identical to NG1's: the parent does no BLAS work and every
# child is pinned to one thread, so --workers N costs N threads.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

HERE = Path(__file__).resolve().parent
SCRATCH = Path(os.environ.get("W6_SCRATCH", Path.home() / ".cache/parcel-0e/w6"))
NG1_SCRATCH = Path(os.environ.get("NG1_SCRATCH", SCRATCH / "ng1"))
os.environ.setdefault("NG1_SCRATCH", str(NG1_SCRATCH))
os.environ.setdefault("PARCEL_MEMORY_PATH", str(SCRATCH / "scratch_memory.sqlite3"))

#: The frozen v4 minival report digest this tree must reproduce with both values
#: OFF (C3 STATUS sec. F1.2, AUDIT_C3 sec. 5).
HEAD_MINIVAL_DIGEST = "021b67ab73c4e7be647aba1a17e20a193ebf23b826a18d5b0990e296e5708496"
#: The five report-level fields a cross-run comparison drops
#: (tests/test_nav_instruct_digest_recipe.py).
REPORT_EXCLUSIONS = frozenset(
    {"report_id", "elapsed_s", "scene", "navigator_flags", "refreeze_provenance"}
)

COMMISSIONED_MARGIN_M = 0.10
FOOTPRINT_RADIUS_M = 0.32          # authority.DEFAULT_SAFETY_ENVELOPE
FULL_GATE_RING_M = 1.12            # ClearanceProfile.gate_range_ring_m at the shipped brake
#: hard margin that makes 0.32 + m == 1.12 exactly.
FULL_HARD_MARGIN_M = round(FULL_GATE_RING_M - FOOTPRINT_RADIUS_M, 10)


@dataclass(frozen=True)
class Arm:
    name: str
    door: bool          # V1: progress_watchdog.held_stall_release
    full: bool          # V2: planner inflation 1.12 instead of 1.0223
    commissioned: bool = False   # the repo config path itself, no scratch tree


ARMS: tuple[Arm, ...] = (
    Arm("A0ref", door=False, full=False, commissioned=True),
    Arm("off_disc", door=False, full=False),
    Arm("on_disc", door=True, full=False),
    Arm("off_full", door=False, full=True),
    Arm("on_full", door=True, full=True),
)
ARM_BY_NAME = {a.name: a for a in ARMS}


def repo_root() -> Path:
    """The worktree this harness measures — derived from the config it reads."""

    env = os.environ.get("W6_REPO")
    if env:
        return Path(env).resolve()
    return HERE.resolve().parents[2]


# ---------------------------------------------------------------------------
# The per-arm navigation config tree — the ONLY override
# ---------------------------------------------------------------------------


def build_arm_config(arm: Arm) -> Path:
    repo = repo_root()
    repo_default = repo / "configs" / "navigation" / "default.yaml"
    if arm.commissioned:
        return repo_default
    root = NG1_SCRATCH / "navcfg" / arm.name
    models = root / "models"
    if models.exists():
        shutil.rmtree(models)
    models.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo / "configs" / "navigation" / "models", models)

    grid = models / "grid.yaml"
    text = grid.read_text(encoding="utf-8")
    anchor = f"  map_safety_margin_m: {COMMISSIONED_MARGIN_M:.2f}"
    if anchor not in text:
        raise RuntimeError(f"grid.yaml no longer carries {anchor!r}")
    if arm.full:
        text = text.replace(
            anchor,
            f"{anchor}\n  map_hard_safety_margin_m: {FULL_HARD_MARGIN_M:.2f}",
            1,
        )
    grid.write_text(text, encoding="utf-8")

    default_text = repo_default.read_text(encoding="utf-8")
    watchdog = "progress_watchdog:\n  timeout_steps: 200"
    if watchdog not in default_text:
        raise RuntimeError("default.yaml no longer carries the progress_watchdog block")
    if arm.door:
        default_text = default_text.replace(
            watchdog, "progress_watchdog:\n  held_stall_release: true\n  timeout_steps: 200", 1
        )
    default_text = default_text.replace(
        "models_root: configs/navigation/models", f"models_root: {models}", 1
    )
    default_text = default_text.replace(
        "pois_path: configs/navigation/cities/demo_pois.yaml",
        f"pois_path: {repo / 'configs/navigation/cities/demo_pois.yaml'}",
        1,
    )
    # Nothing else moves: safety.stop_distance_m stays 0.80 in every arm.
    if "  stop_distance_m: 0.8\n" not in default_text:
        raise RuntimeError("default.yaml no longer carries stop_distance_m: 0.8")
    out = root / "default.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(default_text, encoding="utf-8")
    return out


def live_facts(config_path: Path) -> dict:
    """Read the two values off a REAL navigator built from this arm's tree.

    A silent patch/injection failure would otherwise report the baseline N times,
    so this is asserted in every process before the first episode.
    """

    from parcel_robot.navigation.pipeline import DirectiveNavigator

    nav = DirectiveNavigator.from_config(config_path)
    planner_cfg = nav._navigator._planner.config
    facts = {
        "config_path": str(config_path),
        "held_stall_release": bool(nav.held_stall_release),
        "planner_inflation_radius_m": round(float(planner_cfg.inflation_radius_m), 6),
        "planner_gate_clearance_m": round(float(planner_cfg.gate_clearance_m), 6),
        "planner_gate_lateral_clearance_m": round(
            float(planner_cfg.gate_lateral_clearance_m), 6
        ),
        "planner_effective_hard_margin_m": round(
            float(planner_cfg.effective_hard_margin_m), 6
        ),
        "planner_comfort_radius_m": round(float(planner_cfg.comfort_radius_m), 6),
        "planner_comfort_cost_enabled": bool(planner_cfg.comfort_cost_enabled),
        "navigator_brake_obstacle_stop_m": round(float(nav.collision.obstacle_stop_m), 6),
        "narrowest_routable_corridor_m": round(
            2 * float(planner_cfg.inflation_radius_m), 6
        ),
    }
    nav.close()
    return facts


def assert_arm(arm: Arm, config_path: Path) -> dict:
    facts = live_facts(config_path)
    want_inflation = FULL_GATE_RING_M if arm.full else 1.022296
    if facts["held_stall_release"] is not arm.door:
        raise RuntimeError(f"{arm.name}: held_stall_release {facts['held_stall_release']}")
    if abs(facts["planner_inflation_radius_m"] - want_inflation) > 1e-6:
        raise RuntimeError(
            f"{arm.name}: inflation {facts['planner_inflation_radius_m']} != {want_inflation}"
        )
    if abs(facts["navigator_brake_obstacle_stop_m"] - 0.80) > 1e-9:
        raise RuntimeError(f"{arm.name}: the navigator brake moved")
    if abs(facts["planner_gate_clearance_m"] - FULL_GATE_RING_M) > 1e-9:
        raise RuntimeError(f"{arm.name}: the commissioned gate ring moved")
    facts["arm"] = arm.name
    facts["asserted"] = True
    return facts


# ---------------------------------------------------------------------------
# Stage: NAV-GEN-1
# ---------------------------------------------------------------------------


def _ng1_modules():
    ng1 = repo_root() / "research" / "20260829" / "nav-gen-attribution-1"
    if not ng1.is_dir():
        raise RuntimeError(f"NG1 harness not found at {ng1}")
    if str(ng1) not in sys.path:
        sys.path.insert(0, str(ng1))
    import episodes as EP
    import run as NG1

    return EP, NG1


def stage_ng1(args) -> None:
    _EP, NG1 = _ng1_modules()
    raw = NG1_SCRATCH / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (NG1_SCRATCH / "navcfg").mkdir(parents=True, exist_ok=True)

    arms = [ARM_BY_NAME[n] for n in args.arms.split(",")] if args.arms else list(ARMS)
    cfgs = {a.name: build_arm_config(a) for a in arms}
    facts = {a.name: assert_arm(a, cfgs[a.name]) for a in arms}
    (raw / "w6_arm_facts.json").write_text(json.dumps(facts, indent=2))
    print(json.dumps(facts, indent=2), flush=True)

    host_start = NG1.host_snapshot()
    units = []
    for a in arms:
        units += NG1.arm_units(NG1.Arm(a.name), cfgs[a.name], blocks=("generated", "frozen"))
    print(f"[w6] {len(units)} units, {args.workers} workers", flush=True)
    by_arm = NG1.run_units(units, args.workers, label="w6")
    index = {
        "arms": {},
        "arm_facts": facts,
        "host_start": host_start,
        "run_provenance": {
            "workers": args.workers,
            "cpus": os.cpu_count(),
            "argv": list(sys.argv[1:]),
            "repo": str(repo_root()),
        },
    }
    for a in arms:
        res = by_arm[a.name]
        out = raw / f"w6_rows_{a.name}.json"
        out.write_text(json.dumps(res))
        index["arms"][a.name] = {
            "episodes": len(res["rows"]),
            "wall_s": res["wall_s"],
            "strict_success": sum(1 for r in res["rows"] if r["strict_success"]),
            "file": out.name,
        }
        print(json.dumps({a.name: index["arms"][a.name]}), flush=True)
    index["host_end"] = NG1.host_snapshot()
    (raw / "w6_index.json").write_text(json.dumps(index, indent=2))


# ---------------------------------------------------------------------------
# Stage: the frozen corpora (v4 minival + mutation panel), ONE ARM per process
# ---------------------------------------------------------------------------


def report_digest(report: dict, *, drop_aggregate_scene: bool, compact: bool) -> str:
    """tests/test_nav_instruct_digest_recipe.py's recipe, reproduced exactly."""

    body = {k: v for k, v in report.items() if k not in REPORT_EXCLUSIONS}
    if drop_aggregate_scene and isinstance(body.get("aggregate"), dict):
        body = dict(body)
        body["aggregate"] = {
            k: v for k, v in body["aggregate"].items() if k != "scene"
        }
    if compact:
        blob = json.dumps(body, sort_keys=True, separators=(",", ":"))
    else:
        blob = json.dumps(body, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def stage_frozen(args) -> None:
    repo = repo_root()
    arm = ARM_BY_NAME[args.arm]
    cfg = build_arm_config(arm)
    facts = assert_arm(arm, cfg)

    # THE PATCH — harness side, this child process only.  DESIGN.md sec. 3.3.
    from parcel_robot.simulation import headless_city

    if not arm.commissioned:
        headless_city._navigation_config_from_store = lambda _store, _p=cfg: _p
    # Prove the patch reaches the product caller BEFORE any episode runs.
    from parcel_robot.simulation.headless_city import HeadlessCityQualityHarness

    probe = HeadlessCityQualityHarness(headless_city.HeadlessCityWorld())
    facts["harness_navigation_config"] = str(probe.navigation_config)
    if str(probe.navigation_config) != str(cfg):
        raise RuntimeError(
            f"{arm.name}: harness reads {probe.navigation_config}, not {cfg}"
        )
    facts["harness_reactive_gate_obstacle_stop_m"] = float(
        probe.reactive_safety.obstacle_stop_m
    )
    if abs(facts["harness_reactive_gate_obstacle_stop_m"] - 0.65) > 1e-9:
        raise RuntimeError(f"{arm.name}: the runtime reactive gate moved")
    del probe

    out_root = SCRATCH / "frozen" / arm.name
    out_root.mkdir(parents=True, exist_ok=True)
    payload = {"arm": arm.name, "facts": facts}

    # --- I2: the v4 minival -------------------------------------------------
    t0 = time.time()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from evals.nav_instruct import run_nav_instruct_v1 as RNV

    mini_out = out_root / "minival"
    mini_out.mkdir(parents=True, exist_ok=True)
    rc = RNV.main(
        [
            "--minival",
            "--mode",
            "baseline",
            "--episode-version",
            "v4",
            "--no-ledger",
            "--out",
            str(mini_out),
        ]
    )
    reports = sorted(mini_out.glob("nav-instruct-v1-*.json"))
    if len(reports) != 1:
        raise RuntimeError(f"{arm.name}: expected one minival report, got {reports}")
    report = json.loads(reports[0].read_text())
    payload["minival"] = {
        "rc": rc,
        "report_file": str(reports[0]),
        "wall_s": round(time.time() - t0, 1),
        "report_digest": report_digest(report, drop_aggregate_scene=True, compact=True),
        "episode_digest": report.get("episode_digest"),
        "aggregate": report.get("aggregate"),
        "episodes": report.get("episodes"),
    }
    print(
        json.dumps(
            {
                "arm": arm.name,
                "minival_digest": payload["minival"]["report_digest"],
                "matches_HEAD": payload["minival"]["report_digest"] == HEAD_MINIVAL_DIGEST,
            }
        ),
        flush=True,
    )

    # --- I3: the mutation panel --------------------------------------------
    import importlib.util

    t1 = time.time()
    spec = importlib.util.spec_from_file_location(
        "w6_mutation_panel", repo / "scripts" / "mutation_panel.py"
    )
    panel_mod = importlib.util.module_from_spec(spec)
    sys.modules["w6_mutation_panel"] = panel_mod
    spec.loader.exec_module(panel_mod)
    panel = panel_mod.run_panel()
    panel_out = out_root / f"{arm.name}.panel.json"
    panel_out.write_text(json.dumps(panel, sort_keys=True, indent=2) + "\n")
    payload["panel"] = {
        "file": str(panel_out),
        "wall_s": round(time.time() - t1, 1),
        "generated_at": panel["generated_at"],
        "passed": panel["passed"],
        "survivors": panel["survivors"],
        "equivalent_mutants": panel["equivalent_mutants"],
        "clean_run": panel["clean_run"],
        "clean_checks": panel["clean_checks"],
        "mutants": [
            {
                "mutation": m["mutation"],
                "verdict": m["verdict"],
                "checks_reddened": m["checks_reddened"],
                "kill_channels": len(m["checks_reddened"]),
                "error": m["error"],
            }
            for m in panel["mutants"]
        ],
    }
    print(
        json.dumps(
            {
                "arm": arm.name,
                "panel_passed": panel["passed"],
                "survivors": panel["survivors"],
                "authority": panel["clean_run"]["authority"],
            }
        ),
        flush=True,
    )

    (out_root / "frozen.json").write_text(json.dumps(payload, indent=2))
    print(f"wrote {out_root / 'frozen.json'}", flush=True)


def stage_facts(_args) -> None:
    facts = {}
    for a in ARMS:
        facts[a.name] = assert_arm(a, build_arm_config(a))
    print(json.dumps(facts, indent=2))
    (SCRATCH / "arm_facts.json").parent.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "arm_facts.json").write_text(json.dumps(facts, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=("facts", "ng1", "frozen", "prepare"))
    ap.add_argument("--arm", default="")
    ap.add_argument("--arms", default="")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if args.stage == "facts":
        stage_facts(args)
    elif args.stage == "prepare":
        EP, _NG1 = _ng1_modules()
        raw = NG1_SCRATCH / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        man = EP.scene_manifest()
        params = {str(s): EP.scene_params(s) for s in EP.SCENE_SEEDS}
        (raw / "scenes.json").write_text(
            json.dumps({"manifest": man, "params": params, "episodes": EP.summary()}, indent=2)
        )
        print(json.dumps({"scenes": man["n"], "manifest_sha256": man["manifest_sha256"]}))
    elif args.stage == "ng1":
        stage_ng1(args)
    else:
        if not args.arm:
            raise SystemExit("--stage frozen needs --arm")
        stage_frozen(args)


if __name__ == "__main__":
    main()
