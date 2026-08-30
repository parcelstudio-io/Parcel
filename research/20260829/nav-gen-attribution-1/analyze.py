"""NAV-GEN-1 — analysis.  Every number in RESULTS.md is produced here.

    env -u TMPDIR .parcel/bin/python research/20260829/nav-gen-attribution-1/analyze.py

Reads ``~/.cache/parcel-0e/ng1/raw/rows_*.json`` and writes ``results.json``
next to this file plus the markdown tables on stdout.  No verdict is drawn —
``VERDICT.md`` is Fable's.
"""

from __future__ import annotations

import collections
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import importlib.util

import episodes as EP

# Load THIS folder's run.py by path: several research folders ship a ``run.py``
# and a bare import would pick whichever is first on sys.path.
_spec = importlib.util.spec_from_file_location("ng1_run", HERE / "run.py")
_run = importlib.util.module_from_spec(_spec)
sys.modules["ng1_run"] = _run
_spec.loader.exec_module(_run)
ARMS, MA1_FRAME_BUDGET, RAW = _run.ARMS, _run.MA1_FRAME_BUDGET, _run.RAW

#: MA-1 RESULTS.md 2 — the pre-generation frozen-block probe, band-entry
#: predicate, 16 plain episodes per target.
MA1_FROZEN_PROBE = {"sidewalk": 0.75, "lamppost": 0.44, "bench": 0.19,
                    "crosswalk": 0.12, "planter": 0.06}
#: The values NAV-GEN-1's FROZEN DESIGN quotes for H-NG1c.  They differ from
#: MA-1's published row for lamppost and bench; both comparisons are reported
#: and neither criterion is moved.
DESIGN_FROZEN_REFERENCE = {"sidewalk": 0.75, "lamppost": 0.6, "bench": 0.0}
DESIGN_TOLERANCE = 0.15


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(p, 4), round(max(0.0, centre - half), 4),
            round(min(1.0, centre + half), 4))


def load() -> dict:
    out = {}
    for arm in ARMS:
        f = RAW / f"rows_{arm.name}.json"
        if f.is_file():
            out[arm.name] = json.loads(f.read_text())
    return out


def split(rows):
    gen = [r for r in rows if r["block"] == "generated"]
    frz = [r for r in rows if r["block"] == "frozen"]
    return gen, frz


def rate(rows, key="strict_success"):
    k = sum(1 for r in rows if r[key])
    return k, len(rows), wilson(k, len(rows))


def h_ng1a(rows, success_key: str = "strict_success") -> dict:
    """Termination/clearance vs grounding on STRICT failures."""

    fails = [r for r in rows if not r[success_key]]
    n = len(fails)
    in2x = sum(1 for r in fails if r["inside_2x_band"])
    tc_reason = sum(1 for r in fails if r["class"] == "termination_clearance")
    covered = sum(1 for r in fails
                  if r["inside_2x_band"] or r["class"] == "termination_clearance")
    grounding = sum(1 for r in fails if r["class"] == "grounding")
    return {
        "strict_failures": n,
        "inside_2x_band": in2x,
        "inside_2x_band_frac": round(in2x / n, 4) if n else None,
        "termination_clearance_reason": tc_reason,
        "termination_clearance_reason_frac": round(tc_reason / n, 4) if n else None,
        "covered_by_H_NG1a_clause": covered,
        "covered_frac": round(covered / n, 4) if n else None,
        "covered_ci": wilson(covered, n),
        "grounding_failures": grounding,
        "grounding_frac": round(grounding / n, 4) if n else None,
        "grounding_ci": wilson(grounding, n),
        "bar_covered_ge_0_70": (covered / n >= 0.70) if n else None,
        "bar_grounding_lt_0_15": (grounding / n < 0.15) if n else None,
        "refuted_grounding_ge_0_30": (grounding / n >= 0.30) if n else None,
        "wrong_instance": sum(1 for r in fails if r["wrong_instance"]),
        "false_arrivals": sum(1 for r in fails if r.get("false_arrival")),
        "false_arrival_frac": (round(sum(1 for r in fails if r.get("false_arrival")) / n, 4)
                               if n else None),
        "wrong_instance_ids": collections.Counter(
            r["target_id"] for r in fails if r["wrong_instance"]).most_common(),
        # SENSITIVITY, reported beside the pre-registered bar and never in place
        # of it: ``navigation_no_progress`` is the progress watchdog firing with
        # the route still planned (NAV-CORE's stall class).  The DESIGN's
        # reason list does not name it, so it is NOT counted in the bar above.
        "sensitivity_if_navigation_no_progress_counted": (
            round(sum(1 for r in fails
                      if r["inside_2x_band"] or r["class"] == "termination_clearance"
                      or r["reason"] == "navigation_no_progress") / n, 4) if n else None),
        "reason_histogram": collections.Counter(r["reason"] for r in fails).most_common(),
        "reason_grounding_split": dict(collections.Counter(
            r["reason"] for r in fails if r["class"] == "grounding")),
        "class_histogram": collections.Counter(r["class"] for r in fails).most_common(),
        "target_histogram": collections.Counter(r["target"] for r in fails).most_common(),
        "top5_with_example": [
            {"reason": reason, "n": n_r,
             "example_episode_id": next(r["episode_id"] for r in fails
                                        if r["reason"] == reason),
             "example_dtg_m": next(r["dtg_m"] for r in fails if r["reason"] == reason),
             "example_inside_2x": next(r["inside_2x_band"] for r in fails
                                       if r["reason"] == reason)}
            for reason, n_r in
            collections.Counter(r["reason"] for r in fails).most_common(5)],
    }


