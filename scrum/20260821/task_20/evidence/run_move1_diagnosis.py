"""MOVE-1 E2-D2 diagnosis harness — why doesn't the dog move?

Measurement M1 of ``MOVE1_PREREGISTRATION.md`` Part A: a per-tick trace of the
REAL dispatch chain inside a real runtime driving a real simulator over a real
socket, in three arms that differ from C-1's cell in exactly one axis each.

Nothing here edits product source. The trace is taken by wrapping three
INSTANCE attributes of the live runtime; every wrapper observes and forwards,
and none of them alters a value that the dispatch path then uses. The wrapping
is a deviation declared in the pre-registration (§A.4): there is no public
per-tick trace, and editing ``runtime.py`` is outside this card's OWNS.

A FRESH simulator per arm, for C-1's own reason: ``runtime.close()`` engages an
emergency stop that the simulator latches, and a shared simulator would hand
the next arm a latched e-stop and 0/N accepted motions.
"""

from __future__ import annotations

import os

os.environ.setdefault("MUJOCO_GL", "egl")

import argparse
import hashlib
import itertools
import json
import math
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

# Byte-identical to C-1's OFF config (run_c1_rerun_live.py), so the `replicate`
# arm differs from C-1's cell only in the instrumentation.
BASE_CONFIG = """
skills:
  root: {skills}
simulation:
  scene: {scene}
navigation:
  enabled: true
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
perception:
  spatial_sensors: [camera, lidar]
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cmd(command: object) -> dict[str, float] | None:
    if command is None:
        return None
    return {
        "vx": round(float(command.vx), 6),
        "vy": round(float(command.vy), 6),
        "vyaw": round(float(command.vyaw), 6),
    }


def _speed(command: object) -> float:
    if command is None:
        return 0.0
    return math.hypot(float(command.vx), float(command.vy))


def _directional_min(command: object, observation: object) -> float | None:
    """The distance the product's obstacle branch actually consults.

    Uses the gate's OWN ``_toward`` predicate rather than a re-implementation,
    so this cannot drift from the behaviour it is measuring.
    """

    from parcel_robot.navigation.reactive_safety import _toward

    if observation is None:
        return None
    if observation.lidar_obstacles:
        directional = [
            item
            for item in observation.lidar_obstacles
            if _toward(command, item.bearing_rad)
        ]
        if not directional:
            return None
        return round(min(item.distance_m for item in directional), 6)
    bearing = observation.nearest_obstacle_bearing_rad
    if bearing is None or _toward(command, bearing):
        return observation.nearest_obstacle_m
    return None


def instrument(runtime: object, trace: list[dict]) -> None:
    """Wrap three instance seams so every control tick leaves a row."""

    tick: dict[str, object] = {}

    real_current = runtime.arbiter.current
    real_collision_safe = runtime._collision_safe
    real_set_target = runtime.control_manager.set_target

    # Addendum A1b. ``_collision_safe`` is TWO stages: the geometric reactive
    # gate (``apply_reactive_safety``) and then the time-to-collision gate.
    # Without a seam between them, "the gate zeroed it" cannot say WHICH gate,
    # which is what left 94% of the static arm's ticks unattributed. Patching
    # the module attribute the runtime resolved at import time keeps this a
    # harness-process observation, not a source edit.
    import parcel_robot.runtime as runtime_module

    real_reactive = runtime_module.apply_reactive_safety

    def reactive(command, observation, **kwargs):
        result, state = real_reactive(command, observation, **kwargs)
        tick["post_reactive"] = _cmd(result)
        tick["reactive_state"] = state
        return result, state

    runtime_module.apply_reactive_safety = reactive

    def current(now=None, *args, **kwargs):
        active = real_current(now, *args, **kwargs)
        tick.clear()
        tick["wall"] = time.time()
        tick["intent"] = _cmd(active.command) if active is not None else None
        tick["intent_source"] = getattr(active, "source", None) if active else None
        return active

    def collision_safe(command, observation, **kwargs):
        tick["smoothed"] = _cmd(command)
        gated, proximity_state = real_collision_safe(command, observation, **kwargs)
        tick["gated"] = _cmd(gated)
        tick["proximity_state"] = proximity_state
        ttc = getattr(runtime, "_min_time_to_collision_s", None)
        tick["min_ttc_s"] = (
            None if ttc is None or ttc == float("inf") else round(float(ttc), 4)
        )
        if observation is not None:
            tick["obs"] = {
                # Addendum A1. The product gate does NOT use nearest_obstacle_m
                # when a lidar obstacle list is present: it takes the minimum
                # over obstacles its own ``_toward`` predicate accepts for THIS
                # command. Recording the omnidirectional nearest instead is what
                # made 94% of the first run's static-arm ticks unattributable.
                "obstacle_toward_m": _directional_min(command, observation),
                "x": round(float(observation.robot.x), 6),
                "y": round(float(observation.robot.y), 6),
                "yaw": round(float(observation.robot.yaw), 6),
                "person_m": observation.nearest_person_m,
                "person_bearing": observation.nearest_person_bearing_rad,
                "person_id": observation.nearest_person_id,
                "person_ttc_s": observation.nearest_person_ttc_s,
                "obstacle_m": observation.nearest_obstacle_m,
                "obstacle_bearing": observation.nearest_obstacle_bearing_rad,
                "lidar_obstacles": len(observation.lidar_obstacles),
                "collision": bool(observation.collision),
                "obs_age_s": round(time.monotonic() - float(observation.timestamp), 4),
            }
        else:
            tick["obs"] = None
        # The tick row is complete once the gate has spoken; set_target may or
        # may not fire afterwards (dispatch dedupes unchanged commands), so the
        # row is appended here and amended below if a send happens.
        tick["sent"] = None
        trace.append(dict(tick))
        tick["row"] = len(trace) - 1
        return gated, proximity_state

    def set_target(command, **kwargs):
        row = tick.get("row")
        if isinstance(row, int) and 0 <= row < len(trace):
            trace[row]["sent"] = _cmd(command)
            trace[row]["sent_source"] = kwargs.get("source")
        return real_set_target(command, **kwargs)

    runtime.arbiter.current = current
    runtime._collision_safe = collision_safe
    runtime.control_manager.set_target = set_target


def classify(trace: list[dict]) -> dict[str, object]:
    """Offline attribution. Thresholds come from the real policy object."""

    from parcel_robot.navigation.reactive_safety import ReactiveSafetyPolicy

    policy = ReactiveSafetyPolicy()
    buckets: dict[str, int] = {
        "no_intent": 0,
        "zero_intent": 0,
        "gate_zeroed_person": 0,
        "gate_zeroed_ttc": 0,
        "gate_zeroed_obstacle": 0,
        "gate_zeroed_other": 0,
        "ttc_gate_zeroed": 0,
        "gate_scaled": 0,
        "ramp_limited": 0,
        "delivered_moving": 0,
    }
    translating_intent = 0
    gate_touched = 0
    delivered = []
    slowing_scales: list[dict] = []
    for row in trace:
        intent = row.get("intent")
        smoothed = row.get("smoothed")
        gated = row.get("gated")
        sent = row.get("sent")
        obs = row.get("obs") or {}
        if intent is None:
            buckets["no_intent"] += 1
            continue
        if math.hypot(intent["vx"], intent["vy"]) <= 1e-9:
            buckets["zero_intent"] += 1
            continue
        translating_intent += 1
        intent_speed = math.hypot(intent["vx"], intent["vy"])
        smoothed_speed = math.hypot(smoothed["vx"], smoothed["vy"]) if smoothed else 0.0
        gated_speed = math.hypot(gated["vx"], gated["vy"]) if gated else 0.0
        post_reactive = row.get("post_reactive")
        post_reactive_speed = (
            math.hypot(post_reactive["vx"], post_reactive["vy"])
            if post_reactive
            else None
        )
        if (
            smoothed_speed > 1e-6
            and gated_speed <= 1e-6
            and post_reactive_speed is not None
            and post_reactive_speed > 1e-6
        ):
            # The geometric gate allowed it; the TTC gate scaled it to zero.
            gate_touched += 1
            buckets["ttc_gate_zeroed"] += 1
        elif smoothed_speed > 1e-6 and gated_speed <= 1e-6:
            gate_touched += 1
            ttc = obs.get("person_ttc_s")
            person = obs.get("person_m")
            obstacle = obs.get("obstacle_toward_m")
            if ttc is not None and ttc <= 0.8:
                buckets["gate_zeroed_ttc"] += 1
            elif person is not None and person <= policy.person_stop_m + smoothed_speed * policy.reaction_time_s:
                buckets["gate_zeroed_person"] += 1
            elif obstacle is not None and obstacle <= policy.obstacle_stop_m + smoothed_speed * policy.reaction_time_s:
                buckets["gate_zeroed_obstacle"] += 1
            else:
                buckets["gate_zeroed_other"] += 1
        elif smoothed_speed > 1e-6 and gated_speed < smoothed_speed - 1e-6:
            gate_touched += 1
            buckets["gate_scaled"] += 1
            # D6: the gate's own per-tick scale, and what a SINGLE application
            # of it to the commanded 0.25 m/s would have delivered.
            scale = gated_speed / smoothed_speed
            slowing_scales.append(
                {
                    "scale": round(scale, 6),
                    "delivered": round(gated_speed, 6),
                    "single_application": round(scale * intent_speed, 6),
                }
            )
        elif smoothed_speed < intent_speed - 1e-6:
            buckets["ramp_limited"] += 1
        if sent is not None:
            speed = math.hypot(sent["vx"], sent["vy"])
            delivered.append(speed)
            if speed >= 0.15:
                buckets["delivered_moving"] += 1
    compounded = [
        item for item in slowing_scales
        if item["delivered"] < 0.9 * item["single_application"]
    ]
    return {
        "d6_slowing_ticks": len(slowing_scales),
        "d6_compounded_ticks": len(compounded),
        "d6_compounded_share": (
            round(len(compounded) / len(slowing_scales), 4) if slowing_scales else None
        ),
        "d6_examples": slowing_scales[:5],
        "ticks": len(trace),
        "translating_intent_ticks": translating_intent,
        "gate_touched_ticks": gate_touched,
        "buckets": buckets,
        "sent_count": len(delivered),
        "sent_max_speed": round(max(delivered), 6) if delivered else None,
        "sent_p50_speed": (
            round(sorted(delivered)[len(delivered) // 2], 6) if delivered else None
        ),
        "sent_nonzero_count": sum(1 for value in delivered if value > 1e-6),
    }


def path_length(trace: list[dict]) -> dict[str, float]:
    poses = [
        (row["obs"]["x"], row["obs"]["y"])
        for row in trace
        if row.get("obs") is not None
    ]
    total = 0.0
    for before, after in itertools.pairwise(poses):
        total += math.hypot(after[0] - before[0], after[1] - before[1])
    net = (
        math.hypot(poses[-1][0] - poses[0][0], poses[-1][1] - poses[0][1])
        if len(poses) >= 2
        else 0.0
    )
    return {
        "path_length_m": round(total, 6),
        "net_displacement_m": round(net, 6),
        "pose_samples": len(poses),
        "first": list(poses[0]) if poses else None,
        "last": list(poses[-1]) if poses else None,
    }


def start_simulator(
    *, config_path: Path, socket_path: Path, log_path: Path, static_city: bool
) -> tuple[subprocess.Popen, object]:
    if socket_path.exists():
        socket_path.unlink()
    handle = log_path.open("w", encoding="utf-8")
    argv = [
        sys.executable,
        "-m",
        "parcel_robot.sim",
        "--config",
        str(config_path),
        "--socket",
        str(socket_path),
    ]
    if static_city:
        argv.append("--static-city")
    process = subprocess.Popen(
        argv,
        cwd=str(REPO),
        stdout=handle,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONPATH": str(REPO / "src"), "MUJOCO_GL": "glfw"},
    )
    for _ in range(300):
        if socket_path.exists():
            break
        time.sleep(0.1)
    if not socket_path.exists():
        process.terminate()
        handle.close()
        raise SystemExit(f"simulator socket never appeared; see {log_path}")
    return process, handle


def stop_simulator(process: subprocess.Popen, handle: object, socket_path: Path) -> int:
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
    handle.close()  # type: ignore[attr-defined]
    if socket_path.exists():
        socket_path.unlink()
    return process.returncode


def run_arm(
    *, name: str, config_path: Path, socket_path: Path, duration_s: float, out_dir: Path
) -> dict[str, object]:
    from parcel_robot.models import VelocityCommand
    from parcel_robot.web_panel import build_runtime

    runtime = build_runtime(config_path, socket_path, use_llm=False)
    trace: list[dict] = []
    instrument(runtime, trace)
    runtime.start()

    accepted = 0
    rejected = 0
    collisions = 0
    try:
        deadline = time.monotonic() + duration_s
        toggle = 0
        while time.monotonic() < deadline:
            if name == "replicate":
                # C-1's exact drive: every second request is an explicit stop.
                command = (
                    VelocityCommand(vx=0.25, vy=0.0, vyaw=0.0)
                    if toggle % 2 == 0
                    else VelocityCommand()
                )
            elif name == "steered":
                # Addendum A1 / D5. Identical in every respect to `held` except
                # that it may TURN: if the lane ahead is short, yaw instead of
                # pushing into it. This is the minimum change that distinguishes
                # "the heading was blocked" from "the locomotion path is broken".
                clearance = None
                if trace:
                    clearance = (trace[-1].get("obs") or {}).get("obstacle_toward_m")
                if clearance is not None and clearance < 1.5:
                    command = VelocityCommand(vx=0.0, vy=0.0, vyaw=0.8)
                else:
                    command = VelocityCommand(vx=0.25, vy=0.0, vyaw=0.0)
            else:
                command = VelocityCommand(vx=0.25, vy=0.0, vyaw=0.0)
            try:
                runtime.submit_motion("voice", command)
                accepted += 1
            except Exception:  # noqa: BLE001
                rejected += 1
            toggle += 1
            time.sleep(0.25)
    finally:
        runtime.close()

    collisions = sum(
        1 for row in trace if (row.get("obs") or {}).get("collision") is True
    )
    (out_dir / f"{name}_trace.json").write_text(
        json.dumps(trace, indent=1), encoding="utf-8"
    )
    result: dict[str, object] = {
        "arm": name,
        "duration_s": duration_s,
        "motion_accepted": accepted,
        "motion_rejected": rejected,
        "collision_ticks": collisions,
        **path_length(trace),
        "attribution": classify(trace),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=40.0)
    parser.add_argument("--out", default=None)
    parser.add_argument("--arms", default="replicate,held,held_static,steered")
    args = parser.parse_args()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out or (Path(__file__).parent / f"diagnosis_{stamp}"))
    out_dir.mkdir(parents=True, exist_ok=True)

    scene = REPO / "src" / "parcel_robot" / "scenes" / "city_block.xml"
    skills = REPO / "configs" / "skills"
    config_path = out_dir / "move1.yaml"
    config_path.write_text(
        BASE_CONFIG.format(skills=skills, scene=scene), encoding="utf-8"
    )

    store = Path.home() / ".parcel" / "parcel_memory.sqlite3"
    owner_before = sha256_file(store) if store.is_file() else None

    socket_path = Path(f"/tmp/parcel-move1-{os.getpid()}.sock")
    arms: dict[str, object] = {}
    returncodes: dict[str, int] = {}
    for name in [item.strip() for item in args.arms.split(",") if item.strip()]:
        process, handle = start_simulator(
            config_path=config_path,
            socket_path=socket_path,
            log_path=out_dir / f"simulator_{name}.log",
            static_city=(name == "held_static"),
        )
        try:
            arms[name] = run_arm(
                name=name,
                config_path=config_path,
                socket_path=socket_path,
                duration_s=args.duration,
                out_dir=out_dir,
            )
        finally:
            returncodes[name] = stop_simulator(process, handle, socket_path)

    owner_after = sha256_file(store) if store.is_file() else None
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "repo_head": subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "scene": str(scene),
        "scene_sha256": sha256_file(scene),
        "duration_s": args.duration,
        "simulator_returncodes": returncodes,
        "fresh_simulator_per_arm": True,
        "owner_store": {
            "sha256_before": owner_before,
            "sha256_after": owner_after,
            "unchanged": owner_before == owner_after,
        },
        "arms": arms,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "attribution"} for k, v in arms.items()}, indent=2))
    print(f"\nwrote {out_dir}/summary.json")


if __name__ == "__main__":
    main()
