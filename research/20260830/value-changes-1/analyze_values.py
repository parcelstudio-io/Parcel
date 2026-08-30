"""VALUE-CHANGES-MEASURED-1 (card W6) — every table in RESULTS.md.

Reads the raw arm rows (NAV-GEN-1) and the frozen-corpus payloads (v4 minival +
mutation panel) this card's ``values_harness.py`` wrote into scratch, and emits
``results.json`` + ``tables.md``.  No number in ``RESULTS.md`` is typed by hand.

    env -u TMPDIR PYTHONPATH=<wt>/src:<wt> .parcel/bin/python \
      research/20260830/value-changes-1/analyze_values.py --out <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from pathlib import Path

SCRATCH = Path(os.environ.get("W6_SCRATCH", Path.home() / ".cache/parcel-0e/w6"))
NG1_SCRATCH = Path(os.environ.get("NG1_SCRATCH", SCRATCH / "ng1"))
RAW = NG1_SCRATCH / "raw"
FROZEN = SCRATCH / "frozen"

ARMS = ["A0ref", "off_disc", "on_disc", "off_full", "on_full"]
BASE = "off_disc"          # the licensed baseline arm (scratch tree, both values OFF)
REF = "A0ref"              # the repo config path itself

HEAD_MINIVAL_DIGEST = "021b67ab73c4e7be647aba1a17e20a193ebf23b826a18d5b0990e296e5708496"
STOP_BAND_M = 0.65

#: Panel-payload keys that identify the RUN, not its outcome: the wall-clock
#: stamp and the two fields this card's own driver adds (its scratch path and
#: its wall time). Everything else in the payload is a measurement.
PANEL_RUN_IDENTITY = frozenset({"generated_at", "file", "wall_s"})


def load_rows(arm: str) -> list[dict]:
    return json.loads((RAW / f"w6_rows_{arm}.json").read_text())["rows"]


def is_poi(row: dict) -> bool:
    """A mission the POI table answered, not the semantic ladder.

    C3 sec. 1.1's "non-POI" class is the ladder's, not a target-name class; the
    per-row ``goal_source`` (card C2) is the product's own answer.  The
    pre-registered target-name split is reported beside it.
    """

    return str(row.get("goal_source") or "") == "known_poi"


def block_stats(rows: list[dict]) -> dict:
    n = len(rows)
    reasons: dict[str, int] = {}
    for r in rows:
        key = str(r.get("reason") or "<none>")
        reasons[key] = reasons.get(key, 0) + 1
    stalls = [r for r in rows if r.get("reason") == "navigation_no_progress"]
    steps = [int(r["steps"]) for r in rows]
    below = [
        r
        for r in rows
        if r.get("minimum_clearance_m") is not None
        and float(r["minimum_clearance_m"]) < STOP_BAND_M
    ]
    goal_sources: dict[str, int] = {}
    for r in rows:
        key = str(r.get("goal_source") or "<none>")
        goal_sources[key] = goal_sources.get(key, 0) + 1
    return {
        "episodes": n,
        "strict_success": sum(1 for r in rows if r["strict_success"]),
        "strict_success_any_instance": sum(
            1 for r in rows if r["strict_success_any_instance"]
        ),
        "settled_success": sum(1 for r in rows if r.get("settled_success")),
        "settled": sum(1 for r in rows if r.get("settled")),
        "arrived_verified": sum(1 for r in rows if r.get("arrived_verified")),
        "band_entry": sum(1 for r in rows if r.get("band_entry")),
        "band_entry_any_instance": sum(
            1 for r in rows if r.get("band_entry_any_instance")
        ),
        "false_arrival": sum(1 for r in rows if r.get("false_arrival")),
        "wrong_instance": sum(1 for r in rows if r.get("wrong_instance")),
        "reason_histogram": dict(sorted(reasons.items())),
        "navigation_no_progress": len(stalls),
        "stall_non_poi_by_goal_source": sum(1 for r in stalls if not is_poi(r)),
        "stall_poi_by_goal_source": sum(1 for r in stalls if is_poi(r)),
        "stall_non_crosswalk_target": sum(
            1 for r in stalls if r.get("target") != "crosswalk"
        ),
        "semantic_target_unreachable": reasons.get("semantic_target_unreachable", 0),
        "collisions_total": sum(int(r["collision_count"]) for r in rows),
        "episodes_with_collision": sum(1 for r in rows if int(r["collision_count"]) > 0),
        "episodes_below_stop_band": len(below),
        "episodes_below_stop_band_ids": sorted(r["episode_id"] for r in below),
        "min_clearance_min_m": min(
            (
                float(r["minimum_clearance_m"])
                for r in rows
                if r.get("minimum_clearance_m") is not None
            ),
            default=None,
        ),
        "steps_total": sum(steps),
        "steps_median": statistics.median(steps) if steps else None,
        "planned_without_terminal_reason": sum(
            1
            for r in rows
            if str(r.get("status")) == "planned" and not str(r.get("reason") or "")
        ),
        "goal_source_histogram": dict(sorted(goal_sources.items())),
    }


def arm_stats(rows: list[dict]) -> dict:
    gen = [r for r in rows if r["block"] == "generated"]
    fro = [r for r in rows if r["block"] == "frozen"]
    return {
        "all": block_stats(rows),
        "generated": block_stats(gen),
        "frozen": block_stats(fro),
    }


#: The one row field that is the ARM'S OWN NAME, not an outcome. Comparing it
#: across arms would make every row differ by construction (and did, in the
#: first pass of this analysis — caught by the plumbing control reading 0/530
#: identical for two arms whose every aggregate matched).
ROW_IDENTITY_FIELDS = frozenset({"arm"})


def outcome(row: dict) -> str:
    return json.dumps(
        {k: v for k, v in row.items() if k not in ROW_IDENTITY_FIELDS}, sort_keys=True
    )


def compare(base_rows: list[dict], arm_rows: list[dict]) -> dict:
    b = {r["episode_id"]: r for r in base_rows}
    a = {r["episode_id"]: r for r in arm_rows}
    assert set(b) == set(a), "episode sets differ between arms"
    changed, reason_changed = [], []
    strict_reg, strict_gain = [], []
    settled_reg, settled_gain = [], []
    for k in sorted(b):
        if outcome(b[k]) != outcome(a[k]):
            changed.append(k)
        if b[k].get("reason") != a[k].get("reason"):
            reason_changed.append(
                {"episode_id": k, "from": b[k].get("reason"), "to": a[k].get("reason")}
            )
        if b[k]["strict_success"] and not a[k]["strict_success"]:
            strict_reg.append(k)
        if a[k]["strict_success"] and not b[k]["strict_success"]:
            strict_gain.append(k)
        if b[k].get("settled_success") and not a[k].get("settled_success"):
            settled_reg.append(k)
        if a[k].get("settled_success") and not b[k].get("settled_success"):
            settled_gain.append(k)
    transitions: dict[str, int] = {}
    for item in reason_changed:
        key = f"{item['from']} -> {item['to']}"
        transitions[key] = transitions.get(key, 0) + 1
    return {
        "rows_changed_full_row": len(changed),
        "rows_identical": len(b) - len(changed),
        "rows_changed_reason_only_count": len(reason_changed),
        "reason_transitions": dict(
            sorted(transitions.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "strict_regressions": strict_reg,
        "strict_gains": strict_gain,
        "settled_regressions": settled_reg,
        "settled_gains": settled_gain,
        "changed_episode_ids": changed,
    }


def frozen_payload(arm: str) -> dict:
    return json.loads((FROZEN / arm / "frozen.json").read_text())


def minival_moves(base: dict, arm: dict) -> dict:
    b = {e["episode_id"]: e for e in base["minival"]["episodes"]}
    a = {e["episode_id"]: e for e in arm["minival"]["episodes"]}
    moved = []
    for k in sorted(b):
        if json.dumps(b[k], sort_keys=True) == json.dumps(a[k], sort_keys=True):
            continue
        bt, at = b[k]["trace"], a[k]["trace"]
        moved.append(
            {
                "episode_id": k,
                "family": b[k]["family"],
                "tier": b[k]["tier"],
                "frozen_rule_success": [
                    b[k].get("frozen_rule_success"),
                    a[k].get("frozen_rule_success"),
                ],
                "success": [b[k]["score"].get("success"), a[k]["score"].get("success")],
                "failure": [b[k]["score"].get("failure"), a[k]["score"].get("failure")],
                "reason": [b[k].get("reason"), a[k].get("reason")],
                "authority_category": [
                    b[k].get("authority_category"),
                    a[k].get("authority_category"),
                ],
                "distance_to_goal_m": [
                    b[k]["score"].get("distance_to_goal_m"),
                    a[k]["score"].get("distance_to_goal_m"),
                ],
                "trace_len": [b[k].get("trace_len"), a[k].get("trace_len")],
                "final_xy": [
                    [round(float(bt[-1].get("x", 0.0)), 4), round(float(bt[-1].get("y", 0.0)), 4)],
                    [round(float(at[-1].get("x", 0.0)), 4), round(float(at[-1].get("y", 0.0)), 4)],
                ],
                "verdict_moved": bool(
                    b[k]["score"].get("success") != a[k]["score"].get("success")
                    or b[k]["score"].get("failure") != a[k]["score"].get("failure")
                ),
            }
        )
    return {"moved_row_count": len(moved), "moved_rows": moved}


def panel_summary(payload: dict, base: dict | None) -> dict:
    p = payload["panel"]
    out = {
        "generated_at": p["generated_at"],
        "passed": p["passed"],
        "survivors": p["survivors"],
        "equivalent_mutants": p["equivalent_mutants"],
        "clean_authority": p["clean_run"]["authority"],
        "clean_mean_dtg_m": p["clean_run"]["mean_dtg_m"],
        "clean_collisions": p["clean_run"]["collisions"],
        "clean_successes": p["clean_run"]["successes"],
        "clean_failure_histogram": p["clean_run"]["failure_histogram"],
        "clean_checks": p["clean_checks"],
        "mutants": {
            m["mutation"]: {
                "verdict": m["verdict"],
                "kill_channels": m["kill_channels"],
                "checks_reddened": m["checks_reddened"],
            }
            for m in p["mutants"]
        },
        "clean_episode_min_clearance_m": {
            e["episode_id"]: e["min_clearance_m"] for e in p["clean_run"]["episodes"]
        },
    }
    if base is not None:
        bp = base["panel"]
        def strip(d):
            return json.dumps(
                {k: v for k, v in d.items() if k not in PANEL_RUN_IDENTITY}, sort_keys=True
            )
        out["identical_to_reference_panel"] = strip(p) == strip(bp)
        moved = []
        for eb, ea in zip(bp["clean_run"]["episodes"], p["clean_run"]["episodes"]):
            if json.dumps(eb, sort_keys=True) != json.dumps(ea, sort_keys=True):
                moved.append(
                    {
                        "episode_id": eb["episode_id"],
                        "success": [eb["success"], ea["success"]],
                        "failure": [eb["failure"], ea["failure"]],
                        "min_clearance_m": [eb["min_clearance_m"], ea["min_clearance_m"]],
                        "final_xy": [eb["final_xy"], ea["final_xy"]],
                        "path_length_m": [eb["path_length_m"], ea["path_length_m"]],
                    }
                )
        out["clean_rows_moved"] = moved
        out["clean_rows_moved_count"] = len(moved)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()

    rows = {a: load_rows(a) for a in ARMS}
    frozen = {a: frozen_payload(a) for a in ARMS}
    index = json.loads((RAW / "w6_index.json").read_text())

    results: dict = {
        "card": "W6 VALUE-CHANGES-MEASURED-1",
        "design": "research/20260830/value-changes-1/DESIGN.md (FROZEN 2026-08-30 06:43 EDT)",
        "evidence_tier": "desktop-sim",
        "physical_motion": "NO-GO (unchanged)",
        "hosted_spend_usd": 0,
        "product_edit": False,
        "arms": {
            "A0ref": "door OFF, planner 1.0223 m — the repo config path, untouched",
            "off_disc": "door OFF, planner 1.0223 m — scratch tree (baseline)",
            "on_disc": "door ON,  planner 1.0223 m — V1 alone",
            "off_full": "door OFF, planner 1.12 m   — V2 alone",
            "on_full": "door ON,  planner 1.12 m   — V1 + V2",
        },
        "arm_facts": index["arm_facts"],
        "run_provenance": index["run_provenance"],
        "host_start": index["host_start"],
        "host_end": index.get("host_end"),
        "ng1_wall_s": {a: index["arms"][a]["wall_s"] for a in ARMS},
    }

    # --- the plumbing control -----------------------------------------------
    ident = [outcome(r) for r in rows[REF]] == [outcome(r) for r in rows[BASE]]
    results["plumbing_control"] = {
        "claim": "off_disc (scratch config tree at the commissioned values) reproduces "
        "A0ref (the repo config path) byte-identically on all 530 rows",
        "rows_compared": len(rows[REF]),
        "byte_identical": ident,
        "minival_digest_identical": (
            frozen[REF]["minival"]["report_digest"]
            == frozen[BASE]["minival"]["report_digest"]
        ),
        "panel_identical": panel_summary(frozen[BASE], frozen[REF])[
            "identical_to_reference_panel"
        ],
        "licensed": ident,
    }

    results["ng1"] = {a: arm_stats(rows[a]) for a in ARMS}
    results["ng1_vs_baseline"] = {
        a: {
            "all": compare(rows[BASE], rows[a]),
            "generated": compare(
                [r for r in rows[BASE] if r["block"] == "generated"],
                [r for r in rows[a] if r["block"] == "generated"],
            ),
            "frozen": compare(
                [r for r in rows[BASE] if r["block"] == "frozen"],
                [r for r in rows[a] if r["block"] == "frozen"],
            ),
        }
        for a in ARMS
        if a != BASE
    }

    results["minival"] = {
        a: {
            "report_digest": frozen[a]["minival"]["report_digest"],
            "matches_HEAD_021b67ab": frozen[a]["minival"]["report_digest"]
            == HEAD_MINIVAL_DIGEST,
            "episode_digest": frozen[a]["minival"]["episode_digest"],
            "sr": frozen[a]["minival"]["aggregate"]["sr"],
            "sr_frozen_rule": frozen[a]["minival"]["aggregate"]["sr_frozen_rule"],
            "spl": frozen[a]["minival"]["aggregate"]["spl"],
            "mean_dtg_m": frozen[a]["minival"]["aggregate"]["mean_dtg_m"],
            "collision_total": frozen[a]["minival"]["aggregate"]["collision_total"],
            "authority_histogram": frozen[a]["minival"]["aggregate"]["authority_histogram"],
            "failure_histogram": frozen[a]["minival"]["aggregate"]["failure_histogram"],
            "moves_vs_A0ref": minival_moves(frozen[REF], frozen[a]),
            "wall_s": frozen[a]["minival"]["wall_s"],
        }
        for a in ARMS
    }
    results["panel"] = {
        a: panel_summary(frozen[a], frozen[REF] if a != REF else None) for a in ARMS
    }
    results["panel"][REF]["identical_to_reference_panel"] = True
    results["panel"][REF]["clean_rows_moved"] = []
    results["panel"][REF]["clean_rows_moved_count"] = 0

    out = args.out / "results.json"
    out.write_text(json.dumps(results, indent=2, sort_keys=False) + "\n")
    print(f"wrote {out}")

    # --- the decision table, rendered ---------------------------------------
    lines: list[str] = []
    A = ARMS

    def row(label: str, vals, bold=False):
        cells = " | ".join(str(v) for v in vals)
        lines.append(f"| {'**' + label + '**' if bold else label} | {cells} |")

    lines.append("## T1 — NAV-GEN-1 A0, generated block (450 episodes)")
    lines.append("")
    lines.append("| row | " + " | ".join(A) + " |")
    lines.append("|---|" + "---|" * len(A))
    g = {a: results["ng1"][a]["generated"] for a in A}
    for label, key in [
        ("strict success (MA-1 single-instance oracle)", "strict_success"),
        ("strict success, any legal instance", "strict_success_any_instance"),
        ("settled success", "settled_success"),
        ("`arrived_verified`", "arrived_verified"),
        ("band entry (strict instance)", "band_entry"),
        ("band entry, any instance", "band_entry_any_instance"),
        ("`navigation_no_progress` (all)", "navigation_no_progress"),
        ("… non-POI (goal_source != known_poi)", "stall_non_poi_by_goal_source"),
        ("… POI (goal_source == known_poi)", "stall_poi_by_goal_source"),
        ("… non-crosswalk target (pre-registered split)", "stall_non_crosswalk_target"),
        ("`semantic_target_unreachable`", "semantic_target_unreachable"),
        ("false arrivals", "false_arrival"),
        ("wrong instance", "wrong_instance"),
        ("**collisions**", "collisions_total"),
        ("**episodes with `minimum_clearance_m` < 0.65 m**", "episodes_below_stop_band"),
        ("steps (total)", "steps_total"),
        ("steps (median)", "steps_median"),
        ("rows `status=planned` with no terminal reason (A1)", "planned_without_terminal_reason"),
    ]:
        row(label, [g[a][key] for a in A])
    lines.append("")

    lines.append("## T2 — NAV-GEN-1 A0, frozen demo block (80 episodes)")
    lines.append("")
    lines.append("| row | " + " | ".join(A) + " |")
    lines.append("|---|" + "---|" * len(A))
    f = {a: results["ng1"][a]["frozen"] for a in A}
    for label, key in [
        ("strict success", "strict_success"),
        ("`arrived_verified`", "arrived_verified"),
        ("`navigation_no_progress`", "navigation_no_progress"),
        ("`semantic_target_unreachable`", "semantic_target_unreachable"),
        ("false arrivals", "false_arrival"),
        ("**collisions**", "collisions_total"),
        ("**episodes < 0.65 m**", "episodes_below_stop_band"),
        ("steps (total)", "steps_total"),
    ]:
        row(label, [f[a][key] for a in A])
    lines.append("")

    lines.append("## T3 — rows moved vs `off_disc` (full-row comparison, 530 episodes)")
    lines.append("")
    lines.append("| row | " + " | ".join(a for a in A if a != BASE) + " |")
    lines.append("|---|" + "---|" * (len(A) - 1))
    cmp_all = results["ng1_vs_baseline"]
    others = [a for a in A if a != BASE]
    row("rows changed (full row)", [cmp_all[a]["all"]["rows_changed_full_row"] for a in others])
    row("rows byte-identical", [cmp_all[a]["all"]["rows_identical"] for a in others])
    row("rows with a changed terminal reason", [cmp_all[a]["all"]["rows_changed_reason_only_count"] for a in others])
    row("strict regressions", [len(cmp_all[a]["all"]["strict_regressions"]) for a in others])
    row("strict gains", [len(cmp_all[a]["all"]["strict_gains"]) for a in others])
    row("frozen-block rows changed", [cmp_all[a]["frozen"]["rows_changed_full_row"] for a in others])
    lines.append("")

    lines.append("## T4 — the v4 minival (25 episodes, frozen corpus)")
    lines.append("")
    lines.append("| row | " + " | ".join(A) + " |")
    lines.append("|---|" + "---|" * len(A))
    m = results["minival"]
    row("report digest (first 16)", [f"`{m[a]['report_digest'][:16]}…`" for a in A])
    row("= HEAD `021b67ab…`", ["**yes**" if m[a]["matches_HEAD_021b67ab"] else "**NO**" for a in A])
    row("`episode_digest` (first 16)", [f"`{str(m[a]['episode_digest'])[:16]}…`" for a in A])
    row("SR", [m[a]["sr"] for a in A])
    row("SR (frozen rule)", [m[a]["sr_frozen_rule"] for a in A])
    row("SPL", [round(m[a]["spl"], 6) for a in A])
    row("mean DTG (m)", [round(m[a]["mean_dtg_m"], 6) for a in A])
    row("collisions", [m[a]["collision_total"] for a in A])
    row("authority disagreements", [m[a]["authority_histogram"]["authority_disagreement"] for a in A])
    row("rows moved vs A0ref", [m[a]["moves_vs_A0ref"]["moved_row_count"] for a in A])
    row("rows whose VERDICT moved", [sum(1 for x in m[a]["moves_vs_A0ref"]["moved_rows"] if x["verdict_moved"]) for a in A])
    lines.append("")

    lines.append("## T5 — the mutation panel")
    lines.append("")
    lines.append("| row | " + " | ".join(A) + " |")
    lines.append("|---|" + "---|" * len(A))
    p = results["panel"]
    row("`passed`", [p[a]["passed"] for a in A])
    row("survivors", [p[a]["survivors"] or "—" for a in A])
    row("equivalent mutants", [p[a]["equivalent_mutants"] or "—" for a in A])
    row("clean authority", [json.dumps(p[a]["clean_authority"]) for a in A])
    row("clean mean DTG (m)", [round(p[a]["clean_mean_dtg_m"], 6) for a in A])
    row("clean collisions", [p[a]["clean_collisions"] for a in A])
    row("panel identical to A0ref", [p[a]["identical_to_reference_panel"] for a in A])
    row("clean rows moved", [p[a]["clean_rows_moved_count"] for a in A])
    lines.append("")
    lines.append("### T5b — kill channels per mutant")
    lines.append("")
    lines.append("| mutant | " + " | ".join(A) + " |")
    lines.append("|---|" + "---|" * len(A))
    for name in p[REF]["mutants"]:
        row(f"`{name}`", [f"{p[a]['mutants'][name]['verdict']} / {p[a]['mutants'][name]['kill_channels']}" for a in A])
    lines.append("")

    (args.out / "tables.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {args.out / 'tables.md'}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
