"""Preregistered C-1 normal `.parcel` CPU/EGL live evidence cell.

This is evidence orchestration, not a product runtime alternative.  It starts
the real simulator process and uses ``web_panel.build_runtime`` plus the real
HTTP server/composition root.  See C1_PREREGISTRATION.md before interpreting a
number from its output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import resource
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[4]
EVIDENCE_DIR = SCRIPT.parent
PYTHON = REPO / ".parcel" / "bin" / "python"
CONFIG_ON = EVIDENCE_DIR / "c1_cpu_live.yaml"
CONFIG_OFF = EVIDENCE_DIR / "c1_cpu_live_off.yaml"
SCENE = REPO / "src" / "parcel_robot" / "scenes" / "city_block.xml"
OWNER_STORE = REPO / "parcel_memory.sqlite3"
SOURCE_PATHS = (
    "scripts/launch_sim.sh",
    "src/parcel_robot/camera_channel/backends/mujoco_egl.py",
    "src/parcel_robot/camera_channel/ingress.py",
    "src/parcel_robot/realtime/evidence_log.py",
    "src/parcel_robot/runtime.py",
    "src/parcel_robot/sim.py",
    "src/parcel_robot/ui/index.html",
    "src/parcel_robot/web_panel.py",
    "tests/test_runtime_activation.py",
    "tests/test_c1_camera_ingress.py",
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _proc_memory_kib(pid: int) -> dict[str, int | None]:
    result: dict[str, int | None] = {"vm_rss_kib": None, "vm_hwm_kib": None}
    try:
        rows = (Path("/proc") / str(pid) / "status").read_text(encoding="utf-8")
    except OSError:
        return result
    for line in rows.splitlines():
        if line.startswith("VmRSS:"):
            result["vm_rss_kib"] = int(line.split()[1])
        elif line.startswith("VmHWM:"):
            result["vm_hwm_kib"] = int(line.split()[1])
    return result


def _gpu_sample() -> dict[str, object]:
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        text=True,
        capture_output=True,
        timeout=5.0,
    )
    fields = [field.strip() for field in completed.stdout.splitlines()[0].split(",")]
    applications = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,used_gpu_memory",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        text=True,
        capture_output=True,
        timeout=5.0,
    )
    app_rows: list[dict[str, int]] = []
    for line in applications.stdout.splitlines():
        values = [field.strip() for field in line.split(",")]
        if len(values) == 2 and all(value.isdigit() for value in values):
            app_rows.append({"pid": int(values[0]), "used_gpu_memory_mib": int(values[1])})
    own_usage = sum(
        row["used_gpu_memory_mib"] for row in app_rows if row["pid"] == os.getpid()
    )
    return {
        "sampled_at_utc": _iso_now(),
        "name": fields[0],
        "memory_total_mib": int(fields[1]),
        "memory_used_mib": int(fields[2]),
        "memory_free_mib": int(fields[3]),
        "driver_version": fields[4],
        "compute_applications": app_rows,
        "current_process_used_gpu_memory_mib": own_usage,
    }


def _percentiles(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
            "mean": None,
        }
    ordered = sorted(float(value) for value in values)

    def at(fraction: float) -> float:
        index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
        return round(ordered[index], 3)

    return {
        "count": len(ordered),
        "p50": at(0.50),
        "p95": at(0.95),
        "p99": at(0.99),
        "max": round(max(ordered), 3),
        "mean": round(statistics.fmean(ordered), 3),
    }


def _http_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"Host": "127.0.0.1"})
    with urllib.request.urlopen(request, timeout=5.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{url} did not return one JSON object")
    return payload


def _http_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Host": "127.0.0.1"})
    with urllib.request.urlopen(request, timeout=5.0) as response:
        return response.read()


def _wait_for_sim(socket_path: Path, process: subprocess.Popen[bytes]) -> dict[str, object]:
    from parcel_robot.sim_ipc import request_status

    deadline = time.monotonic() + 30.0
    last_error = "not attempted"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"simulator exited during startup with {process.returncode}")
        try:
            return request_status(socket_path, timeout=1.0)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            last_error = f"{type(error).__name__}: {error}"
            time.sleep(0.1)
    raise TimeoutError(f"simulator did not become ready: {last_error}")


def _clear_sim_estop(socket_path: Path) -> dict[str, object]:
    from parcel_robot.sim_ipc import publish_clear_emergency_stop, request_status

    publish_clear_emergency_stop(socket_path)
    deadline = time.monotonic() + 3.0
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        last = request_status(socket_path, timeout=1.0)
        if last.get("emergency_stopped") is False:
            return last
        time.sleep(0.05)
    raise RuntimeError(f"simulator E-stop did not clear: {last!r}")


def _motion_refresh(runtime: Any, counters: dict[str, object], now: float) -> None:
    from parcel_robot.models import VelocityCommand

    if now < float(counters["next_at"]):
        return
    counters["next_at"] = now + 0.25
    try:
        runtime.submit_motion(
            "voice",
            VelocityCommand(vx=0.08, vy=0.0, vyaw=0.10),
            ttl=0.40,
        )
        counters["accepted"] = int(counters["accepted"]) + 1
    except RuntimeError as error:
        counters["rejected"] = int(counters["rejected"]) + 1
        reasons = counters["rejection_reasons"]
        assert isinstance(reasons, list)
        if len(reasons) < 16:
            reasons.append(str(error))


def _run_arm(
    *,
    name: str,
    config_path: Path,
    socket_path: Path,
    output_dir: Path,
    simulator_pid: int,
    camera_on: bool,
) -> dict[str, object]:
    from parcel_robot.web_panel import RuntimeHTTPServer, build_runtime

    runtime: Any = None
    server: RuntimeHTTPServer | None = None
    server_thread: threading.Thread | None = None
    evidence_path: Path | None = None
    frames: list[Any] = []
    gpu_samples: list[dict[str, object]] = []
    process_rss_samples: list[int] = []
    simulator_rss_samples: list[int] = []
    motion: dict[str, object] = {
        "accepted": 0,
        "rejected": 0,
        "rejection_reasons": [],
        "next_at": 0.0,
    }
    arm_started = time.monotonic()
    state: dict[str, object] = {}
    latency: dict[str, object] = {}
    backend_health: dict[str, object] = {}
    panel_html: dict[str, object] | None = None
    base_url: str | None = None
    close_error: str | None = None
    try:
        runtime = build_runtime(
            config_path,
            socket_path,
            use_llm=False,
            scene_override=SCENE,
        )
        if camera_on:
            log = runtime._session_evidence
            if log is None:
                raise RuntimeError("camera-on runtime did not arm EV-1")
            evidence_path = Path(log.path)
        # Keep the HTTP composition symmetric across OFF and ON.  The ON arm
        # has a camera worker by design; an extra server thread must not be a
        # hidden difference in the ControlLoopWork comparison.
        server = RuntimeHTTPServer(
            ("127.0.0.1", 0),
            runtime,
            scene_path=SCENE,
        )
        runtime.start()
        if server is not None:
            port = int(server.server_address[1])
            base_url = f"http://127.0.0.1:{port}"
            server_thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.05},
                name=f"c1-live-http-{name}",
                daemon=True,
            )
            server_thread.start()

        started = time.monotonic()
        minimum_duration_s = 12.0 if camera_on else 8.0
        maximum_duration_s = 25.0 if camera_on else 8.5
        next_gpu_sample = 0.0
        while True:
            now = time.monotonic()
            elapsed = now - started
            _motion_refresh(runtime, motion, now)
            if camera_on:
                frames.extend(runtime.drain_camera_detection_frames())
            if now >= next_gpu_sample:
                gpu_samples.append(_gpu_sample())
                next_gpu_sample = now + 0.5
            self_memory = _proc_memory_kib(os.getpid())["vm_rss_kib"]
            sim_memory = _proc_memory_kib(simulator_pid)["vm_rss_kib"]
            if isinstance(self_memory, int):
                process_rss_samples.append(self_memory)
            if isinstance(sim_memory, int):
                simulator_rss_samples.append(sim_memory)
            enough_frames = not camera_on or len(frames) >= 5
            if elapsed >= minimum_duration_s and enough_frames:
                break
            if elapsed >= maximum_duration_s:
                break
            time.sleep(0.05)

        if camera_on:
            frames.extend(runtime.drain_camera_detection_frames())
        if base_url is None:
            raise RuntimeError("symmetric HTTP server did not publish an address")
        state = _http_json(f"{base_url}/api/state")
        latency = _http_json(f"{base_url}/api/latency")
        html = _http_bytes(f"{base_url}/")
        panel_html = {
            "bytes": len(html),
            "sha256": hashlib.sha256(html).hexdigest(),
            "camera_renderer_present": b"renderCameraIngress" in html,
            "static_copy_caveat_present": b"static" in html and b"unsynced" in html,
        }
        if camera_on:
            ingress = runtime._camera_stream_ingress
            backend = None if ingress is None else ingress.backend
            buffers = {} if backend is None else getattr(backend, "_buffers", {})
            current = None if backend is None else getattr(backend, "last_buffers", None)
            backend_health = {
                "kind": None if backend is None else getattr(backend, "kind", None),
                "buffer_refs": len(buffers),
                "buffer_bytes": sum(
                    int(getattr(value, "nbytes", 0)) for value in buffers.values()
                ),
                "has_current_buffers": current is not None,
            }
    finally:
        if server is not None:
            try:
                server.shutdown()
            finally:
                server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=2.0)
        if runtime is not None:
            try:
                runtime.close()
            except Exception as error:  # noqa: BLE001 - retain teardown truth
                close_error = f"{type(error).__name__}: {error}"

    evidence: dict[str, object] | None = None
    if evidence_path is not None:
        from parcel_robot.camera_channel.ingress import DetectionFrame
        from parcel_robot.realtime.evidence_log import (
            STREAM_PERCEPTION,
            read_event_log,
            verify_event_log,
        )

        rows = read_event_log(evidence_path)
        perception = [row for row in rows if row.get("stream") == STREAM_PERCEPTION]
        metadata_keys = {
            "seq",
            "stream",
            "wall",
            "kind",
            "runtime_drop_counts",
            "accepted_monotonic_ns",
            "authority",
        }
        decoded_view_ids: list[str] = []
        decode_errors: list[str] = []
        for index, row in enumerate(perception):
            try:
                frame = DetectionFrame.from_mapping(
                    {key: value for key, value in row.items() if key not in metadata_keys}
                )
                decoded_view_ids.append(frame.view_id)
            except (KeyError, TypeError, ValueError) as error:
                decode_errors.append(f"row {index}: {type(error).__name__}: {error}")
        evidence = {
            "path": str(evidence_path),
            "row_count": len(rows),
            "perception_row_count": len(perception),
            "verification_problems": verify_event_log(rows),
            "typed_payloads_decoded": len(decoded_view_ids),
            "typed_payload_decode_errors": decode_errors,
            "decoded_view_ids": decoded_view_ids,
            "typed_payload_requirement_met": bool(decoded_view_ids) and not decode_errors,
            "first_perception_row": perception[0] if perception else None,
            "last_row": rows[-1] if rows else None,
            "sha256": _sha256(evidence_path),
        }

    capture_ms = [
        (frame.capture_completed_monotonic_ns - frame.capture_started_monotonic_ns)
        / 1e6
        for frame in frames
    ]
    detect_ms = [float(frame.detector_latency_ms) for frame in frames]
    inference_ms = [float(frame.inference_latency_ms) for frame in frames]
    total_ms = [
        (frame.published_monotonic_ns - frame.capture_started_monotonic_ns) / 1e6
        for frame in frames
    ]
    published = [int(frame.published_monotonic_ns) for frame in frames]
    achieved_hz = (
        (len(published) - 1) / ((published[-1] - published[0]) / 1e9)
        if len(published) > 1 and published[-1] > published[0]
        else 0.0
    )
    gpu_used = [int(sample["memory_used_mib"]) for sample in gpu_samples]
    gpu_free = [int(sample["memory_free_mib"]) for sample in gpu_samples]
    own_gpu_used = [
        int(sample["current_process_used_gpu_memory_mib"]) for sample in gpu_samples
    ]
    components = latency.get("components", {})
    control_loop = (
        components.get("ControlLoopWork", {}) if isinstance(components, dict) else {}
    )
    result: dict[str, object] = {
        "arm": name,
        "camera_on": camera_on,
        "config": str(config_path),
        "config_sha256": _sha256(config_path),
        "started_at_utc": datetime.fromtimestamp(
            time.time() - (time.monotonic() - arm_started), UTC
        ).isoformat(),
        "ended_at_utc": _iso_now(),
        "elapsed_s": round(time.monotonic() - arm_started, 3),
        "motion_script": {
            key: value for key, value in motion.items() if key != "next_at"
        },
        "motion_measurement_scope": "accepted_by_runtime_submission_api_not_actuator_ack",
        "state": state,
        "latency": latency,
        "control_loop_work": control_loop,
        "typed_frames": {
            "count": len(frames),
            "achieved_hz_from_publish_timestamps": round(achieved_hz, 3),
            "capture_ms": _percentiles(capture_ms),
            "detector_ms": _percentiles(detect_ms),
            "inference_ms": _percentiles(inference_ms),
            "capture_start_to_publish_ms": _percentiles(total_ms),
            "view_ids": [frame.view_id for frame in frames],
            "empty_frames": sum(1 for frame in frames if frame.raw_detection_count == 0),
            "raw_detections": sum(frame.raw_detection_count for frame in frames),
            "localized_detections": sum(frame.total_detection_count for frame in frames),
            "localization_rejections": sum(
                frame.localization_rejection_count for frame in frames
            ),
            "expired_at_publish": sum(
                frame.published_monotonic_ns >= frame.expires_monotonic_ns
                for frame in frames
            ),
            "provider_profiles": sorted({frame.detector_profile for frame in frames}),
            "selected_execution_providers": sorted(
                {frame.detector_selected_execution_provider for frame in frames}
            ),
            "active_execution_providers": sorted(
                {
                    provider
                    for frame in frames
                    for provider in frame.detector_active_execution_providers
                }
            ),
            "model_digests": sorted({frame.detector_model_digest for frame in frames}),
            "scene_digests": sorted({frame.scene_digest for frame in frames}),
            "config_digests": sorted({frame.config_digest for frame in frames}),
        },
        "backend_health_before_close": backend_health,
        "panel_html": panel_html,
        "http_base_url_during_run": base_url,
        "evidence_after_close": evidence,
        "process_memory": {
            "runtime_rss_peak_kib_sampled": max(process_rss_samples, default=None),
            "simulator_rss_peak_kib_sampled": max(simulator_rss_samples, default=None),
            "self_ru_maxrss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        },
        "gpu": {
            "scope": "system_wide_nvidia_smi_not_process_attribution",
            "samples": gpu_samples,
            "used_mib_min": min(gpu_used, default=None),
            "used_mib_peak": max(gpu_used, default=None),
            "free_mib_min": min(gpu_free, default=None),
            "current_process_used_gpu_memory_mib_peak": max(own_gpu_used, default=None),
            "headroom_at_least_6gib": bool(gpu_free) and min(gpu_free) >= 6144,
        },
        "close_error": close_error,
    }
    (output_dir / f"{name}_api_state.json").write_text(
        json.dumps(state, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / f"{name}_arm.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="new directory for the immutable result artifacts",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    socket_path = Path("/tmp") / f"parcel-c1-live-{os.getpid()}.sock"

    os.environ["MUJOCO_GL"] = "egl"
    os.environ["PARCEL_MEMORY_PURPOSE"] = "owner"
    os.environ["PARCEL_SESSION_EVIDENCE"] = "1"
    os.environ["PARCEL_SESSION_EVIDENCE_DIR"] = str(output_dir / "sessions")
    os.environ["PARCEL_CAMERA_INGRESS"] = "0"
    os.environ.pop("PARCEL_REALTIME_CONFIG", None)
    os.environ.pop("PARCEL_OWLV2_SOURCE_MAX_EDGE", None)

    summary: dict[str, object] = {
        "schema": "parcel.c1_cpu_live.v1",
        "preregistration": str(EVIDENCE_DIR / "C1_PREREGISTRATION.md"),
        "started_at_utc": _iso_now(),
        "repo": str(REPO),
        "python": sys.executable,
        "pid": os.getpid(),
        "socket": str(socket_path),
        "scene": str(SCENE),
        "scene_xml_sha256": _sha256(SCENE),
        "source_sha256": {
            path: _sha256(REPO / path) for path in SOURCE_PATHS
        },
        "owner_store_before": {
            "path": str(OWNER_STORE),
            "sha256": _sha256(OWNER_STORE),
        },
        "gpu_before": _gpu_sample(),
        "normal_onnxruntime": {},
        "simulator": {},
        "arms": {},
        "errors": [],
    }
    import onnxruntime as ort

    summary["normal_onnxruntime"] = {
        "version": ort.__version__,
        "available_providers": ort.get_available_providers(),
    }

    sim_log_path = output_dir / "simulator.log"
    sim_log = sim_log_path.open("wb")
    sim_env = dict(os.environ)
    sim_env["MUJOCO_GL"] = "glfw"
    simulator = subprocess.Popen(
        [
            str(PYTHON),
            "-B",
            "-m",
            "parcel_robot.sim",
            "--config",
            str(CONFIG_ON),
            "--scene",
            str(SCENE),
            "--socket",
            str(socket_path),
            "--static-city",
        ],
        cwd=REPO,
        env=sim_env,
        stdout=sim_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    summary["simulator"] = {
        "pid": simulator.pid,
        "command": simulator.args,
        "log": str(sim_log_path),
    }
    exit_code = 0
    try:
        summary["simulator"]["ready_status"] = _wait_for_sim(socket_path, simulator)  # type: ignore[index]
        off = _run_arm(
            name="off",
            config_path=CONFIG_OFF,
            socket_path=socket_path,
            output_dir=output_dir,
            simulator_pid=simulator.pid,
            camera_on=False,
        )
        summary["arms"]["off"] = off  # type: ignore[index]
        summary["simulator"]["after_off_clear"] = _clear_sim_estop(socket_path)  # type: ignore[index]
        on = _run_arm(
            name="on",
            config_path=CONFIG_ON,
            socket_path=socket_path,
            output_dir=output_dir,
            simulator_pid=simulator.pid,
            camera_on=True,
        )
        summary["arms"]["on"] = on  # type: ignore[index]
        evidence = on.get("evidence_after_close")
        if not isinstance(evidence, dict) or evidence.get(
            "typed_payload_requirement_met"
        ) is not True:
            raise RuntimeError("live EV-1 perception payloads did not decode cleanly")
        off_loop = off.get("control_loop_work", {})
        on_loop = on.get("control_loop_work", {})
        off_p99 = off_loop.get("p99_ms") if isinstance(off_loop, dict) else None
        on_p99 = on_loop.get("p99_ms") if isinstance(on_loop, dict) else None
        delta = (
            float(on_p99) - float(off_p99)
            if isinstance(off_p99, (int, float)) and isinstance(on_p99, (int, float))
            else None
        )
        summary["safety_isolation"] = {
            "metric": "ControlLoopWork",
            "scope": "single_sequential_descriptive_pair_not_statistical_proof",
            "off_p99_ms": off_p99,
            "on_p99_ms": on_p99,
            "delta_ms": None if delta is None else round(delta, 3),
            "on_under_100ms": isinstance(on_p99, (int, float)) and float(on_p99) < 100.0,
            "delta_at_most_5ms": delta is not None and delta <= 5.0,
            "preregistered": True,
        }
    except Exception as error:  # noqa: BLE001 - preserve partial live evidence
        exit_code = 1
        errors = summary["errors"]
        assert isinstance(errors, list)
        errors.append(f"{type(error).__name__}: {error}")
    finally:
        if simulator.poll() is None:
            simulator.send_signal(signal.SIGINT)
            try:
                simulator.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                simulator.terminate()
                try:
                    simulator.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    simulator.kill()
                    simulator.wait(timeout=5.0)
        sim_log.close()
        summary["simulator"]["returncode"] = simulator.returncode  # type: ignore[index]
        summary["simulator"]["socket_exists_after_stop"] = socket_path.exists()  # type: ignore[index]
        summary["owner_store_after"] = {
            "path": str(OWNER_STORE),
            "sha256": _sha256(OWNER_STORE),
        }
        before = summary["owner_store_before"]
        after = summary["owner_store_after"]
        summary["owner_store_unchanged"] = (
            isinstance(before, dict)
            and isinstance(after, dict)
            and before.get("sha256") == after.get("sha256")
        )
        summary["gpu_after"] = _gpu_sample()
        summary["ended_at_utc"] = _iso_now()
        (output_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
