"""NAV-ACCEPT — the M1 nav acceptance row, on the FROZEN NAV-CORE corpus.

A2's verdict left one row open: arm B was byte-identical before and after the
"one clearance authority" fix, because the harness builds arm B through
``ModelRegistry.create`` directly, which is not a production planner site, so
an un-commissioned caller still gets the legacy 0.42 m inflation.  **The
shipped shape's true arrival rate was therefore UNMEASURED.**  This file
measures it.

Nothing in ``research/20260824/nav-core/`` is edited — every file there is
byte-identical before and after this run (shas in ``RESULTS.md``).  The corpus,
the seeds, the episode set, the room, the door, the arms, the refuter protocol
and the scoring are IMPORTED from that folder verbatim
(``bench._episode_specs``, ``bench._score``, ``bench._refused_row``,
``bench.run_refuters``, ``arms.ArmB``), so the only new thing here is one arm:

* **``shipped``** — arm B's shape (metric point goal at the stored coordinate,
  chance-constrained arrival), with its controller built through the PRODUCT's
  own commissioning path instead of a bare ``registry.create``.

"Through the product's own path" is literal: ``commissioned_navigator`` calls
``DirectiveNavigator._create_navigator``, the production owner's own method,
which asks ``DirectiveNavigator._planner_gate_ring_m`` for the ring its own
brake enforces and hands it to ``registry.create(map_gate_clearance_m=...)``;
``grid_navigator._planner_coupling_ring_m`` then converts that ring into the
frame the grid inflates in via ``ClearanceProfile.gate_range_ring_m``.  No
number is copied into this file — every clearance the shipped arm plans with is
read back OUT of the constructed planner and recorded per episode.

Production owner 2 (``SearchOwnerController``, which passes
``ReactiveSafetyPolicy.planner_gate_ring_m``) is read the same way and recorded
in the environment block; it builds the frontier searcher, not the point-goal
controller this corpus drives, so it is reported, not applied.

Stage 2 flips exactly one product flag,
``ScanMatchConfig.require_relocalization_margin`` (A3 fix 4, ships OFF), on the
same shipped arm and reports the delta.

Reproduce::

    env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label nav-accept \\
      .parcel/bin/python research/20260824/nav-accept/nav_accept.py \\
      --stage corpus --margin off
"""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.perception_source.selection import (
    SOURCE_LEARNED_MAP,
    SemanticSourcePolicy,
    use_learned_map,
    use_semantic_source,
)

HERE = Path(__file__).resolve().parent
NAVCORE = HERE.parent / "nav-core"
if str(NAVCORE) not in sys.path:
    sys.path.insert(0, str(NAVCORE))

# The frozen harness, loaded rather than copied.  ``importlib`` and not an
# ``import`` statement so the sys.path line above may precede it.
bench = importlib.import_module("bench")
door = importlib.import_module("door")
arms = importlib.import_module("arms")
room = importlib.import_module("room")
world_map = importlib.import_module("world_map")

ArmB = arms.ArmB
ARRIVAL_BAND_M = arms.ARRIVAL_BAND_M
GATE_DEMAND_M = arms.GATE_DEMAND_M

SCRATCH = Path(
    "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/"
    "0b505906-665b-45ea-a2b7-686b3aecb89d/scratchpad/nav-accept"
)

_OWNER: Any = None


def pipeline_owner() -> Any:
    """Production owner 1, built exactly as the product builds it."""

    global _OWNER
    if _OWNER is None:
        _OWNER = DirectiveNavigator.from_config()
    return _OWNER


def commissioned_navigator(arrive_radius_m: float) -> Any:
    """The controller production owner 1 would build, at the corpus's radius.

    ``_create_navigator`` is the product's own method: it asks
    ``_planner_gate_ring_m()`` (this navigator's own collision brake,
    ``configs/navigation/default.yaml`` ``safety.stop_distance_m``) and passes
    it as ``map_gate_clearance_m`` only to models that HAVE an occupancy
    planner.  ``arrive_radius_m`` stays the corpus's pre-registered
    ``ARRIVAL_BAND_M``, so the ONLY difference from arm B is the clearance.
    """

    owner = pipeline_owner()
    return owner._create_navigator(owner.model_id, arrive_radius_m)


