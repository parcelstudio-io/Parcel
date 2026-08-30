"""NAV-GEN-1 — does each arm's config reach the LIVE planner object?

    env -u TMPDIR .parcel/bin/python \
      research/20260829/nav-gen-attribution-1/plumbing_check.py

Builds one real ``DirectiveNavigator`` per arm from that arm's own config file
and reads ``GridPlannerConfig.inflation_radius_m`` off the live planner. This
is the evidence behind RESULTS.md 2.1: ``map_safety_margin_m`` reaches the
planner (its ``safety_margin_m`` moves 0.10 -> 0.00) but does NOT move the
inflation, because ``DirectiveNavigator._create_navigator`` commissions the
gate ring from ``safety.stop_distance_m`` and the ``max`` takes that term.

Read-only: builds and closes navigators, writes nothing, drives no episode.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import episodes as EP  # noqa: F401  (puts src/ on sys.path, sets scratch env)
import run as _r  # resolved from HERE, which sits first on sys.path

from parcel_robot.navigation.pipeline import DirectiveNavigator


def live_planner_rows(nav) -> list:
    """Every occupancy planner reachable from this navigator, with its config."""

    found: list = []
    seen: set = set()

    def walk(obj, depth=0):
        if id(obj) in seen or depth > 4:
            return
        seen.add(id(obj))
        planner = getattr(obj, "_planner", None)
        cfg = getattr(planner, "config", None)
        if cfg is not None and hasattr(cfg, "inflation_radius_m"):
            found.append({
                "owner": type(obj).__name__,
                "safety_margin_m": round(cfg.safety_margin_m, 6),
                "robot_radius_m": round(cfg.robot_radius_m, 6),
                "gate_clearance_m": (None if cfg.gate_clearance_m is None
                                     else round(cfg.gate_clearance_m, 6)),
                "gate_lateral_clearance_m": round(cfg.gate_lateral_clearance_m, 6),
                "LIVE_inflation_radius_m": round(cfg.inflation_radius_m, 6),
            })
        for name in dir(obj):
            if name.startswith("__"):
                continue
            try:
                value = getattr(obj, name)
            except Exception:  # noqa: BLE001, S112 - probing an arbitrary graph
                continue
            if hasattr(value, "__dict__") and not callable(value):
                walk(value, depth + 1)

    walk(nav)
    return found


def main() -> None:
    out = {}
    for arm in _r.ARMS:
        config_path = _r.build_arm_config(arm)
        facts = _r.planner_facts(config_path)
        nav = DirectiveNavigator.from_config(config_path)
        rows = live_planner_rows(nav)
        nav.close()
        out[arm.name] = {
            "map_safety_margin_m": facts["map_safety_margin_m"],
            "nav_safety_stop_distance_m": facts["nav_safety_stop_distance_m"],
            "footprint_term_m": facts["footprint_term_m"],
            "config_only_inflation_radius_m": facts["config_only_inflation_radius_m"],
            "live_planner": rows,
        }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
