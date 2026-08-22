"""C-1 re-dispatch live proof harness.

Runs TWO symmetric arms against the real simulator over a real socket, with the
real non-test composition root (``web_panel.build_runtime``) and a real bound
HTTP server in BOTH arms:

* OFF — ``perception.camera_ingress`` absent from the config entirely.
* ON  — the block present and true.

Symmetry matters and is the correction this harness adopts from the reverted
run's own post-mortem: if only the ON arm binds an HTTP server, the OFF arm is
cheaper for a reason that has nothing to do with the camera and the latency
delta is measuring the wrong thing.

MUJOCO_GL is set before ANY import: the GL backend binds at the first
``import mujoco`` in a process and cannot be changed afterwards.
"""

from __future__ import annotations

import os

os.environ.setdefault("MUJOCO_GL", "egl")

import argparse
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

OFF_CONFIG = """
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

ON_EXTRA = """  camera_ingress: true
  camera_ingress_rate_hz: {rate}
  camera_ingress_queue_capacity: 16
  camera_ingress_max_detections_per_frame: 8
  camera_ingress_queries: [person, lamppost]
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gpu_used_mib() -> dict[str, int] | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip().splitlines()[0]
        used, free = (int(v.strip()) for v in out.split(","))
        return {"used_mib": used, "free_mib": free}
    except Exception:  # noqa: BLE001
        return None


