"""P1-D flag-off identity: HEAD's abstention gate vs P1-D's, verdict by verdict.

Loads ``git show HEAD:src/parcel_robot/perception_abstention.py`` side by side
with the worktree module in ONE interpreter and compares the six verdict fields
that existed before this card, over 50 synthetic rows x 3 entry paths.

Run:  .parcel/bin/python scrum/20260822/task_9/evidence/flag_off_identity.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]


def rows() -> list[dict]:
    out = []
    for i in range(50):
        out.append(
            {
                "query": f"q{i}",
                "asked": bool(i % 7),
                "frames_observed": i,
                "frames_fired": i // 2,
                "peak": min(1.0, (i % 11) / 10),
                "places": [
                    {"pid": f"p{j}", "label": f"l{j}", "ls": j, "dc": j + 1, "ef": j * 2,
                     "gef": min(1.0, j / 10), "sim": (j * 0.11) % 1.0}
                    for j in range(i % 5)
                ],
            }
        )
    return out


def verdicts(m, data) -> list[dict]:
    out = []
    for r in data:
        sup = m.DetectorSupport(
            term=r["query"], asked=r["asked"], frames_observed=r["frames_observed"],
            frames_fired=min(r["frames_fired"], r["frames_observed"]),
            peak_probability=r["peak"],
        )
        places = [
            m.PlaceEvidence(
                place_id=p["pid"], label=p["label"], x=1.0, y=2.0,
                label_support=p["ls"], detection_count=p["dc"],
                evidence_frames=p["ef"], ground_evidence_fraction=p["gef"],
                similarity=p["sim"],
            )
            for p in r["places"]
        ]
        for arm in (
            {"support": sup, "places": places},
            {"support": None, "places": places},
            {"support": sup, "places": ()},
        ):
            d = m.assess_place_query(r["query"], **arm).as_dict()
            # The six fields that existed before P1-D. `outcome`/`candidate`
            # are this card's additive keys and are reported separately.
            out.append({k: d[k] for k in
                        ("admitted", "query", "reason", "alternatives",
                         "place_id", "signals")})
    return out


def main() -> None:
    src = subprocess.run(
        ["git", "show", "HEAD:src/parcel_robot/perception_abstention.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    head = types.ModuleType("head_abstention")
    head.__file__ = "head_abstention.py"
    sys.modules["head_abstention"] = head
    exec(compile(src, "head_abstention", "exec"), head.__dict__)  # noqa: S102  evidence harness executes HEAD's module source by design

    sys.path.insert(0, str(REPO / "src"))
    import parcel_robot.perception_abstention as new

    data = rows()
    a, b = verdicts(head, data), verdicts(new, data)
    ha = hashlib.sha256(json.dumps(a, sort_keys=True).encode()).hexdigest()
    hb = hashlib.sha256(json.dumps(b, sort_keys=True).encode()).hexdigest()
    print(f"rows        : {len(a)}")
    print(f"HEAD  sha256: {ha}")
    print(f"P1-D  sha256: {hb}")
    print(f"IDENTICAL   : {ha == hb}")
    added = sorted(
        set(new.assess_place_query("x", support=None, places=()).as_dict())
        - set(head.assess_place_query("x", support=None, places=()).as_dict())
    )
    print(f"additive keys on as_dict(): {added}")
    print(f"DEFAULT_SIGNALS equal: {head.DEFAULT_SIGNALS == new.DEFAULT_SIGNALS}")
    print(f"default policy enabled: {new.AbstentionPolicy().enabled}")
    raise SystemExit(0 if ha == hb else 1)


if __name__ == "__main__":
    main()
