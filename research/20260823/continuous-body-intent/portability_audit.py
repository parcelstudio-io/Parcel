"""Row B8 — measure, don't argue: what did the second body cost in product code?

The claim is "a body nobody had in mind can be driven from the same stream with
zero product edits".  The way to check it is not to read the fake adapter but
to (a) hash the four product modules, (b) exercise the fake body through them,
and (c) hash again — plus record exactly which product symbols the fake adapter
imports, because an adapter that reaches past the contract into the composer's
internals would be evidence against portability even with the hashes intact.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import random
from pathlib import Path

from fake_quadruped_adapter import FAKE_QUADRUPED_MANIFEST, FakeQuadrupedAdapter

from parcel_robot.contracts.body_intent import degrade, is_no_stronger_than
from parcel_robot.models import VelocityCommand
from parcel_robot.motion.body_composer import BodyComposer
from parcel_robot.motion.expression import ExpressiveOffsets
from parcel_robot.simulation.body_adapter import SIM_BODY_MANIFEST

REPO = Path(__file__).resolve().parents[3]
PRODUCT_MODULES = (
    "src/parcel_robot/contracts/body_intent.py",
    "src/parcel_robot/motion/body_composer.py",
    "src/parcel_robot/simulation/body_adapter.py",
    "src/parcel_robot/control/go2_sport_body_adapter.py",
)
FAKE = Path(__file__).resolve().parent / "fake_quadruped_adapter.py"


def hashes() -> dict[str, str]:
    return {
        path: hashlib.sha256((REPO / path).read_bytes()).hexdigest() for path in PRODUCT_MODULES
    }


def physical_lines(path: Path) -> int:
    return len([line for line in path.read_text().splitlines() if line.strip()])


def product_imports(path: Path) -> dict[str, list[str]]:
    tree = ast.parse(path.read_text())
    found: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("parcel_robot"):
            found.setdefault(node.module or "", []).extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("parcel_robot"):
                    found.setdefault(alias.name, [])
    return {module: sorted(names) for module, names in sorted(found.items())}


def exercise(ticks: int, seed: int) -> dict[str, object]:
    """Drive the fake body from the real composer; check nothing was invented."""

    composer = BodyComposer()
    adapter = FakeQuadrupedAdapter()
    rng = random.Random(seed)
    violations = 0
    for tick in range(ticks):
        now = tick * 0.02
        command = None if tick % 200 < 60 else VelocityCommand(vx=rng.uniform(0.0, 0.5))
        intent = composer.compose(
            now_s=now,
            finalized_velocity=command,
            offsets=ExpressiveOffsets(
                body_height_m=0.004 * rng.uniform(-1, 1),
                body_pitch_rad=0.05 * rng.uniform(-1, 1),
                head_yaw_rad=0.4 * rng.uniform(-1, 1),
                head_pitch_rad=0.1 * rng.uniform(-1, 1),
            ),
        )
        adapter.apply(intent, now_s=now)
        if not is_no_stronger_than(degrade(intent, FAKE_QUADRUPED_MANIFEST), intent):
            violations += 1
    summary = adapter.summary()
    summary["degrade_violations"] = violations
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="H4 portability audit (row B8)")
    parser.add_argument("--ticks", type=int, default=30_000)
    parser.add_argument("--seed", type=int, default=20260823)
    parser.add_argument("--out", default="results/portability_audit.json")
    args = parser.parse_args()

    before = hashes()
    summary = exercise(args.ticks, args.seed)
    after = hashes()
    payload = {
        "fake_adapter_physical_loc": physical_lines(FAKE),
        "fake_adapter_total_lines": len(FAKE.read_text().splitlines()),
        "fake_adapter_product_imports": product_imports(FAKE),
        "product_modules_changed": sorted(k for k in before if before[k] != after[k]),
        "product_hashes": after,
        "manifests_differ": {
            "sim": SIM_BODY_MANIFEST.as_dict(),
            "fake_quadruped": FAKE_QUADRUPED_MANIFEST.as_dict(),
            "differing_fields": sorted(
                key
                for key, value in SIM_BODY_MANIFEST.as_dict().items()
                if FAKE_QUADRUPED_MANIFEST.as_dict()[key] != value
            ),
        },
        "run": summary,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