def h_ng1b(data) -> dict:
    sweep = []
    base = None
    for arm in ARMS:
        if arm.name not in data:
            continue
        gen, _ = split(data[arm.name]["rows"])
        k, n, ci = rate(gen)
        kb, _nb, cib = rate(gen, "band_entry")
        coll = sum(r["collision_count"] for r in gen)
        clear = [r["minimum_clearance_m"] for r in gen if r["minimum_clearance_m"] is not None]
        below_stop = sum(1 for r in gen
                         if r["minimum_clearance_m"] is not None
                         and r["minimum_clearance_m"] < r["required_obstacle_clearance_m"])
        row = {
            "arm": arm.name, "sweep": arm.sweep,
            "map_safety_margin_m": arm.margin_m,
            "nav_safety_stop_distance_m": arm.stop_distance_m,
            "footprint_term_m": arm.footprint_term_m,
            "planner_inflation_m": arm.inflation_m, "commissioned": arm.commissioned,
            "episodes": n, "strict_success": k, "strict_rate": ci[0],
            "strict_ci95": [ci[1], ci[2]],
            "band_entry": kb, "band_entry_rate": cib[0],
            "strict_rate_any_instance": rate(gen, "strict_success_any_instance")[2][0],
            "strict_ci95_any_instance": list(rate(gen, "strict_success_any_instance")[2][1:]),
            "false_arrivals": sum(1 for r in gen if r.get("false_arrival")),
            "grounding_class_episodes": sum(1 for r in gen if r["class"] == "grounding"),
            "collisions": coll,
            "episodes_below_stop_band": below_stop,
            "min_clearance_min_m": round(min(clear), 4) if clear else None,
            "min_clearance_median_m": round(sorted(clear)[len(clear) // 2], 4) if clear else None,
            "nav_claimed_rate": round(sum(1 for r in gen if r["nav_claimed_success"]) / n, 4) if n else None,
        }
        if arm.commissioned:
            base = row
        sweep.append(row)
    gains = []
    if base:
        for row in sweep:
            if row["arm"] == base["arm"]:
                continue
            gains.append({
                "arm": row["arm"], "planner_inflation_m": row["planner_inflation_m"],
                "gain_points": round(100.0 * (row["strict_rate"] - base["strict_rate"]), 2),
                "collisions": row["collisions"],
                "zero_collisions": row["collisions"] == 0,
                "episodes_below_stop_band": row["episodes_below_stop_band"],
            })
    best = max(gains, key=lambda g: g["gain_points"]) if gains else None
    return {
        "sweep": sweep, "baseline_arm": base["arm"] if base else None,
        "gains_vs_commissioned": gains, "best": best,
        "bar_ge_20_points_at_zero_collisions": bool(
            best and best["gain_points"] >= 20.0 and best["zero_collisions"]),
        "refuted_no_arm_gains_10_at_zero_collisions": bool(
            gains and not any(g["gain_points"] >= 10.0 and g["zero_collisions"] for g in gains)),
        "design_target_inflation_m": 0.20,
        "design_target_reachable": False,
        "design_target_note": (
            "planner inflation = SafetyEnvelope.footprint_radius_m (0.32, a code "
            "constant in parcel_robot.authority) + map_safety_margin_m, and "
            "ClearanceProfile refuses a negative margin "
            "('planner_hard_margin_m must be non-negative'); 0.32 m is therefore "
            "the architectural floor and 0.20 m is unreachable without editing "
            "src/, which this probe may not do."),
    }


def h_ng1c(data) -> dict:
    out = {}
    for arm in ARMS:
        if arm.name not in data:
            continue
        _gen, frz = split(data[arm.name]["rows"])
        per = {}
        for target in EP.TARGETS:
            rows = [r for r in frz if r["target"] == target]
            kb, n, cib = rate(rows, "band_entry")
            ks, _n2, cis = rate(rows, "strict_success")
            per[target] = {
                "episodes": n, "band_entry": kb, "band_entry_rate": cib[0],
                "band_entry_ci95": [cib[1], cib[2]],
                "strict_success": ks, "strict_rate": cis[0],
                "ma1_probe_band_entry": MA1_FROZEN_PROBE.get(target),
                "delta_vs_ma1": (round(cib[0] - MA1_FROZEN_PROBE[target], 4)
                                 if target in MA1_FROZEN_PROBE else None),
                "within_0_15_of_ma1": (abs(cib[0] - MA1_FROZEN_PROBE[target]) <= DESIGN_TOLERANCE
                                       if target in MA1_FROZEN_PROBE else None),
                "design_reference": DESIGN_FROZEN_REFERENCE.get(target),
                "within_0_15_of_design_reference": (
                    abs(cib[0] - DESIGN_FROZEN_REFERENCE[target]) <= DESIGN_TOLERANCE
                    if target in DESIGN_FROZEN_REFERENCE else None),
            }
        out[arm.name] = per
    a0 = out.get("A0", {})
    checked = [t for t in DESIGN_FROZEN_REFERENCE if t in a0]
    return {
        "per_arm": out,
        "design_named_targets": checked,
        "bar_all_within_0_15_of_design_reference": all(
            a0[t]["within_0_15_of_design_reference"] for t in checked) if checked else None,
        "bar_all_within_0_15_of_ma1_published": all(
            a0[t]["within_0_15_of_ma1"] for t in checked) if checked else None,
        "note": ("MA-1 RESULTS.md 2 publishes sidewalk 0.75 / lamppost 0.44 / "
                 "bench 0.19; NAV-GEN-1's frozen DESIGN quotes 0.75 / 0.6 / 0.0 "
                 "for the same probe. Both comparisons are reported; the DESIGN "
                 "criterion is not moved."),
    }


def ma1_reconciliation(data) -> dict:
    """Why this probe's generated-block rate is not MA-1's 4.5 %."""

    out = {}
    for arm in ("A0",):
        if arm not in data:
            continue
        gen, _ = split(data[arm]["rows"])
        n = len(gen)
        out[arm] = {
            "episodes": n,
            "strict_rate_1800_steps": rate(gen)[2][0],
            "band_entry_rate_1800_steps": rate(gen, "band_entry")[2][0],
            "band_entry_rate_within_ma1_420_frame_budget":
                rate(gen, "band_entry_within_ma1_budget")[2][0],
            "median_steps": sorted(r["steps"] for r in gen)[n // 2] if n else None,
            "median_steps_successes": (
                sorted(r["steps"] for r in gen if r["strict_success"])[
                    max(0, sum(1 for r in gen if r["strict_success"]) // 2)]
                if any(r["strict_success"] for r in gen) else None),
            "ma1_teacher_sr_held": 0.045,
            "ma1_note": ("MA-1 scored the LAST goal of a scripted multi-goal "
                         "episode (60 % plain / 20 % revise / 20 % queue) under a "
                         f"{MA1_FRAME_BUDGET}-frame per-goal budget with stop and "
                         "owner-speaking cues; this probe scores ONE plain "
                         "directive per episode under the harness's own 1800-step "
                         "budget with no cues. The episode script is NOT the "
                         "explanation: MA-1's 0.045 is a gold-predicate artefact "
                         "(its loop ends one frame after the navigator declares "
                         "arrival, so ORACLE_SETTLE_FRAMES=5 can never "
                         "accumulate). Attribution WITHDRAWN — see RESULTS.md "
                         "7.3a and VERDICT.md 5.1."),
        }
    return out


def per_target(data, arm="A0") -> dict:
    gen, _ = split(data[arm]["rows"])
    out = {}
    for target in EP.TARGETS:
        rows = [r for r in gen if r["target"] == target]
        k, n, ci = rate(rows)
        _kb, _n2, cib = rate(rows, "band_entry")
        out[target] = {"episodes": n, "strict_success": k, "strict_rate": ci[0], "strict_ci95": [ci[1], ci[2]],
                       "band_entry_rate": cib[0],
                       "top_reason": collections.Counter(
                           r["reason"] for r in rows if not r["strict_success"]).most_common(3)}
    return out


def scene_correlation(data, arm="A0") -> dict:
    """Does the goal's own clearance predict the outcome?"""

    gen, _ = split(data[arm]["rows"])
    buckets = collections.defaultdict(lambda: [0, 0])
    for r in gen:
        c = r["goal_band_clearance_max_m"]
        if c is None:
            continue
        b = ("<0.10" if c < 0.10 else "0.10-0.32" if c < 0.32 else
             "0.32-0.70" if c < 0.70 else "0.70-1.00" if c < 1.0 else
             "1.00-2.00" if c < 2.0 else ">=2.00")
        buckets[b][1] += 1
        buckets[b][0] += int(r["strict_success"])
    order = ["<0.10", "0.10-0.32", "0.32-0.70", "0.70-1.00", "1.00-2.00", ">=2.00"]
    return {b: {"strict_success": buckets[b][0], "episodes": buckets[b][1],
                "rate": round(buckets[b][0] / buckets[b][1], 4) if buckets[b][1] else None}
            for b in order if b in buckets}


def unreachable_diagnosis(data, arm="A0") -> dict:
    """Is `semantic_target_unreachable` explained by the planner's inflation?

    The LIVE inflation is a CENTRE-to-obstacle-surface radius; a band point is
    routable exactly when its BODY-SURFACE clearance is
    >= inflation - footprint_radius. At the commissioned arm that demand is
    1.0223 - 0.32 = 0.7023 m of surface clearance inside the goal band.
    """

    gen, _ = split(data[arm]["rows"])
    arm_obj = next(a for a in ARMS if a.name == arm)
    demand = round(arm_obj.inflation_m - 0.32, 4)
    rows = [r for r in gen if r["reason"] == "semantic_target_unreachable"]
    clear = sorted(r["goal_band_clearance_max_m"] for r in rows
                   if r["goal_band_clearance_max_m"] is not None)
    allc = sorted(r["goal_band_clearance_max_m"] for r in gen
                  if r["goal_band_clearance_max_m"] is not None)
    return {
        "arm": arm,
        "live_inflation_m": arm_obj.inflation_m,
        "required_band_surface_clearance_m": demand,
        "unreachable_episodes": len(rows),
        "unreachable_band_clearance_min_m": clear[0] if clear else None,
        "unreachable_band_clearance_median_m": clear[len(clear) // 2] if clear else None,
        "unreachable_band_clearance_max_m": clear[-1] if clear else None,
        "unreachable_with_band_clearance_below_demand": sum(1 for c in clear if c < demand),
        "all_episodes_band_clearance_min_m": allc[0] if allc else None,
        "all_episodes_with_band_clearance_below_demand": sum(1 for c in allc if c < demand),
        "episodes": len(gen),
    }


def markdown(out: dict) -> str:
    """Every table in RESULTS.md 4-7, rendered from `out`. Nothing hand-typed."""

    L = []
    a = out["H_NG1a"]
    aa = out["H_NG1a_any_instance_oracle"]
    ax = out["H_NG1a_excluding_crosswalk"]
    b = out["H_NG1b"]
    c = out["H_NG1c"]

    L.append("### 4.1 The sweep (generated block, 450 episodes per arm)\n")
    L.append("| arm | sweep | `map_safety_margin_m` | `safety.stop_distance_m` | "
             "**live planner inflation (m)** | strict success | 95 % Wilson CI | "
             "any-instance strict | band entry | nav-claimed | grounding-class episodes | "
             "false arrivals | collisions | episodes with min clearance < 0.65 m |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for row in b["sweep"]:
        star = " **(commissioned)**" if row["commissioned"] else ""
        L.append(f"| {row['arm']}{star} | {row['sweep']} | {row['map_safety_margin_m']:.2f} | "
                 f"{row['nav_safety_stop_distance_m']:.2f} | "
                 f"{row['planner_inflation_m']:.4f} | "
                 f"{row['strict_success']}/{row['episodes']} = **{row['strict_rate']:.4f}** | "
                 f"[{row['strict_ci95'][0]:.4f}, {row['strict_ci95'][1]:.4f}] | "
                 f"{row['strict_rate_any_instance']:.4f} | {row['band_entry_rate']:.4f} | "
                 f"{row['nav_claimed_rate']:.4f} | {row['grounding_class_episodes']} | "
                 f"{row['false_arrivals']} | **{row['collisions']}** | "
                 f"{row['episodes_below_stop_band']} |")

    L.append("\n### 4.2 Gain vs the commissioned arm\n")
    L.append("| arm | live planner inflation (m) | gain (points, strict) | collisions | zero collisions |")
    L.append("|---|---|---|---|---|")
    for g in b["gains_vs_commissioned"]:
        L.append(f"| {g['arm']} | {g['planner_inflation_m']:.4f} | "
                 f"{g['gain_points']:+.2f} | {g['collisions']} | "
                 f"{'yes' if g['zero_collisions'] else 'NO'} |")

    L.append("\n### 5.1 Reason histogram — strict failures, commissioned arm, generated block\n")
    L.append(f"n = {a['strict_failures']} strict failures of 450 episodes.\n")
    L.append("| reason | n | share | of which grounding-class (wrong instance) |")
    L.append("|---|---|---|---|")
    for reason, k in a["reason_histogram"]:
        g = a["reason_grounding_split"].get(reason, 0)
        L.append(f"| `{reason}` | {k} | {k / a['strict_failures']:.3f} | {g} |")

    L.append("\n### 5.2 Top-5 failure reasons with one example episode each\n")
    L.append("| reason | n | example episode id | example DTG (m) | example inside 2x band |")
    L.append("|---|---|---|---|---|")
    for row in a["top5_with_example"]:
        L.append(f"| `{row['reason']}` | {row['n']} | `{row['example_episode_id']}` | "
                 f"{row['example_dtg_m']} | {row['example_inside_2x']} |")

    L.append("\n### 5.3 H-NG1a's two clauses\n")
    L.append("| quantity | commissioned arm | any-instance oracle | excluding `crosswalk` |")
    L.append("|---|---|---|---|")
    for label, key in (("strict failures (n)", "strict_failures"),
                       ("inside 2x band", "inside_2x_band_frac"),
                       ("reason in the DESIGN's list", "termination_clearance_reason_frac"),
                       ("**covered by H-NG1a clause 1**", "covered_frac"),
                       ("**grounding failures**", "grounding_frac"),
                       ("false arrivals", "false_arrival_frac"),
                       ("sensitivity: + `navigation_no_progress`",
                        "sensitivity_if_navigation_no_progress_counted")):
        L.append(f"| {label} | {a[key]} | {aa[key]} | {ax[key]} |")

    L.append("\n### 6.1 Frozen demo block, per target (commissioned arm, 16 episodes each)\n")
    L.append("| target | band entry | rate | 95 % CI | strict | MA-1 published probe | delta vs MA-1 | "
             "within +-0.15 of MA-1 | DESIGN's quoted value | within +-0.15 of DESIGN |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for target, row in c["per_arm"]["A0"].items():
        L.append(f"| `{target}` | {row['band_entry']}/{row['episodes']} | "
                 f"**{row['band_entry_rate']:.4f}** | "
                 f"[{row['band_entry_ci95'][0]:.3f}, {row['band_entry_ci95'][1]:.3f}] | "
                 f"{row['strict_rate']:.4f} | {row['ma1_probe_band_entry']} | "
                 f"{row['delta_vs_ma1']:+.4f} | "
                 f"{'yes' if row['within_0_15_of_ma1'] else 'NO'} | "
                 f"{row['design_reference'] if row['design_reference'] is not None else '--'} | "
                 f"{'yes' if row['within_0_15_of_design_reference'] else ('NO' if row['design_reference'] is not None else '--')} |")

    L.append("\n### 7.1 Per target, generated block, commissioned arm\n")
    L.append("| target | strict | rate | 95 % CI | band entry | top failure reasons |")
    L.append("|---|---|---|---|---|---|")
    for target, row in out["per_target_generated_A0"].items():
        top = ", ".join(f"`{r}` x{k}" for r, k in row["top_reason"])
        L.append(f"| `{target}` | {row['strict_success']}/{row['episodes']} | "
                 f"{row['strict_rate']:.4f} | [{row['strict_ci95'][0]:.3f}, {row['strict_ci95'][1]:.3f}] | "
                 f"{row['band_entry_rate']:.4f} | {top} |")

    L.append("\n### 7.2 Goal-band clearance vs outcome (commissioned arm, generated block)\n")
    L.append("| best standable clearance inside the goal band | episodes | strict success rate |")
    L.append("|---|---|---|")
    for bucket, row in out["goal_clearance_vs_outcome_A0"].items():
        L.append(f"| {bucket} m | {row['episodes']} | {row['rate']} |")

    u = out["unreachable_diagnosis_A0"]
    L.append("\n### 7.2b Is `semantic_target_unreachable` an inflation effect?\n")
    L.append("| quantity | value |")
    L.append("|---|---|")
    for label, key in (("live planner inflation, centre-to-surface (m)", "live_inflation_m"),
                       ("band surface clearance the planner therefore demands (m)",
                        "required_band_surface_clearance_m"),
                       ("`semantic_target_unreachable` episodes", "unreachable_episodes"),
                       ("their goal-band best clearance, min (m)",
                        "unreachable_band_clearance_min_m"),
                       ("their goal-band best clearance, median (m)",
                        "unreachable_band_clearance_median_m"),
                       ("of those, below the planner's demand",
                        "unreachable_with_band_clearance_below_demand"),
                       ("all 450 episodes: goal-band best clearance, min (m)",
                        "all_episodes_band_clearance_min_m"),
                       ("all 450 episodes: below the planner's demand",
                        "all_episodes_with_band_clearance_below_demand")):
        L.append(f"| {label} | {u[key]} |")

    L.append("\n### 7.3 Reconciliation with MA-1's 4.5 %\n")
    m = out["ma1_reconciliation"]["A0"]
    L.append("| quantity | value |")
    L.append("|---|---|")
    for label, key in (("episodes", "episodes"),
                       ("strict success, 1800-step budget", "strict_rate_1800_steps"),
                       ("band entry, 1800-step budget", "band_entry_rate_1800_steps"),
                       ("band entry within MA-1's 420-frame per-goal budget",
                        "band_entry_rate_within_ma1_420_frame_budget"),
                       ("median steps", "median_steps"),
                       ("MA-1 held-out teacher SR", "ma1_teacher_sr_held")):
        L.append(f"| {label} | {m[key]} |")
    return "\n".join(L)


def scene_facts_summary(data, arm="A0") -> dict:
    facts = [f for f in data[arm]["scene_facts"] if f["block"] == "generated"]
    blocked = sorted(f["empirical"]["blocked_fraction"] for f in facts)
    tight = sorted(f["empirical"]["inside_stop_band_fraction"] for f in facts)
    return {
        "scenes": len(facts),
        "blocked_fraction_median": blocked[len(blocked) // 2] if blocked else None,
        "blocked_fraction_max": blocked[-1] if blocked else None,
        "inside_0_65_stop_band_fraction_median": tight[len(tight) // 2] if tight else None,
        "inside_0_65_stop_band_fraction_max": tight[-1] if tight else None,
    }


def main() -> None:
    data = load()
    if not data:
        raise SystemExit("no rows found; run run.py first")
    index = json.loads((RAW / "index.json").read_text()) if (RAW / "index.json").is_file() else {}
    # Sweep A's index carries the determinism proof and its own arm facts; the
    # last run to finish owns index.json, so both are merged here.
    idx_a = (json.loads((RAW / "index_sweepA.json").read_text())
             if (RAW / "index_sweepA.json").is_file() else {})
    facts = dict(idx_a.get("arm_config_facts") or {})
    facts.update(index.get("arm_config_facts") or {})
    index["arm_config_facts"] = facts
    index.setdefault("determinism", idx_a.get("determinism"))
    if idx_a.get("determinism"):
        index["determinism"] = idx_a["determinism"]
    index["host_start_sweepA"] = idx_a.get("host_start")
    index["host_end_sweepA"] = idx_a.get("host_end")
    scenes = json.loads((RAW / "scenes.json").read_text()) if (RAW / "scenes.json").is_file() else {}
    gen_a0, _ = split(data["A0"]["rows"])
    out = {
        "probe": "NAV-GEN-1",
        "evidence_tier": "desktop-sim",
        "seed": index.get("seed"),
        "host_start": index.get("host_start"),
        "host_end": index.get("host_end"),
        "determinism": index.get("determinism"),
        "host_start_sweepA": index.get("host_start_sweepA"),
        "host_end_sweepA": index.get("host_end_sweepA"),
        "arm_config_facts": index.get("arm_config_facts"),
        "episode_set": EP.summary(),
        "scene_manifest_sha256": scenes.get("manifest", {}).get("manifest_sha256"),
        "scene_params": scenes.get("params"),
        "arms_run": {name: {"episodes": len(d["rows"])} for name, d in data.items()},
        "H_NG1a": h_ng1a(gen_a0),
        "H_NG1a_any_instance_oracle": h_ng1a(gen_a0, "strict_success_any_instance"),
        "H_NG1a_excluding_crosswalk": h_ng1a([r for r in gen_a0 if r["target"] != "crosswalk"]),
        "H_NG1a_all_arms": {name: h_ng1a(split(d["rows"])[0]) for name, d in data.items()},
        "H_NG1b": h_ng1b(data),
        "H_NG1c": h_ng1c(data),
        "ma1_reconciliation": ma1_reconciliation(data),
        "per_target_generated_A0": per_target(data),
        "goal_clearance_vs_outcome_A0": scene_correlation(data),
        "unreachable_diagnosis_A0": unreachable_diagnosis(data),
        "scene_facts_summary_A0": scene_facts_summary(data),
        "plumbing_control_A0_vs_A0c_identical": (
            json.dumps(data["A0"]["rows"], sort_keys=True)
            == json.dumps([dict(r, arm="A0") for r in data["A0c"]["rows"]], sort_keys=True)
            if "A0c" in data else None),
    }
    (HERE / "results.json").write_text(json.dumps(out, indent=2))
    (HERE / "tables.md").write_text(markdown(out) + "\n")
    print(json.dumps({k: out[k] for k in
                      ("H_NG1a", "H_NG1a_any_instance_oracle",
                       "H_NG1a_excluding_crosswalk", "H_NG1b", "H_NG1c",
                       "ma1_reconciliation",
                       "per_target_generated_A0", "goal_clearance_vs_outcome_A0",
                       "unreachable_diagnosis_A0",
                       "plumbing_control_A0_vs_A0c_identical", "determinism")},
                     indent=2, default=str))


if __name__ == "__main__":
    main()