def percentiles(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(values)

    def pct(q: float) -> float:
        idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
        return round(ordered[idx], 4)

    return {
        "count": len(ordered),
        "p50": pct(0.50),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "max": round(ordered[-1], 4),
        "mean": round(statistics.fmean(ordered), 4),
    }


def http_get(url: str, timeout: float = 10.0) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, response.read()


def run_arm(
    *,
    name: str,
    config_path: Path,
    socket_path: Path,
    duration_s: float,
    out_dir: Path,
    run_start_wall: float,
) -> dict[str, object]:
    """One symmetric arm: real runtime + real HTTP server, driven identically."""

    from parcel_robot.models import VelocityCommand
    from parcel_robot.web_panel import RuntimeHTTPServer, build_runtime, resolve_viewer_scene

    runtime = build_runtime(config_path, socket_path, use_llm=False)
    server = RuntimeHTTPServer(
        ("127.0.0.1", 0),
        runtime,
        scene_path=resolve_viewer_scene(config_path),
    )
    port = server.server_address[1]
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    # Card EV-1. Armed in BOTH arms via the runtime's OWN method, so the arms
    # stay symmetric and the perception rows land through the product path
    # rather than a harness-built log. (The runtime calls this itself when the
    # hosted realtime lane is enabled; this cell runs with the lane off, so the
    # harness invokes the same method directly.)
    runtime._arm_session_evidence()
    evidence_path = (
        str(runtime._session_evidence.path) if runtime._session_evidence else None
    )
    started_at = time.time()
    runtime.start()

    motion_accepted = 0
    motion_rejected = 0
    try:
        deadline = time.monotonic() + duration_s
        toggle = 0
        while time.monotonic() < deadline:
            # Identical drive in both arms: a small motion request every 250 ms
            # so the control loop, collision gate and dispatch path are all
            # genuinely exercised rather than idling.
            try:
                runtime.submit_motion(
                    "voice",
                    VelocityCommand(vx=0.25, vy=0.0, vyaw=0.0)
                    if toggle % 2 == 0
                    else VelocityCommand(),
                )
                motion_accepted += 1
            except Exception:  # noqa: BLE001
                motion_rejected += 1
            toggle += 1
            time.sleep(0.25)
        gpu_during = gpu_used_mib()
        status, body = http_get(f"http://127.0.0.1:{port}/api/state")
        state = json.loads(body)
        html_status, html_body = http_get(f"http://127.0.0.1:{port}/")
        metrics = runtime.component_metrics.snapshot()
        camera_snapshot = runtime.camera_stream_snapshot()
        frames = [f.as_dict() for f in runtime.camera_detection_frame_slice(512)]
        producer = None
        if runtime._camera_ingress is not None:
            producer = dict(runtime._camera_ingress.stats.as_dict())
            detector = runtime._camera_ingress.detector
            resolution = getattr(detector, "resolution", None)
            producer["detector_name"] = getattr(detector, "name", None)
            producer["provider_requested"] = str(getattr(resolution, "requested", None))
            producer["provider_selected"] = str(getattr(resolution, "selected", None))
            producer["provider_precision"] = str(getattr(resolution, "precision", None))
            producer["provider_model_file"] = str(getattr(resolution, "model_file", None))
            producer["provider_execution_providers"] = [
                str(p) for p in (getattr(resolution, "execution_providers", ()) or ())
            ]
            producer["provider_rejected"] = [
                str(r) for r in (getattr(resolution, "rejected", ()) or ())
            ]
    finally:
        server.shutdown()
        server.server_close()
        runtime.close()

    # EV-1 verification, after close() has flushed and written log_closed.
    evidence = {"path": evidence_path, "armed": evidence_path is not None}
    if evidence_path and Path(evidence_path).is_file():
        from parcel_robot.camera_channel.ingress import CameraDetectionFrame
        from parcel_robot.realtime.evidence_log import read_event_log, verify_event_log

        rows = read_event_log(evidence_path)
        camera_rows = [r for r in rows if r.get("kind") == "camera_detection_frame"]
        decoded, decode_errors = 0, []
        for row in camera_rows:
            payload = {
                k: v
                for k, v in row.items()
                if k not in {"kind", "stream", "seq", "at", "wall"}
            }
            try:
                CameraDetectionFrame.from_mapping(payload)
                decoded += 1
            except Exception as exc:  # noqa: BLE001
                decode_errors.append(str(exc))
        evidence.update(
            {
                "sha256": sha256_file(Path(evidence_path)),
                "rows_total": len(rows),
                "perception_rows": len(camera_rows),
                "perception_rows_strictly_decoded": decoded,
                "decode_errors": decode_errors[:5],
                "verify_problems": verify_event_log(rows),
                "final_row_kind": rows[-1].get("kind") if rows else None,
            }
        )
        shutil.copy2(evidence_path, out_dir / f"{name}_events.jsonl")

    (out_dir / f"{name}_api_state.json").write_text(
        json.dumps(state, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / f"{name}_frames.json").write_text(
        json.dumps(frames, indent=2), encoding="utf-8"
    )

    def series(metric: str) -> dict[str, object]:
        row = (metrics.get(metric) or {}) if isinstance(metrics, dict) else {}
        return {
            "count": row.get("count"),
            "p50_ms": row.get("p50_ms"),
            "p95_ms": row.get("p95_ms"),
            "p99_ms": row.get("p99_ms"),
            "max_ms": row.get("max_ms"),
        }

    # P6: every frame must have been captured AFTER this run started. A frame
    # older than the run is a frame from somewhere else.
    stale_provenance = [
        f["frame_id"] for f in frames if float(f["published_wall_s"]) < run_start_wall
    ]

    publish_latencies = [float(f["publish_latency_ms"]) for f in frames]
    detect_latencies = [float(f["detect_ms"]) for f in frames]
    render_latencies = [float(f["render_ms"]) for f in frames]
    expired = [bool(f["expired_at_publish"]) for f in frames]

    return {
        "arm": name,
        "config": str(config_path),
        "http_port": port,
        "api_state_status": status,
        "panel_html_status": html_status,
        "panel_html_bytes": len(html_body),
        "panel_has_perception_tile": b"perception-tile" in html_body,
        "api_state_has_camera_key": "camera_ingress" in state,
        "motion_accepted": motion_accepted,
        "motion_rejected": motion_rejected,
        "started_at": started_at,
        "duration_s": duration_s,
        "gpu_during": gpu_during,
        "metrics": {
            "ControlLoopWork": series("ControlLoopWork"),
            "CollisionGate": series("CollisionGate"),
            "MotionDispatch": series("MotionDispatch"),
            "SimulatorObserve": series("SimulatorObserve"),
        },
        "camera_snapshot": camera_snapshot,
        "producer": producer,
        "frames_captured": len(frames),
        "frames_with_stale_provenance": stale_provenance,
        "publish_latency_ms": percentiles(publish_latencies),
        "detect_ms": percentiles(detect_latencies),
        "render_ms": percentiles(render_latencies),
        "frames_expired_at_publish": sum(1 for e in expired if e),
        "evidence_session_id": runtime._session_evidence_id or None,
        "evidence": evidence,
    }


def start_simulator(
    *, config_path: Path, socket_path: Path, log_path: Path
) -> tuple[subprocess.Popen, object]:
    """A FRESH simulator per arm.

    Sharing one simulator across both arms is not a cheaper equivalent: the
    first arm's ``runtime.close()`` engages an emergency stop, the simulator
    LATCHES it, and the second arm then adopts a latched E-stop and refuses
    every motion request. The first version of this harness did exactly that
    and produced an ON arm with 0/160 motions accepted — an arm-order artifact
    that would have been read as "the camera broke motion". One simulator per
    arm removes the coupling entirely.
    """

    if socket_path.exists():
        socket_path.unlink()
    handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "parcel_robot.sim",
            "--config",
            str(config_path),
            "--socket",
            str(socket_path),
        ],
        cwd=str(REPO),
        stdout=handle,
        stderr=subprocess.STDOUT,
        # The simulator is a SEPARATE process with its own GL binding: it opens
        # a viewer and wants glfw, while this process renders offscreen with egl.
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=25.0)
    parser.add_argument("--rate", type=float, default=2.0)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out or (Path(__file__).parent / f"rerun_live_{stamp}"))
    out_dir.mkdir(parents=True, exist_ok=True)
    run_start_wall = time.time()

    scene = REPO / "src" / "parcel_robot" / "scenes" / "city_block.xml"
    skills = REPO / "configs" / "skills"
    off_path = out_dir / "c1_off.yaml"
    on_path = out_dir / "c1_on.yaml"
    off_text = OFF_CONFIG.format(skills=skills, scene=scene)
    off_path.write_text(off_text, encoding="utf-8")
    on_path.write_text(
        off_text + ON_EXTRA.format(rate=args.rate), encoding="utf-8"
    )

    store = Path.home() / ".parcel" / "parcel_memory.sqlite3"
    owner_store_before = sha256_file(store) if store.is_file() else None

    socket_path = Path(f"/tmp/parcel-c1-rerun-{os.getpid()}.sock")
    gpu_before = gpu_used_mib()
    sim_returncodes = {}
    arms = {}
    for name, cfg in (("off", off_path), ("on", on_path)):
        process, handle = start_simulator(
            config_path=cfg,
            socket_path=socket_path,
            log_path=out_dir / f"simulator_{name}.log",
        )
        try:
            arms[name] = run_arm(
                name=name,
                config_path=cfg,
                socket_path=socket_path,
                duration_s=args.duration,
                out_dir=out_dir,
                run_start_wall=run_start_wall,
            )
        finally:
            sim_returncodes[name] = stop_simulator(process, handle, socket_path)
    off, on = arms["off"], arms["on"]

    gpu_after = gpu_used_mib()
    owner_store_after = sha256_file(store) if store.is_file() else None

    import onnxruntime as ort

    def delta(metric: str, field: str) -> float | None:
        a = off["metrics"][metric][field]
        b = on["metrics"][metric][field]
        if a is None or b is None:
            return None
        return round(float(b) - float(a), 4)

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "run_start_wall": run_start_wall,
        "repo_head": subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "scene": str(scene),
        "scene_sha256": sha256_file(scene),
        "simulator_returncodes": sim_returncodes,
        "fresh_simulator_per_arm": True,
        "socket_removed_after_stop": not socket_path.exists(),
        "environment": {
            "onnxruntime_version": ort.__version__,
            "available_providers": list(ort.get_available_providers()),
            "cuda_provider_present": "CUDAExecutionProvider"
            in ort.get_available_providers(),
            "mujoco_gl": os.environ.get("MUJOCO_GL"),
            "python": sys.version.split()[0],
        },
        "gpu": {"before": gpu_before, "after": gpu_after},
        "owner_store": {
            "path": str(store),
            "sha256_before": owner_store_before,
            "sha256_after": owner_store_after,
            "unchanged": owner_store_before == owner_store_after,
        },
        "off": off,
        "on": on,
        "deltas": {
            "ControlLoopWork_p99_ms": delta("ControlLoopWork", "p99_ms"),
            "ControlLoopWork_p50_ms": delta("ControlLoopWork", "p50_ms"),
            "CollisionGate_p99_ms": delta("CollisionGate", "p99_ms"),
            "CollisionGate_p50_ms": delta("CollisionGate", "p50_ms"),
            "MotionDispatch_p99_ms": delta("MotionDispatch", "p99_ms"),
        },
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary["deltas"], indent=2))
    print(f"\nwrote {out_dir}/summary.json")


if __name__ == "__main__":
    main()