def commissioned_rings() -> dict[str, Any]:
    """Both production owners' commissioned values, read from the product."""

    owner = pipeline_owner()
    policy = arms._safety_policy()
    shipped = commissioned_navigator(ARRIVAL_BAND_M)
    shipped_config = shipped._planner.config
    registry, active = arms._navigation_registry()
    legacy = registry.create(active, arrive_radius_m=ARRIVAL_BAND_M)
    legacy_config = legacy._planner.config
    rings = {
        "model_id": owner.model_id,
        "active_model": active,
        "owner_1_pipeline": {
            "site": "navigation/pipeline.py::DirectiveNavigator._create_navigator",
            "brake_m": float(owner.collision.obstacle_stop_m),
            "planner_gate_ring_m": float(owner._planner_gate_ring_m()),
            "planner_gate_clearance_m": float(shipped_config.gate_clearance_m),
            "planner_inflation_radius_m": float(shipped_config.inflation_radius_m),
        },
        "owner_2_search_owner": {
            "site": "navigation/search_owner.py::SearchOwnerController",
            "brake_m": float(policy.obstacle_stop_m),
            "planner_gate_ring_m": float(policy.planner_gate_ring_m),
            "applied_to_this_corpus": False,
            "why": (
                "builds the frontier searcher, not the point-goal controller "
                "the corpus drives; recorded, not applied"
            ),
        },
        "legacy_arm_b": {
            "site": "ModelRegistry.create (un-commissioned)",
            "planner_gate_clearance_m": float(legacy_config.gate_clearance_m),
            "planner_inflation_radius_m": float(legacy_config.inflation_radius_m),
        },
    }
    shipped.close()
    legacy.close()
    return rings


class ArmShipped(ArmB):
    """Arm B's shape, commissioned through production owner 1.

    ``ArmB.__init__`` runs verbatim (same body, same pose stack, same detector
    seeding, same stored goal, same mission); the un-commissioned controller it
    builds is then closed and replaced by the commissioned one before a single
    tick runs.  Everything downstream — ``_Runner.run``, the untouched reactive
    gate, the scoring — is the frozen harness.
    """

    arm = "shipped"
    #: A3 fix 4.  ``False`` is the shipped default.
    require_relocalization_margin = False

    def __init__(self, spec: Any) -> None:
        if spec.hard_margin_m is not None:
            raise ValueError("the shipped arm takes the product's margin, not a patch")
        super().__init__(spec)
        legacy = self.navigator
        self.navigator = commissioned_navigator(ARRIVAL_BAND_M)
        legacy.close()
        self.navigator.reset(self.mission)
        config = self.navigator._planner.config
        self.result.extra["planner_gate_clearance_m"] = float(config.gate_clearance_m)
        self.result.extra["planner_inflation_radius_m"] = float(config.inflation_radius_m)
        localizer = self.stack.localizer
        localizer.config = replace(
            localizer.config,
            require_relocalization_margin=bool(self.require_relocalization_margin),
        )
        self.result.extra["require_relocalization_margin"] = bool(
            self.require_relocalization_margin
        )
        self._instrument_localizer()

    def _instrument_localizer(self) -> None:
        """Count what the localizer did, without changing what it does.

        ``PoseStack.update`` is wrapped on the INSTANCE; the wrapper reads the
        localizer's public ``diagnostics`` (fully replaced every tick) and the
        published update's health AFTER the real call returns.  Read-only.
        """

        stack = self.stack
        events: dict[str, int] = {}
        health: dict[str, int] = {}
        margins: list[float] = []
        original = stack.update

        def counting(truth: Any, scan: Any, t_s: float) -> Any:
            update = original(truth, scan, t_s)
            key = str(stack.localizer.diagnostics.get("event") or "none")
            events[key] = events.get(key, 0) + 1
            name = getattr(update.health, "value", str(update.health))
            health[name] = health.get(name, 0) + 1
            match = getattr(update, "match", None)
            if match is not None and getattr(match, "margin", None) is not None:
                margins.append(round(float(match.margin), 6))
            return update

        stack.update = counting
        self._localizer_events = events
        self._localizer_health = health
        self._relocalization_margins = margins

    def finish(self) -> None:
        super().finish()
        self.result.extra["localizer_events"] = dict(
            sorted(self._localizer_events.items(), key=lambda kv: -kv[1])
        )
        self.result.extra["map_health_ticks"] = dict(self._localizer_health)
        self.result.extra["relocalization_margins"] = self._relocalization_margins


