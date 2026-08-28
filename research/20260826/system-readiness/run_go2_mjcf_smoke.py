"""Reproducible articulated-asset smoke for the tracked official Go2 MJCF.

This is deliberately below the SDK2/DDS and controller layers.  It proves that
the pinned model can be parsed and stepped by the repository environment; it
does not command a gait, exercise Parcel's gateway, or support a physical claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import struct
import time
from pathlib import Path

import mujoco

REPO = Path(__file__).resolve().parents[3]
SCENE = REPO / "third_party/unitree_mujoco/unitree_robots/go2/scene.xml"
MODEL = REPO / "third_party/unitree_mujoco/unitree_robots/go2/go2.xml"
NONDETERMINISTIC_FIELDS = frozenset({"load_ms"})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state_digest(data: mujoco.MjData) -> str:
    values = tuple(float(value) for value in data.qpos) + tuple(
        float(value) for value in data.qvel
    )
    return hashlib.sha256(struct.pack(f"<{len(values)}d", *values)).hexdigest()


def run(*, steps: int = 1_000) -> dict[str, object]:
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 100_000:
        raise ValueError("steps must be an integer within [1, 100000]")
    started = time.perf_counter()
    model = mujoco.MjModel.from_xml_path(str(SCENE))
    load_ms = (time.perf_counter() - started) * 1_000.0
    data = mujoco.MjData(model)
    if model.nkey:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)
    for _ in range(steps):
        mujoco.mj_step(model, data)
    finite = all(math.isfinite(float(value)) for value in data.qpos) and all(
        math.isfinite(float(value)) for value in data.qvel
    )
    result: dict[str, object] = {
        "schema": "parcel.go2_mjcf_smoke.v1",
        "evidence_tier": "desktop-articulated-simulation-asset-smoke",
        "scene": str(SCENE.relative_to(REPO)),
        "scene_sha256": _sha256(SCENE),
        "model_sha256": _sha256(MODEL),
        "python": platform.python_version(),
        "mujoco": mujoco.__version__,
        "load_ms": round(load_ms, 3),
        "steps": steps,
        "simulated_seconds": round(float(data.time), 9),
        "nq": int(model.nq),
        "nv": int(model.nv),
        "nu": int(model.nu),
        "nsensor": int(model.nsensor),
        "finite": finite,
        "state_sha256": _state_digest(data),
        "claim_ceiling": (
            "Tracked MJCF parse/finite-step evidence only; no SDK2/DDS, learned policy, "
            "gateway, contact-safety, Orin, or physical-Go2 claim."
        ),
    }
    if not finite:
        raise RuntimeError("Go2 MJCF produced a non-finite state")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=1_000)
    destinations = parser.add_mutually_exclusive_group()
    destinations.add_argument("--output", type=Path)
    destinations.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = run(steps=args.steps)
    research_root = Path(__file__).resolve().parent
    if args.verify is not None:
        source = args.verify.resolve()
        if source.parent != research_root:
            raise ValueError("verification artifact must be a direct child of system-readiness")
        expected = json.loads(source.read_text(encoding="utf-8"))
        stable_result = {
            key: value for key, value in result.items() if key not in NONDETERMINISTIC_FIELDS
        }
        stable_expected = {
            key: value for key, value in expected.items() if key not in NONDETERMINISTIC_FIELDS
        }
        if stable_result != stable_expected:
            raise RuntimeError("stored Go2 MJCF smoke artifact did not reproduce")
        result["verification"] = "stable fields reproduced; load_ms intentionally excluded"
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        target = args.output.resolve()
        if target.parent != research_root:
            raise ValueError("output must be a direct child of system-readiness")
        target.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
