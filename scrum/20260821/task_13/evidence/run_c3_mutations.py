#!/usr/bin/env python
"""C-3 seeded-defect harness.

Protocol, per the register (C-1 seed-8 and C-2 §7 lessons, both applied):

* **fresh-interpreter canary before seeding** — the suite must be green in a
  brand-new interpreter first, or a "RED" result proves nothing.
* **``__pycache__`` purged before every cell**, so a stale ``.pyc`` cannot
  serve the unseeded module to the seeded run.
* **anchor uniqueness checked** — a seed whose anchor appears 0 or 2+ times is
  reported as ``anchor_error`` and never silently skipped. A seed that fails to
  apply and "passes" is worse than no seed.
* **restore in a ``finally``, SHA-verified** against the pre-seed bytes.
* **a hang counts RED-by-timeout**, not as an error to be re-run.
* **final sweep after the last source write**, plus a repo-root stray sweep.

Usage:  .parcel/bin/python scrum/20260821/task_13/evidence/run_c3_mutations.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PY = REPO / ".parcel" / "bin" / "python"
SUITE = "tests/test_c3_cutover.py"
TIMEOUT_S = 300

SRC = REPO / "src" / "parcel_robot"
SEL = SRC / "perception_source" / "selection.py"
SHADOW = SRC / "perception_source" / "shadow.py"
SEMMAP = SRC / "navigation" / "semantic_map.py"
GROUNDER = SRC / "navigation" / "grounder.py"
PIPELINE = SRC / "navigation" / "pipeline.py"
RUNTIME = SRC / "runtime.py"


@dataclass(frozen=True)
class Seed:
    number: int
    name: str
    property_broken: str
    path: Path
    anchor: str
    replacement: str


SEEDS: tuple[Seed, ...] = (
    Seed(
        1,
        "T1 stamps a fake confidence",
        "the oracle's 0.98-by-fiat returns under a new name",
        SEMMAP,
        "    value = purity * saturation",
        "    value = 0.98  # SEED",
    ),
    Seed(
        2,
        "shadow divergence unlogged",
        "the migration instrument records nothing",
        SHADOW,
        "        self.divergences.append(divergence)",
        "        pass  # SEED",
    ),
    Seed(
        3,
        "rows 10-13 admit under T1 (empty map fails open)",
        "'go to Narnia' returns the moment the label set is gone",
        RUNTIME,
        "            and self._learned_map_vocabulary() is not None\n",
        "            and False  # SEED\n",
    ),
    Seed(
        4,
        "safety reads the semantic source",
        "the tier moves the safety envelope",
        SRC / "navigation" / "reactive_safety.py",
        "from __future__ import annotations",
        "from __future__ import annotations\n\nfrom parcel_robot.perception_source import active_semantic_source  # SEED",
    ),
    Seed(
        5,
        "T0 is not byte-identical (oracle routed through the map arm)",
        "the shipping default stops being the pre-C-3 read",
        SEMMAP,
        "    if source_policy is not None and source_policy.drives_from_learned_map:",
        "    if source_policy is not None and source_policy.reads_learned_map:  # SEED",
    ),
    Seed(
        6,
        "the POI table is re-enabled off-oracle",
        "a T1-only mission can pass by consulting a lookup table",
        GROUNDER,
        "            if not getattr(candidate, \"poi_grounding_enabled\", True):",
        "            if False:  # SEED",
    ),
    Seed(
        7,
        "the disabled POI arm still grounds",
        "the disable is a log line rather than a mechanism",
        GROUNDER,
        "        if self.disabled_reason:",
        "        if False:  # SEED",
    ),
    Seed(
        8,
        "the divergence taxonomy collapses two classes into one",
        "an admission flip and a benign miss become the same event",
        SHADOW,
        "REFUSAL_FLIP = \"refusal_flip\"",
        "REFUSAL_FLIP = \"benign_miss\"  # SEED",
    ),
    Seed(
        9,
        "agreement is reported without its denominators",
        "a rate with no n behind it re-enters the record",
        SHADOW,
        '            "n_total": self.total_comparisons,',
        "  # SEED",
    ),
    Seed(
        10,
        "a divergence is accepted without the frames that produced it",
        "divergence stops being re-examinable evidence",
        SHADOW,
        "        if not self.frames:",
        "        if False:  # SEED",
    ),
    Seed(
        11,
        "the tier and source axes are conflated ('T1' selects the map)",
        "a config that says T1 silently gets the oracle plus noise",
        SEL,
        '    if key == "t1":',
        '    if False:  # SEED',
    ),
    Seed(
        12,
        "an unestablished sensing envelope counts as comparable",
        "a forgetful harness inflates its own agreement denominator",
        SHADOW,
        "    if envelope is None or not oracle.admitted:\n        return False",
        "    if envelope is None:\n        return True  # SEED\n    if not oracle.admitted:\n        return False",
    ),
    Seed(
        13,
        "the learned-map source silently falls back to the oracle",
        "the cutover reports success while ground truth answers",
        SEMMAP,
        "    if active is None:\n        return []",
        "    if active is None:\n        return semantic_candidates_from_observation(observation)  # SEED",
    ),
    Seed(
        14,
        "an empty agreement class reports a perfect score",
        "n=0 flatters instead of abstaining",
        SHADOW,
        "        if self.total_comparisons == 0:\n            return None",
        "        if self.total_comparisons == 0:\n            return 1.0  # SEED",
    ),
    Seed(
        15,
        "the scene note keeps denying the robot has eyes under T1",
        "F12: the hosted model is instructed to deny a real capability",
        RUNTIME,
        "            SCENE_HONESTY_NOTE if learned_map is None else SCENE_HONESTY_NOTE_LEARNED_MAP",
        "            SCENE_HONESTY_NOTE  # SEED",
    ),
)


def purge_pycache() -> None:
    for directory in REPO.rglob("__pycache__"):
        if ".parcel" in directory.parts or ".git" in directory.parts:
            continue
        shutil.rmtree(directory, ignore_errors=True)


def run_suite() -> tuple[str, str]:
    """(outcome, detail). outcome in {green, red, timeout}."""

    env = dict(os.environ)
    env["PARCEL_MEMORY_PATH"] = ":memory:"
    try:
        proc = subprocess.run(
            [str(PY), "-m", "pytest", SUITE, "-q", "--no-header", "-p", "no:randomly"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "timeout", f"exceeded {TIMEOUT_S}s"
    tail = (proc.stdout or "").strip().splitlines()
    detail = tail[-1] if tail else ""
    return ("green" if proc.returncode == 0 else "red"), detail


def canary() -> dict[str, str]:
    purge_pycache()
    outcome, detail = run_suite()
    return {"outcome": outcome, "detail": detail}


def apply_seed(seed: Seed) -> tuple[bytes, str] | None:
    """Returns (original_bytes, sha) or None when the anchor is not unique."""

    original = seed.path.read_bytes()
    text = original.decode("utf-8")
    occurrences = text.count(seed.anchor)
    if occurrences != 1:
        return None
    seed.path.write_bytes(text.replace(seed.anchor, seed.replacement, 1).encode("utf-8"))
    return original, hashlib.sha256(original).hexdigest()


def main() -> int:
    started = time.time()
    results: list[dict[str, object]] = []

    canary_result = canary()
    if canary_result["outcome"] != "green":
        print(f"CANARY FAILED: {canary_result}", file=sys.stderr)
        return 2
    print(f"canary green: {canary_result['detail']}")

    for seed in SEEDS:
        purge_pycache()
        applied = apply_seed(seed)
        if applied is None:
            text = seed.path.read_text(encoding="utf-8")
            results.append(
                {
                    "seed": seed.number,
                    "name": seed.name,
                    "file": str(seed.path.relative_to(REPO)),
                    "outcome": "anchor_error",
                    "occurrences": text.count(seed.anchor),
                    "restored": True,
                }
            )
            print(f"  seed {seed.number:>2}: ANCHOR ERROR ({seed.name})")
            continue
        original, sha = applied
        try:
            outcome, detail = run_suite()
        finally:
            seed.path.write_bytes(original)
            restored = hashlib.sha256(seed.path.read_bytes()).hexdigest() == sha
            purge_pycache()
        results.append(
            {
                "seed": seed.number,
                "name": seed.name,
                "property_broken": seed.property_broken,
                "file": str(seed.path.relative_to(REPO)),
                "outcome": outcome,
                "detail": detail,
                "restored": restored,
                "pre_seed_sha256": sha,
            }
        )
        flag = {"red": "RED", "timeout": "RED (timeout)", "green": "GREEN — SEED SURVIVED"}[
            outcome
        ]
        print(f"  seed {seed.number:>2}: {flag:<22} restored={restored}  {seed.name}")

    # Final sweep, POSTDATING the last source write.
    purge_pycache()
    sweep_outcome, sweep_detail = run_suite()

    strays = sorted(
        path.name
        for path in REPO.iterdir()
        if path.is_file() and path.suffix in {".orig", ".rej", ".bak"}
    )

    red = sum(1 for row in results if row["outcome"] in {"red", "timeout"})
    restored_all = all(row.get("restored") for row in results)
    summary = {
        "card": "C-3",
        "suite": SUITE,
        "canary": canary_result,
        "seeds_total": len(SEEDS),
        "seeds_red": red,
        "all_restored": restored_all,
        "final_sweep": {"outcome": sweep_outcome, "detail": sweep_detail},
        "repo_root_strays": strays,
        "elapsed_s": round(time.time() - started, 1),
        "results": results,
    }
    out = Path(__file__).with_name("c3_mutation_results.json")
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        f"\n{red}/{len(SEEDS)} RED · all restored={restored_all} · "
        f"final sweep={sweep_outcome} ({sweep_detail}) · strays={strays or 'none'}"
    )
    ok = (
        red == len(SEEDS)
        and restored_all
        and sweep_outcome == "green"
        and not strays
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