class ArmShippedMarginOn(ArmShipped):
    """The same arm with A3's ``require_relocalization_margin`` turned ON."""

    arm = "shipped_margin_on"
    require_relocalization_margin = True


def run_corpus(runtime: Any, arm_cls: type) -> list[dict[str, Any]]:
    """``bench.run_corpus``'s loop with one arm instead of two.

    Seeds, episode specs, the door call and the refusal row all come from the
    frozen ``bench`` module; only the arm tuple differs.
    """

    label = arm_cls.arm
    rows: list[dict[str, Any]] = []
    for seed_index, seed in enumerate(bench.SEEDS):
        learned = world_map.seed_room_map()
        use_learned_map(learned)
        for spec in bench._episode_specs(seed_index, seed, learned):
            verdict = door.ask(runtime, room.PLACES_BY_ID[spec.goal_id].label)
            if not verdict.admitted:
                rows.append(bench._refused_row(label, spec, verdict))
                continue
            result = arm_cls(spec).run()
            row = result.as_row()
            row["door_status"] = verdict.status
            row["route_rule"] = verdict.route_rule
            rows.append(row)
            print(
                f"  seed {seed} ep {spec.episode:2d} {spec.goal_id:14s} "
                f"L{spec.layout} arrived={row['arrived']} "
                f"d={row['truth_distance_m']} {row['failure_type']}",
                flush=True,
            )
    return rows


def environment() -> dict[str, Any]:
    policy = arms._safety_policy()
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": platform.node(),
        "python": platform.python_version(),
        "obstacle_stop_m": policy.obstacle_stop_m,
        "obstacle_slow_m": policy.obstacle_slow_m,
        "reaction_time_s": policy.reaction_time_s,
        "planner_inflation_m": policy.planner_inflation_m,
        "gate_demand_at_cruise_m": GATE_DEMAND_M,
        "room_worst_clearance_m": round(min(room.audit_clearances().values()), 4),
        "alias_scan_max_disagreement_m": room.alias_scan_agreement(),
        "commissioning": commissioned_rings(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="corpus", choices=("corpus", "refuters"))
    parser.add_argument(
        "--margin",
        default="off",
        choices=("off", "on"),
        help="ScanMatchConfig.require_relocalization_margin (corpus stage only)",
    )
    parser.add_argument(
        "--control",
        action="store_true",
        help=(
            "reproduction control: run the FROZEN arms.ArmB through this same "
            "driver; its rows must match results/corpus.json's arm-B rows"
        ),
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    use_learned_map(world_map.seed_room_map())
    runtime = door.build_runtime(SCRATCH)
    try:
        env = environment()
        started = time.perf_counter()
        if args.stage == "corpus":
            arm_cls = ArmShippedMarginOn if args.margin == "on" else ArmShipped
            if args.control:
                arm_cls = ArmB
            print(f"corpus ({arm_cls.arm}):", flush=True)
            rows = run_corpus(runtime, arm_cls)
            payload = {
                "environment": env,
                "wall_s": round(time.perf_counter() - started, 1),
                "arms": {arm_cls.arm: bench._score(rows, arm_cls.arm)},
                "rows": rows,
            }
            name = args.out or (
                "legacy_b_control.json"
                if args.control
                else f"shipped_corpus_margin_{args.margin}.json"
            )
        else:
            # The frozen refuter driver, verbatim, with the two shipped arms
            # substituted for A and B: R4b's one-shot operator protocol, the
            # scan-gap and degrade windows and the seeds are all ``bench``'s.
            print("refuters (shipped clearance; margin off vs on):", flush=True)
            bench.ArmA = ArmShipped
            bench.ArmB = ArmShippedMarginOn
            rows = bench.run_refuters(runtime)
            payload = {
                "environment": env,
                "wall_s": round(time.perf_counter() - started, 1),
                "rows": rows,
            }
            name = args.out or "shipped_refuters.json"
        HERE.mkdir(parents=True, exist_ok=True)
        (HERE / name).write_text(json.dumps(payload, indent=1), encoding="utf-8")
        print(json.dumps(payload.get("arms", {}), indent=1))
        print(f"wrote {HERE / name}", flush=True)
    finally:
        runtime.close()
        if _OWNER is not None:
            _OWNER.close()
        use_learned_map(None)
        use_semantic_source(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
