"""MOVE-1 — the patrol mission, run for real in the dev scene.

Phase 1 of the protocol E-2 could not reach: MOVE the robot through a scene
while the camera → detector → map loop runs, inside a fixed time budget,
producing a path trace and a map-growth record.

C-1's camera stream is consumed as the **diagnostic** stream C-1 declared it to
be (562 ms p50 publish latency against a 300 ms TTL). Its freshness limitation
is a known input to this card, not this card's to fix — so frames are ingested
WITHOUT ``require_fresh``, and the map-growth record carries the expired count
so no reader can mistake this for grounded authority.
"""

from __future__ import annotations

import os

os.environ.setdefault("MUJOCO_GL", "egl")

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

CONFIG = """
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
  camera_ingress: true
  camera_ingress_rate_hz: 2.0
  camera_ingress_queue_capacity: 64
  camera_ingress_max_detections_per_frame: 8
  camera_ingress_queries: [{queries}]
"""

sys.path.insert(0, str(Path(__file__).parent))
from run_move1_diagnosis import sha256_file, start_simulator, stop_simulator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=float, default=120.0)
    parser.add_argument("--scene", default="city_block")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from parcel_robot.models import VelocityCommand
    from parcel_robot.online_map import (
        MapObservation,
        OnlineSemanticMap,
        WriterProvenance,
        observations_from_frame,
    )
    from parcel_robot.patrol import (
        DEFAULT_MAP_SWEEP_VOCABULARY,
        MapGrowthSample,
        PatrolLimits,
        PatrolRunner,
        ingress_queries,
        sense_from_snapshot,
    )
    from parcel_robot.web_panel import build_runtime

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out or (Path(__file__).parent / f"patrol_{args.scene}_{stamp}"))
    out_dir.mkdir(parents=True, exist_ok=True)

    scene = REPO / "src" / "parcel_robot" / "scenes" / f"{args.scene}.xml"
    if not scene.is_file():
        raise SystemExit(f"no such scene: {scene}")

    # E2-D3: the T1 batch. No sidecar — this is the patrol package's own static
    # vocabulary, screened by C-2's hygiene gate, never scene truth.
    # E2-D3, measured: the camera channel REFUSES a batch without "person"
    # (PG-1 safety lease), and C-2's hygiene gate refuses to keep people as
    # places. Both hold at once, which is why these are two different sets.
    batch = ingress_queries(8)
    queries = ", ".join(batch)
    config_path = out_dir / "patrol.yaml"
    config_path.write_text(
        CONFIG.format(
            skills=REPO / "configs" / "skills", scene=scene, queries=queries
        ),
        encoding="utf-8",
    )

    store = Path.home() / ".parcel" / "parcel_memory.sqlite3"
    owner_before = sha256_file(store) if store.is_file() else None

    socket_path = Path(f"/tmp/parcel-move1-patrol-{os.getpid()}.sock")
    process, handle = start_simulator(
        config_path=config_path,
        socket_path=socket_path,
        log_path=out_dir / "simulator.log",
        static_city=False,
    )
    seen_frames: set[str] = set()
    stats = {"frames": 0, "expired": 0, "detections": 0, "observed": 0, "refused": 0}
    # In-memory only: this card never opens the owner's store, and never
    # declares a map store path, so C-2's refusal gate keeps it ephemeral.
    provenance = WriterProvenance(
        session_id=f"move1-{stamp}",
        seat="patrol",
        detector_name="camera_ingress",
        scene_id=args.scene,
    )
    semantic_map = OnlineSemanticMap(provenance=provenance)

    try:
        runtime = build_runtime(config_path, socket_path, use_llm=False)
        runtime.start()
        try:

            def sense_provider(elapsed: float):
                return sense_from_snapshot(runtime.snapshot(), elapsed_s=elapsed)

            def submit(command) -> bool:
                try:
                    runtime.submit_motion(
                        "voice",
                        VelocityCommand(
                            vx=command.vx, vy=command.vy, vyaw=command.vyaw
                        ),
                    )
                except Exception:  # noqa: BLE001
                    return False
                return True

            def map_probe() -> MapGrowthSample:
                for frame in runtime.camera_detection_frame_slice(256):
                    if frame.frame_id in seen_frames:
                        continue
                    seen_frames.add(frame.frame_id)
                    stats["frames"] += 1
                    if getattr(frame, "expired_at_publish", False):
                        stats["expired"] += 1
                    stats["detections"] += len(frame.detections)
                    semantic_map.note_frame(queries=tuple(frame.queries or ()))
                    for observation in observations_from_frame(
                        frame,
                        visit_id=f"move1-{stamp}",
                        provenance=provenance,
                        require_fresh=False,
                    ):
                        if not isinstance(observation, MapObservation):
                            continue
                        outcome = semantic_map.observe(observation)
                        stats["observed"] += 1
                        if not outcome.persisted:
                            stats["refused"] += 1
                entries = semantic_map.entries()
                return MapGrowthSample(
                    t_s=0.0,
                    entries=len(entries),
                    labels=tuple(sorted({entry.label for entry in entries})),
                    frames_seen=stats["frames"],
                    detections_seen=stats["detections"],
                )

            runner = PatrolRunner(
                scene=args.scene,
                sense_provider=sense_provider,
                submit=submit,
                map_probe=map_probe,
                limits=PatrolLimits(budget_s=args.budget),
            )
            report = runner.run()
            final_snapshot = runtime.snapshot()
        finally:
            runtime.close()
    finally:
        returncode = stop_simulator(process, handle, socket_path)

    owner_after = sha256_file(store) if store.is_file() else None
    entries = semantic_map.entries()
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "repo_head": subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "scene": str(scene),
        "scene_sha256": sha256_file(scene),
        "simulator_returncode": returncode,
        "query_vocabulary": list(batch),
        "map_sweep_vocabulary": list(DEFAULT_MAP_SWEEP_VOCABULARY),
        "stream_stats": stats,
        "owner_store": {
            "sha256_before": owner_before,
            "sha256_after": owner_after,
            "unchanged": owner_before == owner_after,
        },
        "final_collision_flag": bool(final_snapshot.get("collision")),
        "map_entries": [
            {
                "label": entry.label,
                "surface_x": round(float(entry.surface_x), 4),
                "surface_y": round(float(entry.surface_y), 4),
                "evidence_frames": entry.evidence_frames,
                "detection_count": entry.detection_count,
                "status": entry.status,
                "hygiene_note": entry.hygiene_note,
                "provenance": {
                    "session_id": entry.provenance.session_id,
                    "seat": entry.provenance.seat,
                    "detector_name": entry.provenance.detector_name,
                    "scene_id": entry.provenance.scene_id,
                },
            }
            for entry in entries
        ],
        "report": report.as_dict(),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    headline = {
        key: payload["report"][key]
        for key in (
            "path_length_m",
            "net_displacement_m",
            "elapsed_s",
            "stopped_reason",
            "reasons",
            "collision_ticks",
            "submitted",
            "refused",
            "map_entries_final",
            "map_labels_final",
        )
    }
    headline["stream_stats"] = stats
    print(json.dumps(headline, indent=2))
    print(f"\nwrote {out_dir}/summary.json")


if __name__ == "__main__":
    main()
