"""NM-1 row W — the veto through the PRODUCT path, now via the bureau.

Same fixture, same policy and same product entry point P1-D measured
(``OnlineSemanticMap.resolve`` -> ``assess_place_query`` -> ``resolve_veto``),
with one thing changed: the callable the gate gets is the bureau's board reader.

Two passes, deliberately:
  pass 1 — nothing is published yet, so every query is an ASK and every query
           schedules a job. This is the new behaviour and it is the point.
  pass 2 — after the worker has caught up, the verdicts are consumed.
No monkeypatch anywhere; the seat is the real Qwen3-VL-2B.
"""
import collections
import json
import os
import sys
import threading
import time

REPO = "/home/jaewoo-jang/Desktop/Projects/Parcel"
sys.path.insert(0, REPO + "/src")
sys.path.insert(0, REPO + "/tests")
os.environ.setdefault("PARCEL_VLM_WEIGHTS", sys.argv[1] if len(sys.argv) > 1 else "")

from test_p1d_eval_rows import ABSENT, _build_map, _prototype_policy

from parcel_robot.perception_abstention import (
    clear_veto_cache,
    in_control_thread,
    resolve_veto,
)
from parcel_robot.vlm_veto.bureau import bureau_for, clear_bureaus

MAIN = threading.get_ident()

policy = _prototype_policy()
clear_veto_cache()
clear_bureaus()
seat = resolve_veto(policy)
bureau = bureau_for(policy.veto_model)
print("resolved seat :", getattr(bureau.runner.verifier, "name", None))
print("callable is the board reader:", seat.__self__ is bureau)
print("main thread is a control loop:", in_control_thread())

smap, present = _build_map(policy)
queries = list(present) + list(ABSENT)


def sweep(tag):
    rows = []
    started = time.perf_counter()
    for q in queries:
        v = smap.resolve(q).verdict
        rows.append({
            "query": q,
            "set": "present" if q in present else "absent",
            "outcome": v.outcome,
            "admitted": v.admitted,
            "reason": v.reason,
            "candidate": v.candidate,
            "p_yes": dict(v.signals).get("veto_p_yes"),
        })
    wall_ms = (time.perf_counter() - started) * 1000.0
    c = collections.Counter(r["outcome"] for r in rows)
    pres = [r for r in rows if r["set"] == "present"]
    abst = [r for r in rows if r["set"] == "absent"]
    summary = {
        "pass_": tag,
        "admit": c["admit"],
        "ask": c["ask"],
        "refuse": c["refuse"],
        "present_admitted": sum(r["admitted"] for r in pres),
        "present_n": len(pres),
        "absent_admitted": sum(r["admitted"] for r in abst),
        "absent_n": len(abst),
        "ask_rate": round(c["ask"] / len(rows), 4),
        "wall_ms_for_all_queries": round(wall_ms, 2),
        "mean_ms_per_resolve": round(wall_ms / len(rows), 3),
        "bureau": bureau.counts(),
        "veto": bureau.runner.stats(),
    }
    print(f"PASS {tag}:", json.dumps(summary))
    return summary, rows


first, rows_first = sweep("1-cold-board")
assert bureau.drain(timeout=120.0), "the worker did not catch up"
second, rows_second = sweep("2-published")

# The safety property, measured rather than asserted in a test: which thread
# did the model actually answer on?
threads = set(getattr(bureau.runner, "_threads", ()) or ())
print("worker never ran on the caller's thread:", MAIN not in threads or not threads)

with open(
    "/home/jaewoo-jang/.cache/parcel-nm1/evidence/product_bureau.json", "w"
) as handle:
    json.dump(
        {
            "pass1": first,
            "pass2": second,
            "rows_pass1": rows_first,
            "rows_pass2": rows_second,
        },
        handle,
        indent=1,
    )
print("wrote product_bureau.json")
clear_bureaus()
